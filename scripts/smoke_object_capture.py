#!/usr/bin/env python3
"""Local-only actual photo -> cutout -> accepted mask -> persisted job -> TTF canary."""
import argparse
import base64
import io
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8011')
    parser.add_argument('--output-dir', type=Path, default=Path('output/object-api-smoke'))
    parser.add_argument('--method', choices=['auto', 'grabcut', 'model', 'box-model'], default='auto')
    args = parser.parse_args()
    if urlparse(args.base_url).hostname not in {'localhost', '127.0.0.1', '::1'}:
        parser.error('Local development service only.')
    base = args.base_url.rstrip('/')
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def upload(data, name):
        slot = requests.post(base + '/uploads', json={'filename': name, 'contentType': 'image/png', 'sizeBytes': len(data)}, timeout=20)
        slot.raise_for_status()
        key = slot.json()['objectKey']
        response = requests.put(base + '/objects/' + key, data=data, headers={'content-type':'image/png'}, timeout=20)
        response.raise_for_status()
        return {'objectKey':key, 'contentType':'image/png', 'sizeBytes':len(data)}

    source = Image.new('RGB', (400, 400), (220, 225, 235))
    draw = ImageDraw.Draw(source)
    draw.ellipse((90, 90, 300, 315), fill=(45, 100, 35))
    draw.ellipse((150, 155, 245, 245), fill=(220, 225, 235))
    draw.ellipse((60, 45, 83, 68), fill=(45, 100, 35))
    buffer = io.BytesIO()
    source.save(buffer, format='PNG')
    source.save(args.output_dir / 'source.png')
    started = time.monotonic()
    capture = {'inputPhoto':upload(buffer.getvalue(), 'source.png'), 'rectangle':[0.1,0.05,0.9,0.9], 'method':args.method}
    if args.method == 'model':
        capture['points'] = [{'x':.275,'y':.45,'label':1}, {'x':.18,'y':.14,'label':1}, {'x':.5,'y':.5,'label':0}]
    response = requests.post(base + '/capture/foreground', json=capture, timeout=60)
    response.raise_for_status()
    cutout = response.json()
    if args.method == 'model':
        assert cutout['method'] == 'slimsam' and cutout.get('modelId'), 'Expected actual pretrained model, not fallback'
    if args.method == 'box-model':
        assert cutout['method'] == 'efficientsam' and cutout.get('modelId'), 'Expected actual EfficientSAM, not fallback'
    mask_bytes = base64.b64decode(cutout['maskDataUrl'].split(',',1)[1])
    mask = Image.open(io.BytesIO(mask_bytes)).convert('L')
    assert mask.getpixel((195, 200)) == 255, 'Counter was lost'
    assert mask.getpixel((72, 56)) == 0, 'Disconnected seed was lost'
    assert mask.getpixel((110, 180)) == 0, 'Main shape was lost'
    (args.output_dir / 'accepted-mask.png').write_bytes(mask_bytes)
    photo = upload(mask_bytes, 'accepted-mask.png')
    response = requests.post(base + '/jobs', json={'inputPhoto':photo, 'font':{'fontName':'ObjectSmoke','familyName':'Object Smoke','styleName':'Regular'}, 'capture':{'mode':'guided','format':'mask-v1','glyphs':[{'char':'O','inputPhoto':photo,'baseline':0.8}]}}, timeout=20)
    response.raise_for_status()
    job_id = response.json()['jobId']
    deadline = time.monotonic()+360
    while time.monotonic() < deadline:
        response = requests.get(base + '/jobs/' + job_id, timeout=20)
        response.raise_for_status()
        job = response.json()
        if job['status'] == 'failed':
            raise RuntimeError(str(job.get('error')))
        if job['status'] == 'succeeded':
            break
        time.sleep(1)
    else:
        raise TimeoutError('Font build exceeded 360 seconds')
    artifact = next(a for a in job['artifacts'] if a['kind']=='ttf')
    response = requests.get(base + '/objects/' + artifact['objectKey'], timeout=20)
    response.raise_for_status()
    font_path = args.output_dir / 'ObjectSmoke.ttf'
    font_path.write_bytes(response.content)
    font = ImageFont.truetype(str(font_path), 130)
    proof = Image.new('RGB', (500, 240), 'white')
    ImageDraw.Draw(proof).text((25,30), 'O O O', font=font, fill='black')
    proof.save(args.output_dir / 'proof.png')
    report = {'status':job['status'], 'job_id':job_id, 'method':cutout['method'], 'model_id':cutout.get('modelId'), 'warnings':cutout.get('warnings', []), 'wall_seconds':round(time.monotonic()-started,3), 'ttf_bytes':len(response.content), 'scope':'Synthetic color object; actual HTTP segmentation, accepted-mask upload, persisted build, TTF/FreeType proof. Not real-photo accuracy.'}
    (args.output_dir / 'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
