"""Real-database adversarial checks; Auth/Storage providers are not exercised here."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from handwrite_font_maker.web.contracts import FontRequest, InputPhoto, JobArtifact, JobStatus
from handwrite_font_maker.web.job_store import PostgresJobStore
from handwrite_font_maker.web.tenant_store import PostgresTenantStore, TenantLimits, WorkerArtifactRegistry, ObjectAccessError, OwnershipError, QuotaExceeded


@pytest.fixture
def context(monkeypatch):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL must name a disposable test database')
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('DEPLOYMENT_MODE', 'local')
    monkeypatch.setenv('SUPABASE_STORAGE_BUCKET', 'handwrite-font-jobs')
    jobs = PostgresJobStore(url)
    with jobs._connect() as conn:
        for path in sorted(Path('supabase/migrations').glob('*.sql')):
            conn.execute(path.read_text())
    tenant = PostgresTenantStore(url)
    owner = str(uuid.uuid4())
    tenant.ensure_tenant(owner)
    yield jobs, tenant, owner
    with jobs._connect() as conn:
        conn.execute('delete from jobs where owner_id=%s', (owner,))
        conn.execute('delete from tenants where owner_id=%s', (owner,))


def photo():
    return InputPhoto(object_key='edge/source.png', content_type='image/png', size_bytes=100)


def font():
    return FontRequest(font_name='Edges', family_name='Edges', style_name='Regular')


def test_staged_artifacts_hidden_until_fenced_success_and_old_attempt_rejected(context):
    jobs, tenants, owner = context
    record = jobs.create(photo(), font(), owner_id=owner)
    old = jobs.claim(record.id)
    registry = WorkerArtifactRegistry(jobs.database_url)
    key = f'jobs/{record.id}/attempts/{old.attempt_id}/artifacts/test.ttf'
    registry.register_attempt_artifact(old, object_key=key, content_type='font/ttf', size_bytes=40, kind='ttf')
    registry.mark_uploaded(old, object_key=key, size_bytes=40)
    with pytest.raises(ObjectAccessError):
        tenants.assert_object_access(owner_id=owner, bucket='handwrite-font-jobs', object_key=key)
    with jobs._connect() as conn:
        conn.execute("update jobs set lease_expires_at=now()-interval '1 second' where id=%s", (record.id,))
    current = jobs.claim(record.id)
    with pytest.raises(OwnershipError):
        registry.register_attempt_artifact(old, object_key=key+'-late', content_type='font/ttf', size_bytes=40)
    current_key = f'jobs/{record.id}/attempts/{current.attempt_id}/artifacts/test.ttf'
    registry.register_attempt_artifact(current, object_key=current_key, content_type='font/ttf', size_bytes=40)
    registry.mark_uploaded(current, object_key=current_key, size_bytes=40)
    current.status = JobStatus.SUCCEEDED
    current.artifacts = [JobArtifact(kind='ttf', label='Font', object_key=current_key, content_type='font/ttf', size_bytes=40)]
    jobs.save(current)
    tenants.assert_object_access(owner_id=owner, bucket='handwrite-font-jobs', object_key=current_key)
    with pytest.raises(ObjectAccessError):
        tenants.assert_object_access(owner_id=owner, bucket='handwrite-font-jobs', object_key=key)


def test_parallel_admission_enforces_daily_and_active_limits(context):
    jobs, tenant, owner = context
    limits = TenantLimits(daily_upload_limit=3, daily_upload_bytes_limit=1000, daily_preview_limit=3, daily_build_limit=10, active_job_limit=2)
    def upload(index):
        key = f'test/{owner}/{index}.png'
        try:
            tenant.register_upload(owner_id=owner, bucket='handwrite-font-jobs', object_key=key, content_type='image/png', size_bytes=100, limits=limits)
            tenant.mark_uploaded(owner_id=owner, bucket='handwrite-font-jobs', object_key=key)
            return key
        except QuotaExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = [key for key in pool.map(upload, range(8)) if key]
    assert len(accepted) == 3
    input_photo = InputPhoto(object_key=accepted[0], content_type='image/png', size_bytes=100)
    def build(_):
        try:
            return tenant.create_job(owner_id=owner, input_photo=input_photo, font=font(), capture=None, bucket='handwrite-font-jobs', limits=limits)
        except QuotaExceeded:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [job for job in pool.map(build, range(6)) if job]
    assert len(results) == 2


def test_rls_denies_untrusted_role_even_if_table_select_were_granted(context):
    jobs, tenants, owner = context
    jobs.create(photo(), font(), owner_id=owner)
    role = 'hfm_probe_' + uuid.uuid4().hex
    tables = ['jobs', 'job_warnings', 'job_artifacts', 'tenants', 'tenant_daily_usage', 'tenant_objects', 'tenant_object_job_refs']
    with jobs._connect() as conn:
        conn.execute(f'create role {role} nologin')
        conn.execute(f'grant usage on schema public to {role}')
        conn.execute(f'grant select on {", ".join(tables)} to {role}')
    try:
        with jobs._connect() as conn:
            conn.execute(f'set local role {role}')
            for table in tables:
                assert conn.execute(f'select count(*) from {table}').fetchone()[0] == 0
    finally:
        with jobs._connect() as conn:
            conn.execute(f'drop owned by {role}')
            conn.execute(f'drop role {role}')


def test_delete_failure_cannot_shorten_inflight_artifact_tombstone(context, monkeypatch):
    jobs, tenants, owner = context
    monkeypatch.setenv('JOB_TIMEOUT_SECONDS', '600')
    monkeypatch.setenv('STORAGE_DELETE_GRACE_SECONDS', '120')
    record = jobs.create(photo(), font(), owner_id=owner)
    claimed = jobs.claim(record.id)
    registry = WorkerArtifactRegistry(jobs.database_url)
    key = f'jobs/{record.id}/attempts/{claimed.attempt_id}/artifacts/late.ttf'
    registry.register_attempt_artifact(claimed, object_key=key, content_type='font/ttf', size_bytes=40)

    class Storage:
        fail = False
        calls = []
        def delete_object(self, object_key):
            self.calls.append(object_key)
            if self.fail and object_key == key:
                raise TimeoutError('temporary storage outage')

    storage = Storage()
    tenants.delete_job(owner_id=owner, job_id=record.id, object_store=storage)
    storage.fail = True
    tenants.cleanup_expired(object_store=storage, limit=10000)
    storage.fail = False
    with jobs._connect() as conn:
        conn.execute('update tenant_objects set next_delete_attempt_at=now() where object_key=%s', (key,))
    tenants.cleanup_expired(object_store=storage, limit=10000)
    with jobs._connect() as conn:
        status = conn.execute('select status from tenant_objects where bucket=%s and object_key=%s', ('handwrite-font-jobs', key)).fetchone()[0]
    assert status != 'deleted', 'a transient delete failure must not cancel the in-flight write grace window'
    with pytest.raises(ObjectAccessError):
        tenants.assert_object_access(owner_id=owner, bucket='handwrite-font-jobs', object_key=key)
