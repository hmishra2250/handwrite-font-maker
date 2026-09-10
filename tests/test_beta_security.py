from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from handwrite_font_maker.web import security
from handwrite_font_maker.web.contracts import FontRequest, InputPhoto
from handwrite_font_maker.web.security import authenticate_request, load_runtime_config
from handwrite_font_maker.web.server import Handler
from handwrite_font_maker.web.tenant_store import PostgresTenantStore, QuotaExceeded, TenantLimits

PG_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://handwrite:local-test-only@127.0.0.1:5438/handwrite_verify")


def _pg_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(PG_URL, connect_timeout=2):
            return True
    except Exception:
        return False



@pytest.fixture
def migrated_pg():
    if not _pg_available():
        pytest.skip("local verification Postgres unavailable")
    import psycopg

    with psycopg.connect(PG_URL) as conn:
        for migration in sorted(Path("supabase/migrations").glob("*.sql")):
            with conn.cursor() as cur:
                cur.execute(migration.read_text(encoding="utf-8"))
    return PG_URL


@pytest.fixture
def beta_env(monkeypatch, migrated_pg):
    monkeypatch.setenv("DEPLOYMENT_MODE", "invite_beta")
    monkeypatch.setenv("DATABASE_URL", migrated_pg)
    monkeypatch.setenv("SUPABASE_URL", "https://unit-test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "s" * 40)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "a" * 40)
    monkeypatch.setenv("INTERNAL_API_KEY", "i" * 40)
    monkeypatch.setenv("PROCESS_JOBS_INLINE", "0")
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", "unit-bucket")
    monkeypatch.setenv("DAILY_UPLOAD_LIMIT", "2")
    monkeypatch.setenv("DAILY_UPLOAD_BYTES_LIMIT", "10000")
    monkeypatch.setenv("DAILY_PREVIEW_LIMIT", "1")
    monkeypatch.setenv("DAILY_BUILD_LIMIT", "1")
    monkeypatch.setenv("ACTIVE_JOB_LIMIT", "1")
    return migrated_pg


def _cleanup_owner(database_url: str, owner_id: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("delete from tenant_object_job_refs where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from tenant_objects where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from tenant_daily_usage where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from jobs where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from tenants where owner_id=%s::uuid", (owner_id,))


def test_invite_beta_config_fails_closed(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "invite_beta")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        load_runtime_config()
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("SUPABASE_URL", "https://unit-test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "s" * 40)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "a" * 40)
    monkeypatch.setenv("INTERNAL_API_KEY", "short")
    monkeypatch.setenv("PROCESS_JOBS_INLINE", "0")
    with pytest.raises(RuntimeError, match="INTERNAL_API_KEY"):
        load_runtime_config()
    monkeypatch.setenv("INTERNAL_API_KEY", "i" * 40)
    monkeypatch.setenv("PROCESS_JOBS_INLINE", "1")
    with pytest.raises(RuntimeError, match="PROCESS_JOBS_INLINE=0"):
        load_runtime_config()
    monkeypatch.setenv("PROCESS_JOBS_INLINE", "0")
    monkeypatch.setenv("DEPLOYMENT_MODE", "   ")
    with pytest.raises(RuntimeError, match="DEPLOYMENT_MODE must be explicit"):
        load_runtime_config()
    monkeypatch.setenv("DEPLOYMENT_MODE", "invite_beta")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    with pytest.raises(RuntimeError, match="Billing is unavailable"):
        load_runtime_config()


def test_auth_verifies_internal_key_and_fetches_supabase_user(monkeypatch, beta_env):
    calls = []

    def fake_fetch(url: str, anon_key: str, token: str):
        calls.append((url, anon_key, token))
        return {"id": "11111111-1111-4111-8111-111111111111", "email": "user@example.test", "app_metadata": {"handwrite_beta": True}}

    monkeypatch.setattr(security, "_fetch_supabase_user", fake_fetch)
    config = load_runtime_config()
    auth = authenticate_request({"x-internal-api-key": "i" * 40, "authorization": "Bearer access.jwt.value"}, config)
    assert auth.owner_id == "11111111-1111-4111-8111-111111111111"
    assert auth.email == "user@example.test"
    assert calls == [("https://unit-test.supabase.co", "a" * 40, "access.jwt.value")]
    with pytest.raises(security.SecurityError):
        authenticate_request({"x-internal-api-key": "bad", "authorization": "Bearer access.jwt.value"}, config)
    monkeypatch.setattr(security, "_fetch_supabase_user", lambda *_: {"id": "11111111-1111-4111-8111-111111111111", "app_metadata": {}})
    with pytest.raises(security.SecurityError, match="invite beta"):
        authenticate_request({"x-internal-api-key": "i" * 40, "authorization": "Bearer access.jwt.value"}, config)


def test_tenant_store_enforces_upload_ownership_quotas_job_owner_and_expiry(beta_env):
    owner_a = str(uuid4())
    owner_b = str(uuid4())
    store = PostgresTenantStore(beta_env)
    limits = TenantLimits(daily_upload_limit=1, daily_upload_bytes_limit=5000, daily_preview_limit=1, daily_build_limit=1, active_job_limit=1)
    try:
        registered = store.register_upload(owner_id=owner_a, bucket="unit-bucket", object_key=f"tenants/{owner_a}/jobs/job_a/input/original.png", content_type="image/png", size_bytes=100, limits=limits)
        assert registered.object_key.endswith("original.png")
        with pytest.raises(Exception):
            store.assert_object_access(owner_id=owner_b, bucket="unit-bucket", object_key=registered.object_key, require_uploaded=False)
        store.assert_object_access(owner_id=owner_a, bucket="unit-bucket", object_key=registered.object_key, require_uploaded=False)
        store.mark_uploaded(owner_id=owner_a, bucket="unit-bucket", object_key=registered.object_key, size_bytes=100)
        store.assert_object_access(owner_id=owner_a, bucket="unit-bucket", object_key=registered.object_key)
        with pytest.raises(QuotaExceeded):
            store.register_upload(owner_id=owner_a, bucket="unit-bucket", object_key=f"tenants/{owner_a}/jobs/job_b/input/original.png", content_type="image/png", size_bytes=100, limits=limits)
        store.record_preview(owner_id=owner_a, limits=limits)
        with pytest.raises(QuotaExceeded):
            store.record_preview(owner_id=owner_a, limits=limits)
        job = store.create_job(
            owner_id=owner_a,
            input_photo=InputPhoto(registered.object_key, "image/png", 100, bucket="unit-bucket"),
            font=FontRequest("BetaFont", "Beta Font"),
            capture=None,
            bucket="unit-bucket",
            limits=limits,
        )
        store.authorize_job(owner_id=owner_a, job_id=job.id)
        with pytest.raises(Exception):
            store.authorize_job(owner_id=owner_b, job_id=job.id)
        import psycopg

        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("update jobs set retention_expires_at=now()-interval '1 second' where id=%s", (job.id,))
        with pytest.raises(Exception):
            store.authorize_job(owner_id=owner_a, job_id=job.id)
    finally:
        _cleanup_owner(beta_env, owner_a)
        _cleanup_owner(beta_env, owner_b)


class FakeObjectStore:
    def signed_upload_url(self, object_key: str) -> str:
        return f"signed://{object_key}"

    def signed_download_url(self, object_key: str, expires_in: int = 1800) -> str:
        return f"download://{object_key}?expiresIn={expires_in}"

    def download_to_path(self, object_key: str, destination: Path) -> None:
        image = Image.new("RGB", (64, 64), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 48, 48), fill="black")
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG")

    def upload_from_path(self, object_key: str, source: Path, content_type: str) -> None:
        pass

    def delete_object(self, object_key: str) -> None:
        pass



def _png_bytes() -> bytes:
    import io

    image = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 48, 48), fill="black")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _put_bytes(url: str, data: bytes, headers: dict[str, str] | None = None):
    request_headers = {"content-type": "image/png", **(headers or {})}
    request = urllib.request.Request(url, data=data, method="PUT", headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))

