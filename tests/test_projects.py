from __future__ import annotations

import json
import os
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

from handwrite_font_maker.web import security
from handwrite_font_maker.web.contracts import FontRequest, InputPhoto
from handwrite_font_maker.web.project_store import JsonProjectStore, PostgresProjectStore, ProjectConflict, ProjectLimitExceeded, ProjectStoreError, validate_project_payload
from handwrite_font_maker.web.server import Handler
from handwrite_font_maker.web.tenant_store import PostgresTenantStore, TenantLimits

PG_URL = os.environ.get("TEST_DATABASE_URL")


def _pg_available() -> bool:
    if not PG_URL:
        return False
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
    return migrated_pg


def _cleanup_owner(database_url: str, owner_id: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("delete from tenant_project_object_refs where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from projects where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from tenant_object_job_refs where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from tenant_objects where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from tenant_daily_usage where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from jobs where owner_id=%s::uuid", (owner_id,))
        cur.execute("delete from tenants where owner_id=%s::uuid", (owner_id,))


def _payload(mask_key: str, *, size: int = 123, last_job_id: str | None = None, sheet_key: str | None = None, name: str = "My Project") -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "font": {"fontName": "ProjectFont", "familyName": "Project Font", "styleName": "Regular"},
        "mode": "guided",
        "targetCharacters": "ABCDE",
        "glyphs": [
            {
                "char": "A",
                "inputPhoto": {"objectKey": mask_key, "contentType": "image/png", "sizeBytes": size},
                "baseline": 0.7,
                "scale": 1.1,
                "spacing": 0.05,
                "width": 64,
                "height": 64,
                "foregroundRatio": 0.3,
                "filename": "A.png",
            }
        ],
        "lastJobId": last_job_id,
    }
    if sheet_key:
        payload["sheet"] = {"inputPhoto": {"objectKey": sheet_key, "contentType": "image/png", "sizeBytes": size}, "cornersConfirmed": False}
    return payload


def _register_uploaded(store: PostgresTenantStore, owner: str, key: str, *, size: int = 123) -> None:
    limits = TenantLimits(daily_upload_limit=50, daily_upload_bytes_limit=500000, daily_preview_limit=50, daily_build_limit=50, active_job_limit=50)
    store.register_upload(owner_id=owner, bucket="unit-bucket", object_key=key, content_type="image/png", size_bytes=size, limits=limits)
    store.mark_uploaded(owner_id=owner, bucket="unit-bucket", object_key=key, size_bytes=size)


class RecordingObjectStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_object(self, object_key: str) -> None:
        self.deleted.append(object_key)


def test_project_payload_validation_defaults_and_rejects_blobs() -> None:
    key = "jobs/local/input/A.png"
    project = validate_project_payload(_payload(key))
    assert project.target_characters == "ABCDE"
    assert project.glyphs[0]["scale"] == 1.1
    assert project.glyphs[0]["spacing"] == 0.05
    no_targets = _payload(key)
    no_targets.pop("targetCharacters")
    assert validate_project_payload(no_targets).target_characters == "ABCDE"
    invalid = _payload(key)
    invalid["maskDataUrl"] = "data:image/png;base64,abc"
    with pytest.raises(ProjectStoreError):
        validate_project_payload(invalid)
    bad_scale = _payload(key)
    bad_scale["glyphs"][0]["scale"] = 2.0  # type: ignore[index]
    with pytest.raises(ProjectStoreError):
        validate_project_payload(bad_scale)
    guided_sheet = _payload(key, sheet_key="jobs/local/sheet.png")
    with pytest.raises(ProjectStoreError):
        validate_project_payload(guided_sheet)
    template_with_glyph = _payload(key)
    template_with_glyph["mode"] = "markerless"
    with pytest.raises(ProjectStoreError):
        validate_project_payload(template_with_glyph)
    empty_template = {**template_with_glyph, "glyphs": [], "sheet": None}
    assert validate_project_payload(empty_template).mode == "markerless"
    unconfirmed_sheet = {**empty_template, "sheet": {"inputPhoto": {"objectKey": key, "contentType": "image/png", "sizeBytes": 123}, "cornersConfirmed": False}}
    assert validate_project_payload(unconfirmed_sheet).sheet is not None
    confirmed_without_corners = {**empty_template, "sheet": {"inputPhoto": {"objectKey": key, "contentType": "image/png", "sizeBytes": 123}, "cornersConfirmed": True}}
    with pytest.raises(ProjectStoreError):
        validate_project_payload(confirmed_without_corners)


