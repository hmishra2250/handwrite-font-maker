from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from handwrite_font_maker.extract import extract_cells
from handwrite_font_maker.layout import get_layout
from handwrite_font_maker.rectify import detect_page_corners, load_bgr, rectify_template_photo
from handwrite_font_maker.schema import DEFAULT_DPI, compute_geometry
from handwrite_font_maker.template import generate_template_pdf, render_template_image


def _save(image: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _page_on_desk(page: Image.Image, *, tilt: float = 0.12) -> tuple[Image.Image, np.ndarray]:
    import cv2

    page_arr = np.array(page.convert("RGB"))
    h, w = page_arr.shape[:2]
    canvas_w = int(round(w * 1.35))
    canvas_h = int(round(h * 1.25))
    canvas = np.full((canvas_h, canvas_w, 3), (212, 207, 198), dtype=np.uint8)
    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    margin_x = int(round(w * 0.16))
    margin_y = int(round(h * 0.09))
    dx = int(round(w * tilt))
    dy = int(round(h * tilt * 0.42))
    dst = np.float32([
        [margin_x + dx, margin_y + dy],
        [margin_x + w - dx, margin_y],
        [margin_x + w - int(dx * 0.25), margin_y + h - dy],
        [margin_x + int(dx * 0.25), margin_y + h - int(dy * 0.35)],
    ])
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(page_arr, matrix, (canvas_w, canvas_h), borderValue=(212, 207, 198))
    mask = cv2.warpPerspective(np.full((h, w), 255, dtype=np.uint8), matrix, (canvas_w, canvas_h))
    canvas[mask > 0] = warped[mask > 0]
    return Image.fromarray(canvas), dst.astype(np.float32)


def _normalized(points: np.ndarray, image: Image.Image) -> list[list[float]]:
    w, h = image.size
    return [[float(x) / float(w - 1), float(y) / float(h - 1)] for x, y in points]


@pytest.mark.parametrize(
    ("corners", "message"),
    [
        ([[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], "exactly four"),
        ([[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [float("nan"), 0.9]], "finite"),
        ([[0.1, 0.1], [0.1, 0.1], [0.9, 0.9], [0.1, 0.9]], "distinct"),
        ([[-0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]], "0..1"),
        ([[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]], "TL/TR/BR/BL"),
        ([[0.10, 0.10], [0.12, 0.10], [0.12, 0.12], [0.10, 0.12]], "too small"),
    ],
)
def test_page_alignment_rejects_invalid_normalized_quads(tmp_path, corners, message):
    path = _save(Image.new("RGB", (800, 1000), (255, 255, 255)), tmp_path / "blank.png")
    with pytest.raises(ValueError, match=message):
        rectify_template_photo(path, alignment="page", corners=corners)


def test_page_alignment_accepts_tilted_tl_tr_br_bl_manual_corners(tmp_path):
    path = _save(Image.new("RGB", (800, 1000), (255, 255, 255)), tmp_path / "blank.png")
    for quad in (
        np.array([[100, 150], [600, 80], [650, 800], [80, 850]], dtype=np.float32),
        np.array([[100, 80], [600, 150], [650, 850], [80, 800]], dtype=np.float32),
    ):
        doc = rectify_template_photo(path, alignment="page", corners=_normalized(quad, Image.new("RGB", (800, 1000))))
        assert doc.rectified_gray.shape == (doc.geometry.page_height, doc.geometry.page_width)
        assert math.isnan(doc.reprojection_error_px)


def test_markerless_template_contains_no_detectable_aruco_markers():
    import cv2

    image = render_template_image(include_markers=False)
    arr = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    _corners, ids, _rejected = detector.detectMarkers(gray)
    assert ids is None

    layout = get_layout(paper_size="A4")
    geometry = compute_geometry(layout, dpi=DEFAULT_DPI, paper_size="A4")
    arr_dark = np.array(image.convert("L")) < 40
    for box in geometry.marker_boxes.values():
        marker_region = arr_dark[box.top : box.bottom + 1, box.left : box.right + 1]
        assert float(marker_region.mean()) < 0.01


def test_generate_markerless_template_pdf_creates_pdf(tmp_path):
    output = generate_template_pdf(tmp_path / "template-markerless.pdf", include_markers=False)
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")


def test_load_bgr_applies_exif_orientation_and_bounds(tmp_path):
    image = Image.new("RGB", (60, 40), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 20, 39), fill=(255, 0, 0))
    exif = Image.Exif()
    exif[274] = 6  # rotate 90 CW when oriented
    path = tmp_path / "oriented.jpg"
    image.save(path, exif=exif)

    bgr = load_bgr(path)
    assert bgr.shape[:2] == (60, 40)
    assert tuple(int(v) for v in bgr[5, 35]) == pytest.approx((0, 0, 254), abs=3)


def test_detect_page_corners_and_rectify_markerless_synthetic_photo(tmp_path):
    markerless = render_template_image(include_markers=False, dpi=DEFAULT_DPI)
    photo, expected = _page_on_desk(markerless, tilt=0.11)
    path = _save(photo, tmp_path / "markerless-photo.png")

    bgr = load_bgr(path)
    detected = detect_page_corners(bgr)
    assert detected.shape == (4, 2)
    assert np.max(np.linalg.norm(detected - expected, axis=1)) < 30.0

    doc = rectify_template_photo(path, alignment="page", corners=_normalized(detected, photo), paper_size="A4")
    assert math.isnan(doc.reprojection_error_px)
    assert doc.metadata.layout_id == "default-v1"
    assert doc.metadata.paper_size == "A4"
    assert len(extract_cells(doc.metadata, doc.geometry)) == 94


def test_page_alignment_autodetects_when_corners_omitted_for_cli_path(tmp_path):
    markerless = render_template_image(include_markers=False, dpi=DEFAULT_DPI)
    photo, _expected = _page_on_desk(markerless, tilt=0.08)
    path = _save(photo, tmp_path / "markerless-autodetect.png")

    doc = rectify_template_photo(path, alignment="page", paper_size="A4")
    assert math.isnan(doc.reprojection_error_px)
    assert len(extract_cells(doc.metadata, doc.geometry)) == 94

def test_quiet_markerless_template_keeps_short_horizontal_user_ink(tmp_path):
    from handwrite_font_maker.pipeline import _prepare_bitmap, _template_guide_ratios_for_crop

    image = render_template_image(include_markers=False, dpi=DEFAULT_DPI)
    layout = get_layout(paper_size="A4")
    geometry = compute_geometry(layout, dpi=DEFAULT_DPI, paper_size="A4")
    cell = geometry.cell_rects[0]
    draw = ImageDraw.Draw(image)
    margin_x = max(4, int(round(cell.width * layout.inner_margin_x)))
    margin_y = max(4, int(round(cell.height * layout.inner_margin_y)))
    y = cell.top + margin_y + int(round((cell.height - (2 * margin_y)) * 0.35))
    x0 = cell.left + margin_x + int(round(cell.width * 0.18))
    x1 = cell.left + margin_x + int(round(cell.width * 0.48))
    draw.line((x0, y, x1, y), fill=(0, 0, 0), width=max(3, cell.width // 30))
    path = _save(image, tmp_path / "quiet-ink.png")

    doc = rectify_template_photo(
        path,
        alignment="page",
        corners=[[0, 0], [1, 0], [1, 1], [0, 1]],
        paper_size="A4",
    )
    cells = extract_cells(doc.metadata, doc.geometry)
    result = _prepare_bitmap(
        doc.rectified_gray,
        cells[0],
        margin_x=margin_x,
        margin_y=margin_y,
        guide_row_ratios=_template_guide_ratios_for_crop(cells[0].height, margin_y, layout.guide_rows),
    )
    assert not result.empty
    assert result.coverage > 0.01
    assert result.bitmap.width > 20


def test_quiet_markerless_guides_stay_inside_symmetric_extraction_region():
    layout = get_layout(paper_size="A4")
    geometry = compute_geometry(layout, dpi=DEFAULT_DPI, paper_size="A4")
    cell = geometry.cell_rects[0]
    top = cell.top + int(round(cell.height * layout.inner_margin_y))
    bottom = cell.bottom - int(round(cell.height * layout.inner_margin_y))
    rendered_bottom = cell.bottom - int(round(cell.height * 0.05))

    # Markerless alpha uses the exact extraction region so handwriting below the
    # printed descender guide is not invited into a later symmetric crop discard.
    quiet_inner_bottom = bottom
    assert quiet_inner_bottom < rendered_bottom
    for ratio in layout.guide_rows:
        y = int(round(top + ((quiet_inner_bottom - top) * ratio)))
        assert top <= y <= bottom


def test_quiet_markerless_blank_cell_has_no_guide_ink_in_extraction_crop(tmp_path):
    from handwrite_font_maker.pipeline import _prepare_bitmap, _template_guide_ratios_for_crop

    image = render_template_image(include_markers=False, dpi=DEFAULT_DPI)
    path = _save(image, tmp_path / "quiet-markerless-blank.png")
    doc = rectify_template_photo(
        path,
        alignment="page",
        corners=[[0, 0], [1, 0], [1, 1], [0, 1]],
        paper_size="A4",
    )
    layout = get_layout(paper_size="A4")
    cells = extract_cells(doc.metadata, doc.geometry)
    cell = cells[0]
    margin_x = max(4, int(round(cell.width * layout.inner_margin_x)))
    margin_y = max(4, int(round(cell.height * layout.inner_margin_y)))
    result = _prepare_bitmap(
        doc.rectified_gray,
        cell,
        margin_x=margin_x,
        margin_y=margin_y,
        guide_row_ratios=_template_guide_ratios_for_crop(cell.height, margin_y, layout.guide_rows),
    )
    assert result.empty
    assert result.coverage < 0.015
