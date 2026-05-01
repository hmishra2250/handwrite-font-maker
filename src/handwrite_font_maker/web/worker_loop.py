from __future__ import annotations

import os
import time
from pathlib import Path

from .api import worker_once
from .job_store import PostgresJobStore
from .supabase_store import SupabaseStorage
from .worker import process_one


def main() -> int:
    store = Path(os.environ.get('JOB_STORE_PATH', '/tmp/jobs.json'))
    object_root = Path(os.environ.get('LOCAL_OBJECT_ROOT', '/tmp/objects'))
    interval = float(os.environ.get('WORKER_POLL_SECONDS', '5'))
    while True:
        database_url = os.environ.get("DATABASE_URL")
        if database_url and os.environ.get("SUPABASE_URL"):
            job = process_one(PostgresJobStore(database_url), SupabaseStorage())
            result = None if job is None else job.as_response()
        else:
            result = worker_once(store, object_root)
        if result is None:
            time.sleep(interval)
        else:
            print(result, flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
