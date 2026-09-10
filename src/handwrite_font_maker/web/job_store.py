from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Protocol

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
    new_job_id,
    retention_expires_at,
)


class LeaseLostError(RuntimeError):
    """This attempt no longer owns the job; it must not publish results."""


@dataclass
class JobRecord:
    id: str
    input_photo: InputPhoto
    font: FontRequest
    capture: CaptureConfig | None = None
    status: JobStatus = JobStatus.QUEUED
    stage: JobStage = JobStage.QUEUED
    warnings: list[JobWarning] = field(default_factory=list)
    artifacts: list[JobArtifact] = field(default_factory=list)
    error: JobError | None = None
    retention_expires_at: str = field(default_factory=retention_expires_at)

    owner_id: str | None = None
    attempt_id: str | None = None
    lease_owner: str | None = None
    attempt_count: int = 0

    def as_response(self, signed_url_for: Callable[[str], str] | None = None) -> dict[str, object]:
        artifacts = [_artifact_response(artifact, signed_url_for=signed_url_for) for artifact in self.artifacts]
        return {
            "jobId": self.id,
            "status": self.status.value,
            "stage": self.stage.value,
            "progressLabel": progress_label(self.stage),
            "warnings": [asdict(w) for w in self.warnings],
            "artifacts": artifacts,
            "error": None if self.error is None else {**asdict(self.error), "code": self.error.code.value},
            "retentionExpiresAt": self.retention_expires_at,
        }


def _artifact_response(artifact: JobArtifact, *, signed_url_for: Callable[[str], str] | None = None) -> dict[str, object]:
    return {
        "kind": artifact.kind,
        "label": artifact.label,
        "objectKey": artifact.object_key,
        "contentType": artifact.content_type,
        "sizeBytes": artifact.size_bytes,
        "url": signed_url_for(artifact.object_key) if signed_url_for is not None else artifact.url,
        "expiresAt": artifact.expires_at,
    }


def progress_label(stage: JobStage) -> str:
    return {
        JobStage.UPLOAD_RECEIVED: "Upload received",
        JobStage.QUEUED: "Waiting for backend processing",
        JobStage.MARKER_DETECTION: "Finding page markers",
        JobStage.HOMOGRAPHY_RECTIFICATION: "Correcting phone perspective",
        JobStage.GLYPH_EXTRACTION: "Extracting glyph cells",
        JobStage.FONT_GENERATION: "Generating font outlines",
        JobStage.FONT_VALIDATION: "Validating font files",
        JobStage.ARTIFACT_PUBLISH: "Publishing download artifacts",
        JobStage.COMPLETE: "Font build complete",
    }[stage]


class JobStore(Protocol):
    def create(self, input_photo: InputPhoto, font: FontRequest, capture: CaptureConfig | None = None, owner_id: str | None = None) -> JobRecord: ...
    def get(self, job_id: str) -> JobRecord | None: ...
    def next_queued(self) -> JobRecord | None: ...
    def save(self, job: JobRecord) -> None: ...


