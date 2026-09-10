from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from handwrite_font_maker.web.alpha_auth import AlphaAuthStore
from handwrite_font_maker.web.security import SecurityError, authenticate_request, load_runtime_config
from handwrite_font_maker.web.server import Handler

PASSWORD = 'private-test-password-123!'


@pytest.fixture
def alpha_env(monkeypatch, tmp_path):
    for key in ('DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY'):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        'DEPLOYMENT_MODE': 'private_alpha', 'ALPHA_DATABASE_PATH': str(tmp_path / 'alpha.sqlite3'),
        'LOCAL_OBJECT_ROOT': str(tmp_path / 'objects'), 'INTERNAL_API_KEY': 's' * 40,
        'PROCESS_JOBS_INLINE': '0', 'BILLING_ENABLED': 'false',
    }.items():
        monkeypatch.setenv(key, value)
    return AlphaAuthStore(tmp_path / 'alpha.sqlite3')


def test_config_fail_closed(alpha_env, monkeypatch):
    assert load_runtime_config().auth_required
    monkeypatch.setenv('ALPHA_DATABASE_PATH', 'relative.sqlite3')
    with pytest.raises(RuntimeError, match='absolute ALPHA_DATABASE_PATH'):
        load_runtime_config()
    monkeypatch.setenv('ALPHA_DATABASE_PATH', alpha_env.path)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://not-alpha')
    with pytest.raises(RuntimeError, match='remove DATABASE_URL'):
        load_runtime_config()
    monkeypatch.delenv('DATABASE_URL')
    monkeypatch.setenv('BILLING_ENABLED', 'true')
    with pytest.raises(RuntimeError, match='Billing is unavailable'):
        load_runtime_config()


def test_password_and_token_never_stored_plaintext_and_restart(alpha_env):
    user = alpha_env.provision('Invited@Example.test', PASSWORD)
    session = alpha_env.login('invited@example.test', PASSWORD)
    assert session['user'] == user
    reopened = AlphaAuthStore(alpha_env.path)
    assert reopened.verify(session['accessToken']) == user
    with sqlite3.connect(alpha_env.path) as conn:
        salt, digest = conn.execute('SELECT salt,password_hash FROM alpha_users').fetchone()
        saved = conn.execute('SELECT token_hash FROM alpha_sessions').fetchone()[0]
    assert len(salt) == 16 and len(digest) == 64
    assert PASSWORD.encode() not in digest and saved != session['accessToken']
    headers = {'x-internal-api-key': 's' * 40, 'authorization': 'Bearer ' + session['accessToken']}
    assert authenticate_request(headers, load_runtime_config()).owner_id == user['id']
    with pytest.raises(SecurityError):
        authenticate_request({**headers, 'x-internal-api-key': 'bad'}, load_runtime_config())


def test_logout_expiry_disable_and_reset_revoke(alpha_env):
    alpha_env.provision('a@example.test', PASSWORD)
    first = alpha_env.login('a@example.test', PASSWORD)['accessToken']
    alpha_env.logout(first)
    with pytest.raises(SecurityError):
        alpha_env.verify(first)
    expired = alpha_env.login('a@example.test', PASSWORD)['accessToken']
    with sqlite3.connect(alpha_env.path) as conn:
        conn.execute('UPDATE alpha_sessions SET expires_at=?', (time.time() - 1,))
    with pytest.raises(SecurityError):
        alpha_env.verify(expired)
    active = alpha_env.login('a@example.test', PASSWORD)['accessToken']
    alpha_env.reset_password('a@example.test', PASSWORD + 'new')
    with pytest.raises(SecurityError):
        alpha_env.verify(active)
    with pytest.raises(SecurityError):
        alpha_env.login('a@example.test', PASSWORD)
    active = alpha_env.login('a@example.test', PASSWORD + 'new')['accessToken']
    alpha_env.disable('a@example.test')
    with pytest.raises(SecurityError):
        alpha_env.verify(active)
    with pytest.raises(SecurityError):
        alpha_env.login('a@example.test', PASSWORD + 'new')


def test_account_password_change_revokes_all_sessions(alpha_env):
    alpha_env.provision('a@example.test', PASSWORD)
    first = alpha_env.login('a@example.test', PASSWORD)['accessToken']
    second = alpha_env.login('a@example.test', PASSWORD)['accessToken']
    with pytest.raises(SecurityError):
        alpha_env.change_password(first, 'wrong', PASSWORD + 'new')
    with pytest.raises(ValueError):
        alpha_env.change_password(first, PASSWORD, 'short')
    alpha_env.change_password(first, PASSWORD, PASSWORD + 'new')
    for token in (first, second):
        with pytest.raises(SecurityError):
            alpha_env.verify(token)
    assert alpha_env.login('a@example.test', PASSWORD + 'new')['user']['email'] == 'a@example.test'


