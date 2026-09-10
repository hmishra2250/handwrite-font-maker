#!/usr/bin/env python3
"""Read-only deployment preflight. Does not provision services or print secrets.

Load the intended environment in your shell, then run:
  python scripts/deploy_preflight.py [--check-services] [--check-models]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse


def check_config(env: dict[str, str]) -> list[str]:
    errors = []
    if env.get("DEPLOYMENT_MODE") not in {"invite_beta", "production"}:
        errors.append("DEPLOYMENT_MODE must explicitly select invite_beta or production")
    for key in ("SITE_URL", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL", "INTERNAL_API_KEY", "WORKER_API_BASE_URL"):
        value = env.get(key, "")
        if not value or any(marker in value.upper() for marker in ("REPLACE_WITH", "YOUR_PROJECT", "EXAMPLE.COM")):
            errors.append(f"{key} is missing or still a placeholder")
    if len(env.get("INTERNAL_API_KEY", "")) < 32:
        errors.append("INTERNAL_API_KEY must contain at least 32 characters")
    for key in ("SITE_URL", "SUPABASE_URL"):
        parsed = urlparse(env.get(key, ""))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            errors.append(f"{key} must be an HTTPS URL without credentials")
    worker = urlparse(env.get("WORKER_API_BASE_URL", ""))
    if worker.scheme not in {"http", "https"} or not worker.hostname or worker.username or worker.password:
        errors.append("WORKER_API_BASE_URL must be a private HTTP(S) service URL")
    if env.get("PROCESS_JOBS_INLINE") != "0":
        errors.append("PROCESS_JOBS_INLINE must be 0; run the separate worker")
    if env.get("BILLING_ENABLED", "false").lower() not in {"false", "0"}:
        errors.append("Paid processing is unavailable: no verified project-credit ledger")
    for key, default, low, high in (("JOB_LEASE_SECONDS", "60", 10, 600), ("JOB_TIMEOUT_SECONDS", "600", 1, 3600), ("JOB_MAX_ATTEMPTS", "3", 1, 5)):
        try:
            if not low <= int(env.get(key, default)) <= high:
                raise ValueError
        except ValueError:
            errors.append(f"{key} must be an integer between {low} and {high}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-services", action="store_true")
    parser.add_argument("--check-models", action="store_true")
    args = parser.parse_args()
    errors = check_config(dict(os.environ))
    evidence = []
    if args.check_services and not errors:
        try:
            from migrate import migrate
            migrate(os.environ["DATABASE_URL"], check=True)
            evidence.append("database migration ledger verified")
        except Exception as exc:
            errors.append(f"Database migration readiness failed ({type(exc).__name__})")
        try:
            import requests
            base = os.environ["SUPABASE_URL"].rstrip("/")
            key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
            bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "handwrite-font-jobs")
            response = requests.get(f"{base}/storage/v1/bucket/{bucket}", headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=15)
            response.raise_for_status()
            if response.json().get("public") is not False:
                raise ValueError("Bucket must be private")
            evidence.append("configured storage bucket exists and is private")
        except Exception as exc:
            errors.append(f"Private storage check failed ({type(exc).__name__})")
    if args.check_models:
        # Check install/runtime without loading both models into RAM.
        try:
            import onnxruntime  # noqa: F401
            from handwrite_font_maker import segmentation, efficient_segmentation
            selected = 0
            for key, backend in (("HANDWRITE_MODEL_DIR", segmentation), ("HANDWRITE_EFFICIENTSAM_MODEL_DIR", efficient_segmentation)):
                if not os.environ.get(key):
                    continue
                selected += 1
                names = backend.model_files(os.environ.get("HANDWRITE_SEGMENTATION_VARIANT", "fp32")) if backend is segmentation else backend.model_files()
                for name in names:
                    backend.verify_asset(Path(os.environ[key]) / name)
                evidence.append(f"{key}: pinned model hashes verified")
            if not selected:
                errors.append("Select a model directory before requesting --check-models")
        except Exception as exc:
            errors.append(f"Optional model validation failed ({type(exc).__name__})")
        for key in ("HANDWRITE_MODEL_DIR", "HANDWRITE_EFFICIENTSAM_MODEL_DIR"):
            if os.environ.get(key) and not Path(os.environ[key]).is_dir():
                errors.append(f"{key} is not a mounted directory")
    print(json.dumps({"ready": not errors, "scope": "schema-and-storage-preflight" if args.check_services else "configuration-only", "errors": errors, "verified": evidence, "unverified": ["hosted login and refresh", "live font canary", "backup restore", "provider memory/load limits", "Word/PowerPoint compatibility", "paid checkout (disabled)"]}, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
