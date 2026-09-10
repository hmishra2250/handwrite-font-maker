from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "experiment_river_extraction.py"
spec = importlib.util.spec_from_file_location("experiment_river_extraction", SCRIPT)
river = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = river
spec.loader.exec_module(river)


def _synthetic_river(path: Path) -> None:
    image = Image.new("RGB", (96, 72), (175, 145, 95))
    draw = ImageDraw.Draw(image)
    draw.line([(5, 54), (30, 38), (58, 42), (90, 22)], fill=(28, 88, 130), width=7)
    draw.line([(0, 18), (96, 18)], fill=(110, 95, 70), width=3)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_seeded_color_uses_keep_and_exclude_seeds_without_full_crop_blob():
    image = np.full((72, 96, 3), (95, 145, 175), np.uint8)  # BGR tan
    image[38:45, 15:80] = (130, 88, 28)  # BGR blue river-ish channel
    image[10:20, 0:96] = (70, 95, 110)  # BGR bank/background clutter
    points = ({"x": 0.45, "y": 0.58, "label": 1}, {"x": 0.5, "y": 0.2, "label": 0})

    mask = river.seeded_color_mask(
        image,
        (0.0, 0.0, 1.0, 1.0),
        points,
        {"lab_tolerance": 18, "exclude_margin": -2, "close": 0, "open": 0, "min_area": 10, "keep_seed_radius": 3},
    )
    diag = river.diagnostics(mask, points)

    assert set(np.unique(mask)).issubset({0, 255})
    assert mask[41, 40] == 0
    assert mask[15, 40] == 255
    assert 0.01 < diag["coverage"] < 0.2
    assert diag["keep_seed_hits"] == 1


def test_seeded_grabcut_returns_black_foreground_and_hits_keep_seed():
    image = np.full((80, 100, 3), (80, 130, 180), np.uint8)
    image[30:50, 10:90] = (120, 60, 20)
    points = ({"x": 0.5, "y": 0.5, "label": 1}, {"x": 0.5, "y": 0.12, "label": 0})

    mask = river.seeded_grabcut_mask(image, (0.05, 0.2, 0.95, 0.75), points, {"keep_seed_radius": 4, "min_area": 20, "grabcut_iters": 1})

    assert mask.shape == image.shape[:2]
    assert set(np.unique(mask)).issubset({0, 255})
    assert river.diagnostics(mask, points)["keep_seed_hits"] == 1


def test_run_experiment_records_sources_failures_and_portable_artifacts(tmp_path: Path):
    image_dir = tmp_path / "images"
    filename = "river.jpg"
    _synthetic_river(image_dir / filename)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "images": [{
            "id": "unit-river",
            "local_file": {"path": str(image_dir / filename), "sha256": river._sha256(image_dir / filename)},
            "license": {"short_name": "unit"},
            "origin_page": "https://example.test/river",
            "credit_line": "unit",
        }]
    }), encoding="utf-8")
    case = river.RiverCase(
        case_id="unit_case",
        glyph="S",
        source_id="unit-river",
        filename=filename,
        rectangle=(0.0, 0.0, 1.0, 1.0),
        points=({"x": 0.45, "y": 0.58, "label": 1}, {"x": 0.5, "y": 0.2, "label": 0}),
        params={"lab_tolerance": 24, "exclude_margin": -2, "close": 0, "open": 0, "min_area": 8, "keep_seed_radius": 3},
        review_label="accepted_candidate",
        review_rationale="unit",
    )

    def ok(image_bgr, rectangle, points, params):
        return river.seeded_color_mask(image_bgr, rectangle, points, params)

    def failing(*_args):
        raise RuntimeError("intentional")

    report = river.run_experiment(
        output_dir=tmp_path / "out",
        image_dir=image_dir,
        manifest_path=manifest,
        cases=(case,),
        methods={"ok": ok, "failing": failing},
        build_font=False,
    )

    row = report["cases"][0]
    assert report["scope"].startswith("Real satellite image experiment")
    assert report["source_verification"]["sources"][0]["status"] == "ok"
    assert row["methods"]["ok"]["status"] == "ok"
    assert row["methods"]["failing"]["status"] == "error"
    assert (tmp_path / "out" / "river-experiment-report.json").exists()
    assert (tmp_path / "out" / "river-contact-sheet.png").exists()
    assert str(tmp_path) not in json.dumps(report)


