#!/usr/bin/env python3
"""Private-alpha account admin wrapper for host-local runs.

Reads .env.alpha with the same no-eval parser used by alpha_preflight.py, maps
Docker's /data defaults to ./.alpha for host-local use, and invokes the trusted
alpha_auth CLI without placing secrets on the command line.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import alpha_preflight
import alpha_dev

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / ".env.alpha"
EXAMPLE_ENV = ROOT / ".env.alpha.example"
SECRET_PLACEHOLDER = "REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS"


def init_env(path: Path = DEFAULT_ENV, *, example: Path = EXAMPLE_ENV) -> Path:
    """Create .env.alpha from the example with a random internal key; never overwrite."""
    if path.exists():
        raise FileExistsError(f"{path} already exists; refusing to overwrite")
    if not example.exists():
        raise FileNotFoundError(f"{example} is missing")
    body = example.read_text(encoding="utf-8")
    if SECRET_PLACEHOLDER not in body:
        raise ValueError(f"{example} does not contain the internal-key placeholder")
    body = body.replace(SECRET_PLACEHOLDER, secrets.token_urlsafe(48), 1)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def alpha_env(path: Path = DEFAULT_ENV, *, api_port: str = "8000", web_port: str = "3000") -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist; run scripts/alpha_admin.py --init-env first")
    env = dict(os.environ)
    env.update(alpha_preflight.parse_env_file(path))
    env["ALPHA_API_PORT"] = str(api_port)
    env["ALPHA_WEB_PORT"] = str(web_port)
    env = alpha_dev.localize_container_defaults(env)
    # alpha_auth only uses runtime security config, but keep the frontend/API URL in
    # the normal local-process shape so an operator can copy the env into local tools.
    env["WORKER_API_BASE_URL"] = f"http://127.0.0.1:{api_port}"
    return env


def validate_for_admin(env: dict[str, str]) -> list[str]:
    check_env = dict(env)
    # Reuse compose-oriented preflight rules while permitting host-local process URLs.
    check_env["WORKER_API_BASE_URL"] = "http://api:8000"
    return alpha_preflight.check_config(check_env)


def run_alpha_auth(action: str, *, email: str, generate_password: bool, env_file: Path, api_port: str, web_port: str) -> int:
    env = alpha_env(env_file, api_port=api_port, web_port=web_port)
    errors = validate_for_admin(env)
    if errors:
        for error in errors:
            print(f"alpha admin config error: {error}", file=sys.stderr)
        return 1
    Path(env["ALPHA_DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    Path(env["LOCAL_OBJECT_ROOT"]).mkdir(parents=True, exist_ok=True)
    command = [alpha_dev.repo_python_executable(), "-m", "handwrite_font_maker.web.alpha_auth", action, "--email", email]
    if generate_password:
        command.append("--generate-password")
    completed = subprocess.run(command, cwd=str(ROOT), env=env, check=False)
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["create-user", "reset-password", "disable-user"], help="admin action to run")
    parser.add_argument("--email", help="invited user's email address")
    parser.add_argument("--generate-password", action="store_true", help="print a generated password once; deliver securely")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV, help="alpha dotenv file parsed without shell evaluation")
    parser.add_argument("--api-port", default=os.environ.get("ALPHA_API_PORT", "8000"))
    parser.add_argument("--web-port", default=os.environ.get("ALPHA_WEB_PORT", "3000"))
    parser.add_argument("--init-env", action="store_true", help="create .env.alpha from .env.alpha.example with a random internal key; never overwrite")
    args = parser.parse_args(argv)

    try:
        if args.init_env:
            path = init_env(args.env_file)
            print(f"Created {path} with mode 0600. Edit SITE_URL before sharing alpha externally. No user was created.")
            return 0
        if not args.action:
            parser.error("choose an action or --init-env")
        if not args.email:
            parser.error("--email is required for account actions")
        return run_alpha_auth(args.action, email=args.email, generate_password=args.generate_password, env_file=args.env_file, api_port=str(args.api_port), web_port=str(args.web_port))
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
