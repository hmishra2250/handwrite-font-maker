import shutil

import pytest

from handwrite_font_maker.pipeline import build_font


@pytest.mark.skipif(shutil.which("potrace") is None or shutil.which("fontforge") is None, reason="font tools unavailable")
def test_full_synthetic_build_outputs_valid_fonts(tmp_path, synthetic_filled_template, save_image):
    image_path = save_image(synthetic_filled_template(), tmp_path / "filled.png")
    outputs = build_font(
        image_path=image_path,
        font_name="SyntheticHand",
        family_name="Synthetic Hand",
        style_name="Regular",
        output_dir=tmp_path / "font",
    )
    assert outputs["otf"].endswith("SyntheticHand.otf")
    assert outputs["ttf"].endswith("SyntheticHand.ttf")
    assert (tmp_path / "font" / "SyntheticHand.otf").exists()
    assert (tmp_path / "font" / "SyntheticHand.ttf").exists()
    assert (tmp_path / "font" / "work" / "manifest.json").exists()