def test_verify_sources_fails_closed_on_missing_sha_license_or_origin(tmp_path: Path):
    image_dir = tmp_path / "images"
    filename = "river.jpg"
    _synthetic_river(image_dir / filename)
    base = {
        "id": "unit-river",
        "local_file": {"path": str(image_dir / filename), "sha256": river._sha256(image_dir / filename)},
        "license": {"short_name": "unit"},
        "origin_page": "https://example.test/river",
        "credit_line": "unit",
    }
    case = river.RiverCase(
        case_id="unit_case",
        glyph="S",
        source_id="unit-river",
        filename=filename,
        rectangle=(0.0, 0.0, 1.0, 1.0),
        points=({"x": 0.45, "y": 0.58, "label": 1},),
        params={},
        review_label="candidate_needs_human_review",
        review_rationale="unit",
    )
    for mutate, expected_status in (
        (lambda row: row["local_file"].pop("sha256"), "missing-source-sha256"),
        (lambda row: row.pop("license"), "missing-source-license"),
        (lambda row: row.pop("origin_page"), "missing-source-origin"),
    ):
        row = json.loads(json.dumps(base))
        mutate(row)
        manifest = tmp_path / f"{expected_status}.json"
        manifest.write_text(json.dumps({"images": [row]}), encoding="utf-8")
        verification = river.verify_sources((case,), manifest, image_dir)
        assert verification["sources"][0]["status"] == expected_status
        assert verification["verified_case_ids"] == []


def test_run_experiment_does_not_score_unverified_sources(tmp_path: Path):
    image_dir = tmp_path / "images"
    filename = "river.jpg"
    _synthetic_river(image_dir / filename)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "images": [{
            "id": "unit-river",
            "local_file": {"path": str(image_dir / filename)},
            "license": {"short_name": "unit"},
            "origin_page": "https://example.test/river",
        }]
    }), encoding="utf-8")
    case = river.RiverCase(
        case_id="unit_case",
        glyph="S",
        source_id="unit-river",
        filename=filename,
        rectangle=(0.0, 0.0, 1.0, 1.0),
        points=({"x": 0.45, "y": 0.58, "label": 1},),
        params={},
        review_label="candidate_needs_human_review",
        review_rationale="unit",
    )

    def should_not_run(*_args):
        raise AssertionError("unverified source should not be scored")

    report = river.run_experiment(
        output_dir=tmp_path / "out",
        image_dir=image_dir,
        manifest_path=manifest,
        cases=(case,),
        methods={"should-not-run": should_not_run},
        build_font=False,
    )

    assert report["cases"][0]["status"] == "source-unverified"
    assert report["cases"][0]["methods"] == {}


def test_selection_requires_explicit_visual_acceptance_label():
    row = {"status": "ok", "diagnostics": {"warnings": [], "coverage": 0.1, "keep_seed_hits": 1, "keep_seed_total": 1}}
    case = river.RiverCase(
        case_id="candidate",
        glyph="S",
        source_id="source",
        filename="x.jpg",
        rectangle=(0, 0, 1, 1),
        points=({"x": 0.5, "y": 0.5, "label": 1},),
        params={},
        review_label="candidate_needs_human_review",
        review_rationale="unit",
    )
    assert river._select(case, {"seeded-grabcut": row})[0] is None

    accepted = river.RiverCase(**{**case.__dict__, "review_label": "accepted_for_font_visual_reviewed"})
    assert river._select(accepted, {"seeded-grabcut": row})[0] == "seeded-grabcut"
