from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .diagnostics import BuildDiagnostics, FontValidationError, GlyphWarning
from .extract import Cell, extract_cells, save_debug_overlay
from .layout import get_layout, glyph_slug
from .rectify import rectify_template_photo

EM_SIZE = 1000
SIDE_BEARING = 80
EMPTY_GLYPH_WIDTH = 280


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


def _cell_inner_crop(gray: np.ndarray, cell: Cell, margin_x: int, margin_y: int) -> np.ndarray:
    return gray[
        cell.top + margin_y : cell.bottom - margin_y + 1,
        cell.left + margin_x : cell.right - margin_x + 1,
    ]


def _autocontrast(grayscale: np.ndarray) -> np.ndarray:
    lo = int(np.percentile(grayscale, 3))
    hi = int(np.percentile(grayscale, 97))
    if hi <= lo:
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


def _clear_guides(binary: np.ndarray, guide_rows: list[int], scale: float) -> np.ndarray:
    cleaned = binary.copy()
    width = cleaned.shape[1]
    for guide_row in guide_rows:
        center = int(round(guide_row * scale))
        for row in range(max(0, center - 2), min(cleaned.shape[0], center + 3)):
            runs = _find_binary_runs(cleaned[row], cleaned[row].astype(np.float32))
            for run in runs:
                if (run.end - run.start + 1) >= int(width * 0.45):
                    cleaned[row, run.start : run.end + 1] = False
    return cleaned


def _lift_grayscale_guides(grayscale: np.ndarray, guide_rows: list[int], scale: float, preserve_cutoff: int) -> np.ndarray:
    lifted = grayscale.copy()
    for guide_row in guide_rows:
        center = int(round(guide_row * scale))
        for row in range(max(0, center - 2), min(lifted.shape[0], center + 3)):
            row_values = lifted[row]
            lift_mask = row_values > preserve_cutoff
            row_values[lift_mask] = 255
    return lifted


