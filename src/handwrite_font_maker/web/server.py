from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .api import create_job, get_job
from .contracts import MAX_UPLOAD_BYTES, new_job_id, retention_expires_at
from .supabase_store import SupabaseStorage


def _json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('content-type', 'application/json')
    handler.send_header('content-length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    store_path = Path('/tmp/jobs.json')

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
        _json(self, 404, {'error': {'code': 'INTERNAL_ERROR', 'message': 'Not found.'}})

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

    def _create_upload(self, body: dict[str, object]) -> None:
        filename = str(body.get('filename') or 'upload.jpg')
        content_type = str(body.get('contentType') or '')
        size_bytes = int(body.get('sizeBytes') or 0)
        if size_bytes > MAX_UPLOAD_BYTES:
            _json(self, 413, {'error': {'code': 'UPLOAD_OBJECT_TOO_LARGE', 'message': 'Upload is too large.'}})
            return
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
        object_key = f'jobs/{new_job_id()}/input/original.{ext}'
        try:
            upload_url = SupabaseStorage().signed_upload_url(object_key)
            mode = 'live'
        except RuntimeError:
            upload_url = f'local://upload/{object_key}'
            mode = 'demo'
        _json(self, 200, {'mode': mode, 'uploadUrl': upload_url, 'method': 'PUT', 'objectKey': object_key, 'expiresAt': retention_expires_at(1), 'maxUploadBytes': MAX_UPLOAD_BYTES, 'contentType': content_type})

    def _create_job(self, body: dict[str, object]) -> None:
        input_photo = body.get('inputPhoto') or {}
        font = body.get('font') or {}
        if not isinstance(input_photo, dict) or not isinstance(font, dict):
            _json(self, 400, {'error': {'code': 'UPLOAD_OBJECT_MISSING', 'message': 'inputPhoto and font are required.'}})
            return
        try:
            job = create_job(
                self.store_path,
                object_key=str(input_photo.get('objectKey') or ''),
                content_type=str(input_photo.get('contentType') or ''),
                size_bytes=int(input_photo.get('sizeBytes') or 0),
                font_name=str(font.get('fontName') or ''),
                family_name=str(font.get('familyName') or ''),
                style_name=str(font.get('styleName') or 'Regular'),
            )
        except ValueError as exc:
            _json(self, 400, {'error': {'code': str(exc), 'message': str(exc)}})
            return
        _json(self, 202, job)


def main() -> int:
    import os

    port = int(os.environ.get('PORT', '8000'))
    Handler.store_path = Path(os.environ.get('JOB_STORE_PATH', '/tmp/jobs.json'))
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    print(f'handwrite-font-api listening on :{port}', flush=True)
    server.serve_forever()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
