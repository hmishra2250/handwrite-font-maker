from handwrite_font_maker.layout import DEFAULT_LAYOUT, get_layout, glyph_slug
from handwrite_font_maker.metadata import decode_metadata, encode_metadata, metadata_for_layout
from handwrite_font_maker.schema import compute_geometry, page_points


def test_default_layout_is_expanded_unique_and_slugged():
    layout = get_layout()
    assert len(layout.chars) == 94
    assert len(set(layout.chars)) == len(layout.chars)
    for char in "{}@#$~^_`":
        assert char in layout.chars
        assert glyph_slug(char)
    assert glyph_slug("{") == "braceleft"
    assert glyph_slug("}") == "braceright"
    assert glyph_slug("@") == "at"
    assert glyph_slug("#") == "numbersign"
    assert glyph_slug("$") == "dollar"
    assert glyph_slug("~") == "asciitilde"
    assert glyph_slug("^") == "asciicircum"
    assert glyph_slug("_") == "underscore"
    assert glyph_slug("`") == "grave"


def test_metadata_round_trip_preserves_character_map_order():
    layout = get_layout()
    payload = encode_metadata(metadata_for_layout(layout))
    decoded = decode_metadata(payload)
    assert decoded.layout_id == layout.layout_id
    assert decoded.chars == layout.chars
    assert decoded.marker_ids == layout.marker_roles


def test_template_geometry_has_one_cell_per_character_and_valid_guides():
    layout = get_layout()
    geometry = compute_geometry(layout)
    assert len(geometry.cell_rects) == len(layout.chars)
    assert geometry.page_width > 0
    assert geometry.page_height > 0
    for cell in geometry.cell_rects:
        assert cell.width > 20
        assert cell.height > 20
    assert page_points("A4")[0] > 500
