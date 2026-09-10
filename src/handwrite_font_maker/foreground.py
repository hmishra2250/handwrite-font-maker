"""Bounded, user-prompted object cutouts without downloaded model weights.

GrabCut models image colors, not object semantics. The accepted mask remains the
source of truth; users must inspect it, especially on textured backgrounds.
"""
from __future__ import annotations

import math
from numbers import Real

import cv2
import numpy as np

MAX_CUTOUT_SIDE = 1024


def extract_foreground(image_bgr: np.ndarray, rectangle: object) -> np.ndarray:
    """Return full-frame black-foreground/white-background uint8 mask.

    Rectangle is normalized left/top/right/bottom in EXIF-oriented source space.
    Outside pixels provide known background. No component filtering or hole
    filling is performed: disconnected pieces can belong to the same letter.
    """
    if (not isinstance(image_bgr, np.ndarray) or image_bgr.dtype != np.uint8
            or image_bgr.ndim != 3 or image_bgr.shape[2] != 3
            or min(image_bgr.shape[:2]) < 8):
        raise ValueError("A color image at least 8 pixels wide and tall is required.")
    if not isinstance(rectangle, (list, tuple)) or len(rectangle) != 4:
        raise ValueError("rectangle must contain left, top, right, bottom.")
    if any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v)
           or not 0 <= v <= 1 for v in rectangle):
        raise ValueError("Rectangle coordinates must be finite numbers between 0 and 1.")
    left, top, right, bottom = map(float, rectangle)
    if left >= right or top >= bottom:
        raise ValueError("Rectangle must have positive width and height.")

    height, width = image_bgr.shape[:2]
    scale = min(1.0, MAX_CUTOUT_SIDE / max(height, width))
    if scale < 1:
        target_size = (round(width * scale), round(height * scale))
        if min(target_size) < 8:
            raise ValueError("Image is too narrow. Crop closer around the character before uploading.")
        image_bgr = cv2.resize(image_bgr, target_size, interpolation=cv2.INTER_AREA)
    height, width = image_bgr.shape[:2]
    x0, y0 = int(left * width), int(top * height)
    x1, y1 = min(width, math.ceil(right * width)), min(height, math.ceil(bottom * height))
    if x1 - x0 < 3 or y1 - y0 < 3:
        raise ValueError("Select a larger rectangle around the entire character.")
    if (x1 - x0) * (y1 - y0) >= width * height - 5:
        raise ValueError("Leave some background outside the rectangle.")

    labels = np.zeros((height, width), dtype=np.uint8)
    try:
        cv2.grabCut(image_bgr, labels, (x0, y0, x1 - x0, y1 - y0),
                    np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
                    5, cv2.GC_INIT_WITH_RECT)
    except cv2.error as exc:
        raise ValueError("Could not separate this object. Try a plain contrasting background.") from exc
    selected = (labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD)
    if np.count_nonzero(selected) < 4:
        raise ValueError("No foreground found. Adjust the rectangle or use ink thresholding.")
    return np.where(selected, 0, 255).astype(np.uint8)
