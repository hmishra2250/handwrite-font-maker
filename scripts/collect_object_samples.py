#!/usr/bin/env python3
"""Collect licensed real object segmentation samples with published masks.

The default source is a bounded Mendeley Data archive (~19 MB) containing real
leaf photos and independent reference masks.  The output stays under ignored
``output/detection-sources/objects`` and records only portable relative paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageOps

MASK_CONVENTION = "uint8 grayscale mask: 0/black = foreground object, 255/white = background"
DEFAULT_SOURCE_MANIFEST = Path("docs/research/object-sources.json")
DEFAULT_OUTPUT_DIR = Path("output/detection-sources/objects")
DEFAULT_LIMIT = 72
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class ObjectPair:
    sample_id: str
    image_path: Path
    mask_path: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        try:
            return str(path.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return path.name


def load_source_manifest(path: Path = DEFAULT_SOURCE_MANIFEST) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("sources"):
        raise ValueError("source manifest must contain at least one source")
    return data


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": "handwrite-font-maker-real-object-benchmark/1.0"})


def download_archive(source: dict[str, Any], output_dir: Path, *, force: bool = False) -> Path:
    archive = source["archive"]
    if int(archive.get("size_bytes", 0)) > 200_000_000:
        raise ValueError("archive exceeds the benchmark's 200 MB bounded-download cap")
    downloads = output_dir / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive_path = downloads / archive["filename"]
    expected_sha = archive["sha256"]
    if archive_path.exists() and not force:
        if sha256_file(archive_path) == expected_sha:
            return archive_path
        archive_path.unlink()
    byte_cap = 200_000_000
    total = 0
    with urllib.request.urlopen(_request(archive["download_url"]), timeout=180) as response, archive_path.open("wb") as stream:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > byte_cap:
                archive_path.unlink(missing_ok=True)
                raise ValueError("download exceeded the benchmark's 200 MB bounded-download cap")
            stream.write(chunk)
    actual_sha = sha256_file(archive_path)
    if actual_sha != expected_sha:
        archive_path.unlink(missing_ok=True)
        raise ValueError(f"downloaded archive SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")
    return archive_path


def verify_archive(source: dict[str, Any], output_dir: Path) -> Path:
    archive = source["archive"]
    archive_path = output_dir / "downloads" / archive["filename"]
    if not archive_path.exists():
        raise FileNotFoundError(f"archive missing: {archive_path}; rerun with --download")
    actual_sha = sha256_file(archive_path)
    if actual_sha != archive["sha256"]:
        raise ValueError(f"archive SHA-256 mismatch: expected {archive['sha256']}, got {actual_sha}")
    return archive_path


def extract_archive(source: dict[str, Any], archive_path: Path, output_dir: Path, *, force: bool = False) -> Path:
    archive = source["archive"]
    extract_dir = output_dir / "extracted"
    dataset_root = extract_dir / archive["dataset_root"]
    if dataset_root.exists() and not force:
        return dataset_root
    if force and dataset_root.exists():
        shutil.rmtree(dataset_root)
    extract_dir.mkdir(parents=True, exist_ok=True)
    bsdtar = shutil.which("bsdtar")
    if not bsdtar:
        raise RuntimeError("bsdtar is required to extract the source RAR archive")
    subprocess.run([bsdtar, "-xf", str(archive_path), "-C", str(extract_dir)], check=True)
    if not dataset_root.exists():
        raise FileNotFoundError(f"expected extracted dataset root not found: {dataset_root}")
    return dataset_root


def _stem_sort_key(path: Path) -> tuple[int, str]:
    digits = "".join(ch for ch in path.stem if ch.isdigit())
    return (int(digits) if digits else 10**12, path.stem)


def discover_pairs(dataset_root: Path, *, image_dir: str = "image", mask_dir: str = "mask") -> list[ObjectPair]:
    images = {
        path.stem: path
        for path in (dataset_root / image_dir).iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    }
    masks = {
        path.stem: path
        for path in (dataset_root / mask_dir).iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    }
    pairs = [ObjectPair(stem, images[stem], masks[stem]) for stem in sorted(set(images) & set(masks), key=lambda s: _stem_sort_key(Path(s)))]
    if not pairs:
        raise ValueError(f"no image/mask pairs found under {dataset_root}")
    return pairs


def select_pairs(pairs: Sequence[ObjectPair], limit: int = DEFAULT_LIMIT) -> list[ObjectPair]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if len(pairs) <= limit:
        return list(pairs)
    if limit == 1:
        return [pairs[0]]
    # Evenly span the dataset instead of taking the first N adjacent filenames.
    indexes: list[int] = []
    used: set[int] = set()
    for i in range(limit):
        idx = round(i * (len(pairs) - 1) / (limit - 1))
        if idx in used:
            idx = next(j for j in range(len(pairs)) if j not in used)
        indexes.append(idx)
        used.add(idx)
    return [pairs[i] for i in sorted(indexes)]


def _read_rgb_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB").size


def normalize_reference_mask(mask_path: Path, image_size: tuple[int, int] | None = None) -> np.ndarray:
    with Image.open(mask_path) as image:
        gray = ImageOps.exif_transpose(image).convert("L")
        if image_size is not None and gray.size != image_size:
            gray = gray.resize(image_size, Image.Resampling.NEAREST)
        arr = np.asarray(gray, dtype=np.uint8)
    border = np.concatenate([arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]])
    # Dataset masks are white foreground on dark background; this also handles
    # the opposite convention for unit fixtures by looking at border background.
    foreground = arr >= 128 if float(np.median(border)) < 128 else arr < 128
    return np.where(foreground, 0, 255).astype(np.uint8)


def rectangle_for(mask: np.ndarray, padding: int = 8) -> tuple[float, float, float, float]:
    ys, xs = np.where(mask < 128)
    if xs.size == 0:
        raise ValueError("reference mask has no foreground pixels")
    height, width = mask.shape[:2]
    left = max(0, int(xs.min()) - padding) / width
    top = max(0, int(ys.min()) - padding) / height
    right = min(width, int(xs.max()) + padding + 1) / width
    bottom = min(height, int(ys.max()) + padding + 1) / height
    return (round(left, 6), round(top, 6), round(right, 6), round(bottom, 6))


def keep_point_for(mask: np.ndarray, rectangle: tuple[float, float, float, float]) -> dict[str, float | int]:
    foreground = (mask < 128).astype(np.uint8)
    count, labels = cv2.connectedComponents(foreground, connectivity=8)
    if count <= 1:
        raise ValueError("reference mask has no foreground component")
    # Pick the largest component, then the most interior pixel by distance transform.
    best_label = max(range(1, count), key=lambda label: int(np.count_nonzero(labels == label)))
    component = (labels == best_label).astype(np.uint8)
    distance = cv2.distanceTransform(component, cv2.DIST_L2, 3)
    y, x = np.unravel_index(int(np.argmax(distance)), distance.shape)
    height, width = mask.shape[:2]
    point = {"x": round(float(x) / width, 6), "y": round(float(y) / height, 6), "label": 1}
    left, top, right, bottom = rectangle
    if not (left <= point["x"] <= right and top <= point["y"] <= bottom):
        raise ValueError("derived keep point is outside derived rectangle")
    return point


def source_group_for(sample_id: str) -> str:
    digits = "".join(ch for ch in sample_id if ch.isdigit())
    if digits:
        return f"numeric-hundred-bucket-{int(digits) // 100:03d}"
    return f"stem-prefix-{sample_id[:3]}"


def split_for_group(group: str) -> str:
    digest = hashlib.sha256(group.encode("utf-8")).digest()[0]
    return "heldout" if digest % 5 == 0 else "dev"


def build_sample_rows(pairs: Sequence[ObjectPair], output_dir: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        image_size = _read_rgb_size(pair.image_path)
        with Image.open(pair.mask_path) as mask_image:
            published_mask_size = mask_image.size
        mask = normalize_reference_mask(pair.mask_path, image_size)
        rectangle = rectangle_for(mask)
        prompt = keep_point_for(mask, rectangle)
        group = source_group_for(pair.sample_id)
        rows.append({
            "sample_id": pair.sample_id,
            "source_id": source["source_id"],
            "source_group": group,
            "split": split_for_group(group),
            "image": _portable(pair.image_path, output_dir),
            "reference_mask": _portable(pair.mask_path, output_dir),
            "image_sha256": sha256_file(pair.image_path),
            "reference_mask_sha256": sha256_file(pair.mask_path),
            "image_size": list(image_size),
            "published_mask_size": list(published_mask_size),
            "reference_mask_normalization": "resize to image size with nearest-neighbor if needed; infer foreground polarity from border background; output black foreground/white background",
            "mask_alignment": {
                "image_size_matches_published_mask": list(image_size) == list(published_mask_size),
                "assumption": "When dimensions differ, the benchmark uses nearest-neighbor resizing to align the published mask to the publisher's paired RGB image; this is recorded and summarized separately.",
            },
            "independent_annotation_origin": "Published dataset mask folder; not generated by this benchmark or by evaluated models.",
            "rectangle": list(rectangle),
            "rectangle_scope": "Reference-mask-derived oracle bounding box supplied equally to bbox methods and as SlimSAM ROI; not an automatic detector output.",
            "prompt_points": [prompt],
            "prompt_scope": "Single deterministic reference-assisted keep point for models that require a point prompt; not unassisted segmentation.",
        })
    return rows


def collect_samples(
    *,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit: int = DEFAULT_LIMIT,
    download: bool = False,
    force_download: bool = False,
    force_extract: bool = False,
) -> dict[str, Any]:
    source_manifest = load_source_manifest(source_manifest_path)
    source = source_manifest["sources"][0]
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = download_archive(source, output_dir, force=force_download) if download else verify_archive(source, output_dir)
    dataset_root = extract_archive(source, archive_path, output_dir, force=force_extract)
    archive = source["archive"]
    all_pairs = discover_pairs(dataset_root, image_dir=archive["image_dir"], mask_dir=archive["mask_dir"])
    selected = select_pairs(all_pairs, limit)
    sample_rows = build_sample_rows(selected, output_dir, source)
    split_counts: dict[str, int] = {}
    for row in sample_rows:
        split_counts[row["split"]] = split_counts.get(row["split"], 0) + 1
    report: dict[str, Any] = {
        "kind": "real-object-sample-manifest-v1",
        "source_manifest": _portable(source_manifest_path, output_dir),
        "mask_convention": MASK_CONVENTION,
        "source": {
            "source_id": source["source_id"],
            "dataset_name": source["dataset_name"],
            "doi": source["doi"],
            "landing_url": source["landing_url"],
            "api_url": source["api_url"],
            "license": source["license"],
            "attribution": source["attribution"],
            "archive": {
                "filename": archive["filename"],
                "size_bytes": archive["size_bytes"],
                "sha256": archive["sha256"],
            },
            "independent_annotation_origin": source.get("description_evidence", "Published dataset masks; not model-generated."),
        },
        "total_paired_samples_available": len(all_pairs),
        "selected_sample_count": len(sample_rows),
        "selection_policy": f"deterministically even-spaced over sorted paired filenames; requested limit={limit}",
        "split_policy": source_manifest.get("split_policy"),
        "grouping_limitation": "No plant/session IDs are provided in the selected archive metadata; source_group is a filename numeric bucket, so split leakage by biological specimen cannot be ruled out.",
        "split_counts": split_counts,
        "samples": sample_rows,
        "artifacts": {"sample_manifest_json": "manifest.json"},
    }
    (output_dir / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--download", action="store_true", help="Download the bounded licensed archive when absent or invalid.")
    parser.add_argument("--force-download", action="store_true", help="Redownload even if the archive already verifies.")
    parser.add_argument("--force-extract", action="store_true", help="Re-extract the archive into the ignored output directory.")
    args = parser.parse_args(argv)
    report = collect_samples(
        source_manifest_path=args.source_manifest,
        output_dir=args.output_dir,
        limit=args.limit,
        download=args.download,
        force_download=args.force_download,
        force_extract=args.force_extract,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
