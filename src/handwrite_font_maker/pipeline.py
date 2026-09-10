from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .diagnostics import BuildDiagnostics, FontValidationError, GlyphWarning
from .extract import Cell, extract_cells, save_debug_overlay
from .layout import DEFAULT_CHARS, get_layout, glyph_slug
from .rectify import rectify_template_photo

EM_SIZE = 1000
ASCENT = 800
DESCENT = 200
SIDE_BEARING = 80
EMPTY_GLYPH_WIDTH = 280
MAX_MASK_SIDE = 1024
MAX_MASK_PIXELS = MAX_MASK_SIDE * MAX_MASK_SIDE
DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 300
PRINTABLE_NONSPACE_ASCII = set(string.ascii_letters + string.digits + string.punctuation)
_FONT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,62}$")
_FAMILY_STYLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._'-]{0,79}$")


@dataclass(frozen=True)
class Run:
    start: int
    end: int
    score: float

    @property
    def center(self) -> int:
        return int(round((self.start + self.end) / 2))


@dataclass(frozen=True)
class GlyphBitmapResult:
    bitmap: Image.Image
    top_offset: int
    coverage: float
    warnings: tuple[str, ...]
    empty: bool = False
    source_width: int | None = None
    source_height: int | None = None
    original_width: int | None = None
    original_height: int | None = None


class MaskValidationError(ValueError):
    """Raised when an accepted guided mask violates the mask-v1 contract."""


def _subprocess_timeout_seconds() -> int:
    raw = os.environ.get("HANDWRITE_FONT_SUBPROCESS_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_SUBPROCESS_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("HANDWRITE_FONT_SUBPROCESS_TIMEOUT_SECONDS must be an integer.") from exc
    if value <= 0:
        raise RuntimeError("HANDWRITE_FONT_SUBPROCESS_TIMEOUT_SECONDS must be positive.")
    return value


def _find_binary_runs(mask: np.ndarray, scores: np.ndarray) -> list[Run]:
    runs: list[Run] = []
    in_run = False
    start = 0
    for index, value in enumerate(mask):
        if value and not in_run:
            start = index
            in_run = True
        elif not value and in_run:
            segment = scores[start:index]
            runs.append(Run(start=start, end=index - 1, score=float(segment.max())))
            in_run = False
    if in_run:
        segment = scores[start:]
        runs.append(Run(start=start, end=len(scores) - 1, score=float(segment.max())))
    return runs


def _cell_inner_crop(gray: np.ndarray, cell: Cell, margin_x: int, margin_y: int, margin_bottom_y: int | None = None) -> np.ndarray:
    bottom_margin = margin_y if margin_bottom_y is None else margin_bottom_y
    return gray[
        cell.top + margin_y : cell.bottom - bottom_margin + 1,
        cell.left + margin_x : cell.right - margin_x + 1,
    ]


def _autocontrast(grayscale: np.ndarray) -> np.ndarray:
    lo = int(np.percentile(grayscale, 3))
    hi = int(np.percentile(grayscale, 97))
    if hi <= lo or (hi - lo) < 20:
        return grayscale
    stretched = (grayscale.astype(np.float32) - lo) * (255.0 / (hi - lo))
    return np.clip(stretched, 0, 255).astype(np.uint8)


def _otsu_threshold(grayscale: np.ndarray) -> int:
    histogram = np.bincount(grayscale.flatten(), minlength=256).astype(np.float64)
    total = grayscale.size
    sum_total = np.dot(np.arange(256), histogram)
    sum_background = 0.0
    weight_background = 0.0
    max_variance = -1.0
    threshold = 160

    for level in range(256):
        weight_background += histogram[level]
        if weight_background == 0:
            continue

        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break

        sum_background += level * histogram[level]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_total - sum_background) / weight_foreground

        variance = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if variance > max_variance:
            max_variance = variance
            threshold = level

    return threshold


