#!/usr/bin/env python3
"""Explicitly install pinned, SHA-256-verified optional ONNX weights (no inference)."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import tempfile

import requests

from handwrite_font_maker.segmentation import (
    MODEL_ASSETS, MODEL_REPO, MODEL_REVISION, model_directory, model_files, verify_asset,
)


def install_asset(name: str, directory: Path, *, model: str = 'slimsam') -> Path:
    if model == 'efficientsam':
        from handwrite_font_maker import efficient_segmentation as backend
        assets, verifier = backend.MODEL_ASSETS, backend.verify_asset
        base = f'https://huggingface.co/spaces/{backend.MODEL_REPO}/resolve/{backend.MODEL_REVISION}'
    elif model == 'slimsam':
        assets, verifier = MODEL_ASSETS, verify_asset
        base = f'https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/onnx'
    else:
        raise ValueError('Unknown model family.')
    expected_size, expected_hash = assets[name]
    target = directory / name
    if target.exists():
        try:
            verifier(target)
            return target
        except RuntimeError:
            pass  # Replace only after a complete verified download.
    url = f'{base}/{name}'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=f'.{name}.', suffix='.part', delete=False) as stream:
            temporary = Path(stream.name)
            digest, size = hashlib.sha256(), 0
            with requests.get(url, stream=True, timeout=(15, 90)) as response:
                response.raise_for_status()
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > expected_size:
                        raise RuntimeError(f'Download exceeds pinned size: {name}')
                    digest.update(chunk)
                    stream.write(chunk)
            if size != expected_size or digest.hexdigest() != expected_hash:
                raise RuntimeError(f'Checkpoint integrity mismatch: {name}')
        temporary.replace(target)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['slimsam', 'efficientsam'], default='slimsam')
    parser.add_argument('--variant', choices=['fp32', 'int8', 'all'], default='fp32')
    parser.add_argument('--directory', type=Path, default=None)
    args = parser.parse_args()
    if args.model == 'efficientsam':
        if args.variant != 'fp32':
            parser.error('EfficientSAM has one pinned fp32 variant; omit --variant.')
        from handwrite_font_maker import efficient_segmentation as backend
        directory = args.directory or backend.model_directory()
        names = backend.model_files()
        repo, revision = backend.MODEL_REPO, backend.MODEL_REVISION
    else:
        directory = args.directory or model_directory()
        variants = ['fp32', 'int8'] if args.variant == 'all' else [args.variant]
        names = [name for variant in variants for name in model_files(variant)]
        repo, revision = MODEL_REPO, MODEL_REVISION
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = install_asset(name, directory, model=args.model)
        print(f'Verified {path.name}: {path.stat().st_size:,} bytes')
    print(f'Model: {repo}@{revision}; Apache-2.0 model-card declaration.')
    print('Install runtime: pip install -e ".[ml]". Requests never download weights automatically.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
