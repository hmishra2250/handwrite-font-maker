#!/usr/bin/env python3
"""Repeatable synthetic extraction/resize/tracing experiment, not a quality benchmark.

Uses existing Pillow/numpy/OpenCV/Potrace only. Outputs source, masks, actual SVGs,
Potrace-rendered PGM proofs, a contact sheet and JSON metrics. No network calls.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from handwrite_font_maker.foreground import extract_foreground


def topology(mask):
    black = (mask < 128).astype(np.uint8)
    count, _ = cv2.connectedComponents(black)
    contours, hierarchy = cv2.findContours(black, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    holes = 0 if hierarchy is None else sum(int(h[3] >= 0) for h in hierarchy[0])
    return {"components": count - 1, "holes": holes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('output/vector-styles'))
    args = parser.parse_args()
    root = args.output_dir
    root.mkdir(parents=True, exist_ok=True)
    source = Image.new('RGB', (1024, 1024), (240, 235, 220))
    draw = ImageDraw.Draw(source)
    # A leaf-like ring with an actual hole, interior veins and disconnected seed.
    draw.ellipse((200, 150, 830, 850), fill=(125, 175, 90))
    draw.ellipse((350, 330, 660, 640), fill=(240, 235, 220))
    draw.ellipse((90, 100, 125, 135), fill=(45, 75, 20))
    draw.line((525, 850, 575, 940), fill=(45, 75, 20), width=5)
    for y in range(215, 820, 65):
        draw.line((240, y, 330, y+45), fill=(45, 75, 20), width=3)
        draw.line((710, y, 790, y+45), fill=(45, 75, 20), width=3)
    source.save(root / 'source.png')
    bgr = np.asarray(source)[:, :, ::-1].copy()
    start = time.perf_counter()
    silhouette = extract_foreground(bgr, [0.04, 0.04, 0.96, 0.97])
    cutout_seconds = time.perf_counter() - start
    # Preserve dark veins/ink only inside accepted silhouette, not background.
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    detail = np.where((gray < 110) & (silhouette < 128), 0, 255).astype(np.uint8)
    styles = {'silhouette': silhouette, 'dark-detail': detail}
    settings = {'faithful': ['-t', '0', '-a', '0', '-O', '0.1'],
                'balanced': ['-t', '0', '-a', '1', '-O', '0.2'],
                'smooth': ['-t', '0', '-a', '1.3', '-O', '0.8']}
    rows = []
    sheet = Image.new('RGB', (4 * 280, 2 * 330), 'white')
    label = ImageDraw.Draw(sheet)
    for row, (style, target) in enumerate(styles.items()):
        Image.fromarray(target).save(root / f'{style}.png')
        for col, side in enumerate((128, 256, 512, 1024)):
            scaled = Image.fromarray(target).resize((side, side), Image.Resampling.LANCZOS)
            binary = scaled.point(lambda x: 0 if x < 128 else 255).convert('1')
            stem = root / f'{style}-{side}'
            binary.save(stem.with_suffix('.pbm'))
            for name, flags in settings.items():
                svg = root / f'{style}-{side}-{name}.svg'
                pgm = root / f'{style}-{side}-{name}.pgm'
                before = time.perf_counter()
                subprocess.run(['potrace', str(stem.with_suffix('.pbm')), '-s', '-o', str(svg), *flags], check=True, timeout=20)
                seconds = time.perf_counter() - before
                subprocess.run(['potrace', str(stem.with_suffix('.pbm')), '-g', '-o', str(pgm), *flags], check=True, timeout=20)
                raster = Image.open(pgm).convert('L').resize((1024, 1024), Image.Resampling.LANCZOS)
                result = np.asarray(raster) < 128
                expected = target < 128
                union = np.count_nonzero(result | expected)
                rows.append({'style': style, 'side': side, 'tracing': name, 'svg_bytes': svg.stat().st_size,
                             'path_commands': len(re.findall(r'[MmLlCcQqZz]', ''.join(re.findall(r' d="([^"]+)"', svg.read_text())))),
                             'seconds': round(seconds, 5), 'iou_to_full_size_style': round(np.count_nonzero(result & expected) / union, 5),
                             'topology': topology(np.asarray(raster)), 'target_topology': topology(target)})
                if name == 'balanced':
                    sheet.paste(raster.resize((256, 256)), (col * 280 + 12, row * 330 + 40))
                    label.text((col * 280 + 12, row * 330 + 10), f'{style} / {side}px / balanced', fill='black')
    sheet.save(root / 'comparison.png')
    report = {'scope': 'Synthetic controlled example; not real-photo or trained-model accuracy evidence.',
              'grabcut_seconds': round(cutout_seconds, 4), 'results': rows}
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