def _lift_grayscale_guides(grayscale: np.ndarray, guide_rows: list[int], scale: float, preserve_cutoff: int) -> np.ndarray:
    lifted = grayscale.copy()
    radius = max(6, int(np.ceil(scale * 3.0)))
    for guide_row in guide_rows:
        center = int(round(guide_row * scale))
        for row in range(max(0, center - radius), min(lifted.shape[0], center + radius + 1)):
            row_values = lifted[row]
            lift_mask = row_values > preserve_cutoff
            row_values[lift_mask] = 255
    return lifted


def _tight_bbox(binary: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(binary)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _template_guide_ratios_for_crop(
    cell_height: int,
    margin_y: int,
    guide_row_ratios: tuple[float, ...],
    margin_bottom_y: int | None = None,
) -> tuple[float, ...]:
    """Map template guide geometry into the actual extraction crop.

    Template rendering places guides between the top writing margin and a 5% descender
    bottom margin; extraction crops both top and bottom by inner_margin_y.  Keeping this
    adjustment local prevents guide removal from targeting user strokes in the wrong rows.
    """
    bottom_margin = margin_y if margin_bottom_y is None else margin_bottom_y
    crop_height = cell_height - margin_y - bottom_margin
    if crop_height <= 1:
        return guide_row_ratios
    guide_span = max(1, cell_height - margin_y - bottom_margin)
    adjusted: list[float] = []
    for ratio in guide_row_ratios:
        guide_y_in_cell = margin_y + (guide_span * ratio)
        adjusted.append(max(0.0, min(1.0, (guide_y_in_cell - margin_y) / crop_height)))
    return tuple(adjusted)


def _prepare_bitmap(
    gray: np.ndarray,
    cell: Cell,
    margin_x: int,
    margin_y: int,
    guide_row_ratios: tuple[float, ...],
    margin_bottom_y: int | None = None,
) -> GlyphBitmapResult:
    inner_crop = _cell_inner_crop(gray, cell, margin_x, margin_y, margin_bottom_y)
    scale = EM_SIZE / inner_crop.shape[0]
    target_width = max(1, int(round(inner_crop.shape[1] * scale)))
    guide_rows = [int(round(inner_crop.shape[0] * ratio)) for ratio in guide_row_ratios]

    image = Image.fromarray(inner_crop).resize((target_width, EM_SIZE), Image.Resampling.LANCZOS)
    precontrast = np.array(image)
    precontrast = _lift_grayscale_guides(
        precontrast,
        guide_rows=guide_rows,
        scale=EM_SIZE / inner_crop.shape[0],
        preserve_cutoff=45,
    )
    if int(precontrast.min()) > 220:
        bitmap = Image.new("L", (1, 1), 255).convert("1")
        return GlyphBitmapResult(bitmap=bitmap, top_offset=0, coverage=0.0, warnings=("likely-empty",), empty=True)

    image = Image.fromarray(precontrast)
    if int(precontrast.max()) - int(precontrast.min()) >= 20:
        image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.MedianFilter(size=3))
    image = image.filter(ImageFilter.GaussianBlur(radius=0.6))

    grayscale = _autocontrast(np.array(image))
    threshold = min(185, _otsu_threshold(grayscale) + 10)
    binary = grayscale < threshold

    smoothed = Image.fromarray(np.where(binary, 0, 255).astype(np.uint8))
    smoothed = smoothed.filter(ImageFilter.GaussianBlur(radius=0.75))
    binary = np.array(smoothed) < 210

    coverage = float(binary.sum()) / float(binary.size)
    warnings: list[str] = []
    if coverage < 0.015:
        warnings.append("likely-empty")
    if coverage > 0.60:
        warnings.append("ink-overflow")

    bbox = _tight_bbox(binary)
    if bbox is None:
        bitmap = Image.new("L", (1, 1), 255).convert("1")
        return GlyphBitmapResult(bitmap=bitmap, top_offset=0, coverage=coverage, warnings=tuple(warnings), empty=True)

    left, top, right, bottom = bbox
    tight = np.where(binary[top : bottom + 1, left : right + 1], 0, 255).astype(np.uint8)
    bitmap = Image.fromarray(tight, mode="L").convert("1")
    return GlyphBitmapResult(bitmap=bitmap, top_offset=top, coverage=coverage, warnings=tuple(warnings), empty=False)


