"""End-to-end tests: synthetic image → Python API → font artifacts.

These tests exercise the full pipeline from upload through font generation,
using synthetic filled templates (clean, warped, noisy) as input.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from handwrite_font_maker.web.api import create_job, worker_once
from handwrite_font_maker.web.contracts import HardErrorCode
from handwrite_font_maker.web.job_store import JsonJobStore
from handwrite_font_maker.web.supabase_store import LocalObjectStore


def _save_to_object_store(image: Image.Image, store: LocalObjectStore, object_key: str) -> None:
    target = store.root / Path(object_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")


@pytest.fixture
def e2e_env(tmp_path):
    store_path = tmp_path / "jobs.json"
    object_root = tmp_path / "objects"
    object_root.mkdir()
    return store_path, object_root, LocalObjectStore(object_root)


@pytest.mark.skipif(
    shutil.which("potrace") is None or shutil.which("fontforge") is None,
    reason="font tools unavailable",
)
class TestE2ECleanTemplate:
    def test_clean_synthetic_produces_fonts(self, e2e_env, synthetic_filled_template):
        store_path, object_root, obj_store = e2e_env
        image = synthetic_filled_template()
        object_key = "jobs/job_e2e_clean/input/original.png"
        _save_to_object_store(image, obj_store, object_key)

        job_response = create_job(
            store_path,
            object_key=object_key,
            content_type="image/png",
            size_bytes=1024,
            font_name="E2ECleanFont",
            family_name="E2E Clean",
        )
        assert job_response["status"] == "queued"

        result = worker_once(store_path, object_root)
        assert result is not None
        assert result["status"] == "succeeded"
        assert result["stage"] == "complete"
        assert any(a["kind"] == "otf" for a in result["artifacts"])
        assert any(a["kind"] == "ttf" for a in result["artifacts"])

    def test_warped_synthetic_produces_fonts(self, e2e_env, synthetic_filled_template, perspective_warp):
        store_path, object_root, obj_store = e2e_env
        warped = perspective_warp(synthetic_filled_template(), tilt=0.14)
        object_key = "jobs/job_e2e_warped/input/original.png"
        _save_to_object_store(warped, obj_store, object_key)

        create_job(
            store_path,
            object_key=object_key,
            content_type="image/png",
            size_bytes=1024,
            font_name="E2EWarpedFont",
            family_name="E2E Warped",
        )

        result = worker_once(store_path, object_root)
        assert result is not None
        assert result["status"] == "succeeded"

    def test_noisy_synthetic_produces_fonts(self, e2e_env, synthetic_filled_template):
        store_path, object_root, obj_store = e2e_env
        rng = np.random.default_rng(42)
        base = np.array(synthetic_filled_template().convert("RGB")).astype(np.float32)
        noisy = np.clip(base + rng.normal(0, 15, base.shape), 0, 255).astype(np.uint8)
        image = Image.fromarray(noisy)
        object_key = "jobs/job_e2e_noisy/input/original.png"
        _save_to_object_store(image, obj_store, object_key)

        create_job(
            store_path,
            object_key=object_key,
            content_type="image/png",
            size_bytes=1024,
            font_name="E2ENoisyFont",
            family_name="E2E Noisy",
        )

        result = worker_once(store_path, object_root)
        assert result is not None
        assert result["status"] == "succeeded"


class TestE2EErrorCases:
    def test_missing_marker_fails_with_correct_code(self, e2e_env, synthetic_filled_template):
        store_path, object_root, obj_store = e2e_env

        from handwrite_font_maker.layout import get_layout
        from handwrite_font_maker.schema import compute_geometry
        from PIL import ImageDraw

        image = synthetic_filled_template()
        geometry = compute_geometry(get_layout())
        box = geometry.marker_boxes["top_left"]
        draw = ImageDraw.Draw(image)
        draw.rectangle((box.left - 5, box.top - 5, box.right + 5, box.bottom + 5), fill=(255, 255, 255))

        object_key = "jobs/job_e2e_missing_marker/input/original.png"
        _save_to_object_store(image, obj_store, object_key)

        create_job(
            store_path,
            object_key=object_key,
            content_type="image/png",
            size_bytes=1024,
            font_name="E2EMarkerFail",
            family_name="E2E Marker Fail",
        )

        result = worker_once(store_path, object_root)
        assert result is not None
        assert result["status"] == "failed"
        assert result["error"]["code"] == HardErrorCode.MARKER_NOT_FOUND.value

    def test_invalid_image_type_rejected_at_creation(self, e2e_env):
        store_path, _, _ = e2e_env
        with pytest.raises(ValueError, match="UNSUPPORTED_IMAGE_TYPE"):
            create_job(
                store_path,
                object_key="test.pdf",
                content_type="application/pdf",
                size_bytes=1024,
                font_name="BadFont",
                family_name="Bad",
            )

    def test_invalid_font_name_rejected_at_creation(self, e2e_env):
        store_path, _, _ = e2e_env
        with pytest.raises(ValueError, match="FONT_METADATA_INVALID"):
            create_job(
                store_path,
                object_key="test.jpg",
                content_type="image/jpeg",
                size_bytes=1024,
                font_name="bad font name",
                family_name="Bad",
            )


class TestE2EJobLifecycle:
    def test_job_transitions_through_stages(self, e2e_env, synthetic_filled_template):
        store_path, object_root, obj_store = e2e_env
        image = synthetic_filled_template()
        object_key = "jobs/job_e2e_lifecycle/input/original.png"
        _save_to_object_store(image, obj_store, object_key)

        created = create_job(
            store_path,
            object_key=object_key,
            content_type="image/png",
            size_bytes=1024,
            font_name="E2ELifecycle",
            family_name="E2E Lifecycle",
        )
        assert created["status"] == "queued"
        assert created["stage"] == "queued"
        assert created["jobId"].startswith("job_")
        assert created["retentionExpiresAt"]
        assert created["warnings"] == []
        assert created["artifacts"] == []

    def test_no_queued_job_returns_none(self, e2e_env):
        store_path, object_root, _ = e2e_env
        JsonJobStore(store_path)
        result = worker_once(store_path, object_root)
        assert result is None


@pytest.mark.skipif(
    shutil.which("potrace") is None or shutil.which("fontforge") is None,
    reason="font tools unavailable",
)
class TestE2EBrightnessVariation:
    def test_bright_image_produces_fonts(self, e2e_env, synthetic_filled_template):
        store_path, object_root, obj_store = e2e_env
        base = np.array(synthetic_filled_template().convert("RGB")).astype(np.float32)
        bright = np.clip(base * 1.4, 0, 255).astype(np.uint8)
        object_key = "jobs/job_e2e_bright/input/original.png"
        _save_to_object_store(Image.fromarray(bright), obj_store, object_key)

        create_job(store_path, object_key=object_key, content_type="image/png", size_bytes=1024, font_name="E2EBright", family_name="E2E Bright")
        result = worker_once(store_path, object_root)
        assert result is not None
        assert result["status"] == "succeeded"

    def test_dark_image_produces_fonts(self, e2e_env, synthetic_filled_template):
        store_path, object_root, obj_store = e2e_env
        base = np.array(synthetic_filled_template().convert("RGB")).astype(np.float32)
        dark = np.clip(base * 0.6, 0, 255).astype(np.uint8)
        object_key = "jobs/job_e2e_dark/input/original.png"
        _save_to_object_store(Image.fromarray(dark), obj_store, object_key)

        create_job(store_path, object_key=object_key, content_type="image/png", size_bytes=1024, font_name="E2EDark", family_name="E2E Dark")
        result = worker_once(store_path, object_root)
        assert result is not None
        assert result["status"] == "succeeded"


@pytest.mark.skipif(
    shutil.which("potrace") is None or shutil.which("fontforge") is None,
    reason="font tools unavailable",
)
class TestE2ECombinedDistortions:
    """Simulate realistic phone captures with multiple simultaneous distortions."""

    def test_warped_plus_noisy_produces_fonts(self, e2e_env, synthetic_filled_template, perspective_warp):
        store_path, object_root, obj_store = e2e_env
        rng = np.random.default_rng(99)
        warped = perspective_warp(synthetic_filled_template(), tilt=0.10)
        arr = np.array(warped.convert("RGB")).astype(np.float32)
        noisy = np.clip(arr + rng.normal(0, 12, arr.shape), 0, 255).astype(np.uint8)
        object_key = "jobs/job_e2e_warp_noise/input/original.png"
        _save_to_object_store(Image.fromarray(noisy), obj_store, object_key)

        create_job(store_path, object_key=object_key, content_type="image/png", size_bytes=1024, font_name="E2EWarpNoise", family_name="E2E Warp Noise")
        result = worker_once(store_path, object_root)
        assert result is not None
        assert result["status"] == "succeeded"
        assert any(a["kind"] == "otf" for a in result["artifacts"])

    def test_warped_dark_noisy_produces_fonts(self, e2e_env, synthetic_filled_template, perspective_warp):
        store_path, object_root, obj_store = e2e_env
        rng = np.random.default_rng(77)
        warped = perspective_warp(synthetic_filled_template(), tilt=0.08)
        arr = np.array(warped.convert("RGB")).astype(np.float32)
        darkened = np.clip(arr * 0.7 + rng.normal(0, 8, arr.shape), 0, 255).astype(np.uint8)
        object_key = "jobs/job_e2e_warp_dark_noise/input/original.png"
        _save_to_object_store(Image.fromarray(darkened), obj_store, object_key)

        create_job(store_path, object_key=object_key, content_type="image/png", size_bytes=1024, font_name="E2EWarpDarkNoise", family_name="E2E Combined")
        result = worker_once(store_path, object_root)
        assert result is not None
        assert result["status"] == "succeeded"
