#!/usr/bin/env python3
"""Share a production-mode mobile alpha over temporary public HTTPS.

The existing alpha API and ML worker remain on loopback. Cloudflare terminates
public TLS; application login, secure cookies and exact-origin checks remain on.
No development server or Python API is exposed. Ctrl-C stops this preview only.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import alpha_dev
import alpha_preflight

ROOT = Path(__file__).resolve().parents[1]
TUNNEL_URL = re.compile(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com\b')


def mobile_environment(env_file: Path, site_url: str, api_port: int) -> dict[str, str]:
    if not TUNNEL_URL.fullmatch(site_url):
        raise ValueError('Expected an HTTPS trycloudflare.com origin, without a path or credentials.')
    env = dict(os.environ)
    env.update(alpha_preflight.parse_env_file(env_file))
    env = alpha_dev.localize_container_defaults(env)
    env.update(SITE_URL=site_url, WORKER_API_BASE_URL=f'http://127.0.0.1:{api_port}',
               HANDWRITE_MOBILE_PREVIEW='1', HANDWRITE_PHONE_PREVIEW='0', NODE_ENV='production')
    errors = alpha_dev.check_local_config(env)
    if errors:
        raise ValueError('; '.join(errors))
    return env


def wait_for_tunnel(proc: subprocess.Popen, log_path: Path, timeout: float = 60) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError('HTTPS tunnel exited; inspect the local tunnel log.')
        # Match the announced URL banner, not an API/error URL elsewhere in logs.
        for line in log_path.read_text(errors='replace').splitlines():
            match = re.search(r'\|\s*(' + TUNNEL_URL.pattern + r')\s*\|', line)
            if match:
                return match.group(1)
        time.sleep(0.25)
    raise RuntimeError('Timed out obtaining a temporary HTTPS URL. No application server was exposed.')


def wait_for_web(proc: subprocess.Popen, port: int, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError('Mobile web server exited before becoming ready.')
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/mobile', timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError('Mobile web server did not become ready.')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.alpha')
    parser.add_argument('--port', type=int, default=3009)
    parser.add_argument('--api-port', type=int, default=8000)
    parser.add_argument('--cloudflared', default=str(ROOT / '.alpha/bin/cloudflared'))
    args = parser.parse_args(argv)
    if not all(1024 <= port <= 65535 for port in (args.port, args.api_port)):
        parser.error('Ports must be between 1024 and 65535.')
    processes: list[subprocess.Popen] = []
    previous_sigterm = alpha_dev.install_signal_handlers()
    runtime = ROOT / '.alpha'
    runtime.mkdir(exist_ok=True)
    status_path = runtime / 'mobile-preview.json'
    owns_status = False
    try:
        # Validate auth before starting any publicly reachable process.
        mobile_environment(args.env_file, 'https://preflight.trycloudflare.com', args.api_port)
        binary = shutil.which(args.cloudflared)
        if not binary:
            raise ValueError('cloudflared is missing. Install the official CLI or pass --cloudflared /path/to/cloudflared.')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', args.port))
        with urllib.request.urlopen(f'http://127.0.0.1:{args.api_port}/readyz', timeout=5) as response:
            if response.status != 200:
                raise ValueError('Start the existing alpha API/worker first.')
        status_path.unlink(missing_ok=True)
        owns_status = True
        tunnel_log = runtime / 'mobile-tunnel.log'
        tunnel_env = {key: value for key, value in os.environ.items() if not key.startswith('TUNNEL_')}
        with tunnel_log.open('w') as log:
            tunnel = subprocess.Popen([binary, 'tunnel', '--config', os.devnull, '--no-autoupdate',
                '--url', f'http://127.0.0.1:{args.port}', '--protocol', 'http2'],
                env=tunnel_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(tunnel)
        site_url = wait_for_tunnel(tunnel, tunnel_log)
        env = mobile_environment(args.env_file, site_url, args.api_port)
        # Compile before exposing an app. No --skip-build: new routes must be present.
        build = alpha_dev.spawn('mobile build', ['npm', 'run', 'build'], cwd=ROOT / 'web', env=env)
        processes.append(build)
        if build.wait() != 0:
            raise RuntimeError('Mobile production build failed; stopping the tunnel.')
        web = alpha_dev.spawn('mobile web', ['npm', 'run', 'start', '--', '--hostname', '127.0.0.1', '--port', str(args.port)], cwd=ROOT / 'web', env=env)
        processes.append(web)
        wait_for_web(web, args.port)
        status_path.write_text(json.dumps({'url': site_url + '/mobile', 'origin': site_url,
            'pid': os.getpid(), 'webPort': args.port, 'temporary': True}, indent=2) + '\n')
        status_path.chmod(0o600)
        print(f'Mobile alpha: {site_url}/mobile', flush=True)
        print('Use your existing alpha login. Link is temporary; keep this computer awake. Ctrl-C stops sharing.', flush=True)
        while True:
            if tunnel.poll() is not None or web.poll() is not None:
                raise RuntimeError('Preview process exited; stopping public sharing.')
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 130
    except alpha_dev.StopRequested as exc:
        return 128 + exc.signum
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'Mobile preview failed: {exc}', file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        alpha_dev.stop(processes)
        if owns_status:
            status_path.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
