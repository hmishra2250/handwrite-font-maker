"""Restrict alpha credential/database files without changing shared directories."""
import os
from pathlib import Path
import stat


def prepare_alpha_database(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        raise RuntimeError('An absolute alpha database path is required.')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = target.parent.stat()
    if parent.st_mode & 0o022:
        raise RuntimeError('Alpha database needs a dedicated directory not writable by group/others.')
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(target, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError('Alpha database must be a regular file.')
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    # SQLite creates WAL/SHM with the database file's mode. Harden older sidecars.
    for suffix in ('-wal', '-shm'):
        sidecar = Path(str(target) + suffix)
        try:
            fd = os.open(sidecar, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
        except FileNotFoundError:
            continue
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
    return target
