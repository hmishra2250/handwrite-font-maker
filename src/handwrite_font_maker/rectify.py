from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .diagnostics import HomographyQualityError, MetadataDecodeError
from .layout import get_layout
from .markers import DetectedMarkers, detect_required_markers
from .metadata import decode_metadata
from .schema import DEFAULT_DPI, MARKER_ROLES, Rect, TemplateGeometry, TemplateLayout, TemplateMetadata, compute_geometry

HOMOGRAPHY_REPROJECTION_THRESHOLD_PX = 5.0


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


def load_bgr(path: Path) -> np.ndarray:
    cv2 = _cv2()
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return image


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


def _decode_qr(rectified_bgr: np.ndarray, geometry: TemplateGeometry) -> TemplateMetadata:
    cv2 = _cv2()
    detector = cv2.QRCodeDetector()
    box = geometry.qr_box
    pad = max(12, int(round(box.width * 0.12)))
    crop = rectified_bgr[
        max(0, box.top - pad) : min(rectified_bgr.shape[0], box.bottom + pad + 1),
        max(0, box.left - pad) : min(rectified_bgr.shape[1], box.right + pad + 1),
    ]
    payload, _points, _straight = detector.detectAndDecode(crop)
    if not payload:
        enlarged = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST)
        payload, _points, _straight = detector.detectAndDecode(enlarged)
    if not payload:
        payload, _points, _straight = detector.detectAndDecode(rectified_bgr)
    return decode_metadata(payload)


def rectify_template_photo(image_path: Path, *, dpi: int = DEFAULT_DPI) -> RectifiedDocument:
    cv2 = _cv2()
    image = load_bgr(image_path)

    # Use the default marker layout first; metadata is decoded after rectification.
    bootstrap_layout = get_layout()
    bootstrap_geometry = compute_geometry(bootstrap_layout, dpi=dpi, paper_size=bootstrap_layout.paper_size)
    detected = detect_required_markers(image, bootstrap_layout)
    homography, error = estimate_homography(detected, bootstrap_geometry)
    rectified = cv2.warpPerspective(image, homography, (bootstrap_geometry.page_width, bootstrap_geometry.page_height), borderValue=(255, 255, 255))
    metadata = _decode_qr(rectified, bootstrap_geometry)
    layout = get_layout(layout_id=metadata.layout_id, paper_size=metadata.paper_size)
    geometry = compute_geometry(layout, dpi=metadata.dpi, paper_size=metadata.paper_size)
    if geometry.page_width != bootstrap_geometry.page_width or geometry.page_height != bootstrap_geometry.page_height:
        # Re-warp if metadata selects another canonical page size.
        homography, error = estimate_homography(detected, geometry)
        rectified = cv2.warpPerspective(image, homography, (geometry.page_width, geometry.page_height), borderValue=(255, 255, 255))
    gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
    if tuple(metadata.chars) != tuple(layout.chars):
        raise MetadataDecodeError("Template character map does not match the declared layout.")
    return RectifiedDocument(
        rectified_bgr=rectified,
        rectified_gray=gray,
        metadata=metadata,
        layout=layout,
        geometry=geometry,
        reprojection_error_px=error,
    )
