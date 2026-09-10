#!/usr/bin/env python3
"""Run the private-alpha stack on a developer machine without sourcing .env files."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import alpha_preflight

ROOT = Path(__file__).resolve().parents[1]


class StopRequested(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def repo_python_executable(root: Path = ROOT, *, fallback: str | None = None) -> str:
    candidate = root / ".venv" / "bin" / "python"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return fallback or sys.executable


def _raise_stop_requested(signum, _frame):
    raise StopRequested(int(signum))


def install_signal_handlers():
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _raise_stop_requested)
    return previous


def localize_container_defaults(env: dict[str, str]) -> dict[str, str]:
    env = dict(env)
    if not env.get("ALPHA_DATABASE_PATH"):
        env["ALPHA_DATABASE_PATH"] = "/data/alpha.sqlite3"
    if not env.get("LOCAL_OBJECT_ROOT"):
        env["LOCAL_OBJECT_ROOT"] = "/data/objects"
    env = alpha_preflight.localize_container_paths_for_host(env, root=ROOT)
    if env.get("WORKER_API_BASE_URL") in {"http://api:8000", ""}:
        env["WORKER_API_BASE_URL"] = f"http://127.0.0.1:{env.get('ALPHA_API_PORT', '8000')}"
    if env.get("SITE_URL") in {"http://localhost:3000", ""}:
        env["SITE_URL"] = f"http://localhost:{env.get('ALPHA_WEB_PORT', '3000')}"
    env.setdefault("DEPLOYMENT_MODE", "private_alpha")
    env.setdefault("PROCESS_JOBS_INLINE", "0")
    return env


def check_local_config(env: dict[str, str]) -> list[str]:
    check_env = dict(env)
    # The compose preflight intentionally requires api:8000; local processes use localhost.
    check_env["WORKER_API_BASE_URL"] = "http://api:8000"
    return alpha_preflight.check_config(check_env)


def spawn(name: str, command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    print(f"[alpha-dev] starting {name}: {' '.join(command)}")
    return subprocess.Popen(command, cwd=str(cwd), env=env, start_new_session=True)


def stop(processes: list[subprocess.Popen]) -> None:
    for proc in processes:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 8
    for proc in processes:
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.alpha", help="dotenv file to load without shell evaluation")
    parser.add_argument("--api-port", default=os.environ.get("ALPHA_API_PORT", "8000"))
    parser.add_argument("--web-port", default=os.environ.get("ALPHA_WEB_PORT", "3000"))
    parser.add_argument("--skip-worker", action="store_true", help="start only API, cleanup and web; builds stay queued")
    args = parser.parse_args(argv)

    env = dict(os.environ)
    if args.env_file.exists():
        env.update(alpha_preflight.parse_env_file(args.env_file))
    env["ALPHA_API_PORT"] = str(args.api_port)
    env["ALPHA_WEB_PORT"] = str(args.web_port)
    env = localize_container_defaults(env)
    errors = check_local_config(env)
    if errors:
        print("Private alpha dev environment is not ready:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    Path(env["ALPHA_DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    Path(env["LOCAL_OBJECT_ROOT"]).mkdir(parents=True, exist_ok=True)
    env.update({"HOST": "127.0.0.1", "PORT": str(args.api_port), "WORKER_API_BASE_URL": f"http://127.0.0.1:{args.api_port}"})

    processes: list[subprocess.Popen] = []
    previous_sigterm = install_signal_handlers()
    python = repo_python_executable()
    try:
        processes.append(spawn("api", [python, "-m", "handwrite_font_maker.web.server"], cwd=ROOT, env=env))
        if not args.skip_worker:
            processes.append(spawn("worker", [python, "-m", "handwrite_font_maker.web.worker_loop"], cwd=ROOT, env=env))
        processes.append(spawn("cleanup", [python, "-m", "handwrite_font_maker.web.cleanup", "--object-root", env["LOCAL_OBJECT_ROOT"]], cwd=ROOT, env=env))
        web_env = dict(env, PORT=str(args.web_port), HOSTNAME="127.0.0.1")
        processes.append(spawn("web", ["npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", str(args.web_port)], cwd=ROOT / "web", env=web_env))
        print(f"[alpha-dev] open http://localhost:{args.web_port}; stop with Ctrl-C")
        while True:
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    print(f"[alpha-dev] child exited with {code}; shutting down", file=sys.stderr)
                    return code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 130
    except StopRequested as exc:
        return 128 + exc.signum
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        stop(processes)


if __name__ == "__main__":
    raise SystemExit(main())
