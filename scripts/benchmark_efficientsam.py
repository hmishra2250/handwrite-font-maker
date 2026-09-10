#!/usr/bin/env python3
"""Experimental second-family comparison, not a serving backend.

EfficientSAM-Ti uses genuine box labels 2/3 and internal preprocessing. Unlike
SlimSAM's benchmark, this runner does not use reference-derived prompt points.
"""
import argparse
import hashlib
from pathlib import Path
import tempfile

import cv2
import numpy as np
import requests

from handwrite_font_maker.segmentation import _prepare_source
from benchmark_segmentation import grabcut_segmenter, run_benchmark

REVISION = 'd8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036'
ROOT = Path('.models/efficientsam')
ASSETS = {
    'efficientsam_ti_encoder.onnx': (24799761, '84ed466ffcc5c1f8d08409bc34a23bb364ab2c15e402cb12d4335a42be0e0951'),
    'efficientsam_ti_decoder.onnx': (16565728, 'a62f8fa5ea080447c0689418d69e58f1e83e0b7adf9c142e2bd9bcc8045c0b11'),
}
SESSIONS = None


def verified(path, size, digest):
    return path.is_file() and path.stat().st_size == size and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def install():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in ASSETS.items():
        target = ROOT/name
        if verified(target,size,digest):
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=ROOT, suffix='.part', delete=False) as f:
                temporary = Path(f.name)
                url = f'https://huggingface.co/spaces/yunyangx/EfficientSAM/resolve/{REVISION}/{name}'
                with requests.get(url, stream=True, timeout=(15,90)) as response:
                    response.raise_for_status()
                    received = 0
                    for chunk in response.iter_content(1024*1024):
                        received += len(chunk)
                        if received > size:
                            raise RuntimeError('Checkpoint exceeds pinned size.')
                        f.write(chunk)
            if not verified(temporary,size,digest):
                raise RuntimeError('Checkpoint integrity mismatch.')
            temporary.replace(target)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


def predict(image_bgr, rectangle, prompt_points=()):
    global SESSIONS
    if SESSIONS is None:
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        for name, (size, digest) in ASSETS.items():
            if not verified(ROOT/name,size,digest):
                raise RuntimeError('Run this script with --install to fetch verified research weights.')
        SESSIONS = tuple(ort.InferenceSession(str(ROOT/name),sess_options=options,providers=['CPUExecutionProvider']) for name in ASSETS)
    source, rectangle = _prepare_source(image_bgr,rectangle)
    height,width = source.shape[:2]
    image = cv2.cvtColor(source,cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2,0,1)[None]/255.0
    encoder,decoder = SESSIONS
    embeddings = encoder.run(None,{'batched_images':image})[0]
    left,top,right,bottom = rectangle
    coords = np.array([[[[left*width,top*height],[right*width,bottom*height]]]],np.float32)
    outputs = decoder.run(None,{'image_embeddings':embeddings,'batched_point_coords':coords,'batched_point_labels':np.array([[[2,3]]],np.float32),'orig_im_size':np.array([height,width],np.int64)})
    masks,scores = outputs[:2]
    selected = masks[0,0,int(np.argmax(scores[0,0]))] >= 0
    assert selected.shape == (height,width)
    # Match the product ROI policy, with no morphology or component removal.
    roi = np.zeros((height,width),bool)
    roi[int(top*height):int(np.ceil(bottom*height)),int(left*width):int(np.ceil(right*width))] = True
    return np.where(selected & roi,0,255).astype(np.uint8)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true',help='Explicitly download pinned research weights.')
    parser.add_argument('--output-dir',type=Path,default=Path('output/efficientsam-benchmark'))
    args=parser.parse_args()
    if args.install:
        install()
    report=run_benchmark(output_dir=args.output_dir,segmenters={'grabcut':grabcut_segmenter,'efficientsam-ti-box':predict},include_real_probe=True)
    import json
    report['candidate_provenance']={'repository':'yunyangx/EfficientSAM','revision':REVISION,'weights':ASSETS,'prompting':'true box only; ignores reference-assisted point prompts supplied by harness','preprocessing':'raw RGB float0..1; graph resizes and normalizes internally; decoder returns original-size logits'}
    (args.output_dir/'benchmark-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report.get('summary',{}),indent=2))


if __name__=='__main__':
    main()
