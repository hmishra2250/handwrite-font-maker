"""Checkpoint downloads are explicit, pinned and atomic; no real network in tests."""
import hashlib
from pathlib import Path

import pytest

import importlib.util

_spec = importlib.util.spec_from_file_location('install_segmentation_model', Path(__file__).resolve().parents[1] / 'scripts/install_segmentation_model.py')
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)


@pytest.mark.parametrize('model', ['slimsam', 'efficientsam'])
def test_verified_assets_are_reused_without_network(tmp_path, monkeypatch, model):
    if model == 'slimsam':
        backend = installer
    else:
        from handwrite_font_maker import efficient_segmentation as backend
    name = 'test.onnx'
    payload = b'verified-graph'
    monkeypatch.setitem(backend.MODEL_ASSETS, name, (len(payload), hashlib.sha256(payload).hexdigest()))
    target = tmp_path / name
    target.write_bytes(payload)
    # The SlimSAM verifier looks up the shared module asset dictionary.
    monkeypatch.setattr(installer.requests, 'get', lambda *a, **k: pytest.fail('Unexpected download'))
    assert installer.install_asset(name, tmp_path, model=model) == target


@pytest.mark.parametrize('valid', [True, False])
def test_download_is_hash_verified_before_atomic_replacement(tmp_path, monkeypatch, valid):
    payload = b'correct-model'
    name = 'test.onnx'
    monkeypatch.setitem(installer.MODEL_ASSETS, name, (len(payload), hashlib.sha256(payload).hexdigest()))
    target = tmp_path / name
    target.write_bytes(b'previous-corrupt-copy')
    urls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def raise_for_status(self): pass
        def iter_content(self, size): yield payload if valid else b'wrong'

    def download(url, **kwargs):
        urls.append(url)
        return Response()

    monkeypatch.setattr(installer.requests, 'get', download)
    if valid:
        assert installer.install_asset(name, tmp_path) == target
        assert target.read_bytes() == payload
    else:
        with pytest.raises(RuntimeError, match='integrity mismatch'):
            installer.install_asset(name, tmp_path)
        assert target.read_bytes() == b'previous-corrupt-copy'
    assert urls == [f'https://huggingface.co/{installer.MODEL_REPO}/resolve/{installer.MODEL_REVISION}/onnx/{name}']
    assert list(tmp_path.glob('*.part')) == []
