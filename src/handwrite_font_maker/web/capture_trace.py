"""Opt-in, host-local capture diagnostics. Never served as public objects.

Retain only bounded capture inputs and results, not HTTP headers or credentials.
The source remains in its existing owner-scoped storage; it is not duplicated.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import time
import uuid

log = logging.getLogger(__name__)


def _private_write(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(content)


class CaptureTrace:
    def __init__(self, directory: Path, owner: str, body: dict):
        self.started = time.monotonic()
        self.path = directory / str(uuid.uuid4())
        self.path.mkdir(parents=True, mode=0o700)
        photo = body.get('inputPhoto', {})
        request = {key: body[key] for key in ('rectangle', 'method', 'style', 'threshold', 'points', 'stage', 'context') if key in body}
        if 'context' in request:
            raw = request['context']
            allowed = {'character','baseline','threshold','invert','inkMaskMethod','foregroundMethod','foregroundStyle'}
            request['context'] = {k: v for k,v in raw.items() if k in allowed and isinstance(v, (str,int,float,bool)) and (not isinstance(v,str) or len(v) <= 128)} if isinstance(raw,dict) else None
        request['inputPhoto'] = {key: photo[key] for key in ('objectKey', 'bucket', 'contentType', 'sizeBytes') if key in photo}
        self.record = {
            'schemaVersion': 1, 'captureId': self.path.name,
            'ownerHash': hashlib.sha256(owner.encode()).hexdigest(),
            'createdAtUnix': time.time(), 'state': 'processing', 'request': request,
        }
        self._save()

    def _save(self):
        _private_write(self.path / 'record.json', json.dumps(self.record, indent=2).encode())

    def source(self, path: Path):
        try:
            self.record['sourceSha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            self._save()
        except OSError:
            log.warning('Could not fingerprint capture source')

    def response(self, status: int, payload: object):
        try:
            if not isinstance(payload, dict):
                return
            result = {key: payload[key] for key in ('method', 'modelId', 'width', 'height', 'warnings', 'error') if key in payload}
            data_url = payload.get('maskDataUrl', '')
            if isinstance(data_url, str) and data_url.startswith('data:image/png;base64,'):
                mask = base64.b64decode(data_url.split(',', 1)[1], validate=True)
                _private_write(self.path / 'mask.png', mask)
                result['maskFile'] = 'mask.png'
                result['maskSha256'] = hashlib.sha256(mask).hexdigest()
            if isinstance(payload.get('candidates'), list):
                result['candidates'] = []
                for index, candidate in enumerate(payload['candidates']):
                    entry = {key: candidate[key] for key in ('id','label','method','polarity','width','height','warnings','provenance') if key in candidate}
                    for field, extension in (('maskDataUrl','png'), ('svgDataUrl','svg')):
                        encoded = candidate.get(field, '')
                        if isinstance(encoded, str) and ';base64,' in encoded:
                            data = base64.b64decode(encoded.split(',',1)[1], validate=True)
                            name = f'candidate-{index}.{extension}'
                            _private_write(self.path / name, data)
                            entry[field.replace('DataUrl','File')] = name
                    result['candidates'].append(entry)
                result['failures'] = payload.get('failures', [])
            self.record.update(state='succeeded' if status < 400 else 'failed', httpStatus=status,
                               durationMs=round((time.monotonic() - self.started) * 1000), result=result)
            self._save()
        except (OSError, ValueError):
            log.warning('Could not save local capture response diagnostics')


def start_capture_trace(owner: str, body: dict) -> CaptureTrace | None:
    configured = os.environ.get('HANDWRITE_CAPTURE_DIAGNOSTICS_DIR')
    if not configured:
        return None
    try:
        directory = Path(configured)
        if not directory.is_absolute():
            raise ValueError('Diagnostic directory must be absolute')
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # This is deliberately a private local debug surface, not shared storage.
        if directory.stat().st_mode & 0o077:
            raise ValueError('Diagnostic directory must have mode 0700')
        # Bound retention to 24h, swept when another capture starts. No source deletion.
        for record in directory.glob('*/record.json'):
            if record.stat().st_mtime < time.time() - 86400:
                for name in ('mask.png', 'record.json', *(p.name for p in record.parent.glob('candidate-*.*'))):
                    (record.parent / name).unlink(missing_ok=True)
                record.parent.rmdir()
        return CaptureTrace(directory, owner, body)
    except (OSError, ValueError):
        log.warning('Could not start local capture diagnostics')
        return None