def test_rate_limit_atomic_persistent_and_unknown_accounts(alpha_env):
    # Use budget reservation directly to avoid burdening the test machine with 20 KDFs.
    def attempt(_):
        try:
            AlphaAuthStore(alpha_env.path)._rate_limit('unknown@example.test')
            return True
        except SecurityError as exc:
            assert exc.status == 429
            return False
    with ThreadPoolExecutor(max_workers=5) as pool:
        assert sum(pool.map(attempt, range(20))) == 10
    with pytest.raises(SecurityError) as exc:
        AlphaAuthStore(alpha_env.path).login('unknown@example.test', 'anything')
    assert exc.value.status == 429


@pytest.fixture
def alpha_http(alpha_env):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, method='GET', body=None, token=None, internal=True):
        headers = {'content-type': 'application/json'}
        if internal:
            headers['x-internal-api-key'] = 's' * 40
        if token:
            headers['authorization'] = 'Bearer ' + token
        req = Request(f'http://127.0.0.1:{server.server_port}{path}', data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        try:
            result = urlopen(req, timeout=15)
        except HTTPError as exc:
            result = exc
        with result:
            return result.status, json.load(result), result.headers
    yield request
    server.shutdown()
    server.server_close()
    thread.join()


def test_real_http_auth_account_and_checkout_gates(alpha_env, alpha_http):
    alpha_env.provision('a@example.test', PASSWORD)
    assert alpha_http('/auth/login', 'POST', {'email': 'a@example.test', 'password': PASSWORD}, internal=False)[0] == 401
    for path in ['/auth/session', '/account', '/projects', '/jobs/missing', '/objects/private.png']:
        assert alpha_http(path)[0] == 401
    assert alpha_http('/billing/checkout', 'POST', {'offerId': 'single'})[0] == 401
    assert alpha_http('/auth/login', 'POST', {'email': 'not-invited@example.test', 'password': PASSWORD})[0] == 401
    status, data, headers = alpha_http('/auth/login', 'POST', {'email': 'a@example.test', 'password': PASSWORD})
    assert status == 200 and headers['cache-control'] == 'no-store'
    token = data['accessToken']
    status, data, _ = alpha_http('/account', token=token)
    assert status == 200 and data['plan']['billingEnabled'] is False
    assert data['retention']['projectDays'] == 7
    status, data, _ = alpha_http('/billing/catalog')
    assert status == 200 and [o['priceCents'] for o in data['offers']] == [1200, 2900]
    status, data, _ = alpha_http('/billing/checkout', 'POST', {'offerId': 'single'}, token)
    assert status == 503 and data['error']['code'] == 'PAYMENT_NOT_CONFIGURED'
    assert alpha_http('/billing/checkout', 'POST', {'offerId': []}, token)[0] == 400
    assert alpha_http('/auth/session', 'POST', {}, token)[0] == 405
    assert alpha_http('/auth/logout', 'POST', {}, token)[0] == 200
    assert alpha_http('/account', token=token)[0] == 401


def test_database_and_sidecars_private_permissions(alpha_env):
    from pathlib import Path
    assert Path(alpha_env.path).stat().st_mode & 0o777 == 0o600
    with alpha_env.connect() as conn:
        conn.execute("INSERT INTO alpha_auth_attempts VALUES('permissions',0,0)")
        for suffix in ('-wal', '-shm'):
            path = Path(alpha_env.path + suffix)
            if path.exists():
                assert path.stat().st_mode & 0o777 == 0o600


def test_http_failed_account_cannot_globally_lock_out_others(alpha_env, alpha_http, monkeypatch):
    import hashlib
    from handwrite_font_maker.web import alpha_auth
    # Test admission behavior without running hundreds of expensive password KDFs.
    monkeypatch.setattr(alpha_auth, '_derive', lambda password, salt: hashlib.sha512(salt + password.encode()).digest())
    alpha_env.provision('legitimate@example.test', PASSWORD)
    for index in range(205):
        assert alpha_http('/auth/login', 'POST', {'email': f'unknown{index}@example.test', 'password': PASSWORD})[0] == 401
    for _ in range(12):
        status, session, _ = alpha_http('/auth/login', 'POST', {'email': 'legitimate@example.test', 'password': PASSWORD})
        assert status == 200  # Successful auth must not accumulate a lockout budget.
        assert alpha_http('/auth/logout', 'POST', {}, session['accessToken'])[0] == 200
    for _ in range(10):
        assert alpha_http('/auth/login', 'POST', {'email': 'target@example.test', 'password': PASSWORD})[0] == 401
    assert alpha_http('/auth/login', 'POST', {'email': 'target@example.test', 'password': PASSWORD})[0] == 429


def test_alpha_unexpected_error_logged_without_secrets(alpha_env, alpha_http, monkeypatch, caplog):
    def unavailable(*_):
        raise RuntimeError('secret-that-must-not-be-logged')
    monkeypatch.setattr(AlphaAuthStore, 'login', unavailable)
    status, data, _ = alpha_http('/auth/login', 'POST', {'email': 'a@example.test', 'password': PASSWORD})
    assert status == 503
    assert 'Reference:' in data['error']['message']
    assert 'RuntimeError' in caplog.text
    assert 'secret-that-must-not-be-logged' not in caplog.text
    assert PASSWORD not in caplog.text