def _tight_bbox(binary: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(binary)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _remove_full_width_horizontal_runs(binary: np.ndarray) -> np.ndarray:
    cleaned = binary.copy()
    min_run = int(cleaned.shape[1] * 0.18)
    min_row_coverage = int(cleaned.shape[1] * 0.55)
    for row in range(cleaned.shape[0]):
        if int(cleaned[row].sum()) < min_row_coverage:
            continue
        runs = _find_binary_runs(cleaned[row], cleaned[row].astype(np.float32))
        for run in runs:
            if (run.end - run.start + 1) >= min_run:
                cleaned[row, run.start : run.end + 1] = False
    return cleaned


def _prepare_bitmap(
    gray: np.ndarray,
    cell: Cell,
    margin_x: int,
    margin_y: int,
    guide_row_ratios: tuple[float, ...],
) -> GlyphBitmapResult:
    inner_crop = _cell_inner_crop(gray, cell, margin_x, margin_y)
    scale = EM_SIZE / inner_crop.shape[0]
    target_width = max(1, int(round(inner_crop.shape[1] * scale)))
    guide_rows = [int(round(inner_crop.shape[0] * ratio)) for ratio in guide_row_ratios]

    image = Image.fromarray(inner_crop).resize((target_width, EM_SIZE), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.MedianFilter(size=3))
    image = image.filter(ImageFilter.GaussianBlur(radius=0.6))

    grayscale = _autocontrast(np.array(image))
    threshold = min(185, _otsu_threshold(grayscale) + 10)
    grayscale = _lift_grayscale_guides(
        grayscale,
        guide_rows=guide_rows,
        scale=EM_SIZE / inner_crop.shape[0],
        preserve_cutoff=max(95, threshold - 28),
    )
    binary = grayscale < threshold
    binary = _clear_guides(binary, guide_rows=guide_rows, scale=EM_SIZE / inner_crop.shape[0])

    smoothed = Image.fromarray(np.where(binary, 0, 255).astype(np.uint8))
    smoothed = smoothed.filter(ImageFilter.GaussianBlur(radius=0.75))
    binary = np.array(smoothed) < 210
    binary = _remove_full_width_horizontal_runs(binary)

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


def _run_checked(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


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


def _safe_family_name(font_name: str, family_name: str | None) -> str:
    if family_name:
        return family_name
    return font_name.replace("-", " ").replace("_", " ")


def _validate_fonts(output_dir: Path, *font_paths: Path) -> None:
    validator_script = Path(__file__).resolve().parents[2] / "scripts" / "fontforge_validate.py"
    try:
        _run_checked(["fontforge", "-script", str(validator_script), *(str(path) for path in font_paths)], cwd=output_dir)
    except subprocess.CalledProcessError as exc:
        raise FontValidationError("Generated OTF/TTF failed FontForge load validation.") from exc


def _dependency_check() -> None:
    if shutil.which("potrace") is None:
        raise RuntimeError("Missing required dependency: potrace")
    if shutil.which("fontforge") is None:
        raise RuntimeError("Missing required dependency: fontforge")
    import cv2

    required = [
        hasattr(cv2, "aruco"),
        hasattr(cv2.aruco, "ArucoDetector"),
        hasattr(cv2.aruco, "getPredefinedDictionary"),
        hasattr(cv2.aruco, "generateImageMarker"),
        hasattr(cv2, "QRCodeDetector"),
    ]
    if not all(required):
        raise RuntimeError("Installed OpenCV package does not expose required ArUco/QR APIs.")


def _warning_for(char: str, code: str, coverage: float) -> GlyphWarning:
    if code == "likely-empty":
        message = "Glyph has very low ink coverage and is likely empty."
    elif code == "ink-overflow":
        message = "Glyph has very high ink coverage and may include smudge or guide-line bleed."
    else:
        message = code
    return GlyphWarning(char=char, code=code, message=message, coverage=coverage)


def build_font(
    *,
    image_path: Path,
    font_name: str,
    family_name: str | None,
    style_name: str,
    output_dir: Path,
) -> dict[str, object]:
    _dependency_check()

    document = rectify_template_photo(image_path)
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
    margin_x = max(4, int(round(np.median(widths) * document.layout.inner_margin_x)))
    margin_y = max(4, int(round(np.median(heights) * document.layout.inner_margin_y)))

    # Baseline follows schema-defined guide geometry; second-to-last guide is the baseline analogue.
    baseline_ratio = document.layout.guide_rows[-2]
    ascent = int(round(EM_SIZE * baseline_ratio))
    ascent = max(550, min(800, ascent))
    descent = EM_SIZE - ascent

    diagnostics = BuildDiagnostics()
    manifest_glyphs: list[dict[str, object]] = []
    advance_widths: list[int] = []

    for char, cell in zip(document.layout.chars, cells, strict=True):
        result = _prepare_bitmap(
            gray=document.rectified_gray,
            cell=cell,
            margin_x=margin_x,
            margin_y=margin_y,
            guide_row_ratios=document.layout.guide_rows,
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
        manifest_glyphs.append(
            {
                "char": char,
                "codepoint": ord(char),
                "svg_path": svg_value,
                "empty": bool(result.empty),
                "top_offset": int(result.top_offset),
                "source_width": int(result.bitmap.width),
                "source_height": int(result.bitmap.height),
                "advance_width": int(advance_width),
                "coverage": result.coverage,
                "warnings": list(result.warnings),
            }
        )

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
    manifest = {
        "font_name": font_name,
        "family_name": _safe_family_name(font_name, family_name),
        "style_name": style_name,
        "full_name": f"{_safe_family_name(font_name, family_name)} {style_name}",
        "em_size": EM_SIZE,
        "ascent": ascent,
        "descent": descent,
        "side_bearing": SIDE_BEARING,
        "space_width": max(260, int(round(average_width * 0.45))),
        "glyphs": manifest_glyphs,
        "template": {
            "layout_id": document.metadata.layout_id,
            "paper_size": document.metadata.paper_size,
            "character_count": document.metadata.character_count,
            "reprojection_error_px": document.reprojection_error_px,
        },
        "warnings": diagnostics.as_dicts(),
    }

    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    debug_overlay = output_dir / "detected-grid.png"
    save_debug_overlay(document.rectified_gray, cells, debug_overlay)

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

    otf_path = output_dir / f"{font_name}.otf"
    ttf_path = output_dir / f"{font_name}.ttf"
    _validate_fonts(output_dir, otf_path, ttf_path)

    return {
        "manifest": str(manifest_path),
        "otf": str(otf_path),
        "ttf": str(ttf_path),
        "sfd": str(output_dir / f"{font_name}.sfd"),
        "debug_overlay": str(debug_overlay),
        "warnings": diagnostics.as_dicts(),
    }


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