def _start_server(tmp_path: Path):
    Handler.store_path = tmp_path / "jobs.json"
    Handler.object_root = tmp_path / "objects"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _post_json(url: str, payload: object, headers: dict[str, str] | None = None):
    request_headers = {"content-type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_server_upload_requires_auth_and_registers_owner(monkeypatch, tmp_path, beta_env):
    owner_id = str(uuid4())
    monkeypatch.setattr(security, "_fetch_supabase_user", lambda *_: {"id": owner_id, "app_metadata": {"handwrite_beta": True}})
    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", lambda _root: FakeObjectStore())
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(base + "/uploads", {"filename": "x.png", "contentType": "image/png", "sizeBytes": len(_png_bytes())})
        assert status == 401
        status, payload = _post_json(
            base + "/uploads",
            {"filename": "x.png", "contentType": "image/png", "sizeBytes": len(_png_bytes())},
            {"x-internal-api-key": "i" * 40, "authorization": "Bearer token"},
        )
        assert status == 200
        assert payload["objectKey"].startswith(f"tenants/{owner_id}/jobs/job_")
        PostgresTenantStore(beta_env).assert_object_access(owner_id=owner_id, bucket="unit-bucket", object_key=payload["objectKey"], require_uploaded=False)
        put_status, _ = _put_bytes(base + payload["uploadUrl"], _png_bytes(), _auth("token"))
        assert put_status == 200
        PostgresTenantStore(beta_env).assert_object_access(owner_id=owner_id, bucket="unit-bucket", object_key=payload["objectKey"])
    finally:
        server.shutdown()
        _cleanup_owner(beta_env, owner_id)


def test_delete_preserves_reused_live_upload_then_deletes_after_last_ref(beta_env):
    owner = str(uuid4())
    store = PostgresTenantStore(beta_env)
    limits = TenantLimits(daily_upload_limit=5, daily_upload_bytes_limit=5000, daily_preview_limit=5, daily_build_limit=5, active_job_limit=5)
    deleted: list[str] = []

    class RecordingDeleteStore(FakeObjectStore):
        def delete_object(self, object_key: str) -> None:
            deleted.append(object_key)

    try:
        object_key = f"tenants/{owner}/jobs/reused/input/original.png"
        store.register_upload(owner_id=owner, bucket="unit-bucket", object_key=object_key, content_type="image/png", size_bytes=100, limits=limits)
        store.mark_uploaded(owner_id=owner, bucket="unit-bucket", object_key=object_key, size_bytes=100)
        job1 = store.create_job(owner_id=owner, input_photo=InputPhoto(object_key, "image/png", 100, bucket="unit-bucket"), font=FontRequest("ReuseOne", "Reuse One"), capture=None, bucket="unit-bucket", limits=limits)
        job2 = store.create_job(owner_id=owner, input_photo=InputPhoto(object_key, "image/png", 100, bucket="unit-bucket"), font=FontRequest("ReuseTwo", "Reuse Two"), capture=None, bucket="unit-bucket", limits=limits)

        result = store.delete_job(owner_id=owner, job_id=job1.id, object_store=RecordingDeleteStore())
        assert result == {"deletedObjects": 0, "failedObjects": 0}
        assert deleted == []

        result = store.delete_job(owner_id=owner, job_id=job2.id, object_store=RecordingDeleteStore())
        assert result == {"deletedObjects": 1, "failedObjects": 0}
        assert deleted == [object_key]
    finally:
        _cleanup_owner(beta_env, owner)


def _get_json(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, method="GET", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _auth(token: str) -> dict[str, str]:
    return {"x-internal-api-key": "i" * 40, "authorization": f"Bearer {token}"}


def test_http_jobs_are_owner_bound_quota_limited_and_expire(monkeypatch, tmp_path, beta_env):
    owner_a = str(uuid4())
    owner_b = str(uuid4())
    token_owner = {"token-a": owner_a, "token-b": owner_b}
    monkeypatch.setattr(security, "_fetch_supabase_user", lambda _url, _anon, token: {"id": token_owner[token], "app_metadata": {"handwrite_beta": True}})
    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", lambda _root: FakeObjectStore())
    server, base = _start_server(tmp_path)
    try:
        status, upload = _post_json(base + "/uploads", {"filename": "x.png", "contentType": "image/png", "sizeBytes": len(_png_bytes())}, _auth("token-a"))
        assert status == 200
        put_status, _ = _put_bytes(base + upload["uploadUrl"], _png_bytes(), _auth("token-a"))
        assert put_status == 200
        job_body = {"inputPhoto": {"objectKey": upload["objectKey"], "contentType": "image/png", "sizeBytes": 100}, "font": {"fontName": "OwnerFont", "familyName": "Owner Font"}}
        status, job = _post_json(base + "/jobs", job_body, _auth("token-a"))
        assert status == 202
        status, _ = _post_json(base + "/jobs", job_body, _auth("token-a"))
        assert status == 429
        status, _ = _get_json(base + f"/jobs/{job['jobId']}", _auth("token-b"))
        assert status == 404
        status, payload = _get_json(base + f"/jobs/{job['jobId']}", _auth("token-a"))
        assert status == 200
        assert payload["jobId"] == job["jobId"]

        import psycopg

        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("update jobs set retention_expires_at=now()-interval '1 second' where id=%s", (job["jobId"],))
        status, _ = _get_json(base + f"/jobs/{job['jobId']}", _auth("token-a"))
        assert status == 404
    finally:
        server.shutdown()
        _cleanup_owner(beta_env, owner_a)
        _cleanup_owner(beta_env, owner_b)


def test_http_guided_secondary_keys_must_belong_to_owner(monkeypatch, tmp_path, beta_env):
    owner_a = str(uuid4())
    owner_b = str(uuid4())
    monkeypatch.setenv("DAILY_UPLOAD_LIMIT", "5")
    monkeypatch.setattr(security, "_fetch_supabase_user", lambda _url, _anon, token: {"id": owner_a if token == "token-a" else owner_b, "app_metadata": {"handwrite_beta": True}})
    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", lambda _root: FakeObjectStore())
    server, base = _start_server(tmp_path)
    try:
        status, upload_a = _post_json(base + "/uploads", {"filename": "a.png", "contentType": "image/png", "sizeBytes": len(_png_bytes())}, _auth("token-a"))
        assert status == 200
        put_status, _ = _put_bytes(base + upload_a["uploadUrl"], _png_bytes(), _auth("token-a"))
        assert put_status == 200
        status, upload_b = _post_json(base + "/uploads", {"filename": "b.png", "contentType": "image/png", "sizeBytes": len(_png_bytes())}, _auth("token-b"))
        assert status == 200
        put_status, _ = _put_bytes(base + upload_b["uploadUrl"], _png_bytes(), _auth("token-b"))
        assert put_status == 200
        status, payload = _post_json(
            base + "/jobs",
            {
                "inputPhoto": {"objectKey": upload_a["objectKey"], "contentType": "image/png", "sizeBytes": 100},
                "font": {"fontName": "GuidedOwner", "familyName": "Guided Owner"},
                "capture": {
                    "mode": "guided",
                    "format": "mask-v1",
                    "glyphs": [
                        {"char": "A", "inputPhoto": {"objectKey": upload_a["objectKey"], "contentType": "image/png", "sizeBytes": 100}, "baseline": 0.7},
                        {"char": "B", "inputPhoto": {"objectKey": upload_b["objectKey"], "contentType": "image/png", "sizeBytes": 100}, "baseline": 0.7},
                    ],
                },
            },
            _auth("token-a"),
        )
        assert status == 400
        assert payload["error"]["code"] == "UPLOAD_OBJECT_MISSING"
    finally:
        server.shutdown()
        _cleanup_owner(beta_env, owner_a)
        _cleanup_owner(beta_env, owner_b)


def test_capture_foreground_rejects_when_local_slot_busy(monkeypatch, tmp_path):
    import threading as thread_mod

    monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    slot = thread_mod.BoundedSemaphore(1)
    assert slot.acquire(blocking=False)
    monkeypatch.setattr("handwrite_font_maker.web.server._foreground_slot", lambda: slot)
    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", lambda _root: FakeObjectStore())
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(base + "/capture/foreground", {"inputPhoto": {"objectKey": "jobs/busy/input/original.png", "contentType": "image/png", "sizeBytes": 100}, "rectangle": [0.1, 0.1, 0.9, 0.9]})
    finally:
        slot.release()
        server.shutdown()
    assert status == 503
    assert payload["error"]["code"] == "SEGMENTATION_BUSY"


def test_worker_artifact_registry_requires_live_attempt_and_marks_uploaded(beta_env):
    from handwrite_font_maker.web.job_store import PostgresJobStore
    from handwrite_font_maker.web.tenant_store import WorkerArtifactRegistry

    owner = str(uuid4())
    store = PostgresTenantStore(beta_env)
    limits = TenantLimits(daily_upload_limit=5, daily_upload_bytes_limit=5000, daily_preview_limit=5, daily_build_limit=5, active_job_limit=5)
    try:
        object_key = f"tenants/{owner}/jobs/source/input/original.png"
        store.register_upload(owner_id=owner, bucket="unit-bucket", object_key=object_key, content_type="image/png", size_bytes=100, limits=limits)
        store.mark_uploaded(owner_id=owner, bucket="unit-bucket", object_key=object_key, size_bytes=100)
        queued = store.create_job(owner_id=owner, input_photo=InputPhoto(object_key, "image/png", 100, bucket="unit-bucket"), font=FontRequest("ArtifactFont", "Artifact Font"), capture=None, bucket="unit-bucket", limits=limits)
        with pytest.raises(Exception):
            WorkerArtifactRegistry(queued).register_attempt_artifact(object_key=f"jobs/{queued.id}/attempts/missing/artifacts/a.ttf", content_type="font/ttf", size_bytes=3, kind="ttf")
        claimed = PostgresJobStore(beta_env).claim(queued.id)
        assert claimed is not None
        artifact_key = f"jobs/{claimed.id}/attempts/{claimed.attempt_id}/artifacts/a.ttf"
        registry = WorkerArtifactRegistry(claimed)
        registry.register_attempt_artifact(object_key=artifact_key, content_type="font/ttf", size_bytes=3, kind="ttf")
        import psycopg

        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("select status from tenant_objects where bucket='unit-bucket' and object_key=%s", (artifact_key,))
            assert cur.fetchone()[0] == "registered"
        registry.mark_uploaded(object_key=artifact_key, size_bytes=3)
        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("select status from tenant_objects where bucket='unit-bucket' and object_key=%s", (artifact_key,))
            assert cur.fetchone()[0] == "uploaded"
    finally:
        _cleanup_owner(beta_env, owner)


def test_proxy_put_is_one_shot(monkeypatch, tmp_path, beta_env):
    owner_id = str(uuid4())
    monkeypatch.setattr(security, "_fetch_supabase_user", lambda *_: {"id": owner_id, "app_metadata": {"handwrite_beta": True}})
    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", lambda _root: FakeObjectStore())
    server, base = _start_server(tmp_path)
    try:
        status, upload = _post_json(base + "/uploads", {"filename": "x.png", "contentType": "image/png", "sizeBytes": len(_png_bytes())}, _auth("token"))
        assert status == 200
        status, _ = _put_bytes(base + upload["uploadUrl"], _png_bytes(), _auth("token"))
        assert status == 200
        status, payload = _put_bytes(base + upload["uploadUrl"], _png_bytes(), _auth("token"))
        assert status == 400
        assert payload["error"]["code"] == "UPLOAD_OBJECT_MISSING"
    finally:
        server.shutdown()
        _cleanup_owner(beta_env, owner_id)


def test_proxy_put_concurrent_same_key_allows_one_uploader(monkeypatch, tmp_path, beta_env):
    owner_id = str(uuid4())
    first_upload_started = threading.Event()
    release_first_upload = threading.Event()

    class SlowObjectStore(FakeObjectStore):
        def upload_from_path(self, object_key: str, source: Path, content_type: str) -> None:
            first_upload_started.set()
            assert release_first_upload.wait(timeout=5)

    monkeypatch.setattr(security, "_fetch_supabase_user", lambda *_: {"id": owner_id, "app_metadata": {"handwrite_beta": True}})
    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", lambda _root: SlowObjectStore())
    server, base = _start_server(tmp_path)
    results: list[tuple[int, dict]] = []
    try:
        status, upload = _post_json(base + "/uploads", {"filename": "x.png", "contentType": "image/png", "sizeBytes": len(_png_bytes())}, _auth("token"))
        assert status == 200
        first = threading.Thread(target=lambda: results.append(_put_bytes(base + upload["uploadUrl"], _png_bytes(), _auth("token"))))
        first.start()
        assert first_upload_started.wait(timeout=5)
        second_status, second_payload = _put_bytes(base + upload["uploadUrl"], _png_bytes(), _auth("token"))
        release_first_upload.set()
        first.join(timeout=5)
        assert len(results) == 1
        assert sorted([results[0][0], second_status]) == [200, 400]
        if second_status == 400:
            assert second_payload["error"]["code"] == "UPLOAD_OBJECT_MISSING"
    finally:
        release_first_upload.set()
        server.shutdown()
        _cleanup_owner(beta_env, owner_id)


def test_late_upload_mark_after_delete_reschedules_cleanup(beta_env):
    owner = str(uuid4())
    store = PostgresTenantStore(beta_env)
    limits = TenantLimits(daily_upload_limit=5, daily_upload_bytes_limit=5000, daily_preview_limit=5, daily_build_limit=5, active_job_limit=5)
    try:
        object_key = f"tenants/{owner}/jobs/late/input/original.png"
        store.register_upload(owner_id=owner, bucket="unit-bucket", object_key=object_key, content_type="image/png", size_bytes=100, limits=limits)
        store.mark_uploaded(owner_id=owner, bucket="unit-bucket", object_key=object_key, size_bytes=100)
        job = store.create_job(owner_id=owner, input_photo=InputPhoto(object_key, "image/png", 100, bucket="unit-bucket"), font=FontRequest("LateFont", "Late Font"), capture=None, bucket="unit-bucket", limits=limits)
        store.delete_job(owner_id=owner, job_id=job.id, object_store=FakeObjectStore())
        with pytest.raises(Exception):
            store.mark_uploaded(owner_id=owner, bucket="unit-bucket", object_key=object_key, size_bytes=100)
        import psycopg

        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("select status, retention_expires_at <= now() from tenant_objects where bucket='unit-bucket' and object_key=%s", (object_key,))
            assert cur.fetchone() == ("delete_failed", True)
    finally:
        _cleanup_owner(beta_env, owner)


def test_late_artifact_upload_without_mark_callback_stays_tombstoned_until_grace(monkeypatch, beta_env):
    from handwrite_font_maker.web.job_store import PostgresJobStore
    from handwrite_font_maker.web.tenant_store import WorkerArtifactRegistry

    owner = str(uuid4())
    store = PostgresTenantStore(beta_env)
    limits = TenantLimits(daily_upload_limit=5, daily_upload_bytes_limit=5000, daily_preview_limit=5, daily_build_limit=5, active_job_limit=5)
    deleted: list[str] = []

    class RecordingDeleteStore(FakeObjectStore):
        def delete_object(self, object_key: str) -> None:
            deleted.append(object_key)

    try:
        source_key = f"tenants/{owner}/jobs/source/input/original.png"
        store.register_upload(owner_id=owner, bucket="unit-bucket", object_key=source_key, content_type="image/png", size_bytes=100, limits=limits)
        store.mark_uploaded(owner_id=owner, bucket="unit-bucket", object_key=source_key, size_bytes=100)
        queued = store.create_job(owner_id=owner, input_photo=InputPhoto(source_key, "image/png", 100, bucket="unit-bucket"), font=FontRequest("TombstoneFont", "Tombstone Font"), capture=None, bucket="unit-bucket", limits=limits)
        claimed = PostgresJobStore(beta_env).claim(queued.id)
        assert claimed is not None
        artifact_key = f"jobs/{claimed.id}/attempts/{claimed.attempt_id}/artifacts/a.ttf"
        WorkerArtifactRegistry(claimed).register_attempt_artifact(object_key=artifact_key, content_type="font/ttf", size_bytes=3, kind="ttf")

        store.delete_job(owner_id=owner, job_id=claimed.id, object_store=RecordingDeleteStore())
        assert artifact_key in deleted
        import psycopg

        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("select status from tenant_objects where bucket='unit-bucket' and object_key=%s", (artifact_key,))
            assert cur.fetchone()[0] == "delete_pending"

        deleted.clear()
        store.cleanup_expired(object_store=RecordingDeleteStore())
        assert artifact_key in deleted
        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("select status from tenant_objects where bucket='unit-bucket' and object_key=%s", (artifact_key,))
            assert cur.fetchone()[0] == "delete_pending"
            cur.execute("update tenant_objects set delete_not_before=now()-interval '1 second' where bucket='unit-bucket' and object_key=%s", (artifact_key,))

        deleted.clear()
        store.cleanup_expired(object_store=RecordingDeleteStore())
        assert artifact_key in deleted
        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("select status from tenant_objects where bucket='unit-bucket' and object_key=%s", (artifact_key,))
            assert cur.fetchone()[0] == "deleted"
    finally:
        _cleanup_owner(beta_env, owner)


def test_proxy_put_rejects_actual_size_mismatch(monkeypatch, tmp_path, beta_env):
    owner_id = str(uuid4())
    data = _png_bytes()
    monkeypatch.setattr(security, "_fetch_supabase_user", lambda *_: {"id": owner_id, "app_metadata": {"handwrite_beta": True}})
    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", lambda _root: FakeObjectStore())
    server, base = _start_server(tmp_path)
    try:
        status, upload = _post_json(base + "/uploads", {"filename": "x.png", "contentType": "image/png", "sizeBytes": len(data) + 1}, _auth("token"))
        assert status == 200
        status, payload = _put_bytes(base + upload["uploadUrl"], data, _auth("token"))
        assert status == 400
        assert payload["error"]["code"] == "UPLOAD_OBJECT_MISSING"
    finally:
        server.shutdown()
        _cleanup_owner(beta_env, owner_id)


def test_cleanup_once_nonzero_on_delete_failures(monkeypatch):
    from handwrite_font_maker.web import cleanup

    monkeypatch.setattr(cleanup, "cleanup_expired_from_env", lambda **_: {"deletedObjects": 0, "failedObjects": 1})
    assert cleanup.main(["--once"]) == 1
