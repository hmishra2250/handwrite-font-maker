"""Opt-in account-linked counts and text feedback. Never accepts attachments/metadata."""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .security import RuntimeConfig, SecurityError
from .tenant_store import PostgresTenantStore, QuotaExceeded

EVENTS = {'upload_complete', 'glyph_accepted', 'build_succeeded', 'font_download_requested', 'font_used'}
TOPICS = {'extraction', 'installation', 'other'}


def validate_payload(payload: object, *, event: bool) -> dict[str, str]:
    if not isinstance(payload, dict) or payload.get('consent') is not True:
        raise SecurityError(400, 'CONSENT_REQUIRED', 'Explicit consent is required.')
    allowed = {'event', 'consent'} if event else {'topic', 'message', 'consent'}
    if set(payload) != allowed:
        raise SecurityError(400, 'INVALID_REQUEST', 'Only the documented fields are accepted; attachments are not supported.')
    if event:
        name = payload.get('event')
        if not isinstance(name, str) or name not in EVENTS:
            raise SecurityError(400, 'INVALID_REQUEST', 'Unknown event.')
        return {'event': name}
    topic, message = payload.get('topic'), payload.get('message')
    if not isinstance(topic, str) or topic not in TOPICS or not isinstance(message, str) or not 10 <= len(message.strip()) <= 1000 or '\x00' in message:
        raise SecurityError(400, 'INVALID_REQUEST', 'Choose a topic and provide 10 to 1000 characters of text.')
    return {'topic': topic, 'message': message.strip()}


def submit(config: RuntimeConfig, owner_id: str, payload: object, *, event: bool, local_path: Path | None = None) -> None:
    value = validate_payload(payload, event=event)
    if config.auth_required:
        store = PostgresTenantStore(config.database_url)
        with store._connect() as conn, conn.cursor() as cur:
            store._ensure_and_lock_tenant(cur, owner_id)
            if event:
                cur.execute("select coalesce(sum(count),0) from beta_events_daily where owner_id=%s::uuid and usage_date=current_date", (owner_id,))
                if cur.fetchone()[0] >= 500:
                    raise QuotaExceeded('Daily usage-count limit reached.')
                cur.execute("insert into beta_events_daily(owner_id,usage_date,event) values(%s::uuid,current_date,%s) on conflict(owner_id,usage_date,event) do update set count=beta_events_daily.count+1", (owner_id, value['event']))
            else:
                cur.execute("select count(*) from beta_feedback where owner_id=%s::uuid and created_at>=current_date", (owner_id,))
                if cur.fetchone()[0] >= 10:
                    raise QuotaExceeded('Daily feedback limit reached.')
                cur.execute("insert into beta_feedback(owner_id,topic,message) values(%s::uuid,%s,%s)", (owner_id, value['topic'], value['message']))
        return
    _local_write(local_path or Path(os.environ.get('FEEDBACK_STORE_PATH', '/tmp/handwrite-feedback.json')), value, event=event)


def _local_write(path: Path, value: dict[str, str] | None, *, event: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    cutoff = (now - timedelta(days=30)).date().isoformat()
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.exists() else {'events': [], 'feedback': []}
        for key in ('events', 'feedback'):
            data[key] = [item for item in data[key] if item['day'] > cutoff]
        if value is None:
            pass  # A scheduled cleanup only prunes, never records usage.
        elif event:
            if sum(item['count'] for item in data['events'] if item['day'] == day) >= 500:
                raise QuotaExceeded('Daily usage-count limit reached.')
            record = next((item for item in data['events'] if item['day'] == day and item['event'] == value['event']), None)
            if record:
                record['count'] += 1
            else:
                data['events'].append({'day': day, 'event': value['event'], 'count': 1})
        else:
            if sum(item['day'] == day for item in data['feedback']) >= 10:
                raise QuotaExceeded('Daily feedback limit reached.')
            data['feedback'].append({'day': day, **value})
        temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
        try:
            temp.write_text(json.dumps(data))
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def cleanup_feedback(config: RuntimeConfig) -> None:
    if not config.database_url:
        path = Path(os.environ.get('FEEDBACK_STORE_PATH', '/tmp/handwrite-feedback.json'))
        if path.exists():
            _local_write(path, None, event=False)
        return
    store = PostgresTenantStore(config.database_url)
    with store._connect() as conn, conn.cursor() as cur:
        cur.execute('delete from beta_feedback where expires_at<=now()')
        cur.execute("delete from beta_events_daily where usage_date<=current_date-30")


def handle_feedback(handler, payload: object, *, event: bool) -> None:
    from .server import _error, _json
    try:
        config, auth = handler._request_context()
        submit(config, auth.owner_id, payload, event=event)
    except (SecurityError, QuotaExceeded) as exc:
        _error(handler, exc.status, exc.code, str(exc))
    except Exception:
        _error(handler, 503, 'FEEDBACK_UNAVAILABLE', 'Feedback storage is temporarily unavailable.')
    else:
        _json(handler, 201, {'ok': True})
