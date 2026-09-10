from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .diagnostics import HomographyQualityError
from .layout import get_layout
from .markers import DetectedMarkers, detect_required_markers
from .metadata import metadata_for_layout
from .schema import DEFAULT_DPI, MARKER_ROLES, TemplateGeometry, TemplateLayout, TemplateMetadata, compute_geometry

HOMOGRAPHY_REPROJECTION_THRESHOLD_PX = 5.0
MAX_DECODED_PIXELS = 40_000_000
MAX_IMAGE_SIDE_PX = 10_000
MIN_PAGE_AREA_RATIO = 0.18
MIN_MANUAL_AREA_RATIO = 0.04
DETECTION_BORDER_MARGIN_PX = 6.0


def _cv2():
    import cv2

    return cv2


@dataclass(frozen=True)
class RectifiedDocument:
    rectified_bgr: np.ndarray
    rectified_gray: np.ndarray
    metadata: TemplateMetadata
    layout: TemplateLayout
    geometry: TemplateGeometry
    reprojection_error_px: float
    alignment: str = "markers"


def load_bgr(path: Path | str) -> np.ndarray:
    """Decode an image as EXIF-oriented BGR while bounding decoded size.

    Coordinates returned by/manual-supplied to this module are always against this
    oriented natural image, matching browser canvas preview orientation.
    """

    path = Path(path)
    try:
        with Image.open(path) as opened:
            width, height = opened.size
            if width <= 0 or height <= 0:
                raise ValueError(f"Image has invalid dimensions: {width}x{height}.")
            if width * height > MAX_DECODED_PIXELS or max(width, height) > MAX_IMAGE_SIDE_PX:
                raise ValueError(
                    f"Image is too large ({width}x{height}); use an image up to "
                    f"{MAX_DECODED_PIXELS:,} pixels and {MAX_IMAGE_SIDE_PX}px on its longest side."
                )
            oriented = ImageOps.exif_transpose(opened).convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError(f"Unsupported or unreadable image file: {path}") from exc
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not read image: {path}")

    arr = np.asarray(oriented, dtype=np.uint8)
    return arr[:, :, ::-1].copy()


def _role_corner(corners: np.ndarray, role: str) -> np.ndarray:
    index = {"top_left": 0, "top_right": 1, "bottom_right": 2, "bottom_left": 3}[role]
    return corners[index]


def _all_expected_corners(geometry: TemplateGeometry) -> dict[str, np.ndarray]:
    return {role: np.array(geometry.marker_boxes[role].corners, dtype=np.float32) for role in MARKER_ROLES}


def estimate_homography(
    detected: DetectedMarkers,
    geometry: TemplateGeometry,
    *,
    threshold_px: float = HOMOGRAPHY_REPROJECTION_THRESHOLD_PX,
) -> tuple[np.ndarray, float]:
    cv2 = _cv2()
    src = np.array([_role_corner(detected.corners_by_role[role], role) for role in MARKER_ROLES], dtype=np.float32)
    dst = np.array([_role_corner(_all_expected_corners(geometry)[role], role) for role in MARKER_ROLES], dtype=np.float32)
    homography = cv2.getPerspectiveTransform(src, dst)

    errors: list[float] = []
    for role in MARKER_ROLES:
        projected = cv2.perspectiveTransform(detected.corners_by_role[role].reshape(1, 4, 2), homography).reshape(4, 2)
        expected = _all_expected_corners(geometry)[role]
        errors.extend(float(np.linalg.norm(a - b)) for a, b in zip(projected, expected, strict=True))
    reprojection_error = float(np.sqrt(np.mean(np.square(errors)))) if errors else float("inf")
    if reprojection_error >= threshold_px:
        raise HomographyQualityError(reprojection_error, threshold_px)
    return homography, reprojection_error


