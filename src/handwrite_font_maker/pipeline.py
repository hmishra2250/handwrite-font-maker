from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .layout import DEFAULT_LAYOUT, glyph_slug

EM_SIZE = 1000
SIDE_BEARING = 80


@dataclass(frozen=True)
class Run:
    start: int
    end: int
    score: float

    @property
    def center(self) -> int:
        return int(round((self.start + self.end) / 2))


@dataclass(frozen=True)
class Cell:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1


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


def _detect_grid_runs(line_sums: np.ndarray, expected: int, axis_length: int) -> list[Run]:
    high = float(np.quantile(line_sums, 0.995))
    threshold = max(10.0, high * 0.72)
    runs = _find_binary_runs(line_sums >= threshold, line_sums)
    runs = [
        run
        for run in runs
        if run.start > 1 and run.end < len(line_sums) - 2 and run.score < axis_length * 0.95
    ]
    if len(runs) > expected:
        runs = sorted(runs, key=lambda run: run.score, reverse=True)[:expected]
        runs = sorted(runs, key=lambda run: run.start)
    if len(runs) != expected:
        raise RuntimeError(f"Expected {expected} grid lines, found {len(runs)}.")
    return runs


def _pair_runs(runs: list[Run]) -> list[tuple[int, int]]:
    if len(runs) % 2 != 0:
        raise RuntimeError("Grid line count is not even.")
    return [(runs[index].start, runs[index + 1].end) for index in range(0, len(runs), 2)]


def _load_grayscale(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("L"))


def _detect_cells(gray: np.ndarray) -> list[Cell]:
    mask = gray < 180
    vertical_runs = _detect_grid_runs(mask.sum(axis=0), expected=16, axis_length=gray.shape[0])
    horizontal_runs = _detect_grid_runs(mask.sum(axis=1), expected=20, axis_length=gray.shape[1])

    columns = _pair_runs(vertical_runs)
    rows = _pair_runs(horizontal_runs)
    return [Cell(left, top, right, bottom) for top, bottom in rows for left, right in columns]


def _cell_inner_crop(gray: np.ndarray, cell: Cell, margin_x: int, margin_y: int) -> np.ndarray:
    return gray[
        cell.top + margin_y : cell.bottom - margin_y + 1,
        cell.left + margin_x : cell.right - margin_x + 1,
    ]


def _estimate_guide_rows(gray: np.ndarray, cells: list[Cell], margin_x: int, margin_y: int) -> tuple[list[int], int]:
    inner_heights = [cell.height - (margin_y * 2) for cell in cells]
    inner_widths = [cell.width - (margin_x * 2) for cell in cells]
    target_height = min(inner_heights)
    target_width = min(inner_widths)

    normalized: list[np.ndarray] = []
    for cell in cells:
        crop = _cell_inner_crop(gray, cell, margin_x, margin_y)
        image = Image.fromarray(crop).resize((target_width, target_height), Image.Resampling.BICUBIC)
        normalized.append(np.array(image))

    median_image = np.median(np.stack(normalized, axis=0), axis=0)
    darkness = 255.0 - median_image.mean(axis=1)
    smoothed = np.convolve(darkness, np.ones(3) / 3.0, mode="same")
    threshold = float(np.median(smoothed) + (np.std(smoothed) * 0.85))
    runs = _find_binary_runs(smoothed >= threshold, smoothed)

    centers = [run.center for run in runs]
    if len(centers) < 3:
        centers = [int(target_height * ratio) for ratio in (0.12, 0.33, 0.67, 0.88)]

    return centers, target_height


