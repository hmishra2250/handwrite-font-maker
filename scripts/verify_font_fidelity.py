#!/usr/bin/env python3
"""Compare accepted masks with actual FreeType-rendered exported glyphs.

This measures outline/raster fidelity, not semantic segmentation accuracy or
spacing. Normalization removes translation and uniform scale, not aspect ratio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from benchmark_segmentation import _topology, segmentation_metrics


def normalize_shape(mask: np.ndarray, side: int = 512) -> np.ndarray:
    foreground = np.asarray(mask) < 128
    ys, xs = np.where(foreground)
    if not len(xs):
        raise ValueError('Cannot compare an empty glyph.')
    crop = np.where(foreground[ys.min():ys.max()+1, xs.min():xs.max()+1], 0, 255).astype(np.uint8)
    image = Image.fromarray(crop)
    scale = (side - 16) / max(image.size)
    image = image.resize(tuple(max(1, round(d * scale)) for d in image.size), Image.Resampling.NEAREST)
    canvas = Image.new('L', (side, side), 255)
    canvas.paste(image, ((side-image.width)//2, (side-image.height)//2))
    return np.asarray(canvas)


def verify_glyph(font: ImageFont.FreeTypeFont, char: str, mask_path: Path, out: Path) -> dict:
    source = np.asarray(Image.open(mask_path).convert('L'))
    bbox = font.getbbox(char)
    if not bbox or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise ValueError(f'Font glyph {char!r} has no visible bounds.')
    canvas = Image.new('L', (bbox[2]-bbox[0]+16, bbox[3]-bbox[1]+16), 255)
    ImageDraw.Draw(canvas).text((8-bbox[0], 8-bbox[1]), char, font=font, fill=0)
    rendered = np.where(np.asarray(canvas) < 128, 0, 255).astype(np.uint8)
    a, b = normalize_shape(source), normalize_shape(rendered)
    panel = Image.new('RGB', (1024, 540), 'white')
    panel.paste(Image.fromarray(a), (0, 28))
    panel.paste(Image.fromarray(b), (512, 28))
    ImageDraw.Draw(panel).text((8, 8), f'{char}: accepted mask | actual TTF render (uniformly normalized)', fill='black')
    panel.save(out)
    return {
        'char': char, 'mask_sha256': hashlib.sha256(mask_path.read_bytes()).hexdigest(),
        'accepted_mask_topology': _topology(source), 'rendered_font_topology': _topology(rendered),
        'normalized_outline_metrics': segmentation_metrics(b, a), 'comparison_png': out.name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', required=True, type=Path)
    parser.add_argument('--glyph', action='append', required=True, help='CHAR=accepted-mask.png')
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(args.font), 1024)
    results = []
    for entry in args.glyph:
        char, path = entry.split('=', 1)
        if len(char) != 1:
            raise ValueError('Each glyph mapping must be exactly one character.')
        try:
            results.append({'status': 'ok', **verify_glyph(font, char, Path(path), args.output_dir / f'U{ord(char):04X}.png')})
        except Exception as exc:
            results.append({'status': 'error', 'char': char, 'error': str(exc)})
    report = {
        'scope': 'Accepted-mask to actual exported TTF outline fidelity, not segmentation ground truth. Does not measure spacing/baseline or human acceptance.',
        'font_sha256': hashlib.sha256(args.font.read_bytes()).hexdigest(),
        'render_size_px': 1024, 'normalization': 'tight bbox; uniform scale; centered 512px canvas; nearest-neighbor binary masks',
        'glyphs': results,
    }
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return 1 if any(row['status'] != 'ok' for row in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
