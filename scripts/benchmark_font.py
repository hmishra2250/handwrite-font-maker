#!/usr/bin/env python3
"""Measure a real local build; pricing projections are explicitly hypothetical."""
from __future__ import annotations

import argparse
import json
import platform
import resource
import time
from collections import defaultdict
from pathlib import Path

from handwrite_font_maker import pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--font-name', default='BenchmarkHand')
    args = parser.parse_args()
    aggregates: dict[str, dict[str, float | int]] = defaultdict(lambda: {'calls': 0, 'wall_seconds': 0.0})
    original = pipeline._run_checked

    def measured(command: list[str], cwd: Path) -> None:
        start = time.perf_counter()
        try:
            original(command, cwd)
        finally:
            entry = aggregates[Path(command[0]).name]
            entry['calls'] += 1
            entry['wall_seconds'] += time.perf_counter() - start

    parent_before = resource.getrusage(resource.RUSAGE_SELF)
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    pipeline._run_checked = measured
    try:
        result = pipeline.build_font(
            image_path=args.input.resolve(), font_name=args.font_name,
            family_name='Benchmark Hand', style_name='Regular',
            output_dir=args.output_dir.resolve(),
        )
    finally:
        pipeline._run_checked = original
    wall = time.perf_counter() - started
    parent_after = resource.getrusage(resource.RUSAGE_SELF)
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = sum(after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime for before, after in [(parent_before, parent_after), (child_before, child_after)])
    manifest = json.loads(Path(str(result['manifest'])).read_text())
    report = {
        'kind': 'local-build-benchmark',
        'environment': {'platform': platform.platform(), 'python': platform.python_version()},
        'input': str(args.input),
        'wall_seconds': round(wall, 3),
        'cpu_seconds_parent_and_children': round(cpu, 3),
        'subprocesses': dict(aggregates),
        'glyph_count': len(manifest['glyphs']),
        'nonempty_glyph_count': sum(not g['empty'] for g in manifest['glyphs']),
        'artifacts_bytes': {kind: Path(str(result[kind])).stat().st_size for kind in ('ttf', 'otf')},
        'illustrative_cloud_active_compute_usd': round(wall * (0.000024 + 2 * 0.0000025), 6),
        'projection_assumptions': 'Hypothetical 1 vCPU + 2 GiB billed for local wall time at reference rates; NOT a cloud benchmark/invoice. Excludes cold starts, idle hosting, retries/free previews, storage/egress, support, payments, tax and acquisition. Busy shared host; no p95 claim from one run.',
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
