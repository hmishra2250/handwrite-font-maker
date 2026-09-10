"""Real PG checks (set TEST_DATABASE_URL to an isolated disposable database)."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from handwrite_font_maker.web.contracts import FontRequest, InputPhoto, JobArtifact, JobStatus
from handwrite_font_maker.web.job_store import PostgresJobStore, LeaseLostError


@pytest.fixture
def store():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL must name a disposable test database")
    result = PostgresJobStore(url)
    with result._connect() as conn:
        for migration in sorted(Path("supabase/migrations").glob("000[123]*.sql")):
            conn.execute(migration.read_text())
    yield result


@pytest.fixture
def job(store):
    result = store.create(InputPhoto(object_key="test/source.png", content_type="image/png", size_bytes=100), FontRequest(font_name="LeaseTest", family_name="Lease Test", style_name="Regular"), owner_id=str(uuid.uuid4()))
    yield result
    with store._connect() as conn:
        conn.execute("delete from jobs where id=%s", (result.id,))


def test_concurrent_claim_fenced_finish(store, job):
    with ThreadPoolExecutor(max_workers=5) as pool:
        claims = list(pool.map(lambda _: store.claim(job.id), range(5)))
    claimed = [claim for claim in claims if claim]
    assert len(claimed) == 1
    attempt = claimed[0]
    assert attempt.owner_id == job.owner_id
    assert attempt.attempt_count == 1 and attempt.attempt_id and attempt.lease_owner
    with pytest.raises(LeaseLostError):
        store.save(job)
    assert store.heartbeat(attempt)
    attempt.status = JobStatus.SUCCEEDED
    attempt.artifacts = [JobArtifact(kind="ttf", label="Font", object_key=f"jobs/{job.id}/attempts/{attempt.attempt_id}/font.ttf", content_type="font/ttf", size_bytes=42)]
    store.save(attempt)
    assert store.get(job.id).status == JobStatus.SUCCEEDED
    assert len(store.get(job.id).artifacts) == 1
    assert not store.heartbeat(attempt)
    with pytest.raises(LeaseLostError):
        store.save(attempt)


def test_stale_claim_cannot_replace_new_attempt_or_artifacts(store, job):
    old = store.claim(job.id)
    with store._connect() as conn:
        conn.execute("update jobs set lease_expires_at=now()-interval '1 second' where id=%s", (job.id,))
    assert not store.heartbeat(old)
    current = store.claim(job.id)
    assert current.attempt_count == 2 and current.attempt_id != old.attempt_id
    with pytest.raises(LeaseLostError):
        old.status = JobStatus.SUCCEEDED
        store.save(old)
    assert not store.retry_attempt(old)
    assert store.get(job.id).attempt_id == current.attempt_id
    assert store.retry_attempt(current, reason="test timeout")
    assert store.get(job.id).status == JobStatus.QUEUED


def test_attempt_limit_and_expired_job_not_claimed(store, job, monkeypatch):
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "1")
    attempt = store.claim(job.id)
    assert store.retry_attempt(attempt)
    assert store.get(job.id).status == JobStatus.FAILED
    assert store.claim(job.id) is None
    with store._connect() as conn:
        conn.execute("update jobs set status='queued',retention_expires_at=now()-interval '1 second' where id=%s", (job.id,))
    assert store.claim(job.id) is None
    assert store.get(job.id).status == JobStatus.EXPIRED


def test_crashed_last_attempt_terminal(store, job, monkeypatch):
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "1")
    store.claim(job.id)
    with store._connect() as conn:
        conn.execute("update jobs set lease_expires_at=now()-interval '1 second' where id=%s", (job.id,))
    assert store.claim(job.id) is None
    assert store.get(job.id).status == JobStatus.FAILED


def test_supervisor_timeout_kills_process_group_and_requeues(store, job, monkeypatch):
    import subprocess
    import sys
    from handwrite_font_maker.web import worker_loop
    real_popen = subprocess.Popen
    children = []

    def slow_process(*args, **kwargs):
        child = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        children.append(child)
        return child

    monkeypatch.setattr(worker_loop.subprocess, "Popen", slow_process)
    # claim only this test's job, never another test's live work.
    monkeypatch.setattr(store, "next_queued", lambda: store.claim(job.id))
    assert worker_loop.run_once(store, timeout=0.1)
    assert children[0].poll() is not None
    assert store.get(job.id).status == JobStatus.QUEUED
    assert store.get(job.id).artifacts == []
    assert "runtime limit" in store.get(job.id).error.message


def test_supervisor_runs_actual_child_and_persists_failure(store, job, monkeypatch, tmp_path):
    from handwrite_font_maker.web import worker_loop
    monkeypatch.setenv("DATABASE_URL", store.database_url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "local")
    monkeypatch.setenv("LOCAL_OBJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(store, "next_queued", lambda: store.claim(job.id))
    assert worker_loop.run_once(store, timeout=15)
    result = store.get(job.id)
    assert result.status == JobStatus.FAILED
    assert result.attempt_count == 1
    assert result.artifacts == []


def test_null_legacy_running_lease_is_recovered(store, job):
    with store._connect() as conn:
        conn.execute("update jobs set status='running',lease_expires_at=null where id=%s", (job.id,))
    recovered = store.claim(job.id)
    assert recovered is not None and recovered.attempt_count == 1


def test_transient_storage_errors_retry_but_invalid_requests_do_not():
    import requests
    from handwrite_font_maker.web.worker import _transient_failure
    assert _transient_failure(requests.Timeout())
    assert _transient_failure(requests.ConnectionError())
    response = requests.Response()
    response.status_code = 503
    assert _transient_failure(requests.HTTPError(response=response))
    response.status_code = 403
    assert not _transient_failure(requests.HTTPError(response=response))
    assert not _transient_failure(ValueError('invalid mask'))


def test_artifact_cleanup_intent_precedes_external_write(monkeypatch, tmp_path):
    from handwrite_font_maker.web.worker import _publish_artifacts
    from handwrite_font_maker.web.job_store import JobRecord
    from handwrite_font_maker.web.tenant_store import WorkerArtifactRegistry
    events = []

    class Registry:
        def register_attempt_artifact(self, *args, **kwargs):
            events.append(('intent', kwargs['object_key']))
        def mark_uploaded(self, *args, **kwargs):
            events.append(('uploaded', kwargs['object_key']))

    class FailingStorage:
        def upload_from_path(self, object_key, *_args):
            events.append(('write', object_key))
            raise TimeoutError('simulated storage outage')

    monkeypatch.setattr(WorkerArtifactRegistry, 'from_env', lambda: Registry())
    source = tmp_path / 'test.ttf'
    source.write_bytes(b'fake-font-for-write-order-test')
    record = JobRecord(id='test', owner_id=str(uuid.uuid4()), attempt_id='attempt-1', lease_owner='lease-1', input_photo=InputPhoto(object_key='input.png', content_type='image/png', size_bytes=1), font=FontRequest(font_name='Test', family_name='Test', style_name='Regular'))
    with pytest.raises(TimeoutError):
        _publish_artifacts(record.id, {'ttf': source}, FailingStorage(), attempt_id=record.attempt_id, job=record)
    assert events == [('intent', 'jobs/test/attempts/attempt-1/artifacts/test.ttf'), ('write', 'jobs/test/attempts/attempt-1/artifacts/test.ttf')]


def test_local_http_job_does_not_attach_pseudo_tenant_owner(monkeypatch, tmp_path):
    from handwrite_font_maker.web.server import _create_job_record
    from handwrite_font_maker.web.security import load_runtime_config
    monkeypatch.delenv('DATABASE_URL', raising=False)
    job = _create_job_record(
        tmp_path / 'jobs.json',
        input_photo=InputPhoto('local/source.png', 'image/png', 100),
        font={'fontName': 'LocalFont'},
        config=load_runtime_config({'DEPLOYMENT_MODE': 'local'}),
        owner_id='local_dev',
    )
    assert job.owner_id is None
