from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from .contracts import (
    GuidedCapture,
    HardErrorCode,
    InputPhoto,
    JobArtifact,
    JobError,
    JobStage,
    JobStatus,
    JobWarning,
    MAX_GUIDED_MASK_SIDE,
    MAX_GUIDED_TOTAL_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_UPLOAD_BYTES,
    TemplateCapture,
    hard_error_message,
)
from .job_store import JobRecord, JobStore, LeaseLostError
from .supabase_store import ObjectStore

CONTENT_TYPES = {
    "otf": "font/otf",
    "ttf": "font/ttf",
    "sfd": "application/vnd.font-fontforge-sfd",
    "debug_overlay": "image/png",
    "manifest": "application/json",
    "download_bundle": "application/zip",
}


def _build_font(**kwargs: object) -> dict[str, object]:
    from ..pipeline import build_font

    return build_font(**kwargs)  # type: ignore[arg-type]


def _build_font_from_masks(**kwargs: object) -> dict[str, object]:
    from ..pipeline import build_font_from_masks

    return build_font_from_masks(**kwargs)  # type: ignore[arg-type]


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
            outputs = _run_build(job, object_store, input_path=input_path, output_dir=output_dir)
            job.stage = JobStage.ARTIFACT_PUBLISH
            job_store.save(job)
            job.artifacts = _publish_artifacts(job.id, outputs, object_store, attempt_id=job.attempt_id, job=job)
            job.warnings = [
                JobWarning(code=str(w.get("code", "GLYPH_LOW_INK_COVERAGE")).upper().replace("-", "_"), glyph=w.get("char"), message=str(w.get("message", "Glyph warning.")))
                for w in outputs.get("warnings", [])
                if isinstance(w, dict)
            ]
            job.status = JobStatus.SUCCEEDED
            job.stage = JobStage.COMPLETE
            job_store.save(job)
            return job
        except LeaseLostError:
            raise
        except Exception as exc:  # mapping layer intentionally keeps worker resilient
            if job.attempt_id and _transient_failure(exc):
                raise  # Supervisor requeues this fenced attempt within the retry budget.
            job.status = JobStatus.FAILED
            job.stage = _stage_for_exception(exc)
            code = _code_for_exception(exc)
            job.error = JobError(code=code, message=hard_error_message(code), retryable=code not in {HardErrorCode.FONTFORGE_UNAVAILABLE, HardErrorCode.POTRACE_UNAVAILABLE}, details={"exception": exc.__class__.__name__, "message": str(exc)[:300]})
            job_store.save(job)
            return job


def _run_build(job: JobRecord, object_store: ObjectStore, *, input_path: Path, output_dir: Path) -> dict[str, object]:
    capture = job.capture
    if isinstance(capture, GuidedCapture):
        job.stage = JobStage.GLYPH_EXTRACTION
        glyph_dir = input_path.parent / "glyphs"
        glyph_dir.mkdir(parents=True, exist_ok=True)
        glyph_args: list[dict[str, object]] = []
        total_bytes = 0
        for index, glyph in enumerate(capture.glyphs):
            glyph_path = glyph_dir / f"{index:02d}_{ord(glyph.char):04x}.png"
            object_store.download_to_path(glyph.input_photo.object_key, glyph_path)
            total_bytes += _validate_guided_mask(glyph_path, glyph.input_photo)
            if total_bytes > MAX_GUIDED_TOTAL_BYTES:
                raise ValueError(HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value)
            glyph_args.append({"char": glyph.char, "image_path": glyph_path, "baseline": glyph.baseline, "scale": glyph.scale, "spacing": glyph.spacing})
        job.stage = JobStage.FONT_GENERATION
        return _build_font_from_masks(
            glyphs=glyph_args,
            font_name=job.font.font_name,
            family_name=job.font.family_name,
            style_name=job.font.style_name,
            output_dir=output_dir,
        )

    object_store.download_to_path(job.input_photo.object_key, input_path)
    _validate_input_image(input_path, job.input_photo)
    job.stage = JobStage.FONT_GENERATION
    if isinstance(capture, TemplateCapture):
        return _build_font(
            image_path=input_path,
            font_name=job.font.font_name,
            family_name=job.font.family_name,
            style_name=job.font.style_name,
            output_dir=output_dir,
            alignment=capture.alignment,
            corners=capture.corners,
            paper_size=capture.paper_size,
        )
    return _build_font(
        image_path=input_path,
        font_name=job.font.font_name,
        family_name=job.font.family_name,
        style_name=job.font.style_name,
        output_dir=output_dir,
    )


def _validate_input_image(path: Path, photo: InputPhoto) -> int:
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(HardErrorCode.UPLOAD_OBJECT_MISSING.value)
    if size > MAX_UPLOAD_BYTES or photo.size_bytes > MAX_UPLOAD_BYTES:
        raise ValueError(HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value)
    if photo.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError(HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value)
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError(HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value)
            actual = Image.MIME.get(image.format or "")
            if actual and actual != photo.content_type:
                raise ValueError(HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value)
            image.verify()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value) from exc
    return size


