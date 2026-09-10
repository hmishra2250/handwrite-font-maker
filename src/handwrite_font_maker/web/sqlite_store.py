"""Single-host SQLite persistence for the private-alpha deployment.

This module intentionally mirrors the durable Postgres stores at the Python
interface level, not by translating PostgreSQL SQL.  It is for one writable host
with local object storage; transactions use BEGIN IMMEDIATE so quota admission,
job leasing, and cleanup decisions are serialized before any external object
write/delete happens.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .contracts import (
    CaptureConfig,
    FontRequest,
    HardErrorCode,
    InputPhoto,
    JobArtifact,
    JobError,
    JobStage,
    JobStatus,
    JobWarning,
    capture_from_json,
    capture_to_json,
    is_safe_object_key,
    new_job_id,
    retention_expires_at,
)
from .job_store import JobRecord, LeaseLostError
from .project_store import (
    MAX_LIVE_PROJECTS,
    ProjectConflict,
    ProjectLimitExceeded,
    ProjectNotFound,
    ProjectStoreError,
    _dt_to_iso as _project_dt_to_iso,
    new_project_id,
    project_retention_expires_at,
    validate_project_payload,
)
from .tenant_store import (
    DeletableObjectStore,
    ObjectAccessError,
    OwnershipError,
    QuotaExceeded,
    RegisteredObject,
    TenantLimits,
    _capture_object_keys,
    _delete_tombstone_seconds,
    _registered_from_row,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _iso(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _as_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _future(value: object | None) -> bool:
    if value is None:
        return False
    try:
        return _as_utc(value) > _now()
    except Exception:
        return False


def _expired(value: object | None) -> bool:
    return not _future(value)


def _json_dumps(value: object | None) -> str | None:
    return None if value is None else json.dumps(value)


def _json_loads(value: object | None, default: object) -> object:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(str(value))


def _row_to_tuple(row: sqlite3.Row) -> tuple[object, ...]:
    return (
        row["owner_id"],
        row["bucket"],
        row["object_key"],
        row["kind"],
        row["content_type"],
        row["size_bytes"],
        row["retention_expires_at"],
        row["job_id"],
    )


class _SQLiteBase:
    def __init__(self, path: str | Path) -> None:
        from .alpha_files import prepare_alpha_database

        self.path = prepare_alpha_database(path)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _migrate(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(SQLITE_SCHEMA)

    def ready_check(self) -> dict[str, object]:
        required = {
            "jobs",
            "job_warnings",
            "job_artifacts",
            "tenants",
            "tenant_daily_usage",
            "tenant_objects",
            "tenant_object_job_refs",
            "projects",
            "tenant_project_object_refs",
            "beta_feedback",
            "beta_events_daily",
        }
        with closing(self._connect()) as conn:
            rows = conn.execute("select name from sqlite_master where type='table'").fetchall()
            tables = {str(row[0]) for row in rows}
            conn.execute("select 1").fetchone()
        missing = sorted(required - tables)
        return {"ok": not missing, "store": "sqlite", "path": str(self.path), "missingTables": missing}


class SQLiteJobStore(_SQLiteBase):
    """Durable private-alpha job store with attempt leases and fencing."""

    @property
    def lease_seconds(self) -> int:
        return max(10, int(os.environ.get("JOB_LEASE_SECONDS", "60")))

    @property
    def max_attempts(self) -> int:
        return max(1, int(os.environ.get("JOB_MAX_ATTEMPTS", "3")))

    def create(self, input_photo: InputPhoto, font: FontRequest, capture: CaptureConfig | None = None, owner_id: str | None = None) -> JobRecord:
        job = JobRecord(id=new_job_id(), input_photo=input_photo, font=font, capture=capture, owner_id=owner_id)
        bucket = input_photo.bucket or "handwrite-font-jobs"
        now = _now_iso()
        with self._transaction() as conn:
            conn.execute(
                """
                insert into jobs (id,status,stage,font_name,family_name,style_name,input_bucket,input_path,
                  input_content_type,input_size_bytes,capture_config,retention_expires_at,owner_id,created_at,updated_at,error_details)
                values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job.id,
                    job.status.value,
                    job.stage.value,
                    font.font_name,
                    font.family_name,
                    font.style_name,
                    bucket,
                    input_photo.object_key,
                    input_photo.content_type,
                    input_photo.size_bytes,
                    _json_dumps(capture_to_json(capture)),
                    job.retention_expires_at,
                    owner_id,
                    now,
                    now,
                    "{}",
                ),
            )
        return job

    def get(self, job_id: str) -> JobRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute("select * from jobs where id=?", (job_id,)).fetchone()
            if row is None:
                return None
            warnings = [
                JobWarning(code=r["code"], glyph=r["glyph"], message=r["message"], severity=r["severity"], details=_json_loads(r["details"], {}))
                for r in conn.execute("select code,glyph,message,severity,details from job_warnings where job_id=? order by id", (job_id,)).fetchall()
            ]
            artifacts = [
                JobArtifact(kind=r["kind"], label=r["label"], object_key=r["path"], content_type=r["content_type"], size_bytes=int(r["size_bytes"]))
                for r in conn.execute("select kind,label,path,content_type,size_bytes from job_artifacts where job_id=? order by id", (job_id,)).fetchall()
            ]
        return _job_from_sqlite_row(row, warnings, artifacts)

    def next_queued(self) -> JobRecord | None:
        return self.claim()

    def claim(self, job_id: str | None = None) -> JobRecord | None:
        now = _now_iso()
        lease_until = (_now() + timedelta(seconds=self.lease_seconds)).isoformat().replace("+00:00", "Z")
        with self._transaction() as conn:
            conn.execute(
                """update jobs set status='expired', lease_owner=null, lease_expires_at=null,
                   completed_at=coalesce(completed_at, ?), updated_at=?
                   where status in ('queued','running') and retention_expires_at<=?""",
                (now, now, now),
            )
            conn.execute(
                """update jobs set status='failed', error_code='INTERNAL_ERROR', error_message='Processing attempts exhausted.',
                   error_retryable=0, lease_owner=null, lease_expires_at=null, completed_at=?, updated_at=?
                   where status in ('queued','running') and attempt_count>=?
                     and (status='queued' or lease_expires_at is null or lease_expires_at<=?)""",
                (now, now, self.max_attempts, now),
            )
            params: tuple[object, ...]
            if job_id is None:
                params = (now, now, self.max_attempts)
                where_job = ""
            else:
                params = (now, now, self.max_attempts, job_id)
                where_job = " and id=?"
            row = conn.execute(
                f"""
                select * from jobs
                where (status='queued' or (status='running' and (lease_expires_at is null or lease_expires_at<=?)))
                  and retention_expires_at>? and attempt_count<?{where_job}
                order by created_at, id limit 1
                """,
                params,
            ).fetchone()
            if row is None:
                return None
            attempt_id = str(uuid4())
            lease_owner = str(uuid4())
            conn.execute(
                """update jobs set status='running', stage='upload_received', lease_owner=?, attempt_id=?,
                   attempt_count=attempt_count+1, lease_expires_at=?, updated_at=?, error_code=null,
                   error_message=null, error_retryable=null, error_details='{}' where id=?""",
                (lease_owner, attempt_id, lease_until, now, row["id"]),
            )
            claimed = conn.execute("select * from jobs where id=?", (row["id"],)).fetchone()
        return _job_from_sqlite_row(claimed, [], []) if claimed is not None else None

    def heartbeat(self, job: JobRecord) -> bool:
        now = _now_iso()
        lease_until = (_now() + timedelta(seconds=self.lease_seconds)).isoformat().replace("+00:00", "Z")
        with self._transaction() as conn:
            cur = conn.execute(
                """update jobs set lease_expires_at=?, updated_at=? where id=? and attempt_id=? and lease_owner=?
                   and status='running' and lease_expires_at>? and retention_expires_at>?""",
                (lease_until, now, job.id, job.attempt_id, job.lease_owner, now, now),
            )
            return cur.rowcount == 1

    def retry_attempt(self, job: JobRecord, *, reason: str = "Worker interrupted") -> bool:
        now = _now_iso()
        with self._transaction() as conn:
            current = conn.execute(
                """select attempt_count from jobs where id=? and attempt_id=? and lease_owner=? and status='running'
                   and lease_expires_at>? and retention_expires_at>?""",
                (job.id, job.attempt_id, job.lease_owner, now, now),
            ).fetchone()
            if current is None:
                return False
            exhausted = int(current["attempt_count"]) >= self.max_attempts
            cur = conn.execute(
                """update jobs set status=?, stage='queued', lease_owner=null, lease_expires_at=null,
                   error_code='INTERNAL_ERROR', error_message=?, error_retryable=?, updated_at=?, completed_at=?
                   where id=? and attempt_id=? and lease_owner=? and status='running'""",
                (
                    JobStatus.FAILED.value if exhausted else JobStatus.QUEUED.value,
                    reason,
                    0 if exhausted else 1,
                    now,
                    now if exhausted else None,
                    job.id,
                    job.attempt_id,
                    job.lease_owner,
                ),
            )
            return cur.rowcount == 1

    def save(self, job: JobRecord) -> None:
        now = _now_iso()
        terminal = job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.EXPIRED}
        with self._transaction() as conn:
            cur = conn.execute(
                """
                update jobs set status=?, stage=?, capture_config=?, error_code=?, error_message=?, error_retryable=?,
                  error_details=?, updated_at=?, completed_at=case when ? then coalesce(completed_at, ?) else completed_at end
                where id=? and attempt_id=? and lease_owner=? and status='running'
                  and lease_expires_at>? and retention_expires_at>?
                """,
                (
                    job.status.value,
                    job.stage.value,
                    _json_dumps(capture_to_json(job.capture)),
                    None if job.error is None else job.error.code.value,
                    None if job.error is None else job.error.message,
                    None if job.error is None else int(job.error.retryable),
                    json.dumps({} if job.error is None else job.error.details),
                    now,
                    1 if terminal else 0,
                    now,
                    job.id,
                    job.attempt_id,
                    job.lease_owner,
                    now,
                    now,
                ),
            )
            if cur.rowcount != 1:
                raise LeaseLostError("Job lease lost or expired")
            conn.execute("delete from job_warnings where job_id=?", (job.id,))
            for warning in job.warnings:
                conn.execute(
                    "insert into job_warnings (job_id,code,glyph,message,severity,details,created_at) values (?,?,?,?,?,?,?)",
                    (job.id, warning.code, warning.glyph, warning.message, warning.severity, json.dumps(warning.details), now),
                )
            conn.execute("delete from job_artifacts where job_id=?", (job.id,))
            for artifact in job.artifacts:
                bucket = job.input_photo.bucket or "handwrite-font-jobs"
                conn.execute(
                    "insert into job_artifacts (job_id,kind,label,bucket,path,content_type,size_bytes,created_at) values (?,?,?,?,?,?,?,?)",
                    (job.id, artifact.kind, artifact.label, bucket, artifact.object_key, artifact.content_type, artifact.size_bytes, now),
                )


