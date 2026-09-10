#!/usr/bin/env python3
"""Seeded river/water extraction experiment for satellite-source glyph probes.

This is a research harness only. It reuses attributed source photos from the
nature-source manifest, records explicit crops and keep/exclude seeds, compares
older broad water-color extraction with seeded alternatives and optional local
models, and only builds a font from masks that pass an explicit review rule.
No ground-truth masks or accuracy claims are created for these real photos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from experiment_nature_fonts import water_color_mask as frozen_water_color_mask  # noqa: E402
from handwrite_font_maker.foreground import MAX_CUTOUT_SIDE, extract_foreground  # noqa: E402

Rectangle = tuple[float, float, float, float]
PromptPoint = dict[str, float | int]
Mask = np.ndarray
ImageBgr = np.ndarray
RiverMethod = Callable[[ImageBgr, Rectangle, Sequence[PromptPoint], dict[str, Any]], Mask]

MASK_CONVENTION = "uint8 grayscale mask: 0/black = river/water foreground, 255/white = background"
SCOPE = "Real satellite image experiment with explicit user-style seeds; no ground-truth masks or accuracy claims."
DEFAULT_MANIFEST = Path("docs/research/nature-source-manifest.json")
DEFAULT_IMAGE_DIR = Path("output/nature-source-images")
DEFAULT_OUTPUT_DIR = Path("output/river-extraction")


@dataclass(frozen=True)
class RiverCase:
    case_id: str
    glyph: str
    source_id: str
    filename: str
    rectangle: Rectangle
    points: tuple[PromptPoint, ...]
    params: dict[str, Any]
    review_label: str
    review_rationale: str


def _norm_rect(crop_xywh: Sequence[int], width: int, height: int) -> Rectangle:
    x, y, w, h = crop_xywh
    return (round(x / width, 6), round(y / height, 6), round((x + w) / width, 6), round((y + h) / height, 6))


def _norm_points(points_xy: Sequence[Sequence[int]], width: int, height: int, label: int) -> tuple[PromptPoint, ...]:
    return tuple({"x": round(x / width, 6), "y": round(y / height, 6), "label": label} for x, y in points_xy)


DEFAULT_CASES: tuple[RiverCase, ...] = (
    RiverCase(
        case_id="meander_mississippi",
        glyph="S",
        source_id="satellite_meandering_mississippi",
        filename="satellite_meander__Meandering_Mississippi_5182095595.jpg",
        rectangle=_norm_rect((2700, 250, 3850, 6600), 7128, 7140),
        points=(
            *_norm_points(((5520, 1380), (4540, 2790), (4450, 4210), (3220, 5660), (5190, 6440)), 7128, 7140, 1),
            *_norm_points(((880, 1040), (1140, 4200), (6440, 700), (6100, 3500)), 7128, 7140, 0),
        ),
        params={"lab_tolerance": 32.0, "exclude_margin": -3.0, "close": 2, "open": 0, "min_area": 80, "keep_seed_radius": 8, "grabcut_iters": 5},
        review_label="visual_rejected_diagnostic",
        review_rationale="Initial run produced broad filled blobs rather than a narrow river trace; retained for comparison only, not font promotion.",
    ),
    RiverCase(
        case_id="meander_channel_trace_attempt",
        glyph="S",
        source_id="satellite_meandering_mississippi",
        filename="satellite_meander__Meandering_Mississippi_5182095595.jpg",
        rectangle=(0.407625, 0.146484, 0.919844, 0.950195),
        points=(
            {"x": 0.915934, "y": 0.175781, "label": 1},
            {"x": 0.705767, "y": 0.297852, "label": 1},
            {"x": 0.705767, "y": 0.37793, "label": 1},
            {"x": 0.587488, "y": 0.436523, "label": 1},
            {"x": 0.568915, "y": 0.532227, "label": 1},
            {"x": 0.604106, "y": 0.668945, "label": 1},
            {"x": 0.571848, "y": 0.758789, "label": 1},
            {"x": 0.567937, "y": 0.848633, "label": 1},
            {"x": 0.43695, "y": 0.920898, "label": 1},
            {"x": 0.779081, "y": 0.209961, "label": 0},
            {"x": 0.798631, "y": 0.356445, "label": 0},
            {"x": 0.652004, "y": 0.43457, "label": 0},
            {"x": 0.544477, "y": 0.576172, "label": 0},
            {"x": 0.686217, "y": 0.629883, "label": 0},
            {"x": 0.490714, "y": 0.751953, "label": 0},
            {"x": 0.837732, "y": 0.756836, "label": 0},
        ),
        params={"lab_tolerance": 18.0, "exclude_margin": -8.0, "close": 1, "open": 1, "min_area": 50, "keep_seed_radius": 4, "grabcut_iters": 5},
        review_label="candidate_needs_human_review",
        review_rationale="One bounded final attempt after visual inspection: narrower crop and seeds placed along visible mid-teal main channel, with excludes on adjacent dark vegetation/banks. Not accepted automatically.",
    ),
    RiverCase(
        case_id="braided_yarlung",
        glyph="B",
        source_id="satellite_braided_yarlung_zangbo",
        filename="satellite_braided__Braided_River_in_Tibet_Redraws_Its_Channels_154747.jpg",
        rectangle=_norm_rect((0, 135, 720, 155), 720, 400),
        points=(
            *_norm_points(((105, 216), (250, 218), (365, 210), (575, 212)), 720, 400, 1),
            *_norm_points(((312, 171), (42, 377), (645, 60), (690, 276)), 720, 400, 0),
        ),
        params={"lab_tolerance": 24.0, "exclude_margin": -2.0, "close": 1, "open": 1, "min_area": 10, "keep_seed_radius": 4, "grabcut_iters": 5},
        review_label="stress_case_expected_failure",
        review_rationale="Embedded label/scale and very low resolution make this a topology stress case; do not promote unless channels are visibly separated from banks/text.",
    ),
    RiverCase(
        case_id="ili_delta_oasis",
        glyph="D",
        source_id="satellite_ili_delta_oasis",
        filename="satellite_delta_oasis__A_Delta_Oasis_in_Southeastern_Kazakhstan.jpg",
        rectangle=_norm_rect((520, 240, 3100, 3350), 4198, 4198),
        points=(
            *_norm_points(((2200, 1180), (1710, 2450), (2860, 1690), (1120, 3070)), 4198, 4198, 1),
            *_norm_points(((360, 500), (3800, 3600), (4100, 1200), (700, 3900)), 4198, 4198, 0),
        ),
        params={"lab_tolerance": 30.0, "exclude_margin": -4.0, "close": 2, "open": 1, "min_area": 120, "keep_seed_radius": 7, "grabcut_iters": 5},
        review_label="reported_failure_not_font_default",
        review_rationale="Water/ice basin tends to produce broad blob masks; retain as diagnostic unless a coherent delta channel symbol appears.",
    ),
    RiverCase(
        case_id="mackenzie_plume",
        glyph="C",
        source_id="satellite_mackenzie_delta_sediment",
        filename="satellite_delta_sediment__Mackenzie_river_enters_Beaufort_sea.jpg",
        rectangle=_norm_rect((750, 900, 7600, 5150), 9000, 7500),
        points=(
            *_norm_points(((3380, 3650), (4750, 4210), (6200, 4930), (7100, 5290)), 9000, 7500, 1),
            *_norm_points(((8400, 900), (620, 7190), (7920, 6900), (2100, 1900)), 9000, 7500, 0),
        ),
        params={"lab_tolerance": 22.0, "exclude_margin": -2.0, "close": 3, "open": 1, "min_area": 160, "keep_seed_radius": 8, "grabcut_iters": 5},
        review_label="reported_failure_not_font_default",
        review_rationale="Sediment plume is semantically ambiguous and soft-edged; retain if useful visually but do not claim river-channel success.",
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable(path: Path, root: Path | None = None) -> str:
    bases = [root.resolve() if root else None, Path.cwd().resolve()]
    resolved = path.resolve()
    for base in bases:
        if base is None:
            continue
        try:
            return str(resolved.relative_to(base))
        except ValueError:
            pass
    return path.name


def _load_bgr(path: Path) -> ImageBgr:
    with Image.open(path) as image:
        oriented = ImageOps.exif_transpose(image)
        if oriented.mode in {"RGBA", "LA"} or (oriented.mode == "P" and "transparency" in oriented.info):
            rgba = oriented.convert("RGBA")
            bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            bg.alpha_composite(rgba)
            rgb = bg.convert("RGB")
        else:
            rgb = oriented.convert("RGB")
    return np.asarray(rgb, dtype=np.uint8)[:, :, ::-1].copy()


def _bounded_source(image_bgr: ImageBgr) -> ImageBgr:
    height, width = image_bgr.shape[:2]
    scale = min(1.0, MAX_CUTOUT_SIDE / max(height, width))
    if scale >= 1.0:
        return image_bgr.copy()
    return cv2.resize(image_bgr, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)


def _roi_bounds(shape: tuple[int, int], rectangle: Rectangle) -> tuple[int, int, int, int]:
    height, width = shape
    left, top, right, bottom = rectangle
    return (
        max(0, int(left * width)),
        max(0, int(top * height)),
        min(width, math.ceil(right * width)),
        min(height, math.ceil(bottom * height)),
    )


def _mask_binary(mask: Mask) -> Mask:
    arr = np.asarray(mask)
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_BGR2GRAY)
    if arr.ndim != 2:
        raise ValueError("mask must be a 2D grayscale image")
    return np.where(arr < 128, 0, 255).astype(np.uint8)


def _foreground(mask: Mask) -> np.ndarray:
    return _mask_binary(mask) < 128


def _remove_small_components(selected: np.ndarray, min_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(selected.astype(np.uint8), connectivity=8)
    keep = np.zeros_like(selected, dtype=bool)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area:
            keep |= labels == label
    return keep


def _seed_mask(shape: tuple[int, int], points: Sequence[PromptPoint], label: int, radius: int) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    for point in points:
        if point["label"] != label:
            continue
        x = min(width - 1, max(0, int(float(point["x"]) * width)))
        y = min(height - 1, max(0, int(float(point["y"]) * height)))
        cv2.circle(mask, (x, y), radius, 1, -1)
    return mask.astype(bool)


def _keep_components_touching_seeds(selected: np.ndarray, seed_mask: np.ndarray) -> np.ndarray:
    count, labels = cv2.connectedComponents(selected.astype(np.uint8), connectivity=8)
    keep_labels = {int(label) for label in np.unique(labels[seed_mask]) if int(label) != 0}
    if not keep_labels:
        return np.zeros_like(selected, dtype=bool)
    return np.isin(labels, list(keep_labels))


def _apply_roi(mask: np.ndarray, rectangle: Rectangle) -> np.ndarray:
    height, width = mask.shape
    x0, y0, x1, y1 = _roi_bounds((height, width), rectangle)
    roi = np.zeros_like(mask, dtype=bool)
    roi[y0:y1, x0:x1] = True
    return mask & roi


def _morph(selected: np.ndarray, *, close: int, open_: int) -> np.ndarray:
    out = selected.astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    if close > 0:
        out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, kernel, iterations=close)
    if open_ > 0:
        out = cv2.morphologyEx(out, cv2.MORPH_OPEN, kernel, iterations=open_)
    return out.astype(bool)


def seeded_color_mask(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], params: dict[str, Any]) -> Mask:
    source = _bounded_source(image_bgr)
    height, width = source.shape[:2]
    lab = cv2.cvtColor(source, cv2.COLOR_BGR2LAB).astype(np.float32)
    keep_samples: list[np.ndarray] = []
    exclude_samples: list[np.ndarray] = []
    for point in points:
        x = min(width - 1, max(0, int(float(point["x"]) * width)))
        y = min(height - 1, max(0, int(float(point["y"]) * height)))
        patch = lab[max(0, y - 3):min(height, y + 4), max(0, x - 3):min(width, x + 4)]
        if patch.size == 0:
            continue
        sample = np.median(patch.reshape(-1, 3), axis=0)
        if point["label"] == 1:
            keep_samples.append(sample)
        else:
            exclude_samples.append(sample)
    if not keep_samples:
        raise ValueError("seeded-color needs at least one keep seed")
    keep_dist = np.min(np.stack([np.linalg.norm(lab - sample, axis=2) for sample in keep_samples]), axis=0)
    if exclude_samples:
        exclude_dist = np.min(np.stack([np.linalg.norm(lab - sample, axis=2) for sample in exclude_samples]), axis=0)
    else:
        exclude_dist = np.full((height, width), 255.0, dtype=np.float32)
    tolerance = float(params.get("lab_tolerance", 28.0))
    margin = float(params.get("exclude_margin", 0.0))
    selected = (keep_dist <= tolerance) & (keep_dist <= exclude_dist + margin)
    selected = _apply_roi(selected, rectangle)
    selected = _morph(selected, close=int(params.get("close", 1)), open_=int(params.get("open", 0)))
    selected &= ~_seed_mask((height, width), points, 0, int(params.get("keep_seed_radius", 6)))
    selected = _keep_components_touching_seeds(selected, _seed_mask((height, width), points, 1, int(params.get("keep_seed_radius", 6))))
    selected = _remove_small_components(selected, int(params.get("min_area", 40)))
    return np.where(selected, 0, 255).astype(np.uint8)


def seeded_grabcut_mask(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], params: dict[str, Any]) -> Mask:
    source = _bounded_source(image_bgr)
    height, width = source.shape[:2]
    x0, y0, x1, y1 = _roi_bounds((height, width), rectangle)
    if x1 <= x0 + 2 or y1 <= y0 + 2:
        raise ValueError("rectangle too small for GrabCut")
    mask = np.full((height, width), cv2.GC_BGD, dtype=np.uint8)
    mask[y0:y1, x0:x1] = cv2.GC_PR_BGD
    keep = _seed_mask((height, width), points, 1, int(params.get("keep_seed_radius", 6)))
    exclude = _seed_mask((height, width), points, 0, int(params.get("keep_seed_radius", 6)))
    mask[keep] = cv2.GC_FGD
    mask[exclude] = cv2.GC_BGD
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(source, mask, None, bgd_model, fgd_model, int(params.get("grabcut_iters", 5)), cv2.GC_INIT_WITH_MASK)
    selected = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
    selected = _apply_roi(selected, rectangle)
    selected = _keep_components_touching_seeds(selected, keep)
    selected = _remove_small_components(selected, int(params.get("min_area", 40)))
    return np.where(selected, 0, 255).astype(np.uint8)


def frozen_water_color(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], params: dict[str, Any]) -> Mask:
    del params
    return frozen_water_color_mask(image_bgr, rectangle, points)


def grabcut_box(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], params: dict[str, Any]) -> Mask:
    del points, params
    return extract_foreground(_bounded_source(image_bgr), list(rectangle))


def efficientsam_box(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], params: dict[str, Any]) -> Mask:
    del points, params
    from handwrite_font_maker.efficient_segmentation import predict_efficientsam_box

    return predict_efficientsam_box(_bounded_source(image_bgr), list(rectangle))


def slimsam_points(image_bgr: ImageBgr, rectangle: Rectangle, points: Sequence[PromptPoint], params: dict[str, Any]) -> Mask:
    del params
    from handwrite_font_maker.segmentation import predict_slimsam

    return predict_slimsam(_bounded_source(image_bgr), list(rectangle), variant="fp32", points=[dict(p) for p in points])


def default_methods() -> dict[str, RiverMethod]:
    return {
        "water-color-frozen": frozen_water_color,
        "seeded-color": seeded_color_mask,
        "seeded-grabcut": seeded_grabcut_mask,
        "grabcut-box": grabcut_box,
        "efficientsam-box": efficientsam_box,
        "slimsam-points": slimsam_points,
    }


def topology(mask: Mask) -> dict[str, int]:
    fg = _foreground(mask).astype(np.uint8)
    count, _ = cv2.connectedComponents(fg, connectivity=8)
    contours, hierarchy = cv2.findContours(fg, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    holes = 0 if hierarchy is None else sum(int(item[3] >= 0) for item in hierarchy[0])
    return {"components": int(count - 1), "holes": int(holes)}


def diagnostics(mask: Mask, points: Sequence[PromptPoint]) -> dict[str, Any]:
    fg = _foreground(mask)
    height, width = fg.shape
    foreground = int(fg.sum())
    coverage = foreground / float(fg.size) if fg.size else 0.0
    if foreground:
        ys, xs = np.where(fg)
        bbox = [round(xs.min() / width, 6), round(ys.min() / height, 6), round((xs.max() + 1) / width, 6), round((ys.max() + 1) / height, 6)]
    else:
        bbox = None
    keep_hits = 0
    for point in points:
        if point["label"] != 1:
            continue
        x = min(width - 1, max(0, int(float(point["x"]) * width)))
        y = min(height - 1, max(0, int(float(point["y"]) * height)))
        keep_hits += int(bool(fg[y, x]))
    topo = topology(mask)
    warnings: list[str] = []
    if foreground == 0:
        warnings.append("blank-mask")
    if coverage > 0.55:
        warnings.append("high-coverage-blob")
    if coverage < 0.001:
        warnings.append("very-low-coverage")
    if keep_hits == 0:
        warnings.append("misses-keep-seeds")
    if topo["components"] > 120:
        warnings.append("speckled-components")
    return {
        "shape": [height, width],
        "foreground_pixels": foreground,
        "coverage": round(coverage, 6),
        "bbox": bbox,
        "topology": topo,
        "keep_seed_hits": keep_hits,
        "keep_seed_total": sum(1 for p in points if p["label"] == 1),
        "warnings": warnings,
    }


def _validate_case(case: RiverCase) -> None:
    left, top, right, bottom = case.rectangle
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError(f"{case.case_id} rectangle must be normalized")
    if not any(point["label"] == 1 for point in case.points):
        raise ValueError(f"{case.case_id} requires keep seeds")
    for point in case.points:
        if set(point) != {"x", "y", "label"} or point["label"] not in (0, 1):
            raise ValueError(f"{case.case_id} has malformed point")
        if not (0 <= float(point["x"]) <= 1 and 0 <= float(point["y"]) <= 1):
            raise ValueError(f"{case.case_id} point outside normalized image")


def _load_source_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {"status": "missing", "path": _portable(manifest_path)}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id = {image["id"]: image for image in data.get("images", [])}
    return {"status": "loaded", "path": _portable(manifest_path), "images_by_id": by_id}


def verify_sources(cases: Sequence[RiverCase], manifest_path: Path, image_dir: Path) -> dict[str, Any]:
    manifest = _load_source_manifest(manifest_path)
    rows: list[dict[str, Any]] = []
    by_id = manifest.get("images_by_id", {}) if manifest.get("status") == "loaded" else {}
    for case in cases:
        image_info = by_id.get(case.source_id)
        path = image_dir / case.filename
        row = {"case_id": case.case_id, "source_id": case.source_id, "path": _portable(path)}
        if manifest.get("status") != "loaded":
            row["status"] = "manifest-unverified"
        elif not isinstance(image_info, dict):
            row["status"] = "source-missing-from-manifest"
        else:
            local = image_info.get("local_file", {}) if isinstance(image_info.get("local_file"), dict) else {}
            expected = local.get("sha256")
            license_info = image_info.get("license")
            origin = image_info.get("origin_page")
            if not isinstance(expected, str) or len(expected) != 64:
                row["status"] = "missing-source-sha256"
            elif not isinstance(license_info, dict) or not license_info.get("short_name"):
                row["status"] = "missing-source-license"
            elif not isinstance(origin, str) or not origin:
                row["status"] = "missing-source-origin"
            elif not path.exists():
                row["status"] = "missing-local-file"
                row["expected_sha256"] = expected
            else:
                actual = _sha256(path)
                if actual != expected:
                    row.update({"status": "sha256-mismatch", "expected_sha256": expected, "actual_sha256": actual})
                else:
                    row.update({
                        "status": "ok",
                        "sha256": expected,
                        "license": license_info,
                        "origin_page": origin,
                        "credit_line": image_info.get("credit_line"),
                    })
        rows.append(row)
    verified_case_ids = [row["case_id"] for row in rows if row.get("status") == "ok"]
    return {"manifest": {k: v for k, v in manifest.items() if k != "images_by_id"}, "sources": rows, "verified_case_ids": verified_case_ids}

def _save_fixtures(case: RiverCase, source: ImageBgr, output_dir: Path) -> dict[str, str]:
    case_root = output_dir / "cases" / case.case_id
    case_root.mkdir(parents=True, exist_ok=True)
    bounded = _bounded_source(source)
    Image.fromarray(bounded[:, :, ::-1]).save(case_root / "source-bounded.png")
    x0, y0, x1, y1 = _roi_bounds(bounded.shape[:2], case.rectangle)
    Image.fromarray(bounded[y0:y1, x0:x1, ::-1]).save(case_root / "crop.png")
    overlay = Image.fromarray(bounded[:, :, ::-1]).convert("RGB")
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline=(255, 210, 0), width=3)
    for point in case.points:
        x = int(float(point["x"]) * bounded.shape[1])
        y = int(float(point["y"]) * bounded.shape[0])
        color = (0, 220, 0) if point["label"] == 1 else (230, 35, 35)
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color, outline=(255, 255, 255))
    overlay.save(case_root / "prompt-overlay.png")
    return {"source_bounded_png": f"cases/{case.case_id}/source-bounded.png", "crop_png": f"cases/{case.case_id}/crop.png", "prompt_overlay_png": f"cases/{case.case_id}/prompt-overlay.png"}


def _write_svg(mask_path: Path, svg_path: Path) -> None:
    arr = np.asarray(Image.open(mask_path).convert("L"))
    contours, _ = cv2.findContours((arr < 128).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    commands: list[str] = []
    for contour in contours:
        pts = contour.reshape(-1, 2)
        if len(pts) < 3:
            continue
        commands.append("M " + " L ".join(f"{int(x)} {int(y)}" for x, y in pts) + " Z")
    width, height = Image.open(mask_path).size
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">\n'
        f'  <rect width="100%" height="100%" fill="white"/>\n'
        f'  <path d="{" ".join(commands)}" fill="black" fill-rule="evenodd"/>\n'
        f'</svg>\n',
        encoding="utf-8",
    )


def _prepare_font_mask(mask: Mask, path: Path, max_side: int = 420) -> None:
    binary = _remove_small_components(_foreground(mask), min_area=25)
    ys, xs = np.where(binary)
    if xs.size == 0:
        raise ValueError("cannot build font mask from blank river mask")
    pad = 6
    y0, y1 = max(0, ys.min() - pad), min(binary.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(binary.shape[1], xs.max() + pad + 1)
    image = Image.fromarray(np.where(binary[y0:y1, x0:x1], 0, 255).astype(np.uint8))
    scale = min(1.0, max_side / max(image.size))
    if scale < 1.0:
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.NEAREST)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _select(case: RiverCase, rows: Mapping[str, dict[str, Any]]) -> tuple[str | None, str]:
    """Return a font-selected method only after explicit visual acceptance.

    Diagnostics are useful for triage, but numeric gates are not human review.
    The current default cases intentionally have no ``accepted_for_font_visual_reviewed``
    label, so river outputs remain research artifacts until the leader/user accepts
    a specific visible mask.
    """

    if case.review_label != "accepted_for_font_visual_reviewed":
        return None, "not promoted: requires explicit human visual acceptance; numeric diagnostics alone are insufficient"
    for method_name in ("seeded-grabcut", "seeded-color", "slimsam-points", "efficientsam-box", "water-color-frozen"):
        row = rows.get(method_name)
        if row is None or row.get("status") != "ok":
            continue
        diag = row["diagnostics"]
        warnings = set(diag["warnings"])
        coverage = float(diag["coverage"])
        keep_hits = int(diag["keep_seed_hits"])
        if warnings & {"blank-mask", "high-coverage-blob", "misses-keep-seeds", "speckled-components"}:
            continue
        if 0.004 <= coverage <= 0.32 and keep_hits >= max(1, int(diag["keep_seed_total"]) // 2):
            return method_name, "explicitly visually accepted and passed deterministic sanity checks"
    return None, "explicit visual acceptance label present, but no method passed sanity gates"

def _render_font_proof(ttf_path: Path, glyphs: Sequence[str], output_path: Path) -> None:
    font = ImageFont.truetype(str(ttf_path), size=126)
    text = " ".join(glyphs) + "    " + "".join(glyphs)
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.text((28, 24), "River glyph TTF proof (actual generated font)", fill=(25, 25, 25))
    draw.text((36, 105), text, font=font, fill=(0, 0, 0))
    image.save(output_path)


def _tile(path: Path, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, "white")
    if path.exists():
        img = Image.open(path).convert("RGB")
        img.thumbnail((size[0], size[1] - 24))
        canvas.paste(img, ((size[0] - img.width) // 2, 2))
    else:
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, size[0] - 1, size[1] - 25), outline=(190, 190, 190))
        draw.line((0, 0, size[0] - 1, size[1] - 25), fill=(180, 180, 180))
    return canvas


def write_contact_sheet(cases: Sequence[RiverCase], methods: Sequence[str], output_dir: Path) -> str:
    cols = ["crop", *methods, "selected"]
    tile_w, tile_h, gap = 145, 172, 8
    sheet = Image.new("RGB", (gap + len(cols) * (tile_w + gap), gap + len(cases) * (tile_h + gap)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for row, case in enumerate(cases):
        y = gap + row * (tile_h + gap)
        root = output_dir / "cases" / case.case_id
        paths = [root / "crop.png", *[root / f"{m}.png" for m in methods], root / "selected-font-mask.png"]
        for col, path in enumerate(paths):
            x = gap + col * (tile_w + gap)
            sheet.paste(_tile(path, (tile_w, tile_h - 24)), (x, y))
            label = case.case_id if col == 0 else cols[col]
            draw.text((x + 2, y + tile_h - 21), label[:25], fill=(20, 20, 20), font=font)
    out = output_dir / "river-contact-sheet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return "river-contact-sheet.png"


def run_experiment(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    image_dir: Path = DEFAULT_IMAGE_DIR,
    manifest_path: Path = DEFAULT_MANIFEST,
    cases: Sequence[RiverCase] = DEFAULT_CASES,
    methods: Mapping[str, RiverMethod] | None = None,
    build_font: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    methods = dict(methods or default_methods())
    source_verification = verify_sources(tuple(cases), manifest_path, image_dir)
    verified_case_ids = set(source_verification.get("verified_case_ids", []))
    report_cases: list[dict[str, Any]] = []
    selected_glyphs: list[dict[str, Any]] = []
    selected_chars: list[str] = []

    for case in cases:
        _validate_case(case)
        case_root = output_dir / "cases" / case.case_id
        shutil.rmtree(case_root, ignore_errors=True)
        case_root.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / case.filename
        case_report: dict[str, Any] = {
            "case_id": case.case_id,
            "glyph": case.glyph,
            "source_id": case.source_id,
            "source_image": _portable(image_path),
            "rectangle": list(case.rectangle),
            "points": [dict(p) for p in case.points],
            "params": case.params,
            "review_label": case.review_label,
            "review_rationale": case.review_rationale,
            "scope": "qualitative real-image river extraction; no ground truth mask",
            "artifacts": {},
            "methods": {},
        }
        if case.case_id not in verified_case_ids:
            verification_row = next((row for row in source_verification.get("sources", []) if row.get("case_id") == case.case_id), {})
            case_report.update({"status": "source-unverified", "error": verification_row.get("status", "source verification failed before scoring")})
            report_cases.append(case_report)
            continue
        source = _load_bgr(image_path)
        bounded = _bounded_source(source)
        case_report["source_shape"] = [int(source.shape[0]), int(source.shape[1])]
        case_report["method_source_shape"] = [int(bounded.shape[0]), int(bounded.shape[1])]
        case_report["artifacts"].update(_save_fixtures(case, source, output_dir))
        method_rows: dict[str, dict[str, Any]] = {}
        for method_name, runner in methods.items():
            started = time.perf_counter()
            try:
                mask = _mask_binary(runner(source.copy(), case.rectangle, case.points, dict(case.params)))
                seconds = time.perf_counter() - started
                path = case_root / f"{method_name}.png"
                Image.fromarray(mask).save(path)
                row = {"status": "ok", "seconds": round(seconds, 6), "diagnostics": diagnostics(mask, case.points), "artifact": f"cases/{case.case_id}/{method_name}.png"}
            except Exception as exc:
                row = {"status": "error", "seconds": round(time.perf_counter() - started, 6), "error": f"{type(exc).__name__}: {exc}"}
            method_rows[method_name] = row
            case_report["methods"][method_name] = row
        selected_method, selected_reason = _select(case, method_rows)
        case_report["selected_method"] = selected_method
        case_report["selected_reason"] = selected_reason
        if selected_method:
            selected_src = case_root / f"{selected_method}.png"
            selected_mask = _mask_binary(np.asarray(Image.open(selected_src).convert("L")))
            selected_path = case_root / "selected-font-mask.png"
            _prepare_font_mask(selected_mask, selected_path)
            svg_path = case_root / "selected-font-mask.svg"
            _write_svg(selected_path, svg_path)
            case_report["artifacts"].update({"selected_font_mask_png": f"cases/{case.case_id}/selected-font-mask.png", "selected_font_mask_svg": f"cases/{case.case_id}/selected-font-mask.svg"})
            selected_glyphs.append({"char": case.glyph, "image_path": selected_path, "baseline": 0.72})
            selected_chars.append(case.glyph)
        report_cases.append(case_report)

    font_report: dict[str, Any] = {"status": "skipped", "reason": "build_font=False"}
    if build_font:
        if not selected_glyphs:
            rejected = output_dir / "RiverGlyphs" / "RiverGlyphs.ttf"
            font_report = {"status": "not-built", "reason": "no explicitly visually accepted river masks"}
            if rejected.exists():
                font_report["rejected_diagnostic_ttf"] = _portable(rejected, output_dir)
                font_report["rejected_note"] = "Retained from an earlier run only as a rejected diagnostic artifact; not a successful river font."
        else:
            try:
                from handwrite_font_maker.pipeline import build_font_from_masks

                font_dir = output_dir / "RiverGlyphs"
                shutil.rmtree(font_dir, ignore_errors=True)
                outputs = build_font_from_masks(
                    glyphs=selected_glyphs,
                    font_name="RiverGlyphs",
                    family_name="River Glyphs",
                    style_name="Regular",
                    output_dir=font_dir,
                )
                proof = output_dir / "river-font-proof.png"
                _render_font_proof(Path(str(outputs["ttf"])), selected_chars, proof)
                font_report = {
                    "status": "built",
                    "glyphs": selected_chars,
                    "outputs": {k: _portable(Path(str(v)), output_dir) if isinstance(v, str) else v for k, v in outputs.items()},
                    "proof_png": "river-font-proof.png",
                    "note": "Actual TTF built only from selected masks; no style completion or automatic alphabet generation.",
                }
            except Exception as exc:
                font_report = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    contact_sheet = write_contact_sheet(tuple(cases), tuple(methods), output_dir)
    report = {
        "kind": "river-extraction-experiment-v1",
        "scope": SCOPE,
        "mask_convention": MASK_CONVENTION,
        "source_verification": source_verification,
        "execution": "single-process sequential; no production pipeline changes",
        "methods": {
            "water-color-frozen": "Earlier broad HSV/LAB water-color helper from nature experiment.",
            "seeded-color": "Explicit keep/exclude LAB color-distance mask, ROI-limited, then keep only components touching keep seeds.",
            "seeded-grabcut": "Benchmark-only seeded OpenCV GrabCut mask initialized with keep/exclude seeds and ROI; uses cv2.GC_FGD/cv2.GC_BGD seed labels.",
            "grabcut-box": "Existing rectangle-only GrabCut baseline.",
            "efficientsam-box": "Optional local EfficientSAM box prompt.",
            "slimsam-points": "Optional local SlimSAM with explicit keep/exclude seeds.",
        },
        "cases": report_cases,
        "font": font_report,
        "artifacts": {"report_json": "river-experiment-report.json", "contact_sheet_png": contact_sheet},
    }
    (output_dir / "river-experiment-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--methods", default="water-color-frozen,seeded-color,seeded-grabcut,grabcut-box,efficientsam-box,slimsam-points")
    parser.add_argument("--no-font", action="store_true")
    args = parser.parse_args(argv)
    available = default_methods()
    names = [name.strip() for name in args.methods.split(",") if name.strip()]
    unknown = [name for name in names if name not in available]
    if unknown:
        parser.error(f"unknown methods: {', '.join(unknown)}")
    report = run_experiment(
        output_dir=args.output_dir,
        image_dir=args.image_dir,
        manifest_path=args.manifest,
        methods={name: available[name] for name in names},
        build_font=not args.no_font,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
