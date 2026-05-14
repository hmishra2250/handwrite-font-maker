from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .api import get_job
from .contracts import FontRequest, InputPhoto, MAX_UPLOAD_BYTES, new_job_id, retention_expires_at, is_safe_font_name, is_supported_image
from .job_store import JobRecord, JsonJobStore, PostgresJobStore
from .supabase_store import LocalObjectStore, SupabaseStorage
from .worker import process_job


def _json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('content-type', 'application/json')
    handler.send_header('content-length', str(len(body)))
    handler.send_header('access-control-allow-origin', '*')
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    store_path = Path('/tmp/jobs.json')
    object_root = Path('/tmp/objects')

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == '/healthz':
            _json(self, 200, {'ok': True, 'service': 'handwrite-font-api'})
            return
        if parsed.path.startswith('/jobs/'):
            job_id = unquote(parsed.path.removeprefix('/jobs/'))
            job = get_job(self.store_path, job_id)
            _json(self, 404 if job is None else 200, {'error': {'code': 'JOB_EXPIRED', 'message': 'Job not found.'}} if job is None else job)
            return
        if parsed.path.startswith('/objects/'):
            object_key = unquote(parsed.path.removeprefix('/objects/'))
            self._serve_object(object_key)
            return
        _json(self, 404, {'error': {'code': 'INTERNAL_ERROR', 'message': 'Not found.'}})

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith('/objects/'):
            object_key = unquote(parsed.path.removeprefix('/objects/'))
            self._store_object(object_key)
            return
        _json(self, 404, {'error': {'code': 'INTERNAL_ERROR', 'message': 'Not found.'}})

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight for local-mode cross-origin requests."""
        self.send_response(204)
        self.send_header('access-control-allow-origin', '*')
        self.send_header('access-control-allow-methods', 'GET, POST, PUT, OPTIONS')
        self.send_header('access-control-allow-headers', 'content-type')
        self.send_header('access-control-max-age', '86400')
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._read_json()
        if parsed.path in {'/api/uploads', '/uploads'}:
            self._create_upload(body)
            return
        if parsed.path == '/jobs':
            self._create_job(body)
            return
        _json(self, 404, {'error': {'code': 'INTERNAL_ERROR', 'message': 'Not found.'}})

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get('content-length', '0'))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode('utf-8'))

    def _store_object(self, object_key: str) -> None:
        """Accept raw file bytes via PUT and store to the local object root."""
        length = int(self.headers.get('content-length', '0'))
        if length <= 0:
            _json(self, 400, {'error': {'code': 'UPLOAD_OBJECT_MISSING', 'message': 'Empty body.'}})
            return
        if length > MAX_UPLOAD_BYTES:
            _json(self, 413, {'error': {'code': 'UPLOAD_OBJECT_TOO_LARGE', 'message': 'Upload is too large.'}})
            return
        data = self.rfile.read(length)
        store = LocalObjectStore(self.object_root)
        target = store._path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        _json(self, 200, {'ok': True, 'objectKey': object_key, 'sizeBytes': len(data)})

    def _serve_object(self, object_key: str) -> None:
        """Serve a file from the local object root."""
        import mimetypes
        store = LocalObjectStore(self.object_root)
        try:
            path = store._path(object_key)
        except ValueError:
            _json(self, 400, {'error': {'code': 'INTERNAL_ERROR', 'message': 'Invalid object key.'}})
            return
        if not path.exists():
            _json(self, 404, {'error': {'code': 'UPLOAD_OBJECT_MISSING', 'message': 'Object not found.'}})
            return
        content_type = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        body = path.read_bytes()
        self.send_response(200)
        self.send_header('content-type', content_type)
        self.send_header('content-length', str(len(body)))
        self.send_header('access-control-allow-origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _create_upload(self, body: dict[str, object]) -> None:
        filename = str(body.get('filename') or 'upload.jpg')
        content_type = str(body.get('contentType') or '')
        size_bytes = int(body.get('sizeBytes') or 0)
        if size_bytes > MAX_UPLOAD_BYTES:
            _json(self, 413, {'error': {'code': 'UPLOAD_OBJECT_TOO_LARGE', 'message': 'Upload is too large.'}})
            return
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
        object_key = f'jobs/{new_job_id()}/input/original.{ext}'
        obj_store = _object_store(self.object_root)
        if isinstance(obj_store, SupabaseStorage):
            upload_url = obj_store.signed_upload_url(object_key)
            mode = 'live'
        else:
            # Local mode: the Next.js proxy will construct the real PUT URL,
            # so we only need to return the objectKey.  The uploadUrl here is
            # a placeholder the proxy ignores.
            upload_url = f'local://upload/{object_key}'
            mode = 'local'
        _json(self, 200, {'mode': mode, 'uploadUrl': upload_url, 'method': 'PUT', 'objectKey': object_key, 'expiresAt': retention_expires_at(1), 'maxUploadBytes': MAX_UPLOAD_BYTES, 'contentType': content_type})

    def _create_job(self, body: dict[str, object]) -> None:
        input_photo = body.get('inputPhoto') or {}
        font = body.get('font') or {}
        if not isinstance(input_photo, dict) or not isinstance(font, dict):
            _json(self, 400, {'error': {'code': 'UPLOAD_OBJECT_MISSING', 'message': 'inputPhoto and font are required.'}})
            return
        try:
            job = _create_job_record(self.store_path, input_photo=input_photo, font=font)
        except ValueError as exc:
            _json(self, 400, {'error': {'code': str(exc), 'message': str(exc)}})
            return
        _start_inline_processing(job.id, self.store_path, self.object_root)
        _json(self, 202, job.as_response())


def _job_store(store_path: Path):
    database_url = os.environ.get("DATABASE_URL")
    return PostgresJobStore(database_url) if database_url else JsonJobStore(store_path)


def _object_store(object_root: Path):
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return SupabaseStorage()
    return LocalObjectStore(object_root)


def _create_job_record(store_path: Path, *, input_photo: dict[str, object], font: dict[str, object]) -> JobRecord:
    object_key = str(input_photo.get("objectKey") or "")
    content_type = str(input_photo.get("contentType") or "")
    size_bytes = int(input_photo.get("sizeBytes") or 0)
    font_name = str(font.get("fontName") or "")
    if not object_key:
        raise ValueError("UPLOAD_OBJECT_MISSING")
    if not is_supported_image(content_type):
        raise ValueError("UNSUPPORTED_IMAGE_TYPE")
    if not is_safe_font_name(font_name):
        raise ValueError("FONT_METADATA_INVALID")
    return _job_store(store_path).create(
        InputPhoto(
            object_key=object_key,
            bucket=str(input_photo.get("bucket") or os.environ.get("SUPABASE_STORAGE_BUCKET") or "handwrite-font-jobs"),
            content_type=content_type,
            size_bytes=size_bytes,
        ),
        FontRequest(
            font_name=font_name,
            family_name=str(font.get("familyName") or font_name),
            style_name=str(font.get("styleName") or "Regular"),
        ),
    )


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
    port = int(os.environ.get('PORT', '8000'))
    Handler.store_path = Path(os.environ.get('JOB_STORE_PATH', '/tmp/jobs.json'))
    Handler.object_root = Path(os.environ.get('LOCAL_OBJECT_ROOT', '/tmp/objects'))
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    print(f'handwrite-font-api listening on :{port} with inline processing', flush=True)
    server.serve_forever()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