class JsonJobStore:
    """Local/dev job store matching the Supabase Postgres row model."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _read(self) -> dict[str, dict[str, object]]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, dict[str, object]]) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def create(self, input_photo: InputPhoto, font: FontRequest, capture: CaptureConfig | None = None, owner_id: str | None = None) -> JobRecord:
        job = JobRecord(id=new_job_id(), input_photo=input_photo, font=font, capture=capture, owner_id=owner_id)
        self.save(job)
        return job

    def get(self, job_id: str) -> JobRecord | None:
        row = self._read().get(job_id)
        return None if row is None else _from_row(row)

    def next_queued(self) -> JobRecord | None:
        for row in self._read().values():
            job = _from_row(row)
            if job.status == JobStatus.QUEUED:
                return job
        return None

    def save(self, job: JobRecord) -> None:
        data = self._read()
        data[job.id] = _to_row(job)
        self._write(data)


def _to_row(job: JobRecord) -> dict[str, object]:
    return {
        "id": job.id,
        "owner_id": job.owner_id,
        "attempt_id": job.attempt_id,
        "lease_owner": job.lease_owner,
        "attempt_count": job.attempt_count,
        "input_photo": asdict(job.input_photo),
        "font": asdict(job.font),
        "capture": capture_to_json(job.capture),
        "status": job.status.value,
        "stage": job.stage.value,
        "warnings": [asdict(w) for w in job.warnings],
        "artifacts": [{**asdict(a), "url": None, "expires_at": None} for a in job.artifacts],
        "error": None if job.error is None else {**asdict(job.error), "code": job.error.code.value},
        "retention_expires_at": job.retention_expires_at,
    }


def _from_row(row: dict[str, object]) -> JobRecord:
    error_row = row.get("error")

    return JobRecord(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]) if row.get("owner_id") else None,
        attempt_id=str(row["attempt_id"]) if row.get("attempt_id") else None,
        lease_owner=str(row["lease_owner"]) if row.get("lease_owner") else None,
        attempt_count=int(row.get("attempt_count") or 0),
        input_photo=InputPhoto(**row["input_photo"]),  # type: ignore[arg-type]
        font=FontRequest(**row["font"]),  # type: ignore[arg-type]
        capture=capture_from_json(row.get("capture")),
        status=JobStatus(str(row["status"])),
        stage=JobStage(str(row["stage"])),
        warnings=[JobWarning(**w) for w in row.get("warnings", [])],  # type: ignore[arg-type]
        artifacts=[JobArtifact(**a) for a in row.get("artifacts", [])],  # type: ignore[arg-type]
        error=None if not error_row else JobError(code=HardErrorCode(error_row["code"]), message=error_row["message"], retryable=error_row["retryable"], details=error_row.get("details", {})),  # type: ignore[index,union-attr,arg-type]
        retention_expires_at=str(row["retention_expires_at"]),
    )


class PostgresJobStore:
    """Supabase Postgres job store used by Render services when DATABASE_URL is set."""

    def __init__(self, database_url: str) -> None:
        import psycopg

        self.database_url = database_url
        self._psycopg = psycopg

    def _connect(self):
        return self._psycopg.connect(self.database_url, connect_timeout=5, options="-c statement_timeout=10000 -c lock_timeout=5000")

    def create(self, input_photo: InputPhoto, font: FontRequest, capture: CaptureConfig | None = None, owner_id: str | None = None) -> JobRecord:
        job = JobRecord(id=new_job_id(), input_photo=input_photo, font=font, capture=capture, owner_id=owner_id)
        bucket = input_photo.bucket or "handwrite-font-jobs"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into jobs (id, status, stage, font_name, family_name, style_name,
                  input_bucket, input_path, input_content_type, input_size_bytes, capture_config, retention_expires_at, owner_id)
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
        return job

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select * from jobs where id = %s", (job_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [desc.name for desc in cur.description]
            job_row = dict(zip(cols, row, strict=True))
            cur.execute("select code, glyph, message, severity, details from job_warnings where job_id = %s order by id", (job_id,))
            warnings = [JobWarning(code=r[0], glyph=r[1], message=r[2], severity=r[3], details=r[4] or {}) for r in cur.fetchall()]
            cur.execute("select kind, label, path, content_type, size_bytes from job_artifacts where job_id = %s order by id", (job_id,))
            artifacts = [JobArtifact(kind=r[0], label=r[1], object_key=r[2], content_type=r[3], size_bytes=r[4]) for r in cur.fetchall()]
        return _from_postgres_row(job_row, warnings, artifacts)

    @property
    def lease_seconds(self) -> int:
        return max(10, int(os.environ.get("JOB_LEASE_SECONDS", "60")))

    @property
    def max_attempts(self) -> int:
        return max(1, int(os.environ.get("JOB_MAX_ATTEMPTS", "3")))

    def next_queued(self) -> JobRecord | None:
        return self.claim()

    def claim(self, job_id: str | None = None) -> JobRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            # Expiry and exhausted crashed attempts become terminal even with an empty queue.
            cur.execute("""update jobs set status='expired', lease_owner=null, lease_expires_at=null,
                           updated_at=now() where status in ('queued','running') and retention_expires_at<=now()""")
            cur.execute("""update jobs set status='failed', error_code='INTERNAL_ERROR',
                           error_message='Processing attempts exhausted.', error_retryable=false,
                           lease_owner=null, lease_expires_at=null, completed_at=now(), updated_at=now()
                           where status in ('queued','running') and attempt_count>=%s
                           and (status='queued' or lease_expires_at is null or lease_expires_at<=now())""", (self.max_attempts,))
            cur.execute(
                """
                update jobs set status='running', stage='upload_received',
                    lease_owner=gen_random_uuid()::text, attempt_id=gen_random_uuid()::text,
                    attempt_count=attempt_count+1,
                    lease_expires_at=now() + %s * interval '1 second', updated_at=now(),
                    error_code=null, error_message=null, error_retryable=null, error_details='{}'::jsonb
                where id = (
                    select id from jobs where
                    (status='queued' or (status='running' and (lease_expires_at is null or lease_expires_at<=now())))
                    and retention_expires_at>now() and attempt_count<%s
                    and (%s::text is null or id=%s)
                    order by created_at, id for update skip locked limit 1
                ) returning *
                """, (self.lease_seconds, self.max_attempts, job_id, job_id)
            )
            row = cur.fetchone()
            if row is None:
                return None
            job_row = dict(zip([desc.name for desc in cur.description], row, strict=True))
        return _from_postgres_row(job_row, [], [])

    def heartbeat(self, job: JobRecord) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""update jobs set lease_expires_at=now()+%s*interval '1 second', updated_at=now()
                           where id=%s and attempt_id=%s and lease_owner=%s and status='running'
                           and lease_expires_at>now() and retention_expires_at>now()""",
                        (self.lease_seconds, job.id, job.attempt_id, job.lease_owner))
            return cur.rowcount == 1

    def retry_attempt(self, job: JobRecord, *, reason: str = "Worker interrupted") -> bool:
        """Release a crashed/timed-out attempt. Fence prevents a late supervisor changing a new claim."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""update jobs set status=case when attempt_count<%s then 'queued' else 'failed' end,
                           stage='queued', lease_owner=null, lease_expires_at=null,
                           error_code='INTERNAL_ERROR', error_message=%s, error_retryable=(attempt_count<%s),
                           updated_at=now(), completed_at=case when attempt_count>=%s then now() else null end
                           where id=%s and attempt_id=%s and lease_owner=%s and status='running'
                           and lease_expires_at>now() and retention_expires_at>now()""",
                        (self.max_attempts, reason, self.max_attempts, self.max_attempts,
                         job.id, job.attempt_id, job.lease_owner))
            return cur.rowcount == 1

    def save(self, job: JobRecord) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update jobs
                set status=%s, stage=%s, capture_config=%s::jsonb, error_code=%s, error_message=%s, error_retryable=%s,
                    error_details=%s::jsonb, updated_at=now(), completed_at = case when %s then now() else completed_at end
                where id=%s and attempt_id=%s and lease_owner=%s and status='running'
                  and lease_expires_at>now() and retention_expires_at>now()
                """,
                (
                    job.status.value,
                    job.stage.value,
                    json.dumps(capture_to_json(job.capture)),
                    None if job.error is None else job.error.code.value,
                    None if job.error is None else job.error.message,
                    None if job.error is None else job.error.retryable,
                    json.dumps({} if job.error is None else job.error.details),
                    job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.EXPIRED},
                    job.id,
                    job.attempt_id,
                    job.lease_owner,
                ),
            )
            if cur.rowcount != 1:
                raise LeaseLostError("Job lease lost or expired")
            cur.execute("delete from job_warnings where job_id=%s", (job.id,))
            for warning in job.warnings:
                cur.execute("insert into job_warnings (job_id, code, glyph, message, severity, details) values (%s,%s,%s,%s,%s,%s::jsonb)", (job.id, warning.code, warning.glyph, warning.message, warning.severity, json.dumps(warning.details)))
            cur.execute("delete from job_artifacts where job_id=%s", (job.id,))
            for artifact in job.artifacts:
                bucket = job.input_photo.bucket or "handwrite-font-jobs"
                cur.execute("insert into job_artifacts (job_id, kind, label, bucket, path, content_type, size_bytes) values (%s,%s,%s,%s,%s,%s,%s)", (job.id, artifact.kind, artifact.label, bucket, artifact.object_key, artifact.content_type, artifact.size_bytes))


def _from_postgres_row(row: dict[str, object], warnings: list[JobWarning], artifacts: list[JobArtifact]) -> JobRecord:
    error = None
    if row.get("error_code"):
        error = JobError(code=HardErrorCode(str(row["error_code"])), message=str(row.get("error_message") or ""), retryable=bool(row.get("error_retryable")), details=row.get("error_details") or {})  # type: ignore[arg-type]
    return JobRecord(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]) if row.get("owner_id") else None,
        attempt_id=str(row["attempt_id"]) if row.get("attempt_id") else None,
        lease_owner=str(row["lease_owner"]) if row.get("lease_owner") else None,
        attempt_count=int(row.get("attempt_count") or 0),
        input_photo=InputPhoto(object_key=str(row["input_path"]), bucket=str(row["input_bucket"]), content_type=str(row["input_content_type"]), size_bytes=int(row["input_size_bytes"])),
        font=FontRequest(font_name=str(row["font_name"]), family_name=str(row["family_name"]), style_name=str(row["style_name"])),
        capture=capture_from_json(row.get("capture_config")),
        status=JobStatus(str(row["status"])),
        stage=JobStage(str(row["stage"])),
        warnings=warnings,
        artifacts=artifacts,
        error=error,
        retention_expires_at=str(row["retention_expires_at"]),
    )
