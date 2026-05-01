from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import FontRequest, HardErrorCode, InputPhoto, is_safe_font_name, is_supported_image
from .job_store import JsonJobStore, PostgresJobStore
from .supabase_store import LocalObjectStore
from .worker import process_one


def _job_store(store_path: Path):
    import os
    database_url = os.environ.get("DATABASE_URL")
    return PostgresJobStore(database_url) if database_url else JsonJobStore(store_path)


def create_job(store_path: Path, *, object_key: str, content_type: str, size_bytes: int, font_name: str, family_name: str, style_name: str = "Regular") -> dict[str, object]:
    if not object_key:
        raise ValueError(HardErrorCode.UPLOAD_OBJECT_MISSING.value)
    if not is_supported_image(content_type):
        raise ValueError(HardErrorCode.UNSUPPORTED_IMAGE_TYPE.value)
    if not is_safe_font_name(font_name):
        raise ValueError(HardErrorCode.FONT_METADATA_INVALID.value)
    store = _job_store(store_path)
    job = store.create(InputPhoto(object_key=object_key, content_type=content_type, size_bytes=size_bytes), FontRequest(font_name=font_name, family_name=family_name, style_name=style_name))
    return job.as_response()


def get_job(store_path: Path, job_id: str) -> dict[str, object] | None:
    job = _job_store(store_path).get(job_id)
    return None if job is None else job.as_response()


def worker_once(store_path: Path, object_root: Path) -> dict[str, object] | None:
    store = _job_store(store_path)
    object_store = LocalObjectStore(object_root)
    job = process_one(store, object_store)
    return None if job is None else job.as_response()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="handwrite-font-web-api", description="Local/dev Render API-worker contract harness.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-job")
    create.add_argument("--store", required=True)
    create.add_argument("--object-key", required=True)
    create.add_argument("--content-type", required=True)
    create.add_argument("--size-bytes", type=int, required=True)
    create.add_argument("--font-name", required=True)
    create.add_argument("--family-name", required=True)
    create.add_argument("--style-name", default="Regular")
    get = sub.add_parser("get-job")
    get.add_argument("--store", required=True)
    get.add_argument("job_id")
    worker = sub.add_parser("worker-once")
    worker.add_argument("--store", required=True)
    worker.add_argument("--object-root", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-job":
        result = create_job(Path(args.store), object_key=args.object_key, content_type=args.content_type, size_bytes=args.size_bytes, font_name=args.font_name, family_name=args.family_name, style_name=args.style_name)
    elif args.command == "get-job":
        result = get_job(Path(args.store), args.job_id)
    else:
        result = worker_once(Path(args.store), Path(args.object_root))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
