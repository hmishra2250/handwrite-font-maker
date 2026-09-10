from __future__ import annotations

import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from handwrite_font_maker.web.contracts import FontRequest, InputPhoto, JobArtifact, JobStatus
from handwrite_font_maker.web.feedback_store import cleanup_feedback, submit
from handwrite_font_maker.web.job_store import LeaseLostError
from handwrite_font_maker.web.security import load_runtime_config
from handwrite_font_maker.web.sqlite_store import SQLiteJobStore, SQLiteProjectStore, SQLiteTenantStore
from handwrite_font_maker.web.tenant_store import ObjectAccessError, OwnershipError, QuotaExceeded, TenantLimits, WorkerArtifactRegistry, cleanup_expired_from_env


BUCKET = "alpha-bucket"


def limits(**overrides: int) -> TenantLimits:
    values = dict(daily_upload_limit=50, daily_upload_bytes_limit=500_000, daily_preview_limit=50, daily_build_limit=50, active_job_limit=50)
    values.update(overrides)
    return TenantLimits(**values)


def font() -> FontRequest:
    return FontRequest(font_name="AlphaFont", family_name="Alpha Font", style_name="Regular")


def payload(mask_key: str, *, size: int = 123, last_job_id: str | None = None, name: str = "Alpha Project") -> dict[str, object]:
    return {
        "name": name,
        "font": {"fontName": "AlphaFont", "familyName": "Alpha Font", "styleName": "Regular"},
        "mode": "guided",
        "targetCharacters": "A",
        "glyphs": [
            {
                "char": "A",
                "inputPhoto": {"objectKey": mask_key, "contentType": "image/png", "sizeBytes": size},
                "baseline": 0.7,
                "scale": 1.0,
                "spacing": 0.0,
                "width": 64,
                "height": 64,
                "foregroundRatio": 0.3,
                "filename": "A.png",
            }
        ],
        "lastJobId": last_job_id,
    }


def register_uploaded(store: SQLiteTenantStore, owner: str, key: str, *, size: int = 123) -> None:
    store.register_upload(owner_id=owner, bucket=BUCKET, object_key=key, content_type="image/png", size_bytes=size, limits=limits())
    store.mark_uploaded(owner_id=owner, bucket=BUCKET, object_key=key, size_bytes=size)


class RecordingObjectStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_object(self, object_key: str) -> None:
        self.deleted.append(object_key)


def test_sqlite_ready_check_and_persistence_survive_reopen(tmp_path: Path) -> None:
    db = tmp_path / "alpha.sqlite"
    jobs = SQLiteJobStore(db)
    tenants = SQLiteTenantStore(db)
    projects = SQLiteProjectStore(db, bucket=BUCKET)
    assert jobs.ready_check()["ok"] is True
    owner = str(uuid.uuid4())
    key = f"tenants/{owner}/masks/A.png"
    register_uploaded(tenants, owner, key)
    job = tenants.create_job(owner_id=owner, input_photo=InputPhoto(key, "image/png", 123, bucket=BUCKET), font=font(), capture=None, bucket=BUCKET, limits=limits())
    created = projects.create(owner_id=owner, payload=payload(key, last_job_id=job.id))

    reopened_jobs = SQLiteJobStore(db)
    reopened_projects = SQLiteProjectStore(db, bucket=BUCKET)
    assert reopened_jobs.get(job.id).owner_id == owner
    assert reopened_projects.get(owner_id=owner, project_id=created["id"])["lastJobId"] == job.id


def test_sqlite_job_claims_are_atomic_and_attempt_fenced(tmp_path: Path) -> None:
    db = tmp_path / "alpha.sqlite"
    tenant = SQLiteTenantStore(db)
    jobs = SQLiteJobStore(db)
    owner = str(uuid.uuid4())
    key = f"tenants/{owner}/input.png"
    register_uploaded(tenant, owner, key)
    job = tenant.create_job(owner_id=owner, input_photo=InputPhoto(key, "image/png", 123, bucket=BUCKET), font=font(), capture=None, bucket=BUCKET, limits=limits())

    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda _: SQLiteJobStore(db).claim(job.id), range(6)))
    claimed = [claim for claim in claims if claim]
    assert len(claimed) == 1
    attempt = claimed[0]
    assert attempt.attempt_count == 1 and attempt.attempt_id and attempt.lease_owner
    with pytest.raises(LeaseLostError):
        jobs.save(job)

    key_ttf = f"jobs/{job.id}/attempts/{attempt.attempt_id}/artifacts/font.ttf"
    tenant.register_artifact(owner_id=owner, job_id=job.id, bucket=BUCKET, object_key=key_ttf, content_type="font/ttf", size_bytes=42, kind="attempt_artifact:ttf", attempt_id=attempt.attempt_id, lease_owner=attempt.lease_owner)
    tenant.mark_artifact_uploaded(owner_id=owner, bucket=BUCKET, object_key=key_ttf, size_bytes=42)
    with pytest.raises(ObjectAccessError):
        tenant.assert_object_access(owner_id=owner, bucket=BUCKET, object_key=key_ttf)
    attempt.status = JobStatus.SUCCEEDED
    attempt.artifacts = [JobArtifact(kind="ttf", label="Font", object_key=key_ttf, content_type="font/ttf", size_bytes=42)]
    jobs.save(attempt)
    assert jobs.get(job.id).status == JobStatus.SUCCEEDED
    tenant.assert_object_access(owner_id=owner, bucket=BUCKET, object_key=key_ttf)
    assert not jobs.heartbeat(attempt)
    with pytest.raises(LeaseLostError):
        jobs.save(attempt)


