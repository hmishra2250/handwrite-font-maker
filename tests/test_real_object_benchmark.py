from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_script(name: str):
    module_path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


collect = _load_script("collect_object_samples")
bench = _load_script("benchmark_real_objects")


def _write_pair(root: Path, stem: str, *, white_foreground: bool = True) -> None:
    image_dir = root / "image"
    mask_dir = root / "mask"
    image_dir.mkdir(parents=True, exist_ok=True)
    mask_dir.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (48, 40), (30, 70, 35))
    draw = ImageDraw.Draw(image)
    draw.ellipse((13, 8, 35, 30), fill=(80, 150, 70))
    image.save(image_dir / f"{stem}.jpg")
    bg, fg = (0, 255) if white_foreground else (255, 0)
    mask = Image.new("L", (96, 80), bg)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((26, 16, 70, 60), fill=fg)
    mask.save(mask_dir / f"{stem}.jpg")


def test_source_manifest_records_primary_license_and_bounded_archive():
    manifest = json.loads((ROOT / "docs" / "research" / "object-sources.json").read_text(encoding="utf-8"))
    source = manifest["sources"][0]

    assert source["doi"] == "10.17632/46n94cngkx.1"
    assert source["license"]["short_name"] == "CC BY 4.0"
    assert source["archive"]["size_bytes"] < 200_000_000
    assert len(source["archive"]["sha256"]) == 64
    assert not Path(source["archive"]["filename"]).is_absolute()


def test_collect_discovers_pairs_normalizes_mask_and_builds_portable_rows(tmp_path: Path):
    dataset = tmp_path / "out" / "extracted" / "Plant_Leaf_Segmentation"
    for stem in ("100s", "200s", "300s", "400s", "500s"):
        _write_pair(dataset, stem, white_foreground=True)

    pairs = collect.discover_pairs(dataset)
    selected = collect.select_pairs(pairs, 3)
    rows = collect.build_sample_rows(selected, tmp_path / "out", {
        "source_id": "unit-source",
    })

    assert [pair.sample_id for pair in selected] == ["100s", "300s", "500s"]
    assert len(rows) == 3
    assert all(not Path(row["image"]).is_absolute() for row in rows)
    assert all(row["prompt_points"][0]["label"] == 1 for row in rows)
    assert {row["split"] for row in rows}.issubset({"dev", "heldout"})

    normalized = collect.normalize_reference_mask(dataset / "mask" / "100s.jpg", (48, 40))
    assert normalized.shape == (40, 48)
    assert set(np.unique(normalized)).issubset({0, 255})
    assert int((normalized < 128).sum()) > 0
    assert normalized[0, 0] == 255


def test_real_object_benchmark_uses_independent_reference_masks_and_portable_outputs(tmp_path: Path):
    output_dir = tmp_path / "objects"
    dataset = output_dir / "extracted" / "Plant_Leaf_Segmentation"
    _write_pair(dataset, "100s", white_foreground=True)
    _write_pair(dataset, "200s", white_foreground=False)

    pairs = collect.discover_pairs(dataset)
    source = {
        "source_id": "unit-source",
        "dataset_name": "unit real leaves",
        "doi": "10.test/unit",
        "landing_url": "https://example.test/dataset",
        "api_url": "https://example.test/api",
        "license": {"short_name": "test-license", "url": "https://example.test/license"},
        "attribution": "unit",
        "archive": {"filename": "unit.rar", "size_bytes": 1, "sha256": "0" * 64},
    }
    rows = collect.build_sample_rows(pairs, output_dir, source)
    manifest = {
        "kind": "real-object-sample-manifest-v1",
        "source": source,
        "samples": rows,
    }
    manifest_path = output_dir / "manifest.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def perfect(image_bgr, rectangle, prompt_points):
        assert image_bgr.dtype == np.uint8
        assert len(rectangle) == 4
        assert len(prompt_points) == 1
        sample = rows[len(seen)]
        seen.append(sample["sample_id"])
        return collect.normalize_reference_mask(output_dir / sample["reference_mask"], tuple(sample["image_size"]))

    def failing(*_args):
        raise RuntimeError("unit failure")

    seen: list[str] = []
    report = bench.run_benchmark(
        manifest_path=manifest_path,
        output_dir=output_dir,
        methods={"perfect-one-point-stub": perfect, "failing-stub": failing},
        contact_sheet_limit=2,
    )

    assert report["scope"].startswith("Real licensed leaf/object photos")
    assert "no model-generated pseudo-ground-truth" in report["scope"]
    assert report["summary"]["perfect-one-point-stub"]["mean_iou"] == 1.0
    assert report["summary"]["failing-stub"]["failed"] == 2
    assert (output_dir / "real-object-benchmark.json").exists()
    assert (output_dir / "real-object-comparison.png").exists()
    encoded = json.dumps(report)
    assert str(tmp_path) not in encoded


