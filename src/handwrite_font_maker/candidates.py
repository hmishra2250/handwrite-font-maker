"""Visual extraction alternatives with bounded, isolated optional model work.

Extraction uses bounded source coordinates; final masks have explicit crop/canvas transforms.
SVGs are true traced paths, never embedded PNGs.
This module makes no network requests and never downloads models.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image

from .rectify import load_bgr


def source_and_roi(image, rectangle):
    h, w = image.shape[:2]
    scale = min(1., 1024 / max(h, w))
    image = cv2.resize(image, (max(8, round(w*scale)), max(8, round(h*scale))), interpolation=cv2.INTER_AREA) if scale < 1 else image
    h, w = image.shape[:2]
    left, top, right, bottom = rectangle
    x0, y0, x1, y1 = int(left*w), int(top*h), min(w, int(np.ceil(right*w))), min(h, int(np.ceil(bottom*h)))
    if x1-x0 < 8 or y1-y0 < 8:
        raise ValueError('Select a larger area around the letter.')
    return image, (x0, y0, x1, y1)


def ink_masks(image, rectangle):
    image, (x0, y0, x1, y1) = source_and_roi(image, rectangle)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    crop = gray[y0:y1, x0:x1]
    # Polarity comes from the border, not a requirement that paper be white.
    border = np.concatenate((crop[0], crop[-1], crop[:, 0], crop[:, -1]))
    cutoff, _ = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    light = float(np.median(border)) <= cutoff
    polarity = 'light-on-dark' if light else 'dark-on-light'
    options = []
    for name, blurred in [('clean', crop), ('soft', cv2.GaussianBlur(crop, (5, 5), .9))]:
        _, binary = cv2.threshold(blurred, 0, 255, (cv2.THRESH_BINARY if light else cv2.THRESH_BINARY_INV) | cv2.THRESH_OTSU)
        mask = np.full(gray.shape, 255, np.uint8)
        mask[y0:y1, x0:x1] = 255-binary
        options.append((name, mask, polarity))
    # A local-lighting alternative, not a blanket cleanup that removes dots/holes.
    prepared = 255-crop if light else crop
    local = cv2.adaptiveThreshold(prepared, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12)
    mask = np.full(gray.shape, 255, np.uint8)
    mask[y0:y1, x0:x1] = local
    options.append(('adaptive', mask, polarity))
    return image, options


def vector_candidate(mask, *, name, label, method, polarity=None, warnings=()):
    foreground = mask < 128
    coverage = float(foreground.mean())
    if coverage < .0005 or coverage > .70:
        raise ValueError('This option could not isolate a usable letter.')
    # Remove photographic margins without resampling strokes. The font builder
    # derives em sizing from this canvas, so raw phone whitespace would make A tiny.
    ys, xs = np.where(foreground)
    left, top, right, bottom = int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1)
    tight = mask[top:bottom, left:right]
    canvas_h = max(16, int(np.ceil(tight.shape[0] / .70)))
    canvas_w = max(16, int(np.ceil(tight.shape[1] / .80)))
    offset_y = round(canvas_h * .8) - tight.shape[0]
    offset_x = (canvas_w-tight.shape[1])//2
    normalized = np.full((canvas_h, canvas_w), 255, np.uint8)
    normalized[offset_y:offset_y+tight.shape[0], offset_x:offset_x+tight.shape[1]] = tight
    mask = normalized
    transform = {'sourceBounds': [left,top,right,bottom], 'canvasSize': [canvas_w,canvas_h],
                 'offset': [offset_x,offset_y], 'suggestedBaseline': .8, 'resampled': False}
    with tempfile.TemporaryDirectory(prefix='capture_vector_') as tmp:
        root = Path(tmp)
        # PBM black is the foreground; no hole filling or largest-component deletion.
        Image.fromarray(mask).convert('1').save(root/'mask.pbm')
        subprocess.run(['potrace', str(root/'mask.pbm'), '--svg', '--tight', '--turdsize', '0',
                        '--alphamax', '0.9', '--opttolerance', '.15', '--unit', '100', '--output', str(root/'glyph.svg')],
                       check=True, capture_output=True, timeout=4)
        svg = (root/'glyph.svg').read_bytes()
    if len(svg) > 2_000_000 or b'<image' in svg or b'<path' not in svg:
        raise ValueError('Tracing did not produce a vector outline.')
    png = io.BytesIO(); Image.fromarray(mask).save(png, format='PNG')
    return {'id': name+'-'+hashlib.sha256(png.getvalue()).hexdigest()[:10], 'label': label,
            'maskDataUrl': 'data:image/png;base64,'+base64.b64encode(png.getvalue()).decode(),
            'svgDataUrl': 'data:image/svg+xml;base64,'+base64.b64encode(svg).decode(),
            'width': mask.shape[1], 'height': mask.shape[0], 'method': method,
            'polarity': polarity, 'warnings': list(warnings), 'provenance': {'normalization': transform}}


def _method_mask(image_path, rectangle, method, output):
    from .segmentation import segment_image
    image = load_bgr(image_path)
    kwargs = {}
    if method == 'model':
        prepared, options = ink_masks(image, rectangle)
        coords = np.argwhere(options[0][1] < 128)
        if not len(coords):
            raise ValueError('No clear foreground point for learned extraction.')
        center = np.median(coords, axis=0)
        y, x = coords[np.argmin(np.sum((coords-center)**2, axis=1))]
        kwargs['points'] = [{'x': float((x+.5)/prepared.shape[1]), 'y': float((y+.5)/prepared.shape[0]), 'label': 1}]
    result = segment_image(image, rectangle, method=method, style='silhouette', **kwargs)
    Image.fromarray(result.mask).save(output)
    print(json.dumps({'method': result.method, 'modelId': result.model_id, 'warnings': list(result.warnings), 'points': kwargs.get('points', [])}))


def generate_candidates(image_path: Path, rectangle, stage: str):
    image = load_bgr(image_path)
    prepared, options = ink_masks(image, rectangle)
    candidates, failures = [], []
    if stage == 'ink':
        labels = {'clean': 'Clean letter', 'soft': 'Softer edges', 'adaptive': 'Uneven-lighting option'}
        reference = options[0][1] < 128
        for name, mask, polarity in options:
            try:
                if name == 'adaptive':
                    selected = mask < 128
                    agreement = np.count_nonzero(reference & selected) / max(1, np.count_nonzero(reference | selected))
                    if agreement < .65:
                        failures.append({'method': name, 'message': 'The local-lighting option changed too much of the letter and was excluded.'})
                        continue
                candidates.append(vector_candidate(mask, name=name, label=labels[name], method='threshold-'+name, polarity=polarity))
            except (ValueError, subprocess.SubprocessError, OSError):
                failures.append({'method': name, 'message': 'This option did not produce a usable vector. Try adjusting the selection.'})
    else:
        # One request's optional methods run concurrently, each in a killable process.
        # The API admits only one optional stage at a time; fast stages have a separate slot.
        reference = options[0][1] < 128
        gray = cv2.cvtColor(prepared, cv2.COLOR_BGR2GRAY)
        high_contrast = (0 < reference.mean() < .15 and
                         abs(float(np.median(gray[reference]))-float(np.median(gray[~reference]))) > 80)
        def run_method(item):
            method, label = item
            try:
                with tempfile.TemporaryDirectory(prefix='capture_method_') as tmp:
                    output = Path(tmp)/'mask.png'
                    env = dict(os.environ, OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
                    run = subprocess.run([sys.executable, '-m', 'handwrite_font_maker.candidates', '--image', str(image_path),
                                          '--rectangle', json.dumps(rectangle), '--method', method, '--output', str(output)],
                                         capture_output=True, text=True, timeout=25, env=env)
                    if run.returncode:
                        return None, {'method': method, 'message': 'This extraction method is unavailable or could not isolate the letter.'}
                    info = json.loads(run.stdout.strip().splitlines()[-1])
                    mask = np.asarray(Image.open(output).convert('L'))
                    selected = mask < 128
                    if high_contrast and (selected.shape != reference.shape or
                        np.count_nonzero(selected & reference)/max(1,np.count_nonzero(selected | reference)) < .45):
                        return None, {'method': method, 'message': 'This option selected the background or changed too much of the letter and was excluded.'}
                    candidate = vector_candidate(mask, name=method, label=label, method=info['method'], warnings=info['warnings'])
                    candidate['provenance'] = {**candidate['provenance'], 'modelId': info.get('modelId'), 'points': info.get('points', [])}
                    return candidate, None
            except subprocess.TimeoutExpired:
                return None, {'method': method, 'message': 'This option exceeded its time limit; your other options are still usable.'}
            except (ValueError, subprocess.SubprocessError, OSError):
                return None, {'method': method, 'message': 'This option did not produce a usable vector.'}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for candidate, failure in pool.map(run_method, [('grabcut', 'Object outline'), ('box-model', 'AI object outline'), ('model', 'AI detail outline')]):
                if candidate is not None:
                    candidates.append(candidate)
                if failure is not None:
                    failures.append(failure)
    for candidate in candidates:
        candidate['provenance'] = {**candidate.get('provenance', {}), 'pipelineVersion': 'candidates-v1', 'rectangle': list(rectangle), 'originalSourceSize': list(image.shape[1::-1]), 'processingSourceSize': list(prepared.shape[1::-1]), 'processingScale': [prepared.shape[1]/image.shape[1], prepared.shape[0]/image.shape[0]], 'maskSize': [candidate['width'], candidate['height']], 'thresholdSelection': 'otsu' if stage == 'ink' else None, 'smoothingSigma': .9 if candidate['method'] == 'threshold-soft' else 0, 'vectorizer': {'name': 'potrace', 'alphamax': .9, 'opttolerance': .15, 'turdsize': 0}}
    return {'candidates': candidates, 'failures': failures, 'stage': stage}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--rectangle', required=True)
    parser.add_argument('--method', choices=['grabcut','box-model','model'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    _method_mask(args.image, json.loads(args.rectangle), args.method, args.output)


if __name__ == '__main__':
    main()
