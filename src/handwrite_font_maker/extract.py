from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .diagnostics import CellExtractionError
from .schema import Rect, TemplateGeometry, TemplateMetadata

Cell = Rect


def extract_cells(metadata: TemplateMetadata, geometry: TemplateGeometry) -> list[Cell]:
    cells = list(geometry.cell_rects)
    expected = metadata.character_count
    if len(cells) != expected:
        raise CellExtractionError(f"Expected {expected} cells from template metadata, extracted {len(cells)}.")
    return cells


def save_debug_overlay(rectified_gray: np.ndarray, cells: list[Cell], output_path: Path) -> None:
    image = Image.fromarray(rectified_gray).convert("RGB")
    draw = ImageDraw.Draw(image)
    for cell in cells:
        draw.rectangle((cell.left, cell.top, cell.right, cell.bottom), outline=(220, 50, 50), width=2)
    image.save(output_path)
