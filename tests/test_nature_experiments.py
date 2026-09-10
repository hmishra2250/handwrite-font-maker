from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "experiment_nature_fonts.py"
spec = importlib.util.spec_from_file_location("experiment_nature_fonts", MODULE_PATH)
nature = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = nature
spec.loader.exec_module(nature)


def _source(path: Path) -> None:
    image = Image.new("RGB", (80, 64), (210, 225, 235))
    draw = ImageDraw.Draw(image)
    draw.ellipse((20, 16, 58, 48), fill=(35, 105, 55))
    image.save(path)


def test_case_metadata_validates_normalized_rectangles_and_points():
    for case in nature.DEFAULT_CASES:
        nature._validate_rectangle(case.rectangle)
        nature._validate_points(case.points, case.rectangle)
        assert len(case.glyph) == 1
        assert case.review_label
        assert case.preferred_methods


def test_mask_diagnostics_preserve_black_foreground_polarity():
    mask = np.full((20, 24), 255, np.uint8)
    mask[4:12, 5:10] = 0
    mask[14:17, 15:19] = 0

    diagnostics = nature.mask_diagnostics(mask)

    assert diagnostics["foreground_pixels"] == 8 * 5 + 3 * 4
    assert diagnostics["topology"]["components"] == 2
    assert diagnostics["coverage"] < 0.2
    assert diagnostics["warnings"] == []


def test_run_experiment_records_method_errors_and_portable_artifacts(tmp_path: Path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    filename = "leaf.jpg"
    _source(image_dir / filename)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sources": [{"filename": filename, "license": "test"}]}), encoding="utf-8")
    case = nature.NatureCase(
        case_id="leaf_test",
        glyph="L",
        glyph_idea="test leaf",
        filename=filename,
        rectangle=(0.1, 0.1, 0.9, 0.9),
        points=({"x": 0.5, "y": 0.5, "label": 1}, {"x": 0.15, "y": 0.15, "label": 0}),
        preferred_methods=("ok", "fails"),
        review_label="accepted_for_font",
        review_rationale="unit fixture",
    )

    def ok_runner(image_bgr, rectangle, points, color_strategy):
        assert image_bgr.dtype == np.uint8
        assert rectangle == case.rectangle
        assert points[0]["label"] == 1
        assert color_strategy is None
        mask = np.full(image_bgr.shape[:2], 255, np.uint8)
        mask[10:30, 20:45] = 0
        return mask

    def failing_runner(*_args):
        raise RuntimeError("intentional failure")

    report = nature.run_experiment(
        output_dir=tmp_path / "out",
        image_dir=image_dir,
        manifest_path=manifest,
        cases=(case,),
        methods={"ok": ok_runner, "fails": failing_runner},
        build_font=False,
    )

    row = report["cases"][0]
    assert report["mask_convention"].startswith("uint8 grayscale mask: 0/black")
    assert report["source_manifest"]["status"] == "loaded"
    assert row["methods"]["ok"]["status"] == "ok"
    assert row["methods"]["fails"]["status"] == "error"
    assert row["selected_method"] == "ok"
    assert report["font_scope"].startswith("Ornament/symbol font")
    assert (tmp_path / "out" / "nature-experiment-report.json").exists()
    assert (tmp_path / "out" / "contact-sheet.png").exists()
    assert (tmp_path / "out" / row["artifacts"]["standalone_selected_png"]).exists()
    assert (tmp_path / "out" / row["artifacts"]["standalone_selected_svg"]).read_text(encoding="utf-8").startswith("<svg")
    encoded = json.dumps(report)
    assert str(tmp_path) not in encoded


def test_nature_decoder_matches_production_alpha_compositing(tmp_path):
    from handwrite_font_maker.rectify import load_bgr
    image = Image.new('RGBA', (20, 20), (0, 0, 0, 0))
    image.putpixel((10, 10), (30, 80, 10, 128))
    path = tmp_path / 'transparent-leaf.png'
    image.save(path)
    assert np.array_equal(nature._load_bgr(path), load_bgr(path))
    assert np.all(nature._load_bgr(path)[0, 0] == 255)
