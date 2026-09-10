import importlib.util
from pathlib import Path


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path('scripts') / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_env():
    return {
        'DEPLOYMENT_MODE': 'private_alpha',
        'SITE_URL': 'http://localhost:3000',
        'WORKER_API_BASE_URL': 'http://api:8000',
        'INTERNAL_API_KEY': 'x' * 48,
        'ALPHA_DATABASE_PATH': '/data/alpha.sqlite3',
        'LOCAL_OBJECT_ROOT': '/data/objects',
        'PROCESS_JOBS_INLINE': '0',
        'BILLING_ENABLED': '0',
        'DAILY_UPLOAD_LIMIT': '300',
        'DAILY_UPLOAD_BYTES_LIMIT': '524288000',
        'DAILY_PREVIEW_LIMIT': '200',
        'DAILY_BUILD_LIMIT': '10',
        'JOB_TIMEOUT_SECONDS': '1200',
    }


def test_alpha_preflight_accepts_compose_shape():
    check = script('alpha_preflight').check_config
    assert check(valid_env()) == []
    assert check({**valid_env(), 'SITE_URL': 'https://fonts.example.com'}) == []


def test_alpha_preflight_rejects_cloud_or_paid_credentials_without_echoing_values():
    check = script('alpha_preflight').check_config
    bad = {
        **valid_env(),
        'DATABASE_URL': 'postgresql://user:supersecret@db/fonts',
        'SUPABASE_URL': 'https://project.supabase.co',
        'STRIPE_SECRET_KEY': 'sk_live_supersecret',
        'BILLING_ENABLED': 'true',
    }
    errors = check(bad)
    assert len(errors) >= 4
    rendered = '\n'.join(errors)
    assert 'supersecret' not in rendered
    assert 'sk_live' not in rendered


def test_alpha_preflight_fails_closed_for_public_http_inline_and_weak_key():
    check = script('alpha_preflight').check_config
    errors = check({
        **valid_env(),
        'SITE_URL': 'http://fonts.example.com',
        'INTERNAL_API_KEY': 'short-secret',
        'PROCESS_JOBS_INLINE': '1',
    })
    assert any('SITE_URL' in error for error in errors)
    assert any('INTERNAL_API_KEY' in error for error in errors)
    assert any('PROCESS_JOBS_INLINE' in error for error in errors)


def test_alpha_preflight_parses_dotenv_without_shell_expansion(tmp_path):
    preflight = script('alpha_preflight')
    env_file = tmp_path / '.env.alpha'
    env_file.write_text('''\n# comment\nexport DEPLOYMENT_MODE=private_alpha\nSITE_URL="http://localhost:3000"\nWORKER_API_BASE_URL=http://api:8000\nINTERNAL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\nALPHA_DATABASE_PATH=/data/alpha.sqlite3\nLOCAL_OBJECT_ROOT=/data/objects # inline comment\nPROCESS_JOBS_INLINE=0\nBILLING_ENABLED=0\nLITERAL='$HOME/not-expanded'\n''')
    parsed = preflight.parse_env_file(env_file)
    assert parsed['SITE_URL'] == 'http://localhost:3000'
    assert parsed['LOCAL_OBJECT_ROOT'] == '/data/objects'
    assert parsed['LITERAL'] == '$HOME/not-expanded'
    assert preflight.check_config(parsed) == []


def test_alpha_dev_localizes_container_defaults_for_host_processes(monkeypatch):
    preflight = script('alpha_preflight')
    import sys
    monkeypatch.syspath_prepend(str(Path('scripts').resolve()))
    alpha_dev = script('alpha_dev')
    env = alpha_dev.localize_container_defaults(valid_env())
    assert env['ALPHA_DATABASE_PATH'].endswith('/.alpha/alpha.sqlite3')
    assert env['LOCAL_OBJECT_ROOT'].endswith('/.alpha/objects')
    assert env['WORKER_API_BASE_URL'] == 'http://127.0.0.1:8000'
    assert preflight.check_config({**env, 'WORKER_API_BASE_URL': 'http://api:8000'}) == []


def test_alpha_preflight_rejects_unsupported_model_variant():
    check = script('alpha_preflight').check_config
    errors = check({**valid_env(), 'HANDWRITE_SEGMENTATION_VARIANT': 'quantized'})
    assert any('HANDWRITE_SEGMENTATION_VARIANT' in error for error in errors)
    assert check({**valid_env(), 'HANDWRITE_SEGMENTATION_VARIANT': 'int8', 'HANDWRITE_MODEL_DIR': '/models/slimsam'}) == []


def test_alpha_preflight_check_paths_localizes_docker_defaults(tmp_path):
    preflight = script('alpha_preflight')
    env = preflight.localize_container_paths_for_host(valid_env(), root=tmp_path)
    assert env['ALPHA_DATABASE_PATH'] == str((tmp_path / '.alpha' / 'alpha.sqlite3').resolve())
    assert env['LOCAL_OBJECT_ROOT'] == str((tmp_path / '.alpha' / 'objects').resolve())
    assert preflight.check_config(valid_env()) == []
    assert preflight.check_paths(env) == []
