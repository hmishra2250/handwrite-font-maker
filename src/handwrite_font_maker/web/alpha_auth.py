"""Operator-provisioned, single-host alpha accounts. No public signup or email service."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import getpass
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from uuid import uuid4

from .security import SecurityError
from .alpha_files import prepare_alpha_database

SESSION_SECONDS = 86400
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 3
_KDF_SLOTS = threading.BoundedSemaphore(2)


def _email(value: object) -> str:
    if not isinstance(value, str) or len(value) > 254 or value.count('@') != 1 or any(c.isspace() for c in value.strip()):
        raise ValueError('A valid email address is required.')
    result = value.strip().lower()
    if not all(result.split('@')):
        raise ValueError('A valid email address is required.')
    return result


def _password(value: object) -> str:
    if not isinstance(value, str) or not 12 <= len(value) <= 256 or len(value.encode()) > 1024:
        raise ValueError('Use a password of 12–256 characters (at most 1024 UTF-8 bytes).')
    return value


def _derive(password: str, salt: bytes) -> bytes:
    if not _KDF_SLOTS.acquire(blocking=False):
        raise SecurityError(429, 'AUTH_RATE_LIMITED', 'Sign-in is busy. Try again shortly.')
    try:
        return hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=64 * 1024 * 1024, dklen=64)
    finally:
        _KDF_SLOTS.release()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AlphaAuthStore:
    def __init__(self, path: str | Path | None):
        if not path or not Path(path).is_absolute():
            raise RuntimeError('An absolute ALPHA_DATABASE_PATH is required.')
        self.path = str(prepare_alpha_database(path))
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS alpha_users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                    salt BLOB NOT NULL, password_hash BLOB NOT NULL,
                    algorithm TEXT NOT NULL DEFAULT 'scrypt-n32768-r8-p3',
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alpha_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES alpha_users(id), expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS alpha_sessions_user ON alpha_sessions(user_id);
                CREATE TABLE IF NOT EXISTS alpha_auth_attempts (
                    bucket TEXT PRIMARY KEY, started_at REAL NOT NULL, attempts INTEGER NOT NULL
                );
            ''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA foreign_keys=ON')
            yield conn
        finally:
            conn.close()

    def provision(self, email: str, password: str) -> dict[str, str]:
        email, password = _email(email), _password(password)
        salt = secrets.token_bytes(16)
        digest = _derive(password, salt)
        user = {'id': str(uuid4()), 'email': email}
        with self.connect() as conn:
            try:
                conn.execute('INSERT INTO alpha_users(id,email,salt,password_hash,created_at) VALUES(?,?,?,?,?)', (user['id'], email, salt, digest, time.time()))
            except sqlite3.IntegrityError as exc:
                raise ValueError('Account already exists; use reset-password.') from exc
        return user

    def _rate_limit(self, email: str):
        now = time.time()
        # Reserve per-account attempts, including nonexistent accounts, before KDF.
        # Do not persist a global lockout that any caller could exhaust for everyone.
        # KDF concurrency is bounded separately; trusted ingress handles per-IP limits.
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.execute('DELETE FROM alpha_auth_attempts WHERE started_at <= ?', (now - 900,))
                for bucket, maximum in [('email:' + _token_hash(email), 10)]:
                    row = conn.execute('SELECT attempts FROM alpha_auth_attempts WHERE bucket=?', (bucket,)).fetchone()
                    if row and row['attempts'] >= maximum:
                        raise SecurityError(429, 'AUTH_RATE_LIMITED', 'Too many sign-in attempts. Try again in 15 minutes.')
                    conn.execute('INSERT INTO alpha_auth_attempts VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1', (bucket, now))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def login(self, email: object, password: object) -> dict[str, object]:
        try:
            normalized = _email(email)
        except ValueError:
            normalized = 'invalid'
        self._rate_limit(normalized)
        if not isinstance(password, str) or len(password) > 256 or len(password.encode()) > 1024:
            raise SecurityError(401, 'AUTH_INVALID', 'Invalid email or password.')
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM alpha_users WHERE email=?', (normalized,)).fetchone()
        digest = _derive(password, bytes(row['salt']) if row else b'\0' * 16)
        if row is None or not hmac.compare_digest(digest, bytes(row['password_hash'])) or not row['active']:
            raise SecurityError(401, 'AUTH_INVALID', 'Invalid email or password.')
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                # Recheck after expensive KDF: reset/disable must win this race.
                fresh = conn.execute('SELECT active,password_hash FROM alpha_users WHERE id=?', (row['id'],)).fetchone()
                if not fresh or not fresh['active'] or fresh['password_hash'] != row['password_hash']:
                    raise SecurityError(401, 'AUTH_INVALID', 'Invalid email or password.')
                conn.execute('DELETE FROM alpha_sessions WHERE expires_at<=?', (time.time(),))
                conn.execute('INSERT INTO alpha_sessions VALUES(?,?,?)', (_token_hash(token), row['id'], time.time() + SESSION_SECONDS))
                conn.execute('DELETE FROM alpha_auth_attempts WHERE bucket=?', ('email:' + _token_hash(normalized),))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {'accessToken': token, 'expiresIn': SESSION_SECONDS, 'user': {'id': row['id'], 'email': row['email']}}

    def verify(self, token: str) -> dict[str, str]:
        if not isinstance(token, str) or not 40 <= len(token) <= 128:
            raise SecurityError(401, 'AUTH_REQUIRED', 'Sign in to continue.')
        with self.connect() as conn:
            row = conn.execute('''SELECT u.id,u.email FROM alpha_sessions s JOIN alpha_users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.active=1''', (_token_hash(token), time.time())).fetchone()
        if row is None:
            raise SecurityError(401, 'AUTH_REQUIRED', 'Sign in to continue.')
        return {'id': row['id'], 'email': row['email']}

    def logout(self, token: str):
        with self.connect() as conn:
            conn.execute('DELETE FROM alpha_sessions WHERE token_hash=?', (_token_hash(token),))

    def reset_password(self, email: str, password: str, *, expected_hash: bytes | None = None):
        email, password = _email(email), _password(password)
        salt = secrets.token_bytes(16)
        digest = _derive(password, salt)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                row = conn.execute('SELECT id,password_hash FROM alpha_users WHERE email=?', (email,)).fetchone()
                if row is None:
                    raise ValueError('Account not found.')
                if expected_hash is not None and row['password_hash'] != expected_hash:
                    raise SecurityError(401, 'AUTH_INVALID', 'Password changed; sign in again.')
                conn.execute('UPDATE alpha_users SET salt=?,password_hash=? WHERE id=?', (salt, digest, row['id']))
                conn.execute('DELETE FROM alpha_sessions WHERE user_id=?', (row['id'],))
                conn.execute('DELETE FROM alpha_auth_attempts WHERE bucket=?', ('email:' + _token_hash(email),))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def change_password(self, token: str, current: object, new: object):
        user = self.verify(token)
        self._rate_limit(user['email'])
        if not isinstance(current, str) or len(current) > 256 or len(current.encode()) > 1024:
            raise SecurityError(401, 'AUTH_INVALID', 'Current password is incorrect.')
        _password(new)
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM alpha_users WHERE id=?', (user['id'],)).fetchone()
        if not row or not hmac.compare_digest(_derive(current, bytes(row['salt'])), bytes(row['password_hash'])):
            raise SecurityError(401, 'AUTH_INVALID', 'Current password is incorrect.')
        self.reset_password(user['email'], new, expected_hash=bytes(row['password_hash']))

    def disable(self, email: str):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                row = conn.execute('SELECT id FROM alpha_users WHERE email=?', (_email(email),)).fetchone()
                if not row:
                    raise ValueError('Account not found.')
                conn.execute('UPDATE alpha_users SET active=0 WHERE id=?', (row['id'],))
                conn.execute('DELETE FROM alpha_sessions WHERE user_id=?', (row['id'],))
                conn.commit()
            except Exception:
                conn.rollback()
                raise


def main():
    from .security import DeploymentMode, load_runtime_config
    parser = argparse.ArgumentParser(description='Private-alpha account administration; run only on the trusted host.')
    parser.add_argument('action', choices=['create-user', 'reset-password', 'disable-user'])
    parser.add_argument('--email', required=True)
    parser.add_argument('--generate-password', action='store_true', help='Print a generated password once; deliver securely to the invited user.')
    args = parser.parse_args()
    config = load_runtime_config()
    if config.mode != DeploymentMode.PRIVATE_ALPHA:
        parser.error('Set DEPLOYMENT_MODE=private_alpha with the alpha environment first.')
    store = AlphaAuthStore(config.alpha_database_path)
    try:
        if args.action == 'disable-user':
            store.disable(args.email)
        else:
            password = secrets.token_urlsafe(24) if args.generate_password else getpass.getpass('Password (12+ characters): ')
            if args.action == 'create-user':
                store.provision(args.email, password)
            else:
                store.reset_password(args.email, password)
            if args.generate_password:
                print(f'One-time display — deliver privately: {password}')
        print('Account updated. Reset/disable revokes existing sessions.')
    except (ValueError, SecurityError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
