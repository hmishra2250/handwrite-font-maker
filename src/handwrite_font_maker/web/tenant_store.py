from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .contracts import CaptureConfig, FontRequest, InputPhoto, capture_to_json, is_safe_object_key, new_job_id, retention_expires_at
from .security import RuntimeConfig, load_runtime_config


class TenantStoreError(RuntimeError):
    status = 400
    code = "TENANT_ERROR"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class QuotaExceeded(TenantStoreError):
    status = 429
    code = "QUOTA_EXCEEDED"


class OwnershipError(TenantStoreError):
    status = 404
    code = "JOB_EXPIRED"


class ObjectAccessError(TenantStoreError):
    status = 400
    code = "UPLOAD_OBJECT_MISSING"


@dataclass(frozen=True)
class TenantLimits:
    daily_upload_limit: int
    daily_upload_bytes_limit: int
    daily_preview_limit: int
    daily_build_limit: int
    active_job_limit: int

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> "TenantLimits":
        return cls(
            daily_upload_limit=config.daily_upload_limit,
            daily_upload_bytes_limit=config.daily_upload_bytes_limit,
            daily_preview_limit=config.daily_preview_limit,
            daily_build_limit=config.daily_build_limit,
            active_job_limit=config.active_job_limit,
        )


@dataclass(frozen=True)
class RegisteredObject:
    owner_id: str
    bucket: str
    object_key: str
    kind: str
    content_type: str
    size_bytes: int
    retention_expires_at: str
    job_id: str | None = None


class DeletableObjectStore(Protocol):
    def delete_object(self, object_key: str) -> None: ...


def _delete_tombstone_seconds() -> int:
    try:
        job_timeout = int(os.environ.get("JOB_TIMEOUT_SECONDS", "600"))
    except ValueError:
        job_timeout = 600
    try:
        storage_grace = int(os.environ.get("STORAGE_DELETE_GRACE_SECONDS", "120"))
    except ValueError:
        storage_grace = 120
    return max(0, job_timeout) + max(0, storage_grace)


