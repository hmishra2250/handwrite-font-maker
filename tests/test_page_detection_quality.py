from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from handwrite_font_maker.rectify import detect_page_corners
from handwrite_font_maker.template import render_template_image


def _bgr(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("RGB"))[:, :, ::-1].copy()


def _page_on_desk(
    *,
    canvas_size: tuple[int, int] = (1100, 1300),
    background: tuple[int, int, int] = (196, 194, 188),
) -> tuple[Image.Image, np.ndarray]:
    import cv2

    page = render_template_image(include_markers=False, dpi=72).convert("RGB").resize((600, 848))
    src = np.float32([[0, 0], [page.width - 1, 0], [page.width - 1, page.height - 1], [0, page.height - 1]])
    dst = np.float32([[230, 120], [850, 170], [800, 1120], [160, 1040]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    canvas = np.full((canvas_size[1], canvas_size[0], 3), background, dtype=np.uint8)
    mask = cv2.warpPerspective(np.full((page.height, page.width), 255, dtype=np.uint8), matrix, canvas_size)
    shadow = cv2.GaussianBlur(mask, (0, 0), 12)
    canvas[shadow > 20] = (np.array(background) * 0.75).astype(np.uint8)
    warped = cv2.warpPerspective(np.array(page), matrix, canvas_size, borderValue=background)
    canvas[mask > 0] = warped[mask > 0]
    return Image.fromarray(canvas), dst


def test_detect_page_corners_accepts_low_contrast_shadowed_page():
    image, expected = _page_on_desk()

    detected = detect_page_corners(_bgr(image))

    assert detected.shape == (4, 2)
    assert float(np.max(np.linalg.norm(detected - expected, axis=1))) < 18.0


def test_detect_page_corners_rejects_curved_non_page_distractor():
    image = Image.new("RGB", (1000, 1300), (70, 75, 80))
    draw = ImageDraw.Draw(image)
    draw.ellipse((210, 120, 790, 1180), fill=(245, 245, 240))

    with pytest.raises(ValueError):
        detect_page_corners(_bgr(image))


@pytest.mark.parametrize("occluder", [("top-left", (200, 80, 460, 420)), ("right-edge", (650, 0, 999, 1299))])
def test_detect_page_corners_rejects_clipped_or_absent_full_page(occluder):
    _name, box = occluder
    image = Image.new("RGB", (1000, 1300), (80, 80, 80))
    draw = ImageDraw.Draw(image)
    draw.polygon([(220, 120), (780, 140), (760, 1140), (220, 1120)], fill=(245, 245, 245))
    draw.rectangle(box, fill=(80, 80, 80))

    with pytest.raises(ValueError):
        detect_page_corners(_bgr(image))


def test_detect_page_corners_rejects_two_similarly_plausible_pages():
    page = render_template_image(include_markers=False, dpi=72).convert("RGB").resize((500, 707))
    image = Image.new("RGB", (1400, 1000), (80, 80, 80))
    image.paste(page, (100, 150))
    image.paste(page, (770, 150))

    with pytest.raises(ValueError):
        detect_page_corners(_bgr(image))
