from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
JOB_RETENTION_HOURS = 24


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class JobStage(StrEnum):
    UPLOAD_RECEIVED = "upload_received"
    QUEUED = "queued"
    MARKER_DETECTION = "marker_detection"
    QR_DECODE = "qr_decode"
    HOMOGRAPHY_RECTIFICATION = "homography_rectification"
    GLYPH_EXTRACTION = "glyph_extraction"
    FONT_GENERATION = "font_generation"
    FONT_VALIDATION = "font_validation"
    ARTIFACT_PUBLISH = "artifact_publish"
    COMPLETE = "complete"


class HardErrorCode(StrEnum):
    MARKER_NOT_FOUND = "MARKER_NOT_FOUND"
    MARKER_AMBIGUOUS = "MARKER_AMBIGUOUS"
    MARKER_GEOMETRY_INVALID = "MARKER_GEOMETRY_INVALID"
    TEMPLATE_BORDER_CROPPED = "TEMPLATE_BORDER_CROPPED"
    QR_NOT_FOUND = "QR_NOT_FOUND"
    QR_UNREADABLE = "QR_UNREADABLE"
    QR_TEMPLATE_VERSION_UNSUPPORTED = "QR_TEMPLATE_VERSION_UNSUPPORTED"
    QR_TEMPLATE_MISMATCH = "QR_TEMPLATE_MISMATCH"
    HOMOGRAPHY_FAILED = "HOMOGRAPHY_FAILED"
    HOMOGRAPHY_CONFIDENCE_LOW = "HOMOGRAPHY_CONFIDENCE_LOW"
    RECTIFIED_PAGE_OUT_OF_BOUNDS = "RECTIFIED_PAGE_OUT_OF_BOUNDS"
    GLYPH_GRID_NOT_FOUND = "GLYPH_GRID_NOT_FOUND"
    GLYPH_EXTRACTION_FAILED = "GLYPH_EXTRACTION_FAILED"
    GLYPH_REQUIRED_SET_MISSING = "GLYPH_REQUIRED_SET_MISSING"
    FONTFORGE_UNAVAILABLE = "FONTFORGE_UNAVAILABLE"
    POTRACE_UNAVAILABLE = "POTRACE_UNAVAILABLE"
    FONT_GENERATION_FAILED = "FONT_GENERATION_FAILED"
    FONT_VALIDATION_FAILED = "FONT_VALIDATION_FAILED"
    FONT_METADATA_INVALID = "FONT_METADATA_INVALID"
    UPLOAD_OBJECT_MISSING = "UPLOAD_OBJECT_MISSING"
    UPLOAD_OBJECT_TOO_LARGE = "UPLOAD_OBJECT_TOO_LARGE"
    UNSUPPORTED_IMAGE_TYPE = "UNSUPPORTED_IMAGE_TYPE"
    ARTIFACT_PUBLISH_FAILED = "ARTIFACT_PUBLISH_FAILED"
    JOB_EXPIRED = "JOB_EXPIRED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class InputPhoto:
    object_key: str
    content_type: str
    size_bytes: int
    bucket: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class FontRequest:
    font_name: str
    family_name: str
    style_name: str = "Regular"


@dataclass(frozen=True)
class JobWarning:
    code: str
    message: str
    glyph: str | None = None
    severity: Literal["warning"] = "warning"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobArtifact:
    kind: str
    label: str
    object_key: str
    content_type: str
    size_bytes: int
    url: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True)
class JobError:
    code: HardErrorCode
    message: str
    retryable: bool
    details: dict[str, Any] = field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def retention_expires_at(hours: int = JOB_RETENTION_HOURS) -> str:
    return (utc_now() + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def new_job_id() -> str:
    return f"job_{uuid4()}"


def is_supported_image(content_type: str) -> bool:
    return content_type in {"image/jpeg", "image/png", "image/webp"}


def is_safe_font_name(font_name: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,62}", font_name))


def hard_error_message(code: HardErrorCode) -> str:
    return {
        HardErrorCode.MARKER_NOT_FOUND: "We could not find all four page markers. Retake the photo with the entire page visible.",
        HardErrorCode.QR_UNREADABLE: "The QR code could not be read. Retake the photo with sharper focus and less glare.",
        HardErrorCode.HOMOGRAPHY_FAILED: "Perspective correction failed. Retake with less tilt and all corners visible.",
        HardErrorCode.FONT_VALIDATION_FAILED: "The generated font failed validation. Retake the photo or try a simpler font name.",
        HardErrorCode.FONT_METADATA_INVALID: "The font metadata is invalid. Use letters, numbers, hyphens, or underscores.",
        HardErrorCode.UPLOAD_OBJECT_TOO_LARGE: "The photo is larger than the configured upload limit.",
        HardErrorCode.UNSUPPORTED_IMAGE_TYPE: "Upload a JPEG, PNG, or WebP image.",
    }.get(code, "An unexpected backend error occurred. Try again with a fresh upload.")
