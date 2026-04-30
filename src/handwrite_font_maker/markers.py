from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .diagnostics import MarkerDetectionError
from .schema import MARKER_DICTIONARY, MARKER_ROLES, TemplateLayout


def _cv2():
    import cv2

    return cv2


ARUCO_DICTIONARIES = {
    "DICT_4X4_50": "DICT_4X4_50",
    "DICT_4X4_100": "DICT_4X4_100",
    "DICT_5X5_100": "DICT_5X5_100",
    "DICT_6X6_250": "DICT_6X6_250",
}


def get_aruco_dictionary(name: str = MARKER_DICTIONARY):
    cv2 = _cv2()
    try:
        attr = ARUCO_DICTIONARIES[name]
        dictionary_id = getattr(cv2.aruco, attr)
    except AttributeError as exc:
        raise RuntimeError("Installed OpenCV does not expose required cv2.aruco dictionaries.") from exc
    except KeyError as exc:
        raise ValueError(f"Unsupported ArUco dictionary: {name}") from exc
    return cv2.aruco.getPredefinedDictionary(dictionary_id)


def generate_marker_image(marker_id: int, size: int, dictionary_name: str = MARKER_DICTIONARY) -> np.ndarray:
    cv2 = _cv2()
    dictionary = get_aruco_dictionary(dictionary_name)
    image = np.zeros((size, size), dtype=np.uint8)
    cv2.aruco.generateImageMarker(dictionary, int(marker_id), int(size), image, 1)
    return image


@dataclass(frozen=True)
class DetectedMarkers:
    corners_by_role: dict[str, np.ndarray]
    ids_by_role: dict[str, int]


def detect_required_markers(image: np.ndarray, layout: TemplateLayout) -> DetectedMarkers:
    cv2 = _cv2()
    dictionary = get_aruco_dictionary(layout.marker_dictionary)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    parameters = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(dictionary, parameters)
    corners, ids, _rejected = detector.detectMarkers(gray)

    found_by_id: dict[int, np.ndarray] = {}
    if ids is not None:
        for marker_corners, marker_id in zip(corners, ids.flatten(), strict=True):
            found_by_id[int(marker_id)] = marker_corners.reshape(4, 2).astype(np.float32)

    corners_by_role: dict[str, np.ndarray] = {}
    ids_by_role: dict[str, int] = {}
    missing: list[str] = []
    for role in MARKER_ROLES:
        marker_id = int(layout.marker_roles[role])
        if marker_id not in found_by_id:
            missing.append(role)
        else:
            corners_by_role[role] = found_by_id[marker_id]
            ids_by_role[role] = marker_id
    if missing:
        raise MarkerDetectionError(missing)
    return DetectedMarkers(corners_by_role=corners_by_role, ids_by_role=ids_by_role)