def test_local_project_store_create_update_conflict_delete(tmp_path) -> None:
    object_root = tmp_path / "objects"
    object_key = "jobs/local/input/A.png"
    target = object_root / object_key
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * 123)
    store = JsonProjectStore(tmp_path / "projects.json", object_root=object_root)
    with pytest.raises(Exception):
        store.create(owner_id="local_dev", payload=_payload(object_key, last_job_id="job_missing"))
    job_store_path = tmp_path / "jobs.json"
    job_store_path.write_text(json.dumps({"job_local": {"owner_id": "local_dev"}}), encoding="utf-8")
    store = JsonProjectStore(tmp_path / "projects.json", object_root=object_root, job_store_path=job_store_path)
    local_with_job = store.create(owner_id="local_dev", payload=_payload(object_key, last_job_id="job_local"))
    assert local_with_job["lastJobId"] == "job_local"
    project = store.create(owner_id="local_dev", payload=_payload(object_key))
    assert project["revision"] == 1
    assert project["id"] in {item["id"] for item in store.list(owner_id="local_dev")}
    update = _payload(object_key, name="Renamed")
    update["revision"] = project["revision"]
    updated = store.update(owner_id="local_dev", project_id=str(project["id"]), payload=update)
    assert updated["name"] == "Renamed"
    assert updated["revision"] == 2
    with pytest.raises(ProjectConflict):
        store.update(owner_id="local_dev", project_id=str(project["id"]), payload=update)
    assert store.delete(owner_id="local_dev", project_id=str(project["id"])) == {"deletedObjects": 0, "failedObjects": 0}
    remaining = store.list(owner_id="local_dev")
    assert [item["id"] for item in remaining] == [local_with_job["id"]]
    assert store.delete(owner_id="local_dev", project_id=str(local_with_job["id"])) == {"deletedObjects": 0, "failedObjects": 0}
    assert store.list(owner_id="local_dev") == []


def test_pg_projects_are_owner_scoped_revisioned_and_limited(beta_env) -> None:
    owner_a = str(uuid4())
    owner_b = str(uuid4())
    mask_key = f"tenants/{owner_a}/projects/masks/A.png"
    store = PostgresTenantStore(beta_env)
    project_store = PostgresProjectStore(beta_env, bucket="unit-bucket")
    try:
        _register_uploaded(store, owner_a, mask_key)
        project = project_store.create(owner_id=owner_a, payload=_payload(mask_key))
        assert project["revision"] == 1
        assert project_store.get(owner_id=owner_a, project_id=str(project["id"]))["id"] == project["id"]
        with pytest.raises(Exception):
            project_store.get(owner_id=owner_b, project_id=str(project["id"]))
        stale = _payload(mask_key, name="Stale")
        stale["revision"] = project["revision"]
        updated = project_store.update(owner_id=owner_a, project_id=str(project["id"]), payload=stale)
        assert updated["revision"] == 2
        with pytest.raises(ProjectConflict):
            project_store.update(owner_id=owner_a, project_id=str(project["id"]), payload=stale)
        mismatch = _payload(mask_key, size=999)
        with pytest.raises(Exception):
            project_store.create(owner_id=owner_a, payload=mismatch)
        for idx in range(9):
            key = f"tenants/{owner_a}/projects/masks/{idx}.png"
            _register_uploaded(store, owner_a, key)
            project_store.create(owner_id=owner_a, payload=_payload(key, name=f"P{idx}"))
        extra_key = f"tenants/{owner_a}/projects/masks/extra.png"
        _register_uploaded(store, owner_a, extra_key)
        with pytest.raises(ProjectLimitExceeded):
            project_store.create(owner_id=owner_a, payload=_payload(extra_key, name="Too Many"))
    finally:
        _cleanup_owner(beta_env, owner_a)
        _cleanup_owner(beta_env, owner_b)