def _as_quad(points: Iterable[Iterable[float]], *, normalized: bool) -> np.ndarray:
    try:
        quad = np.asarray(points, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError("Page corners must be exactly four [x,y] coordinate pairs.") from exc
    if quad.shape != (4, 2):
        raise ValueError("Page corners must be exactly four [x,y] coordinate pairs in TL/TR/BR/BL order.")
    if not np.all(np.isfinite(quad)):
        raise ValueError("Page corners must contain only finite coordinates.")
    if normalized and (float(quad.min()) < 0.0 or float(quad.max()) > 1.0):
        raise ValueError("Normalized page corners must be within 0..1 of the EXIF-oriented image.")
    return quad


def _polygon_signed_area(quad: np.ndarray) -> float:
    x = quad[:, 0]
    y = quad[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _order_corners_tl_tr_br_bl(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    by_y = pts[np.argsort(pts[:, 1])]
    top = by_y[:2]
    bottom = by_y[2:]
    tl, tr = top[np.argsort(top[:, 0])]
    bl, br = bottom[np.argsort(bottom[:, 0])]
    ordered = np.array([tl, tr, br, bl], dtype=np.float32)
    if _polygon_signed_area(ordered) <= 0:
        # Fallback for severe perspective where simple y-bands become unstable.
        sums = pts.sum(axis=1)
        diffs = pts[:, 0] - pts[:, 1]
        ordered = np.array([
            pts[int(np.argmin(sums))],
            pts[int(np.argmax(diffs))],
            pts[int(np.argmax(sums))],
            pts[int(np.argmin(diffs))],
        ], dtype=np.float32)
    return ordered.astype(np.float32)


def _validate_page_quad(
    quad: np.ndarray,
    *,
    image_width: int,
    image_height: int,
    normalized: bool,
    min_area_ratio: float,
    require_ordered: bool = True,
    border_margin_px: float = 0.0,
) -> np.ndarray:
    if normalized:
        quad_px = quad.copy()
        quad_px[:, 0] *= float(image_width - 1)
        quad_px[:, 1] *= float(image_height - 1)
    else:
        quad_px = quad.astype(np.float32, copy=True)

    if (
        float(quad_px[:, 0].min()) < 0.0
        or float(quad_px[:, 1].min()) < 0.0
        or float(quad_px[:, 0].max()) > float(image_width - 1)
        or float(quad_px[:, 1].max()) > float(image_height - 1)
    ):
        raise ValueError("Page corners must be in-bounds for the EXIF-oriented image.")

    if border_margin_px > 0.0:
        if (
            float(quad_px[:, 0].min()) < border_margin_px
            or float(quad_px[:, 1].min()) < border_margin_px
            or float(quad_px[:, 0].max()) > float(image_width - 1) - border_margin_px
            or float(quad_px[:, 1].max()) > float(image_height - 1) - border_margin_px
        ):
            raise ValueError("Detected page appears clipped by the image border; re-shoot with all paper edges visible.")

    min_pairwise = max(8.0, min(image_width, image_height) * 0.015)
    for i in range(4):
        for j in range(i + 1, 4):
            if float(np.linalg.norm(quad_px[i] - quad_px[j])) < min_pairwise:
                raise ValueError("Page corners must be distinct; adjust or re-detect the four page corners.")

    cv2 = _cv2()
    if not cv2.isContourConvex(quad_px.reshape(-1, 1, 2).astype(np.float32)):
        raise ValueError("Page corners must form a convex non-self-intersecting quad in TL/TR/BR/BL order.")

    area = abs(_polygon_signed_area(quad_px))
    if area < float(image_width * image_height) * min_area_ratio:
        raise ValueError("Page corner quad is too small; include more of the flat A4 page in the photo.")

    if require_ordered:
        ordered = _order_corners_tl_tr_br_bl(quad_px)
        tolerance = max(4.0, min(image_width, image_height) * 0.015)
        if float(np.max(np.linalg.norm(quad_px - ordered, axis=1))) > tolerance:
            raise ValueError("Page corners must be supplied in TL/TR/BR/BL order without crossing edges.")

    edge_lengths = [float(np.linalg.norm(quad_px[(i + 1) % 4] - quad_px[i])) for i in range(4)]
    if min(edge_lengths) < max(12.0, min(image_width, image_height) * 0.04):
        raise ValueError("Page corner quad is too narrow; re-shoot the full A4 page.")

    return quad_px.astype(np.float32)


def _candidate_from_contour(contour: np.ndarray) -> np.ndarray | None:
    cv2 = _cv2()
    perimeter = cv2.arcLength(contour, True)
    if perimeter <= 0:
        return None
    for epsilon_ratio in (0.015, 0.02, 0.03, 0.04, 0.055, 0.075):
        approx = cv2.approxPolyDP(contour, epsilon_ratio * perimeter, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype(np.float32)
    rect = cv2.minAreaRect(contour)
    box = cv2.boxPoints(rect)
    return box.astype(np.float32)


def _score_quad(quad: np.ndarray, *, image_width: int, image_height: int) -> float:
    area = abs(_polygon_signed_area(quad))
    area_ratio = area / float(image_width * image_height)
    edges = [float(np.linalg.norm(quad[(i + 1) % 4] - quad[i])) for i in range(4)]
    if min(edges) <= 0:
        return -1.0
    opposite_balance = min(edges[0], edges[2]) / max(edges[0], edges[2]) + min(edges[1], edges[3]) / max(edges[1], edges[3])
    expected_ratio = 1.0 / 1.41421356237
    width_est = (edges[0] + edges[2]) / 2.0
    height_est = (edges[1] + edges[3]) / 2.0
    ratio = min(width_est, height_est) / max(width_est, height_est)
    ratio_score = max(0.0, 1.0 - abs(ratio - expected_ratio) / 0.45)
    return area_ratio * 6.0 + opposite_balance + ratio_score


def _find_page_candidates(gray: np.ndarray) -> list[np.ndarray]:
    cv2 = _cv2()
    h, w = gray.shape[:2]
    candidates: list[np.ndarray] = []

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _hier = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = list(contours)

    # Bright-page candidate for photos on a darker desk.
    threshold = max(150, int(np.percentile(gray, 58)))
    _, bright = cv2.threshold(blurred, threshold, 255, cv2.THRESH_BINARY)
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, kernel, iterations=2)
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, kernel, iterations=1)
    bright_contours, _hier = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours.extend(list(bright_contours))

    min_area = float(w * h) * MIN_PAGE_AREA_RATIO
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        raw = _candidate_from_contour(contour)
        if raw is None:
            continue
        ordered = _order_corners_tl_tr_br_bl(raw)
        try:
            valid = _validate_page_quad(
                ordered,
                image_width=w,
                image_height=h,
                normalized=False,
                min_area_ratio=MIN_PAGE_AREA_RATIO,
                border_margin_px=DETECTION_BORDER_MARGIN_PX,
            )
        except ValueError:
            continue
        candidates.append(valid)
    return candidates


def detect_page_corners(image_bgr: np.ndarray) -> np.ndarray:
    """Suggest markerless page corners in pixel TL/TR/BR/BL order.

    This is a detection suggestion only. It validates geometry/visibility but does
    not report homography residual as an independent confidence score.
    """

    if image_bgr is None or not isinstance(image_bgr, np.ndarray) or image_bgr.size == 0:
        raise ValueError("Page detection needs a decoded image.")
    if image_bgr.ndim not in (2, 3):
        raise ValueError("Page detection expects a grayscale or BGR image array.")

    cv2 = _cv2()
    image = image_bgr
    h, w = image.shape[:2]
    if w * h > MAX_DECODED_PIXELS or max(w, h) > MAX_IMAGE_SIDE_PX:
        raise ValueError("Page detection image is too large; resize before upload.")

    scale = 1.0
    max_detection_side = 1600.0
    if max(w, h) > max_detection_side:
        scale = max_detection_side / float(max(w, h))
        image = cv2.resize(image, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    candidates = _find_page_candidates(gray)
    if not candidates:
        raise ValueError(
            "Could not find a full A4 page outline. Re-shoot flat on a contrasting background with all four paper edges visible, or supply manual corners."
        )

    dh, dw = gray.shape[:2]
    best = max(candidates, key=lambda quad: _score_quad(quad, image_width=dw, image_height=dh))
    if scale != 1.0:
        best = best / scale
    return best.astype(np.float32)


def _homography_for_page_corners(corners_px: np.ndarray, geometry: TemplateGeometry) -> np.ndarray:
    cv2 = _cv2()
    dst = np.array(
        [
            [0.0, 0.0],
            [float(geometry.page_width - 1), 0.0],
            [float(geometry.page_width - 1), float(geometry.page_height - 1)],
            [0.0, float(geometry.page_height - 1)],
        ],
        dtype=np.float32,
    )
    return cv2.getPerspectiveTransform(corners_px.astype(np.float32), dst)


def rectify_template_photo(
    image_path: Path | str,
    *,
    dpi: int = DEFAULT_DPI,
    alignment: str = "markers",
    corners: Iterable[Iterable[float]] | None = None,
    paper_size: str = "A4",
) -> RectifiedDocument:
    cv2 = _cv2()
    image = load_bgr(image_path)

    normalized_alignment = alignment.lower().strip()
    if normalized_alignment not in {"markers", "page"}:
        raise ValueError("alignment must be 'markers' or 'page'.")

    if normalized_alignment == "page" and paper_size.upper() != "A4":
        raise ValueError("Markerless page alignment supports only templateId default-v1 on A4 paper in alpha.")

    layout = get_layout(paper_size=paper_size)
    geometry = compute_geometry(layout, dpi=dpi, paper_size=layout.paper_size)

    if normalized_alignment == "markers":
        detected = detect_required_markers(image, layout)
        homography, error = estimate_homography(detected, geometry)
    else:
        h, w = image.shape[:2]
        if corners is None:
            corners_px = detect_page_corners(image)
            corners_px = _validate_page_quad(
                corners_px,
                image_width=w,
                image_height=h,
                normalized=False,
                min_area_ratio=MIN_PAGE_AREA_RATIO,
                border_margin_px=DETECTION_BORDER_MARGIN_PX,
            )
        else:
            normalized = _as_quad(corners, normalized=True)
            corners_px = _validate_page_quad(
                normalized,
                image_width=w,
                image_height=h,
                normalized=True,
                min_area_ratio=MIN_MANUAL_AREA_RATIO,
                border_margin_px=0.0,
            )
        homography = _homography_for_page_corners(corners_px, geometry)
        # A four-corner homography has no independent residual. Use NaN so callers
        # cannot mistake exact interpolation for confidence/quality proof.
        error = float("nan")

    rectified = cv2.warpPerspective(image, homography, (geometry.page_width, geometry.page_height), borderValue=(255, 255, 255))
    metadata = metadata_for_layout(layout, dpi=dpi)
    gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
    return RectifiedDocument(
        rectified_bgr=rectified,
        rectified_gray=gray,
        metadata=metadata,
        layout=layout,
        geometry=geometry,
        reprojection_error_px=error,
        alignment=normalized_alignment,
    )