def test_sqlite_stale_attempt_cannot_retry_or_publish_over_new_claim(tmp_path: Path) -> None:
    db = tmp_path / "alpha.sqlite"
    tenant = SQLiteTenantStore(db)
    jobs = SQLiteJobStore(db)
    owner = str(uuid.uuid4())
    key = f"tenants/{owner}/input.png"
    register_uploaded(tenant, owner, key)
    job = tenant.create_job(owner_id=owner, input_photo=InputPhoto(key, "image/png", 123, bucket=BUCKET), font=font(), capture=None, bucket=BUCKET, limits=limits())
    old = jobs.claim(job.id)
    assert old is not None
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("update jobs set lease_expires_at='2000-01-01T00:00:00Z' where id=?", (job.id,))
        conn.commit()
    current = jobs.claim(job.id)
    assert current is not None and current.attempt_count == 2 and current.attempt_id != old.attempt_id
    old.status = JobStatus.SUCCEEDED
    with pytest.raises(LeaseLostError):
        jobs.save(old)
    assert not jobs.retry_attempt(old)
    assert jobs.get(job.id).attempt_id == current.attempt_id


def test_sqlite_tenant_quota_and_owner_scopes_are_serialized(tmp_path: Path) -> None:
    db = tmp_path / "alpha.sqlite"
    owner = str(uuid.uuid4())
    tenant = SQLiteTenantStore(db)
    limited = limits(daily_upload_limit=3, daily_upload_bytes_limit=1000, daily_build_limit=10, active_job_limit=2)

    def upload(index: int) -> str | None:
        store = SQLiteTenantStore(db)
        key = f"tenants/{owner}/parallel/{index}.png"
        try:
            store.register_upload(owner_id=owner, bucket=BUCKET, object_key=key, content_type="image/png", size_bytes=100, limits=limited)
            store.mark_uploaded(owner_id=owner, bucket=BUCKET, object_key=key, size_bytes=100)
            return key
        except QuotaExceeded:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = [key for key in pool.map(upload, range(8)) if key]
    assert len(accepted) == 3
    with pytest.raises(ObjectAccessError):
        tenant.assert_object_access(owner_id=str(uuid.uuid4()), bucket=BUCKET, object_key=accepted[0])

    def build(_: int):
        try:
            return SQLiteTenantStore(db).create_job(owner_id=owner, input_photo=InputPhoto(accepted[0], "image/png", 100, bucket=BUCKET), font=font(), capture=None, bucket=BUCKET, limits=limited)
        except QuotaExceeded:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [job for job in pool.map(build, range(6)) if job]
    assert len(jobs) == 2


def test_sqlite_project_refs_protect_cleanup_until_last_project_deleted(tmp_path: Path) -> None:
    db = tmp_path / "alpha.sqlite"
    owner = str(uuid.uuid4())
    tenants = SQLiteTenantStore(db)
    projects = SQLiteProjectStore(db, bucket=BUCKET)
    key = f"tenants/{owner}/masks/shared.png"
    register_uploaded(tenants, owner, key)
    first = projects.create(owner_id=owner, payload=payload(key, name="One"))
    second = projects.create(owner_id=owner, payload=payload(key, name="Two"))
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("update tenant_objects set retention_expires_at='2000-01-01T00:00:00Z' where owner_id=? and object_key=?", (owner, key))
        conn.commit()
    deleter = RecordingObjectStore()
    assert tenants.cleanup_expired(object_store=deleter)["deletedObjects"] == 0
    assert projects.delete(owner_id=owner, project_id=first["id"], object_store=deleter) == {"deletedObjects": 0, "failedObjects": 0}
    assert key not in deleter.deleted
    assert projects.delete(owner_id=owner, project_id=second["id"], object_store=deleter)["deletedObjects"] == 1
    assert key in deleter.deleted