def _draw_debug_overlay(image_path: Path, cells: list[Cell], output_path: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    for cell in cells:
        draw.rectangle((cell.left, cell.top, cell.right, cell.bottom), outline=(220, 50, 50), width=2)
    image.save(output_path)


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
            dark_positions = np.where(cleaned[row])[0]
            if not len(dark_positions):
                continue
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


def _tight_bbox(binary: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(binary)
    if len(xs) == 0 or len(ys) == 0:
        raise RuntimeError("Encountered an empty glyph after cleanup.")
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
    guide_rows: list[int],
    target_inner_height: int,
) -> tuple[Image.Image, int]:
    inner_crop = _cell_inner_crop(gray, cell, margin_x, margin_y)
    scale = EM_SIZE / inner_crop.shape[0]
    target_width = max(1, int(round(inner_crop.shape[1] * scale)))

    image = Image.fromarray(inner_crop).resize((target_width, EM_SIZE), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.MedianFilter(size=3))
    image = image.filter(ImageFilter.GaussianBlur(radius=0.6))

    grayscale = _autocontrast(np.array(image))
    threshold = min(185, _otsu_threshold(grayscale) + 10)
    grayscale = _lift_grayscale_guides(
        grayscale,
        guide_rows=guide_rows,
        scale=EM_SIZE / target_inner_height,
        preserve_cutoff=max(95, threshold - 28),
    )
    binary = grayscale < threshold
    binary = _clear_guides(binary, guide_rows=guide_rows, scale=EM_SIZE / target_inner_height)

    # Re-binarize after a light blur to smooth JPEG artifacts before tracing.
    smoothed = Image.fromarray(np.where(binary, 0, 255).astype(np.uint8))
    smoothed = smoothed.filter(ImageFilter.GaussianBlur(radius=0.75))
    binary = np.array(smoothed) < 210
    binary = _remove_full_width_horizontal_runs(binary)

    left, top, right, bottom = _tight_bbox(binary)
    tight = np.where(binary[top : bottom + 1, left : right + 1], 0, 255).astype(np.uint8)
    bitmap = Image.fromarray(tight, mode="L").convert("1")
    return bitmap, top


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


def build_font(
    *,
    image_path: Path,
    font_name: str,
    family_name: str | None,
    style_name: str,
    output_dir: Path,
) -> dict[str, str]:
    if shutil.which("potrace") is None:
        raise RuntimeError("Missing required dependency: potrace")
    if shutil.which("fontforge") is None:
        raise RuntimeError("Missing required dependency: fontforge")

    gray = _load_grayscale(image_path)
    cells = _detect_cells(gray)
    if len(cells) != len(DEFAULT_LAYOUT):
        raise RuntimeError(f"Expected {len(DEFAULT_LAYOUT)} cells, found {len(cells)}.")

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "work"
    bitmaps_dir = work_dir / "bitmaps"
    svg_dir = work_dir / "svg"
    bitmaps_dir.mkdir(parents=True, exist_ok=True)
    svg_dir.mkdir(parents=True, exist_ok=True)

    widths = [cell.width for cell in cells]
    heights = [cell.height for cell in cells]
    margin_x = max(4, int(round(np.median(widths) * 0.08)))
    margin_y = max(4, int(round(np.median(heights) * 0.04)))
    guide_rows, guide_reference_height = _estimate_guide_rows(gray, cells, margin_x, margin_y)

    baseline_row = guide_rows[-2]
    ascent = int(round(EM_SIZE * (baseline_row / guide_reference_height)))
    ascent = max(550, min(800, ascent))
    descent = EM_SIZE - ascent

    manifest_glyphs: list[dict[str, object]] = []
    advance_widths: list[int] = []

    for char, cell in zip(DEFAULT_LAYOUT, cells, strict=True):
        bitmap, top_offset = _prepare_bitmap(
            gray=gray,
            cell=cell,
            margin_x=margin_x,
            margin_y=margin_y,
            guide_rows=guide_rows,
            target_inner_height=guide_reference_height,
        )
        glyph_basename = f"{ord(char):04x}_{glyph_slug(char)}"
        bitmap_path = bitmaps_dir / f"{glyph_basename}.pbm"
        svg_path = svg_dir / f"{glyph_basename}.svg"
        bitmap.save(bitmap_path)
        _vectorize_bitmap(bitmap_path, svg_path, cwd=output_dir)

        advance_width = max(280, bitmap.width + (SIDE_BEARING * 2))
        advance_widths.append(advance_width)
        manifest_glyphs.append(
            {
                "char": char,
                "codepoint": ord(char),
                "svg_path": str(svg_path),
                "top_offset": int(top_offset),
                "source_width": int(bitmap.width),
                "source_height": int(bitmap.height),
                "advance_width": int(advance_width),
            }
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
    }

    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _draw_debug_overlay(image_path, cells, output_dir / "detected-grid.png")

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

    return {
        "manifest": str(manifest_path),
        "otf": str(output_dir / f"{font_name}.otf"),
        "ttf": str(output_dir / f"{font_name}.ttf"),
        "sfd": str(output_dir / f"{font_name}.sfd"),
        "debug_overlay": str(output_dir / "detected-grid.png"),
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

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
