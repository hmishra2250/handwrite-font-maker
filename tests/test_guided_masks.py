from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from handwrite_font_maker.pipeline import _prepare_accepted_mask, _validate_mask_glyphs, build_font_from_masks


def _mask(path: Path, draw_fn) -> Path:
    image = Image.new("L", (220, 220), 255)
    draw = ImageDraw.Draw(image)
    draw_fn(draw)
    image.save(path, format="PNG")
    return path


def test_mask_v1_preserves_disconnected_dots_holes_and_horizontal_strokes(tmp_path: Path):
    mask_path = _mask(
        tmp_path / "punctuation.png",
        lambda draw: (
            draw.ellipse((40, 28, 64, 52), fill=0),
            draw.ellipse((150, 28, 174, 52), fill=0),
            draw.rectangle((35, 118, 185, 132), fill=0),
            draw.ellipse((70, 70, 150, 160), fill=0),
            draw.ellipse((94, 94, 126, 128), fill=255),
        ),
    )

    result = _prepare_accepted_mask(mask_path, 0.8)
    arr = result.bitmap.convert("L")
    pixels = arr.load()
    foreground_points = [(x, y) for y in range(arr.height) for x in range(arr.width) if pixels[x, y] < 128]

    assert result.original_width == 220
    assert result.original_height == 220
    assert result.source_height < 700  # tight bbox is scaled from full-image coordinates, not recropped to 1000 high.
    assert len(foreground_points) > 0
    # The long horizontal bar remains because guide-line cleanup is not run on accepted masks.
    assert max(sum(1 for x in range(arr.width) if pixels[x, y] < 128) for y in range(arr.height)) > 120
    # The white center of the ring remains a hole in the accepted mask crop.
    mid_x, mid_y = arr.width // 2, arr.height // 2
    assert pixels[mid_x, mid_y] >= 128


@pytest.mark.parametrize(
    "glyphs,match",
    [
        ([{"char": "A", "image_path": "missing.png", "baseline": 0.8}, {"char": "A", "image_path": "missing2.png", "baseline": 0.8}], "Duplicate"),
        ([{"char": " ", "image_path": "missing.png", "baseline": 0.8}], "printable non-space ASCII"),
        ([{"char": "é", "image_path": "missing.png", "baseline": 0.8}], "printable non-space ASCII"),
    ],
)
def test_guided_glyph_labels_are_unique_printable_nonspace_ascii(glyphs, match):
    with pytest.raises(ValueError, match=match):
        _validate_mask_glyphs(glyphs)


def test_mask_v1_rejects_blank_solid_and_invalid_baseline(tmp_path: Path):
    blank = tmp_path / "blank.png"
    Image.new("L", (32, 32), 255).save(blank, format="PNG")
    solid = tmp_path / "solid.png"
    Image.new("L", (32, 32), 0).save(solid, format="PNG")

    with pytest.raises(ValueError, match="blank"):
        _prepare_accepted_mask(blank, 0.8)
    with pytest.raises(ValueError, match="solid"):
        _prepare_accepted_mask(solid, 0.8)
    with pytest.raises(ValueError, match="strictly between 0 and 1"):
        _prepare_accepted_mask(blank, 1.0)


@pytest.mark.skipif(shutil.which("potrace") is None or shutil.which("fontforge") is None, reason="font tools unavailable")
def test_build_font_from_masks_generates_valid_partial_font(tmp_path: Path):
    a = _mask(tmp_path / "A.png", lambda draw: draw.line((38, 170, 110, 35, 182, 170), fill=0, width=18))
    o = _mask(
        tmp_path / "O.png",
        lambda draw: (draw.ellipse((45, 45, 175, 175), fill=0), draw.ellipse((82, 82, 138, 138), fill=255)),
    )
    dash = _mask(tmp_path / "dash.png", lambda draw: draw.rectangle((35, 105, 185, 123), fill=0))

    outputs = build_font_from_masks(
        glyphs=[
            {"char": "A", "image_path": a, "baseline": 0.82},
            {"char": "O", "image_path": o, "baseline": 0.78},
            {"char": "-", "image_path": dash, "baseline": 0.60},
        ],
        font_name="GuidedSmoke",
        family_name="Guided Smoke",
        style_name="Regular",
        output_dir=tmp_path / "font",
    )

    manifest = json.loads(Path(outputs["manifest"]).read_text(encoding="utf-8"))
    assert manifest["mask_format"] == "mask-v1"
    assert manifest["ascent"] == 800
    assert manifest["descent"] == 200
    assert {g["codepoint"] for g in manifest["glyphs"]} == {65, 79, 45}
    assert all(g["advance_width"] >= 280 for g in manifest["glyphs"])
    assert Path(outputs["otf"]).exists()
    assert Path(outputs["ttf"]).exists()
    assert Path(outputs["debug_overlay"]).exists()

    probe = """
import fontforge, sys
font = fontforge.open(sys.argv[1])
assert font.em == 1000 and font.ascent == 800 and font.descent == 200
assert int(font.os2_fstype) == 0
for cp in (65, 79, 45, 32):
    glyph = font[cp]
    assert glyph.width >= 260 if cp == 32 else glyph.width >= 280
for cp in (65, 79, 45):
    assert font[cp].isWorthOutputting()
assert font['.notdef'].isWorthOutputting()
font.close()
"""
    subprocess.run(["fontforge", "-lang=py", "-c", probe, outputs["ttf"]], check=True, timeout=60)
