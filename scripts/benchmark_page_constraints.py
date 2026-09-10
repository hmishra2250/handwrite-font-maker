#!/usr/bin/env python3
"""Compare originals with oracle reference-centered crops; NOT new phone captures.

Uses the pinned/verified SmartDoc corpus established by benchmark_real_pages.py.
Crops change the page-area constraint but remove clutter using reference corners,
so cannot estimate unassisted capture accuracy. All clips have already been seen.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw
from benchmark_real_pages import quad_metrics, summarize
from handwrite_font_maker.rectify import detect_page_corners, MIN_PAGE_AREA_RATIO


def reference_crop(image, reference):
    height, width = image.shape[:2]
    low, high = reference.min(axis=0), reference.max(axis=0)
    padding = (high-low)*.28
    left, top = np.maximum(np.floor(low-padding), 0).astype(int)
    right, bottom = np.minimum(np.ceil(high+padding)+1, [width,height]).astype(int)
    return image[top:bottom,left:right].copy(), reference-[left,top], [int(left),int(top),int(right),int(bottom)]


def run(source_report: Path, source_root: Path, output: Path):
    previous=json.loads(source_report.read_text())
    output.mkdir(parents=True,exist_ok=True)
    rows=[]; tiles=[]
    for original in previous['samples']:
        sid=original['sample_id']; path=source_root/f'{sid}.png'
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        expected=original.get('image_sha256') or original.get('sha256')
        if not expected or digest != expected:
            raise ValueError(f'Source hash mismatch or missing for {sid}')
        image=cv2.imread(str(path)); reference=np.asarray(original['reference_corners_tl_tr_br_bl'],np.float32)
        cropped, shifted, crop_box=reference_crop(image,reference)
        for variant,source,ref,box in [('original',image,reference,None),('oracle-centered-crop',cropped,shifted,crop_box)]:
            row={'sample_id':sid,'source_group':original['source_group'],'variant':variant,'source_sha256':digest,
                 'crop_box':box,'image_size':[source.shape[1],source.shape[0]],'reference_corners':ref.tolist(),
                 'reference_area_ratio':abs(cv2.contourArea(ref.astype(np.float32)))/(source.shape[0]*source.shape[1])}
            try:
                corners=detect_page_corners(source)
                row.update(status='detected',predicted_corners=corners.tolist(),metrics=quad_metrics(corners,ref,source.shape[:2]))
            except ValueError as exc: row.update(status='rejected',error=str(exc))
            rows.append(row)
            if variant=='oracle-centered-crop':
                panel=Image.fromarray(cv2.cvtColor(source,cv2.COLOR_BGR2RGB)); draw=ImageDraw.Draw(panel)
                draw.line([tuple(p) for p in ref]+[tuple(ref[0])],fill='lime',width=3)
                if row['status']=='detected':
                    points=row['predicted_corners'];draw.line([tuple(p) for p in points]+[tuple(points[0])],fill='red',width=3)
                panel.thumbnail((280,210));tile=Image.new('RGB',(290,240),'white');tile.paste(panel,(5,25));ImageDraw.Draw(tile).text((5,4),f"{sid} {row['status']}",fill='black');tiles.append(tile)
    report={'scope':'24 original frames + 24 oracle-centered derived crops; three correlated already-seen clips, NOT 48 independent captures or untouched heldout data.',
            'source':{k:previous[k] for k in ['source_url','download_url','archive_sha256','license','license_url','attribution']},'crop_policy':'Reference bbox expanded 28% per side, clipped to image. Oracle crop removes clutter and changes apparent page area; does not replicate moving a camera.',
            'minimum_page_area_ratio':MIN_PAGE_AREA_RATIO,'summary':{v:summarize([r for r in rows if r['variant']==v]) for v in ['original','oracle-centered-crop']},'samples':rows}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    sheet=Image.new('RGB',(290*4,240*6),'#ddd')
    for i,tile in enumerate(tiles):sheet.paste(tile,((i%4)*290,(i//4)*240))
    sheet.save(output/'contact-sheet.jpg',quality=85)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report',type=Path,default=Path('docs/research/real-page-evidence/report.json'))
    parser.add_argument('--source-root',type=Path,default=Path('output/detection-sources/pages'))
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.source_report,args.source_root,args.output_dir)['summary'],indent=2))
