from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .contracts import (
    FontRequest,
    HardErrorCode,
    MAX_UPLOAD_BYTES,
    InputPhoto,
    is_safe_font_name,
    is_supported_image,
    new_job_id,
    parse_capture_config,
    parse_input_photo,
    retention_expires_at,
    validate_normalized_corners,
)
from .job_store import JobRecord, JsonJobStore, PostgresJobStore
from .supabase_store import LocalObjectStore, SupabaseStorage
from .worker import _validate_guided_mask, _validate_input_image, process_job


class RequestJsonError(ValueError):
    pass


def _json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(body)))
    handler.send_header("access-control-allow-origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: BaseHTTPRequestHandler, status: int, code: HardErrorCode | str, message: str | None = None) -> None:
    from .contracts import hard_error_message

    code_value = code.value if isinstance(code, HardErrorCode) else str(code)
    try:
        hard_code = HardErrorCode(code_value)
        default = hard_error_message(hard_code)
    except ValueError:
        default = "Invalid request."
    _json(handler, status, {"error": {"code": code_value, "message": message or default}})


class Handler(BaseHTTPRequestHandler):
    store_path = Path("/tmp/jobs.json")
    object_root = Path("/tmp/objects")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            _json(self, 200, {"ok": True, "service": "handwrite-font-api"})
            return
        if parsed.path.startswith("/jobs/"):
            job_id = unquote(parsed.path.removeprefix("/jobs/"))
            self._get_job(job_id)
            return
        if parsed.path.startswith("/objects/"):
            object_key = unquote(parsed.path.removeprefix("/objects/"))
            self._serve_object(object_key)
            return
        _error(self, 404, HardErrorCode.INTERNAL_ERROR, "Not found.")

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/objects/"):
            object_key = unquote(parsed.path.removeprefix("/objects/"))
            self._store_object(object_key)
            return
        _error(self, 404, HardErrorCode.INTERNAL_ERROR, "Not found.")

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight for local-mode cross-origin requests."""
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, PUT, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("access-control-max-age", "86400")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            body = self._read_json()
        except RequestJsonError as exc:
            _error(self, 400, HardErrorCode.INTERNAL_ERROR, str(exc))
            return
        if parsed.path in {"/api/uploads", "/uploads"}:
            self._create_upload(body)
            return
        if parsed.path == "/jobs":
            self._create_job(body)
            return
        if parsed.path in {"/api/capture/page", "/capture/page"}:
            self._capture_page(body)
            return
        if parsed.path in {"/api/capture/foreground", "/capture/foreground"}:
            self._capture_foreground(body)
            return
        _error(self, 404, HardErrorCode.INTERNAL_ERROR, "Not found.")

    def _read_json(self) -> dict[str, object]:
        length_header = self.headers.get("content-length", "0")
        try:
            length = int(length_header)
        except ValueError as exc:
            raise RequestJsonError("Content-Length must be an integer.") from exc
        if length < 0 or length > MAX_UPLOAD_BYTES:
            raise RequestJsonError("JSON body is too large.")
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            raise RequestJsonError("Malformed JSON body.") from exc
        if not isinstance(payload, dict):
            raise RequestJsonError("JSON body must be an object.")
        return payload

    def _store_object(self, object_key: str) -> None:
        """Accept raw file bytes via PUT and store to the local object root."""
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError:
            _error(self, 400, HardErrorCode.UPLOAD_OBJECT_MISSING, "Content-Length must be an integer.")
            return
        content_type = self.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not is_supported_image(content_type):
            _error(self, 415, HardErrorCode.UNSUPPORTED_IMAGE_TYPE)
            return
        if length <= 0:
            _error(self, 400, HardErrorCode.UPLOAD_OBJECT_MISSING, "Empty body.")
            return
        if length > MAX_UPLOAD_BYTES:
            _error(self, 413, HardErrorCode.UPLOAD_OBJECT_TOO_LARGE, "Upload is too large.")
            return
        data = self.rfile.read(length)
        if len(data) != length:
            _error(self, 400, HardErrorCode.UPLOAD_OBJECT_MISSING, "Incomplete upload body.")
            return
        store = LocalObjectStore(self.object_root)
        try:
            target = store._path(object_key)
        except ValueError:
            _error(self, 400, HardErrorCode.UPLOAD_OBJECT_MISSING, "Invalid object key.")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        try:
            _validate_input_image(target, InputPhoto(object_key=object_key, content_type=content_type, size_bytes=len(data)))
        except ValueError as exc:
            target.unlink(missing_ok=True)
            _error(self, _status_for_code(str(exc)), str(exc))
            return
        _json(self, 200, {"ok": True, "objectKey": object_key, "sizeBytes": len(data)})

    def _serve_object(self, object_key: str) -> None:
        """Serve a file from the local object root."""
        import mimetypes

        store = LocalObjectStore(self.object_root)
        try:
            path = store._path(object_key)
        except ValueError:
            _error(self, 400, HardErrorCode.INTERNAL_ERROR, "Invalid object key.")
            return
        if not path.exists():
            _error(self, 404, HardErrorCode.UPLOAD_OBJECT_MISSING, "Object not found.")
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _create_upload(self, body: dict[str, object]) -> None:
        filename = body.get("filename")
        content_type = body.get("contentType")
        size_bytes = body.get("sizeBytes")
        if not isinstance(filename, str) or not filename or not isinstance(content_type, str) or not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
            _error(self, 400, HardErrorCode.UPLOAD_OBJECT_MISSING, "filename, contentType, and integer sizeBytes are required.")
            return
        if not is_supported_image(content_type):
            _error(self, 415, HardErrorCode.UNSUPPORTED_IMAGE_TYPE)
            return
        if size_bytes > MAX_UPLOAD_BYTES:
            _error(self, 413, HardErrorCode.UPLOAD_OBJECT_TOO_LARGE, "Upload is too large.")
            return
        raw_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
        ext = re.sub(r"[^a-z0-9]", "", raw_ext) or "jpg"
        if ext not in {"jpg", "jpeg", "png", "webp"}:
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(content_type, "jpg")
        object_key = f"jobs/{new_job_id()}/input/original.{ext}"
        obj_store = _object_store(self.object_root)
        if isinstance(obj_store, SupabaseStorage):
            upload_url = obj_store.signed_upload_url(object_key)
            mode = "live"
        else:
            upload_url = f"local://upload/{object_key}"
            mode = "local"
        _json(self, 200, {"mode": mode, "uploadUrl": upload_url, "method": "PUT", "objectKey": object_key, "expiresAt": retention_expires_at(1), "maxUploadBytes": MAX_UPLOAD_BYTES, "contentType": content_type})

    def _create_job(self, body: dict[str, object]) -> None:
        input_photo_raw = body.get("inputPhoto")
        font = body.get("font")
        if not isinstance(font, dict):
            _error(self, 400, HardErrorCode.FONT_METADATA_INVALID, "font is required.")
            return
        try:
            input_photo = parse_input_photo(input_photo_raw)
            capture = parse_capture_config(body.get("capture"), outer_input_photo=input_photo)
            _validate_capture_objects(input_photo, capture, _object_store(self.object_root))
            job = _create_job_record(self.store_path, input_photo=input_photo, font=font, capture=capture)
        except ValueError as exc:
            _error(self, _status_for_code(str(exc)), str(exc))
            return
        _start_inline_processing(job.id, self.store_path, self.object_root)
        _json(self, 202, job.as_response())

    def _get_job(self, job_id: str) -> None:
        job = _job_store(self.store_path).get(job_id)
        if job is None:
            _error(self, 404, HardErrorCode.JOB_EXPIRED, "Job not found.")
            return
        object_store = _object_store(self.object_root)
        _json(self, 200, job.as_response(object_store.signed_download_url))

    def _capture_page(self, body: dict[str, object]) -> None:
        try:
            input_photo = parse_input_photo(body.get("inputPhoto"))
        except ValueError as exc:
            _error(self, _status_for_code(str(exc)), str(exc))
            return
        with tempfile.TemporaryDirectory(prefix="capture_page_") as tmp:
            image_path = Path(tmp) / "input"
            try:
                object_store = _object_store(self.object_root)
                object_store.download_to_path(input_photo.object_key, image_path)
                _validate_input_image(image_path, input_photo)
                from ..rectify import load_bgr

                image_bgr = load_bgr(image_path)
                corners_px = _detect_page_corners(image_bgr)
                corners = _normalize_corners(corners_px, width=image_bgr.shape[1], height=image_bgr.shape[0])
            except ValueError as exc:
                _error(self, _status_for_code(str(exc)), str(exc))
                return
            except Exception as exc:
                _error(self, 422, HardErrorCode.MARKER_GEOMETRY_INVALID, f"Could not detect page corners: {exc}")
                return
        _json(self, 200, {"corners": [[x, y] for x, y in corners]})

    def _capture_foreground(self, body: dict[str, object]) -> None:
        try:
            input_photo = parse_input_photo(body.get("inputPhoto"))
            rectangle = _validate_normalized_rectangle(body.get("rectangle"))
        except ValueError as exc:
            _error(self, _status_for_code(str(exc)), str(exc))
            return
        with tempfile.TemporaryDirectory(prefix="capture_foreground_") as tmp:
            image_path = Path(tmp) / "input"
            try:
                object_store = _object_store(self.object_root)
                object_store.download_to_path(input_photo.object_key, image_path)
                _validate_input_image(image_path, input_photo)
                from ..rectify import load_bgr

                image_bgr = load_bgr(image_path)
                mask = _extract_foreground(image_bgr, rectangle)
                data_url, width, height = _encode_mask_data_url(mask)
            except ValueError as exc:
                _error(self, _status_for_code(str(exc)), str(exc))
                return
            except Exception as exc:
                _error(self, 422, HardErrorCode.GLYPH_EXTRACTION_FAILED, f"Could not extract foreground mask: {exc}")
                return
        _json(self, 200, {"maskDataUrl": data_url, "width": width, "height": height, "method": "grabcut"})


def _detect_page_corners(image_bgr):
    from ..rectify import detect_page_corners

    return detect_page_corners(image_bgr)


def _extract_foreground(image_bgr, rectangle):
    from ..foreground import extract_foreground

    return extract_foreground(image_bgr, rectangle)


def _validate_normalized_rectangle(raw: object) -> tuple[float, float, float, float]:
    if not isinstance(raw, list | tuple) or len(raw) != 4:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    values: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        number = float(value)
        if not math.isfinite(number) or number < 0.0 or number > 1.0:
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        values.append(number)
    left, top, right, bottom = values
    if right <= left or bottom <= top or (right - left) * (bottom - top) < 0.0001:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    return (left, top, right, bottom)


def _encode_mask_data_url(mask) -> tuple[str, int, int]:
    import numpy as np
    from PIL import Image

    array = np.asarray(mask)
    if array.ndim == 3:
        if array.shape[2] == 4:
            alpha = array[:, :, 3]
            if bool((alpha < 255).any()):
                raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
            array = array[:, :, :3].mean(axis=2).astype(np.uint8)
        elif array.shape[2] in {3, 1}:
            array = array[:, :, :3].mean(axis=2).astype(np.uint8)
        else:
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    if array.ndim != 2 or array.size == 0:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    height, width = array.shape
    if width <= 0 or height <= 0 or max(width, height) > 1024 or width * height > 1024 * 1024:
        raise ValueError(HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value)
    foreground = array < 128
    coverage = float(foreground.mean())
    if coverage <= 0.0001 or coverage >= 0.98:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    image = Image.fromarray(array, mode="L")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}", width, height


def _normalize_corners(corners_px: object, *, width: int, height: int):
    if width <= 0 or height <= 0:
        raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)
    corners = []
    for point in corners_px:  # type: ignore[union-attr]
        x, y = point
        corners.append([float(x) / float(width), float(y) / float(height)])
    return validate_normalized_corners(corners)


def _job_store(store_path: Path):
    database_url = os.environ.get("DATABASE_URL")
    return PostgresJobStore(database_url) if database_url else JsonJobStore(store_path)


def _object_store(object_root: Path):
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return SupabaseStorage()
    return LocalObjectStore(object_root)


def _create_job_record(store_path: Path, *, input_photo: InputPhoto, font: dict[str, object], capture=None) -> JobRecord:
    font_name = font.get("fontName")
    if not isinstance(font_name, str) or not is_safe_font_name(font_name):
        raise ValueError(HardErrorCode.FONT_METADATA_INVALID.value)
    family_name = font.get("familyName")
    style_name = font.get("styleName")
    return _job_store(store_path).create(
        input_photo,
        FontRequest(
            font_name=font_name,
            family_name=family_name if isinstance(family_name, str) and family_name else font_name,
            style_name=style_name if isinstance(style_name, str) and style_name else "Regular",
        ),
        capture=capture,
    )


def _validate_capture_objects(input_photo: InputPhoto, capture, object_store) -> None:
    with tempfile.TemporaryDirectory(prefix="job_validate_") as tmp:
        tmp_path = Path(tmp)
        if getattr(capture, "mode", None) == "guided":
            total = 0
            for index, glyph in enumerate(capture.glyphs):
                glyph_path = tmp_path / f"glyph_{index}.png"
                object_store.download_to_path(glyph.input_photo.object_key, glyph_path)
                total += _validate_guided_mask(glyph_path, glyph.input_photo)
                if total > MAX_UPLOAD_BYTES:
                    raise ValueError(HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value)
            return
        image_path = tmp_path / "input"
        object_store.download_to_path(input_photo.object_key, image_path)
        _validate_input_image(image_path, input_photo)


def _status_for_code(code: str) -> int:
    if code == HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value:
        return 413
    if code == HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value:
        return 415
    if code in {HardErrorCode.MARKER_GEOMETRY_INVALID.value, HardErrorCode.GLYPH_EXTRACTION_FAILED.value}:
        return 422
    return 400


def _start_inline_processing(job_id: str, store_path: Path, object_root: Path) -> None:
    if os.environ.get("PROCESS_JOBS_INLINE", "1").lower() in {"0", "false", "no", "off"}:
        return
    thread = threading.Thread(target=_process_job_by_id, args=(job_id, store_path, object_root), daemon=True)
    thread.start()


def _process_job_by_id(job_id: str, store_path: Path, object_root: Path) -> None:
    store = _job_store(store_path)
    job = store.get(job_id)
    if job is None:
        return
    process_job(job, store, _object_store(object_root))


def main() -> int:
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    Handler.store_path = Path(os.environ.get("JOB_STORE_PATH", "/tmp/jobs.json"))
    Handler.object_root = Path(os.environ.get("LOCAL_OBJECT_ROOT", "/tmp/objects"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"handwrite-font-api listening on {host}:{port} with inline processing", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
