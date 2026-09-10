from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_GUIDED_MASK_SIDE = 1024
MAX_GUIDED_GLYPHS = 94
MAX_GUIDED_TOTAL_BYTES = MAX_UPLOAD_BYTES
GUIDED_GLYPH_SCALE_MIN = 0.5
GUIDED_GLYPH_SCALE_MAX = 1.5
GUIDED_GLYPH_SPACING_MIN = -0.05
GUIDED_GLYPH_SPACING_MAX = 0.25
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
class TemplateCapture:
    template_id: Literal["default-v1"]
    paper_size: Literal["A4"]
    alignment: Literal["markers", "page"]
    corners: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]] | None = None
    mode: Literal["template"] = "template"


@dataclass(frozen=True)
class GuidedGlyphCapture:
    char: str
    input_photo: InputPhoto
    baseline: float
    scale: float = 1.0
    spacing: float = 0.0


@dataclass(frozen=True)
class GuidedCapture:
    glyphs: tuple[GuidedGlyphCapture, ...]
    mode: Literal["guided"] = "guided"
    format: Literal["mask-v1"] = "mask-v1"


CaptureConfig = TemplateCapture | GuidedCapture


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
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,62}", font_name))


def is_safe_object_key(object_key: str) -> bool:
    if not object_key or "\x00" in object_key or object_key.startswith(("/", "\\")):
        return False
    path = Path(object_key)
    return not path.is_absolute() and ".." not in path.parts and all(part not in {"", "."} for part in path.parts)


def parse_input_photo(payload: object, *, require_png: bool = False) -> InputPhoto:
    if not isinstance(payload, dict):
        raise ValueError(HardErrorCode.UPLOAD_OBJECT_MISSING.value)
    object_key = payload.get("objectKey", payload.get("object_key"))
    content_type = payload.get("contentType", payload.get("content_type"))
    size_bytes = payload.get("sizeBytes", payload.get("size_bytes"))
    if not isinstance(object_key, str) or not is_safe_object_key(object_key):
        raise ValueError(HardErrorCode.UPLOAD_OBJECT_MISSING.value)
    if not isinstance(content_type, str) or not is_supported_image(content_type):
        raise ValueError(HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value)
    if require_png and content_type != "image/png":
        raise ValueError(HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value)
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
        raise ValueError(HardErrorCode.UPLOAD_OBJECT_MISSING.value)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise ValueError(HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value)
    bucket = payload.get("bucket")
    sha256 = payload.get("sha256")
    return InputPhoto(
        object_key=object_key,
        content_type=content_type,
        size_bytes=size_bytes,
        bucket=bucket if isinstance(bucket, str) and bucket else None,
        sha256=sha256 if isinstance(sha256, str) and sha256 else None,
    )


def parse_capture_config(payload: object | None, *, outer_input_photo: InputPhoto | None = None) -> CaptureConfig | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError(HardErrorCode.INTERNAL_ERROR.value)
    mode = payload.get("mode")
    if mode == "template":
        return _parse_template_capture(payload)
    if mode == "guided":
        return _parse_guided_capture(payload, outer_input_photo=outer_input_photo)
    raise ValueError(HardErrorCode.INTERNAL_ERROR.value)


def capture_to_json(capture: CaptureConfig | None) -> dict[str, object] | None:
    if capture is None:
        return None
    if isinstance(capture, TemplateCapture):
        row: dict[str, object] = {
            "mode": "template",
            "templateId": capture.template_id,
            "paperSize": capture.paper_size,
            "alignment": capture.alignment,
        }
        if capture.corners is not None:
            row["corners"] = [[x, y] for x, y in capture.corners]
        return row
    return {
        "mode": "guided",
        "format": capture.format,
        "glyphs": [
            {"char": glyph.char, "inputPhoto": input_photo_to_json(glyph.input_photo), "baseline": glyph.baseline, "scale": glyph.scale, "spacing": glyph.spacing}
            for glyph in capture.glyphs
        ],
    }


def capture_from_json(payload: object | None) -> CaptureConfig | None:
    return parse_capture_config(payload)


def input_photo_to_json(photo: InputPhoto) -> dict[str, object]:
    data: dict[str, object] = {
        "objectKey": photo.object_key,
        "contentType": photo.content_type,
        "sizeBytes": photo.size_bytes,
    }
    if photo.bucket:
        data["bucket"] = photo.bucket
    if photo.sha256:
        data["sha256"] = photo.sha256
    return data


def validate_normalized_corners(raw: object) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]:
    if not isinstance(raw, list | tuple) or len(raw) != 4:
        raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)
    points: list[tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, list | tuple) or len(point) != 2:
            raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)
        x_raw, y_raw = point
        if isinstance(x_raw, bool) or isinstance(y_raw, bool) or not isinstance(x_raw, int | float) or not isinstance(y_raw, int | float):
            raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)
        x = float(x_raw)
        y = float(y_raw)
        if not math.isfinite(x) or not math.isfinite(y) or x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0:
            raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)
        points.append((x, y))

    if len(set(points)) != 4:
        raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)

    area = 0.5 * abs(sum(points[i][0] * points[(i + 1) % 4][1] - points[(i + 1) % 4][0] * points[i][1] for i in range(4)))
    if area < 0.05:
        raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)

    def cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])

    crosses = [cross(points[i], points[(i + 1) % 4], points[(i + 2) % 4]) for i in range(4)]
    if any(abs(value) < 1e-6 for value in crosses) or not (all(value > 0 for value in crosses) or all(value < 0 for value in crosses)):
        raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)

    return (points[0], points[1], points[2], points[3])


