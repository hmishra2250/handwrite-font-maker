#!/usr/bin/env python3
"""Small isolated-process CPU/memory probe; not a production latency estimate."""
import argparse
import json
from pathlib import Path
import platform
import resource
import statistics
import time

import cv2

from handwrite_font_maker.segmentation import MODEL_ASSETS, MODEL_REPO, MODEL_REVISION, model_files, predict_slimsam

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model', choices=['slimsam', 'efficientsam'], default='slimsam')
parser.add_argument('--variant', choices=['fp32','int8'], default='fp32')
parser.add_argument('--image', type=Path, default=Path('output/object-api-smoke/source.png'))
parser.add_argument('--runs', type=int, default=4)
args = parser.parse_args()
if not 2 <= args.runs <= 10:
    parser.error('Use 2..10 runs; this probe is intentionally bounded.')
image = cv2.imread(str(args.image))
if image is None:
    parser.error('Run scripts/smoke_object_capture.py first, or supply a source image.')
points = [{'x':.275,'y':.45,'label':1},{'x':.18,'y':.14,'label':1},{'x':.5,'y':.5,'label':0}]
if args.model == 'efficientsam':
    if args.variant != 'fp32':
        parser.error('EfficientSAM only supports the pinned fp32 variant.')
    from handwrite_font_maker.efficient_segmentation import MODEL_ASSETS, MODEL_REPO, MODEL_REVISION, predict_efficientsam_box
    weight_names = list(MODEL_ASSETS)
else:
    weight_names = model_files(args.variant)
rows = []
for index in range(args.runs):
    before = resource.getrusage(resource.RUSAGE_SELF)
    start = time.perf_counter()
    mask = (predict_efficientsam_box(image, [.1,.05,.9,.9]) if args.model == 'efficientsam'
            else predict_slimsam(image,[.1,.05,.9,.9],variant=args.variant,points=points))
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rows.append({'kind':'cold' if index == 0 else 'warm','wall_seconds':round(time.perf_counter()-start,4),'cpu_seconds':round(usage.ru_utime+usage.ru_stime-before.ru_utime-before.ru_stime,4),'foreground_pixels':int((mask<128).sum())})
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
peak_bytes = peak if platform.system() == 'Darwin' else peak*1024
print(json.dumps({'model':MODEL_REPO,'revision':MODEL_REVISION,'variant':args.variant,'provider':'CPUExecutionProvider','intra_op_threads':2,'inter_op_threads':1,'environment':platform.platform(),'python':platform.python_version(),'weights_bytes':sum(MODEL_ASSETS[x][0] for x in weight_names),'runs':rows,'warm_median_seconds':statistics.median(x['wall_seconds'] for x in rows[1:]),'process_peak_rss_bytes':peak_bytes,'scope':'Isolated process on a shared development host; repeated synthetic image with known prompts. No representative p95, cloud cost or general quality claim.'},indent=2))
