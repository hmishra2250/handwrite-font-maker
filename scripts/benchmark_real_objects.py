#!/usr/bin/env python3
"""Benchmark real object segmentation against independent published masks.

Inputs come from ``scripts/collect_object_samples.py``.  This runner compares
box-only methods separately from SlimSAM's required one keep-point prompt and
labels that point as reference-assisted/oracle to avoid unequal-prompt claims.
"""
from __future__ import annotations

import argparse
import json
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

from benchmark_segmentation import (  # noqa: E402
    MASK_CONVENTION,
    PromptPoint,
    Rectangle,
    _binary_mask,
    _foreground,
    _reference_prompt_points,
    segmentation_metrics,
)
from collect_object_samples import normalize_reference_mask, sha256_file  # noqa: E402
from handwrite_font_maker.foreground import extract_foreground  # noqa: E402

DEFAULT_MANIFEST = Path("output/detection-sources/objects/manifest.json")
DEFAULT_OUTPUT_DIR = Path("output/detection-sources/objects")
MethodRunner = Callable[[np.ndarray, Rectangle, Sequence[PromptPoint]], np.ndarray]


@dataclass(frozen=True)
class RealObjectSample:
    sample_id: str
    split: str
    source_group: str
    image_path: Path
    mask_path: Path
    rectangle: Rectangle
    prompt_points: tuple[PromptPoint, ...]
    metadata: dict[str, Any]