def test_loader_rejects_missing_annotation_hash_mismatch_and_split_leakage(tmp_path: Path):
    output_dir = tmp_path / "objects"
    dataset = output_dir / "extracted" / "Plant_Leaf_Segmentation"
    _write_pair(dataset, "100s", white_foreground=True)
    _write_pair(dataset, "101s", white_foreground=True)
    pairs = collect.discover_pairs(dataset)
    rows = collect.build_sample_rows(pairs, output_dir, {"source_id": "unit-source"})
    rows[1]["source_group"] = rows[0]["source_group"]
    rows[0]["split"] = "dev"
    rows[1]["split"] = "heldout"
    manifest_path = output_dir / "manifest.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"samples": rows}), encoding="utf-8")

    try:
        bench.load_samples(manifest_path)
    except ValueError as exc:
        assert "appears in both" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected source-group split leakage rejection")

    rows[1]["source_group"] = "different-group"
    rows[0]["image_sha256"] = "f" * 64
    manifest_path.write_text(json.dumps({"samples": rows}), encoding="utf-8")
    try:
        bench.load_samples(manifest_path)
    except ValueError as exc:
        assert "image SHA-256 mismatch" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected image hash rejection")

    rows[0]["image_sha256"] = collect.sha256_file(output_dir / rows[0]["image"])
    rows[0].pop("independent_annotation_origin")
    manifest_path.write_text(json.dumps({"samples": rows}), encoding="utf-8")
    try:
        bench.load_samples(manifest_path)
    except ValueError as exc:
        assert "independent_annotation_origin" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected missing annotation-origin rejection")


def test_summary_counts_failures_as_zero_in_headline_mean():
    rows = [
        {"method": "m", "split": "dev", "status": "ok", "seconds": 1.0, "mask_alignment": "same-dimensions", "metrics": {"iou": 1.0, "boundary": {"f1": 0.8}, "topology": {"components_preserved": True, "holes_preserved": True}}},
        {"method": "m", "split": "dev", "status": "error", "seconds": 0.1, "mask_alignment": "same-dimensions", "error": "boom"},
    ]

    summary = bench._summarize(rows)["m"]

    assert summary["mean_iou"] == 0.5
    assert summary["mean_iou_successful_only"] == 1.0
    assert summary["mean_boundary_f1"] == 0.4
    assert summary["by_split"]["dev"]["mean_iou"] == 0.5


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ("image_sha256", None, "image_sha256"),
        ("image_sha256", "abc", "malformed image_sha256"),
        ("reference_mask_sha256", None, "reference_mask_sha256"),
        ("reference_mask_sha256", "xyz", "malformed reference_mask_sha256"),
        ("image_size", None, "image_size"),
        ("image_size", [48, 0], "image_size"),
        ("published_mask_size", None, "published_mask_size"),
        ("published_mask_size", [96], "published_mask_size"),
        ("split", None, "split"),
        ("split", "train", "invalid split"),
        ("source_group", "", "source_group"),
        ("sample_id", "", "sample_id"),
    ],
)
def test_loader_requires_complete_manifest_integrity_fields(tmp_path: Path, field: str, bad_value, message: str):
    output_dir = tmp_path / "objects"
    dataset = output_dir / "extracted" / "Plant_Leaf_Segmentation"
    _write_pair(dataset, "100s", white_foreground=True)
    rows = collect.build_sample_rows(collect.discover_pairs(dataset), output_dir, {"source_id": "unit-source"})
    if bad_value is None:
        rows[0].pop(field)
    else:
        rows[0][field] = bad_value
    manifest_path = output_dir / "manifest.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"samples": rows}), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        bench.load_samples(manifest_path)


def test_loader_rejects_duplicate_sample_ids(tmp_path: Path):
    output_dir = tmp_path / "objects"
    dataset = output_dir / "extracted" / "Plant_Leaf_Segmentation"
    _write_pair(dataset, "100s", white_foreground=True)
    _write_pair(dataset, "200s", white_foreground=True)
    rows = collect.build_sample_rows(collect.discover_pairs(dataset), output_dir, {"source_id": "unit-source"})
    rows[1]["sample_id"] = rows[0]["sample_id"]
    manifest_path = output_dir / "manifest.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"samples": rows}), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate sample_id"):
        bench.load_samples(manifest_path)
