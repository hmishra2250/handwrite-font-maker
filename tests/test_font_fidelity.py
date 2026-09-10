import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_font_fidelity import normalize_shape
from benchmark_segmentation import _topology


def test_fidelity_normalization_preserves_aspect_ratio_hole_and_dot():
    source = np.full((100, 80), 255, np.uint8)
    source[30:90, 10:50] = 0
    source[40:80, 20:40] = 255
    source[10:15, 25:30] = 0
    normalized = normalize_shape(source)
    assert normalized.shape == (512, 512)
    assert _topology(normalized) == _topology(source)
    ys, xs = np.where(normalized < 128)
    assert (xs.max()-xs.min()+1)/(ys.max()-ys.min()+1) == pytest.approx(.5, abs=.005)


def test_fidelity_normalization_rejects_blank():
    with pytest.raises(ValueError, match='empty'):
        normalize_shape(np.full((20, 20), 255, np.uint8))