def test_pg_project_last_job_id_is_historical_owner_pointer(beta_env) -> None:
    owner = str(uuid4())
    foreign = str(uuid4())
    store = PostgresTenantStore(beta_env)
    project_store = PostgresProjectStore(beta_env, bucket="unit-bucket")
    mask_key = f"tenants/{owner}/projects/masks/A.png"
    try:
        _register_uploaded(store, owner, mask_key)
        job = store.create_job(
            owner_id=owner,
            input_photo=InputPhoto(mask_key, "image/png", 123, bucket="unit-bucket"),
            font=FontRequest("HistoricalFont", "Historical Font"),
            capture=None,
            bucket="unit-bucket",
            limits=TenantLimits(daily_upload_limit=50, daily_upload_bytes_limit=500000, daily_preview_limit=50, daily_build_limit=50, active_job_limit=50),
        )
        import psycopg

        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("update jobs set status='expired', delete_requested_at=now(), retention_expires_at=now()-interval '1 second' where id=%s", (job.id,))
        project = project_store.create(owner_id=owner, payload=_payload(mask_key, last_job_id=job.id))
        update = _payload(mask_key, last_job_id=job.id, name="Still Editable")
        update["revision"] = project["revision"]
        updated = project_store.update(owner_id=owner, project_id=str(project["id"]), payload=update)
        assert updated["lastJobId"] == job.id
        with pytest.raises(Exception):
            project_store.create(owner_id=owner, payload=_payload(mask_key, last_job_id="job_missing"))
        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("insert into tenants (owner_id) values (%s::uuid) on conflict do nothing", (foreign,))
            cur.execute(
                """
                insert into jobs (id, status, stage, font_name, family_name, style_name, input_bucket, input_path, input_content_type, input_size_bytes, retention_expires_at, owner_id)
                values ('job_foreign','expired','queued','F','F','Regular','unit-bucket',%s,'image/png',123,now()-interval '1 second',%s::uuid)
                on conflict (id) do update set owner_id=excluded.owner_id
                """,
                (mask_key, foreign),
            )
        with pytest.raises(Exception):
            project_store.create(owner_id=owner, payload=_payload(mask_key, last_job_id="job_foreign"))
    finally:
        _cleanup_owner(beta_env, owner)
        _cleanup_owner(beta_env, foreign)


def test_pg_project_refs_protect_cleanup_and_delete_no_harm_shared(beta_env) -> None:
    owner = str(uuid4())
    store = PostgresTenantStore(beta_env)
    project_store = PostgresProjectStore(beta_env, bucket="unit-bucket")
    mask_key = f"tenants/{owner}/projects/masks/A.png"
    other_key = f"tenants/{owner}/projects/masks/B.png"
    deleter = RecordingObjectStore()
    try:
        _register_uploaded(store, owner, mask_key)
        _register_uploaded(store, owner, other_key)
        first = project_store.create(owner_id=owner, payload=_payload(mask_key, name="One"))
        second = project_store.create(owner_id=owner, payload=_payload(mask_key, name="Two"))
        import psycopg

        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("update tenant_objects set retention_expires_at=now()-interval '1 second' where owner_id=%s::uuid and object_key=%s", (owner, mask_key))
        assert store.cleanup_expired(object_store=deleter)["deletedObjects"] == 0
        assert mask_key not in deleter.deleted
        assert project_store.delete(owner_id=owner, project_id=str(first["id"]), object_store=deleter) == {"deletedObjects": 0, "failedObjects": 0}
        assert mask_key not in deleter.deleted
        result = project_store.delete(owner_id=owner, project_id=str(second["id"]), object_store=deleter)
        assert result["deletedObjects"] == 1
        assert mask_key in deleter.deleted
    finally:
        _cleanup_owner(beta_env, owner)


def _start_server(tmp_path: Path):
    Handler.store_path = tmp_path / "jobs.json"
    Handler.project_store_path = tmp_path / "projects.json"
    Handler.object_root = tmp_path / "objects"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _auth(token: str = "token") -> dict[str, str]:
    return {"x-internal-api-key": "i" * 40, "authorization": f"Bearer {token}"}


