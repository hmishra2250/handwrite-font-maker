import json
import signal
from pathlib import Path

import pytest

from test_alpha_dev import script, valid_env_file


def test_mobile_requires_exact_https_tunnel_origin_and_private_alpha(tmp_path):
    mobile = script('alpha_mobile')
    env_file = valid_env_file(tmp_path)
    for bad in ('http://test.trycloudflare.com', 'https://test.trycloudflare.com/path', 'https://test.trycloudflare.com.evil.test', 'https://user@test.trycloudflare.com'):
        with pytest.raises(ValueError):
            mobile.mobile_environment(env_file, bad, 8000)
    env = mobile.mobile_environment(env_file, 'https://phone-test.trycloudflare.com', 8000)
    assert env['SITE_URL'] == 'https://phone-test.trycloudflare.com'
    assert env['WORKER_API_BASE_URL'] == 'http://127.0.0.1:8000'
    assert env['NODE_ENV'] == 'production'
    assert env['HANDWRITE_MOBILE_PREVIEW'] == '1'
    assert env['HANDWRITE_PHONE_PREVIEW'] == '0'
    env_file.write_text(env_file.read_text().replace('DEPLOYMENT_MODE=private_alpha', 'DEPLOYMENT_MODE=local'))
    with pytest.raises(ValueError, match='DEPLOYMENT_MODE'):
        mobile.mobile_environment(env_file, 'https://phone-test.trycloudflare.com', 8000)


def test_tunnel_parser_uses_announced_banner_only(tmp_path):
    mobile = script('alpha_mobile')
    log = tmp_path / 'tunnel.log'
    log.write_text('POST https://api.trycloudflare.com/tunnel\n| https://four-word-phone-test.trycloudflare.com |\n')
    class Running:
        def poll(self): return None
    assert mobile.wait_for_tunnel(Running(), log) == 'https://four-word-phone-test.trycloudflare.com'


def test_tunnel_failure_does_not_return_old_or_api_url(tmp_path):
    mobile = script('alpha_mobile')
    log = tmp_path / 'tunnel.log'
    log.write_text('POST https://api.trycloudflare.com/tunnel failed\n')
    class Exited:
        def poll(self): return 1
    with pytest.raises(RuntimeError, match='exited'):
        mobile.wait_for_tunnel(Exited(), log)


def test_invalid_auth_never_starts_tunnel(tmp_path, monkeypatch):
    mobile = script('alpha_mobile')
    monkeypatch.setattr(mobile, 'ROOT', tmp_path)
    calls = []
    monkeypatch.setattr(mobile.subprocess, 'Popen', lambda *a, **k: calls.append(a))
    env_file = valid_env_file(tmp_path)
    env_file.write_text(env_file.read_text().replace('DEPLOYMENT_MODE=private_alpha', 'DEPLOYMENT_MODE=local'))
    assert mobile.main(['--env-file', str(env_file)]) == 1
    assert calls == []


def test_mobile_stops_tunnel_on_build_failure(tmp_path, monkeypatch):
    mobile = script('alpha_mobile')
    monkeypatch.setattr(mobile, 'ROOT', tmp_path)
    class Ready:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Proc:
        def poll(self): return None
        def wait(self): return 1
    tunnel, build = Proc(), Proc()
    monkeypatch.setattr(mobile.shutil, 'which', lambda _: '/verified/cloudflared')
    monkeypatch.setattr(mobile.urllib.request, 'urlopen', lambda *a, **kw: Ready())
    monkeypatch.setattr(mobile.subprocess, 'Popen', lambda *a, **kw: tunnel)
    monkeypatch.setattr(mobile, 'wait_for_tunnel', lambda *a: 'https://phone-test.trycloudflare.com')
    spawned = []
    def spawn(name, command, **kwargs):
        spawned.append((name, command, kwargs))
        return build
    monkeypatch.setattr(mobile.alpha_dev, 'spawn', spawn)
    stopped = []
    monkeypatch.setattr(mobile.alpha_dev, 'stop', lambda processes: stopped.extend(processes))
    assert mobile.main(['--env-file', str(valid_env_file(tmp_path)), '--port', '30991']) == 1
    assert spawned[0][1] == ['npm', 'run', 'build']
    assert spawned[0][2]['env']['NODE_ENV'] == 'production'
    assert stopped == [tunnel, build]
    assert not (tmp_path / '.alpha/mobile-preview.json').exists()