def _parse_template_capture(payload: dict[str, object]) -> TemplateCapture:
    if payload.get("templateId") != "default-v1" or payload.get("paperSize") != "A4":
        raise ValueError(HardErrorCode.INTERNAL_ERROR.value)
    alignment = payload.get("alignment")
    if alignment not in {"markers", "page"}:
        raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)
    corners = None
    if "corners" in payload and payload.get("corners") is not None:
        corners = validate_normalized_corners(payload.get("corners"))
    if alignment == "page" and corners is None:
        raise ValueError(HardErrorCode.MARKER_GEOMETRY_INVALID.value)
    return TemplateCapture(template_id="default-v1", paper_size="A4", alignment=alignment, corners=corners)  # type: ignore[arg-type]


def _parse_guided_capture(payload: dict[str, object], *, outer_input_photo: InputPhoto | None) -> GuidedCapture:
    if payload.get("format") != "mask-v1":
        raise ValueError(HardErrorCode.INTERNAL_ERROR.value)
    raw_glyphs = payload.get("glyphs")
    if not isinstance(raw_glyphs, list) or not 1 <= len(raw_glyphs) <= MAX_GUIDED_GLYPHS:
        raise ValueError(HardErrorCode.GLYPH_REQUIRED_SET_MISSING.value)
    seen: set[str] = set()
    glyphs: list[GuidedGlyphCapture] = []
    total_bytes = 0
    for raw_glyph in raw_glyphs:
        if not isinstance(raw_glyph, dict):
            raise ValueError(HardErrorCode.GLYPH_REQUIRED_SET_MISSING.value)
        char = raw_glyph.get("char")
        if not isinstance(char, str) or len(char) != 1 or not (33 <= ord(char) <= 126) or char in seen:
            raise ValueError(HardErrorCode.GLYPH_REQUIRED_SET_MISSING.value)
        baseline_raw = raw_glyph.get("baseline")
        if isinstance(baseline_raw, bool) or not isinstance(baseline_raw, int | float):
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        baseline = float(baseline_raw)
        if not math.isfinite(baseline) or not 0.0 < baseline < 1.0:
            raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
        scale = _guided_glyph_metric(raw_glyph, "scale", 1.0, GUIDED_GLYPH_SCALE_MIN, GUIDED_GLYPH_SCALE_MAX)
        spacing = _guided_glyph_metric(raw_glyph, "spacing", 0.0, GUIDED_GLYPH_SPACING_MIN, GUIDED_GLYPH_SPACING_MAX)
        input_photo = parse_input_photo(raw_glyph.get("inputPhoto"), require_png=True)
        total_bytes += input_photo.size_bytes
        if total_bytes > MAX_GUIDED_TOTAL_BYTES:
            raise ValueError(HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value)
        seen.add(char)
        glyphs.append(GuidedGlyphCapture(char=char, input_photo=input_photo, baseline=baseline, scale=scale, spacing=spacing))
    if outer_input_photo is not None and glyphs[0].input_photo.object_key != outer_input_photo.object_key:
        raise ValueError(HardErrorCode.UPLOAD_OBJECT_MISSING.value)
    return GuidedCapture(glyphs=tuple(glyphs))


def _guided_glyph_metric(raw_glyph: dict[str, object], key: str, default: float, minimum: float, maximum: float) -> float:
    raw = raw_glyph.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    value = float(raw)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(HardErrorCode.GLYPH_EXTRACTION_FAILED.value)
    return value


def hard_error_message(code: HardErrorCode) -> str:
    return {
        HardErrorCode.MARKER_NOT_FOUND: "We could not find all four page markers. Retake the photo with the entire page visible.",
        HardErrorCode.MARKER_GEOMETRY_INVALID: "Confirm the page corners in top-left, top-right, bottom-right, bottom-left order with the full page visible.",
        HardErrorCode.HOMOGRAPHY_FAILED: "Perspective correction failed. Retake with less tilt and all corners visible.",
        HardErrorCode.GLYPH_EXTRACTION_FAILED: "One accepted glyph mask is blank, solid, oversized, or malformed. Redo that character mask.",
        HardErrorCode.GLYPH_REQUIRED_SET_MISSING: "Guided mode needs 1 to 94 unique printable non-space ASCII glyphs.",
        HardErrorCode.FONT_VALIDATION_FAILED: "The generated font failed validation. Retake the photo or try a simpler font name.",
        HardErrorCode.FONT_METADATA_INVALID: "The font metadata is invalid. Use letters, numbers, hyphens, or underscores.",
        HardErrorCode.UPLOAD_OBJECT_MISSING: "The uploaded image could not be found or the request is missing image metadata.",
        HardErrorCode.UPLOAD_OBJECT_TOO_LARGE: "The photo is larger than the configured upload limit.",
        HardErrorCode.UNSUPPORTED_IMAGE_TYPE: "Upload a JPEG, PNG, or WebP image.",
    }.get(code, "An unexpected backend error occurred. Try again with a fresh upload.")
