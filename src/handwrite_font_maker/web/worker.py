from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from ..pipeline import build_font
from .contracts import HardErrorCode, JobArtifact, JobError, JobStage, JobStatus, JobWarning, hard_error_message
from .job_store import JobRecord, JobStore
from .supabase_store import ObjectStore

CONTENT_TYPES = {
    "otf": "font/otf",
    "ttf": "font/ttf",
    "sfd": "application/vnd.font-fontforge-sfd",
    "debug_overlay": "image/png",
    "manifest": "application/json",
}


def process_one(job_store: JobStore, object_store: ObjectStore) -> JobRecord | None:
    job = job_store.next_queued()
    if job is None:
        return None
    return process_job(job, job_store, object_store)


def process_job(job: JobRecord, job_store: JobStore, object_store: ObjectStore) -> JobRecord:
    job.status = JobStatus.RUNNING
    job.stage = JobStage.UPLOAD_RECEIVED
    job_store.save(job)

    with TemporaryDirectory(prefix=f"{job.id}_") as tmp:
        tmp_path = Path(tmp)
        input_path = tmp_path / "input" / "source"
        output_dir = tmp_path / "output"
        try:
            object_store.download_to_path(job.input_photo.object_key, input_path)
            job.stage = JobStage.FONT_GENERATION
            job_store.save(job)
            outputs = build_font(
                image_path=input_path,
                font_name=job.font.font_name,
                family_name=job.font.family_name,
                style_name=job.font.style_name,
                output_dir=output_dir,
            )
            job.stage = JobStage.ARTIFACT_PUBLISH
            job_store.save(job)
            job.artifacts = _publish_artifacts(job.id, outputs, object_store)
            job.warnings = [
                JobWarning(code=str(w.get("code", "GLYPH_LOW_INK_COVERAGE")).upper().replace("-", "_"), glyph=w.get("char"), message=str(w.get("message", "Glyph warning.")))
                for w in outputs.get("warnings", [])
                if isinstance(w, dict)
            ]
            job.status = JobStatus.SUCCEEDED
            job.stage = JobStage.COMPLETE
            job_store.save(job)
            return job
        except Exception as exc:  # mapping layer intentionally keeps worker resilient
            job.status = JobStatus.FAILED
            job.stage = _stage_for_exception(exc)
            code = _code_for_exception(exc)
            job.error = JobError(code=code, message=hard_error_message(code), retryable=code not in {HardErrorCode.FONTFORGE_UNAVAILABLE, HardErrorCode.POTRACE_UNAVAILABLE}, details={"exception": exc.__class__.__name__})
            job_store.save(job)
            return job


def _publish_artifacts(job_id: str, outputs: dict[str, object], object_store: ObjectStore) -> list[JobArtifact]:
    artifacts: list[JobArtifact] = []
    for kind in ["otf", "ttf", "sfd", "debug_overlay"]:
        value = outputs.get(kind)
        if not value:
            continue
        source = Path(str(value))
        object_key = f"jobs/{job_id}/artifacts/{source.name}"
        object_store.upload_from_path(object_key, source, CONTENT_TYPES.get(kind, "application/octet-stream"))
        artifacts.append(JobArtifact(kind=kind, label=_label(kind), object_key=object_key, content_type=CONTENT_TYPES.get(kind, "application/octet-stream"), size_bytes=source.stat().st_size, url=object_store.signed_download_url(object_key)))
    manifest = outputs.get("manifest")
    if manifest:
        source = Path(str(manifest))
        object_key = f"jobs/{job_id}/artifacts/manifest.json"
        object_store.upload_from_path(object_key, source, "application/json")
        artifacts.append(JobArtifact(kind="manifest", label="Build manifest", object_key=object_key, content_type="application/json", size_bytes=source.stat().st_size, url=object_store.signed_download_url(object_key)))
    return artifacts


def _label(kind: str) -> str:
    return {"otf": "OpenType Font", "ttf": "TrueType Font", "sfd": "FontForge Source", "debug_overlay": "Rectified Template"}.get(kind, kind)


def _code_for_exception(exc: Exception) -> HardErrorCode:
    message = str(exc).lower()
    if "potrace" in message:
        return HardErrorCode.POTRACE_UNAVAILABLE
    if "fontforge" in message and "validation" not in message:
        return HardErrorCode.FONTFORGE_UNAVAILABLE
    if "validation" in message:
        return HardErrorCode.FONT_VALIDATION_FAILED
    if "marker" in message:
        return HardErrorCode.MARKER_NOT_FOUND
    if "qr" in message or "metadata" in message:
        return HardErrorCode.QR_UNREADABLE
    if "homography" in message or "reprojection" in message:
        return HardErrorCode.HOMOGRAPHY_FAILED
    return HardErrorCode.INTERNAL_ERROR


def _stage_for_exception(exc: Exception) -> JobStage:
    code = _code_for_exception(exc)
    if code.name.startswith("MARKER"):
        return JobStage.MARKER_DETECTION
    if code.name.startswith("QR"):
        return JobStage.QR_DECODE
    if code.name.startswith("HOMOGRAPHY"):
        return JobStage.HOMOGRAPHY_RECTIFICATION
    if code in {HardErrorCode.FONT_VALIDATION_FAILED}:
        return JobStage.FONT_VALIDATION
    return JobStage.FONT_GENERATION
