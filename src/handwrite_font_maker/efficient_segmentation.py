"""Optional, offline EfficientSAM box-prompt inference.

This serving path is explicit-only (`method='box-model'` in segmentation) and
uses the selected rectangle as a genuine box prompt. It never downloads weights
at request time and shares segmentation's model lock/session cache so a worker
process keeps at most one ONNX model pair loaded.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

import cv2
import numpy as np

from . import segmentation as _shared
from .segmentation import MODEL_CACHE, ModelUnavailableError, SegmentationBusyError, _prepare_source

MODEL_REPO = 'yunyangx/EfficientSAM'
MODEL_REVISION = 'd8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036'
MODEL_ASSETS = {
    'efficientsam_ti_encoder.onnx': (24799761, '84ed466ffcc5c1f8d08409bc34a23bb364ab2c15e402cb12d4335a42be0e0951'),
    'efficientsam_ti_decoder.onnx': (16565728, 'a62f8fa5ea080447c0689418d69e58f1e83e0b7adf9c142e2bd9bcc8045c0b11'),
}


def model_directory() -> Path:
    return Path(os.environ.get('HANDWRITE_EFFICIENTSAM_MODEL_DIR', '.models/efficientsam')).expanduser().resolve()


def model_files() -> tuple[str, str]:
    return 'efficientsam_ti_encoder.onnx', 'efficientsam_ti_decoder.onnx'


def verify_asset(path: Path) -> None:
    try:
        size, expected = MODEL_ASSETS[path.name]
    except KeyError as exc:
        raise ModelUnavailableError('Unknown EfficientSAM asset.') from exc
    if not path.is_file() or path.stat().st_size != size:
        raise ModelUnavailableError('EfficientSAM weights are missing or incomplete.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ModelUnavailableError('EfficientSAM weights failed integrity verification. Reinstall the pinned model.')


def _sessions():
    directory = model_directory()
    paths = [directory / name for name in model_files()]
    try:
        stamps = tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
    except OSError as exc:
        raise ModelUnavailableError('EfficientSAM is not installed. Install the pinned model files first.') from exc
    key = ('efficientsam', str(directory), MODEL_REVISION, stamps)
    if key in MODEL_CACHE:
        return MODEL_CACHE[key]
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
        raise ModelUnavailableError('Could not load the pinned EfficientSAM model with the installed CPU runtime.') from exc
    # Shared bounded cache: switching model families drops the previous pair.
    MODEL_CACHE.clear()
    MODEL_CACHE[key] = pair
    return pair


def predict_efficientsam_box(image_bgr: np.ndarray, rectangle) -> np.ndarray:
    source, rectangle = _prepare_source(image_bgr, rectangle)
    if not _shared._INFERENCE_LOCK.acquire(blocking=False):
        raise SegmentationBusyError('Segmentation is busy. Try again shortly.')
    try:
        encoder, decoder = _sessions()
        height, width = source.shape[:2]
        image = cv2.cvtColor(source, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        embeddings = encoder.run(None, {'batched_images': image})[0]
        left, top, right, bottom = rectangle
        coords = np.array([[[[left * width, top * height], [right * width, bottom * height]]]], dtype=np.float32)
        labels = np.array([[[2, 3]]], dtype=np.float32)
        outputs = decoder.run(
            None,
            {
                'image_embeddings': embeddings,
                'batched_point_coords': coords,
                'batched_point_labels': labels,
                'orig_im_size': np.array([height, width], dtype=np.int64),
            },
        )
        masks, scores = outputs[:2]
        selected = masks[0, 0, int(np.argmax(scores[0, 0]))] >= 0
        if selected.shape != (height, width):
            raise ModelUnavailableError('EfficientSAM returned an unexpected mask shape.')
        roi = np.zeros((height, width), dtype=bool)
        roi[int(top * height):math.ceil(bottom * height), int(left * width):math.ceil(right * width)] = True
        selected &= roi
        if np.count_nonzero(selected) < 4:
            raise ValueError('Model found no foreground. Adjust the rectangle or use classical extraction.')
        return np.where(selected, 0, 255).astype(np.uint8)
    except (ModelUnavailableError, SegmentationBusyError, ValueError):
        raise
    except Exception as exc:
        raise ModelUnavailableError('EfficientSAM inference failed. Try classical extraction or check the model installation.') from exc
    finally:
        _shared._INFERENCE_LOCK.release()