def _prepare_accepted_mask(image_path: Path, baseline: float) -> GlyphBitmapResult:
    if not isinstance(baseline, (int, float)) or not np.isfinite(float(baseline)):
        raise MaskValidationError("Mask baseline must be a finite normalized number.")
    baseline = float(baseline)
    if not 0.0 < baseline < 1.0:
        raise MaskValidationError("Mask baseline must be strictly between 0 and 1.")

    try:
        with Image.open(image_path) as image:
            if image.format != "PNG":
                raise MaskValidationError("Accepted mask-v1 images must be PNG files.")
            gray_image = image.convert("L")
    except MaskValidationError:
        raise
    except Exception as exc:
        raise MaskValidationError(f"Could not read accepted mask PNG: {image_path}") from exc

    width, height = gray_image.size
    if width <= 0 or height <= 0:
        raise MaskValidationError("Mask dimensions must be positive.")
    if max(width, height) > MAX_MASK_SIDE or width * height > MAX_MASK_PIXELS:
        raise MaskValidationError(f"Mask dimensions must be at most {MAX_MASK_SIDE}px on the longest side.")
    aspect = max(width / height, height / width)
    if aspect > 8.0:
        raise MaskValidationError("Mask aspect ratio is too extreme to build a usable glyph.")

    grayscale = np.array(gray_image)
    binary = grayscale < 128
    foreground = int(binary.sum())
    pixels = int(binary.size)
    if foreground == 0:
        raise MaskValidationError("Mask is blank; no foreground pixels were found.")
    if foreground == pixels or (foreground / pixels) > 0.95:
        raise MaskValidationError("Mask is solid; foreground covers almost the entire image.")

    bbox = _tight_bbox(binary)
    if bbox is None:  # guarded by foreground check, kept defensive.
        raise MaskValidationError("Mask is blank; no foreground pixels were found.")

    left, top, right, bottom = bbox
    tight_binary = binary[top : bottom + 1, left : right + 1]
    tight = np.where(tight_binary, 0, 255).astype(np.uint8)
    bitmap = Image.fromarray(tight, mode="L").convert("1")

    scale = EM_SIZE / height
    source_width = max(1, int(round(bitmap.width * scale)))
    source_height = max(1, int(round(bitmap.height * scale)))
    top_offset = int(round(ASCENT - (baseline * EM_SIZE) + (top * scale)))
    coverage = foreground / pixels
    warnings: list[str] = []
    if coverage < 0.002:
        warnings.append("likely-empty")
    if coverage > 0.60:
        warnings.append("ink-overflow")

    return GlyphBitmapResult(
        bitmap=bitmap,
        top_offset=top_offset,
        coverage=coverage,
        warnings=tuple(warnings),
        empty=False,
        source_width=source_width,
        source_height=source_height,
        original_width=width,
        original_height=height,
    )


