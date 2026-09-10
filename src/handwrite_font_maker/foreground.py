"""Bounded, user-prompted object cutouts without downloaded model weights.

GrabCut models image colors, not object semantics. The accepted mask remains the
source of truth; users must inspect it, especially on textured backgrounds.
"""
from __future__ import annotations

import math
import multiprocessing as mp
import os
from multiprocessing.connection import wait
from numbers import Real
from dataclasses import dataclass

import cv2
import numpy as np

MAX_CUTOUT_SIDE = 1024
GRABCUT_WORK_SIDE = 512
GRABCUT_TIMEOUT_SECONDS = 4.0


@dataclass(frozen=True)
class ForegroundResult:
    mask: np.ndarray
    method: str
    warnings: tuple[str, ...] = ()


def _normalized_timeout() -> float:
    raw = os.environ.get("HANDWRITE_GRABCUT_TIMEOUT_SECONDS")
    if raw is None:
        return GRABCUT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return GRABCUT_TIMEOUT_SECONDS
    return min(30.0, max(0.25, value))


def _validate_source_and_rectangle(image_bgr: np.ndarray, rectangle: object) -> tuple[np.ndarray, tuple[float, float, float, float], tuple[int, int, int, int]]:
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
    return image_bgr, (left, top, right, bottom), (x0, y0, x1, y1)


