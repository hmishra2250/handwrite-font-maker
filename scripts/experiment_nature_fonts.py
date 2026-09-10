#!/usr/bin/env python3
"""Real nature-image segmentation probes and a small generated font.

The harness is deliberately sequential and reproducible: it reads source photos
from an ignored local image directory, applies explicit rectangles/points, records
honest per-method outcomes, and builds a few-glyph mask-v1 font only from masks
that have explicit review labels.  It does not invent ground truth for real photos
and it does not perform automatic AI style completion.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from handwrite_font_maker.foreground import MAX_CUTOUT_SIDE, extract_foreground

Rectangle = tuple[float, float, float, float]
PromptPoint = dict[str, float | int]
Mask = np.ndarray
ImageBgr = np.ndarray
Segmenter = Callable[[ImageBgr, Rectangle, Sequence[PromptPoint], str | None], Mask]

MASK_CONVENTION = "uint8 grayscale mask: 0/black = foreground, 255/white = background"
SCOPE_NOTE = "Real-photo qualitative experiment; no hand-labeled ground truth or accuracy claim."


@dataclass(frozen=True)
class NatureCase:
    case_id: str
    glyph: str
    glyph_idea: str
    filename: str
    rectangle: Rectangle
    points: tuple[PromptPoint, ...]
    preferred_methods: tuple[str, ...]
    review_label: str
    review_rationale: str
    color_strategy: str | None = None
    baseline: float = 0.78


DEFAULT_CASES: tuple[NatureCase, ...] = (
    NatureCase(
        case_id="leaf_isolated",
        glyph="L",
        glyph_idea="single maple leaf silhouette",
        filename="isolated_leaf__Autumn_Silver_Maple_Leaf.jpg",
        rectangle=(0.033576, 0.023562, 0.970901, 0.9839),
        points=(
            {"x": 0.506435, "y": 0.484979, "label": 1},
            {"x": 0.498041, "y": 0.145297, "label": 1},
            {"x": 0.218243, "y": 0.5537, "label": 1},
            {"x": 0.786234, "y": 0.557628, "label": 1},
            {"x": 0.500839, "y": 0.899273, "label": 1},
            {"x": 0.044768, "y": 0.031415, "label": 0},
        ),
        preferred_methods=("grabcut", "efficientsam", "slimsam"),
        review_label="accepted_for_font",
        review_rationale="manifest crop covers the whole isolated leaf; first pass showed GrabCut preserved lower lobes better than EfficientSAM.",
    ),
    NatureCase(
        case_id="oak_leaf_single",
        glyph="B",
        glyph_idea="single oak leaf from branch photo",
        filename="whole_branch__Small_oak_branch.jpg",
        rectangle=(0.46, 0.30, 0.78, 0.69),
        points=(
            {"x": 0.62, "y": 0.49, "label": 1},
            {"x": 0.70, "y": 0.37, "label": 1},
            {"x": 0.51, "y": 0.59, "label": 1},
            {"x": 0.83, "y": 0.42, "label": 0},
            {"x": 0.52, "y": 0.27, "label": 0},
        ),
        preferred_methods=("efficientsam", "slimsam", "grabcut"),
        review_label="accepted_for_font_if_coherent",
        review_rationale="refined from whole-branch clutter to one prominent oak leaf to avoid accepting a huge-background mask.",
    ),
    NatureCase(
        case_id="fern_frond",
        glyph="F",
        glyph_idea="emerging fern frond",
        filename="fern_thin_structure__Close-up_of_Emerging_Fern_Frond_in_Spring.jpg",
        rectangle=(0.05, 0.427778, 0.654167, 0.713889),
        points=(
            {"x": 0.179167, "y": 0.544444, "label": 1},
            {"x": 0.358333, "y": 0.561111, "label": 1},
            {"x": 0.525, "y": 0.50, "label": 1},
            {"x": 0.55, "y": 0.655556, "label": 1},
            {"x": 0.779167, "y": 0.333333, "label": 0},
            {"x": 0.791667, "y": 0.666667, "label": 0},
        ),
        preferred_methods=("efficientsam", "grabcut", "slimsam"),
        review_label="accepted_for_font_if_thin_stem_survives",
        review_rationale="manifest crop excludes most vertical wood; first pass rejected SlimSAM's large black rectangle and prefers smaller plant masks.",
    ),
    NatureCase(
        case_id="river_meander",
        glyph="M",
        glyph_idea="satellite meandering river",
        filename="satellite_meander__Meandering_Mississippi_5182095595.jpg",
        rectangle=(0.378788, 0.035014, 0.918911, 0.959398),
        points=(
            {"x": 0.774411, "y": 0.193277, "label": 1},
            {"x": 0.636925, "y": 0.390756, "label": 1},
            {"x": 0.624299, "y": 0.589636, "label": 1},
            {"x": 0.45174, "y": 0.792717, "label": 1},
            {"x": 0.728114, "y": 0.901961, "label": 1},
            {"x": 0.123457, "y": 0.145658, "label": 0},
            {"x": 0.159933, "y": 0.588235, "label": 0},
        ),
        preferred_methods=("water-color", "efficientsam", "slimsam", "grabcut"),
        review_label="reported_failure_not_font_default",
        review_rationale="river/delta probes are useful diagnostics, but current masks are blob/noisy candidates rather than recognizable river glyphs; exclude from default font.",
        color_strategy="water",
        baseline=0.70,
    ),
    NatureCase(
        case_id="delta_oasis",
        glyph="D",
        glyph_idea="satellite delta/lake basin",
        filename="satellite_delta_oasis__A_Delta_Oasis_in_Southeastern_Kazakhstan.jpg",
        rectangle=(0.123869, 0.05717, 0.862315, 0.855169),
        points=(
            {"x": 0.524059, "y": 0.281086, "label": 1},
            {"x": 0.407337, "y": 0.583611, "label": 1},
            {"x": 0.681277, "y": 0.402573, "label": 1},
            {"x": 0.266794, "y": 0.731301, "label": 1},
            {"x": 0.085755, "y": 0.119104, "label": 0},
            {"x": 0.905193, "y": 0.857551, "label": 0},
        ),
        preferred_methods=("grabcut", "efficientsam", "slimsam", "water-color"),
        review_label="reported_failure_not_font_default",
        review_rationale="broad water/ice/delta basin remains too blob-like for a reviewed glyph; report methods but exclude from default font.",
        color_strategy="water",
        baseline=0.70,
    ),
    NatureCase(
        case_id="braided_river_badcase",
        glyph="R",
        glyph_idea="braided river stress case",
        filename="satellite_braided__Braided_River_in_Tibet_Redraws_Its_Channels_154747.jpg",
        rectangle=(0.0, 0.3375, 1.0, 0.725),
        points=(
            {"x": 0.145833, "y": 0.54, "label": 1},
            {"x": 0.347222, "y": 0.545, "label": 1},
            {"x": 0.506944, "y": 0.525, "label": 1},
            {"x": 0.798611, "y": 0.53, "label": 1},
            {"x": 0.433333, "y": 0.4275, "label": 0},
            {"x": 0.058333, "y": 0.9425, "label": 0},
        ),
        preferred_methods=("water-color", "efficientsam", "slimsam", "grabcut"),
        review_label="reported_badcase_not_font_default",
        review_rationale="diagnostic braided-channel case with map text/scale artifacts; report quality but do not include in the default font subset.",
        color_strategy="water",
        baseline=0.70,
    ),
)

def _portable(path: Path, root: Path | None = None) -> str:
    path = path.resolve()
    for base in [root.resolve() if root else None, Path.cwd().resolve()]:
        if base is None:
            continue
        try:
            return str(path.relative_to(base))
        except ValueError:
            pass
    return path.name


def _validate_rectangle(rectangle: Rectangle) -> None:
    if len(rectangle) != 4 or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)) for v in rectangle):
        raise ValueError("rectangle must contain four finite normalized numbers")
    left, top, right, bottom = map(float, rectangle)
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("rectangle must be normalized left/top/right/bottom with positive area")


def _validate_points(points: Sequence[PromptPoint], rectangle: Rectangle) -> None:
    _validate_rectangle(rectangle)
    left, top, right, bottom = rectangle
    if not points:
        raise ValueError("each nature case needs at least one explicit keep/exclude point")
    for point in points:
        if set(point) != {"x", "y", "label"}:
            raise ValueError("points must have x, y, label")
        x = point["x"]
        y = point["y"]
        label = point["label"]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)) or not 0 <= float(v) <= 1 for v in (x, y)):
            raise ValueError("point coordinates must be finite normalized numbers")
        if label not in (0, 1) or isinstance(label, bool):
            raise ValueError("point label must be 1 keep or 0 exclude")
        if label == 1 and not (left <= float(x) <= right and top <= float(y) <= bottom):
            raise ValueError("keep points must be inside the rectangle")


def _load_bgr(path: Path) -> ImageBgr:
    with Image.open(path) as image:
        oriented = ImageOps.exif_transpose(image)
        if 'A' in oriented.getbands() or 'transparency' in oriented.info:
            rgba = oriented.convert('RGBA')
            oriented = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba)
        rgb = oriented.convert('RGB')
    return np.asarray(rgb, dtype=np.uint8)[:, :, ::-1].copy()


def _bounded_source(image_bgr: ImageBgr) -> ImageBgr:
    height, width = image_bgr.shape[:2]
    scale = min(1.0, MAX_CUTOUT_SIDE / max(height, width))
    if scale >= 1.0:
        return image_bgr.copy()
    return cv2.resize(image_bgr, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)


def _mask_binary(mask: Mask) -> Mask:
    arr = np.asarray(mask)
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_BGR2GRAY)
    if arr.ndim != 2:
        raise ValueError("method returned non-2D mask")
    return np.where(arr < 128, 0, 255).astype(np.uint8)


def _foreground(mask: Mask) -> np.ndarray:
    return _mask_binary(mask) < 128


def topology(mask: Mask) -> dict[str, int]:
    fg = _foreground(mask).astype(np.uint8)
    count, _ = cv2.connectedComponents(fg, connectivity=8)
    contours, hierarchy = cv2.findContours(fg, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    holes = 0 if hierarchy is None else sum(int(item[3] >= 0) for item in hierarchy[0])
    return {"components": int(count - 1), "holes": int(holes)}


def mask_diagnostics(mask: Mask) -> dict[str, Any]:
    binary = _foreground(mask)
    height, width = binary.shape
    pixels = int(binary.size)
    foreground = int(binary.sum())
    if foreground:
        ys, xs = np.where(binary)
        bbox = [round(float(xs.min()) / width, 6), round(float(ys.min()) / height, 6), round(float(xs.max() + 1) / width, 6), round(float(ys.max() + 1) / height, 6)]
    else:
        bbox = None
    warnings: list[str] = []
    coverage = foreground / pixels if pixels else 0.0
    if foreground == 0:
        warnings.append("blank-mask")
    if coverage > 0.60:
        warnings.append("high-coverage")
    if coverage < 0.002:
        warnings.append("very-low-coverage")
    return {
        "shape": [int(height), int(width)],
        "foreground_pixels": foreground,
        "coverage": round(float(coverage), 6),
        "bbox": bbox,
        "topology": topology(mask),
        "warnings": warnings,
    }


def _roi_bounds(shape: tuple[int, int], rectangle: Rectangle) -> tuple[int, int, int, int]:
    height, width = shape
    left, top, right, bottom = rectangle
    x0 = max(0, int(left * width))
    y0 = max(0, int(top * height))
    x1 = min(width, math.ceil(right * width))
    y1 = min(height, math.ceil(bottom * height))
    return x0, y0, x1, y1


def _remove_small_components(selected: np.ndarray, min_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(selected.astype(np.uint8), connectivity=8)
    keep = np.zeros_like(selected, dtype=bool)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area:
            keep |= labels == label
    return keep


def water_color_mask(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint] = ()) -> Mask:
    """Classical sampled water mask for satellite rivers/deltas.

    It uses explicit keep points as color samples plus a conservative blue/green
    satellite-water rule, then removes tiny speckles by area. It does not keep
    only one largest component, so separate channels/oxbows can survive.
    """

    source = _bounded_source(image_bgr)
    height, width = source.shape[:2]
    x0, y0, x1, y1 = _roi_bounds((height, width), rectangle)
    rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(source, cv2.COLOR_BGR2LAB).astype(np.float32)
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    sampled = np.zeros((height, width), dtype=bool)
    for point in points:
        if point["label"] != 1:
            continue
        px = min(width - 1, max(0, int(float(point["x"]) * width)))
        py = min(height - 1, max(0, int(float(point["y"]) * height)))
        patch = lab[max(0, py - 3):min(height, py + 4), max(0, px - 3):min(width, px + 4)]
        if patch.size == 0:
            continue
        sample = np.median(patch.reshape(-1, 3), axis=0)
        distance = np.linalg.norm(lab - sample, axis=2)
        sampled |= distance < 24
    blue_green = ((h >= 72) & (h <= 112) & (s >= 45) & (v >= 55) & (b > r + 14) & (g > r + 6))
    dark_channel = (v < 65) & (b > r + 3) & (g >= r - 8)
    selected = sampled | blue_green | dark_channel
    roi = np.zeros((height, width), dtype=bool)
    roi[y0:y1, x0:x1] = True
    selected &= roi
    kernel = np.ones((3, 3), np.uint8)
    selected = cv2.morphologyEx(selected.astype(np.uint8), cv2.MORPH_CLOSE, kernel, iterations=1).astype(bool)
    selected = _remove_small_components(selected, min_area=24)
    return np.where(selected, 0, 255).astype(np.uint8)


def grabcut_runner(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], color_strategy: str | None) -> Mask:
    del points, color_strategy
    return extract_foreground(image_bgr, list(rectangle))


def slimsam_runner(variant: str) -> Segmenter:
    def run(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], color_strategy: str | None) -> Mask:
        del color_strategy
        from handwrite_font_maker.segmentation import predict_slimsam

        return predict_slimsam(image_bgr, list(rectangle), variant=variant, points=[dict(point) for point in points])

    return run


def efficientsam_runner(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], color_strategy: str | None) -> Mask:
    del points, color_strategy
    from handwrite_font_maker.efficient_segmentation import predict_efficientsam_box

    return predict_efficientsam_box(image_bgr, list(rectangle))


def color_runner(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], color_strategy: str | None) -> Mask:
    if color_strategy != "water":
        raise ValueError("water-color is only configured for cases with color_strategy='water'")
    return water_color_mask(image_bgr, rectangle, points)


def default_methods() -> dict[str, Segmenter]:
    return {
        "grabcut": grabcut_runner,
        "efficientsam": efficientsam_runner,
        "slimsam": slimsam_runner("fp32"),
        "slimsam-int8": slimsam_runner("int8"),
        "water-color": color_runner,
    }


def _save_source_artifacts(case: NatureCase, source: ImageBgr, output_dir: Path) -> dict[str, str]:
    root = output_dir / "cases" / case.case_id
    root.mkdir(parents=True, exist_ok=True)
    bounded = _bounded_source(source)
    Image.fromarray(bounded[:, :, ::-1]).save(root / "source-bounded.png")
    x0, y0, x1, y1 = _roi_bounds(bounded.shape[:2], case.rectangle)
    Image.fromarray(bounded[y0:y1, x0:x1, ::-1]).save(root / "crop.png")
    overlay = Image.fromarray(bounded[:, :, ::-1]).convert("RGB")
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline=(255, 210, 0), width=3)
    for point in case.points:
        px = int(float(point["x"]) * bounded.shape[1])
        py = int(float(point["y"]) * bounded.shape[0])
        color = (0, 220, 0) if point["label"] == 1 else (230, 40, 40)
        draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill=color, outline=(255, 255, 255))
    overlay.save(root / "prompt-overlay.png")
    return {
        "source_bounded_png": f"cases/{case.case_id}/source-bounded.png",
        "crop_png": f"cases/{case.case_id}/crop.png",
        "prompt_overlay_png": f"cases/{case.case_id}/prompt-overlay.png",
    }


def _select_result(case: NatureCase, results: Mapping[str, dict[str, Any]]) -> tuple[str | None, str]:
    if case.review_label.endswith("not_font_default"):
        return None, "explicitly reported as a failure/stress case, not accepted for the font"
    for method in case.preferred_methods:
        row = results.get(method)
        if not row or row.get("status") != "ok":
            continue
        diagnostics = row["diagnostics"]
        warnings = set(diagnostics.get("warnings", []))
        if "blank-mask" in warnings or "high-coverage" in warnings:
            continue
        topology_row = diagnostics.get("topology", {})
        if int(topology_row.get("holes", 0)) > 300 or int(topology_row.get("components", 0)) > 300:
            continue
        coverage = float(diagnostics["coverage"])
        if 0.002 <= coverage <= 0.60:
            return method, "selected from explicit preferred_methods after sanity checks; requires visual review for product use"
    return None, "no preferred method produced a nonblank, non-solid mask"


def _prepare_font_mask(mask: Mask, path: Path, max_side: int = 420) -> None:
    binary = _remove_small_components(_foreground(mask), min_area=18)
    ys, xs = np.where(binary)
    if xs.size == 0:
        raise ValueError("cannot build a glyph from a blank mask")
    pad = 8
    y0 = max(0, int(ys.min()) - pad)
    y1 = min(binary.shape[0], int(ys.max()) + pad + 1)
    x0 = max(0, int(xs.min()) - pad)
    x1 = min(binary.shape[1], int(xs.max()) + pad + 1)
    cropped = np.where(binary[y0:y1, x0:x1], 0, 255).astype(np.uint8)
    image = Image.fromarray(cropped, mode="L")
    scale = min(1.0, max_side / max(image.size))
    if scale < 1.0:
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.NEAREST)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_mask_svg(mask_path: Path, svg_path: Path) -> None:
    gray = np.asarray(Image.open(mask_path).convert("L"))
    foreground = gray < 128
    contours, _hierarchy = cv2.findContours(foreground.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    commands: list[str] = []
    for contour in contours:
        points = contour.reshape(-1, 2)
        if len(points) < 3:
            continue
        first = points[0]
        parts = [f"M {int(first[0])} {int(first[1])}"]
        parts.extend(f"L {int(point[0])} {int(point[1])}" for point in points[1:])
        parts.append("Z")
        commands.append(" ".join(parts))
    width, height = Image.open(mask_path).size
    path_data = " ".join(commands)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">\n'
        f'  <rect width="100%" height="100%" fill="white"/>\n'
        f'  <path d="{path_data}" fill="black" fill-rule="evenodd"/>\n'
        f'</svg>\n'
    )
    svg_path.write_text(svg, encoding="utf-8")


def _save_selected_glyph_artifacts(case: NatureCase, selected_path: Path, output_dir: Path) -> dict[str, str]:
    review_dir = output_dir / "selected-glyphs"
    review_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{case.glyph}_{case.case_id}"
    png_path = review_dir / f"{stem}.png"
    svg_path = review_dir / f"{stem}.svg"
    Image.open(selected_path).save(png_path)
    _write_mask_svg(png_path, svg_path)
    return {
        "standalone_selected_png": f"selected-glyphs/{stem}.png",
        "standalone_selected_svg": f"selected-glyphs/{stem}.svg",
    }


def _render_font_proof(ttf_path: Path, glyphs: Sequence[str], output_path: Path) -> None:
    font = ImageFont.truetype(str(ttf_path), size=120)
    text = " ".join(glyphs) + "    " + "".join(glyphs)
    probe = Image.new("RGB", (1, 1), "white")
    probe_draw = ImageDraw.Draw(probe)
    bbox = probe_draw.textbbox((0, 0), text, font=font)
    width = max(1100, int(bbox[2] - bbox[0]) + 96)
    image = Image.new("RGB", (width, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.text((28, 20), "Nature glyph font proof (actual generated TTF)", fill=(30, 30, 30))
    draw.text((28, 105), text, font=font, fill=(0, 0, 0))
    image.save(output_path)


def _tile(image: Image.Image, size: tuple[int, int] = (150, 150)) -> Image.Image:
    canvas = Image.new("RGB", size, "white")
    image = image.convert("RGB")
    image.thumbnail((size[0], size[1] - 28))
    canvas.paste(image, ((size[0] - image.width) // 2, 4))
    return canvas


def write_contact_sheet(cases: Sequence[NatureCase], method_names: Sequence[str], output_dir: Path) -> str:
    tile_w, tile_h = 150, 176
    gap = 8
    cols = ["crop", *method_names, "selected"]
    sheet = Image.new("RGB", (gap + len(cols) * (tile_w + gap), gap + len(cases) * (tile_h + gap)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for row, case in enumerate(cases):
        y = gap + row * (tile_h + gap)
        root = output_dir / "cases" / case.case_id
        paths = [root / "crop.png", *[root / f"{name}.png" for name in method_names], root / "selected-font-mask.png"]
        for col, path in enumerate(paths):
            x = gap + col * (tile_w + gap)
            if path.exists():
                img = Image.open(path)
                sheet.paste(_tile(img, (tile_w, tile_h - 26)), (x, y))
            else:
                draw.rectangle((x, y, x + tile_w - 1, y + tile_h - 27), outline=(200, 200, 200))
                draw.line((x, y, x + tile_w - 1, y + tile_h - 27), fill=(180, 180, 180))
            label = case.case_id if col == 0 else cols[col]
            draw.text((x + 3, y + tile_h - 23), label[:24], fill=(20, 20, 20), font=font)
    path = output_dir / "contact-sheet.png"
    sheet.save(path)
    return "contact-sheet.png"


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {"status": "missing", "path": _portable(manifest_path), "note": "source image manifest was not present; filenames from the ignored source image directory were used"}
    try:
        return {"status": "loaded", "path": _portable(manifest_path), "data": json.loads(manifest_path.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"status": "error", "path": _portable(manifest_path), "error": f"{type(exc).__name__}: {exc}"}


def run_experiment(
    *,
    output_dir: Path = Path("output/nature-experiments"),
    image_dir: Path = Path("output/nature-source-images"),
    manifest_path: Path = Path("docs/research/nature-source-manifest.json"),
    cases: Sequence[NatureCase] = DEFAULT_CASES,
    methods: Mapping[str, Segmenter] | None = None,
    build_font: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(output_dir / "selected-glyphs", ignore_errors=True)
    methods = dict(methods or default_methods())
    report_cases: list[dict[str, Any]] = []
    selected_glyphs: list[dict[str, object]] = []
    selected_chars: list[str] = []

    for case in cases:
        _validate_rectangle(case.rectangle)
        _validate_points(case.points, case.rectangle)
        image_path = image_dir / case.filename
        case_root = output_dir / "cases" / case.case_id
        shutil.rmtree(case_root, ignore_errors=True)
        case_root.mkdir(parents=True, exist_ok=True)
        case_report: dict[str, Any] = {
            "case_id": case.case_id,
            "glyph": case.glyph,
            "glyph_idea": case.glyph_idea,
            "source_image": _portable(image_path),
            "rectangle": list(case.rectangle),
            "points": [dict(point) for point in case.points],
            "point_scope": "explicit normalized keep/exclude prompts; not inferred from a ground-truth mask",
            "review_label": case.review_label,
            "review_rationale": case.review_rationale,
            "preferred_methods": list(case.preferred_methods),
            "color_strategy": case.color_strategy,
            "baseline": case.baseline,
            "artifacts": {},
            "methods": {},
        }
        if not image_path.exists():
            case_report["status"] = "source-missing"
            case_report["error"] = "source image not found"
            report_cases.append(case_report)
            continue
        source = _load_bgr(image_path)
        method_source = _bounded_source(source)
        case_report["source_shape"] = [int(source.shape[0]), int(source.shape[1])]
        case_report["method_source_shape"] = [int(method_source.shape[0]), int(method_source.shape[1])]
        case_report["artifacts"].update(_save_source_artifacts(case, source, output_dir))

        result_rows: dict[str, dict[str, Any]] = {}
        for method_name, runner in methods.items():
            if method_name == "water-color" and case.color_strategy != "water":
                continue
            started = time.perf_counter()
            try:
                mask = _mask_binary(runner(method_source.copy(), case.rectangle, case.points, case.color_strategy))
                seconds = time.perf_counter() - started
                artifact = case_root / f"{method_name}.png"
                Image.fromarray(mask).save(artifact)
                row = {
                    "status": "ok",
                    "seconds": round(seconds, 6),
                    "diagnostics": mask_diagnostics(mask),
                    "artifact": f"cases/{case.case_id}/{method_name}.png",
                }
                result_rows[method_name] = row
                case_report["methods"][method_name] = row
            except Exception as exc:
                row = {"status": "error", "seconds": round(time.perf_counter() - started, 6), "error": f"{type(exc).__name__}: {exc}"}
                result_rows[method_name] = row
                case_report["methods"][method_name] = row

        selected_method, selected_reason = _select_result(case, result_rows)
        case_report["selected_method"] = selected_method
        case_report["selected_reason"] = selected_reason
        if selected_method:
            selected_src = case_root / f"{selected_method}.png"
            selected_mask = _mask_binary(np.asarray(Image.open(selected_src).convert("L")))
            selected_path = case_root / "selected-font-mask.png"
            _prepare_font_mask(selected_mask, selected_path)
            case_report["artifacts"]["selected_font_mask_png"] = f"cases/{case.case_id}/selected-font-mask.png"
            case_report["artifacts"].update(_save_selected_glyph_artifacts(case, selected_path, output_dir))
            case_report["font_preparation"] = "selected mask cropped to foreground bbox, tiny components under 18 px removed, resized to <=420 px; no shape generation/completion"
            if case.review_label != "reported_badcase_not_font_default" and len(selected_glyphs) < 5:
                selected_glyphs.append({"char": case.glyph, "image_path": selected_path, "baseline": case.baseline})
                selected_chars.append(case.glyph)
        report_cases.append(case_report)

    method_names = list(methods)
    contact_sheet = write_contact_sheet(cases, method_names, output_dir)
    font_report: dict[str, Any] = {"status": "skipped", "reason": "build_font=False"}
    if build_font:
        if not selected_glyphs:
            font_report = {"status": "not-built", "reason": "no selected usable masks"}
        else:
            try:
                from handwrite_font_maker.pipeline import build_font_from_masks

                font_dir = output_dir / "NatureGlyphs"
                shutil.rmtree(font_dir, ignore_errors=True)
                outputs = build_font_from_masks(
                    glyphs=selected_glyphs,
                    font_name="NatureGlyphs",
                    family_name="Nature Glyphs",
                    style_name="Regular",
                    output_dir=font_dir,
                )
                proof_path = output_dir / "font-proof.png"
                _render_font_proof(Path(str(outputs["ttf"])), selected_chars, proof_path)
                font_report = {
                    "status": "built",
                    "glyphs": selected_chars,
                    "outputs": {key: _portable(Path(str(value))) if isinstance(value, str) else value for key, value in outputs.items()},
                    "proof_png": "font-proof.png",
                    "note": "Actual font built from selected mask-v1 PNGs; masks are cropped/resized only, with no generated style completion.",
                }
            except Exception as exc:
                font_report = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    report = {
        "kind": "nature-font-experiment-v1",
        "scope": SCOPE_NOTE,
        "mask_convention": MASK_CONVENTION,
        "source_manifest": _load_manifest(manifest_path),
        "source_file_verification": verify_or_download_sources(manifest_path, image_dir, download=False),
        "image_dir": _portable(image_dir),
        "execution": "single-process sequential inference; no parallel model execution",
        "font_scope": "Ornament/symbol font mapped to manual characters; not an automatically generated readable A-Z alphabet.",
        "methods": list(methods),
        "cases": report_cases,
        "font": font_report,
        "artifacts": {"report_json": "nature-experiment-report.json", "contact_sheet_png": contact_sheet},
    }
    (output_dir / "nature-experiment-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report



def verify_or_download_sources(manifest_path: Path, image_dir: Path, *, download: bool = False) -> dict[str, Any]:
    """Verify manifest SHA-256 files, optionally downloading missing inputs.

    Download uses only URLs recorded by the source manifest and writes under the
    ignored source-image directory; it never edits the manifest itself.
    """

    if not manifest_path.exists():
        return {"status": "manifest-missing", "path": _portable(manifest_path)}
    import hashlib
    from urllib.request import urlretrieve

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    image_dir.mkdir(parents=True, exist_ok=True)
    for image in manifest.get("images", []):
        local = image.get("local_file", {})
        rel_path = Path(str(local.get("path", "")))
        path = image_dir / rel_path.name
        expected = local.get("sha256")
        if not path.exists() and download:
            url = image.get("downloadable_image_url")
            if url:
                urlretrieve(str(url), path)
        if not path.exists():
            rows.append({"id": image.get("id"), "status": "missing", "path": _portable(path)})
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append({"id": image.get("id"), "status": "ok" if digest == expected else "sha256-mismatch", "path": _portable(path), "sha256": digest})
    return {"status": "ok", "downloaded": bool(download), "files": rows}

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/nature-experiments"))
    parser.add_argument("--image-dir", type=Path, default=Path("output/nature-source-images"))
    parser.add_argument("--manifest", type=Path, default=Path("docs/research/nature-source-manifest.json"))
    parser.add_argument("--methods", default="grabcut,efficientsam,slimsam,water-color")
    parser.add_argument("--no-font", action="store_true", help="Run masks/contact sheet only; skip font build.")
    parser.add_argument("--download-sources", action="store_true", help="Download/verify ignored source images using the manifest before running.")
    args = parser.parse_args(argv)
    available = default_methods()
    selected = [name.strip() for name in args.methods.split(",") if name.strip()]
    unknown = [name for name in selected if name not in available]
    if unknown:
        parser.error(f"unknown methods: {', '.join(unknown)}")
    if args.download_sources:
        verify_or_download_sources(args.manifest, args.image_dir, download=True)
    report = run_experiment(
        output_dir=args.output_dir,
        image_dir=args.image_dir,
        manifest_path=args.manifest,
        methods={name: available[name] for name in selected},
        build_font=not args.no_font,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
