#!/usr/bin/env python3
"""Apply additive SQL migrations in order with a transactional migration ledger.

DATABASE_URL=... python scripts/migrate.py [--check]
Always back up a non-disposable database first. This never performs down-migrations.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import psycopg


def migrate(database_url: str, *, check: bool = False, directory: Path | None = None) -> list[str]:
    directory = directory or Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise RuntimeError("No migration files found")
    applied = []
    with psycopg.connect(database_url, connect_timeout=10) as conn:
        # One transaction: failed migrations leave neither partial schema nor a false ledger entry.
        conn.execute("select pg_advisory_xact_lock(719842031)")
        if check:
            if conn.execute("select to_regclass('handwrite_schema_migrations')").fetchone()[0] is None:
                raise RuntimeError("Migration ledger is missing")
        else:
            conn.execute("create table if not exists handwrite_schema_migrations (name text primary key, sha256 text not null, applied_at timestamptz not null default now())")
        rows = dict(conn.execute("select name,sha256 from handwrite_schema_migrations").fetchall())
        unknown = set(rows) - {p.name for p in files}
        if unknown:
            raise RuntimeError("Database has newer migrations than this application")
        for path in files:
            body = path.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if path.name in rows:
                if rows[path.name] != digest:
                    raise RuntimeError(f"Applied migration checksum changed: {path.name}")
                continue
            if check:
                raise RuntimeError(f"Pending migration: {path.name}")
            conn.execute(body.decode("utf-8"))
            conn.execute("insert into handwrite_schema_migrations(name,sha256) values(%s,%s)", (path.name, digest))
            applied.append(path.name)
    return applied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL is required")
    try:
        result = migrate(url, check=args.check)
    except Exception as exc:
        # Driver errors can contain connection strings. Do not dump them into deployment logs.
        print(f"Migration check failed ({type(exc).__name__}); inspect schema/configuration securely.")
        raise SystemExit(1) from None
    print("Schema up to date" if not result else "Applied: " + ", ".join(result))


if __name__ == "__main__":
    main()