def _roi_and_background(gray: np.ndarray, bounds: tuple[int, int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, x1, y1 = bounds
    roi = gray[y0:y1, x0:x1]
    outside = np.ones(gray.shape, dtype=bool)
    outside[y0:y1, x0:x1] = False
    background = gray[outside]
    return roi, background


def _score_threshold_candidate(selected_roi: np.ndarray, roi: np.ndarray, background: np.ndarray) -> float:
    coverage = float(selected_roi.mean())
    if not 0.001 <= coverage <= 0.85:
        return -1.0
    selected_values = roi[selected_roi]
    if selected_values.size < 4 or background.size < 4:
        return -1.0
    contrast = abs(float(np.median(selected_values)) - float(np.median(background)))
    # Avoid accepting low-contrast texture/noise as a deterministic "cutout".
    if contrast < 18.0:
        return -1.0
    return contrast * min(coverage, 1.0 - coverage)


def threshold_foreground(
    image_bgr: np.ndarray,
    rectangle: object,
    *,
    polarity: str = "auto",
    adaptive: bool = False,
) -> np.ndarray:
    """Fast deterministic mask for high-contrast foregrounds.

    ``polarity`` controls which side of the local threshold is foreground:
    ``dark`` for ink/objects darker than the background, ``light`` for light
    objects on dark backgrounds, and ``auto`` to infer from the rectangle edge
    and outside-of-rectangle background. The returned mask follows the app-wide
    convention: 0/black foreground, 255/white background.
    """

    if polarity not in {"auto", "dark", "light"}:
        raise ValueError("polarity must be auto, dark or light.")
    source, _rectangle, bounds = _validate_source_and_rectangle(image_bgr, rectangle)
    x0, y0, x1, y1 = bounds
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    roi, background = _roi_and_background(gray, bounds)
    if roi.size < 9:
        raise ValueError("Select a larger rectangle around the entire character.")
    if float(np.std(roi)) < 2.0 and float(np.std(background)) < 2.0:
        raise ValueError("No foreground found. Adjust the rectangle or use a higher-contrast image.")

    if adaptive:
        block = max(15, min(81, (min(roi.shape[:2]) // 6) | 1))
        blurred = cv2.GaussianBlur(roi, (3, 3), 0)
        dark_binary = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 9)
        light_binary = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 9)
        dark_selected = dark_binary > 0
        light_selected = light_binary > 0
    else:
        threshold, _ = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        dark_selected = roi <= threshold
        light_selected = roi > threshold

    candidates: list[tuple[str, np.ndarray, float]] = []
    for name, selected in (("dark", dark_selected), ("light", light_selected)):
        if polarity != "auto" and polarity != name:
            continue
        candidates.append((name, selected, _score_threshold_candidate(selected, roi, background)))
    selected_name, selected_roi, score = max(candidates, key=lambda item: item[2])
    del selected_name
    if score < 0:
        raise ValueError("No high-contrast foreground found for threshold extraction.")

    # Preserve holes/disconnected parts. Only remove tiny isolated camera noise.
    min_area = max(4, int(round(roi.size * 0.00002)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(selected_roi.astype(np.uint8), connectivity=8)
    cleaned = np.zeros_like(selected_roi, dtype=bool)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area:
            cleaned |= labels == label
    if np.count_nonzero(cleaned) < 4:
        raise ValueError("No foreground found. Adjust the rectangle or use a higher-contrast image.")
    mask = np.full(gray.shape, 255, np.uint8)
    mask[y0:y1, x0:x1] = np.where(cleaned, 0, 255).astype(np.uint8)
    return mask


def _grabcut_worker(image_bgr: np.ndarray, bounds: tuple[int, int, int, int], connection) -> None:
    x0, y0, x1, y1 = bounds
    labels = np.zeros(image_bgr.shape[:2], dtype=np.uint8)
    try:
        cv2.setNumThreads(1)
        cv2.grabCut(
            image_bgr,
            labels,
            (x0, y0, x1 - x0, y1 - y0),
            np.zeros((1, 65), np.float64),
            np.zeros((1, 65), np.float64),
            3,
            cv2.GC_INIT_WITH_RECT,
        )
        selected = ((labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD)).astype(np.uint8)
        connection.send(("ok", selected))
    except Exception as exc:  # pragma: no cover - exercised by parent error path.
        connection.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        connection.close()


def _bounded_grabcut(image_bgr: np.ndarray, bounds: tuple[int, int, int, int], timeout_seconds: float) -> np.ndarray:
    height, width = image_bgr.shape[:2]
    scale = min(1.0, GRABCUT_WORK_SIDE / max(height, width))
    if scale < 1.0:
        work = cv2.resize(image_bgr, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        x0, y0, x1, y1 = bounds
        work_bounds = (
            int(x0 * scale),
            int(y0 * scale),
            min(work.shape[1], math.ceil(x1 * scale)),
            min(work.shape[0], math.ceil(y1 * scale)),
        )
    else:
        work = image_bgr
        work_bounds = bounds
    if work_bounds[2] - work_bounds[0] < 3 or work_bounds[3] - work_bounds[1] < 3:
        raise ValueError("Select a larger rectangle around the entire character.")

    context = mp.get_context("spawn" if "spawn" in mp.get_all_start_methods() else None)
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(target=_grabcut_worker, args=(work, work_bounds, child_connection), daemon=True)
    process.start()
    child_connection.close()
    ready = wait([parent_connection, process.sentinel], timeout_seconds)
    if parent_connection in ready:
        status, payload = parent_connection.recv()
        process.join(1.0)
        parent_connection.close()
        if status != "ok":
            raise ValueError("Could not separate this object. Try a plain contrasting background.")
        selected = np.asarray(payload, dtype=np.uint8).astype(bool)
        if scale < 1.0:
            selected = cv2.resize(selected.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST).astype(bool)
        return selected
    process.join(0.0)
    if process.is_alive():
        process.terminate()
        process.join(1.0)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(1.0)
        parent_connection.close()
        raise ValueError("Classical GrabCut exceeded its time limit. Try threshold extraction, a tighter crop, or a learned model.")
    parent_connection.close()
    raise ValueError("Could not separate this object. Try a plain contrasting background.")


def extract_foreground_result(image_bgr: np.ndarray, rectangle: object) -> ForegroundResult:
    """Return full-frame black-foreground/white-background uint8 mask.

    Rectangle is normalized left/top/right/bottom in EXIF-oriented source space.
    Outside pixels provide known background. No component filtering or hole
    filling is performed: disconnected pieces can belong to the same letter.
    """
    source, _rectangle, bounds = _validate_source_and_rectangle(image_bgr, rectangle)

    try:
        mask = threshold_foreground(source, rectangle, polarity="auto", adaptive=False)
        return ForegroundResult(mask, "threshold", ("Used deterministic high-contrast threshold; classical GrabCut was not needed.",))
    except ValueError as exc:
        gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        if "No foreground" in str(exc) or float(np.std(gray)) < 2.0:
            raise ValueError("No foreground found. Adjust the rectangle or use ink thresholding.") from exc
        pass

    selected = _bounded_grabcut(source, bounds, _normalized_timeout())
    if np.count_nonzero(selected) < 4:
        raise ValueError("No foreground found. Adjust the rectangle or use ink thresholding.")
    return ForegroundResult(np.where(selected, 0, 255).astype(np.uint8), "grabcut")


def extract_foreground(image_bgr: np.ndarray, rectangle: object) -> np.ndarray:
    """Backward-compatible mask-only wrapper around extract_foreground_result."""

    return extract_foreground_result(image_bgr, rectangle).mask