def _request_json(url: str, method: str, payload: object | None = None, headers: dict[str, str] | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"content-type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_cleanup_purges_expired_project_metadata_refs_and_masks(beta_env) -> None:
    owner = str(uuid4())
    store = PostgresTenantStore(beta_env)
    project_store = PostgresProjectStore(beta_env, bucket="unit-bucket")
    mask_key = f"tenants/{owner}/projects/masks/expired.png"
    deleter = RecordingObjectStore()
    try:
        _register_uploaded(store, owner, mask_key)
        project = project_store.create(owner_id=owner, payload=_payload(mask_key, name="Expired"))
        import psycopg

        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("update projects set retention_expires_at=now()-interval '1 second' where id=%s", (project["id"],))
            cur.execute("update tenant_objects set retention_expires_at=now()-interval '1 second' where owner_id=%s::uuid and object_key=%s", (owner, mask_key))
        result = store.cleanup_expired(object_store=deleter)
        assert result["deletedObjects"] == 1
        assert mask_key in deleter.deleted
        with psycopg.connect(beta_env) as conn, conn.cursor() as cur:
            cur.execute("select 1 from projects where id=%s", (project["id"],))
            assert cur.fetchone() is None
            cur.execute("select 1 from tenant_project_object_refs where project_id=%s", (project["id"],))
            assert cur.fetchone() is None
    finally:
        _cleanup_owner(beta_env, owner)


def test_http_project_routes_require_auth_and_enforce_revision(monkeypatch, tmp_path, beta_env) -> None:
    owner = str(uuid4())
    mask_key = f"tenants/{owner}/projects/masks/A.png"
    store = PostgresTenantStore(beta_env)
    try:
        _register_uploaded(store, owner, mask_key)
        monkeypatch.setattr(security, "_fetch_supabase_user", lambda *_: {"id": owner, "app_metadata": {"handwrite_beta": True}})
        server, base = _start_server(tmp_path)
        try:
            status, _ = _request_json(base + "/projects", "GET")
            assert status == 401
            status, created = _request_json(base + "/projects", "POST", _payload(mask_key), _auth())
            assert status == 201
            status, listed = _request_json(base + "/projects", "GET", headers=_auth())
            assert status == 200
            assert [project["id"] for project in listed["projects"]] == [created["id"]]
            update = _payload(mask_key, name="HTTP Renamed")
            update["revision"] = created["revision"]
            status, updated = _request_json(base + f"/projects/{created['id']}", "PUT", update, _auth())
            assert status == 200
            assert updated["revision"] == 2
            status, conflict = _request_json(base + f"/projects/{created['id']}", "PUT", update, _auth())
            assert status == 409
            assert conflict["error"]["code"] == "PROJECT_REVISION_CONFLICT"
            status, deleted = _request_json(base + f"/projects/{created['id']}", "DELETE", headers=_auth())
            assert status == 200
            assert deleted["ok"] is True
            assert "deletedObjects" in deleted and "failedObjects" in deleted
            status, _ = _request_json(base + f"/projects/{created['id']}", "GET", headers=_auth())
            assert status == 404
        finally:
            server.shutdown()
    finally:
        _cleanup_owner(beta_env, owner)


def test_http_project_put_authenticates_before_reading_body(monkeypatch, tmp_path, beta_env) -> None:
    owner = str(uuid4())
    monkeypatch.setattr(security, "_fetch_supabase_user", lambda *_: {"id": owner, "app_metadata": {"handwrite_beta": True}})
    server, base = _start_server(tmp_path)
    try:
        host = "127.0.0.1"
        port = int(base.rsplit(":", 1)[1])
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(
                b"PUT /projects/proj_missing HTTP/1.1\r\n"
                + f"Host: {host}:{port}\r\n".encode("ascii")
                + b"Content-Type: application/json\r\n"
                + b"Content-Length: 16777216\r\n"
                + b"Connection: close\r\n\r\n"
            )
            response = sock.recv(4096).decode("utf-8", errors="replace")
        assert response.startswith("HTTP/1.0 401") or response.startswith("HTTP/1.1 401")
        assert "UNAUTHORIZED" in response
    finally:
        server.shutdown()
        _cleanup_owner(beta_env, owner)
