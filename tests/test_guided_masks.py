from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
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
        ([{"char": "A", "image_path": "missing.png", "baseline": 0.8, "scale": 0.49}], "scale"),
        ([{"char": "A", "image_path": "missing.png", "baseline": 0.8, "spacing": 0.26}], "spacing"),
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
    pipe = _mask(tmp_path / "pipe.png", lambda draw: draw.rectangle((100, 35, 120, 185), fill=0))
    backtick = _mask(tmp_path / "backtick.png", lambda draw: draw.line((88, 45, 128, 78), fill=0, width=16))

    outputs = build_font_from_masks(
        glyphs=[
            {"char": "A", "image_path": a, "baseline": 0.82},
            {"char": "O", "image_path": o, "baseline": 0.78},
            {"char": "-", "image_path": dash, "baseline": 0.60},
            {"char": "|", "image_path": pipe, "baseline": 0.80},
            {"char": "`", "image_path": backtick, "baseline": 0.80},
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
    assert {g["codepoint"] for g in manifest["glyphs"]} == {65, 79, 45, 124, 96}
    assert all(g["advance_width"] >= 280 for g in manifest["glyphs"])
    assert Path(outputs["otf"]).exists()
    assert Path(outputs["ttf"]).exists()
    assert Path(outputs["download_bundle"]).exists()
    assert Path(outputs["debug_overlay"]).exists()

    with zipfile.ZipFile(outputs["download_bundle"]) as bundle:
        assert bundle.namelist() == [
            "README.md",
            "CHARACTER_MAP.md",
            "fonts/GuidedSmoke.ttf",
            "fonts/GuidedSmoke.otf",
        ]
        readme = bundle.read("README.md").decode("utf-8")
        charmap = bundle.read("CHARACTER_MAP.md").decode("utf-8")
    assert str(tmp_path) not in readme
    assert str(tmp_path) not in charmap
    assert "automatic OS install" in readme
    assert "Office compatibility testing" in readme
    assert "depend on your rights to the input glyph images" in readme
    assert "does not automatically license your output" in readme
    assert "`U+0041`" in charmap
    assert "&#124;" in charmap
    assert "&#96;" in charmap

    probe = """
import fontforge, sys
font = fontforge.open(sys.argv[1])
assert font.em == 1000 and font.ascent == 800 and font.descent == 200
assert int(font.os2_fstype) == 0
for cp in (65, 79, 45, 124, 96, 32):
    glyph = font[cp]
    assert glyph.width >= 260 if cp == 32 else glyph.width >= 280
for cp in (65, 79, 45, 124, 96):
    assert font[cp].isWorthOutputting()
assert font['.notdef'].isWorthOutputting()
font.close()
"""
    subprocess.run(["fontforge", "-lang=py", "-c", probe, outputs["ttf"]], check=True, timeout=60)


@pytest.mark.skipif(shutil.which("potrace") is None or shutil.which("fontforge") is None, reason="font tools unavailable")
def test_guided_mask_vectorization_preserves_tiny_accepted_details(tmp_path: Path):
    detailed = _mask(
        tmp_path / "A.png",
        lambda draw: (
            draw.rectangle((50, 50, 170, 170), fill=0),
            draw.rectangle((108, 108, 109, 109), fill=255),
            draw.rectangle((185, 55, 186, 56), fill=0),
        ),
    )

    outputs = build_font_from_masks(
        glyphs=[{"char": "A", "image_path": detailed, "baseline": 0.80}],
        font_name="GuidedDetails",
        family_name="Guided Details",
        style_name="Regular",
        output_dir=tmp_path / "font",
    )

    probe = """
import json, fontforge, sys
font = fontforge.open(sys.argv[1])
glyph = font[65]
contours = []
for contour in glyph.foreground:
    xs = [point.x for point in contour]
    ys = [point.y for point in contour]
    contours.append([min(xs), min(ys), max(xs), max(ys), len(contour)])
font.close()
print(json.dumps(contours))
"""
    completed = subprocess.run(["fontforge", "-lang=py", "-c", probe, outputs["ttf"]], check=True, timeout=60, text=True, capture_output=True)
    contours = json.loads(completed.stdout)
    tiny_contours = [row for row in contours if (row[2] - row[0]) <= 16 and (row[3] - row[1]) <= 16]

    assert len(contours) >= 3, contours
    assert len(tiny_contours) >= 2, contours


@pytest.mark.skipif(shutil.which("potrace") is None or shutil.which("fontforge") is None, reason="font tools unavailable")
def test_guided_scale_and_spacing_change_real_ttf_metrics_and_manifest(tmp_path: Path):
    def draw_stem(draw):
        draw.rectangle((82, 28, 138, 190), fill=0)

    default = _mask(tmp_path / "A.png", draw_stem)
    adjusted = _mask(tmp_path / "B.png", draw_stem)

    outputs = build_font_from_masks(
        glyphs=[
            {"char": "A", "image_path": default, "baseline": 0.80},
            {"char": "B", "image_path": adjusted, "baseline": 0.80, "scale": 1.5, "spacing": 0.25},
        ],
        font_name="GuidedMetrics",
        family_name="Guided Metrics",
        style_name="Regular",
        output_dir=tmp_path / "font",
    )

    manifest = json.loads(Path(outputs["manifest"]).read_text(encoding="utf-8"))
    rows = {row["char"]: row for row in manifest["glyphs"]}

    assert rows["A"]["scale"] == 1.0
    assert rows["A"]["spacing"] == 0.0
    assert rows["B"]["scale"] == 1.5
    assert rows["B"]["spacing"] == 0.25
    assert rows["B"]["source_width"] > rows["A"]["source_width"]
    assert rows["B"]["source_height"] > rows["A"]["source_height"]
    assert rows["B"]["advance_width"] == max(280, int(rows["B"]["source_width"]) + 160 + 250)
    assert int(rows["B"]["top_offset"]) < int(rows["A"]["top_offset"])
    assert abs((800 - int(rows["B"]["top_offset"])) - round((800 - int(rows["A"]["top_offset"])) * 1.5)) <= 1

    probe = """
import json, fontforge, sys
font = fontforge.open(sys.argv[1])
rows = {}
for cp in (65, 66):
    glyph = font[cp]
    bbox = glyph.boundingBox()
    rows[chr(cp)] = {'width': glyph.width, 'bbox': [int(v) for v in bbox]}
font.close()
print(json.dumps(rows, sort_keys=True))
"""
    completed = subprocess.run(["fontforge", "-lang=py", "-c", probe, outputs["ttf"]], check=True, timeout=60, text=True, capture_output=True)
    metrics = json.loads(completed.stdout)

    assert metrics["A"]["width"] == rows["A"]["advance_width"]
    assert metrics["B"]["width"] == rows["B"]["advance_width"]
    assert metrics["B"]["width"] > metrics["A"]["width"]
    assert (metrics["B"]["bbox"][3] - metrics["B"]["bbox"][1]) > (metrics["A"]["bbox"][3] - metrics["A"]["bbox"][1])
    assert abs(metrics["B"]["bbox"][3] - (800 - rows["B"]["top_offset"])) <= 2