def _run_checked(command: list[str], cwd: Path) -> None:
    timeout = _subprocess_timeout_seconds()
    try:
        subprocess.run(command, cwd=cwd, check=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        tool = Path(command[0]).name if command else "subprocess"
        raise RuntimeError(f"{tool} timed out after {timeout}s.") from exc


def _vectorize_bitmap(bitmap_path: Path, svg_path: Path, cwd: Path) -> None:
    _run_checked(
        [
            "potrace",
            str(bitmap_path),
            "--svg",
            "--tight",
            "--turdsize",
            "4",
            "--alphamax",
            "0.9",
            "--opttolerance",
            "0.15",
            "--unit",
            "100",
            "--output",
            str(svg_path),
        ],
        cwd=cwd,
    )


def _validate_font_names(font_name: str, family_name: str | None, style_name: str) -> None:
    if not isinstance(font_name, str) or not _FONT_NAME_RE.fullmatch(font_name):
        raise ValueError("font_name must contain 2..63 letters, digits, underscores, or hyphens and start with an alphanumeric character.")
    if family_name is not None and (not isinstance(family_name, str) or not _FAMILY_STYLE_RE.fullmatch(family_name)):
        raise ValueError("family_name contains unsupported characters or is too long.")
    if not isinstance(style_name, str) or not _FAMILY_STYLE_RE.fullmatch(style_name):
        raise ValueError("style_name contains unsupported characters or is too long.")


def _safe_family_name(font_name: str, family_name: str | None) -> str:
    if family_name:
        return family_name
    return font_name.replace("-", " ").replace("_", " ")


def _validate_fonts(output_dir: Path, manifest_path: Path, *font_paths: Path) -> None:
    validator_script = Path(__file__).resolve().parents[2] / "scripts" / "fontforge_validate.py"
    try:
        _run_checked(["fontforge", "-script", str(validator_script), str(manifest_path), *(str(path) for path in font_paths)], cwd=output_dir)
    except subprocess.CalledProcessError as exc:
        raise FontValidationError("Generated OTF/TTF failed FontForge structural validation.") from exc


def _font_dependency_check() -> None:
    if shutil.which("potrace") is None:
        raise RuntimeError("Missing required dependency: potrace")
    if shutil.which("fontforge") is None:
        raise RuntimeError("Missing required dependency: fontforge")


def _dependency_check() -> None:
    _font_dependency_check()
    import cv2

    required = [
        hasattr(cv2, "aruco"),
        hasattr(cv2.aruco, "ArucoDetector"),
        hasattr(cv2.aruco, "getPredefinedDictionary"),
        hasattr(cv2.aruco, "generateImageMarker"),
    ]
    if not all(required):
        raise RuntimeError("Installed OpenCV package does not expose required ArUco APIs.")


def _warning_for(char: str, code: str, coverage: float) -> GlyphWarning:
    if code == "likely-empty":
        message = "Glyph has very low ink coverage and is likely empty."
    elif code == "ink-overflow":
        message = "Glyph has very high ink coverage and may include smudge or guide-line bleed."
    else:
        message = code
    return GlyphWarning(char=char, code=code, message=message, coverage=coverage)


def _glyph_record(char: str, result: GlyphBitmapResult, svg_value: str | None, advance_width: int) -> dict[str, object]:
    return {
        "char": char,
        "glyph_name": glyph_slug(char),
        "codepoint": ord(char),
        "svg_path": svg_value,
        "empty": bool(result.empty),
        "top_offset": int(result.top_offset),
        "source_width": int(result.source_width if result.source_width is not None else result.bitmap.width),
        "source_height": int(result.source_height if result.source_height is not None else result.bitmap.height),
        "advance_width": int(advance_width),
        "coverage": result.coverage,
        "warnings": list(result.warnings),
    }


def _generate_debug_mask_sheet(glyphs: list[tuple[str, Image.Image]], output_path: Path) -> None:
    cell = 96
    label_h = 18
    cols = min(8, max(1, len(glyphs)))
    rows = int(np.ceil(len(glyphs) / cols))
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (char, bitmap) in enumerate(glyphs):
        row, col = divmod(index, cols)
        x = col * cell
        y = row * (cell + label_h)
        draw.rectangle((x, y, x + cell - 1, y + cell + label_h - 1), outline=(220, 220, 220))
        preview = bitmap.convert("L")
        preview.thumbnail((cell - 16, cell - 24), Image.Resampling.LANCZOS)
        px = x + (cell - preview.width) // 2
        py = y + 6 + (cell - 24 - preview.height) // 2
        sheet.paste(ImageOps.colorize(preview, black="black", white="white"), (px, py))
        draw.text((x + 5, y + cell), char, fill=(40, 40, 40))
    sheet.save(output_path)


def _rectify_for_build(image_path: Path, *, alignment: str, corners: list[list[float]] | None, paper_size: str):
    if alignment not in {"markers", "page"}:
        raise ValueError("alignment must be 'markers' or 'page'.")
    signature = inspect.signature(rectify_template_photo)
    supports_alignment = "alignment" in signature.parameters
    supports_corners = "corners" in signature.parameters
    supports_paper_size = "paper_size" in signature.parameters
    requested_non_default = alignment != "markers" or corners is not None or paper_size.upper() != "A4"
    if alignment != "markers" and not supports_alignment:
        raise RuntimeError("rectify_template_photo does not yet support alignment options in this checkout.")
    if corners is not None and not supports_corners:
        raise RuntimeError("rectify_template_photo does not yet support manual corner options in this checkout.")
    if paper_size.upper() != "A4" and not supports_paper_size:
        raise RuntimeError("rectify_template_photo does not yet support paper_size options in this checkout.")
    if supports_alignment or supports_corners or supports_paper_size:
        kwargs: dict[str, Any] = {}
        if supports_alignment:
            kwargs["alignment"] = alignment
        if supports_corners:
            kwargs["corners"] = corners
        if supports_paper_size:
            kwargs["paper_size"] = paper_size
        return rectify_template_photo(image_path, **kwargs)
    if requested_non_default:
        raise RuntimeError("rectify_template_photo does not yet support alignment/corners/paper_size options in this checkout.")
    return rectify_template_photo(image_path)


def _validate_mask_glyphs(glyphs: list[dict[str, object]]) -> None:
    if not isinstance(glyphs, list) or not 1 <= len(glyphs) <= len(DEFAULT_CHARS):
        raise ValueError("guided glyph list must contain 1..94 glyphs.")
    seen: set[str] = set()
    for glyph in glyphs:
        char = glyph.get("char")
        if not isinstance(char, str) or len(char) != 1 or char not in PRINTABLE_NONSPACE_ASCII:
            raise ValueError("Each guided glyph char must be one printable non-space ASCII character.")
        if char in seen:
            raise ValueError(f"Duplicate guided glyph label: {char!r}")
        seen.add(char)
        if "image_path" not in glyph:
            raise ValueError(f"Guided glyph {char!r} is missing image_path.")
        if "baseline" not in glyph:
            raise ValueError(f"Guided glyph {char!r} is missing baseline.")


def _write_manifest_and_build(manifest: dict[str, object], output_dir: Path, debug_overlay: Path) -> dict[str, object]:
    work_dir = output_dir / "work"
    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    builder_script = Path(__file__).resolve().parents[2] / "scripts" / "fontforge_build.py"
    _run_checked(
        [
            "fontforge",
            "-script",
            str(builder_script),
            str(manifest_path),
            str(output_dir),
        ],
        cwd=output_dir,
    )

    font_name = str(manifest["font_name"])
    otf_path = output_dir / f"{font_name}.otf"
    ttf_path = output_dir / f"{font_name}.ttf"
    _validate_fonts(output_dir, manifest_path, otf_path, ttf_path)

    return {
        "manifest": str(manifest_path),
        "otf": str(otf_path),
        "ttf": str(ttf_path),
        "sfd": str(output_dir / f"{font_name}.sfd"),
        "debug_overlay": str(debug_overlay),
        "warnings": manifest.get("warnings", []),
    }


def build_font(
    *,
    image_path: Path,
    font_name: str,
    family_name: str | None,
    style_name: str,
    output_dir: Path,
    alignment: str = "markers",
    corners: list[list[float]] | None = None,
    paper_size: str = "A4",
) -> dict[str, object]:
    _dependency_check()
    _validate_font_names(font_name, family_name, style_name)
    output_dir = output_dir.expanduser().resolve()

    document = _rectify_for_build(image_path, alignment=alignment, corners=corners, paper_size=paper_size)
    cells = extract_cells(document.metadata, document.geometry)
    if len(cells) != len(document.layout.chars):
        raise RuntimeError(f"Expected {len(document.layout.chars)} cells, found {len(cells)}.")

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "work"
    bitmaps_dir = work_dir / "bitmaps"
    svg_dir = work_dir / "svg"
    bitmaps_dir.mkdir(parents=True, exist_ok=True)
    svg_dir.mkdir(parents=True, exist_ok=True)

    widths = [cell.width for cell in cells]
    heights = [cell.height for cell in cells]
    median_height = int(round(np.median(heights)))
    margin_x = max(4, int(round(np.median(widths) * document.layout.inner_margin_x)))
    margin_y = max(4, int(round(median_height * document.layout.inner_margin_y)))
    markerless_alignment = alignment == "page" or getattr(document, "alignment", "markers") == "page"
    bottom_margin_ratio = document.layout.inner_margin_y if markerless_alignment else 0.05
    margin_bottom_y = max(2, int(round(median_height * bottom_margin_ratio)))
    guide_ratios = _template_guide_ratios_for_crop(
        median_height, margin_y, document.layout.guide_rows, margin_bottom_y=margin_bottom_y
    )

    diagnostics = BuildDiagnostics()
    manifest_glyphs: list[dict[str, object]] = []
    advance_widths: list[int] = []

    for char, cell in zip(document.layout.chars, cells, strict=True):
        result = _prepare_bitmap(
            gray=document.rectified_gray,
            cell=cell,
            margin_x=margin_x,
            margin_y=margin_y,
            guide_row_ratios=guide_ratios,
            margin_bottom_y=margin_bottom_y,
        )
        for code in result.warnings:
            diagnostics.add(_warning_for(char, code, result.coverage))

        glyph_basename = f"{ord(char):04x}_{glyph_slug(char)}"
        bitmap_path = bitmaps_dir / f"{glyph_basename}.pbm"
        svg_path = svg_dir / f"{glyph_basename}.svg"
        result.bitmap.save(bitmap_path)

        if result.empty:
            svg_value: str | None = None
            advance_width = EMPTY_GLYPH_WIDTH
        else:
            _vectorize_bitmap(bitmap_path, svg_path, cwd=output_dir)
            svg_value = str(svg_path)
            advance_width = max(EMPTY_GLYPH_WIDTH, result.bitmap.width + (SIDE_BEARING * 2))

        advance_widths.append(advance_width)
        manifest_glyphs.append(_glyph_record(char, result, svg_value, advance_width))

    likely_empty_count = sum(1 for warning in diagnostics.warnings if warning.code == "likely-empty")
    if likely_empty_count > 5:
        diagnostics.add(
            GlyphWarning(
                char="*",
                code="likely-empty-summary",
                message=f"{likely_empty_count} glyphs look likely empty; consider re-shooting if this was not intentional.",
                coverage=0.0,
            )
        )

    average_width = int(round(sum(advance_widths) / len(advance_widths)))
    family = _safe_family_name(font_name, family_name)
    manifest = {
        "font_name": font_name,
        "family_name": family,
        "style_name": style_name,
        "full_name": f"{family} {style_name}",
        "em_size": EM_SIZE,
        "ascent": ASCENT,
        "descent": DESCENT,
        "side_bearing": SIDE_BEARING,
        "space_width": max(260, int(round(average_width * 0.45))),
        "glyphs": manifest_glyphs,
        "template": {
            "layout_id": document.metadata.layout_id,
            "paper_size": document.metadata.paper_size,
            "character_count": document.metadata.character_count,
            "reprojection_error_px": document.reprojection_error_px,
            "alignment": alignment,
        },
        "warnings": diagnostics.as_dicts(),
    }

    debug_overlay = output_dir / "rectified-template.png"
    save_debug_overlay(document.rectified_gray, cells, debug_overlay)
    return _write_manifest_and_build(manifest, output_dir, debug_overlay)


def build_font_from_masks(
    *,
    glyphs: list[dict[str, object]],
    font_name: str,
    family_name: str | None,
    style_name: str,
    output_dir: Path,
) -> dict[str, object]:
    _font_dependency_check()
    _validate_font_names(font_name, family_name, style_name)
    _validate_mask_glyphs(glyphs)
    output_dir = output_dir.expanduser().resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "work"
    bitmaps_dir = work_dir / "bitmaps"
    svg_dir = work_dir / "svg"
    bitmaps_dir.mkdir(parents=True, exist_ok=True)
    svg_dir.mkdir(parents=True, exist_ok=True)

    diagnostics = BuildDiagnostics()
    manifest_glyphs: list[dict[str, object]] = []
    advance_widths: list[int] = []
    debug_bitmaps: list[tuple[str, Image.Image]] = []

    for glyph in glyphs:
        char = str(glyph["char"])
        image_path = Path(glyph["image_path"]).expanduser().resolve()
        baseline = float(glyph["baseline"])
        result = _prepare_accepted_mask(image_path, baseline)
        for code in result.warnings:
            diagnostics.add(_warning_for(char, code, result.coverage))

        glyph_basename = f"{ord(char):04x}_{glyph_slug(char)}"
        bitmap_path = bitmaps_dir / f"{glyph_basename}.pbm"
        svg_path = svg_dir / f"{glyph_basename}.svg"
        result.bitmap.save(bitmap_path)
        _vectorize_bitmap(bitmap_path, svg_path, cwd=output_dir)

        scaled_ink_width = int(result.source_width if result.source_width is not None else result.bitmap.width)
        advance_width = max(EMPTY_GLYPH_WIDTH, scaled_ink_width + (SIDE_BEARING * 2))
        advance_widths.append(advance_width)
        manifest_glyphs.append(_glyph_record(char, result, str(svg_path), advance_width))
        debug_bitmaps.append((char, result.bitmap.copy()))

    average_width = int(round(sum(advance_widths) / len(advance_widths)))
    family = _safe_family_name(font_name, family_name)
    manifest = {
        "font_name": font_name,
        "family_name": family,
        "style_name": style_name,
        "full_name": f"{family} {style_name}",
        "em_size": EM_SIZE,
        "ascent": ASCENT,
        "descent": DESCENT,
        "side_bearing": SIDE_BEARING,
        "space_width": max(260, int(round(average_width * 0.45))),
        "glyphs": manifest_glyphs,
        "mask_format": "mask-v1",
        "warnings": diagnostics.as_dicts(),
    }

    debug_overlay = output_dir / "accepted-mask-preview.png"
    _generate_debug_mask_sheet(debug_bitmaps, debug_overlay)
    return _write_manifest_and_build(manifest, output_dir, debug_overlay)


def cli_build(
    image: str,
    font_name: str,
    family_name: str | None,
    style_name: str,
    output_dir: str,
) -> int:
    outputs = build_font(
        image_path=Path(image).expanduser().resolve(),
        font_name=font_name,
        family_name=family_name,
        style_name=style_name,
        output_dir=Path(output_dir).expanduser().resolve(),
    )

    print(json.dumps(outputs, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    from .cli import build_parser
    from .template import generate_template_pdf

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        return cli_build(
            image=args.image,
            font_name=args.font_name,
            family_name=args.family_name,
            style_name=args.style_name,
            output_dir=args.output_dir,
        )
    if args.command == "generate-template":
        output = generate_template_pdf(args.output, layout_id=args.layout, paper_size=args.paper_size)
        print(json.dumps({"template": str(output)}, indent=2))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
