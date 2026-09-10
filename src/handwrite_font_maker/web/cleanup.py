from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .tenant_store import cleanup_expired_from_env
from .feedback_store import cleanup_feedback
from .security import load_runtime_config


def _run_once(*, object_root: Path | None, limit: int) -> tuple[int, dict[str, object]]:
    try:
        result = cleanup_expired_from_env(object_root=object_root, limit=limit)
        cleanup_feedback(load_runtime_config())
    except Exception as exc:
        return 1, {"ok": False, "error": {"code": exc.__class__.__name__, "message": "Cleanup pass failed."}}
    failed = int(result.get("failedObjects") or 0)
    return (1 if failed else 0), {"ok": failed == 0, **result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="handwrite-font-cleanup", description="Delete expired registered uploads and artifacts.")
    parser.add_argument("--once", action="store_true", help="Run one cleanup pass and exit.")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--object-root", type=Path)
    args = parser.parse_args(argv)
    exit_code = 0
    while True:
        exit_code, payload = _run_once(object_root=args.object_root, limit=args.limit)
        print(json.dumps(payload), flush=True)
        if args.once:
            return exit_code
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
