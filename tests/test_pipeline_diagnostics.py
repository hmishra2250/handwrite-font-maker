from PIL import Image
import numpy as np

from handwrite_font_maker.layout import get_layout
from handwrite_font_maker.pipeline import _prepare_bitmap
from handwrite_font_maker.schema import Rect


def test_empty_glyph_warns_without_crashing():
    gray = np.full((120, 120), 255, dtype=np.uint8)
    result = _prepare_bitmap(gray, Rect(0, 0, 119, 119), 4, 4, get_layout().guide_rows)
    assert result.empty
    assert "likely-empty" in result.warnings


def test_legacy_grid_functions_are_deleted():
    import handwrite_font_maker.pipeline as pipeline

    assert not hasattr(pipeline, "_detect_grid_runs")
    assert not hasattr(pipeline, "_pair_runs")


def test_template_bitmap_preserves_real_horizontal_ascii_strokes():
    from PIL import ImageDraw
    from handwrite_font_maker.schema import Rect

    for char, draw_stroke in {
        "-": lambda draw: draw.rectangle((22, 58, 98, 66), fill=0),
        "_": lambda draw: draw.rectangle((22, 90, 98, 98), fill=0),
        "=": lambda draw: (draw.rectangle((24, 48, 96, 55), fill=0), draw.rectangle((24, 72, 96, 79), fill=0)),
        "A": lambda draw: (draw.line((24, 96, 60, 20, 96, 96), fill=0, width=7), draw.line((42, 64, 78, 64), fill=0, width=6)),
    }.items():
        image = Image.new("L", (120, 120), 255)
        draw = ImageDraw.Draw(image)
        draw_stroke(draw)
        result = _prepare_bitmap(np.array(image), Rect(0, 0, 119, 119), 4, 4, ())
        assert not result.empty, char
        assert result.bitmap.width > 30, char
        assert result.coverage > 0.002, char


def test_template_bitmap_crop_preserves_descender_zone():
    from PIL import ImageDraw
    from handwrite_font_maker.schema import Rect

    image = Image.new("L", (120, 120), 255)
    draw = ImageDraw.Draw(image)
    draw.line((62, 40, 62, 113), fill=0, width=8)
    result = _prepare_bitmap(np.array(image), Rect(0, 0, 119, 119), 4, 22, (), margin_bottom_y=6)
    assert not result.empty
    assert result.bitmap.height > 65


def test_blank_template_guides_do_not_become_glyph_ink():
    from handwrite_font_maker.schema import compute_geometry
    from handwrite_font_maker.template import render_template_image

    layout = get_layout()
    geometry = compute_geometry(layout)
    cell = geometry.cell_rects[0]
    margin_x = int(round(cell.width * layout.inner_margin_x))
    margin_y = int(round(cell.height * layout.inner_margin_y))
    image = render_template_image(layout=layout, include_markers=False).convert("L")

    result = _prepare_bitmap(np.array(image), cell, margin_x, margin_y, layout.guide_rows)

    assert result.empty
    assert result.coverage < 0.002


def test_dark_template_stroke_crossing_guide_is_preserved():
    from PIL import ImageDraw
    from handwrite_font_maker.schema import compute_geometry
    from handwrite_font_maker.template import render_template_image

    layout = get_layout()
    geometry = compute_geometry(layout)
    cell = geometry.cell_rects[0]
    margin_x = int(round(cell.width * layout.inner_margin_x))
    margin_y = int(round(cell.height * layout.inner_margin_y))
    image = render_template_image(layout=layout, include_markers=False).convert("L")
    draw = ImageDraw.Draw(image)
    inner_top = cell.top + margin_y
    inner_bottom = cell.bottom - int(round(cell.height * 0.05))
    baseline_y = int(round(inner_top + ((inner_bottom - inner_top) * layout.guide_rows[-2])))
    draw.rectangle((cell.left + margin_x + 20, baseline_y - 5, cell.right - margin_x - 20, baseline_y + 5), fill=0)

    result = _prepare_bitmap(np.array(image), cell, margin_x, margin_y, layout.guide_rows)

    assert not result.empty
    assert result.bitmap.width > 100
