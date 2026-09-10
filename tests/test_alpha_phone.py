import argparse
import os
from pathlib import Path

import pytest

from test_alpha_dev import script, valid_env_file


def test_phone_preview_accepts_only_private_ipv4():
    phone = script('alpha_phone')
    for address in ('192.168.1.3', '10.0.0.2', '172.16.0.2'):
        assert phone.private_ipv4(address) == address
    for address in ('0.0.0.0', '127.0.0.1', '8.8.8.8', 'example.com', '::1', '169.254.1.1'):
        with pytest.raises(argparse.ArgumentTypeError):
            phone.private_ipv4(address)


def test_phone_env_sets_exact_https_origin_and_keeps_api_loopback(tmp_path):
    phone = script('alpha_phone')
    env = phone.phone_environment(valid_env_file(tmp_path), '192.168.1.3', 3443, 8000)
    assert env['SITE_URL'] == 'https://192.168.1.3:3443'
    assert env['WORKER_API_BASE_URL'] == 'http://127.0.0.1:8000'
    assert env['DEPLOYMENT_MODE'] == 'private_alpha'
    assert env['HANDWRITE_PHONE_PREVIEW'] == '1'
    assert env['INTERNAL_API_KEY'] == 'x' * 48


def test_phone_prepare_never_overwrites_or_installs_trust(tmp_path, monkeypatch):
    phone = script('alpha_phone')
    directory = tmp_path / 'tls'
    directory.mkdir()
    (directory / 'ca.key').write_text('private existing key')
    calls = []
    monkeypatch.setattr(phone.subprocess, 'run', lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError, match='nothing was overwritten'):
        phone.prepare_certificate(directory, '192.168.1.3')
    assert (directory / 'ca.key').read_text() == 'private existing key'
    assert calls == []


def test_phone_prepare_generates_short_lived_ip_cert_without_trust_changes(tmp_path, monkeypatch):
    phone = script('alpha_phone')
    calls = []
    monkeypatch.setattr(phone.subprocess, 'run', lambda command, **kwargs: calls.append(command))
    old_umask = os.umask(0o022)
    try:
        phone.prepare_certificate(tmp_path / 'tls', '192.168.1.3')
        observed = os.umask(0o022)
        assert observed == 0o022
    finally:
        os.umask(old_umask)
    assert len(calls) == 4
    assert all(command[0] == 'openssl' for command in calls)
    assert '7' in calls[2]
    assert '30' in calls[0]
    assert 'subjectAltName=IP:192.168.1.3' in (tmp_path / 'tls/server.ext').read_text()
    assert not any('security' in command or 'add-trusted-cert' in command for command in calls)


def test_phone_launch_uses_isolated_https_web_and_existing_loopback_api(tmp_path, monkeypatch):
    phone = script('alpha_phone')
    tls = tmp_path / 'tls'
    tls.mkdir()
    (tls / 'server.crt').write_text('cert')
    (tls / 'server.key').write_text('key')
    commands = []
    monkeypatch.setattr(phone.subprocess, 'run', lambda command, **kwargs: commands.append(command))
    class Ready:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    urls = []
    monkeypatch.setattr(phone.urllib.request, 'urlopen', lambda url, **kwargs: (urls.append(url) or Ready()))
    monkeypatch.setattr(phone.os, 'chdir', lambda path: None)
    class Launched(Exception): pass
    def launch(binary, command, env):
        assert binary == 'npm'
        assert command[command.index('--hostname') + 1] == '192.168.1.3'
        assert '--experimental-https' in command
        assert env['SITE_URL'] == 'https://192.168.1.3:3443'
        assert env['HANDWRITE_PHONE_PREVIEW'] == '1'
        raise Launched()
    monkeypatch.setattr(phone.os, 'execvpe', launch)
    with pytest.raises(Launched):
        phone.main(['--host', '192.168.1.3', '--env-file', str(valid_env_file(tmp_path)), '--tls-dir', str(tls)])
    assert urls == ['http://127.0.0.1:8000/readyz']
    assert commands[0][-2:] == ['-checkip', '192.168.1.3']
    assert commands[1][-2:] == ['-checkend', '60']
