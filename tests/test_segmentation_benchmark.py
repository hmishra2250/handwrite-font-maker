from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
from PIL import Image

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_segmentation.py"
spec = importlib.util.spec_from_file_location("benchmark_segmentation", MODULE_PATH)
benchmark_segmentation = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = benchmark_segmentation
spec.loader.exec_module(benchmark_segmentation)


def test_synthetic_fixture_corpus_covers_glyph_failure_modes():
    fixtures = benchmark_segmentation.synthetic_fixtures()
    names = {fixture.name for fixture in fixtures}
    assert names == {
        "thin_strokes",
        "ring_hole",
        "detached_dot_leaves",
        "low_contrast_clutter",
        "source_detail_veins",
    }
    for fixture in fixtures:
        assert fixture.image_bgr.dtype == np.uint8
        assert fixture.image_bgr.ndim == 3
        assert fixture.image_bgr.shape[:2] == fixture.reference_mask.shape
        assert set(np.unique(fixture.reference_mask)).issubset({0, 255})
        assert all(0 <= value <= 1 for value in fixture.rectangle)
        assert fixture.rectangle[0] < fixture.rectangle[2]
        assert fixture.rectangle[1] < fixture.rectangle[3]
        assert any(point["label"] == 1 for point in fixture.prompt_points)
        assert all(0 <= point["x"] <= 1 and 0 <= point["y"] <= 1 for point in fixture.prompt_points)
        assert all(point["label"] in (0, 1) for point in fixture.prompt_points)

    topologies = {fixture.name: benchmark_segmentation._topology(fixture.reference_mask) for fixture in fixtures}
    assert topologies["ring_hole"]["holes"] == 1
    assert topologies["detached_dot_leaves"]["components"] >= 2
    assert topologies["source_detail_veins"]["components"] >= 2


def test_metrics_include_overlap_boundary_topology_and_mask_convention():
    reference = np.full((32, 32), 255, np.uint8)
    reference[8:24, 8:24] = 0
    predicted = reference.copy()
    predicted[8:12, 8:12] = 255

    metrics = benchmark_segmentation.segmentation_metrics(predicted, reference)

    assert 0 < metrics["iou"] < 1
    assert set(metrics["boundary"]) == {"precision", "recall", "f1"}
    assert metrics["foreground_pixels"]["reference"] == 16 * 16
    assert metrics["false_negative_pixels"] == 4 * 4
    assert metrics["topology"]["reference"] == {"components": 1, "holes": 0}
    assert metrics["topology"]["predicted"]["components"] == 1


def test_benchmark_runner_writes_json_png_and_uses_normalized_rectangles(tmp_path):
    seen_rectangles = []

    def perfect_runner(image_bgr, rectangle):
        assert image_bgr.dtype == np.uint8
        assert image_bgr.ndim == 3
        assert len(rectangle) == 4
        assert all(0 <= value <= 1 for value in rectangle)
        seen_rectangles.append(tuple(rectangle))
        # The test runner intentionally uses the public fixture corpus order to
        # model how an ML adapter can be plugged in without touching the harness.
        fixture = benchmark_segmentation.synthetic_fixtures()[len(seen_rectangles) - 1]
        return fixture.reference_mask.copy()

    report = benchmark_segmentation.run_benchmark(
        tmp_path,
        segmenters={"perfect_ml_stub": perfect_runner},
        include_real_probe=False,
    )

    assert report["mask_convention"].startswith("uint8 grayscale mask: 0/black = foreground")
    assert "Callable" in report["segmenter_contract"]
    assert report["summary"]["perfect_ml_stub"]["mean_iou"] == 1.0
    assert report["summary"]["perfect_ml_stub"]["topology_exact_count"] == 5
    assert len(seen_rectangles) == 5
    assert (tmp_path / "benchmark-report.json").exists()
    assert (tmp_path / "comparison.png").exists()
    assert Image.open(tmp_path / "comparison.png").size[0] > 100
    assert not any(str(tmp_path) in str(value) for value in report["artifacts"].values())
