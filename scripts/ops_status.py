#!/usr/bin/env python3
"""Read-only, aggregate beta operations snapshot. No photos, tokens, or owner IDs."""
import json
import os

import psycopg


def snapshot(url: str) -> dict:
    with psycopg.connect(url, connect_timeout=5, options='-c default_transaction_read_only=on -c statement_timeout=10000') as conn:
        jobs = dict(conn.execute('select status,count(*) from jobs group by status').fetchall())
        oldest = conn.execute("select coalesce(extract(epoch from now()-min(created_at)),0) from jobs where status='queued' and retention_expires_at>now()").fetchone()[0]
        stale = conn.execute("select count(*) from jobs where status='running' and (lease_expires_at is null or lease_expires_at<=now())").fetchone()[0]
        objects = conn.execute("select count(*) filter (where status='delete_failed'),count(*) filter (where retention_expires_at<=now() and status<>'deleted') from tenant_objects").fetchone()
        events = {event: {'count': int(count), 'accounts': int(accounts)} for event, count, accounts in conn.execute("select event,sum(count),count(distinct owner_id) from beta_events_daily where usage_date>current_date-30 group by event")}
        feedback = dict(conn.execute("select topic,count(*) from beta_feedback where expires_at>now() group by topic").fetchall())
        return {'eventsLast30Days': events, 'feedbackByTopic': feedback, 'jobs': jobs, 'oldestQueuedSeconds': float(oldest), 'staleLeases': stale, 'failedObjectDeletes': objects[0], 'expiredObjectsPendingDelete': objects[1]}


if __name__ == '__main__':
    try:
        print(json.dumps(snapshot(os.environ['DATABASE_URL']), indent=2))
    except Exception as exc:
        print(json.dumps({'ok': False, 'errorClass': type(exc).__name__}))
        raise SystemExit(1) from None