class SQLiteTenantStore(_SQLiteBase):
    def ensure_tenant(self, owner_id: str) -> None:
        now = _now_iso()
        with self._transaction() as conn:
            conn.execute(
                "insert into tenants(owner_id,status,created_at,updated_at) values(?, 'active', ?, ?) on conflict(owner_id) do update set updated_at=excluded.updated_at",
                (owner_id, now, now),
            )

    def _ensure_and_lock_tenant(self, conn: sqlite3.Connection, owner_id: str) -> None:
        now = _now_iso()
        conn.execute(
            "insert into tenants(owner_id,status,created_at,updated_at) values(?, 'active', ?, ?) on conflict(owner_id) do update set updated_at=excluded.updated_at",
            (owner_id, now, now),
        )
        row = conn.execute("select owner_id from tenants where owner_id=? and status='active'", (owner_id,)).fetchone()
        if row is None:
            raise OwnershipError("Tenant is disabled or missing.")

    def register_upload(self, *, owner_id: str, bucket: str, object_key: str, content_type: str, size_bytes: int, limits: TenantLimits, expires_at: str | None = None) -> RegisteredObject:
        if not is_safe_object_key(object_key):
            raise ObjectAccessError("Invalid object key.")
        if limits.daily_upload_limit <= 0 or limits.daily_upload_bytes_limit < size_bytes:
            raise QuotaExceeded("Daily upload quota exceeded.")
        expires_at = expires_at or retention_expires_at(24)
        today = date.today().isoformat()
        now = _now_iso()
        with self._transaction() as conn:
            self._ensure_and_lock_tenant(conn, owner_id)
            usage = conn.execute("select uploads_count, upload_bytes from tenant_daily_usage where owner_id=? and usage_date=?", (owner_id, today)).fetchone()
            uploads = int(usage["uploads_count"]) if usage else 0
            upload_bytes = int(usage["upload_bytes"]) if usage else 0
            if uploads >= limits.daily_upload_limit or upload_bytes + size_bytes > limits.daily_upload_bytes_limit:
                raise QuotaExceeded("Daily upload quota exceeded.")
            conn.execute(
                """insert into tenant_daily_usage(owner_id,usage_date,uploads_count,upload_bytes,created_at,updated_at)
                   values(?,?,?,?,?,?)
                   on conflict(owner_id,usage_date) do update set uploads_count=uploads_count+1,
                   upload_bytes=upload_bytes+excluded.upload_bytes, updated_at=excluded.updated_at""",
                (owner_id, today, 1, size_bytes, now, now),
            )
            existing = conn.execute("select * from tenant_objects where bucket=? and object_key=?", (bucket, object_key)).fetchone()
            if existing is not None:
                if existing["owner_id"] != owner_id or existing["status"] != "registered":
                    raise ObjectAccessError("Upload object key is already registered.")
                conn.execute("update tenant_objects set updated_at=? where bucket=? and object_key=?", (now, bucket, object_key))
            else:
                conn.execute(
                    """insert into tenant_objects(owner_id,bucket,object_key,kind,content_type,size_bytes,status,retention_expires_at,created_at,updated_at)
                       values(?,?,?,?,?,?,'registered',?,?,?)""",
                    (owner_id, bucket, object_key, "upload", content_type, size_bytes, expires_at, now, now),
                )
            row = conn.execute("select owner_id,bucket,object_key,kind,content_type,size_bytes,retention_expires_at,job_id from tenant_objects where bucket=? and object_key=?", (bucket, object_key)).fetchone()
        return _registered_from_row(_row_to_tuple(row))

    def mark_uploaded(self, *, owner_id: str, bucket: str, object_key: str, size_bytes: int | None = None) -> None:
        now = _now_iso()
        rescheduled_deleted_upload = False
        with self._transaction() as conn:
            cur = conn.execute(
                """update tenant_objects set status='uploaded', size_bytes=coalesce(?, size_bytes), updated_at=?
                   where owner_id=? and bucket=? and object_key=? and retention_expires_at>? and status in ('registered','uploading')""",
                (size_bytes, now, owner_id, bucket, object_key, now),
            )
            if cur.rowcount == 1:
                return
            cur = conn.execute(
                """update tenant_objects set status='delete_failed', retention_expires_at=min(retention_expires_at, ?),
                   last_delete_error='Upload completed after deletion request.', updated_at=?
                   where owner_id=? and bucket=? and object_key=? and status='deleted'""",
                (now, now, owner_id, bucket, object_key),
            )
            if cur.rowcount == 1:
                rescheduled_deleted_upload = True
            else:
                raise ObjectAccessError("Upload object is not registered to this user.")
        if rescheduled_deleted_upload:
            raise ObjectAccessError("Upload completed after deletion and was scheduled for cleanup.")

    def assert_object_access(self, *, owner_id: str, bucket: str, object_key: str, require_uploaded: bool = True) -> None:
        now = _now_iso()
        with closing(self._connect()) as conn:
            row = conn.execute(
                """select * from tenant_objects where owner_id=? and bucket=? and object_key=?
                   and retention_expires_at>? and status <> 'deleted'""",
                (owner_id, bucket, object_key, now),
            ).fetchone()
            allowed = row is not None
            if allowed and require_uploaded:
                allowed = row["status"] == "uploaded" and (
                    row["kind"] == "upload"
                    or (
                        "artifact:" in str(row["kind"])
                        and conn.execute(
                            """select 1 from job_artifacts a join jobs j on j.id=a.job_id
                               where a.bucket=? and a.path=? and j.owner_id=? and j.status='succeeded'
                                 and j.retention_expires_at>?""",
                            (bucket, object_key, owner_id, now),
                        ).fetchone()
                        is not None
                    )
                )
            if not allowed:
                raise ObjectAccessError("Upload object is missing, expired, or belongs to another user.")

    def assert_upload_intent(self, *, owner_id: str, bucket: str, object_key: str) -> RegisteredObject:
        now = _now_iso()
        with closing(self._connect()) as conn:
            row = conn.execute(
                """select owner_id,bucket,object_key,kind,content_type,size_bytes,retention_expires_at,job_id from tenant_objects
                   where owner_id=? and bucket=? and object_key=? and retention_expires_at>? and status='registered'""",
                (owner_id, bucket, object_key, now),
            ).fetchone()
            if row is None:
                raise ObjectAccessError("Upload object is not awaiting bytes for this user.")
            return _registered_from_row(tuple(row))

    def claim_upload_intent(self, *, owner_id: str, bucket: str, object_key: str) -> RegisteredObject:
        now = _now_iso()
        with self._transaction() as conn:
            cur = conn.execute(
                """update tenant_objects set status='uploading', updated_at=?
                   where owner_id=? and bucket=? and object_key=? and retention_expires_at>? and status='registered'""",
                (now, owner_id, bucket, object_key, now),
            )
            if cur.rowcount != 1:
                raise ObjectAccessError("Upload object is not awaiting bytes for this user.")
            row = conn.execute("select owner_id,bucket,object_key,kind,content_type,size_bytes,retention_expires_at,job_id from tenant_objects where owner_id=? and bucket=? and object_key=?", (owner_id, bucket, object_key)).fetchone()
        return _registered_from_row(tuple(row))

    def record_preview(self, *, owner_id: str, limits: TenantLimits) -> None:
        if limits.daily_preview_limit <= 0:
            raise QuotaExceeded("Daily preview quota exceeded.")
        today = date.today().isoformat()
        now = _now_iso()
        with self._transaction() as conn:
            self._ensure_and_lock_tenant(conn, owner_id)
            row = conn.execute("select previews_count from tenant_daily_usage where owner_id=? and usage_date=?", (owner_id, today)).fetchone()
            if row is not None and int(row["previews_count"]) >= limits.daily_preview_limit:
                raise QuotaExceeded("Daily preview quota exceeded.")
            conn.execute(
                """insert into tenant_daily_usage(owner_id,usage_date,previews_count,created_at,updated_at) values(?,?,?,?,?)
                   on conflict(owner_id,usage_date) do update set previews_count=previews_count+1, updated_at=excluded.updated_at""",
                (owner_id, today, 1, now, now),
            )

    def create_job(self, *, owner_id: str, input_photo: InputPhoto, font: FontRequest, capture: CaptureConfig | None, bucket: str, limits: TenantLimits) -> JobRecord:
        object_keys = _capture_object_keys(input_photo, capture)
        job = JobRecord(id=new_job_id(), input_photo=input_photo, font=font, capture=capture, owner_id=owner_id)
        today = date.today().isoformat()
        now = _now_iso()
        with self._transaction() as conn:
            if limits.daily_build_limit <= 0 or limits.active_job_limit <= 0:
                raise QuotaExceeded("Daily build quota exceeded.")
            self._ensure_and_lock_tenant(conn, owner_id)
            active = conn.execute("select count(*) from jobs where owner_id=? and status in ('queued','running') and retention_expires_at>?", (owner_id, now)).fetchone()[0]
            if int(active) >= limits.active_job_limit:
                raise QuotaExceeded("Active job quota exceeded.")
            usage = conn.execute("select builds_count from tenant_daily_usage where owner_id=? and usage_date=?", (owner_id, today)).fetchone()
            if usage is not None and int(usage["builds_count"]) >= limits.daily_build_limit:
                raise QuotaExceeded("Daily build quota exceeded.")
            conn.execute(
                """insert into tenant_daily_usage(owner_id,usage_date,builds_count,created_at,updated_at) values(?,?,?,?,?)
                   on conflict(owner_id,usage_date) do update set builds_count=builds_count+1, updated_at=excluded.updated_at""",
                (owner_id, today, 1, now, now),
            )
            for object_key in object_keys:
                if conn.execute(
                    """select 1 from tenant_objects where owner_id=? and bucket=? and object_key=?
                       and retention_expires_at>? and status='uploaded'""",
                    (owner_id, bucket, object_key, now),
                ).fetchone() is None:
                    raise ObjectAccessError("All job objects must be registered to the authenticated user.")
            conn.execute(
                """insert into jobs (id,status,stage,font_name,family_name,style_name,input_bucket,input_path,input_content_type,
                  input_size_bytes,capture_config,retention_expires_at,owner_id,created_at,updated_at,error_details)
                  values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job.id,
                    job.status.value,
                    job.stage.value,
                    font.font_name,
                    font.family_name,
                    font.style_name,
                    bucket,
                    input_photo.object_key,
                    input_photo.content_type,
                    input_photo.size_bytes,
                    _json_dumps(capture_to_json(capture)),
                    job.retention_expires_at,
                    owner_id,
                    now,
                    now,
                    "{}",
                ),
            )
            for object_key in object_keys:
                conn.execute(
                    """update tenant_objects set job_id=?, retention_expires_at=max(retention_expires_at, ?), updated_at=?
                       where owner_id=? and bucket=? and object_key=?""",
                    (job.id, job.retention_expires_at, now, owner_id, bucket, object_key),
                )
                conn.execute(
                    """insert into tenant_object_job_refs(owner_id,bucket,object_key,job_id,retention_expires_at,created_at,updated_at)
                       values(?,?,?,?,?,?,?)
                       on conflict(bucket,object_key,job_id) do update set retention_expires_at=excluded.retention_expires_at, updated_at=excluded.updated_at""",
                    (owner_id, bucket, object_key, job.id, job.retention_expires_at, now, now),
                )
        return job

    def authorize_job(self, *, owner_id: str, job_id: str) -> None:
        now = _now_iso()
        with self._transaction() as conn:
            row = conn.execute("select owner_id,retention_expires_at,status,delete_requested_at from jobs where id=?", (job_id,)).fetchone()
            if row is None or row["owner_id"] != owner_id:
                raise OwnershipError("Job not found.")
            if row["status"] == "expired" or row["delete_requested_at"] is not None or _expired(row["retention_expires_at"]):
                conn.execute("update jobs set status='expired', updated_at=?, completed_at=coalesce(completed_at, ?) where id=?", (now, now, job_id))
                raise OwnershipError("Job expired.")

    def delete_job(self, *, owner_id: str, job_id: str, object_store: DeletableObjectStore) -> dict[str, object]:
        self.authorize_job(owner_id=owner_id, job_id=job_id)
        now = _now_iso()
        with self._transaction() as conn:
            self._ensure_and_lock_tenant(conn, owner_id)
            conn.execute(
                """update jobs set status='expired', lease_owner=null, lease_expires_at=null, delete_requested_at=?,
                   retention_expires_at=min(retention_expires_at, ?), completed_at=coalesce(completed_at, ?), updated_at=?
                   where id=? and owner_id=?""",
                (now, now, now, now, job_id, owner_id),
            )
            object_rows = [
                (str(r["bucket"]), str(r["object_key"]))
                for r in conn.execute(
                    """select o.bucket,o.object_key from tenant_objects o
                       where o.owner_id=? and o.status <> 'deleted'
                         and exists (select 1 from tenant_object_job_refs r where r.bucket=o.bucket and r.object_key=o.object_key and r.job_id=?)""",
                    (owner_id, job_id),
                ).fetchall()
                if self._object_unprotected(conn, bucket=str(r["bucket"]), object_key=str(r["object_key"]), except_job_id=job_id, now=now)
            ]
            object_rows.extend((str(r["bucket"]), str(r["path"])) for r in conn.execute("select bucket,path from job_artifacts where job_id=?", (job_id,)).fetchall())
            for bucket, object_key in object_rows:
                conn.execute("update tenant_objects set retention_expires_at=min(retention_expires_at, ?), updated_at=? where bucket=? and object_key=?", (now, now, bucket, object_key))
        return self._delete_rows(object_rows, object_store)

    def cleanup_expired(self, *, object_store: DeletableObjectStore, limit: int = 100) -> dict[str, object]:
        now = _now_iso()
        with self._transaction() as conn:
            conn.execute("""update jobs set status='expired', lease_owner=null, lease_expires_at=null,
                       completed_at=coalesce(completed_at, ?), updated_at=? where retention_expires_at<=? and status <> 'expired'""", (now, now, now))
            conn.execute("update projects set deleted_at=coalesce(deleted_at, ?), updated_at=? where deleted_at is null and retention_expires_at<=?", (now, now, now))
            conn.execute("delete from tenant_project_object_refs where project_id in (select id from projects where deleted_at is not null or retention_expires_at<=?)", (now,))
            conn.execute("delete from projects where deleted_at is not null and retention_expires_at<=?", (now,))
            candidates = conn.execute(
                """select bucket,object_key from tenant_objects where retention_expires_at<=? and status <> 'deleted'
                   and (next_delete_attempt_at is null or next_delete_attempt_at<=?) order by retention_expires_at, delete_attempts limit ?""",
                (now, now, limit),
            ).fetchall()
            object_rows = [
                (str(r["bucket"]), str(r["object_key"]))
                for r in candidates
                if self._object_unprotected(conn, bucket=str(r["bucket"]), object_key=str(r["object_key"]), now=now)
            ]
        return self._delete_rows(object_rows, object_store)

    def register_artifact(self, *, owner_id: str, job_id: str, bucket: str, object_key: str, content_type: str, size_bytes: int, kind: str = "artifact", expires_at: str | None = None, attempt_id: str | None = None, lease_owner: str | None = None) -> None:
        if not is_safe_object_key(object_key):
            raise ObjectAccessError("Invalid object key.")
        expires_at = expires_at or retention_expires_at(24)
        now = _now_iso()
        with self._transaction() as conn:
            self._assert_live_job_attempt(conn, owner_id=owner_id, job_id=job_id, attempt_id=attempt_id, lease_owner=lease_owner)
            existing = conn.execute("select owner_id from tenant_objects where bucket=? and object_key=?", (bucket, object_key)).fetchone()
            if existing is not None and existing["owner_id"] != owner_id:
                raise ObjectAccessError("Artifact object key is already registered.")
            conn.execute(
                """insert into tenant_objects(owner_id,bucket,object_key,kind,content_type,size_bytes,job_id,status,retention_expires_at,created_at,updated_at)
                   values(?,?,?,?,?,?,?,'registered',?,?,?)
                   on conflict(bucket,object_key) do update set owner_id=excluded.owner_id, kind=excluded.kind,
                   content_type=excluded.content_type, size_bytes=excluded.size_bytes, job_id=excluded.job_id,
                   status='registered', retention_expires_at=excluded.retention_expires_at, updated_at=excluded.updated_at""",
                (owner_id, bucket, object_key, kind, content_type, size_bytes, job_id, expires_at, now, now),
            )
            conn.execute(
                """insert into tenant_object_job_refs(owner_id,bucket,object_key,job_id,retention_expires_at,created_at,updated_at)
                   values(?,?,?,?,?,?,?) on conflict(bucket,object_key,job_id) do update set retention_expires_at=excluded.retention_expires_at, updated_at=excluded.updated_at""",
                (owner_id, bucket, object_key, job_id, expires_at, now, now),
            )

    def mark_artifact_uploaded(self, *, owner_id: str, bucket: str, object_key: str, size_bytes: int | None = None) -> None:
        self.mark_uploaded(owner_id=owner_id, bucket=bucket, object_key=object_key, size_bytes=size_bytes)

    def _assert_live_job_attempt(self, conn: sqlite3.Connection, *, owner_id: str, job_id: str, attempt_id: str | None, lease_owner: str | None) -> None:
        if not attempt_id or not lease_owner:
            raise OwnershipError("Artifact registration requires a live leased job attempt.")
        now = _now_iso()
        row = conn.execute(
            """select 1 from jobs where id=? and owner_id=? and status='running' and retention_expires_at>?
               and attempt_id=? and lease_owner=? and lease_expires_at>?""",
            (job_id, owner_id, now, attempt_id, lease_owner, now),
        ).fetchone()
        if row is None:
            raise OwnershipError("Job attempt is no longer live.")

    def _object_unprotected(self, conn: sqlite3.Connection, *, bucket: str, object_key: str, now: str, except_job_id: str | None = None) -> bool:
        job_params: tuple[object, ...]
        extra = ""
        if except_job_id is not None:
            extra = " and r.job_id<>?"
            job_params = (bucket, object_key, except_job_id, now)
        else:
            job_params = (bucket, object_key, now)
        if conn.execute(
            f"""select 1 from tenant_object_job_refs r join jobs j on j.id=r.job_id
                where r.bucket=? and r.object_key=?{extra} and j.status in ('queued','running','succeeded') and j.retention_expires_at>?""",
            job_params,
        ).fetchone() is not None:
            return False
        if conn.execute(
            """select 1 from tenant_project_object_refs pr join projects p on p.id=pr.project_id
               where pr.bucket=? and pr.object_key=? and p.deleted_at is null and p.retention_expires_at>?""",
            (bucket, object_key, now),
        ).fetchone() is not None:
            return False
        return True

    def _claim_expired_object(self, *, bucket: str, object_key: str) -> bool:
        now = _now_iso()
        with self._transaction() as conn:
            row = conn.execute("select owner_id,status from tenant_objects where bucket=? and object_key=?", (bucket, object_key)).fetchone()
            if row is None:
                return False
            if conn.execute("select owner_id from tenants where owner_id=? and status='active'", (row["owner_id"],)).fetchone() is None:
                return False
            candidate = conn.execute(
                """select status from tenant_objects where bucket=? and object_key=? and status <> 'deleted'
                   and retention_expires_at<=? and (next_delete_attempt_at is null or next_delete_attempt_at<=?)""",
                (bucket, object_key, now, now),
            ).fetchone()
            if candidate is None or not self._object_unprotected(conn, bucket=bucket, object_key=object_key, now=now):
                return False
            in_flight = str(candidate["status"]) in {"registered", "uploading"}
            delete_not_before = (_now() + timedelta(seconds=_delete_tombstone_seconds())).isoformat().replace("+00:00", "Z") if in_flight else None
            conn.execute(
                """update tenant_objects set status='delete_pending', delete_not_before=coalesce(delete_not_before, ?), updated_at=?
                   where bucket=? and object_key=?""",
                (delete_not_before, now, bucket, object_key),
            )
            return True

    def _mark_deleted(self, *, bucket: str, object_key: str) -> None:
        now = _now_iso()
        with self._transaction() as conn:
            row = conn.execute("select delete_not_before from tenant_objects where bucket=? and object_key=?", (bucket, object_key)).fetchone()
            status = "delete_pending" if row is not None and row["delete_not_before"] and _future(row["delete_not_before"]) else "deleted"
            conn.execute("update tenant_objects set status=?, last_delete_error=null, next_delete_attempt_at=null, updated_at=? where bucket=? and object_key=?", (status, now, bucket, object_key))

    def _mark_delete_failure(self, *, bucket: str, object_key: str, error: str) -> None:
        now = _now_iso()
        with self._transaction() as conn:
            row = conn.execute("select delete_attempts from tenant_objects where bucket=? and object_key=?", (bucket, object_key)).fetchone()
            attempts = int(row["delete_attempts"]) if row else 0
            delay = min(300, 5 * (2 ** min(attempts, 6)))
            next_attempt = (_now() + timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")
            conn.execute(
                """update tenant_objects set status='delete_failed', delete_attempts=delete_attempts+1,
                   next_delete_attempt_at=?, last_delete_error=?, updated_at=? where bucket=? and object_key=?""",
                (next_attempt, error, now, bucket, object_key),
            )

    def _delete_rows(self, object_rows: list[tuple[str, str]], object_store: DeletableObjectStore) -> dict[str, object]:
        deleted = 0
        failed = 0
        seen: set[tuple[str, str]] = set()
        for bucket, object_key in object_rows:
            item = (bucket, object_key)
            if item in seen:
                continue
            seen.add(item)
            if not self._claim_expired_object(bucket=bucket, object_key=object_key):
                continue
            try:
                object_store.delete_object(object_key)
            except Exception as exc:
                failed += 1
                self._mark_delete_failure(bucket=bucket, object_key=object_key, error=type(exc).__name__)
            else:
                deleted += 1
                self._mark_deleted(bucket=bucket, object_key=object_key)
        return {"deletedObjects": deleted, "failedObjects": failed}


class SQLiteProjectStore(_SQLiteBase):
    def __init__(self, path: str | Path, *, bucket: str | None = None) -> None:
        self.bucket = bucket or os.environ.get("SUPABASE_STORAGE_BUCKET") or "handwrite-font-jobs"
        super().__init__(path)
        self._tenant_store = SQLiteTenantStore(path)

    def list(self, *, owner_id: str) -> list[dict[str, object]]:
        self._expire_projects(owner_id=owner_id)
        now = _now_iso()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """select * from projects where owner_id=? and deleted_at is null and retention_expires_at>?
                   order by updated_at desc, id desc""",
                (owner_id, now),
            ).fetchall()
        return [_project_from_sqlite_row(row) for row in rows]

    def get(self, *, owner_id: str, project_id: str) -> dict[str, object]:
        self._expire_projects(owner_id=owner_id)
        now = _now_iso()
        with closing(self._connect()) as conn:
            row = conn.execute("select * from projects where id=? and owner_id=? and deleted_at is null and retention_expires_at>?", (project_id, owner_id, now)).fetchone()
            if row is None:
                raise ProjectNotFound("Project not found.")
        return _project_from_sqlite_row(row)

    def create(self, *, owner_id: str, payload: dict[str, object]) -> dict[str, object]:
        project = validate_project_payload(payload)
        retention = project_retention_expires_at()
        project_id = new_project_id()
        now = _now_iso()
        with self._transaction() as conn:
            self._tenant_store._ensure_and_lock_tenant(conn, owner_id)
            self._expire_projects_cur(conn, owner_id=owner_id)
            live = conn.execute("select count(*) from projects where owner_id=? and deleted_at is null and retention_expires_at>?", (owner_id, now)).fetchone()[0]
            if int(live) >= MAX_LIVE_PROJECTS:
                raise ProjectLimitExceeded("Live project limit exceeded.")
            self._validate_refs(conn, owner_id=owner_id, project=project)
            conn.execute(
                """insert into projects(id,owner_id,name,font,mode,target_characters,glyphs,sheet,last_job_id,revision,
                  retention_expires_at,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,1,?,?,?)""",
                (project_id, owner_id, project.name, json.dumps(project.font), project.mode, project.target_characters, json.dumps(project.glyphs), _json_dumps(project.sheet), project.last_job_id, retention, now, now),
            )
            self._replace_project_refs(conn, owner_id=owner_id, project_id=project_id, refs=project.object_refs, retention=retention)
            row = conn.execute("select * from projects where id=?", (project_id,)).fetchone()
        return _project_from_sqlite_row(row)

    def update(self, *, owner_id: str, project_id: str, payload: dict[str, object]) -> dict[str, object]:
        expected = payload.get("revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0:
            raise ProjectStoreError("revision is required.")
        project = validate_project_payload(payload)
        retention = project_retention_expires_at()
        now = _now_iso()
        with self._transaction() as conn:
            self._tenant_store._ensure_and_lock_tenant(conn, owner_id)
            self._expire_projects_cur(conn, owner_id=owner_id)
            row = conn.execute("select revision from projects where id=? and owner_id=? and deleted_at is null and retention_expires_at>?", (project_id, owner_id, now)).fetchone()
            if row is None:
                raise ProjectNotFound("Project not found.")
            if int(row["revision"]) != expected:
                raise ProjectConflict("Project revision conflict.")
            self._validate_refs(conn, owner_id=owner_id, project=project)
            conn.execute(
                """update projects set name=?, font=?, mode=?, target_characters=?, glyphs=?, sheet=?, last_job_id=?,
                   revision=revision+1, retention_expires_at=?, updated_at=? where id=? and owner_id=?""",
                (project.name, json.dumps(project.font), project.mode, project.target_characters, json.dumps(project.glyphs), _json_dumps(project.sheet), project.last_job_id, retention, now, project_id, owner_id),
            )
            self._replace_project_refs(conn, owner_id=owner_id, project_id=project_id, refs=project.object_refs, retention=retention)
            result = conn.execute("select * from projects where id=?", (project_id,)).fetchone()
        return _project_from_sqlite_row(result)

    def delete(self, *, owner_id: str, project_id: str, object_store: DeletableObjectStore | None = None) -> dict[str, object]:
        now = _now_iso()
        object_rows: list[tuple[str, str]] = []
        with self._transaction() as conn:
            self._tenant_store._ensure_and_lock_tenant(conn, owner_id)
            if conn.execute("select id from projects where id=? and owner_id=? and deleted_at is null", (project_id, owner_id)).fetchone() is None:
                raise ProjectNotFound("Project not found.")
            conn.execute("update projects set deleted_at=?, retention_expires_at=min(retention_expires_at, ?), updated_at=? where id=? and owner_id=?", (now, now, now, project_id, owner_id))
            old_refs = conn.execute("select bucket,object_key from tenant_project_object_refs where project_id=?", (project_id,)).fetchall()
            conn.execute("delete from tenant_project_object_refs where project_id=?", (project_id,))
            for row in old_refs:
                bucket, object_key = str(row["bucket"]), str(row["object_key"])
                if self._tenant_store._object_unprotected(conn, bucket=bucket, object_key=object_key, now=now):
                    object_rows.append((bucket, object_key))
                    conn.execute("update tenant_objects set retention_expires_at=min(retention_expires_at, ?), updated_at=? where bucket=? and object_key=?", (now, now, bucket, object_key))
        if object_store is None:
            return {"deletedObjects": 0, "failedObjects": 0}
        return self._tenant_store._delete_rows(object_rows, object_store)

    def _expire_projects(self, *, owner_id: str) -> None:
        with self._transaction() as conn:
            self._expire_projects_cur(conn, owner_id=owner_id)

    def _expire_projects_cur(self, conn: sqlite3.Connection, *, owner_id: str) -> None:
        now = _now_iso()
        conn.execute("update projects set deleted_at=coalesce(deleted_at, ?), updated_at=? where owner_id=? and deleted_at is null and retention_expires_at<=?", (now, now, owner_id, now))

    def _validate_refs(self, conn: sqlite3.Connection, *, owner_id: str, project) -> None:
        now = _now_iso()
        for photo in project.object_refs:
            row = conn.execute(
                """select 1 from tenant_objects where owner_id=? and bucket=? and object_key=? and status='uploaded'
                   and retention_expires_at>? and content_type=? and size_bytes=?""",
                (owner_id, self.bucket, photo.object_key, now, photo.content_type, photo.size_bytes),
            ).fetchone()
            if row is None:
                raise ObjectAccessError("Project object is missing, expired, has changed metadata, or belongs to another user.")
        if project.last_job_id is not None:
            row = conn.execute("select 1 from jobs where id=? and owner_id=?", (project.last_job_id, owner_id)).fetchone()
            if row is None:
                raise OwnershipError("lastJobId is not owned by this user.")

    def _replace_project_refs(self, conn: sqlite3.Connection, *, owner_id: str, project_id: str, refs: tuple[InputPhoto, ...], retention: str) -> None:
        now = _now_iso()
        conn.execute("delete from tenant_project_object_refs where project_id=?", (project_id,))
        for photo in refs:
            conn.execute(
                """insert into tenant_project_object_refs(owner_id,bucket,object_key,project_id,retention_expires_at,created_at,updated_at)
                   values(?,?,?,?,?,?,?) on conflict(bucket,object_key,project_id) do update set retention_expires_at=excluded.retention_expires_at, updated_at=excluded.updated_at""",
                (owner_id, self.bucket, photo.object_key, project_id, retention, now, now),
            )
            conn.execute("update tenant_objects set retention_expires_at=max(retention_expires_at, ?), updated_at=? where owner_id=? and bucket=? and object_key=?", (retention, now, owner_id, self.bucket, photo.object_key))


class SQLiteFeedbackStore(_SQLiteBase):
    def submit_value(self, owner_id: str, value: dict[str, str], *, event: bool) -> None:
        today = date.today().isoformat()
        now = _now_iso()
        expires = (_now() + timedelta(days=30)).isoformat().replace("+00:00", "Z")
        with self._transaction() as conn:
            now_for_tenant = now
            conn.execute(
                "insert into tenants(owner_id,status,created_at,updated_at) values(?, 'active', ?, ?) on conflict(owner_id) do update set updated_at=excluded.updated_at",
                (owner_id, now_for_tenant, now_for_tenant),
            )
            if conn.execute("select owner_id from tenants where owner_id=? and status='active'", (owner_id,)).fetchone() is None:
                raise OwnershipError("Tenant is disabled or missing.")
            if event:
                total = conn.execute("select coalesce(sum(count),0) from beta_events_daily where owner_id=? and usage_date=?", (owner_id, today)).fetchone()[0]
                if int(total) >= 500:
                    raise QuotaExceeded("Daily usage-count limit reached.")
                conn.execute(
                    """insert into beta_events_daily(owner_id,usage_date,event,count,created_at,updated_at) values(?,?,?,?,?,?)
                       on conflict(owner_id,usage_date,event) do update set count=count+1, updated_at=excluded.updated_at""",
                    (owner_id, today, value["event"], 1, now, now),
                )
            else:
                count = conn.execute("select count(*) from beta_feedback where owner_id=? and created_at>=?", (owner_id, today)).fetchone()[0]
                if int(count) >= 10:
                    raise QuotaExceeded("Daily feedback limit reached.")
                conn.execute(
                    "insert into beta_feedback(id,owner_id,topic,message,created_at,expires_at) values(?,?,?,?,?,?)",
                    (str(uuid4()), owner_id, value["topic"], value["message"], now, expires),
                )

    def cleanup(self) -> None:
        today = date.today().isoformat()
        now = _now_iso()
        with self._transaction() as conn:
            conn.execute("delete from beta_feedback where expires_at<=?", (now,))
            conn.execute("delete from beta_events_daily where usage_date<=date(?, '-30 day')", (today,))


def _job_from_sqlite_row(row: sqlite3.Row, warnings: list[JobWarning], artifacts: list[JobArtifact]) -> JobRecord:
    error = None
    if row["error_code"]:
        error = JobError(
            code=HardErrorCode(str(row["error_code"])),
            message=str(row["error_message"] or ""),
            retryable=bool(row["error_retryable"]),
            details=_json_loads(row["error_details"], {}),  # type: ignore[arg-type]
        )
    return JobRecord(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]) if row["owner_id"] else None,
        attempt_id=str(row["attempt_id"]) if row["attempt_id"] else None,
        lease_owner=str(row["lease_owner"]) if row["lease_owner"] else None,
        attempt_count=int(row["attempt_count"] or 0),
        input_photo=InputPhoto(object_key=str(row["input_path"]), bucket=str(row["input_bucket"]), content_type=str(row["input_content_type"]), size_bytes=int(row["input_size_bytes"])),
        font=FontRequest(font_name=str(row["font_name"]), family_name=str(row["family_name"]), style_name=str(row["style_name"])),
        capture=capture_from_json(_json_loads(row["capture_config"], None)),
        status=JobStatus(str(row["status"])),
        stage=JobStage(str(row["stage"])),
        warnings=warnings,
        artifacts=artifacts,
        error=error,
        retention_expires_at=str(row["retention_expires_at"]),
    )


def _project_from_sqlite_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "revision": int(row["revision"]),
        "createdAt": _project_dt_to_iso(row["created_at"]),
        "updatedAt": _project_dt_to_iso(row["updated_at"]),
        "retentionExpiresAt": _project_dt_to_iso(row["retention_expires_at"]),
        "name": str(row["name"]),
        "font": _json_loads(row["font"], {}),
        "mode": str(row["mode"]),
        "targetCharacters": str(row["target_characters"]),
        "glyphs": _json_loads(row["glyphs"], []),
        "sheet": _json_loads(row["sheet"], None),
        "lastJobId": row["last_job_id"],
    }


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','expired')),
  stage TEXT NOT NULL,
  font_name TEXT NOT NULL,
  family_name TEXT NOT NULL,
  style_name TEXT NOT NULL DEFAULT 'Regular',
  input_bucket TEXT NOT NULL,
  input_path TEXT NOT NULL,
  input_content_type TEXT NOT NULL,
  input_size_bytes INTEGER NOT NULL,
  capture_config TEXT,
  error_code TEXT,
  error_message TEXT,
  error_retryable INTEGER,
  error_details TEXT NOT NULL DEFAULT '{}',
  lease_owner TEXT,
  lease_expires_at TEXT,
  retention_expires_at TEXT NOT NULL,
  owner_id TEXT,
  attempt_id TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  delete_requested_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE TABLE IF NOT EXISTS job_warnings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  glyph TEXT,
  message TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'warning',
  details TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  label TEXT NOT NULL,
  bucket TEXT NOT NULL,
  path TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status_created_idx ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS jobs_retention_expires_idx ON jobs(retention_expires_at);
CREATE INDEX IF NOT EXISTS jobs_owner_idx ON jobs(owner_id, created_at);
CREATE INDEX IF NOT EXISTS jobs_running_lease_idx ON jobs(lease_expires_at);

CREATE TABLE IF NOT EXISTS tenants (
  owner_id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenant_daily_usage (
  owner_id TEXT NOT NULL REFERENCES tenants(owner_id) ON DELETE CASCADE,
  usage_date TEXT NOT NULL,
  uploads_count INTEGER NOT NULL DEFAULT 0 CHECK (uploads_count >= 0),
  upload_bytes INTEGER NOT NULL DEFAULT 0 CHECK (upload_bytes >= 0),
  previews_count INTEGER NOT NULL DEFAULT 0 CHECK (previews_count >= 0),
  builds_count INTEGER NOT NULL DEFAULT 0 CHECK (builds_count >= 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (owner_id, usage_date)
);
CREATE TABLE IF NOT EXISTS tenant_objects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id TEXT NOT NULL REFERENCES tenants(owner_id) ON DELETE CASCADE,
  bucket TEXT NOT NULL,
  object_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
  job_id TEXT,
  status TEXT NOT NULL DEFAULT 'registered' CHECK (status IN ('registered','uploading','uploaded','delete_pending','deleted','delete_failed')),
  retention_expires_at TEXT NOT NULL,
  delete_attempts INTEGER NOT NULL DEFAULT 0 CHECK (delete_attempts >= 0),
  last_delete_error TEXT,
  delete_not_before TEXT,
  next_delete_attempt_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(bucket, object_key)
);
CREATE TABLE IF NOT EXISTS tenant_object_job_refs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id TEXT NOT NULL REFERENCES tenants(owner_id) ON DELETE CASCADE,
  bucket TEXT NOT NULL,
  object_key TEXT NOT NULL,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  retention_expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(bucket, object_key, job_id)
);
CREATE INDEX IF NOT EXISTS tenant_objects_owner_key_idx ON tenant_objects(owner_id, bucket, object_key);
CREATE INDEX IF NOT EXISTS tenant_objects_job_idx ON tenant_objects(job_id);
CREATE INDEX IF NOT EXISTS tenant_objects_retention_idx ON tenant_objects(retention_expires_at, status);
CREATE INDEX IF NOT EXISTS tenant_object_refs_object_idx ON tenant_object_job_refs(bucket, object_key);
CREATE INDEX IF NOT EXISTS tenant_object_refs_job_idx ON tenant_object_job_refs(job_id);
CREATE INDEX IF NOT EXISTS tenant_usage_owner_date_idx ON tenant_daily_usage(owner_id, usage_date);
CREATE INDEX IF NOT EXISTS jobs_owner_retention_idx ON jobs(owner_id, retention_expires_at);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES tenants(owner_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  font TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('guided','markerless','legacy')),
  target_characters TEXT NOT NULL,
  glyphs TEXT NOT NULL DEFAULT '[]',
  sheet TEXT,
  last_job_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  retention_expires_at TEXT NOT NULL,
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenant_project_object_refs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id TEXT NOT NULL REFERENCES tenants(owner_id) ON DELETE CASCADE,
  bucket TEXT NOT NULL,
  object_key TEXT NOT NULL,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  retention_expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(bucket, object_key, project_id)
);
CREATE INDEX IF NOT EXISTS projects_owner_retention_idx ON projects(owner_id, retention_expires_at);
CREATE INDEX IF NOT EXISTS projects_updated_idx ON projects(owner_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS tenant_project_refs_object_idx ON tenant_project_object_refs(bucket, object_key);
CREATE INDEX IF NOT EXISTS tenant_project_refs_project_idx ON tenant_project_object_refs(project_id);

CREATE TABLE IF NOT EXISTS beta_feedback (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES tenants(owner_id) ON DELETE CASCADE,
  topic TEXT NOT NULL CHECK (topic IN ('extraction','installation','other')),
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS beta_feedback_owner_created ON beta_feedback(owner_id, created_at);
CREATE TABLE IF NOT EXISTS beta_events_daily (
  owner_id TEXT NOT NULL REFERENCES tenants(owner_id) ON DELETE CASCADE,
  usage_date TEXT NOT NULL,
  event TEXT NOT NULL CHECK (event IN ('upload_complete','glyph_accepted','build_succeeded','font_download_requested','font_used')),
  count INTEGER NOT NULL DEFAULT 1 CHECK (count BETWEEN 1 AND 500),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(owner_id, usage_date, event)
);
"""