class PostgresTenantStore:
    def __init__(self, database_url: str | None = None) -> None:
        import psycopg

        self.database_url = database_url or os.environ.get("DATABASE_URL") or ""
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for tenant storage.")
        self._psycopg = psycopg

    def _connect(self):
        return self._psycopg.connect(
            self.database_url,
            connect_timeout=5,
            options="-c statement_timeout=5000 -c lock_timeout=2000",
        )

    def ready_check(self) -> dict[str, object]:
        required_tables = {"jobs", "projects", "tenant_daily_usage", "tenant_objects", "tenant_object_job_refs", "tenant_project_object_refs", "tenants"}
        required_job_columns = {"owner_id", "retention_expires_at", "status"}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select table_name from information_schema.tables where table_schema='public'")
            tables = {str(row[0]) for row in cur.fetchall()}
            cur.execute("select column_name from information_schema.columns where table_schema='public' and table_name='jobs'")
            job_columns = {str(row[0]) for row in cur.fetchall()}
            cur.execute("select 1")
            cur.fetchone()
        missing_tables = sorted(required_tables - tables)
        missing_job_columns = sorted(required_job_columns - job_columns)
        ok = not missing_tables and not missing_job_columns
        return {"ok": ok, "missingTables": missing_tables, "missingJobColumns": missing_job_columns}

    def ensure_tenant(self, owner_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into tenants (owner_id) values (%s::uuid) on conflict (owner_id) do update set updated_at=now()",
                (owner_id,),
            )

    def _ensure_and_lock_tenant(self, cur, owner_id: str) -> None:
        cur.execute(
            "insert into tenants (owner_id) values (%s::uuid) on conflict (owner_id) do update set updated_at=now()",
            (owner_id,),
        )
        cur.execute("select owner_id from tenants where owner_id=%s::uuid and status='active' for update", (owner_id,))
        if cur.fetchone() is None:
            raise OwnershipError("Tenant is disabled or missing.")

    def register_upload(self, *, owner_id: str, bucket: str, object_key: str, content_type: str, size_bytes: int, limits: TenantLimits, expires_at: str | None = None) -> RegisteredObject:
        if not is_safe_object_key(object_key):
            raise ObjectAccessError("Invalid object key.")
        if limits.daily_upload_limit <= 0 or limits.daily_upload_bytes_limit < size_bytes:
            raise QuotaExceeded("Daily upload quota exceeded.")
        expires_at = expires_at or retention_expires_at(24)
        today = date.today().isoformat()
        with self._connect() as conn, conn.cursor() as cur:
            self._ensure_and_lock_tenant(cur, owner_id)
            cur.execute(
                """
                insert into tenant_daily_usage (owner_id, usage_date, uploads_count, upload_bytes)
                values (%s::uuid, %s::date, 1, %s)
                on conflict (owner_id, usage_date) do update set
                  uploads_count = tenant_daily_usage.uploads_count + 1,
                  upload_bytes = tenant_daily_usage.upload_bytes + excluded.upload_bytes,
                  updated_at = now()
                where tenant_daily_usage.uploads_count < %s
                  and tenant_daily_usage.upload_bytes + excluded.upload_bytes <= %s
                returning uploads_count, upload_bytes
                """,
                (owner_id, today, size_bytes, limits.daily_upload_limit, limits.daily_upload_bytes_limit),
            )
            if cur.fetchone() is None:
                raise QuotaExceeded("Daily upload quota exceeded.")
            cur.execute(
                """
                insert into tenant_objects (owner_id, bucket, object_key, kind, content_type, size_bytes, retention_expires_at)
                values (%s::uuid, %s, %s, 'upload', %s, %s, %s::timestamptz)
                on conflict (bucket, object_key) do update set updated_at=tenant_objects.updated_at
                where tenant_objects.owner_id=excluded.owner_id and tenant_objects.status='registered'
                returning owner_id, bucket, object_key, kind, content_type, size_bytes, retention_expires_at, job_id
                """,
                (owner_id, bucket, object_key, content_type, size_bytes, expires_at),
            )
            row = cur.fetchone()
            if row is None:
                raise ObjectAccessError("Upload object key is already registered.")
        return _registered_from_row(row)

    def mark_uploaded(self, *, owner_id: str, bucket: str, object_key: str, size_bytes: int | None = None) -> None:
        rescheduled_deleted_upload = False
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update tenant_objects set status='uploaded', size_bytes=coalesce(%s, size_bytes), updated_at=now()
                where owner_id=%s::uuid and bucket=%s and object_key=%s and retention_expires_at>now() and status in ('registered','uploading')
                returning status
                """,
                (size_bytes, owner_id, bucket, object_key),
            )
            if cur.fetchone() is not None:
                return
            cur.execute(
                """
                update tenant_objects set status='delete_failed', retention_expires_at=least(retention_expires_at, now()),
                  last_delete_error='Upload completed after deletion request.', updated_at=now()
                where owner_id=%s::uuid and bucket=%s and object_key=%s and status='deleted'
                returning status
                """,
                (owner_id, bucket, object_key),
            )
            if cur.fetchone() is not None:
                rescheduled_deleted_upload = True
            else:
                raise ObjectAccessError("Upload object is not registered to this user.")
        if rescheduled_deleted_upload:
            raise ObjectAccessError("Upload completed after deletion and was scheduled for cleanup.")

    def assert_object_access(self, *, owner_id: str, bucket: str, object_key: str, require_uploaded: bool = True) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select 1 from tenant_objects o
                where o.owner_id=%s::uuid and o.bucket=%s and o.object_key=%s
                  and o.retention_expires_at>now() and o.status <> 'deleted'
                  and (%s = false or o.status='uploaded')
                  and (
                    %s = false
                    or o.kind = 'upload'
                    or (
                      o.kind like '%%artifact:%%'
                      and exists (
                        select 1 from job_artifacts a
                        join jobs j on j.id=a.job_id
                        where a.bucket=o.bucket and a.path=o.object_key
                          and j.owner_id=o.owner_id and j.status='succeeded'
                          and j.retention_expires_at>now()
                      )
                    )
                  )
                """,
                (owner_id, bucket, object_key, require_uploaded, require_uploaded),
            )
            if cur.fetchone() is None:
                raise ObjectAccessError("Upload object is missing, expired, or belongs to another user.")

    def assert_upload_intent(self, *, owner_id: str, bucket: str, object_key: str) -> RegisteredObject:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select owner_id, bucket, object_key, kind, content_type, size_bytes, retention_expires_at, job_id
                from tenant_objects
                where owner_id=%s::uuid and bucket=%s and object_key=%s
                  and retention_expires_at>now() and status='registered'
                """,
                (owner_id, bucket, object_key),
            )
            row = cur.fetchone()
            if row is None:
                raise ObjectAccessError("Upload object is not awaiting bytes for this user.")
            return _registered_from_row(row)

    def claim_upload_intent(self, *, owner_id: str, bucket: str, object_key: str) -> RegisteredObject:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update tenant_objects set status='uploading', updated_at=now()
                where owner_id=%s::uuid and bucket=%s and object_key=%s
                  and retention_expires_at>now() and status='registered'
                returning owner_id, bucket, object_key, kind, content_type, size_bytes, retention_expires_at, job_id
                """,
                (owner_id, bucket, object_key),
            )
            row = cur.fetchone()
            if row is None:
                raise ObjectAccessError("Upload object is not awaiting bytes for this user.")
            return _registered_from_row(row)

    def record_preview(self, *, owner_id: str, limits: TenantLimits) -> None:
        if limits.daily_preview_limit <= 0:
            raise QuotaExceeded("Daily preview quota exceeded.")
        today = date.today().isoformat()
        with self._connect() as conn, conn.cursor() as cur:
            self._ensure_and_lock_tenant(cur, owner_id)
            cur.execute(
                """
                insert into tenant_daily_usage (owner_id, usage_date, previews_count)
                values (%s::uuid, %s::date, 1)
                on conflict (owner_id, usage_date) do update set
                  previews_count = tenant_daily_usage.previews_count + 1,
                  updated_at = now()
                where tenant_daily_usage.previews_count < %s
                returning previews_count
                """,
                (owner_id, today, limits.daily_preview_limit),
            )
            if cur.fetchone() is None:
                raise QuotaExceeded("Daily preview quota exceeded.")

    def create_job(
        self,
        *,
        owner_id: str,
        input_photo: InputPhoto,
        font: FontRequest,
        capture: CaptureConfig | None,
        bucket: str,
        limits: TenantLimits,
    ):
        from .job_store import JobRecord

        object_keys = _capture_object_keys(input_photo, capture)
        job = JobRecord(id=new_job_id(), input_photo=input_photo, font=font, capture=capture, owner_id=owner_id)
        today = date.today().isoformat()
        with self._connect() as conn, conn.cursor() as cur:
            if limits.daily_build_limit <= 0 or limits.active_job_limit <= 0:
                raise QuotaExceeded("Daily build quota exceeded.")
            self._ensure_and_lock_tenant(cur, owner_id)
            cur.execute(
                """
                select count(*) from jobs
                where owner_id=%s::uuid and status in ('queued','running') and retention_expires_at>now()
                """,
                (owner_id,),
            )
            if int(cur.fetchone()[0]) >= limits.active_job_limit:
                raise QuotaExceeded("Active job quota exceeded.")
            cur.execute(
                """
                insert into tenant_daily_usage (owner_id, usage_date, builds_count)
                values (%s::uuid, %s::date, 1)
                on conflict (owner_id, usage_date) do update set
                  builds_count = tenant_daily_usage.builds_count + 1,
                  updated_at = now()
                where tenant_daily_usage.builds_count < %s
                returning builds_count
                """,
                (owner_id, today, limits.daily_build_limit),
            )
            if cur.fetchone() is None:
                raise QuotaExceeded("Daily build quota exceeded.")
            for object_key in object_keys:
                cur.execute(
                    """
                    select 1 from tenant_objects
                    where owner_id=%s::uuid and bucket=%s and object_key=%s
                      and retention_expires_at>now() and status='uploaded'
                    """,
                    (owner_id, bucket, object_key),
                )
                if cur.fetchone() is None:
                    raise ObjectAccessError("All job objects must be registered to the authenticated user.")
            cur.execute(
                """
                insert into jobs (id, status, stage, font_name, family_name, style_name,
                  input_bucket, input_path, input_content_type, input_size_bytes, capture_config,
                  retention_expires_at, owner_id)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::timestamptz,%s::uuid)
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
                    json.dumps(capture_to_json(capture)),
                    job.retention_expires_at,
                    owner_id,
                ),
            )
            cur.execute(
                """
                update tenant_objects set job_id=%s, retention_expires_at=greatest(retention_expires_at, %s::timestamptz), updated_at=now()
                where owner_id=%s::uuid and bucket=%s and object_key = any(%s)
                """,
                (job.id, job.retention_expires_at, owner_id, bucket, object_keys),
            )
            for object_key in object_keys:
                cur.execute(
                    """
                    insert into tenant_object_job_refs (owner_id, bucket, object_key, job_id, retention_expires_at)
                    values (%s::uuid,%s,%s,%s,%s::timestamptz)
                    on conflict (bucket, object_key, job_id) do update set
                      retention_expires_at=excluded.retention_expires_at, updated_at=now()
                    """,
                    (owner_id, bucket, object_key, job.id, job.retention_expires_at),
                )
        return job

    def authorize_job(self, *, owner_id: str, job_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select owner_id, retention_expires_at, status, delete_requested_at from jobs where id=%s", (job_id,))
            row = cur.fetchone()
            if row is None or str(row[0]) != owner_id:
                raise OwnershipError("Job not found.")
            if str(row[2]) == "expired" or row[3] is not None or _as_utc(row[1]) <= datetime.now(timezone.utc):
                cur.execute("update jobs set status='expired', updated_at=now(), completed_at=coalesce(completed_at, now()) where id=%s", (job_id,))
                raise OwnershipError("Job expired.")

    def delete_job(self, *, owner_id: str, job_id: str, object_store: DeletableObjectStore) -> dict[str, object]:
        self.authorize_job(owner_id=owner_id, job_id=job_id)
        with self._connect() as conn, conn.cursor() as cur:
            self._ensure_and_lock_tenant(cur, owner_id)
            cur.execute(
                """
                update jobs set status='expired', lease_owner=null, lease_expires_at=null, delete_requested_at=now(),
                  retention_expires_at=least(retention_expires_at, now()),
                  completed_at=coalesce(completed_at, now()), updated_at=now()
                where id=%s and owner_id=%s::uuid
                """,
                (job_id, owner_id),
            )
            cur.execute(
                """
                select o.bucket, o.object_key from tenant_objects o
                where o.owner_id=%s::uuid and o.status <> 'deleted'
                  and exists (
                    select 1 from tenant_object_job_refs r
                    where r.bucket=o.bucket and r.object_key=o.object_key and r.job_id=%s
                  )
                  and not exists (
                    select 1 from tenant_object_job_refs r
                    join jobs j on j.id=r.job_id
                    where r.bucket=o.bucket and r.object_key=o.object_key and r.job_id<>%s
                      and j.status in ('queued','running','succeeded')
                      and j.retention_expires_at>now()
                  )
                  and not exists (
                    select 1 from tenant_project_object_refs pr
                    join projects p on p.id=pr.project_id
                    where pr.bucket=o.bucket and pr.object_key=o.object_key
                      and p.deleted_at is null and p.retention_expires_at>now()
                  )
                order by o.created_at
                """,
                (owner_id, job_id, job_id),
            )
            object_rows = cur.fetchall()
            cur.execute("select bucket, path from job_artifacts where job_id=%s", (job_id,))
            object_rows.extend(cur.fetchall())
            for bucket, object_key in object_rows:
                cur.execute(
                    "update tenant_objects set retention_expires_at=least(retention_expires_at, now()), updated_at=now() where bucket=%s and object_key=%s",
                    (bucket, object_key),
                )
        deleted = 0
        failed = 0
        seen: set[tuple[str, str]] = set()
        for bucket, object_key in object_rows:
            item = (str(bucket), str(object_key))
            if item in seen:
                continue
            seen.add(item)
            if not self._claim_expired_object(bucket=str(bucket), object_key=str(object_key)):
                continue
            try:
                object_store.delete_object(str(object_key))
            except Exception as exc:  # cleanup is retryable; expose count, not secrets
                failed += 1
                self._mark_delete_failure(bucket=str(bucket), object_key=str(object_key), error=type(exc).__name__)
            else:
                deleted += 1
                self._mark_deleted(bucket=str(bucket), object_key=str(object_key))
        return {"deletedObjects": deleted, "failedObjects": failed}

    def cleanup_expired(self, *, object_store: DeletableObjectStore, limit: int = 100) -> dict[str, object]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update jobs set status='expired', lease_owner=null, lease_expires_at=null,
                  completed_at=coalesce(completed_at, now()), updated_at=now()
                where retention_expires_at<=now() and status <> 'expired'
                """
            )
            cur.execute(
                "update projects set deleted_at=coalesce(deleted_at, now()), updated_at=now() where deleted_at is null and retention_expires_at<=now()"
            )
            cur.execute(
                "delete from tenant_project_object_refs using projects p where tenant_project_object_refs.project_id=p.id and (p.deleted_at is not null or p.retention_expires_at<=now())"
            )
            cur.execute(
                "delete from projects where deleted_at is not null and retention_expires_at<=now()"
            )
            cur.execute(
                """
                select o.bucket, o.object_key from tenant_objects o
                where o.retention_expires_at<=now() and o.status <> 'deleted'
                  and (o.next_delete_attempt_at is null or o.next_delete_attempt_at<=now())
                  and not exists (
                    select 1 from tenant_object_job_refs r
                    join jobs j on j.id=r.job_id
                    where r.bucket=o.bucket and r.object_key=o.object_key
                      and j.status in ('queued','running','succeeded')
                      and j.retention_expires_at>now()
                  )
                  and not exists (
                    select 1 from tenant_project_object_refs pr
                    join projects p on p.id=pr.project_id
                    where pr.bucket=o.bucket and pr.object_key=o.object_key
                      and p.deleted_at is null and p.retention_expires_at>now()
                  )
                order by retention_expires_at, delete_attempts limit %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        deleted = 0
        failed = 0
        for bucket, object_key in rows:
            if not self._claim_expired_object(bucket=str(bucket), object_key=str(object_key)):
                continue
            try:
                object_store.delete_object(str(object_key))
            except Exception as exc:
                failed += 1
                self._mark_delete_failure(bucket=str(bucket), object_key=str(object_key), error=type(exc).__name__)
            else:
                deleted += 1
                self._mark_deleted(bucket=str(bucket), object_key=str(object_key))
        return {"deletedObjects": deleted, "failedObjects": failed}

    def register_artifact(
        self,
        *,
        owner_id: str,
        job_id: str,
        bucket: str,
        object_key: str,
        content_type: str,
        size_bytes: int,
        kind: str = "artifact",
        expires_at: str | None = None,
        attempt_id: str | None = None,
        lease_owner: str | None = None,
    ) -> None:
        if not is_safe_object_key(object_key):
            raise ObjectAccessError("Invalid object key.")
        expires_at = expires_at or retention_expires_at(24)
        with self._connect() as conn, conn.cursor() as cur:
            self._assert_live_job_attempt(cur, owner_id=owner_id, job_id=job_id, attempt_id=attempt_id, lease_owner=lease_owner)
            cur.execute(
                """
                insert into tenant_objects (owner_id, bucket, object_key, kind, content_type, size_bytes, job_id, status, retention_expires_at)
                values (%s::uuid,%s,%s,%s,%s,%s,%s,'registered',%s::timestamptz)
                on conflict (bucket, object_key) do update set
                  owner_id=excluded.owner_id, kind=excluded.kind, content_type=excluded.content_type,
                  size_bytes=excluded.size_bytes, job_id=excluded.job_id, status='registered',
                  retention_expires_at=excluded.retention_expires_at, updated_at=now()
                where tenant_objects.owner_id=excluded.owner_id
                """,
                (owner_id, bucket, object_key, kind, content_type, size_bytes, job_id, expires_at),
            )
            if cur.rowcount != 1:
                raise ObjectAccessError("Artifact object key is already registered.")
            cur.execute(
                """
                insert into tenant_object_job_refs (owner_id, bucket, object_key, job_id, retention_expires_at)
                values (%s::uuid,%s,%s,%s,%s::timestamptz)
                on conflict (bucket, object_key, job_id) do update set
                  retention_expires_at=excluded.retention_expires_at, updated_at=now()
                """,
                (owner_id, bucket, object_key, job_id, expires_at),
            )

    def mark_artifact_uploaded(self, *, owner_id: str, bucket: str, object_key: str, size_bytes: int | None = None) -> None:
        self.mark_uploaded(owner_id=owner_id, bucket=bucket, object_key=object_key, size_bytes=size_bytes)

    def _assert_live_job_attempt(self, cur, *, owner_id: str, job_id: str, attempt_id: str | None, lease_owner: str | None) -> None:
        if not attempt_id or not lease_owner:
            raise OwnershipError("Artifact registration requires a live leased job attempt.")
        cur.execute(
            """
            select 1 from jobs where id=%s and owner_id=%s::uuid
              and status='running' and retention_expires_at>now()
              and attempt_id=%s and lease_owner=%s and lease_expires_at>now()
            for update
            """,
            (job_id, owner_id, attempt_id, lease_owner),
        )
        if cur.fetchone() is None:
            raise OwnershipError("Job attempt is no longer live.")

    def _claim_expired_object(self, *, bucket: str, object_key: str) -> bool:
        # Serialize with create_job's tenant lock, then recheck after any retention
        # extension. Commit the non-admissible state BEFORE the external delete.
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select owner_id from tenant_objects where bucket=%s and object_key=%s", (bucket, object_key))
            row = cur.fetchone()
            if row is None:
                return False
            cur.execute("select owner_id from tenants where owner_id=%s for update", (row[0],))
            cur.execute(
                """
                select o.status from tenant_objects o
                where o.bucket=%s and o.object_key=%s and o.status <> 'deleted'
                  and o.retention_expires_at<=now()
                  and (o.next_delete_attempt_at is null or o.next_delete_attempt_at<=now())
                  and not exists (
                    select 1 from tenant_object_job_refs r join jobs j on j.id=r.job_id
                    where r.bucket=o.bucket and r.object_key=o.object_key
                      and j.status in ('queued','running','succeeded') and j.retention_expires_at>now()
                  )
                  and not exists (
                    select 1 from tenant_project_object_refs pr join projects p on p.id=pr.project_id
                    where pr.bucket=o.bucket and pr.object_key=o.object_key
                      and p.deleted_at is null and p.retention_expires_at>now()
                  )
                for update of o
                """,
                (bucket, object_key),
            )
            row = cur.fetchone()
            if row is None:
                return False
            in_flight = str(row[0]) in {'registered', 'uploading'}
            cur.execute(
                """
                update tenant_objects set status='delete_pending',
                  delete_not_before=coalesce(delete_not_before, now() + (%s * interval '1 second')),
                  updated_at=now()
                where bucket=%s and object_key=%s
                """,
                (_delete_tombstone_seconds() if in_flight else 0, bucket, object_key),
            )
            return True

    def _mark_deleted(self, *, bucket: str, object_key: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update tenant_objects set
                  status=case when delete_not_before>now() then 'delete_pending' else 'deleted' end,
                  last_delete_error=null, next_delete_attempt_at=null, updated_at=now()
                where bucket=%s and object_key=%s
                """,
                (bucket, object_key),
            )

    def _mark_delete_failure(self, *, bucket: str, object_key: str, error: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update tenant_objects set status='delete_failed', delete_attempts=delete_attempts+1,
                  next_delete_attempt_at=now() + (least(300, 5 * power(2, least(delete_attempts, 6))) * interval '1 second'),
                  last_delete_error=%s, updated_at=now() where bucket=%s and object_key=%s
                """,
                (error, bucket, object_key),
            )


def _registered_from_row(row: tuple[object, ...]) -> RegisteredObject:
    return RegisteredObject(
        owner_id=str(row[0]),
        bucket=str(row[1]),
        object_key=str(row[2]),
        kind=str(row[3]),
        content_type=str(row[4]),
        size_bytes=int(row[5]),
        retention_expires_at=_dt_to_iso(row[6]),
        job_id=str(row[7]) if row[7] else None,
    )


def _capture_object_keys(input_photo: InputPhoto, capture: CaptureConfig | None) -> list[str]:
    keys = [input_photo.object_key]
    if getattr(capture, "mode", None) == "guided":
        keys = [glyph.input_photo.object_key for glyph in capture.glyphs]  # type: ignore[union-attr]
    return sorted(set(keys))


def _dt_to_iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _as_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class WorkerArtifactRegistry:
    """Small worker-facing registry for attempt artifacts before/after final publication.

    Worker contract:
    - Construct with ``WorkerArtifactRegistry(job)`` or ``WorkerArtifactRegistry.from_env()``.
    - Call ``register_attempt_artifact(job, object_key=..., content_type=..., size_bytes=..., kind=...)`` immediately before each object upload.
    - Call ``mark_uploaded(job, object_key=..., size_bytes=...)`` after the upload succeeds.
    - The methods derive ``owner_id`` from ``job.owner_id`` and verify the active job attempt before registering cleanup-visible intent.
    """

    def __init__(self, job=None, database_url: str | None = None, *, bucket: str | None = None) -> None:
        if isinstance(job, str) and database_url is None:
            database_url = job
            job = None
        self.job = job
        self.config = load_runtime_config()
        if getattr(self.config.mode, "value", None) == "private_alpha":
            from .sqlite_store import SQLiteTenantStore

            self.store = SQLiteTenantStore(self.config.alpha_database_path or "")
        else:
            self.store = PostgresTenantStore(database_url or self.config.database_url)
        self.bucket = bucket or self.config.storage_bucket

    @classmethod
    def from_env(cls) -> "WorkerArtifactRegistry":
        return cls()

    def register_attempt_artifact(self, job=None, *, object_key: str, content_type: str, size_bytes: int, kind: str = "artifact") -> None:
        job = job or self.job
        if job is None:
            raise OwnershipError("Artifact registration requires a job.")
        owner_id = getattr(job, "owner_id", None)
        if not owner_id:
            return
        attempt_id = getattr(job, "attempt_id", None)
        lease_owner = getattr(job, "lease_owner", None)
        registry_kind = f"attempt_artifact:{kind}" if attempt_id else f"artifact:{kind}"
        self.store.register_artifact(
            owner_id=str(owner_id),
            job_id=str(job.id),
            bucket=getattr(job.input_photo, "bucket", None) or self.bucket,
            object_key=object_key,
            content_type=content_type,
            size_bytes=size_bytes,
            kind=registry_kind[:40],
            expires_at=getattr(job, "retention_expires_at", None),
            attempt_id=str(attempt_id) if attempt_id else None,
            lease_owner=str(lease_owner) if lease_owner else None,
        )

    def mark_uploaded(self, job=None, *, object_key: str, size_bytes: int | None = None) -> None:
        job = job or self.job
        if job is None:
            raise OwnershipError("Artifact upload marking requires a job.")
        owner_id = getattr(job, "owner_id", None)
        if not owner_id:
            return
        self.store.mark_artifact_uploaded(
            owner_id=str(owner_id),
            bucket=getattr(job.input_photo, "bucket", None) or self.bucket,
            object_key=object_key,
            size_bytes=size_bytes,
        )


def cleanup_expired_from_env(*, object_root: Path | None = None, limit: int = 100) -> dict[str, object]:
    from .supabase_store import LocalObjectStore, SupabaseStorage

    config = load_runtime_config()
    if getattr(config.mode, "value", None) == "private_alpha":
        from .sqlite_store import SQLiteTenantStore

        store = SQLiteTenantStore(config.alpha_database_path or "")
        object_store = LocalObjectStore(object_root or Path(config.local_object_root or os.environ.get("LOCAL_OBJECT_ROOT", "/tmp/objects")))
        return store.cleanup_expired(object_store=object_store, limit=limit)
    store = PostgresTenantStore(config.database_url)
    object_store = SupabaseStorage(bucket=config.storage_bucket) if config.auth_required else LocalObjectStore(object_root or Path(os.environ.get("LOCAL_OBJECT_ROOT", "/tmp/objects")))
    return store.cleanup_expired(object_store=object_store, limit=limit)
