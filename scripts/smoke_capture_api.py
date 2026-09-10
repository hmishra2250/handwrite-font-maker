#!/usr/bin/env python3
"""Exercise real guided upload -> persisted job -> font download on localhost."""
from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8011')
    parser.add_argument('--output-dir', type=Path, default=Path('output/api-smoke'))
    args = parser.parse_args()
    if urlparse(args.base_url).hostname not in {'localhost', '127.0.0.1', '::1'}:
        parser.error('This canary is intentionally limited to a local development service.')
    base = args.base_url.rstrip('/')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    glyphs = []
    for char in ('A', 'i', 'O', 'g', '-'):
        mask = Image.new('L', (256, 256), 255)
        draw = ImageDraw.Draw(mask)
        if char == 'A':
            draw.line([(40, 200), (125, 35), (210, 200)], fill=0, width=14)
            draw.line([(80, 128), (170, 128)], fill=0, width=12)
        elif char == 'i':
            draw.ellipse((108, 55, 130, 77), fill=0)
            draw.rectangle((109, 105, 129, 200), fill=0)
        elif char == 'O':
            draw.ellipse((45, 35, 205, 200), outline=0, width=16)
        elif char == 'g':
            draw.ellipse((65, 75, 165, 180), outline=0, width=14)
            draw.line([(160, 125), (160, 226), (92, 235)], fill=0, width=14)
        else:
            draw.rectangle((45, 125, 210, 142), fill=0)
        buffer = io.BytesIO()
        mask.save(buffer, format='PNG')
        data = buffer.getvalue()
        mask.save(args.output_dir / f'{ord(char):04x}.png')
        slot = requests.post(base + '/uploads', json={'filename': f'{ord(char):04x}.png', 'contentType': 'image/png', 'sizeBytes': len(data)}, timeout=20)
        slot.raise_for_status()
        key = slot.json()['objectKey']
        uploaded = requests.put(base + '/objects/' + key, data=data, headers={'content-type': 'image/png'}, timeout=20)
        uploaded.raise_for_status()
        glyphs.append({'char': char, 'inputPhoto': {'objectKey': key, 'contentType': 'image/png', 'sizeBytes': len(data)}, 'baseline': 0.8})
    created = requests.post(base + '/jobs', json={
        'inputPhoto': glyphs[0]['inputPhoto'],
        'font': {'fontName': 'SmokeGuided', 'familyName': 'Smoke Guided', 'styleName': 'Regular'},
        'capture': {'mode': 'guided', 'format': 'mask-v1', 'glyphs': glyphs},
    }, timeout=20)
    created.raise_for_status()
    job_id = created.json()['jobId']
    start = time.monotonic()
    while time.monotonic() - start < 360:
        response = requests.get(base + '/jobs/' + job_id, timeout=20)
        response.raise_for_status()
        job = response.json()
        if job['status'] in {'failed', 'expired'}:
            raise RuntimeError(json.dumps(job.get('error')))
        if job['status'] == 'succeeded':
            break
        time.sleep(1)
    else:
        raise TimeoutError('Local guided canary exceeded 360 seconds.')
    artifact = next(a for a in job['artifacts'] if a['kind'] == 'ttf')
    key = artifact.get('object_key', artifact.get('objectKey'))
    downloaded = requests.get(base + '/objects/' + key, timeout=20)
    downloaded.raise_for_status()
    font_path = args.output_dir / 'SmokeGuided.ttf'
    font_path.write_bytes(downloaded.content)
    font = ImageFont.truetype(str(font_path), size=90)
    proof = Image.new('RGB', (950, 300), '#fafaf8')
    draw = ImageDraw.Draw(proof)
    draw.text((25, 15), 'Actual generated TTF: A i O g -', fill='#333333')
    draw.text((25, 70), 'A i O g -   AiOg-', font=font, fill='#111111')
    proof.save(args.output_dir / 'proof.png')
    report = {'job_id': job_id, 'status': job['status'], 'glyphs': [g['char'] for g in glyphs], 'wall_seconds': round(time.monotonic()-start, 3), 'ttf_bytes': len(downloaded.content), 'proof': str(args.output_dir / 'proof.png')}
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
