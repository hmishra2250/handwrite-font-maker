#!/usr/bin/env python3
"""Deterministic glyph segmentation benchmark harness.

This benchmark is intentionally local and synthetic.  It creates source images and
hand-authored reference masks for glyph-like edge cases, then runs segmentation
callables against each fixture.  The default runners include the app's current GrabCut baseline plus lazy
SlimSAM fp32/int8 adapters when the optional local model runtime is installed;
other ML implementations can be connected through the same callable contract
without changing the metrics or fixture corpus.

Mask convention: uint8 grayscale, black/0 = foreground and white/255 = background.
Rectangle convention: normalized left/top/right/bottom in EXIF-oriented source
coordinates, matching handwrite_font_maker.foreground.extract_foreground().
"""
from __future__ import annotations

import argparse
import json
import time
import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from handwrite_font_maker.foreground import extract_foreground

MaskArray = np.ndarray
ImageArray = np.ndarray
Rectangle = tuple[float, float, float, float]
PromptPoint = dict[str, float | int]
Segmenter = Callable[..., MaskArray]

MASK_CONVENTION = "uint8 grayscale mask: 0/black = foreground, 255/white = background"
RECTANGLE_CONVENTION = "normalized left, top, right, bottom in source coordinates"
SEGMENTER_CONTRACT = (
    "Callable accepting image_bgr (np.ndarray uint8 HxWx3), normalized rectangle "
    "(left, top, right, bottom), and optionally prompt_points "
    "([{x: normalized float, y: normalized float, label: 1 keep | 0 exclude}]); "
    "returns np.ndarray uint8 HxW mask with black foreground/white background"
)


@dataclass(frozen=True)
class SegmentationFixture:
    """One benchmark source image plus its intended binary reference mask."""

    name: str
    description: str
    image_bgr: ImageArray
    reference_mask: MaskArray
    rectangle: Rectangle
    source_notes: str
    prompt_points: tuple[PromptPoint, ...]


def _as_bgr(image: Image.Image) -> ImageArray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8)[:, :, ::-1].copy()


def _binary_mask(mask: MaskArray) -> MaskArray:
    arr = np.asarray(mask)
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_BGR2GRAY)
    if arr.ndim != 2:
        raise ValueError("Segmenter must return a 2D grayscale mask or 3-channel image.")
    return np.where(arr < 128, 0, 255).astype(np.uint8)


def _foreground(mask: MaskArray) -> np.ndarray:
    return _binary_mask(mask) < 128


def _rectangle_for(mask: MaskArray, padding: int = 14) -> Rectangle:
    ys, xs = np.where(_foreground(mask))
    if xs.size == 0:
        raise ValueError("Reference mask has no foreground pixels.")
    height, width = mask.shape[:2]
    left = max(0, int(xs.min()) - padding) / width
    top = max(0, int(ys.min()) - padding) / height
    right = min(width, int(xs.max()) + padding + 1) / width
    bottom = min(height, int(ys.max()) + padding + 1) / height
    return (round(left, 6), round(top, 6), round(right, 6), round(bottom, 6))



