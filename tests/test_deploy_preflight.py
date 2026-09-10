import importlib.util
from pathlib import Path
import os
import uuid

import pytest


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path('scripts') / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config():
    return dict(DEPLOYMENT_MODE='invite_beta', SITE_URL='https://fonts.test', SUPABASE_URL='https://project.supabase.co', SUPABASE_ANON_KEY='anonkey', SUPABASE_SERVICE_ROLE_KEY='servicekey', DATABASE_URL='postgresql://user:password@db/fonts', INTERNAL_API_KEY='x'*48, WORKER_API_BASE_URL='http://api:8000', PROCESS_JOBS_INLINE='0')


def test_preflight_failclosed_and_no_secret_echo():
    check = script('deploy_preflight').check_config
    assert check({})
    good = config()
    assert check(good) == []
    bad = {**good, 'PROCESS_JOBS_INLINE': '1', 'BILLING_ENABLED': 'true', 'SITE_URL': 'http://fonts.test', 'INTERNAL_API_KEY': 'secret'}
    errors = check(bad)
    assert len(errors) == 4
    assert 'secret' not in '\n'.join(errors)
    assert check({**good, 'JOB_TIMEOUT_SECONDS': 'nan'})
    assert check({**good, 'SUPABASE_URL': 'https://YOUR_PROJECT.supabase.co'})


def test_migrations_atomic_checksummed_and_repeatable(tmp_path):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL must name a disposable test database')
    import psycopg
    from psycopg.conninfo import make_conninfo
    schema = 'migration_test_' + uuid.uuid4().hex
    with psycopg.connect(url) as conn:
        conn.execute(f'create schema {schema}')
    scoped = make_conninfo(url, options=f'-csearch_path={schema}')
    migrate = script('migrate').migrate
    try:
        (tmp_path / '0001.sql').write_text('create table example(id int primary key);')
        with pytest.raises(RuntimeError, match='ledger'):
            migrate(scoped, check=True, directory=tmp_path)
        assert migrate(scoped, directory=tmp_path) == ['0001.sql']
        assert migrate(scoped, directory=tmp_path) == []
        assert migrate(scoped, check=True, directory=tmp_path) == []
        (tmp_path / '0002.sql').write_text('create table broken(id int); select missing_column;')
        with pytest.raises(psycopg.Error):
            migrate(scoped, directory=tmp_path)
        with psycopg.connect(scoped) as conn:
            assert conn.execute("select to_regclass('broken')").fetchone()[0] is None
            assert conn.execute('select count(*) from handwrite_schema_migrations').fetchone()[0] == 1
        (tmp_path / '0002.sql').unlink()
        (tmp_path / '0001.sql').write_text('select 1;')
        with pytest.raises(RuntimeError, match='checksum'):
            migrate(scoped, directory=tmp_path)
    finally:
        with psycopg.connect(url) as conn:
            conn.execute(f'drop schema {schema} cascade')