def _validate_guided_mask(path: Path, photo: InputPhoto) -> int:
    size = _validate_input_image(path, photo)
    if photo.content_type != "image/png":
        raise ValueError(HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value)
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError(HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value)
            width, height = image.size
            if max(width, height) > MAX_GUIDED_MASK_SIDE or width * height > MAX_GUIDED_MASK_SIDE * MAX_GUIDED_MASK_SIDE:
                raise ValueError(HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value)
            rgba = image.convert("RGBA")
            alpha = np.asarray(rgba.getchannel("A"))
            if bool((alpha < 255).any()):
                raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
            grayscale = np.asarray(rgba.convert("L"))
            foreground = grayscale < 128
            coverage = float(foreground.mean())
            if coverage <= 0.0001 or coverage >= 0.98:
                raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value) from exc
    return size


def _publish_artifacts(job_id: str, outputs: dict[str, object], object_store: ObjectStore, *, attempt_id: str | None = None, job: JobRecord | None = None) -> list[JobArtifact]:
    artifacts: list[JobArtifact] = []
    registry = None
    if job is not None and job.owner_id:
        from .tenant_store import WorkerArtifactRegistry
        registry = WorkerArtifactRegistry.from_env()

    def upload(object_key: str, source: Path, content_type: str, kind: str) -> None:
        # Persist cleanup intent before the non-transactional external write.
        # Registry rows alone never grant artifact reads: final job_artifacts is fenced.
        if registry is not None:
            registry.register_attempt_artifact(job, object_key=object_key, content_type=content_type, size_bytes=source.stat().st_size, kind=kind)
        object_store.upload_from_path(object_key, source, content_type)
        if registry is not None:
            registry.mark_uploaded(job, object_key=object_key, size_bytes=source.stat().st_size)

    prefix = f"jobs/{job_id}/attempts/{attempt_id}" if attempt_id else f"jobs/{job_id}"
    for kind in ["otf", "ttf", "sfd", "debug_overlay", "download_bundle"]:
        value = outputs.get(kind)
        if not value:
            continue
        source = Path(str(value))
        object_key = f"{prefix}/artifacts/{source.name}"
        upload(object_key, source, CONTENT_TYPES.get(kind, "application/octet-stream"), kind)
        artifacts.append(JobArtifact(kind=kind, label=_label(kind), object_key=object_key, content_type=CONTENT_TYPES.get(kind, "application/octet-stream"), size_bytes=source.stat().st_size, url=object_store.signed_download_url(object_key)))
    manifest = outputs.get("manifest")
    if manifest:
        source = Path(str(manifest))
        object_key = f"{prefix}/artifacts/manifest.json"
        upload(object_key, source, "application/json", "manifest")
        artifacts.append(JobArtifact(kind="manifest", label="Build manifest", object_key=object_key, content_type="application/json", size_bytes=source.stat().st_size, url=object_store.signed_download_url(object_key)))
    return artifacts


def _label(kind: str) -> str:
    return {"otf": "OpenType Font", "ttf": "TrueType Font", "sfd": "FontForge Source", "debug_overlay": "Rectified Template", "download_bundle": "Download package"}.get(kind, kind)


def _code_for_exception(exc: Exception) -> HardErrorCode:
    text = str(exc)
    if text in {code.value for code in HardErrorCode}:
        return HardErrorCode(text)
    message = text.lower()
    if "potrace" in message:
        return HardErrorCode.POTRACE_UNAVAILABLE
    if "fontforge" in message and "validation" not in message:
        return HardErrorCode.FONTFORGE_UNAVAILABLE
    if "validation" in message:
        return HardErrorCode.FONT_VALIDATION_FAILED
    if "marker" in message:
        return HardErrorCode.MARKER_NOT_FOUND
    if "homography" in message or "reprojection" in message:
        return HardErrorCode.HOMOGRAPHY_FAILED
    return HardErrorCode.INTERNAL_ERROR


def _stage_for_exception(exc: Exception) -> JobStage:
    code = _code_for_exception(exc)
    if code.name.startswith("MARKER"):
        return JobStage.MARKER_DETECTION
    if code.name.startswith("HOMOGRAPHY"):
        return JobStage.HOMOGRAPHY_RECTIFICATION
    if code in {HardErrorCode.GLYPH_EXTRACTION_FAILED, HardErrorCode.GLYPH_REQUIRED_SET_MISSING, HardErrorCode.UNSUPPORTED_IMAGE_TYPE, HardErrorCode.UPLOAD_OBJECT_TOO_LARGE}:
        return JobStage.GLYPH_EXTRACTION
    if code in {HardErrorCode.FONT_VALIDATION_FAILED}:
        return JobStage.FONT_VALIDATION
    return JobStage.FONT_GENERATION


def _transient_failure(exc: Exception) -> bool:
    import requests
    if isinstance(exc, (requests.ConnectionError, requests.Timeout, TimeoutError)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False