def _reference_prompt_points(mask: MaskArray, rectangle: Rectangle) -> tuple[PromptPoint, ...]:
    """Derive deterministic oracle clicks from a reference mask for point-prompted models.

    These points are intentionally reference-assisted so fp32/int8 learned-model
    variants receive identical prompts. They measure model response to a controlled
    prompt budget, not unassisted automatic segmentation.
    """

    binary = _foreground(mask).astype(np.uint8)
    height, width = binary.shape
    points: list[PromptPoint] = []
    count, labels = cv2.connectedComponents(binary, connectivity=8)
    for label in range(1, count):
        component = (labels == label).astype(np.uint8)
        if int(component.sum()) < 4:
            continue
        distance = cv2.distanceTransform(component, cv2.DIST_L2, 3)
        y, x = np.unravel_index(int(np.argmax(distance)), distance.shape)
        points.append({"x": round(float(x) / width, 6), "y": round(float(y) / height, 6), "label": 1})

    # Add deterministic negative prompts for enclosed counters/holes.
    background = (binary == 0).astype(np.uint8)
    bg_count, bg_labels = cv2.connectedComponents(background, connectivity=8)
    for label in range(1, bg_count):
        ys, xs = np.where(bg_labels == label)
        if xs.size == 0:
            continue
        touches_border = xs.min() == 0 or ys.min() == 0 or xs.max() == width - 1 or ys.max() == height - 1
        if touches_border:
            continue
        component = (bg_labels == label).astype(np.uint8)
        distance = cv2.distanceTransform(component, cv2.DIST_L2, 3)
        y, x = np.unravel_index(int(np.argmax(distance)), distance.shape)
        points.append({"x": round(float(x) / width, 6), "y": round(float(y) / height, 6), "label": 0})

    left, top, right, bottom = rectangle
    positives = [p for p in points if p["label"] == 1 and left <= float(p["x"]) <= right and top <= float(p["y"]) <= bottom]
    if not positives:
        ys, xs = np.where(binary > 0)
        if xs.size == 0:
            raise ValueError("Reference mask has no foreground pixels.")
        idx = int(len(xs) // 2)
        points.insert(0, {"x": round(float(xs[idx]) / width, 6), "y": round(float(ys[idx]) / height, 6), "label": 1})
    return tuple(points[:16])

def _make_background(size: tuple[int, int], base: tuple[int, int, int], *, clutter: bool = False) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(image)
    if clutter:
        for y in range(0, height, 13):
            shade = tuple(max(0, min(255, channel + ((y // 13) % 5 - 2) * 5)) for channel in base)
            draw.line((0, y, width, y + 9), fill=shade, width=1)
        for x in range(7, width, 29):
            draw.line((x, 0, min(width, x + 42), height), fill=(205, 203, 196), width=1)
        draw.rectangle((18, 28, 78, 48), fill=(224, 222, 216))
        draw.ellipse((125, 118, 175, 154), outline=(198, 196, 190), width=2)
    return image


def _apply_mask_color(
    background: Image.Image,
    mask: Image.Image,
    color: tuple[int, int, int],
    *,
    interior_fill_mask: Image.Image | None = None,
    interior_color: tuple[int, int, int] | None = None,
) -> Image.Image:
    image = background.copy()
    if interior_fill_mask is not None and interior_color is not None:
        fill = Image.new("RGB", image.size, interior_color)
        image.paste(fill, mask=interior_fill_mask.point(lambda value: 255 if value < 128 else 0))
    foreground = Image.new("RGB", image.size, color)
    image.paste(foreground, mask=mask.point(lambda value: 255 if value < 128 else 0))
    return image


def _topology(mask: MaskArray) -> dict[str, int]:
    fg = _foreground(mask).astype(np.uint8)
    components, _labels = cv2.connectedComponents(fg, connectivity=8)
    contours, hierarchy = cv2.findContours(fg, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    holes = 0 if hierarchy is None else sum(int(item[3] >= 0) for item in hierarchy[0])
    return {"components": int(components - 1), "holes": int(holes)}


def synthetic_fixtures(size: int = 192) -> list[SegmentationFixture]:
    """Return the deterministic synthetic fixture corpus.

    These are reference-labeled engineering probes, not measurements on real user
    uploads.  Each mask uses the product convention: black foreground on white
    background, and disconnected pieces/counters are intentional.
    """

    fixtures: list[SegmentationFixture] = []
    dims = (size, size)

    # 1. Hairline writing: narrow strokes should not vanish under preprocessing.
    mask = Image.new("L", dims, 255)
    draw = ImageDraw.Draw(mask)
    draw.line([(45, 158), (92, 28), (147, 158)], fill=0, width=3)
    draw.line([(67, 104), (124, 104)], fill=0, width=3)
    draw.arc((72, 125, 132, 185), start=200, end=340, fill=0, width=2)
    bg = _make_background(dims, (239, 237, 228))
    source = _apply_mask_color(bg, mask, (28, 34, 38))
    fixtures.append(SegmentationFixture(
        name="thin_strokes",
        description="3px and 2px glyph-like strokes on plain paper.",
        image_bgr=_as_bgr(source),
        reference_mask=np.asarray(mask, dtype=np.uint8),
        rectangle=_rectangle_for(np.asarray(mask, dtype=np.uint8), padding=18),
        source_notes="Synthetic ink strokes; exercises fine-stroke recall.",
        prompt_points=_reference_prompt_points(np.asarray(mask, dtype=np.uint8), _rectangle_for(np.asarray(mask, dtype=np.uint8), padding=18)),
    ))

    # 2. A counter/counter-form: holes must remain background, not be filled.
    mask = Image.new("L", dims, 255)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((42, 27, 150, 165), fill=0)
    draw.ellipse((72, 61, 120, 130), fill=255)
    bg = _make_background(dims, (226, 232, 224))
    source = _apply_mask_color(bg, mask, (46, 112, 42))
    fixtures.append(SegmentationFixture(
        name="ring_hole",
        description="Filled ring with a true white counter/hole.",
        image_bgr=_as_bgr(source),
        reference_mask=np.asarray(mask, dtype=np.uint8),
        rectangle=_rectangle_for(np.asarray(mask, dtype=np.uint8), padding=17),
        source_notes="Synthetic object silhouette; hole preservation matters for O-like glyphs.",
        prompt_points=_reference_prompt_points(np.asarray(mask, dtype=np.uint8), _rectangle_for(np.asarray(mask, dtype=np.uint8), padding=17)),
    ))

    # 3. Detached dot/leaves: largest-component-only cleanup would be wrong.
    mask = Image.new("L", dims, 255)
    draw = ImageDraw.Draw(mask)
    draw.line((96, 70, 96, 162), fill=0, width=9)
    draw.ellipse((61, 102, 97, 136), fill=0)
    draw.ellipse((97, 78, 142, 112), fill=0)
    draw.ellipse((83, 27, 109, 53), fill=0)
    bg = _make_background(dims, (231, 229, 218))
    source = _apply_mask_color(bg, mask, (38, 92, 32))
    fixtures.append(SegmentationFixture(
        name="detached_dot_leaves",
        description="Multi-component glyph with an i-dot-like detached part.",
        image_bgr=_as_bgr(source),
        reference_mask=np.asarray(mask, dtype=np.uint8),
        rectangle=_rectangle_for(np.asarray(mask, dtype=np.uint8), padding=19),
        source_notes="Synthetic leaves/dot; no largest-component filtering is allowed.",
        prompt_points=_reference_prompt_points(np.asarray(mask, dtype=np.uint8), _rectangle_for(np.asarray(mask, dtype=np.uint8), padding=19)),
    ))

    # 4. Low contrast plus clutter: color models can confuse background marks.
    mask = Image.new("L", dims, 255)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((48, 42, 139, 132), fill=0)
    draw.ellipse((75, 68, 113, 104), fill=255)
    draw.line((132, 90, 132, 166, 84, 172), fill=0, width=6)
    bg = _make_background(dims, (214, 213, 205), clutter=True)
    source = _apply_mask_color(bg, mask, (163, 162, 154))
    fixtures.append(SegmentationFixture(
        name="low_contrast_clutter",
        description="Low-contrast glyph/object over deterministic background clutter.",
        image_bgr=_as_bgr(source),
        reference_mask=np.asarray(mask, dtype=np.uint8),
        rectangle=_rectangle_for(np.asarray(mask, dtype=np.uint8), padding=16),
        source_notes="Synthetic hard case; exposes sensitivity to similarly colored backgrounds.",
        prompt_points=_reference_prompt_points(np.asarray(mask, dtype=np.uint8), _rectangle_for(np.asarray(mask, dtype=np.uint8), padding=16)),
    ))

    # 5. Source detail: target includes fine vein strokes, not just a silhouette.
    silhouette = Image.new("L", dims, 255)
    draw = ImageDraw.Draw(silhouette)
    draw.ellipse((35, 35, 157, 148), fill=0)
    draw.polygon([(95, 145), (108, 180), (101, 181), (88, 148)], fill=0)
    detail = Image.new("L", dims, 255)
    draw = ImageDraw.Draw(detail)
    draw.arc((35, 35, 157, 148), start=15, end=345, fill=0, width=2)
    draw.line((96, 45, 96, 146), fill=0, width=2)
    for y in range(62, 135, 18):
        draw.line((96, y, 56, y + 14), fill=0, width=2)
        draw.line((96, y + 4, 138, y - 8), fill=0, width=2)
    draw.line((95, 145, 104, 179), fill=0, width=2)
    draw.ellipse((148, 34, 155, 41), fill=0)
    bg = _make_background(dims, (237, 235, 222))
    source = _apply_mask_color(
        bg,
        detail,
        (34, 68, 30),
        interior_fill_mask=silhouette,
        interior_color=(174, 193, 127),
    )
    fixtures.append(SegmentationFixture(
        name="source_detail_veins",
        description="Fine source-detail strokes inside a pale object; target is detail, not only area.",
        image_bgr=_as_bgr(source),
        reference_mask=np.asarray(detail, dtype=np.uint8),
        rectangle=_rectangle_for(np.asarray(silhouette, dtype=np.uint8), padding=14),
        source_notes="Synthetic detail mask; a silhouette-only method should score poorly here.",
        prompt_points=_reference_prompt_points(np.asarray(detail, dtype=np.uint8), _rectangle_for(np.asarray(silhouette, dtype=np.uint8), padding=14)),
    ))

    return fixtures


def grabcut_segmenter(image_bgr: ImageArray, rectangle: Rectangle, prompt_points: Sequence[PromptPoint] | None = None) -> MaskArray:
    """Adapter for the current app baseline; performs no post component filtering."""

    del prompt_points
    return extract_foreground(image_bgr, list(rectangle))


def slimsam_segmenter(variant: str) -> Segmenter:
    """Return a lazy SlimSAM adapter for genuine local learned-weight comparison."""

    def runner(image_bgr: ImageArray, rectangle: Rectangle, prompt_points: Sequence[PromptPoint] | None = None) -> MaskArray:
        from handwrite_font_maker.segmentation import predict_slimsam

        if not prompt_points:
            raise ValueError("SlimSAM benchmark runner requires deterministic keep/exclude prompt points.")
        return predict_slimsam(image_bgr, list(rectangle), variant=variant, points=[dict(point) for point in prompt_points])

    return runner


def default_segmenters() -> dict[str, Segmenter]:
    return {
        "grabcut": grabcut_segmenter,
        "slimsam": slimsam_segmenter("fp32"),
        "slimsam-int8": slimsam_segmenter("int8"),
    }


def _call_segmenter(runner: Segmenter, fixture: SegmentationFixture) -> MaskArray:
    try:
        signature = inspect.signature(runner)
    except (TypeError, ValueError):
        return runner(fixture.image_bgr.copy(), fixture.rectangle, fixture.prompt_points)
    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values()):
        return runner(fixture.image_bgr.copy(), fixture.rectangle, fixture.prompt_points)
    if "prompt_points" in signature.parameters or len(signature.parameters) >= 3:
        return runner(fixture.image_bgr.copy(), fixture.rectangle, fixture.prompt_points)
    return runner(fixture.image_bgr.copy(), fixture.rectangle)


def _boundary(mask: MaskArray) -> np.ndarray:
    fg = _foreground(mask).astype(np.uint8)
    if not np.any(fg):
        return np.zeros_like(fg, dtype=bool)
    kernel = np.ones((3, 3), dtype=np.uint8)
    eroded = cv2.erode(fg, kernel, iterations=1)
    return (fg != eroded).astype(bool)


def _boundary_score(predicted: MaskArray, reference: MaskArray, tolerance_px: int = 2) -> dict[str, float]:
    pred_boundary = _boundary(predicted)
    ref_boundary = _boundary(reference)
    if not pred_boundary.any() and not ref_boundary.any():
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred_boundary.any() or not ref_boundary.any():
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (tolerance_px * 2 + 1, tolerance_px * 2 + 1),
    )
    pred_near_ref = cv2.dilate(ref_boundary.astype(np.uint8), kernel, iterations=1).astype(bool)
    ref_near_pred = cv2.dilate(pred_boundary.astype(np.uint8), kernel, iterations=1).astype(bool)
    precision = float(np.count_nonzero(pred_boundary & pred_near_ref) / np.count_nonzero(pred_boundary))
    recall = float(np.count_nonzero(ref_boundary & ref_near_pred) / np.count_nonzero(ref_boundary))
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6)}


def segmentation_metrics(predicted: MaskArray, reference: MaskArray) -> dict[str, Any]:
    """Compute mask-overlap, boundary, and topology-preservation metrics."""

    pred = _foreground(predicted)
    ref = _foreground(reference)
    intersection = int(np.count_nonzero(pred & ref))
    union = int(np.count_nonzero(pred | ref))
    iou = 1.0 if union == 0 else intersection / union
    false_positive = int(np.count_nonzero(pred & ~ref))
    false_negative = int(np.count_nonzero(~pred & ref))
    pred_topology = _topology(predicted)
    ref_topology = _topology(reference)
    return {
        "iou": round(float(iou), 6),
        "boundary": _boundary_score(predicted, reference),
        "foreground_pixels": {"predicted": int(np.count_nonzero(pred)), "reference": int(np.count_nonzero(ref))},
        "false_positive_pixels": false_positive,
        "false_negative_pixels": false_negative,
        "topology": {
            "predicted": pred_topology,
            "reference": ref_topology,
            "components_preserved": pred_topology["components"] == ref_topology["components"],
            "holes_preserved": pred_topology["holes"] == ref_topology["holes"],
            "component_delta": pred_topology["components"] - ref_topology["components"],
            "hole_delta": pred_topology["holes"] - ref_topology["holes"],
        },
    }


def _write_fixture_images(fixtures: Sequence[SegmentationFixture], output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fixture_root = output_dir / "fixtures"
    for fixture in fixtures:
        root = fixture_root / fixture.name
        root.mkdir(parents=True, exist_ok=True)
        Image.fromarray(fixture.image_bgr[:, :, ::-1]).save(root / "source.png")
        Image.fromarray(fixture.reference_mask).save(root / "reference-mask.png")
        topology = _topology(fixture.reference_mask)
        rows.append({
            "name": fixture.name,
            "description": fixture.description,
            "rectangle": list(fixture.rectangle),
            "reference_topology": topology,
            "reference_foreground_pixels": int(np.count_nonzero(_foreground(fixture.reference_mask))),
            "source_notes": fixture.source_notes,
            "prompt_points": list(fixture.prompt_points),
            "prompt_scope": "Oracle/reference-assisted normalized keep/exclude points for equal point-prompt budget; not unassisted segmentation.",
            "artifacts": {
                "source_png": f"fixtures/{fixture.name}/source.png",
                "reference_mask_png": f"fixtures/{fixture.name}/reference-mask.png",
            },
        })
    return rows


def _mask_tile(mask: MaskArray, size: int) -> Image.Image:
    return Image.fromarray(_binary_mask(mask)).convert("RGB").resize((size, size), Image.Resampling.NEAREST)


def _source_tile(image_bgr: ImageArray, size: int) -> Image.Image:
    return Image.fromarray(image_bgr[:, :, ::-1]).resize((size, size), Image.Resampling.LANCZOS)


def _error_overlay(predicted: MaskArray, reference: MaskArray, size: int) -> Image.Image:
    pred = _foreground(predicted)
    ref = _foreground(reference)
    overlay = np.full((*ref.shape, 3), 255, dtype=np.uint8)
    overlay[ref & pred] = (0, 0, 0)        # true foreground
    overlay[pred & ~ref] = (40, 105, 230)  # false positive: blue
    overlay[~pred & ref] = (220, 45, 45)   # false negative: red
    return Image.fromarray(overlay).resize((size, size), Image.Resampling.NEAREST)


def _draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover - Pillow always has a default font in supported envs.
        font = None
    draw.text(xy, text, fill=(20, 20, 20), font=font)


def write_comparison_png(
    fixtures: Sequence[SegmentationFixture],
    predictions: Mapping[tuple[str, str], MaskArray],
    output_path: Path,
    *,
    real_probe: tuple[ImageArray, Mapping[str, MaskArray]] | None = None,
) -> None:
    """Write a contact sheet with source/reference/prediction/error columns."""

    segmenter_names = sorted({segmenter for _fixture, segmenter in predictions})
    tile = 154
    label_h = 42
    gap = 10
    columns = ["source", "reference"]
    for name in segmenter_names:
        columns.extend([name, f"{name} error"])
    width = gap + len(columns) * (tile + gap)
    rows = len(fixtures) + (1 if real_probe is not None else 0)
    height = gap + rows * (tile + label_h + gap)
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)

    for row_index, fixture in enumerate(fixtures):
        y = gap + row_index * (tile + label_h + gap)
        tiles = [_source_tile(fixture.image_bgr, tile), _mask_tile(fixture.reference_mask, tile)]
        for name in segmenter_names:
            pred = predictions.get((fixture.name, name))
            if pred is None:
                blank = Image.new("RGB", (tile, tile), (245, 245, 245))
                ImageDraw.Draw(blank).line((0, 0, tile, tile), fill=(180, 180, 180), width=3)
                tiles.extend([blank, blank.copy()])
            else:
                tiles.extend([_mask_tile(pred, tile), _error_overlay(pred, fixture.reference_mask, tile)])
        for col_index, img in enumerate(tiles):
            x = gap + col_index * (tile + gap)
            sheet.paste(img, (x, y))
            label = columns[col_index]
            if col_index == 0:
                label = f"{fixture.name}\nsource"
            _draw_label(draw, (x, y + tile + 3), label[:42])

    if real_probe is not None:
        image_bgr, real_predictions = real_probe
        y = gap + (len(fixtures)) * (tile + label_h + gap)
        source = _source_tile(image_bgr, tile)
        blank_ref = Image.new("RGB", (tile, tile), (248, 248, 248))
        _draw_label(ImageDraw.Draw(blank_ref), (8, 58), "qualitative only\nno ground truth")
        tiles = [source, blank_ref]
        for name in segmenter_names:
            pred = real_predictions.get(name)
            blank = Image.new("RGB", (tile, tile), (248, 248, 248))
            if pred is None:
                tiles.extend([blank, blank.copy()])
            else:
                tiles.extend([_mask_tile(pred, tile), blank])
        for col_index, img in enumerate(tiles):
            x = gap + col_index * (tile + gap)
            sheet.paste(img, (x, y))
            label = columns[col_index]
            if col_index == 0:
                label = "real_photo_probe\nsource"
            _draw_label(draw, (x, y + tile + 3), label[:42])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def _summarize(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_segmenter: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_segmenter.setdefault(row["segmenter"], []).append(row)
    summary: dict[str, Any] = {}
    for segmenter, rows in sorted(by_segmenter.items()):
        successful = [row for row in rows if row.get("status") == "ok"]
        if successful:
            mean_iou = sum(float(row["metrics"]["iou"]) for row in successful) / len(successful)
            mean_boundary = sum(float(row["metrics"]["boundary"]["f1"]) for row in successful) / len(successful)
            topology_exact = sum(
                bool(row["metrics"]["topology"]["components_preserved"])
                and bool(row["metrics"]["topology"]["holes_preserved"])
                for row in successful
            )
            mean_seconds = sum(float(row["seconds"]) for row in successful) / len(successful)
        else:
            mean_iou = mean_boundary = mean_seconds = 0.0
            topology_exact = 0
        summary[segmenter] = {
            "fixtures": len(rows),
            "successful": len(successful),
            "failed": len(rows) - len(successful),
            "mean_iou": round(mean_iou, 6),
            "mean_boundary_f1": round(mean_boundary, 6),
            "topology_exact_count": int(topology_exact),
            "mean_seconds": round(mean_seconds, 6),
        }
    return summary


def run_benchmark(
    output_dir: Path,
    *,
    segmenters: Mapping[str, Segmenter] | None = None,
    include_real_probe: bool = True,
) -> dict[str, Any]:
    """Run synthetic fixtures and write JSON/PNG artifacts.

    ML comparison hook: pass ``segmenters={"grabcut": grabcut_segmenter,
    "my_model": my_model_runner}``, where each runner follows SEGMENTER_CONTRACT.
    No largest-component filtering or hole filling is applied by this harness.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    segmenters = dict(segmenters or default_segmenters())
    fixtures = synthetic_fixtures()
    fixture_rows = _write_fixture_images(fixtures, output_dir)
    results: list[dict[str, Any]] = []
    predictions: dict[tuple[str, str], MaskArray] = {}

    for fixture in fixtures:
        for name, runner in segmenters.items():
            started = time.perf_counter()
            try:
                predicted = _binary_mask(_call_segmenter(runner, fixture))
                seconds = time.perf_counter() - started
                predictions[(fixture.name, name)] = predicted
                Image.fromarray(predicted).save(output_dir / "fixtures" / fixture.name / f"{name}-mask.png")
                results.append({
                    "fixture": fixture.name,
                    "segmenter": name,
                    "status": "ok",
                    "seconds": round(seconds, 6),
                    "metrics": segmentation_metrics(predicted, fixture.reference_mask),
                    "artifact": f"fixtures/{fixture.name}/{name}-mask.png",
                })
            except Exception as exc:  # Keep benchmark comparable even when one runner fails a hard case.
                seconds = time.perf_counter() - started
                results.append({
                    "fixture": fixture.name,
                    "segmenter": name,
                    "status": "error",
                    "seconds": round(seconds, 6),
                    "error": f"{type(exc).__name__}: {exc}",
                })

    qualitative_real_probe: dict[str, Any] | None = None
    real_for_sheet: tuple[ImageArray, Mapping[str, MaskArray]] | None = None
    if include_real_probe:
        real_path = Path("output/real-cutout-probe/fruits.jpg")
        if real_path.exists():
            image_bgr = cv2.imread(str(real_path), cv2.IMREAD_COLOR)
            if image_bgr is not None:
                rectangle: Rectangle = (0.13, 0.08, 0.69, 0.99)
                real_prompt_points: tuple[PromptPoint, ...] = ({"x": 0.43, "y": 0.54, "label": 1},)
                qualitative_results: list[dict[str, Any]] = []
                real_predictions: dict[str, MaskArray] = {}
                for name, runner in segmenters.items():
                    started = time.perf_counter()
                    try:
                        predicted = _binary_mask(runner(image_bgr.copy(), rectangle, real_prompt_points))
                        seconds = time.perf_counter() - started
                        real_predictions[name] = predicted
                        Image.fromarray(predicted).save(output_dir / f"real-photo-probe-{name}.png")
                        qualitative_results.append({
                            "segmenter": name,
                            "status": "ok",
                            "seconds": round(seconds, 6),
                            "topology": _topology(predicted),
                            "foreground_pixels": int(np.count_nonzero(_foreground(predicted))),
                            "artifact": f"real-photo-probe-{name}.png",
                        })
                    except Exception as exc:
                        qualitative_results.append({
                            "segmenter": name,
                            "status": "error",
                            "seconds": round(time.perf_counter() - started, 6),
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                qualitative_real_probe = {
                    "source": "output/real-cutout-probe/fruits.jpg",
                    "scope": "Qualitative optional existing photo only; no labeled ground truth and no accuracy claim.",
                    "rectangle": list(rectangle),
                    "prompt_points": list(real_prompt_points),
                    "prompt_scope": "Manual normalized keep point on the selected object; qualitative only, no ground-truth accuracy score.",
                    "results": qualitative_results,
                }
                real_for_sheet = (image_bgr, real_predictions)
            else:
                qualitative_real_probe = {
                    "source": "output/real-cutout-probe/fruits.jpg",
                    "scope": "Qualitative optional existing photo only; no labeled ground truth and no accuracy claim.",
                    "status": "unreadable",
                }

    comparison_path = output_dir / "comparison.png"
    write_comparison_png(fixtures, predictions, comparison_path, real_probe=real_for_sheet)
    report_path = output_dir / "benchmark-report.json"
    report: dict[str, Any] = {
        "kind": "segmentation-benchmark-v1",
        "scope": "Deterministic synthetic fixture benchmark for engineering comparison; synthetic is not real-world quality proof.",
        "mask_convention": MASK_CONVENTION,
        "rectangle_convention": RECTANGLE_CONVENTION,
        "segmenter_contract": SEGMENTER_CONTRACT,
        "baseline": "grabcut",
        "notes": [
            "Default baseline is the existing OpenCV GrabCut foreground extractor.",
            "The harness does not keep only the largest component, fill holes, or denoise runner output before scoring.",
            "SlimSAM runners use genuine pinned local weights when handwrite_font_maker.segmentation and its optional runtime are installed.",
            "SlimSAM receives deterministic oracle/reference-assisted normalized keep/exclude points; GrabCut receives only the normalized rectangle, so interaction budgets differ and are reported explicitly.",
        ],
        "fixtures": fixture_rows,
        "results": results,
        "summary": _summarize(results),
        "artifacts": {
            "report_json": "benchmark-report.json",
            "comparison_png": "comparison.png",
        },
    }
    if qualitative_real_probe is not None:
        report["qualitative_real_probe"] = qualitative_real_probe
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/segmentation-benchmark"))
    parser.add_argument("--skip-real-probe", action="store_true", help="Do not run the optional ignored real photo probe.")
    parser.add_argument("--methods", default="grabcut,slimsam,slimsam-int8", help="Comma-separated methods from grabcut, slimsam, slimsam-int8.")
    args = parser.parse_args(argv)
    available = default_segmenters()
    names = [name.strip() for name in args.methods.split(",") if name.strip()]
    unknown = [name for name in names if name not in available]
    if unknown:
        parser.error(f"Unknown methods: {', '.join(unknown)}")
    report = run_benchmark(args.output_dir, segmenters={name: available[name] for name in names}, include_real_probe=not args.skip_real_probe)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
