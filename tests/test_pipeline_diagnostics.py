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