def test_sqlite_project_revision_and_last_job_ownership(tmp_path: Path) -> None:
    db = tmp_path / "alpha.sqlite"
    owner = str(uuid.uuid4())
    other = str(uuid.uuid4())
    tenants = SQLiteTenantStore(db)
    projects = SQLiteProjectStore(db, bucket=BUCKET)
    key = f"tenants/{owner}/masks/A.png"
    register_uploaded(tenants, owner, key)
    job = tenants.create_job(owner_id=owner, input_photo=InputPhoto(key, "image/png", 123, bucket=BUCKET), font=font(), capture=None, bucket=BUCKET, limits=limits())
    project = projects.create(owner_id=owner, payload=payload(key, last_job_id=job.id))
    update = payload(key, last_job_id=job.id, name="Renamed")
    update["revision"] = project["revision"]
    assert projects.update(owner_id=owner, project_id=project["id"], payload=update)["revision"] == 2
    with pytest.raises(Exception):
        projects.update(owner_id=other, project_id=project["id"], payload=update)
    with pytest.raises(OwnershipError):
        projects.create(owner_id=owner, payload=payload(key, last_job_id="job_missing"))


def test_private_alpha_feedback_and_cleanup_use_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "alpha.sqlite"
    owner = str(uuid.uuid4())
    config = load_runtime_config({
        "DEPLOYMENT_MODE": "private_alpha",
        "ALPHA_DATABASE_PATH": str(db),
        "LOCAL_OBJECT_ROOT": str(tmp_path / "objects"),
        "INTERNAL_API_KEY": "i" * 40,
        "PROCESS_JOBS_INLINE": "0",
    })
    SQLiteTenantStore(db).ensure_tenant(owner)
    submit(config, owner, {"topic": "other", "message": "Useful alpha feedback", "consent": True}, event=False)
    submit(config, owner, {"event": "glyph_accepted", "consent": True}, event=True)
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("select count(*) from beta_feedback where owner_id=?", (owner,)).fetchone()[0] == 1
        assert conn.execute("select count(*) from beta_events_daily where owner_id=?", (owner,)).fetchone()[0] == 1
        conn.execute("update beta_feedback set expires_at='2000-01-01T00:00:00Z' where owner_id=?", (owner,))
        conn.commit()
    cleanup_feedback(config)
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("select count(*) from beta_feedback where owner_id=?", (owner,)).fetchone()[0] == 0


def test_private_alpha_worker_registry_and_cleanup_factory_use_sqlite_local_objects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "alpha.sqlite"
    object_root = tmp_path / "objects"
    monkeypatch.setenv("DEPLOYMENT_MODE", "private_alpha")
    monkeypatch.setenv("ALPHA_DATABASE_PATH", str(db))
    monkeypatch.setenv("LOCAL_OBJECT_ROOT", str(object_root))
    monkeypatch.setenv("INTERNAL_API_KEY", "i" * 40)
    monkeypatch.setenv("PROCESS_JOBS_INLINE", "0")
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", BUCKET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    owner = str(uuid.uuid4())
    tenants = SQLiteTenantStore(db)
    jobs = SQLiteJobStore(db)
    key = f"tenants/{owner}/input.png"
    register_uploaded(tenants, owner, key)
    job = tenants.create_job(owner_id=owner, input_photo=InputPhoto(key, "image/png", 123, bucket=BUCKET), font=font(), capture=None, bucket=BUCKET, limits=limits())
    attempt = jobs.claim(job.id)
    artifact = f"jobs/{job.id}/attempts/{attempt.attempt_id}/artifacts/font.ttf"
    registry = WorkerArtifactRegistry.from_env()
    registry.register_attempt_artifact(attempt, object_key=artifact, content_type="font/ttf", size_bytes=42, kind="ttf")
    registry.mark_uploaded(attempt, object_key=artifact, size_bytes=42)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("update tenant_objects set retention_expires_at='2000-01-01T00:00:00Z' where object_key=?", (artifact,))
        conn.execute("update jobs set status='expired', retention_expires_at='2000-01-01T00:00:00Z' where id=?", (job.id,))
        conn.commit()
    target = object_root / artifact
    target.parent.mkdir(parents=True)
    target.write_bytes(b"font")
    result = cleanup_expired_from_env(object_root=object_root)
    assert result["deletedObjects"] >= 1
    assert not target.exists()
