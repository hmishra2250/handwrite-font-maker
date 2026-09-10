from __future__ import annotations

import json
import math
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .contracts import FontRequest, HardErrorCode, InputPhoto, MAX_UPLOAD_BYTES, input_photo_to_json, is_safe_font_name, parse_input_photo, validate_normalized_corners
from .tenant_store import DeletableObjectStore, ObjectAccessError, OwnershipError, PostgresTenantStore, QuotaExceeded

PROJECT_RETENTION_DAYS = 7
MAX_LIVE_PROJECTS = 10
DEFAULT_TARGET_CHARACTERS = "ABCDE"
PROJECT_MODES = {"guided", "markerless", "legacy"}


class ProjectStoreError(RuntimeError):
    status = 400
    code = "PROJECT_INVALID"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class ProjectNotFound(ProjectStoreError):
    status = 404
    code = "PROJECT_NOT_FOUND"


class ProjectConflict(ProjectStoreError):
    status = 409
    code = "PROJECT_REVISION_CONFLICT"


class ProjectLimitExceeded(ProjectStoreError):
    status = 429
    code = "PROJECT_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class ProjectData:
    name: str
    font: dict[str, object]
    mode: str
    target_characters: str
    glyphs: list[dict[str, object]]
    sheet: dict[str, object] | None
    last_job_id: str | None
    object_refs: tuple[InputPhoto, ...]

    def payload(self) -> dict[str, object]:
        data: dict[str, object] = {
            "name": self.name,
            "font": self.font,
            "mode": self.mode,
            "targetCharacters": self.target_characters,
            "glyphs": self.glyphs,
            "lastJobId": self.last_job_id,
        }
        if self.sheet is not None:
            data["sheet"] = self.sheet
        else:
            data["sheet"] = None
        return data


class ProjectStore(Protocol):
    def list(self, *, owner_id: str) -> list[dict[str, object]]: ...
    def get(self, *, owner_id: str, project_id: str) -> dict[str, object]: ...
    def create(self, *, owner_id: str, payload: dict[str, object]) -> dict[str, object]: ...
    def update(self, *, owner_id: str, project_id: str, payload: dict[str, object]) -> dict[str, object]: ...
    def delete(self, *, owner_id: str, project_id: str, object_store: DeletableObjectStore | None = None) -> dict[str, object]: ...


def project_retention_expires_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=PROJECT_RETENTION_DAYS)).isoformat().replace("+00:00", "Z")


def new_project_id() -> str:
    return f"proj_{uuid4()}"


def validate_project_payload(payload: dict[str, object]) -> ProjectData:
    if not isinstance(payload, dict):
        raise ProjectStoreError("Project payload must be an object.")
    _reject_embedded_blob(payload)
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise ProjectStoreError("Project name is required.")
    font = _validate_font(payload.get("font"))
    mode = payload.get("mode")
    if not isinstance(mode, str) or mode not in PROJECT_MODES:
        raise ProjectStoreError("Project mode must be guided, markerless, or legacy.")
    target_characters = _validate_target_characters(payload.get("targetCharacters", DEFAULT_TARGET_CHARACTERS))
    raw_glyphs = payload.get("glyphs")
    if not isinstance(raw_glyphs, list) or len(raw_glyphs) > 94:
        raise ProjectStoreError("glyphs must be an array of at most 94 glyphs.")
    glyphs: list[dict[str, object]] = []
    object_refs: list[InputPhoto] = []
    seen_glyphs: set[str] = set()
    total_glyph_bytes = 0
    for raw in raw_glyphs:
        glyph, photo = _validate_project_glyph(raw)
        char = str(glyph["char"])
        if char in seen_glyphs:
            raise ProjectStoreError("Project glyph chars must be unique.")
        seen_glyphs.add(char)
        total_glyph_bytes += photo.size_bytes
        if total_glyph_bytes > MAX_UPLOAD_BYTES:
            raise ProjectStoreError(HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value)
        glyphs.append(glyph)
        object_refs.append(photo)
    sheet = _validate_sheet(payload.get("sheet")) if "sheet" in payload else None
    if mode == "guided" and sheet is not None:
        raise ProjectStoreError("Guided projects must not include a sheet.")
    if mode in {"markerless", "legacy"} and glyphs:
        raise ProjectStoreError("Template projects must not include editable glyph masks.")
    if sheet is not None:
        object_refs.append(parse_input_photo(sheet["inputPhoto"]))
    last_job_id_raw = payload.get("lastJobId")
    if last_job_id_raw is None:
        last_job_id = None
    elif isinstance(last_job_id_raw, str) and last_job_id_raw.startswith("job_") and len(last_job_id_raw) < 80:
        last_job_id = last_job_id_raw
    else:
        raise ProjectStoreError("lastJobId must be null or a job id.")
    return ProjectData(
        name=name.strip(),
        font=font,
        mode=mode,
        target_characters=target_characters,
        glyphs=glyphs,
        sheet=sheet,
        last_job_id=last_job_id,
        object_refs=tuple(_unique_photos(object_refs)),
    )


