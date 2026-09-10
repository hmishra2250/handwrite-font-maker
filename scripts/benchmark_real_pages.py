#!/usr/bin/env python3
"""Pinned SmartDoc sample videos: real page-outline ground-truth evaluation.

24 sampled frames from THREE correlated capture clips, not 24 independent phone
sessions. No handwriting ink masks. Printed pages are out-of-template stress
inputs; this does not measure successful font extraction from our A4 template.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import tarfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from handwrite_font_maker.rectify import MIN_PAGE_AREA_RATIO, detect_page_corners

URL = 'https://zenodo.org/records/1230218/files/sampleDataset.tar.gz?download=1'
SHA256 = '90d1a64f476ffe290ebbddf4337e108d471b9c25420551223f447db972844a9a'
ATTRIBUTION = 'Burie, Chazalon, Coustaty, Eskenazi, Luqman, Mehri, Nayef, Ogier, Prum, Rusinol. ICDAR2015 Competition on Smartphone Document Capture and OCR (SmartDoc). ICDAR 2015.'


def quad_metrics(predicted, reference, shape):
    p, r = np.asarray(predicted, np.float32), np.asarray(reference, np.float32)
    area_p, area_r = abs(cv2.contourArea(p)), abs(cv2.contourArea(r))
    intersection, _ = cv2.intersectConvexConvex(p, r)
    union = area_p + area_r - intersection
    # Corner geometry only: cyclic alignment doesn't assess reading orientation.
    error = min(float(np.sqrt(np.mean(np.sum((p-np.roll(r, shift, axis=0))**2, axis=1)))) for shift in range(4))
    return {'polygon_iou': float(intersection / union) if union else 0.,
            'corner_rmse_px_cyclic': error, 'corner_rmse_image_diagonal': error / float(np.hypot(*shape))}


def summarize(rows):
    successful = [r for r in rows if r['status'] == 'detected']
    return {'frames': len(rows), 'detected': len(successful), 'rejected': len(rows)-len(successful),
            'mean_iou_all_frames_rejections_zero': sum(r.get('metrics', {}).get('polygon_iou', 0) for r in rows)/len(rows) if rows else None,
            'wrong_suggestion_iou_below_090': sum(r['metrics']['polygon_iou'] < .90 for r in successful)}


def run(source_root: Path, output: Path, download: bool = False):
    source_root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    archive = source_root/'sampleDataset.tar.gz'
    if not archive.exists() and download:
        temporary = archive.with_suffix('.part')
        try:
            with urllib.request.urlopen(URL, timeout=90) as response, temporary.open('wb') as target:
                total = 0
                while chunk := response.read(1024*1024):
                    total += len(chunk)
                    if total > 25*1024*1024: raise ValueError('Archive exceeds pinned download bound.')
                    target.write(chunk)
            temporary.replace(archive)
        finally: temporary.unlink(missing_ok=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('SmartDoc archive SHA-256 mismatch.')
    with tarfile.open(archive) as bundle:
        if sum(m.size for m in bundle.getmembers()) > 100*1024*1024: raise ValueError('Archive expansion exceeds bound.')
        bundle.extractall(source_root, filter='data')
    rows, tiles = [], []
    for video in sorted((source_root/'sampleDataset/input_sample').rglob('*.avi')):
        xml = next(source_root.rglob(video.stem+'.gt.xml'))
        frames = ET.parse(xml).findall('.//frame')
        capture = cv2.VideoCapture(str(video))
        group = video.stem
        split = 'heldout' if group == 'letter001' else 'dev'
        for index in np.linspace(0, len(frames)-1, 8, dtype=int):
            annotation = frames[index]
            # Publisher XML indices are 1-based; OpenCV positions are 0-based.
            frame_number = int(annotation.get('index'))
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number-1)
            ok, source = capture.read()
            if not ok: raise ValueError(f'Could not decode {group} frame {frame_number}.')
            if annotation.get('rejected') != 'false': raise ValueError('Unexpected rejected GT; revise protocol explicitly.')
            points = {p.get('name'): [float(p.get('x')), float(p.get('y'))] for p in annotation.findall('point')}
            reference = np.array([points[n] for n in ['tl','tr','br','bl']], np.float32)
            sample_id = f'{group}-{frame_number:04d}'
            image_path = source_root/f'{sample_id}.png'; cv2.imwrite(str(image_path), source)
            row = {'sample_id': sample_id, 'source_group': group, 'split': split, 'frame_index_1based': frame_number,
                   'image_path': str(image_path), 'image_sha256': hashlib.sha256(image_path.read_bytes()).hexdigest(),
                   'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(), 'annotation_sha256': hashlib.sha256(xml.read_bytes()).hexdigest(),
                   'annotation_origin': 'publisher SmartDoc ground_truth XML, not model output',
                   'width': source.shape[1], 'height': source.shape[0], 'reference_corners_tl_tr_br_bl': reference.tolist(),
                   'reference_area_ratio': abs(cv2.contourArea(reference))/(source.shape[0]*source.shape[1])}
            preview = source.copy(); cv2.polylines(preview, [reference.astype(np.int32)], True, (0,200,0), 5)
            started = time.perf_counter()
            try:
                predicted = detect_page_corners(source)
                row.update(status='detected', predicted_corners=predicted.tolist(), metrics=quad_metrics(predicted, reference, source.shape[:2]))
                cv2.polylines(preview, [predicted.astype(np.int32)], True, (0,0,255), 3)
            except ValueError as exc: row.update(status='rejected', reason=str(exc))
            row['seconds'] = time.perf_counter()-started
            rows.append(row)
            tile = Image.fromarray(cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)).resize((384,216))
            cell = Image.new('RGB', (384,248), 'white'); cell.paste(tile, (0,32))
            ImageDraw.Draw(cell).text((4,4), f'{sample_id} {split}: {row["status"]}', fill='black');tiles.append(cell)
        capture.release()
    sheet = Image.new('RGB', (384*4,248*6), 'white')
    for i,tile in enumerate(tiles): sheet.paste(tile, ((i%4)*384,(i//4)*248))
    sheet.save(output/'contact-sheet.jpg', quality=85)
    report = {'source_url': 'https://zenodo.org/records/1230218', 'download_url': URL, 'archive_sha256': SHA256,
              'license': 'CC BY 4.0', 'license_url': 'https://creativecommons.org/licenses/by/4.0/', 'attribution': ATTRIBUTION,
              'scope': __doc__, 'sampling': 'Eight uniformly spaced frames per clip, chosen before detection; group=clip/document. Shared background/camera; only three groups.',
              'split_policy': 'letter001 heldout; datasheet001 and magazine001 dev; no tuning on this dataset in this run',
              'metrics_scope': 'Cyclic corner geometry, not reading orientation; all reference pages present. No absent-page false-positive estimate. IoU .90 is a diagnostic threshold, not a release acceptance claim.',
              'product_area_gate': {'minimum_ratio': MIN_PAGE_AREA_RATIO,
                  'frames_meeting_minimum_area': sum(r['reference_area_ratio'] >= MIN_PAGE_AREA_RATIO for r in rows),
                  'note': 'Out-of-range pages are capture-constraint stress cases; do not present rejection rate as in-spec page detection accuracy.'},
              'summary': summarize(rows), 'by_split': {s:summarize([r for r in rows if r['split']==s]) for s in ['dev','heldout']}, 'samples': rows}
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path('output/detection-sources/pages'))
    parser.add_argument('--output-dir', type=Path, default=Path('docs/research/real-page-evidence'))
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.source_root,args.output_dir,args.download)['summary'], indent=2))
