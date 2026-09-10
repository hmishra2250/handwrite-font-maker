import cv2
import numpy as np
import pytest

from handwrite_font_maker.foreground import extract_foreground


def test_object_cutout_preserves_hole_and_disconnected_parts():
    source = np.full((200, 240, 3), (210, 225, 235), np.uint8)
    cv2.circle(source, (130, 110), 50, (50, 110, 30), -1)
    cv2.circle(source, (130, 110), 22, (210, 225, 235), -1)
    cv2.circle(source, (55, 40), 10, (50, 110, 30), -1)
    mask = extract_foreground(source, [0.1, 0.1, 0.85, 0.9])
    assert mask.shape == source.shape[:2]
    assert mask.dtype == np.uint8
    assert set(np.unique(mask)) == {0, 255}
    assert mask[110, 130] == 255  # hole, not filled
    assert mask[110, 170] == 0
    assert mask[40, 55] == 0  # dot, not largest-component-only
    assert mask[0, 0] == 255


@pytest.mark.parametrize("rectangle", [None, [], [0, 0, 1, 1], [0.2, 0.2, 0.2, 0.8], [0, 0, float('nan'), 0.8], [False, 0, 0.8, 0.8], [-0.1, 0, 0.8, 0.8]])
def test_invalid_rectangle_rejected(rectangle):
    with pytest.raises(ValueError):
        extract_foreground(np.zeros((50, 50, 3), np.uint8), rectangle)


def test_blank_result_is_not_silently_accepted():
    with pytest.raises(ValueError, match="No foreground"):
        extract_foreground(np.full((60, 60, 3), 255, np.uint8), [0.1, 0.1, 0.9, 0.9])


def test_output_is_bounded_and_not_cropped():
    source = np.full((1200, 1600, 3), 230, np.uint8)
    cv2.rectangle(source, (600, 450), (1000, 750), (40, 90, 20), -1)
    result = extract_foreground(source, [0.2, 0.2, 0.8, 0.8])
    assert result.shape == (768, 1024)
    assert result[384, 512] == 0


def test_extreme_aspect_ratio_is_not_stretched():
    with pytest.raises(ValueError, match="too narrow"):
        extract_foreground(np.zeros((8, 2048, 3), np.uint8), [0.1, 0.1, 0.9, 0.9])
