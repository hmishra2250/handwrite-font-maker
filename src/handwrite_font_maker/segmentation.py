"""Optional, offline SlimSAM inference and explicit classical fallback.

Checkpoint preprocessing follows the pinned SamImageProcessor configuration.
No request downloads weights or runs remote code. Model assets are verified
before loading and CPU inference is serialized per worker process.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from PIL import Image

from .foreground import MAX_CUTOUT_SIDE, extract_foreground_result, threshold_foreground

MODEL_REPO = 'Xenova/slimsam-77-uniform'
MODEL_REVISION = '5850ab45f587c112167512ffef949107115e26a0'
# SHA-256 values and lengths from the pinned Hugging Face Git LFS objects.
MODEL_ASSETS = {
    'vision_encoder.onnx': (23276014, '9f8433273a6750b587779baa0cf5508111001bf7e7acfcf585d370139fd366d0'),
    'prompt_encoder_mask_decoder.onnx': (16557892, 'f4514391764fbd56e08e119060d874ecd7d52994bfb1968af159e12d4943b5bb'),
    'vision_encoder_quantized.onnx': (8882165, 'cce23c7b2e5d4f330932738fb67ba518e04b0d99ccdd1cccd22a7da4e01f2971'),
    'prompt_encoder_mask_decoder_quantized.onnx': (4903810, 'cb90b279f549d2cab7fd6e20c38522438c65d84bdcca3d2a764cff7d857fdce2'),
}
_INFERENCE_LOCK = Lock()
_SESSIONS: dict[tuple, tuple] = {}
MODEL_CACHE = _SESSIONS


class ModelUnavailableError(RuntimeError):
    """Optional model/runtime missing, corrupt or unable to run."""


class SegmentationBusyError(RuntimeError):
    """This worker already has an expensive model request in flight."""


@dataclass(frozen=True)
class CutoutResult:
    mask: np.ndarray
    method: str
    model_id: str | None = None
    warnings: tuple[str, ...] = ()


def model_directory() -> Path:
    return Path(os.environ.get('HANDWRITE_MODEL_DIR', '.models/slimsam')).expanduser().resolve()


def model_files(variant: str) -> tuple[str, str]:
    if variant not in {'fp32', 'int8'}:
        raise ModelUnavailableError('Model variant must be fp32 or int8.')
    suffix = '_quantized' if variant == 'int8' else ''
    return f'vision_encoder{suffix}.onnx', f'prompt_encoder_mask_decoder{suffix}.onnx'


def verify_asset(path: Path) -> None:
    size, expected = MODEL_ASSETS[path.name]
    if not path.is_file() or path.stat().st_size != size:
        raise ModelUnavailableError('SlimSAM weights are missing or incomplete. Run scripts/install_segmentation_model.py.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ModelUnavailableError('SlimSAM weights failed integrity verification. Reinstall the pinned model.')


def _sessions(variant: str):
    directory = model_directory()
    paths = [directory / name for name in model_files(variant)]
    try:
        stamps = tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
    except OSError as exc:
        raise ModelUnavailableError('SlimSAM is not installed. Run scripts/install_segmentation_model.py.') from exc
    key = ('slimsam', str(directory), variant, MODEL_REVISION, stamps)
    if key in _SESSIONS:
        return _SESSIONS[key]
    for path in paths:
        verify_asset(path)
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise ModelUnavailableError('Install the optional ML runtime with pip install -e ".[ml]".') from exc
    try:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        pair = tuple(ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider']) for path in paths)
    except Exception as exc:
        raise ModelUnavailableError('Could not load the pinned SlimSAM model with the installed CPU runtime.') from exc
    # Bound memory: only the selected pair is retained in a serving process.
    _SESSIONS.clear()
    _SESSIONS[key] = pair
    return pair


def _prepare_source(image_bgr: np.ndarray, rectangle) -> tuple[np.ndarray, tuple[float, ...]]:
    if (not isinstance(image_bgr, np.ndarray) or image_bgr.dtype != np.uint8
            or image_bgr.ndim != 3 or image_bgr.shape[2] != 3
            or min(image_bgr.shape[:2]) < 8 or image_bgr.size > 60_000_000):
        raise ValueError('A bounded color image of at least 8 pixels per side is required.')
    if not isinstance(rectangle, (list, tuple)) or len(rectangle) != 4:
        raise ValueError('rectangle must contain left, top, right, bottom.')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in rectangle):
        raise ValueError('Rectangle coordinates must be finite normalized numbers.')
    left, top, right, bottom = map(float, rectangle)
    if left >= right or top >= bottom:
        raise ValueError('Rectangle must have positive width and height.')
    height, width = image_bgr.shape[:2]
    scale = min(1.0, MAX_CUTOUT_SIDE / max(height, width))
    size = (round(width * scale), round(height * scale))
    if min(size) < 8 or (right-left)*size[0] < 3 or (bottom-top)*size[1] < 3:
        raise ValueError('Crop closer around the character or select a larger rectangle.')
    if size != (width, height):
        image_bgr = cv2.resize(image_bgr, size, interpolation=cv2.INTER_AREA)
    return image_bgr, (left, top, right, bottom)


def _encode_image(image_bgr: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    height, width = image_bgr.shape[:2]
    scale = 1024 / max(height, width)
    new_height, new_width = int(height * scale + 0.5), int(width * scale + 0.5)
    # SAM's processor uses PIL bilinear resize, RGB, ImageNet normalization,
    # then zero padding on the bottom/right of the normalized tensor.
    rgb = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
    resized = np.asarray(rgb.resize((new_width, new_height), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
    normalized = (resized - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    pixels = np.zeros((1, 3, 1024, 1024), dtype=np.float32)
    pixels[0, :, :new_height, :new_width] = normalized.transpose(2, 0, 1)
    return pixels, (new_height, new_width)


def _validate_points(points, rectangle) -> list[dict]:
    if points is None:
        return []
    if not isinstance(points, list) or len(points) > 16:
        raise ValueError('Provide at most 16 foreground/background points.')
    left, top, right, bottom = rectangle
    for point in points:
        if not isinstance(point, dict) or set(point) != {'x', 'y', 'label'}:
            raise ValueError('Each point must have x, y and label.')
        for axis in ('x', 'y'):
            value = point[axis]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Point coordinates must be finite normalized numbers.')
        if isinstance(point['label'], bool) or not isinstance(point['label'], int) or point['label'] not in (0, 1):
            raise ValueError('Point label must be 1 (keep) or 0 (exclude).')
        if point['label'] == 1 and not (left <= point['x'] <= right and top <= point['y'] <= bottom):
            raise ValueError('Keep points must be inside the selected rectangle.')
    return points


def _rectangle_area_pixels(shape: tuple[int, int], rectangle: tuple[float, float, float, float]) -> int:
    height, width = shape
    left, top, right, bottom = rectangle
    x0, y0 = int(left * width), int(top * height)
    x1, y1 = min(width, math.ceil(right * width)), min(height, math.ceil(bottom * height))
    return max(0, x1 - x0) * max(0, y1 - y0)


def _reject_selection_that_is_really_the_box(mask: np.ndarray, rectangle: tuple[float, float, float, float]) -> None:
    area = _rectangle_area_pixels(mask.shape[:2], rectangle)
    if area <= 0:
        raise ValueError('Select a larger rectangle around the entire character.')
    foreground = int(np.count_nonzero(mask < 128))
    if foreground / area > 0.85:
        raise ValueError('This method selected almost the entire box, not the character. Try threshold extraction, a tighter crop, or prompt points.')


def predict_slimsam(image_bgr: np.ndarray, rectangle, *, variant: str = 'fp32', points=None) -> np.ndarray:
    image_bgr, rectangle = _prepare_source(image_bgr, rectangle)
    points = _validate_points(points, rectangle)
    if not any(p['label'] == 1 for p in points):
        raise ValueError('Mark at least one keep point on the character before learned extraction.')
    if not _INFERENCE_LOCK.acquire(blocking=False):
        raise SegmentationBusyError('Segmentation is busy. Try again shortly.')
    try:
        encoder, decoder = _sessions(variant)
        pixels, (new_height, new_width) = _encode_image(image_bgr)
        left, top, right, bottom = rectangle
        # This HF export embeds POINT labels 0/1 only, not box labels 2/3.
        coordinates = np.array([[[[p['x'] * new_width, p['y'] * new_height] for p in points]]], dtype=np.float32)
        labels = np.array([[[p['label'] for p in points]]], dtype=np.int64)
        encoded = encoder.run(None, {'pixel_values': pixels})
        embeddings = dict(zip((o.name for o in encoder.get_outputs()), encoded, strict=True))
        inputs = {'input_points': coordinates, 'input_labels': labels, **embeddings}
        outputs = decoder.run(None, {i.name: inputs[i.name] for i in decoder.get_inputs()})
        decoded = dict(zip((o.name for o in decoder.get_outputs()), outputs, strict=True))
        scores = decoded['iou_scores'][0, 0]
        logits = decoded['pred_masks'][0, 0, int(np.argmax(scores))]
        padded = cv2.resize(logits, (1024, 1024), interpolation=cv2.INTER_LINEAR)
        height, width = image_bgr.shape[:2]
        logits = cv2.resize(padded[:new_height, :new_width], (width, height), interpolation=cv2.INTER_LINEAR)
        selected = logits > 0
        # Respect the user's selected region. No topology cleanup is applied.
        allowed = np.zeros((height, width), dtype=bool)
        allowed[int(top*height):math.ceil(bottom*height), int(left*width):math.ceil(right*width)] = True
        selected &= allowed
        if np.count_nonzero(selected) < 4:
            raise ValueError('Model found no foreground. Adjust the rectangle or use ink/classical extraction.')
        return np.where(selected, 0, 255).astype(np.uint8)
    except (ModelUnavailableError, SegmentationBusyError, ValueError):
        raise
    except Exception as exc:
        raise ModelUnavailableError('SlimSAM inference failed. Try classical extraction or check the model installation.') from exc
    finally:
        _INFERENCE_LOCK.release()


def segment_image(
    image_bgr: np.ndarray,
    rectangle,
    *,
    method: str = 'auto',
    style: str = 'silhouette',
    threshold: int = 128,
    points=None,
    ink_polarity: str = 'dark',
) -> CutoutResult:
    if method not in {'auto', 'model', 'grabcut', 'box-model'}:
        raise ValueError('method must be auto, model, grabcut or box-model.')
    if style not in {'silhouette', 'ink'}:
        raise ValueError('style must be silhouette or ink.')
    if isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold <= 254:
        raise ValueError('threshold must be an integer between 1 and 254.')
    if ink_polarity not in {'dark', 'light', 'auto'}:
        raise ValueError('ink_polarity must be dark, light or auto.')
    source, rectangle = _prepare_source(image_bgr, rectangle)
    warnings: tuple[str, ...] = ()
    actual_method, model_id = 'grabcut', None

    if method == 'box-model':
        if points is not None and (not isinstance(points, list) or len(points) > 0):
            raise ValueError('box-model uses only the selected rectangle; omit foreground/background points.')
        from .efficient_segmentation import MODEL_REPO as EFFICIENT_MODEL_REPO
        from .efficient_segmentation import MODEL_REVISION as EFFICIENT_MODEL_REVISION
        from .efficient_segmentation import predict_efficientsam_box

        mask = predict_efficientsam_box(source, rectangle)
        actual_method = 'efficientsam'
        model_id = f'{EFFICIENT_MODEL_REPO}@{EFFICIENT_MODEL_REVISION}:ti-box'
    else:
        points = _validate_points(points, rectangle)
        has_positive = any(p['label'] == 1 for p in points)
        if method == 'model' and not has_positive:
            raise ValueError('Mark at least one keep point on the character before learned extraction.')
        if method != 'grabcut' and has_positive:
            variant = os.environ.get('HANDWRITE_SEGMENTATION_VARIANT', 'fp32')
            try:
                mask = predict_slimsam(source, rectangle, variant=variant, points=points)
                actual_method = 'slimsam'
                model_id = f'{MODEL_REPO}@{MODEL_REVISION}:{variant}'
            except ModelUnavailableError as exc:
                if method == 'model':
                    raise
                foreground = extract_foreground_result(source, rectangle)
                warnings = (f'Learned segmentation unavailable; used {foreground.method} instead. {exc}', *foreground.warnings)
                mask = foreground.mask
                actual_method = foreground.method
        else:
            if method == 'auto':
                warnings = ('Used classical extraction. Add a keep point on the character to try learned segmentation.',)
            foreground = extract_foreground_result(source, rectangle)
            mask = foreground.mask
            actual_method = foreground.method
            warnings = (*warnings, *foreground.warnings)
    _reject_selection_that_is_really_the_box(mask, rectangle)
    if style == 'ink':
        if ink_polarity == 'auto':
            detail = threshold_foreground(source, rectangle, polarity='auto', adaptive=False)
            mask = np.where((mask < 128) & (detail < 128), 0, 255).astype(np.uint8)
        else:
            gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
            detail = gray < threshold if ink_polarity == 'dark' else gray > threshold
            mask = np.where((mask < 128) & detail, 0, 255).astype(np.uint8)
        foreground_pixels = int(np.count_nonzero(mask < 128))
        if foreground_pixels < max(4, int(mask.size * 0.0005)):
            raise ValueError('No ink detail remains at this threshold. Increase it or choose silhouette.')
    return CutoutResult(mask=mask, method=actual_method, model_id=model_id, warnings=warnings)
