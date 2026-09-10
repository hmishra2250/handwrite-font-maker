import base64
import json
import os
from pathlib import Path

from handwrite_font_maker.web.capture_trace import start_capture_trace


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv('HANDWRITE_CAPTURE_DIAGNOSTICS_DIR', raising=False)
    assert start_capture_trace('user', {}) is None


def test_retains_exact_parameters_and_output_not_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv('HANDWRITE_CAPTURE_DIAGNOSTICS_DIR', str(tmp_path))
    body = {'inputPhoto': {'objectKey': 'tenants/owner/input.jpg', 'contentType': 'image/jpeg', 'sizeBytes': 100, 'secret': 'omit'},
            'rectangle': [.1, .2, .8, .9], 'method': 'grabcut', 'style': 'ink', 'threshold': 130,
            'points': [], 'password': 'omit', 'authorization': 'omit'}
    trace = start_capture_trace('private-owner', body)
    assert trace is not None
    initial = json.loads((trace.path / 'record.json').read_text())
    assert initial['state'] == 'processing'
    trace.response(200, {'method': 'grabcut', 'width': 1, 'height': 1, 'warnings': [],
                         'maskDataUrl': 'data:image/png;base64,' + base64.b64encode(b'png-test').decode()})
    data = json.loads((trace.path / 'record.json').read_text())
    assert data['request']['rectangle'] == body['rectangle']
    assert data['request']['threshold'] == 130
    assert data['state'] == 'succeeded'
    assert data['durationMs'] >= 0
    assert data['result']['maskFile'] == 'mask.png'
    assert (trace.path / 'mask.png').read_bytes() == b'png-test'
    assert 'omit' not in json.dumps(data)
    assert 'private-owner' not in json.dumps(data)
    assert (trace.path / 'record.json').stat().st_mode & 0o777 == 0o600


def test_errors_retained_and_trace_failure_is_nonfatal(monkeypatch, tmp_path):
    monkeypatch.setenv('HANDWRITE_CAPTURE_DIAGNOSTICS_DIR', str(tmp_path))
    trace = start_capture_trace('user', {})
    trace.response(503, {'error': {'code': 'MODEL_UNAVAILABLE'}})
    assert json.loads((trace.path / 'record.json').read_text())['state'] == 'failed'
    monkeypatch.setenv('HANDWRITE_CAPTURE_DIAGNOSTICS_DIR', 'relative/path')
    assert start_capture_trace('user', {}) is None


def test_expired_diagnostics_removed_but_not_source(monkeypatch, tmp_path):
    monkeypatch.setenv('HANDWRITE_CAPTURE_DIAGNOSTICS_DIR', str(tmp_path))
    trace = start_capture_trace('user', {})
    (trace.path / 'mask.png').write_bytes(b'old')
    os.utime(trace.path / 'record.json', (0, 0))
    assert start_capture_trace('user', {}) is not None
    assert not trace.path.exists()
