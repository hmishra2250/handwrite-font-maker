#!/usr/bin/env python3
"""Fail-closed private-alpha environment preflight.

This script intentionally parses .env files itself instead of sourcing them. Values are
reported only as key names so secrets do not leak into CI or deployment logs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

PLACEHOLDERS = ("REPLACE_WITH", "CHANGE_ME", "YOUR_", "EXAMPLE", "TODO", "PASTE_")
FORBIDDEN_KEYS = (
    "DATABASE_URL",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_STORAGE_BUCKET",
)
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

PAYMENT_KEYS = (
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "PADDLE_API_KEY",
    "PADDLE_WEBHOOK_SECRET",
    "LEMONSQUEEZY_API_KEY",
    "LEMONSQUEEZY_WEBHOOK_SECRET",
)


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse simple dotenv assignments without shell evaluation or expansion."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise ValueError(f"{path}:{number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            raise ValueError(f"{path}:{number}: invalid environment key")
        value = _strip_comment(value.strip())
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _strip_comment(value: str) -> str:
    if not value or value[0] in {'"', "'"}:
        return value
    marker = value.find(" #")
    return value[:marker].rstrip() if marker >= 0 else value


def merged_env(env_file: Path | None = None, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    if env_file is not None:
        env.update(parse_env_file(env_file))
    return env


def check_config(env: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if env.get("DEPLOYMENT_MODE") != "private_alpha":
        errors.append("DEPLOYMENT_MODE must be private_alpha")
    for key in ("ALPHA_DATABASE_PATH", "LOCAL_OBJECT_ROOT"):
        value = env.get(key, "")
        if not value:
            errors.append(f"{key} is required")
        elif not Path(value).is_absolute():
            errors.append(f"{key} must be an absolute path")
        elif _placeholder(value):
            errors.append(f"{key} still contains a placeholder")
    key = env.get("INTERNAL_API_KEY", "")
    if len(key) < 32:
        errors.append("INTERNAL_API_KEY must contain at least 32 characters")
    elif _placeholder(key):
        errors.append("INTERNAL_API_KEY still contains a placeholder")
    if env.get("PROCESS_JOBS_INLINE") != "0":
        errors.append("PROCESS_JOBS_INLINE must be 0; private alpha runs a separate worker")
    if env.get("WORKER_API_BASE_URL") != "http://api:8000":
        errors.append("WORKER_API_BASE_URL must be http://api:8000 for the private-alpha compose network")
    errors.extend(_check_site_url(env.get("SITE_URL", "")))
    for forbidden in FORBIDDEN_KEYS:
        if env.get(forbidden):
            errors.append(f"{forbidden} must be unset; private alpha uses local SQLite/object storage")
    if str(env.get("BILLING_ENABLED", "0")).strip().lower() not in {"", "0", "false", "no", "off"}:
        errors.append("BILLING_ENABLED must remain false; private alpha has no payment ledger")
    for payment in PAYMENT_KEYS:
        if env.get(payment):
            errors.append(f"{payment} must be unset; payment credentials are not used by private alpha")

    variant = str(env.get("HANDWRITE_SEGMENTATION_VARIANT", "fp32")).strip().lower()
    if variant not in {"fp32", "int8"}:
        errors.append("HANDWRITE_SEGMENTATION_VARIANT must be fp32 or int8; use int8 for the quantized SlimSAM assets")
    if env.get("HANDWRITE_EFFICIENTSAM_MODEL_DIR") and variant != "fp32" and not env.get("HANDWRITE_MODEL_DIR"):
        errors.append("EfficientSAM supports only the pinned fp32 assets; set HANDWRITE_SEGMENTATION_VARIANT=fp32 or use HANDWRITE_MODEL_DIR for SlimSAM int8")
    try:
        from handwrite_font_maker.web.security import load_runtime_config
        load_runtime_config(env)
    except Exception as exc:
        errors.append(f"Runtime security config rejected private alpha settings ({type(exc).__name__})")

    for name, default, low, high in (
        ("DAILY_UPLOAD_LIMIT", "300", 1, 10000),
        ("DAILY_UPLOAD_BYTES_LIMIT", "524288000", 1024 * 1024, 20 * 1024 * 1024 * 1024),
        ("DAILY_PREVIEW_LIMIT", "200", 1, 10000),
        ("DAILY_BUILD_LIMIT", "10", 1, 1000),
        ("ACTIVE_JOB_LIMIT", "2", 1, 100),
        ("JOB_TIMEOUT_SECONDS", "1200", 1, 7200),
        ("JOB_LEASE_SECONDS", "60", 10, 600),
        ("JOB_MAX_ATTEMPTS", "3", 1, 10),
    ):
        _check_int_range(env, name, default, low, high, errors)
    return errors


def _placeholder(value: str) -> bool:
    upper = value.upper()
    return any(marker in upper for marker in PLACEHOLDERS)


def _check_site_url(value: str) -> list[str]:
    if not value:
        return ["SITE_URL is required"]
    parsed = urlparse(value)
    if parsed.username or parsed.password or not parsed.hostname:
        return ["SITE_URL must be an HTTP(S) URL without credentials"]
    if parsed.scheme == "https":
        return []
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return []
    return ["SITE_URL must be http://localhost for local-only alpha or https:// for a TLS-protected host"]


def _check_int_range(env: dict[str, str], name: str, default: str, low: int, high: int, errors: list[str]) -> None:
    raw = env.get(name, default)
    try:
        value = int(str(raw))
    except ValueError:
        errors.append(f"{name} must be an integer between {low} and {high}")
        return
    if value < low or value > high:
        errors.append(f"{name} must be an integer between {low} and {high}")




def localize_container_paths_for_host(env: dict[str, str], *, root: Path | None = None) -> dict[str, str]:
    localized = dict(env)
    root = ROOT if root is None else root
    if localized.get("ALPHA_DATABASE_PATH") == "/data/alpha.sqlite3":
        localized["ALPHA_DATABASE_PATH"] = str((root / ".alpha" / "alpha.sqlite3").resolve())
    if localized.get("LOCAL_OBJECT_ROOT") == "/data/objects":
        localized["LOCAL_OBJECT_ROOT"] = str((root / ".alpha" / "objects").resolve())
    return localized

def check_paths(env: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for key, is_file in (("ALPHA_DATABASE_PATH", True), ("LOCAL_OBJECT_ROOT", False)):
        raw = env.get(key, "")
        if not raw or not Path(raw).is_absolute():
            continue
        path = Path(raw)
        target = path.parent if is_file else path
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".alpha-preflight-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError:
            errors.append(f"{key} is not writable by the current user/container")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env.alpha"), help="dotenv file to validate; parsed without shell evaluation")
    parser.add_argument("--no-env-file", action="store_true", help="validate only the current process environment")
    parser.add_argument("--check-paths", action="store_true", help="create only parent directories/probe files to verify local write access")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)
    try:
        env_file = None if args.no_env_file else args.env_file
        env = merged_env(env_file if env_file and env_file.exists() else None)
        errors = check_config(env)
        verified = ["configuration values parsed without shell evaluation"]
        if args.check_paths and not errors:
            path_errors = check_paths(localize_container_paths_for_host(env))
            errors.extend(path_errors)
            if not path_errors:
                verified.append("SQLite parent directory and object root are writable")
    except Exception as exc:
        errors = [f"Preflight could not parse configuration ({type(exc).__name__})"]
        verified = []
    payload = {
        "ready": not errors,
        "scope": "private-alpha-local",
        "errors": errors,
        "verified": verified,
        "unverified": [
            "first real invited-user login",
            "live font canary on the target host",
            "backup restore drill",
            "TLS/reverse-proxy configuration",
            "paid checkout (intentionally disabled)",
        ],
    }
    print(json.dumps(payload, indent=2) if args.json else _human(payload))
    return 1 if errors else 0


def _human(payload: dict[str, object]) -> str:
    lines = ["Private alpha preflight: " + ("ready" if payload["ready"] else "not ready")]
    for key in ("verified", "errors", "unverified"):
        values = payload[key]
        if values:
            lines.append(key + ":")
            lines.extend(f"- {value}" for value in values)  # type: ignore[union-attr]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
