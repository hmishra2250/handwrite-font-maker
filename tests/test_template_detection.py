from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from handwrite_font_maker.diagnostics import MarkerDetectionError
from handwrite_font_maker.extract import extract_cells
from handwrite_font_maker.rectify import rectify_template_photo
from handwrite_font_maker.template import generate_template_pdf


def test_generate_template_pdf_creates_pdf(tmp_path):
    output = generate_template_pdf(tmp_path / "template.pdf")
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")


def test_rectify_and_extract_clean_synthetic_template(tmp_path, synthetic_filled_template, save_image):
    image_path = save_image(synthetic_filled_template(), tmp_path / "filled.png")
    doc = rectify_template_photo(image_path)
    cells = extract_cells(doc.metadata, doc.geometry)
    assert doc.reprojection_error_px < 5
    assert doc.metadata.character_count == 94
    assert len(cells) == doc.metadata.character_count


def test_perspective_warp_fixture_extracts(tmp_path, synthetic_filled_template, perspective_warp, save_image):
    warped = perspective_warp(synthetic_filled_template(), tilt=0.16)
    image_path = save_image(warped, tmp_path / "warped.png")
    doc = rectify_template_photo(image_path)
    assert doc.reprojection_error_px < 5
    assert len(extract_cells(doc.metadata, doc.geometry)) == 94


def test_noise_and_brightness_fixtures_extract(tmp_path, synthetic_filled_template, save_image):
    rng = np.random.default_rng(123)
    base = np.array(synthetic_filled_template().convert("RGB")).astype(np.float32)
    noisy = np.clip(base + rng.normal(0, 15, base.shape), 0, 255).astype(np.uint8)
    bright = np.clip(base * 1.4, 0, 255).astype(np.uint8)
    dark = np.clip(base * 0.6, 0, 255).astype(np.uint8)
    for name, arr in [("noisy", noisy), ("bright", bright), ("dark", dark)]:
        path = save_image(Image.fromarray(arr), tmp_path / f"{name}.png")
        doc = rectify_template_photo(path)
        assert len(extract_cells(doc.metadata, doc.geometry)) == 94


def test_missing_marker_names_corner(tmp_path, synthetic_filled_template, save_image):
    image = synthetic_filled_template()
    # Cover the top-left marker.
    from handwrite_font_maker.layout import get_layout
    from handwrite_font_maker.schema import compute_geometry
    from PIL import ImageDraw

    geometry = compute_geometry(get_layout())
    box = geometry.marker_boxes["top_left"]
    draw = ImageDraw.Draw(image)
    draw.rectangle((box.left - 5, box.top - 5, box.right + 5, box.bottom + 5), fill=(255, 255, 255))
    path = save_image(image, tmp_path / "missing.png")
    with pytest.raises(MarkerDetectionError) as exc:
        rectify_template_photo(path)
    assert "top_left" in str(exc.value)
    assert "re-shoot" in str(exc.value)


def test_rotated_180_extracts(tmp_path, synthetic_filled_template, save_image):
    image = synthetic_filled_template().rotate(180, expand=True)
    path = save_image(image, tmp_path / "rotated.png")
    doc = rectify_template_photo(path)
    assert len(extract_cells(doc.metadata, doc.geometry)) == 94
