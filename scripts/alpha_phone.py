#!/usr/bin/env python3
"""Run a LAN-only HTTPS phone preview alongside the localhost private alpha.

Requires the normal alpha API/worker to be running. Never changes system trust,
opens a public tunnel, or shares the development CA private key.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

import alpha_dev
import alpha_preflight

ROOT = Path(__file__).resolve().parents[1]


def private_ipv4(value: str) -> str:
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise argparse.ArgumentTypeError('Use the computer\'s private Wi-Fi IPv4 address.') from exc
    if not any(address in network for network in (ipaddress.ip_network('10.0.0.0/8'), ipaddress.ip_network('172.16.0.0/12'), ipaddress.ip_network('192.168.0.0/16'))):
        raise argparse.ArgumentTypeError('Only private LAN addresses are allowed; no public exposure.')
    return str(address)


def prepare_certificate(directory: Path, host: str) -> None:
    """Create a short-lived, dedicated test CA and IP certificate; never install it."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    ca_key, ca_cert = directory / 'ca.key', directory / 'handwrite-phone-ca.crt'
    key, cert = directory / 'server.key', directory / 'server.crt'
    if any(path.exists() for path in (ca_key, ca_cert, key, cert)):
        raise ValueError('Phone TLS files already exist. Reuse them, or choose a new --tls-dir; nothing was overwritten.')
    old_umask = os.umask(0o077)
    try:
        def run(*args: str) -> None:
            subprocess.run(['openssl', *args], check=True, capture_output=True)
        run('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '30', '-sha256',
            '-subj', '/CN=Handwrite phone testing ONLY', '-keyout', str(ca_key), '-out', str(ca_cert),
            '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        run('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-subj', f'/CN={host}',
            '-keyout', str(key), '-out', str(directory / 'server.csr'))
        extensions = directory / 'server.ext'
        extensions.write_text(f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:{host}\n')
        run('x509', '-req', '-in', str(directory / 'server.csr'), '-CA', str(ca_cert), '-CAkey', str(ca_key),
            '-CAcreateserial', '-out', str(cert), '-days', '7', '-sha256', '-extfile', str(extensions))
        # DER copy is convenient to transfer/install on phones. This is public, not a key.
        run('x509', '-in', str(ca_cert), '-outform', 'DER', '-out', str(directory / 'handwrite-phone-ca.cer'))
    finally:
        os.umask(old_umask)


def phone_environment(env_file: Path, host: str, port: int, api_port: int) -> dict[str, str]:
    env = dict(os.environ)
    env.update(alpha_preflight.parse_env_file(env_file))
    env = alpha_dev.localize_container_defaults(env)
    env.update(SITE_URL=f'https://{host}:{port}', WORKER_API_BASE_URL=f'http://127.0.0.1:{api_port}',
               HANDWRITE_PHONE_PREVIEW='1', HOSTNAME=host, PORT=str(port))
    errors = alpha_dev.check_local_config(env)
    if errors:
        raise ValueError('; '.join(errors))
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, type=private_ipv4, help='Computer Wi-Fi IPv4 address, e.g. 192.168.1.3')
    parser.add_argument('--port', type=int, default=3443)
    parser.add_argument('--api-port', type=int, default=8000)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.alpha')
    parser.add_argument('--tls-dir', type=Path, default=ROOT / '.alpha/phone-tls')
    parser.add_argument('--prepare', action='store_true', help='Generate test certificates only; does not install trust or start a server')
    args = parser.parse_args(argv)
    if not all(1024 <= port <= 65535 for port in (args.port, args.api_port)):
        parser.error('Ports must be between 1024 and 65535.')
    try:
        if args.prepare:
            prepare_certificate(args.tls_dir, args.host)
            print(f'Certificate ready: {args.tls_dir / "handwrite-phone-ca.cer"}')
            print('Transfer ONLY this public .cer file to your phone; never transfer .key files. See docs/PHONE-TESTING.md.')
            return 0
        env = phone_environment(args.env_file, args.host, args.port, args.api_port)
        cert, key = args.tls_dir / 'server.crt', args.tls_dir / 'server.key'
        if not cert.is_file() or not key.is_file():
            raise ValueError('Missing phone TLS certificate/key. Run with --prepare first.')
        # Reject expired or wrong-IP certificates instead of suggesting a browser bypass.
        for check in (['-checkip', args.host], ['-checkend', '60']):
            subprocess.run(['openssl', 'x509', '-in', str(cert), '-noout', *check], check=True, capture_output=True)
        with urllib.request.urlopen(f'http://127.0.0.1:{args.api_port}/readyz', timeout=5) as response:
            if response.status != 200:
                raise ValueError('Start the private alpha API and worker first.')
        command = ['npm', 'run', 'dev', '--', '--hostname', args.host, '--port', str(args.port),
                   '--experimental-https', '--experimental-https-key', str(key.resolve()), '--experimental-https-cert', str(cert.resolve())]
        print(f'Phone preview: {env["SITE_URL"]} (same Wi-Fi; trust the dedicated test CA first).', flush=True)
        # Replace the launcher so normal terminal/SIGTERM cleanup reaches Next.
        os.chdir(ROOT / 'web')
        os.execvpe(command[0], command, env)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Phone preview could not start: {exc if not isinstance(exc, subprocess.CalledProcessError) else "TLS certificate command failed. Check the certificate and IP address."}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
