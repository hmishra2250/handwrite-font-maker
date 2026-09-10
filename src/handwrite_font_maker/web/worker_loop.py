"""One bounded font-build process at a time, supervised by a durable PG lease.

Run: python -m handwrite_font_maker.web.worker_loop [--once]
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .job_store import PostgresJobStore
from .supabase_store import LocalObjectStore, SupabaseStorage


def object_store():
    if os.environ.get("DEPLOYMENT_MODE", "local") == "private_alpha":
        return LocalObjectStore(Path(os.environ.get("LOCAL_OBJECT_ROOT", "/tmp/handwrite-alpha-objects")))
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return SupabaseStorage()
    if os.environ.get("DEPLOYMENT_MODE", "local") != "local":
        raise RuntimeError("Beta/prod workers require private Supabase Storage")
    return LocalObjectStore(Path(os.environ.get("LOCAL_OBJECT_ROOT", "/tmp/handwrite-alpha-objects")))


def _stop_group(process: subprocess.Popen) -> None:
    # Every child uses start_new_session, so this cannot signal the supervisor's group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_once(store, *, timeout: float | None = None) -> bool:
    job = store.next_queued()
    if job is None:
        return False
    timeout = timeout if timeout is not None else float(os.environ.get("JOB_TIMEOUT_SECONDS", "600"))
    if timeout <= 0:
        raise ValueError("JOB_TIMEOUT_SECONDS must be positive")
    process = subprocess.Popen(
        [sys.executable, "-m", "handwrite_font_maker.web.worker_loop", "--execute", job.id, job.attempt_id, job.lease_owner],
        start_new_session=True,
    )
    started = time.monotonic()
    next_heartbeat = started + store.lease_seconds / 3
    reason = "Worker process exited before completion"
    try:
        while process.poll() is None:
            now = time.monotonic()
            if now - started >= timeout:
                reason = "Worker runtime limit exceeded"
                break
            if now >= next_heartbeat:
                if not store.heartbeat(job):
                    reason = "Worker lease lost"
                    break
                next_heartbeat = now + store.lease_seconds / 3
            time.sleep(min(0.25, max(0.01, timeout - (now - started))))
    finally:
        _stop_group(process)
        # No-op if the child succeeded/failed, user deleted the job, or a new attempt owns it.
        store.retry_attempt(job, reason=reason)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--execute", nargs=3, metavar=("JOB", "ATTEMPT", "LEASE"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    from .security import DeploymentMode, load_runtime_config

    config = load_runtime_config()  # Fail closed before claiming work.
    if config.mode == DeploymentMode.PRIVATE_ALPHA:
        from .sqlite_store import SQLiteJobStore

        store = SQLiteJobStore(config.alpha_database_path or "")
    else:
        if not database_url:
            parser.error("DATABASE_URL is required for the durable worker")
        store = PostgresJobStore(database_url)
    if args.execute:
        # The lease is revalidated by the first save before any object read or build.
        from .worker import process_job
        job = store.get(args.execute[0])
        if job is None or (job.attempt_id, job.lease_owner) != tuple(args.execute[1:]):
            raise SystemExit("Attempt no longer owns this job")
        process_job(job, store, object_store())
        return

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        while True:
            worked = run_once(store)
            if args.once:
                return
            if not worked:
                time.sleep(2)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Worker stopped ({type(exc).__name__}); no request data logged.", file=sys.stderr)
        raise SystemExit(1) from None
