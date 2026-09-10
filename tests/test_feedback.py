import json
import os
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from handwrite_font_maker.web.feedback_store import submit, validate_payload, cleanup_feedback
from handwrite_font_maker.web.security import load_runtime_config, SecurityError
from handwrite_font_maker.web.tenant_store import PostgresTenantStore, QuotaExceeded


def test_feedback_rejects_unconsented_images_metadata_and_unknown_events():
    for value in ({'event': 'glyph_accepted'}, {'event': 'glyph_accepted', 'consent': False}, {'event': 'secret-text', 'consent': True}, {'event': 'glyph_accepted', 'consent': True, 'projectId': 'private'}):
        with pytest.raises(SecurityError): validate_payload(value, event=True)
    with pytest.raises(SecurityError): validate_payload({'topic': 'extraction', 'message': 'Something went wrong', 'consent': True, 'image': 'data:image/png'}, event=False)
    assert validate_payload({'topic': 'other', 'message': ' Useful feedback ', 'consent': True}, event=False) == {'topic': 'other', 'message': 'Useful feedback'}


def test_local_counts_are_atomic_bounded_and_contain_no_capture_data(tmp_path):
    path = tmp_path / 'feedback.json'
    config = load_runtime_config({'DEPLOYMENT_MODE': 'local'})
    def write(_): submit(config, 'local_dev', {'event': 'glyph_accepted', 'consent': True}, event=True, local_path=path)
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(write, range(30)))
    data = json.loads(path.read_text())
    assert data['events'][0]['count'] == 30
    assert set(data['events'][0]) == {'day', 'event', 'count'}
    for _ in range(10): submit(config, 'local_dev', {'topic': 'other', 'message': 'Useful feedback', 'consent': True}, event=False, local_path=path)
    with pytest.raises(QuotaExceeded): submit(config, 'local_dev', {'topic': 'other', 'message': 'Useful feedback', 'consent': True}, event=False, local_path=path)
    assert len(json.loads(path.read_text())['feedback']) == 10


def test_postgres_feedback_quota_retention_and_rls():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url: pytest.skip('Use an isolated TEST_DATABASE_URL')
    store = PostgresTenantStore(url)
    with store._connect() as conn:
        for migration in sorted(Path('supabase/migrations').glob('*.sql')): conn.execute(migration.read_text())
    config = load_runtime_config({'DEPLOYMENT_MODE': 'invite_beta', 'DATABASE_URL': url, 'SUPABASE_URL': 'https://fixture.supabase.co', 'SUPABASE_ANON_KEY': 'anon', 'SUPABASE_SERVICE_ROLE_KEY': 'service', 'INTERNAL_API_KEY': 'i'*40, 'PROCESS_JOBS_INLINE': '0'})
    owner = str(uuid4())
    try:
        for _ in range(10): submit(config, owner, {'topic': 'extraction', 'message': 'The edge was clipped', 'consent': True}, event=False)
        with pytest.raises(QuotaExceeded): submit(config, owner, {'topic': 'other', 'message': 'Another message', 'consent': True}, event=False)
        submit(config, owner, {'event': 'build_succeeded', 'consent': True}, event=True)
        with store._connect() as conn:
            assert conn.execute('select count from beta_events_daily where owner_id=%s', (owner,)).fetchone()[0] == 1
            assert all(row[0] for row in conn.execute("select relrowsecurity from pg_class where relname in ('beta_feedback','beta_events_daily')"))
            conn.execute("update beta_feedback set expires_at=now()-interval '1 second' where owner_id=%s", (owner,))
            conn.execute("update beta_events_daily set usage_date=current_date-31 where owner_id=%s", (owner,))
        cleanup_feedback(config)
        with store._connect() as conn:
            assert conn.execute('select count(*) from beta_feedback where owner_id=%s', (owner,)).fetchone()[0] == 0
            assert conn.execute('select count(*) from beta_events_daily where owner_id=%s', (owner,)).fetchone()[0] == 0
    finally:
        with store._connect() as conn: conn.execute('delete from tenants where owner_id=%s', (owner,))


def test_local_cleanup_removes_expired_feedback_without_new_submission(tmp_path, monkeypatch):
    path = tmp_path / 'feedback.json'
    path.write_text(json.dumps({'events': [{'day': '2000-01-01', 'event': 'glyph_accepted', 'count': 2}], 'feedback': [{'day': '2000-01-01', 'topic': 'other', 'message': 'Expired text'}]}))
    monkeypatch.setenv('FEEDBACK_STORE_PATH', str(path))
    cleanup_feedback(load_runtime_config({'DEPLOYMENT_MODE': 'local'}))
    assert json.loads(path.read_text()) == {'events': [], 'feedback': []}