def _validate_font(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProjectStoreError("font is required.")
    font_name = raw.get("fontName")
    if not isinstance(font_name, str) or not is_safe_font_name(font_name):
        raise ProjectStoreError(HardErrorCode.FONT_METADATA_INVALID.value)
    family_name = raw.get("familyName")
    style_name = raw.get("styleName", "Regular")
    if not isinstance(family_name, str) or not family_name.strip() or len(family_name) > 120:
        raise ProjectStoreError(HardErrorCode.FONT_METADATA_INVALID.value)
    if not isinstance(style_name, str) or not style_name.strip() or len(style_name) > 80:
        raise ProjectStoreError(HardErrorCode.FONT_METADATA_INVALID.value)
    _ = FontRequest(font_name=font_name, family_name=family_name, style_name=style_name)
    return {"fontName": font_name, "familyName": family_name, "styleName": style_name}


def _validate_target_characters(raw: object) -> str:
    if isinstance(raw, list):
        chars = "".join(item for item in raw if isinstance(item, str))
        if len(chars) != len(raw):
            raise ProjectStoreError("targetCharacters must be a string of printable ASCII characters.")
    elif isinstance(raw, str):
        chars = raw
    else:
        raise ProjectStoreError("targetCharacters must be a string of printable ASCII characters.")
    if not 1 <= len(chars) <= 94 or len(set(chars)) != len(chars) or any(not (33 <= ord(char) <= 126) for char in chars):
        raise ProjectStoreError("targetCharacters must be 1-94 unique printable non-space ASCII characters.")
    return chars


def _validate_project_glyph(raw: object) -> tuple[dict[str, object], InputPhoto]:
    if not isinstance(raw, dict):
        raise ProjectStoreError("Each glyph must be an object.")
    char = raw.get("char")
    if not isinstance(char, str) or len(char) != 1 or not (33 <= ord(char) <= 126):
        raise ProjectStoreError("Glyph char must be one printable non-space ASCII character.")
    baseline = _finite_float(raw.get("baseline"), "baseline")
    if not 0.0 < baseline < 1.0:
        raise ProjectStoreError("Glyph baseline must be between 0 and 1.")
    scale = _finite_float(raw.get("scale", 1.0), "scale")
    if not 0.5 <= scale <= 1.5:
        raise ProjectStoreError("Glyph scale must be between 0.5 and 1.5.")
    spacing = _finite_float(raw.get("spacing", 0.0), "spacing")
    if not -0.05 <= spacing <= 0.25:
        raise ProjectStoreError("Glyph spacing must be between -0.05 and 0.25 em.")
    width = _positive_int(raw.get("width"), "width", max_value=4096)
    height = _positive_int(raw.get("height"), "height", max_value=4096)
    foreground_ratio = _finite_float(raw.get("foregroundRatio"), "foregroundRatio")
    if not 0.0 < foreground_ratio < 1.0:
        raise ProjectStoreError("foregroundRatio must be between 0 and 1.")
    filename = raw.get("filename")
    if not isinstance(filename, str) or not filename or len(filename) > 180 or "/" in filename or "\\" in filename or "\x00" in filename:
        raise ProjectStoreError("Glyph filename is invalid.")
    photo = parse_input_photo(raw.get("inputPhoto"), require_png=True)
    return (
        {
            "char": char,
            "inputPhoto": input_photo_to_json(photo),
            "baseline": baseline,
            "scale": scale,
            "spacing": spacing,
            "width": width,
            "height": height,
            "foregroundRatio": foreground_ratio,
            "filename": filename,
        },
        photo,
    )


def _validate_sheet(raw: object) -> dict[str, object] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProjectStoreError("sheet must be an object or null.")
    photo = parse_input_photo(raw.get("inputPhoto"))
    sheet: dict[str, object] = {"inputPhoto": input_photo_to_json(photo)}
    if raw.get("corners") is not None:
        sheet["corners"] = [[x, y] for x, y in validate_normalized_corners(raw.get("corners"))]
    if raw.get("cornersConfirmed") is not None:
        if not isinstance(raw.get("cornersConfirmed"), bool):
            raise ProjectStoreError("cornersConfirmed must be boolean.")
        if raw.get("cornersConfirmed") is True and "corners" not in sheet:
            raise ProjectStoreError("Confirmed sheet corners require valid corners.")
        sheet["cornersConfirmed"] = raw.get("cornersConfirmed")
    return sheet


def _finite_float(raw: object, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ProjectStoreError(f"{field} must be a finite number.")
    value = float(raw)
    if not math.isfinite(value):
        raise ProjectStoreError(f"{field} must be a finite number.")
    return value


def _positive_int(raw: object, field: str, *, max_value: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0 or raw > max_value:
        raise ProjectStoreError(f"{field} must be a positive integer.")
    return raw


def _reject_embedded_blob(value: object) -> None:
    if isinstance(value, str):
        if value.startswith("data:") or len(value) > 4096:
            raise ProjectStoreError("Project JSON must not contain blobs or base64 data.")
    elif isinstance(value, list):
        for item in value:
            _reject_embedded_blob(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in {"blob", "base64", "maskdataurl", "dataurl"}:
                raise ProjectStoreError("Project JSON must not contain blobs or base64 data.")
            _reject_embedded_blob(item)


def _unique_photos(photos: list[InputPhoto]) -> list[InputPhoto]:
    seen: set[tuple[str | None, str]] = set()
    result: list[InputPhoto] = []
    for photo in photos:
        key = (photo.bucket, photo.object_key)
        if key in seen:
            continue
        seen.add(key)
        result.append(photo)
    return result


def _dt_to_iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


class JsonProjectStore:
    def __init__(self, path: Path, *, object_root: Path, job_store_path: Path | None = None) -> None:
        self.path = path
        self.object_root = object_root
        self.job_store_path = job_store_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._atomic_write({})

    @contextmanager
    def _locked(self):
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except ImportError:
                fcntl = None  # type: ignore[assignment]
            try:
                yield
            finally:
                if "fcntl" in locals() and fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, dict[str, object]]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _atomic_write(self, data: dict[str, dict[str, object]]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def list(self, *, owner_id: str) -> list[dict[str, object]]:
        with self._locked():
            data = self._read()
            self._expire_old_data(data)
            return [_public_project(row) for row in data.values() if row.get("ownerId") == owner_id and not row.get("deletedAt") and _future(row.get("retentionExpiresAt"))]

    def get(self, *, owner_id: str, project_id: str) -> dict[str, object]:
        with self._locked():
            data = self._read()
            self._expire_old_data(data)
            row = data.get(project_id)
            if not row or row.get("ownerId") != owner_id or row.get("deletedAt") or not _future(row.get("retentionExpiresAt")):
                raise ProjectNotFound("Project not found.")
            return _public_project(row)

    def create(self, *, owner_id: str, payload: dict[str, object]) -> dict[str, object]:
        project = validate_project_payload(payload)
        self._validate_local_refs(project)
        with self._locked():
            data = self._read()
            self._expire_old_data(data)
            live_count = sum(1 for row in data.values() if row.get("ownerId") == owner_id and not row.get("deletedAt") and _future(row.get("retentionExpiresAt")))
            if live_count >= MAX_LIVE_PROJECTS:
                raise ProjectLimitExceeded("Live project limit exceeded.")
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            row = {**project.payload(), "id": new_project_id(), "ownerId": owner_id, "revision": 1, "createdAt": now, "updatedAt": now, "retentionExpiresAt": project_retention_expires_at(), "deletedAt": None}
            data[str(row["id"])] = row
            self._atomic_write(data)
            return _public_project(row)

    def update(self, *, owner_id: str, project_id: str, payload: dict[str, object]) -> dict[str, object]:
        expected = payload.get("revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0:
            raise ProjectStoreError("revision is required.")
        project = validate_project_payload(payload)
        self._validate_local_refs(project)
        with self._locked():
            data = self._read()
            self._expire_old_data(data)
            row = data.get(project_id)
            if not row or row.get("ownerId") != owner_id or row.get("deletedAt") or not _future(row.get("retentionExpiresAt")):
                raise ProjectNotFound("Project not found.")
            if int(row.get("revision") or 0) != expected:
                raise ProjectConflict("Project revision conflict.")
            row.update(project.payload())
            row["revision"] = expected + 1
            row["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            row["retentionExpiresAt"] = project_retention_expires_at()
            data[project_id] = row
            self._atomic_write(data)
            return _public_project(row)

    def delete(self, *, owner_id: str, project_id: str, object_store: DeletableObjectStore | None = None) -> dict[str, object]:
        with self._locked():
            data = self._read()
            row = data.get(project_id)
            if not row or row.get("ownerId") != owner_id or row.get("deletedAt"):
                raise ProjectNotFound("Project not found.")
            row["deletedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            row["retentionExpiresAt"] = row["deletedAt"]
            self._atomic_write(data)
            return {"deletedObjects": 0, "failedObjects": 0}

    def _expire_old_data(self, data: dict[str, dict[str, object]]) -> None:
        changed = False
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for row in data.values():
            if not row.get("deletedAt") and not _future(row.get("retentionExpiresAt")):
                row["deletedAt"] = now
                changed = True
        if changed:
            self._atomic_write(data)

    def _validate_local_refs(self, project: ProjectData) -> None:
        for photo in project.object_refs:
            path = self.object_root / photo.object_key
            if not path.exists() or path.stat().st_size != photo.size_bytes:
                raise ObjectAccessError("Project object is missing or has unexpected size.")
        if project.last_job_id:
            if not self.job_store_path or not self.job_store_path.exists():
                raise ProjectNotFound("lastJobId is not owned by this user.")
            try:
                jobs = json.loads(self.job_store_path.read_text(encoding="utf-8"))
            except Exception:
                jobs = {}
            row = jobs.get(project.last_job_id) if isinstance(jobs, dict) else None
            if not isinstance(row, dict):
                raise ProjectNotFound("lastJobId is not owned by this user.")
            row_owner = row.get("owner_id")
            if row_owner not in {None, "local_dev"}:
                raise ProjectNotFound("lastJobId is not owned by this user.")


class PostgresProjectStore:
    def __init__(self, database_url: str | None = None, *, bucket: str | None = None) -> None:
        import psycopg

        self.database_url = database_url or os.environ.get("DATABASE_URL") or ""
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for project storage.")
        self.bucket = bucket or os.environ.get("SUPABASE_STORAGE_BUCKET") or "handwrite-font-jobs"
        self._psycopg = psycopg
        self._tenant_store = PostgresTenantStore(self.database_url)

    def _connect(self):
        return self._psycopg.connect(self.database_url, connect_timeout=5, options="-c statement_timeout=10000 -c lock_timeout=5000")

    def list(self, *, owner_id: str) -> list[dict[str, object]]:
        self._expire_projects(owner_id=owner_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select * from projects where owner_id=%s::uuid and deleted_at is null and retention_expires_at>now()
                order by updated_at desc, id desc
                """,
                (owner_id,),
            )
            rows = cur.fetchall()
            cols = [desc.name for desc in cur.description]
        return [_project_from_pg(dict(zip(cols, row, strict=True))) for row in rows]

    def get(self, *, owner_id: str, project_id: str) -> dict[str, object]:
        self._expire_projects(owner_id=owner_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select * from projects where id=%s and owner_id=%s::uuid and deleted_at is null and retention_expires_at>now()", (project_id, owner_id))
            row = cur.fetchone()
            if row is None:
                raise ProjectNotFound("Project not found.")
            cols = [desc.name for desc in cur.description]
        return _project_from_pg(dict(zip(cols, row, strict=True)))

    def create(self, *, owner_id: str, payload: dict[str, object]) -> dict[str, object]:
        project = validate_project_payload(payload)
        retention = project_retention_expires_at()
        project_id = new_project_id()
        with self._connect() as conn, conn.cursor() as cur:
            self._tenant_store._ensure_and_lock_tenant(cur, owner_id)
            self._expire_projects_cur(cur, owner_id=owner_id)
            cur.execute("select count(*) from projects where owner_id=%s::uuid and deleted_at is null and retention_expires_at>now()", (owner_id,))
            if int(cur.fetchone()[0]) >= MAX_LIVE_PROJECTS:
                raise ProjectLimitExceeded("Live project limit exceeded.")
            self._validate_pg_refs(cur, owner_id=owner_id, project=project)
            cur.execute(
                """
                insert into projects (id, owner_id, name, font, mode, target_characters, glyphs, sheet, last_job_id, revision, retention_expires_at)
                values (%s,%s::uuid,%s,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s,1,%s::timestamptz)
                returning *
                """,
                (project_id, owner_id, project.name, json.dumps(project.font), project.mode, project.target_characters, json.dumps(project.glyphs), json.dumps(project.sheet) if project.sheet is not None else None, project.last_job_id, retention),
            )
            row = cur.fetchone()
            cols = [desc.name for desc in cur.description]
            self._replace_project_refs(cur, owner_id=owner_id, project_id=project_id, refs=project.object_refs, retention=retention)
        return _project_from_pg(dict(zip(cols, row, strict=True)))

    def update(self, *, owner_id: str, project_id: str, payload: dict[str, object]) -> dict[str, object]:
        expected = payload.get("revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0:
            raise ProjectStoreError("revision is required.")
        project = validate_project_payload(payload)
        retention = project_retention_expires_at()
        with self._connect() as conn, conn.cursor() as cur:
            self._tenant_store._ensure_and_lock_tenant(cur, owner_id)
            self._expire_projects_cur(cur, owner_id=owner_id)
            cur.execute("select revision from projects where id=%s and owner_id=%s::uuid and deleted_at is null and retention_expires_at>now() for update", (project_id, owner_id))
            row = cur.fetchone()
            if row is None:
                raise ProjectNotFound("Project not found.")
            if int(row[0]) != expected:
                raise ProjectConflict("Project revision conflict.")
            self._validate_pg_refs(cur, owner_id=owner_id, project=project)
            cur.execute(
                """
                update projects set name=%s, font=%s::jsonb, mode=%s, target_characters=%s, glyphs=%s::jsonb,
                  sheet=%s::jsonb, last_job_id=%s, revision=revision+1, retention_expires_at=%s::timestamptz, updated_at=now()
                where id=%s and owner_id=%s::uuid returning *
                """,
                (project.name, json.dumps(project.font), project.mode, project.target_characters, json.dumps(project.glyphs), json.dumps(project.sheet) if project.sheet is not None else None, project.last_job_id, retention, project_id, owner_id),
            )
            row = cur.fetchone()
            cols = [desc.name for desc in cur.description]
            self._replace_project_refs(cur, owner_id=owner_id, project_id=project_id, refs=project.object_refs, retention=retention)
        return _project_from_pg(dict(zip(cols, row, strict=True)))

    def delete(self, *, owner_id: str, project_id: str, object_store: DeletableObjectStore | None = None) -> dict[str, object]:
        object_rows: list[tuple[str, str]] = []
        with self._connect() as conn, conn.cursor() as cur:
            self._tenant_store._ensure_and_lock_tenant(cur, owner_id)
            cur.execute("select id from projects where id=%s and owner_id=%s::uuid and deleted_at is null for update", (project_id, owner_id))
            if cur.fetchone() is None:
                raise ProjectNotFound("Project not found.")
            cur.execute("update projects set deleted_at=now(), retention_expires_at=least(retention_expires_at, now()), updated_at=now() where id=%s and owner_id=%s::uuid", (project_id, owner_id))
            cur.execute("select bucket, object_key from tenant_project_object_refs where project_id=%s", (project_id,))
            old_refs = cur.fetchall()
            cur.execute("delete from tenant_project_object_refs where project_id=%s", (project_id,))
            for bucket, object_key in old_refs:
                cur.execute(
                    """
                    select o.bucket, o.object_key from tenant_objects o
                    where o.bucket=%s and o.object_key=%s and o.status <> 'deleted'
                      and not exists (
                        select 1 from tenant_object_job_refs r join jobs j on j.id=r.job_id
                        where r.bucket=o.bucket and r.object_key=o.object_key
                          and j.status in ('queued','running','succeeded') and j.retention_expires_at>now()
                      )
                      and not exists (
                        select 1 from tenant_project_object_refs pr join projects p on p.id=pr.project_id
                        where pr.bucket=o.bucket and pr.object_key=o.object_key
                          and p.deleted_at is null and p.retention_expires_at>now()
                      )
                    """,
                    (bucket, object_key),
                )
                maybe = cur.fetchone()
                if maybe is not None:
                    object_rows.append((str(maybe[0]), str(maybe[1])))
                    cur.execute("update tenant_objects set retention_expires_at=least(retention_expires_at, now()), updated_at=now() where bucket=%s and object_key=%s", (bucket, object_key))
        if object_store is None:
            return {"deletedObjects": 0, "failedObjects": 0}
        deleted = 0
        failed = 0
        seen: set[tuple[str, str]] = set()
        for bucket, object_key in object_rows:
            item = (bucket, object_key)
            if item in seen:
                continue
            seen.add(item)
            if not self._tenant_store._claim_expired_object(bucket=bucket, object_key=object_key):
                continue
            try:
                object_store.delete_object(object_key)
            except Exception as exc:
                failed += 1
                self._tenant_store._mark_delete_failure(bucket=bucket, object_key=object_key, error=type(exc).__name__)
            else:
                deleted += 1
                self._tenant_store._mark_deleted(bucket=bucket, object_key=object_key)
        return {"deletedObjects": deleted, "failedObjects": failed}

    def _expire_projects(self, *, owner_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self._expire_projects_cur(cur, owner_id=owner_id)

    def _expire_projects_cur(self, cur, *, owner_id: str) -> None:
        cur.execute("update projects set deleted_at=coalesce(deleted_at, now()), updated_at=now() where owner_id=%s::uuid and deleted_at is null and retention_expires_at<=now()", (owner_id,))

    def _validate_pg_refs(self, cur, *, owner_id: str, project: ProjectData) -> None:
        for photo in project.object_refs:
            bucket = self.bucket
            cur.execute(
                """
                select 1 from tenant_objects
                where owner_id=%s::uuid and bucket=%s and object_key=%s and status='uploaded'
                  and retention_expires_at>now() and content_type=%s and size_bytes=%s
                for update
                """,
                (owner_id, bucket, photo.object_key, photo.content_type, photo.size_bytes),
            )
            if cur.fetchone() is None:
                raise ObjectAccessError("Project object is missing, expired, has changed metadata, or belongs to another user.")
        if project.last_job_id is not None:
            cur.execute(
                """
                select 1 from jobs where id=%s and owner_id=%s::uuid
                """,
                (project.last_job_id, owner_id),
            )
            if cur.fetchone() is None:
                raise OwnershipError("lastJobId is not owned by this user.")

    def _replace_project_refs(self, cur, *, owner_id: str, project_id: str, refs: tuple[InputPhoto, ...], retention: str) -> None:
        cur.execute("delete from tenant_project_object_refs where project_id=%s", (project_id,))
        for photo in refs:
            cur.execute(
                """
                insert into tenant_project_object_refs (owner_id, bucket, object_key, project_id, retention_expires_at)
                values (%s::uuid,%s,%s,%s,%s::timestamptz)
                on conflict (bucket, object_key, project_id) do update set
                  retention_expires_at=excluded.retention_expires_at, updated_at=now()
                """,
                (owner_id, self.bucket, photo.object_key, project_id, retention),
            )
            cur.execute(
                """
                update tenant_objects set retention_expires_at=greatest(retention_expires_at, %s::timestamptz), updated_at=now()
                where owner_id=%s::uuid and bucket=%s and object_key=%s
                """,
                (retention, owner_id, self.bucket, photo.object_key),
            )


def _project_from_pg(row: dict[str, object]) -> dict[str, object]:
    project = {
        "id": str(row["id"]),
        "revision": int(row["revision"]),
        "createdAt": _dt_to_iso(row["created_at"]),
        "updatedAt": _dt_to_iso(row["updated_at"]),
        "retentionExpiresAt": _dt_to_iso(row["retention_expires_at"]),
        "name": str(row["name"]),
        "font": row["font"],
        "mode": str(row["mode"]),
        "targetCharacters": str(row["target_characters"]),
        "glyphs": row["glyphs"] or [],
        "sheet": row["sheet"],
        "lastJobId": row["last_job_id"],
    }
    return project


def _public_project(row: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in row.items() if k not in {"ownerId", "deletedAt"}}


def _future(value: object) -> bool:
    if not value:
        return False
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc) > datetime.now(timezone.utc)
    except Exception:
        return False