def _portable(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        try:
            return str(path.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return path.name


def _resolve_manifest_path(path_text: str, manifest_path: Path, output_dir: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    candidates = [output_dir / path, manifest_path.parent / path, Path.cwd() / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_bgr(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        oriented = ImageOps.exif_transpose(image)
        if oriented.mode in {"RGBA", "LA"} or (oriented.mode == "P" and "transparency" in oriented.info):
            rgba = oriented.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            background.alpha_composite(rgba)
            rgb = background.convert("RGB")
        else:
            rgb = oriented.convert("RGB")
    return np.asarray(rgb, dtype=np.uint8)[:, :, ::-1].copy()



def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"sample {row.get('sample_id')} is missing required non-empty {key}")
    return value


def _required_sha256(row: Mapping[str, Any], key: str) -> str:
    value = _required_text(row, key)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise ValueError(f"sample {row.get('sample_id')} has malformed {key}")
    return value.lower()


def _required_size(row: Mapping[str, Any], key: str) -> tuple[int, int]:
    value = row.get(key)
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in value)
    ):
        raise ValueError(f"sample {row.get('sample_id')} has malformed required {key}")
    return (int(value[0]), int(value[1]))

def _validate_rectangle(rectangle: Sequence[Any]) -> Rectangle:
    if len(rectangle) != 4:
        raise ValueError("rectangle must have four normalized values")
    left, top, right, bottom = (float(v) for v in rectangle)
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("rectangle must be normalized left/top/right/bottom with positive area")
    return (left, top, right, bottom)


def _one_keep_point(mask: np.ndarray, rectangle: Rectangle, row: Mapping[str, Any]) -> tuple[PromptPoint, ...]:
    manifest_points = [p for p in row.get("prompt_points", []) if p.get("label") == 1]
    if manifest_points:
        p = manifest_points[0]
        return ({"x": float(p["x"]), "y": float(p["y"]), "label": 1},)
    positives = [p for p in _reference_prompt_points(mask, rectangle) if p["label"] == 1]
    if not positives:
        raise ValueError("could not derive a keep point from the reference mask")
    p = positives[0]
    return ({"x": float(p["x"]), "y": float(p["y"]), "label": 1},)


def load_samples(manifest_path: Path = DEFAULT_MANIFEST, *, limit: int | None = None) -> tuple[dict[str, Any], list[RealObjectSample]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir = manifest_path.parent
    samples: list[RealObjectSample] = []
    group_splits: dict[str, str] = {}
    image_hash_splits: dict[str, str] = {}
    rows = manifest.get("samples", [])
    if limit is not None:
        rows = rows[:limit]
    seen_sample_ids: set[str] = set()
    for row in rows:
        sample_id = _required_text(row, "sample_id")
        if sample_id in seen_sample_ids:
            raise ValueError(f"duplicate sample_id: {sample_id}")
        seen_sample_ids.add(sample_id)
        _required_text(row, "independent_annotation_origin")
        split = _required_text(row, "split")
        if split not in {"dev", "heldout"}:
            raise ValueError(f"sample {sample_id} has invalid split {split!r}")
        group = _required_text(row, "source_group")
        expected_image_hash = _required_sha256(row, "image_sha256")
        expected_mask_hash = _required_sha256(row, "reference_mask_sha256")
        expected_image_size = _required_size(row, "image_size")
        expected_mask_size = _required_size(row, "published_mask_size")
        image_path = _resolve_manifest_path(_required_text(row, "image"), manifest_path, output_dir)
        mask_path = _resolve_manifest_path(_required_text(row, "reference_mask"), manifest_path, output_dir)
        if sha256_file(image_path) != expected_image_hash:
            raise ValueError(f"image SHA-256 mismatch for {sample_id}")
        if sha256_file(mask_path) != expected_mask_hash:
            raise ValueError(f"reference mask SHA-256 mismatch for {sample_id}")
        rectangle = _validate_rectangle(row["rectangle"])
        with Image.open(image_path) as image:
            image_size = ImageOps.exif_transpose(image).convert("RGB").size
        with Image.open(mask_path) as mask_image:
            published_mask_size = mask_image.size
        if image_size != expected_image_size:
            raise ValueError(f"image dimensions changed for {sample_id}")
        if published_mask_size != expected_mask_size:
            raise ValueError(f"reference mask dimensions changed for {sample_id}")
        prior_split = group_splits.setdefault(group, split)
        if prior_split != split:
            raise ValueError(f"source_group {group} appears in both {prior_split} and {split}")
        image_hash = expected_image_hash
        prior_hash_split = image_hash_splits.setdefault(image_hash, split)
        if prior_hash_split != split:
            raise ValueError(f"duplicate image hash crosses splits for {row['sample_id']}")
        reference = normalize_reference_mask(mask_path, image_size)
        points = _one_keep_point(reference, rectangle, row)
        samples.append(RealObjectSample(
            sample_id=sample_id,
            split=split,
            source_group=group,
            image_path=image_path,
            mask_path=mask_path,
            rectangle=rectangle,
            prompt_points=points,
            metadata=row,
        ))
    if not samples:
        raise ValueError(f"no samples loaded from {manifest_path}")
    return manifest, samples


def grabcut_bbox(image_bgr: np.ndarray, rectangle: Rectangle, prompt_points: Sequence[PromptPoint]) -> np.ndarray:
    del prompt_points
    return extract_foreground(image_bgr, list(rectangle))


def efficientsam_bbox(image_bgr: np.ndarray, rectangle: Rectangle, prompt_points: Sequence[PromptPoint]) -> np.ndarray:
    del prompt_points
    from handwrite_font_maker.efficient_segmentation import predict_efficientsam_box

    return predict_efficientsam_box(image_bgr, list(rectangle))


def slimsam_one_point(image_bgr: np.ndarray, rectangle: Rectangle, prompt_points: Sequence[PromptPoint]) -> np.ndarray:
    from handwrite_font_maker.segmentation import predict_slimsam

    points = [dict(prompt_points[0])]
    return predict_slimsam(image_bgr, list(rectangle), variant="fp32", points=points)


def default_methods() -> dict[str, MethodRunner]:
    return {
        "grabcut-bbox": grabcut_bbox,
        "efficientsam-bbox": efficientsam_bbox,
        "slimsam-one-point": slimsam_one_point,
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for method in sorted({row["method"] for row in rows}):
        method_rows = [row for row in rows if row["method"] == method]
        ok = [row for row in method_rows if row.get("status") == "ok"]
        all_iou = [float(row["metrics"]["iou"]) if row.get("status") == "ok" else 0.0 for row in method_rows]
        all_boundary = [float(row["metrics"]["boundary"]["f1"]) if row.get("status") == "ok" else 0.0 for row in method_rows]
        ok_iou = [float(row["metrics"]["iou"]) for row in ok]
        ok_boundary = [float(row["metrics"]["boundary"]["f1"]) for row in ok]
        topology_exact = sum(
            bool(row["metrics"]["topology"]["components_preserved"])
            and bool(row["metrics"]["topology"]["holes_preserved"])
            for row in ok
        )
        mean_seconds = _mean([float(row["seconds"]) for row in ok])
        split_summary: dict[str, dict[str, float | int]] = {}
        for split in sorted({row["split"] for row in method_rows}):
            split_rows = [row for row in method_rows if row["split"] == split]
            split_ok = [row for row in split_rows if row.get("status") == "ok"]
            split_summary[split] = {
                "samples": len(split_rows),
                "successful": len(split_ok),
                "mean_iou": round(_mean([float(row["metrics"]["iou"]) if row.get("status") == "ok" else 0.0 for row in split_rows]), 6),
                "mean_iou_successful_only": round(_mean([float(row["metrics"]["iou"]) for row in split_ok]), 6),
            }
        alignment_summary: dict[str, dict[str, float | int]] = {}
        for label in sorted({row.get("mask_alignment", "unknown") for row in method_rows}):
            aligned_rows = [row for row in method_rows if row.get("mask_alignment", "unknown") == label]
            aligned_ok = [row for row in aligned_rows if row.get("status") == "ok"]
            alignment_summary[str(label)] = {
                "samples": len(aligned_rows),
                "successful": len(aligned_ok),
                "mean_iou": round(_mean([float(row["metrics"]["iou"]) if row.get("status") == "ok" else 0.0 for row in aligned_rows]), 6),
                "mean_boundary_f1": round(_mean([float(row["metrics"]["boundary"]["f1"]) if row.get("status") == "ok" else 0.0 for row in aligned_rows]), 6),
            }
        summary[method] = {
            "samples": len(method_rows),
            "successful": len(ok),
            "failed": len(method_rows) - len(ok),
            "mean_iou": round(_mean(all_iou), 6),
            "mean_boundary_f1": round(_mean(all_boundary), 6),
            "mean_iou_denominator": "all samples; failed runs contribute 0.0",
            "mean_boundary_f1_denominator": "all samples; failed runs contribute 0.0",
            "mean_iou_successful_only": round(_mean(ok_iou), 6),
            "mean_boundary_f1_successful_only": round(_mean(ok_boundary), 6),
            "topology_exact_count": int(topology_exact),
            "mean_seconds_successful_only": round(mean_seconds, 6),
            "by_split": split_summary,
            "by_mask_alignment": alignment_summary,
        }
    return summary

def _source_tile(image_bgr: np.ndarray, size: int) -> Image.Image:
    return Image.fromarray(image_bgr[:, :, ::-1]).resize((size, size), Image.Resampling.LANCZOS)


def _mask_tile(mask: np.ndarray, size: int) -> Image.Image:
    return Image.fromarray(_binary_mask(mask)).convert("RGB").resize((size, size), Image.Resampling.NEAREST)


def _error_overlay(predicted: np.ndarray, reference: np.ndarray, size: int) -> Image.Image:
    pred = _foreground(predicted)
    ref = _foreground(reference)
    overlay = np.full((*ref.shape, 3), 255, dtype=np.uint8)
    overlay[ref & pred] = (0, 0, 0)
    overlay[pred & ~ref] = (40, 105, 230)
    overlay[~pred & ref] = (220, 45, 45)
    return Image.fromarray(overlay).resize((size, size), Image.Resampling.NEAREST)


def _draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover
        font = None
    draw.text(xy, text, fill=(20, 20, 20), font=font)


def write_contact_sheet(
    output_path: Path,
    samples: Sequence[RealObjectSample],
    references: Mapping[str, np.ndarray],
    predictions: Mapping[tuple[str, str], np.ndarray],
    methods: Sequence[str],
    *,
    max_samples: int = 12,
) -> None:
    shown = list(samples[:max_samples])
    tile = 128
    label_h = 42
    gap = 8
    columns = ["source", "reference"]
    for method in methods:
        columns.extend([method, f"{method} error"])
    width = gap + len(columns) * (tile + gap)
    height = gap + len(shown) * (tile + label_h + gap)
    sheet = Image.new("RGB", (width, max(height, tile + label_h + 2 * gap)), "white")
    draw = ImageDraw.Draw(sheet)
    for row_idx, sample in enumerate(shown):
        y = gap + row_idx * (tile + label_h + gap)
        source = _source_tile(_load_bgr(sample.image_path), tile)
        ref = references[sample.sample_id]
        tiles = [source, _mask_tile(ref, tile)]
        for method in methods:
            pred = predictions.get((sample.sample_id, method))
            if pred is None:
                blank = Image.new("RGB", (tile, tile), (245, 245, 245))
                ImageDraw.Draw(blank).line((0, 0, tile, tile), fill=(180, 180, 180), width=3)
                tiles.extend([blank, blank.copy()])
            else:
                tiles.extend([_mask_tile(pred, tile), _error_overlay(pred, ref, tile)])
        for col_idx, tile_image in enumerate(tiles):
            x = gap + col_idx * (tile + gap)
            sheet.paste(tile_image, (x, y))
            label = columns[col_idx]
            if col_idx == 0:
                label = f"{sample.sample_id}\n{sample.split}"
            _draw_label(draw, (x, y + tile + 3), label[:42])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)



def _alignment_label(sample: RealObjectSample) -> str:
    alignment = sample.metadata.get("mask_alignment", {})
    if isinstance(alignment, dict) and alignment.get("image_size_matches_published_mask") is False:
        return "resized-published-mask"
    if isinstance(alignment, dict) and alignment.get("image_size_matches_published_mask") is True:
        return "same-dimensions"
    image_size = sample.metadata.get("image_size")
    mask_size = sample.metadata.get("published_mask_size")
    return "same-dimensions" if image_size and mask_size and list(image_size) == list(mask_size) else "unknown"


def _prior_results(output_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    path = output_dir / "real-object-benchmark.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {(str(row.get("sample_id")), str(row.get("method"))): row for row in data.get("results", [])}

def run_benchmark(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    methods: Mapping[str, MethodRunner] | None = None,
    limit: int | None = None,
    contact_sheet_limit: int = 12,
    reuse_predictions: bool = False,
) -> dict[str, Any]:
    source_manifest, samples = load_samples(manifest_path, limit=limit)
    methods = dict(methods or default_methods())
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_root = output_dir / "predictions"
    results: list[dict[str, Any]] = []
    prior_results = _prior_results(output_dir) if reuse_predictions else {}
    predictions: dict[tuple[str, str], np.ndarray] = {}
    references: dict[str, np.ndarray] = {}

    loaded: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for sample in samples:
        image_bgr = _load_bgr(sample.image_path)
        image_size = (image_bgr.shape[1], image_bgr.shape[0])
        reference = normalize_reference_mask(sample.mask_path, image_size)
        loaded[sample.sample_id] = (image_bgr, reference)
        references[sample.sample_id] = reference
        sample_dir = prediction_root / sample.sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(reference).save(sample_dir / "reference-normalized.png")

    # Run sequentially by method so optional ONNX model sessions stay cached; this
    # avoids repeatedly evicting EfficientSAM and SlimSAM in the shared cache.
    for method_name, runner in methods.items():
        for sample in samples:
            image_bgr, reference = loaded[sample.sample_id]
            sample_dir = prediction_root / sample.sample_id
            artifact = sample_dir / f"{method_name}.png"
            alignment_label = _alignment_label(sample)
            base_row = {
                "sample_id": sample.sample_id,
                "split": sample.split,
                "source_group": sample.source_group,
                "method": method_name,
                "mask_alignment": alignment_label,
                "image_size": sample.metadata.get("image_size"),
                "published_mask_size": sample.metadata.get("published_mask_size"),
                "independent_annotation_origin": sample.metadata.get("independent_annotation_origin"),
                "rectangle_scope": sample.metadata.get("rectangle_scope", "Reference-mask-derived oracle bounding box."),
            }
            prior = prior_results.get((sample.sample_id, method_name), {})
            if reuse_predictions and artifact.exists():
                predicted = _binary_mask(np.asarray(Image.open(artifact).convert("L"), dtype=np.uint8))
                predictions[(sample.sample_id, method_name)] = predicted
                results.append({
                    **base_row,
                    "status": "ok",
                    "seconds": float(prior.get("seconds", 0.0)),
                    "metrics": segmentation_metrics(predicted, reference),
                    "artifact": _portable(artifact, output_dir),
                    "reused_prediction": True,
                })
                continue
            if reuse_predictions and prior.get("status") == "error":
                results.append({**base_row, **prior, "reused_prediction": True})
                continue
            started = time.perf_counter()
            try:
                predicted = _binary_mask(runner(image_bgr.copy(), sample.rectangle, sample.prompt_points))
                seconds = time.perf_counter() - started
                predictions[(sample.sample_id, method_name)] = predicted
                Image.fromarray(predicted).save(artifact)
                results.append({
                    **base_row,
                    "status": "ok",
                    "seconds": round(seconds, 6),
                    "metrics": segmentation_metrics(predicted, reference),
                    "artifact": _portable(artifact, output_dir),
                })
            except Exception as exc:
                results.append({
                    **base_row,
                    "status": "error",
                    "seconds": round(time.perf_counter() - started, 6),
                    "error": f"{type(exc).__name__}: {exc}",
                })

    comparison_path = output_dir / "real-object-comparison.png"
    write_contact_sheet(comparison_path, samples, references, predictions, tuple(methods), max_samples=contact_sheet_limit)
    report: dict[str, Any] = {
        "kind": "real-object-segmentation-benchmark-v1",
        "scope": "Real licensed leaf/object photos scored against independent published reference masks; no model-generated pseudo-ground-truth.",
        "mask_convention": MASK_CONVENTION,
        "source": source_manifest.get("source", {}),
        "sample_count": len(samples),
        "methods": {
            "grabcut-bbox": "Existing OpenCV GrabCut baseline; normalized rectangle only.",
            "efficientsam-bbox": "EfficientSAM local learned weights; same normalized rectangle-only budget as GrabCut.",
            "slimsam-one-point": "SlimSAM fp32 local learned weights; normalized rectangle plus one deterministic reference-assisted keep point because this export requires point labels.",
        },
        "prompt_comparison_note": "Compare GrabCut vs EfficientSAM as bbox-only. SlimSAM one-point is a separate assisted diagnostic and must not be described as prompt-equivalent to bbox-only methods. All rectangles are reference-mask-derived oracle boxes, not detector outputs.",
        "integrity_checks": {
            "verified_sample_hashes": True,
            "verified_recorded_dimensions": True,
            "verified_no_source_group_crosses_splits": True,
            "verified_no_duplicate_image_hash_crosses_splits": True,
            "independent_annotation_required": True,
        },
        "mask_alignment_note": "Rows marked resized-published-mask use nearest-neighbor resizing to align independent published masks to paired RGB images; same-dimensions means no geometric resizing was required.",
        "samples": [
            {
                "sample_id": sample.sample_id,
                "split": sample.split,
                "source_group": sample.source_group,
                "rectangle": list(sample.rectangle),
                "rectangle_scope": sample.metadata.get("rectangle_scope", "Reference-mask-derived oracle bounding box."),
                "prompt_points": list(sample.prompt_points),
                "image": _portable(sample.image_path, output_dir),
                "reference_mask": _portable(sample.mask_path, output_dir),
                "image_size": sample.metadata.get("image_size"),
                "published_mask_size": sample.metadata.get("published_mask_size"),
                "mask_alignment": _alignment_label(sample),
                "independent_annotation_origin": sample.metadata.get("independent_annotation_origin"),
            }
            for sample in samples
        ],
        "results": results,
        "summary": _summarize(results),
        "artifacts": {
            "report_json": "real-object-benchmark.json",
            "comparison_png": "real-object-comparison.png",
            "predictions_dir": "predictions/",
        },
    }
    report_path = output_dir / "real-object-benchmark.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--methods", default="grabcut-bbox,efficientsam-bbox,slimsam-one-point")
    parser.add_argument("--limit", type=int, default=None, help="Optional first-N subset for smoke runs.")
    parser.add_argument("--contact-sheet-limit", type=int, default=12)
    parser.add_argument("--reuse-predictions", action="store_true", help="Reuse existing prediction PNGs and recompute metrics/report without running inference.")
    args = parser.parse_args(argv)
    available = default_methods()
    names = [name.strip() for name in args.methods.split(",") if name.strip()]
    unknown = [name for name in names if name not in available]
    if unknown:
        parser.error(f"unknown methods: {', '.join(unknown)}")
    report = run_benchmark(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        methods={name: available[name] for name in names},
        limit=args.limit,
        contact_sheet_limit=args.contact_sheet_limit,
        reuse_predictions=args.reuse_predictions,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
