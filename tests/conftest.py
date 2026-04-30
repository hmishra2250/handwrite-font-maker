from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from handwrite_font_maker.layout import get_layout
from handwrite_font_maker.schema import DEFAULT_DPI, compute_geometry
from handwrite_font_maker.template import render_template_image


@pytest.fixture
def synthetic_filled_template():
    def _make(*, dpi: int = DEFAULT_DPI) -> Image.Image:
        layout = get_layout(paper_size="A4")
        geometry = compute_geometry(layout, dpi=dpi, paper_size="A4")
        image = render_template_image(layout=layout, paper_size="A4", dpi=dpi)
        draw = ImageDraw.Draw(image)
        for index, cell in enumerate(geometry.cell_rects):
            mx = int(cell.width * 0.22)
            my = int(cell.height * 0.26)
            x0, y0 = cell.left + mx, cell.top + my
            x1, y1 = cell.right - mx, cell.bottom - int(cell.height * 0.15)
            width = max(2, cell.width // 28)
            if index % 3 == 0:
                draw.line((x0, y1, (x0 + x1) // 2, y0, x1, y1), fill=(0, 0, 0), width=width)
            elif index % 3 == 1:
                draw.ellipse((x0, y0, x1, y1), outline=(0, 0, 0), width=width)
            else:
                draw.line((x0, y0, x1, y1), fill=(0, 0, 0), width=width)
                draw.line((x1, y0, x0, y1), fill=(0, 0, 0), width=width)
        return image

    return _make


@pytest.fixture
def save_image():
    def _save(image: Image.Image, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return path

    return _save


@pytest.fixture
def perspective_warp():
    def _warp(image: Image.Image, *, tilt: float = 0.18) -> Image.Image:
        import cv2

        arr = np.array(image.convert("RGB"))
        h, w = arr.shape[:2]
        src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        dx = w * tilt
        dy = h * tilt * 0.35
        dst = np.float32([[dx, dy], [w - dx, 0], [w - 1, h - dy], [0, h - dy * 0.5]])
        matrix = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(arr, matrix, (w, h), borderValue=(255, 255, 255))
        return Image.fromarray(warped)

    return _warp
