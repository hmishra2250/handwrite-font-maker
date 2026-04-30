from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

TEMPLATE_KIND = "handwrite-font-template"
TEMPLATE_VERSION = 1
DEFAULT_LAYOUT_ID = "default-v1"
DEFAULT_PAPER_SIZE = "A4"
DEFAULT_DPI = 150
MARKER_DICTIONARY = "DICT_4X4_50"
MARKER_IDS = {
    "top_left": 10,
    "top_right": 11,
    "bottom_right": 12,
    "bottom_left": 13,
}
MARKER_ROLES = tuple(MARKER_IDS.keys())

PAPER_SIZES_INCHES: dict[str, tuple[float, float]] = {
    "A4": (8.2677165354, 11.692913386),
    "LETTER": (8.5, 11.0),
}


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    @property
    def corners(self) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]:
        return (
            (float(self.left), float(self.top)),
            (float(self.right), float(self.top)),
            (float(self.right), float(self.bottom)),
            (float(self.left), float(self.bottom)),
        )


@dataclass(frozen=True)
class TemplateLayout:
    layout_id: str
    chars: tuple[str, ...]
    columns: int = 10
    paper_size: str = DEFAULT_PAPER_SIZE
    marker_dictionary: str = MARKER_DICTIONARY
    marker_ids: dict[str, int] | None = None
    guide_rows: tuple[float, ...] = (0.22, 0.50, 0.74)
    inner_margin_x: float = 0.08
    inner_margin_y: float = 0.18

    @property
    def rows(self) -> int:
        return math.ceil(len(self.chars) / self.columns)

    @property
    def marker_roles(self) -> dict[str, int]:
        return self.marker_ids or MARKER_IDS

    def validate(self) -> None:
        if len(set(self.chars)) != len(self.chars):
            raise ValueError("Layout contains duplicate characters.")
        missing_roles = set(MARKER_ROLES) - set(self.marker_roles)
        if missing_roles:
            raise ValueError(f"Layout marker roles missing: {sorted(missing_roles)}")
        if not all(0.0 < row < 1.0 for row in self.guide_rows):
            raise ValueError("Guide rows must be relative positions between 0 and 1.")


@dataclass(frozen=True)
class TemplateGeometry:
    page_width: int
    page_height: int
    marker_size: int
    margin: int
    qr_box: Rect
    marker_boxes: dict[str, Rect]
    cell_rects: tuple[Rect, ...]
    grid_rect: Rect


def paper_dimensions_px(paper_size: str = DEFAULT_PAPER_SIZE, dpi: int = DEFAULT_DPI) -> tuple[int, int]:
    try:
        width_in, height_in = PAPER_SIZES_INCHES[paper_size.upper()]
    except KeyError as exc:
        raise ValueError(f"Unsupported paper size: {paper_size}") from exc
    return int(round(width_in * dpi)), int(round(height_in * dpi))


def page_points(paper_size: str = DEFAULT_PAPER_SIZE) -> tuple[float, float]:
    width_in, height_in = PAPER_SIZES_INCHES[paper_size.upper()]
    return width_in * 72.0, height_in * 72.0


def compute_geometry(layout: TemplateLayout, *, dpi: int = DEFAULT_DPI, paper_size: str | None = None) -> TemplateGeometry:
    layout.validate()
    width, height = paper_dimensions_px(paper_size or layout.paper_size, dpi=dpi)
    margin = max(36, int(round(width * 0.05)))
    marker_size = max(72, int(round(width * 0.08)))
    qr_size = max(380, int(round(width * 0.30)))

    marker_boxes = {
        "top_left": Rect(margin, margin, margin + marker_size - 1, margin + marker_size - 1),
        "top_right": Rect(width - margin - marker_size, margin, width - margin - 1, margin + marker_size - 1),
        "bottom_right": Rect(
            width - margin - marker_size,
            height - margin - marker_size,
            width - margin - 1,
            height - margin - 1,
        ),
        "bottom_left": Rect(margin, height - margin - marker_size, margin + marker_size - 1, height - margin - 1),
    }
    qr_box = Rect((width - qr_size) // 2, margin, (width + qr_size) // 2 - 1, margin + qr_size - 1)

    grid_top = max(margin + marker_size + 48, qr_box.bottom + 36, int(round(height * 0.22)))
    grid_bottom = height - margin - marker_size - 36
    grid_left = margin
    grid_right = width - margin - 1
    grid_rect = Rect(grid_left, grid_top, grid_right, grid_bottom)

    cell_w = grid_rect.width / layout.columns
    cell_h = grid_rect.height / layout.rows
    cells: list[Rect] = []
    for index in range(len(layout.chars)):
        row = index // layout.columns
        col = index % layout.columns
        left = int(round(grid_left + col * cell_w))
        top = int(round(grid_top + row * cell_h))
        right = int(round(grid_left + (col + 1) * cell_w)) - 1
        bottom = int(round(grid_top + (row + 1) * cell_h)) - 1
        cells.append(Rect(left, top, right, bottom))

    return TemplateGeometry(
        page_width=width,
        page_height=height,
        marker_size=marker_size,
        margin=margin,
        qr_box=qr_box,
        marker_boxes=marker_boxes,
        cell_rects=tuple(cells),
        grid_rect=grid_rect,
    )


@dataclass(frozen=True)
class TemplateMetadata:
    kind: str
    version: int
    layout_id: str
    chars: tuple[str, ...]
    paper_size: str
    marker_dictionary: str
    marker_ids: dict[str, int]
    dpi: int = DEFAULT_DPI

    @property
    def character_count(self) -> int:
        return len(self.chars)
