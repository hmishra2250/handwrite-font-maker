"""Disposable real alpha API + leased worker for Playwright; never deploy this fixture."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from http.server import ThreadingHTTPServer


def _port_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError as exc:
        raise SystemExit(f'{name} must be an integer TCP port, got {raw!r}') from exc
    if not (1 <= port <= 65535):
        raise SystemExit(f'{name} must be between 1 and 65535, got {port}')
    return port


def main():
    api_port = _port_from_env('ALPHA_E2E_API_PORT', 8007)
    with tempfile.TemporaryDirectory(prefix='hfm-alpha-e2e-') as directory:
        root = Path(directory)
        os.environ.update({
            'DEPLOYMENT_MODE': 'private_alpha', 'ALPHA_DATABASE_PATH': str(root / 'alpha.sqlite3'),
            'LOCAL_OBJECT_ROOT': str(root / 'objects'), 'INTERNAL_API_KEY': 'e2e-only-internal-secret-do-not-deploy-123456',
            'PROCESS_JOBS_INLINE': '0', 'BILLING_ENABLED': 'false',
            'DAILY_UPLOAD_LIMIT': '300', 'DAILY_UPLOAD_BYTES_LIMIT': str(500 * 1024 * 1024),
            'DAILY_PREVIEW_LIMIT': '200', 'DAILY_BUILD_LIMIT': '10', 'ACTIVE_JOB_LIMIT': '2',
            'JOB_TIMEOUT_SECONDS': '180', 'JOB_LEASE_SECONDS': '30',
        })
        for key in ('DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY'):
            os.environ.pop(key, None)
        if os.environ.get('ALPHA_E2E_ML') == '1':
            os.environ['HANDWRITE_EFFICIENTSAM_MODEL_DIR'] = str(Path(__file__).resolve().parents[1] / '.models' / 'efficientsam')
        from handwrite_font_maker.web.alpha_auth import AlphaAuthStore
        from handwrite_font_maker.web.sqlite_store import SQLiteTenantStore
        from handwrite_font_maker.web.server import Handler
        SQLiteTenantStore(os.environ['ALPHA_DATABASE_PATH']).ready_check()
        auth = AlphaAuthStore(os.environ['ALPHA_DATABASE_PATH'])
        for email in ('alpha@example.test', 'other@example.test'):
            auth.provision(email, 'e2e-test-password-only-1234')
        Handler.object_root = root / 'objects'
        worker = subprocess.Popen([sys.executable, '-m', 'handwrite_font_maker.web.worker_loop'], start_new_session=True)
        server = ThreadingHTTPServer(('127.0.0.1', api_port), Handler)
        def stop(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            os.killpg(worker.pid, signal.SIGTERM)
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(worker.pid, signal.SIGKILL)
                worker.wait()


if __name__ == '__main__':
    main()
