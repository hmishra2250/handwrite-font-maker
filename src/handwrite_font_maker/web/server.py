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

from ..segmentation import ModelUnavailableError, SegmentationBusyError
from .capture_trace import start_capture_trace
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
from .project_store import JsonProjectStore, PostgresProjectStore, ProjectStoreError
from .security import AuthContext, DeploymentMode, SecurityError, authenticate_request, load_runtime_config
from .supabase_store import LocalObjectStore, SupabaseStorage
from .tenant_store import ObjectAccessError, OwnershipError, PostgresTenantStore, QuotaExceeded, TenantLimits
from .worker import _validate_guided_mask, _validate_input_image, process_job


class RequestJsonError(ValueError):
    pass


_FOREGROUND_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}


def _cors_origin() -> str:
    try:
        config = load_runtime_config()
    except RuntimeError:
        return ""
    if config.auth_required:
        return os.environ.get("CORS_ALLOW_ORIGIN", "")
    return "*"


def _json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    trace = getattr(handler, "_capture_trace", None)
    if trace is not None:
        trace.response(status, payload)
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("cache-control", "no-store")
    handler.send_header("content-length", str(len(body)))
    origin = _cors_origin()
    if origin:
        handler.send_header("access-control-allow-origin", origin)
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
    project_store_path = Path("/tmp/projects.json")
    object_root = Path("/tmp/objects")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        from .alpha_http import handle_alpha_route
        if handle_alpha_route(self, parsed.path, "GET"):
            return
        if parsed.path == "/healthz":
            _json(self, 200, {"ok": True, "service": "handwrite-font-api"})
            return
        if parsed.path == "/readyz":
            self._readyz()
            return
        if parsed.path in {"/projects", "/api/projects"}:
            self._list_projects()
            return
        if parsed.path.startswith("/projects/") or parsed.path.startswith("/api/projects/"):
            project_id = _path_id(parsed.path, "/projects/") if parsed.path.startswith("/projects/") else _path_id(parsed.path, "/api/projects/")
            self._get_project(project_id)
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

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        from .alpha_http import handle_alpha_route
        if handle_alpha_route(self, parsed.path, "DELETE"):
            return
        if parsed.path.startswith("/jobs/"):
            job_id = unquote(parsed.path.removeprefix("/jobs/"))
            self._delete_job(job_id)
            return
        if parsed.path.startswith("/projects/") or parsed.path.startswith("/api/projects/"):
            project_id = _path_id(parsed.path, "/projects/") if parsed.path.startswith("/projects/") else _path_id(parsed.path, "/api/projects/")
            self._delete_project(project_id)
            return
        _error(self, 404, HardErrorCode.INTERNAL_ERROR, "Not found.")

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        from .alpha_http import handle_alpha_route
        if handle_alpha_route(self, parsed.path, "PUT"):
            return
        if parsed.path.startswith("/objects/"):
            object_key = unquote(parsed.path.removeprefix("/objects/"))
            self._store_object(object_key)
            return
        if parsed.path.startswith("/projects/") or parsed.path.startswith("/api/projects/"):
            project_id = _path_id(parsed.path, "/projects/") if parsed.path.startswith("/projects/") else _path_id(parsed.path, "/api/projects/")
            try:
                self._request_context()
            except SecurityError as exc:
                _error(self, exc.status, exc.code, exc.message)
                return
            try:
                body = self._read_json()
            except RequestJsonError as exc:
                _error(self, 400, HardErrorCode.INTERNAL_ERROR, str(exc))
                return
            self._update_project(project_id, body)
            return
        _error(self, 404, HardErrorCode.INTERNAL_ERROR, "Not found.")

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight for local-mode cross-origin requests."""
        self.send_response(204)
        origin = _cors_origin()
        if origin:
            self.send_header("access-control-allow-origin", origin)
        self.send_header("access-control-allow-methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type, authorization, x-internal-api-key")
        self.send_header("access-control-max-age", "86400")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        from .alpha_http import handle_alpha_route
        if handle_alpha_route(self, parsed.path, "POST"):
            return
        if parsed.path in {"/api/uploads", "/uploads", "/jobs", "/projects", "/api/projects", "/feedback", "/events", "/api/capture/page", "/capture/page", "/api/capture/foreground", "/capture/foreground", "/api/capture/candidates", "/capture/candidates"}:
            try:
                self._request_context()
            except SecurityError as exc:
                _error(self, exc.status, exc.code, exc.message)
                return
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
        if parsed.path in {"/projects", "/api/projects"}:
            self._create_project(body)
            return
        if parsed.path in {"/feedback", "/events"}:
            from .feedback_store import handle_feedback

            handle_feedback(self, body, event=(parsed.path == "/events"))
            return
        if parsed.path in {"/api/capture/page", "/capture/page"}:
            self._capture_page(body)
            return
        if parsed.path in {"/api/capture/candidates", "/capture/candidates"}:
            from .candidate_http import handle_candidates
            handle_candidates(self, body)
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

    def _request_context(self) -> tuple[object, AuthContext]:
        cached = getattr(self, "_cached_request_context", None)
        if cached is not None:
            return cached
        try:
            config = load_runtime_config()
        except RuntimeError as exc:
            raise SecurityError(503, "CONFIGURATION_ERROR", str(exc)) from exc
        try:
            auth = authenticate_request(self.headers, config)
        except SecurityError:
            raise
        self._cached_request_context = (config, auth)
        return config, auth

    def _readyz(self) -> None:
        try:
            config = load_runtime_config()
            checks: dict[str, object] = {
                "mode": config.mode.value,
                "inlineProcessing": config.process_jobs_inline,
                "storage": "supabase" if config.auth_required and config.mode != DeploymentMode.PRIVATE_ALPHA else "local",
            }
            if config.mode == DeploymentMode.PRIVATE_ALPHA:
                from .sqlite_store import SQLiteTenantStore
                from .alpha_auth import AlphaAuthStore
                AlphaAuthStore(config.alpha_database_path)
                schema = SQLiteTenantStore(config.alpha_database_path).ready_check()
                checks["schema"] = {key: schema[key] for key in ("ok", "store", "missingTables") if key in schema}
                ok = bool(schema.get("ok"))
            elif config.database_url:
                schema = PostgresTenantStore(config.database_url).ready_check()
                checks["schema"] = schema
                ok = bool(schema.get("ok"))
            else:
                checks["schema"] = {"ok": True, "store": "json"}
                ok = True
            _json(self, 200 if ok else 503, {"ok": ok, "checks": checks})
        except Exception as exc:
            _ = exc
            _json(self, 503, {"ok": False, "error": {"code": "CONFIGURATION_ERROR", "message": "Readiness check failed."}})

    def _store_object(self, object_key: str) -> None:
        """Accept raw file bytes via PUT and store to the local object root."""
        try:
            config, auth = self._request_context()
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
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
        if getattr(config, "auth_required", False):
            try:
                tenant_store = _tenant_store(config)
                registered = tenant_store.claim_upload_intent(owner_id=auth.owner_id, bucket=config.storage_bucket, object_key=object_key)
                if registered.content_type != content_type or registered.size_bytes != len(data):
                    raise ValueError(HardErrorCode.UPLOAD_OBJECT_MISSING.value)
                with tempfile.TemporaryDirectory(prefix="proxy_upload_") as tmp:
                    target = Path(tmp) / "upload"
                    target.write_bytes(data)
                    _validate_input_image(target, InputPhoto(object_key=object_key, content_type=content_type, size_bytes=len(data), bucket=config.storage_bucket))
                    _object_store(self.object_root).upload_from_path(object_key, target, content_type)
                tenant_store.mark_uploaded(owner_id=auth.owner_id, bucket=config.storage_bucket, object_key=object_key, size_bytes=len(data))
            except ObjectAccessError as exc:
                _error(self, exc.status, exc.code, exc.message)
                return
            except ValueError as exc:
                _error(self, _status_for_code(str(exc)), str(exc))
                return
            except Exception:
                _error(self, 502, HardErrorCode.ARTIFACT_PUBLISH_FAILED, "Object upload failed.")
                return
        else:
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
            _mark_local_upload(auth, object_key, len(data))
        _json(self, 200, {"ok": True, "objectKey": object_key, "sizeBytes": len(data)})

    def _serve_object(self, object_key: str) -> None:
        """Serve a file from the local object root."""
        import mimetypes

        try:
            config, auth = self._request_context()
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        store = _object_store(self.object_root) if getattr(config, "auth_required", False) else LocalObjectStore(self.object_root)
        try:
            if getattr(config, "auth_required", False):
                _tenant_store(config).assert_object_access(owner_id=auth.owner_id, bucket=config.storage_bucket, object_key=object_key)
                with tempfile.TemporaryDirectory(prefix="proxy_object_") as tmp:
                    path = Path(tmp) / "object"
                    store.download_to_path(object_key, path)
                    body = path.read_bytes()
            else:
                path = store._path(object_key)
                if not path.exists():
                    _error(self, 404, HardErrorCode.UPLOAD_OBJECT_MISSING, "Object not found.")
                    return
                body = path.read_bytes()
        except ValueError:
            _error(self, 400, HardErrorCode.INTERNAL_ERROR, "Invalid object key.")
            return
        except ObjectAccessError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        except Exception:
            _error(self, 502, HardErrorCode.UPLOAD_OBJECT_MISSING, "Object download failed.")
            return
        content_type = mimetypes.guess_type(object_key)[0] or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("cache-control", "private, no-store")
        self.send_header("content-length", str(len(body)))
        origin = _cors_origin()
        if origin:
            self.send_header("access-control-allow-origin", origin)
        self.end_headers()
        self.wfile.write(body)

    def _create_upload(self, body: dict[str, object]) -> None:
        try:
            config, auth = self._request_context()
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
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
        owner_prefix = f"tenants/{auth.owner_id}/" if getattr(config, "auth_required", False) else ""
        object_key = f"{owner_prefix}jobs/{new_job_id()}/input/original.{ext}"
        if getattr(config, "auth_required", False):
            upload_url = f"/objects/{object_key}"
            mode = "proxy"
        else:
            upload_url = f"local://upload/{object_key}"
            mode = "local"
        expires_at = retention_expires_at(24)
        if getattr(config, "auth_required", False):
            try:
                _tenant_store(config).register_upload(
                    owner_id=auth.owner_id,
                    bucket=config.storage_bucket,
                    object_key=object_key,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    limits=TenantLimits.from_config(config),
                    expires_at=expires_at,
                )
            except QuotaExceeded as exc:
                _error(self, exc.status, exc.code, exc.message)
                return
        _json(self, 200, {"mode": mode, "uploadUrl": upload_url, "method": "PUT", "objectKey": object_key, "expiresAt": expires_at, "maxUploadBytes": MAX_UPLOAD_BYTES, "contentType": content_type})

    def _create_job(self, body: dict[str, object]) -> None:
        try:
            config, auth = self._request_context()
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        input_photo_raw = body.get("inputPhoto")
        font = body.get("font")
        if not isinstance(font, dict):
            _error(self, 400, HardErrorCode.FONT_METADATA_INVALID, "font is required.")
            return
        try:
            input_photo = parse_input_photo(input_photo_raw)
            input_photo = _server_bound_input_photo(input_photo, config)
            capture = parse_capture_config(body.get("capture"), outer_input_photo=input_photo)
            capture = _server_bound_capture(capture, config)
            _authorize_capture_objects(config, auth, input_photo, capture)
            _validate_capture_objects(input_photo, capture, _object_store(self.object_root))
            job = _create_job_record(self.store_path, input_photo=input_photo, font=font, capture=capture, config=config, owner_id=auth.owner_id)
        except ValueError as exc:
            _error(self, _status_for_code(str(exc)), str(exc))
            return
        except (QuotaExceeded, ObjectAccessError) as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        _start_inline_processing(job.id, self.store_path, self.object_root)
        _json(self, 202, job.as_response())

    def _get_job(self, job_id: str) -> None:
        try:
            config, auth = self._request_context()
            if getattr(config, "auth_required", False):
                _tenant_store(config).authorize_job(owner_id=auth.owner_id, job_id=job_id)
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        except OwnershipError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        job = _job_store(self.store_path).get(job_id)
        if job is None:
            _error(self, 404, HardErrorCode.JOB_EXPIRED, "Job not found.")
            return
        object_store = _object_store(self.object_root)
        _json(self, 200, job.as_response(object_store.signed_download_url))

    def _delete_job(self, job_id: str) -> None:
        try:
            config, auth = self._request_context()
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        if getattr(config, "auth_required", False):
            try:
                result = _tenant_store(config).delete_job(owner_id=auth.owner_id, job_id=job_id, object_store=_object_store(self.object_root))
            except (OwnershipError, ObjectAccessError) as exc:
                _error(self, exc.status, exc.code, exc.message)
                return
            _json(self, 200, {"ok": True, **result})
            return
        if _expire_local_job(self.store_path, job_id):
            _json(self, 200, {"ok": True, "deletedObjects": 0, "failedObjects": 0})
        else:
            _error(self, 404, HardErrorCode.JOB_EXPIRED, "Job not found.")

    def _list_projects(self) -> None:
        try:
            config, auth = self._request_context()
            projects = _project_store(config, self.project_store_path, self.object_root, self.store_path).list(owner_id=auth.owner_id)
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        except ProjectStoreError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        _json(self, 200, {"projects": projects})

    def _get_project(self, project_id: str) -> None:
        try:
            config, auth = self._request_context()
            project = _project_store(config, self.project_store_path, self.object_root, self.store_path).get(owner_id=auth.owner_id, project_id=project_id)
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        except ProjectStoreError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        _json(self, 200, project)

    def _create_project(self, body: dict[str, object]) -> None:
        try:
            config, auth = self._request_context()
            project = _project_store(config, self.project_store_path, self.object_root, self.store_path).create(owner_id=auth.owner_id, payload=body)
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        except (ProjectStoreError, ObjectAccessError, OwnershipError, QuotaExceeded) as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        _json(self, 201, project)

    def _update_project(self, project_id: str, body: dict[str, object]) -> None:
        try:
            config, auth = self._request_context()
            project = _project_store(config, self.project_store_path, self.object_root, self.store_path).update(owner_id=auth.owner_id, project_id=project_id, payload=body)
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        except (ProjectStoreError, ObjectAccessError, OwnershipError, QuotaExceeded) as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        _json(self, 200, project)

    def _delete_project(self, project_id: str) -> None:
        try:
            config, auth = self._request_context()
            result = _project_store(config, self.project_store_path, self.object_root, self.store_path).delete(owner_id=auth.owner_id, project_id=project_id, object_store=_object_store(self.object_root))
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        except (ProjectStoreError, ObjectAccessError, OwnershipError, QuotaExceeded) as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        _json(self, 200, {"ok": True, **result})

    def _capture_page(self, body: dict[str, object]) -> None:
        try:
            config, auth = self._request_context()
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        try:
            input_photo = parse_input_photo(body.get("inputPhoto"))
            input_photo = _server_bound_input_photo(input_photo, config)
            _authorize_capture_objects(config, auth, input_photo, None)
            _record_preview(config, auth)
        except ValueError as exc:
            _error(self, _status_for_code(str(exc)), str(exc))
            return
        except (QuotaExceeded, ObjectAccessError) as exc:
            _error(self, exc.status, exc.code, exc.message)
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
            self._run_capture_foreground(body)
        finally:
            self._capture_trace = None

    def _run_capture_foreground(self, body: dict[str, object]) -> None:
        try:
            config, auth = self._request_context()
        except SecurityError as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        try:
            input_photo = parse_input_photo(body.get("inputPhoto"))
            input_photo = _server_bound_input_photo(input_photo, config)
            _authorize_capture_objects(config, auth, input_photo, None)
            rectangle = _validate_normalized_rectangle(body.get("rectangle"))
            method, style, threshold = _validate_foreground_options(body)
            points = _validate_foreground_points(body.get("points"), rectangle=rectangle, method=method)
        except ValueError as exc:
            _error(self, _status_for_code(str(exc)), str(exc))
            return
        except (QuotaExceeded, ObjectAccessError) as exc:
            _error(self, exc.status, exc.code, exc.message)
            return
        self._capture_trace = start_capture_trace(auth.owner_id, body)
        foreground_slot = _foreground_slot()
        if not foreground_slot.acquire(blocking=False):
            _segmentation_error(self, "SEGMENTATION_BUSY", "Foreground capture is temporarily busy. Retry shortly.", retryable=True)
            return
        with tempfile.TemporaryDirectory(prefix="capture_foreground_") as tmp:
            image_path = Path(tmp) / "input"
            try:
                _record_preview(config, auth)
                object_store = _object_store(self.object_root)
                object_store.download_to_path(input_photo.object_key, image_path)
                _validate_input_image(image_path, input_photo)
                from ..rectify import load_bgr

                image_bgr = load_bgr(image_path)
                if self._capture_trace is not None:
                    self._capture_trace.source(image_path)
                cutout = _extract_foreground(
                    image_bgr,
                    rectangle,
                    method=method,
                    style=style,
                    threshold=threshold,
                    points=points,
                )
                mask, used_method, model_id, warnings = _serialize_cutout(cutout)
                data_url, width, height = _encode_mask_data_url(mask)
            except ModelUnavailableError:
                _segmentation_error(
                    self,
                    "MODEL_UNAVAILABLE",
                    "Segmentation model is not available. Choose method 'auto' or 'grabcut', "
                    "or install the configured model weights.",
                    retryable=False,
                )
                return
            except SegmentationBusyError:
                _segmentation_error(
                    self,
                    "SEGMENTATION_BUSY",
                    "Segmentation is temporarily busy. Retry shortly.",
                    retryable=True,
                )
                return
            except ValueError as exc:
                _foreground_value_error(self, exc)
                return
            except QuotaExceeded as exc:
                _error(self, exc.status, exc.code, exc.message)
                return
            except Exception as exc:
                _error(self, 422, HardErrorCode.GLYPH_EXTRACTION_FAILED, f"Could not extract foreground mask: {exc}")
                return
            finally:
                foreground_slot.release()
        _json(
            self,
            200,
            {
                "maskDataUrl": data_url,
                "width": width,
                "height": height,
                "method": used_method,
                "modelId": model_id,
                "warnings": warnings,
            },
        )


def _detect_page_corners(image_bgr):
    from ..rectify import detect_page_corners

    return detect_page_corners(image_bgr)


def _extract_foreground(
    image_bgr,
    rectangle,
    *,
    method: str = "auto",
    style: str = "silhouette",
    threshold: int = 128,
    points: list[dict[str, float | int]] | None = None,
):
    from ..segmentation import segment_image

    kwargs: dict[str, object] = {"method": method, "style": style, "threshold": threshold}
    if points is not None:
        kwargs["points"] = points
    return segment_image(image_bgr, rectangle, **kwargs)


def _validate_foreground_options(body: dict[str, object]) -> tuple[str, str, int]:
    method = body.get("method", "auto")
    if not isinstance(method, str) or method not in {"auto", "model", "grabcut", "box-model"}:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    style = body.get("style", "silhouette")
    if not isinstance(style, str) or style not in {"silhouette", "ink"}:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    threshold = body.get("threshold", 128)
    if isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold <= 254:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    return method, style, threshold


def _validate_foreground_points(
    raw: object,
    *,
    rectangle: tuple[float, float, float, float],
    method: str,
) -> list[dict[str, float | int]] | None:
    if raw is None:
        if method == "model":
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        return None
    if not isinstance(raw, list) or len(raw) > 16:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    if method == "box-model" and len(raw) > 0:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)

    left, top, right, bottom = rectangle
    parsed: list[dict[str, float | int]] = []
    positive_count = 0
    for point in raw:
        if not isinstance(point, dict) or set(point) != {"x", "y", "label"}:
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        x_raw = point.get("x")
        y_raw = point.get("y")
        label_raw = point.get("label")
        if (
            isinstance(x_raw, bool)
            or isinstance(y_raw, bool)
            or not isinstance(x_raw, int | float)
            or not isinstance(y_raw, int | float)
        ):
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        x = float(x_raw)
        y = float(y_raw)
        if not math.isfinite(x) or not math.isfinite(y) or not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        if isinstance(label_raw, bool) or not isinstance(label_raw, int) or label_raw not in {0, 1}:
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        if label_raw == 1:
            positive_count += 1
            if not (left <= x <= right and top <= y <= bottom):
                raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        parsed.append({"x": x, "y": y, "label": label_raw})

    if method == "model" and positive_count == 0:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    return parsed


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


def _serialize_cutout(cutout) -> tuple[object, str, str | None, list[str]]:
    if hasattr(cutout, "mask"):
        mask = cutout.mask
        method = getattr(cutout, "method", None)
        model_id = getattr(cutout, "model_id", None)
        warnings_raw = getattr(cutout, "warnings", ())
    else:
        mask = cutout
        method = "grabcut"
        model_id = None
        warnings_raw = ()
    if method not in {"threshold", "grabcut", "slimsam", "efficientsam"}:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    if model_id is not None and not isinstance(model_id, str):
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    if warnings_raw is None:
        warnings: list[str] = []
    elif isinstance(warnings_raw, (list, tuple)):
        warnings = [str(warning) for warning in warnings_raw]
    else:
        warnings = [str(warnings_raw)]
    return mask, method, model_id, warnings


def _foreground_value_error(handler: BaseHTTPRequestHandler, exc: ValueError) -> None:
    code = str(exc)
    if code in {error.value for error in HardErrorCode}:
        _error(handler, _status_for_code(code), code)
        return
    _error(handler, 422, HardErrorCode.GLYPH_EXTRACTION_FAILED, code)


def _segmentation_error(handler: BaseHTTPRequestHandler, code: str, message: str, *, retryable: bool) -> None:
    _json(handler, 503, {"error": {"code": code, "message": message, "retryable": retryable}})


def _foreground_slot() -> threading.BoundedSemaphore:
    raw = os.environ.get("CAPTURE_FOREGROUND_CONCURRENCY", "1")
    try:
        limit = max(1, int(raw))
    except ValueError:
        limit = 1
    slot = _FOREGROUND_SEMAPHORES.get(limit)
    if slot is None:
        slot = threading.BoundedSemaphore(limit)
        _FOREGROUND_SEMAPHORES[limit] = slot
    return slot


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


def _path_id(path: str, prefix: str) -> str:
    return unquote(path.removeprefix(prefix))


def _project_store(config, path: Path, object_root: Path, job_store_path: Path):
    if getattr(config, "mode", None) == DeploymentMode.PRIVATE_ALPHA:
        from .sqlite_store import SQLiteProjectStore
        return SQLiteProjectStore(config.alpha_database_path, bucket=config.storage_bucket)
    if getattr(config, "auth_required", False):
        return PostgresProjectStore(config.database_url, bucket=config.storage_bucket)
    return JsonProjectStore(path, object_root=object_root, job_store_path=job_store_path)


def _job_store(store_path: Path):
    if os.environ.get("DEPLOYMENT_MODE", "").strip().lower() == "private_alpha":
        from .sqlite_store import SQLiteJobStore
        return SQLiteJobStore(os.environ.get("ALPHA_DATABASE_PATH"))
    database_url = os.environ.get("DATABASE_URL")
    return PostgresJobStore(database_url) if database_url else JsonJobStore(store_path)


def _object_store(object_root: Path):
    config = load_runtime_config()
    if config.auth_required and config.mode != DeploymentMode.PRIVATE_ALPHA:
        return SupabaseStorage(bucket=config.storage_bucket)
    return LocalObjectStore(object_root)


def _tenant_store(config):
    if getattr(config, "mode", None) == DeploymentMode.PRIVATE_ALPHA:
        from .sqlite_store import SQLiteTenantStore
        return SQLiteTenantStore(config.alpha_database_path)
    return PostgresTenantStore(config.database_url)


def _create_job_record(store_path: Path, *, input_photo: InputPhoto, font: dict[str, object], capture=None, config=None, owner_id: str | None = None) -> JobRecord:
    font_name = font.get("fontName")
    if not isinstance(font_name, str) or not is_safe_font_name(font_name):
        raise ValueError(HardErrorCode.FONT_METADATA_INVALID.value)
    family_name = font.get("familyName")
    style_name = font.get("styleName")
    font_request = FontRequest(
        font_name=font_name,
        family_name=family_name if isinstance(family_name, str) and family_name else font_name,
        style_name=style_name if isinstance(style_name, str) and style_name else "Regular",
    )
    if config is not None and getattr(config, "auth_required", False):
        return _tenant_store(config).create_job(
            owner_id=owner_id or "",
            input_photo=input_photo,
            font=font_request,
            capture=capture,
            bucket=config.storage_bucket,
            limits=TenantLimits.from_config(config),
        )
    # Local pseudo-identity is not a PostgreSQL tenant UUID or artifact registry owner.
    return _job_store(store_path).create(input_photo, font_request, capture=capture, owner_id=None)


def _server_bound_input_photo(input_photo: InputPhoto, config) -> InputPhoto:
    if not getattr(config, "auth_required", False):
        return input_photo
    return InputPhoto(
        object_key=input_photo.object_key,
        content_type=input_photo.content_type,
        size_bytes=input_photo.size_bytes,
        bucket=config.storage_bucket,
        sha256=input_photo.sha256,
    )


def _server_bound_capture(capture, config):
    if not getattr(config, "auth_required", False) or getattr(capture, "mode", None) != "guided":
        return capture
    from .contracts import GuidedCapture, GuidedGlyphCapture

    return GuidedCapture(
        glyphs=tuple(
            GuidedGlyphCapture(
                char=glyph.char,
                input_photo=_server_bound_input_photo(glyph.input_photo, config),
                baseline=glyph.baseline,
                scale=glyph.scale,
                spacing=glyph.spacing,
            )
            for glyph in capture.glyphs
        )
    )


def _authorize_capture_objects(config, auth: AuthContext, input_photo: InputPhoto, capture) -> None:
    if not getattr(config, "auth_required", False):
        return
    store = _tenant_store(config)
    bucket = config.storage_bucket
    if getattr(capture, "mode", None) == "guided":
        for glyph in capture.glyphs:
            store.assert_object_access(owner_id=auth.owner_id, bucket=bucket, object_key=glyph.input_photo.object_key)
        return
    store.assert_object_access(owner_id=auth.owner_id, bucket=bucket, object_key=input_photo.object_key)


def _record_preview(config, auth: AuthContext) -> None:
    if getattr(config, "auth_required", False):
        _tenant_store(config).record_preview(owner_id=auth.owner_id, limits=TenantLimits.from_config(config))


def _mark_local_upload(auth: AuthContext, object_key: str, size_bytes: int) -> None:
    _ = (auth, object_key, size_bytes)


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
    claim = getattr(store, "claim", None)
    job = claim(job_id) if callable(claim) else store.get(job_id)
    if job is None:
        return
    process_job(job, store, _object_store(object_root))


def main() -> int:
    config = load_runtime_config()
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    Handler.store_path = Path(os.environ.get("JOB_STORE_PATH", "/tmp/jobs.json"))
    Handler.project_store_path = Path(os.environ.get("PROJECT_STORE_PATH", str(Handler.store_path.with_name("projects.json"))))
    Handler.object_root = Path(os.environ.get("LOCAL_OBJECT_ROOT", "/tmp/objects"))
    server = ThreadingHTTPServer((host, port), Handler)
    processing = "inline processing" if config.process_jobs_inline else "external worker processing"
    print(f"handwrite-font-api listening on {host}:{port} with {processing}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
