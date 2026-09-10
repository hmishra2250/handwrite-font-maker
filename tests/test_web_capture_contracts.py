from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageDraw

from handwrite_font_maker.web.api import create_job, worker_once
from handwrite_font_maker.web.contracts import FontRequest, InputPhoto, JobArtifact
from handwrite_font_maker.web.job_store import JsonJobStore
from handwrite_font_maker.web.server import Handler
from handwrite_font_maker.web.supabase_store import LocalObjectStore


def _png(path: Path, *, foreground: bool = True, size: tuple[int, int] = (64, 64)) -> int:
    image = Image.new("RGB", size, "white")
    if foreground:
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 12, 44, 50), fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path.stat().st_size


def _fake_outputs(output_dir: Path, font_name: str) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / "work" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{}", encoding="utf-8")
    otf = output_dir / f"{font_name}.otf"
    ttf = output_dir / f"{font_name}.ttf"
    otf.write_bytes(b"otf")
    ttf.write_bytes(b"ttf")
    return {"manifest": str(manifest), "otf": str(otf), "ttf": str(ttf), "warnings": []}


def test_template_capture_round_trips_and_worker_passes_alignment(monkeypatch, tmp_path: Path):
    store_path = tmp_path / "jobs.json"
    object_root = tmp_path / "objects"
    object_key = "jobs/job_template/input/original.png"
    size = _png(object_root / object_key)
    corners = [[0.1, 0.1], [0.9, 0.1], [0.85, 0.9], [0.12, 0.88]]
    calls: dict[str, object] = {}

    def fake_build_font(**kwargs: object) -> dict[str, object]:
        calls.update(kwargs)
        return _fake_outputs(Path(kwargs["output_dir"]), str(kwargs["font_name"]))

    monkeypatch.setattr("handwrite_font_maker.web.worker._build_font", fake_build_font)
    created = create_job(
        store_path,
        object_key=object_key,
        content_type="image/png",
        size_bytes=size,
        font_name="TemplateFont",
        family_name="Template Font",
        capture={"mode": "template", "templateId": "default-v1", "paperSize": "A4", "alignment": "page", "corners": corners},
    )

    raw_store = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw_store[created["jobId"]]["capture"] == {"mode": "template", "templateId": "default-v1", "paperSize": "A4", "alignment": "page", "corners": corners}

    result = worker_once(store_path, object_root)
    assert result is not None
    assert result["status"] == "succeeded"
    assert calls["alignment"] == "page"
    assert calls["corners"] == tuple(tuple(p) for p in corners)
    assert calls["paper_size"] == "A4"


def test_guided_capture_validates_each_mask_and_worker_passes_glyph_paths(monkeypatch, tmp_path: Path):
    store_path = tmp_path / "jobs.json"
    object_root = tmp_path / "objects"
    a_key = "jobs/job_guided/input/A.png"
    b_key = "jobs/job_guided/input/B.png"
    a_size = _png(object_root / a_key)
    b_size = _png(object_root / b_key)
    calls: dict[str, object] = {}

    def fake_build_font_from_masks(**kwargs: object) -> dict[str, object]:
        calls.update(kwargs)
        glyphs = kwargs["glyphs"]
        assert [g["char"] for g in glyphs] == ["A", "B"]
        assert all(Path(g["image_path"]).exists() for g in glyphs)
        assert [g["baseline"] for g in glyphs] == [0.7, 0.8]
        return _fake_outputs(Path(kwargs["output_dir"]), str(kwargs["font_name"]))

    monkeypatch.setattr("handwrite_font_maker.web.worker._build_font_from_masks", fake_build_font_from_masks)
    create_job(
        store_path,
        object_key=a_key,
        content_type="image/png",
        size_bytes=a_size,
        font_name="GuidedFont",
        family_name="Guided Font",
        capture={
            "mode": "guided",
            "format": "mask-v1",
            "glyphs": [
                {"char": "A", "inputPhoto": {"objectKey": a_key, "contentType": "image/png", "sizeBytes": a_size}, "baseline": 0.7},
                {"char": "B", "inputPhoto": {"objectKey": b_key, "contentType": "image/png", "sizeBytes": b_size}, "baseline": 0.8},
            ],
        },
    )

    result = worker_once(store_path, object_root)
    assert result is not None
    assert result["status"] == "succeeded"
    assert calls["font_name"] == "GuidedFont"


def test_guided_capture_rejects_duplicate_label_and_bad_baseline(tmp_path: Path):
    photo = {"objectKey": "jobs/j/input/A.png", "contentType": "image/png", "sizeBytes": 10}
    for glyphs in (
        [
            {"char": "A", "inputPhoto": photo, "baseline": 0.8},
            {"char": "A", "inputPhoto": {**photo, "objectKey": "jobs/j/input/B.png"}, "baseline": 0.7},
        ],
        [{"char": "A", "inputPhoto": photo, "baseline": 1}],
    ):
        try:
            create_job(
                tmp_path / "jobs.json",
                object_key=photo["objectKey"],
                content_type="image/png",
                size_bytes=10,
                font_name="BadGuided",
                family_name="Bad Guided",
                capture={"mode": "guided", "format": "mask-v1", "glyphs": glyphs},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("invalid guided capture was accepted")


def _start_server(tmp_path: Path):
    Handler.store_path = tmp_path / "jobs.json"
    Handler.object_root = tmp_path / "objects"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _post_json(url: str, payload: object | bytes):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_capture_page_endpoint_returns_normalized_corners(monkeypatch, tmp_path: Path):
    object_key = "jobs/job_capture/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(200, 100))
    monkeypatch.setattr("handwrite_font_maker.web.server._detect_page_corners", lambda _image: [[20, 10], [180, 10], [170, 90], [24, 88]])
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(base + "/capture/page", {"inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size}})
    finally:
        server.shutdown()
    assert status == 200
    assert payload["corners"] == [[0.1, 0.1], [0.9, 0.1], [0.85, 0.9], [0.12, 0.88]]


def test_server_malformed_json_and_bad_integer_types_return_4xx(tmp_path: Path):
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(base + "/jobs", b"{not-json")
        assert status == 400
        assert payload["error"]["code"] == "INTERNAL_ERROR"
        status, payload = _post_json(base + "/uploads", {"filename": "x.png", "contentType": "image/png", "sizeBytes": "12"})
        assert status == 400
        assert payload["error"]["code"] == "UPLOAD_OBJECT_MISSING"
    finally:
        server.shutdown()


def test_get_job_resigns_persisted_artifacts(tmp_path: Path):
    store_path = tmp_path / "jobs.json"
    object_root = tmp_path / "objects"
    store = JsonJobStore(store_path)
    job = store.create(
        input_photo=InputPhoto("jobs/j/input/original.png", "image/png", 10),
        font=FontRequest("ReSign", "ReSign"),
    )
    job.artifacts = [JobArtifact(kind="ttf", label="TrueType Font", object_key="jobs/j/artifacts/ReSign.ttf", content_type="font/ttf", size_bytes=3, url="stale://url")]
    store.save(job)
    (object_root / "jobs/j/artifacts").mkdir(parents=True)
    (object_root / "jobs/j/artifacts/ReSign.ttf").write_bytes(b"ttf")
    server, base = _start_server(tmp_path)
    try:
        with urllib.request.urlopen(base + f"/jobs/{job.id}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
    artifact = payload["artifacts"][0]
    assert artifact == {
        "kind": "ttf",
        "label": "TrueType Font",
        "objectKey": "jobs/j/artifacts/ReSign.ttf",
        "contentType": "font/ttf",
        "sizeBytes": 3,
        "url": artifact["url"],
        "expiresAt": None,
    }
    assert artifact["url"].startswith("local://download/jobs/j/artifacts/ReSign.ttf")
    assert "object_key" not in artifact
    assert "content_type" not in artifact
    assert "size_bytes" not in artifact
    assert "expires_at" not in artifact


def test_capture_foreground_endpoint_returns_png_data_url(monkeypatch, tmp_path: Path):
    import base64
    import io

    object_key = "jobs/job_foreground/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(120, 80))
    seen: dict[str, object] = {}

    def fake_extract(image_bgr, rectangle):
        seen["shape"] = image_bgr.shape
        seen["rectangle"] = rectangle
        mask = Image.new("L", (32, 24), 255)
        draw = ImageDraw.Draw(mask)
        draw.rectangle((8, 6, 22, 18), fill=0)
        return __import__("numpy").asarray(mask)

    monkeypatch.setattr("handwrite_font_maker.web.server._extract_foreground", fake_extract)
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(base + "/capture/foreground", {"inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size}, "rectangle": [0.1, 0.2, 0.9, 0.8]})
    finally:
        server.shutdown()
    assert status == 200
    assert payload["method"] == "grabcut"
    assert payload["width"] == 32
    assert payload["height"] == 24
    assert seen["rectangle"] == (0.1, 0.2, 0.9, 0.8)
    prefix = "data:image/png;base64,"
    assert payload["maskDataUrl"].startswith(prefix)
    decoded = base64.b64decode(payload["maskDataUrl"][len(prefix):])
    with Image.open(io.BytesIO(decoded)) as image:
        assert image.mode == "L"
        assert image.size == (32, 24)


def test_capture_foreground_rejects_invalid_rectangle_and_empty_mask(monkeypatch, tmp_path: Path):
    object_key = "jobs/job_foreground_bad/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(80, 80))
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(base + "/api/capture/foreground", {"inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size}, "rectangle": [0.5, 0.2, 0.4, 0.8]})
        assert status == 422
        assert payload["error"]["code"] == "GLYPH_EXTRACTION_FAILED"
    finally:
        server.shutdown()

    monkeypatch.setattr("handwrite_font_maker.web.server._extract_foreground", lambda *_args: __import__("numpy").full((16, 16), 255, dtype=__import__("numpy").uint8))
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(base + "/api/capture/foreground", {"inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size}, "rectangle": [0.1, 0.1, 0.9, 0.9]})
    finally:
        server.shutdown()
    assert status == 422
    assert payload["error"]["code"] == "GLYPH_EXTRACTION_FAILED"


def test_server_guided_cumulative_cap_uses_actual_downloaded_bytes_not_declared(monkeypatch, tmp_path: Path):
    import pytest

    from handwrite_font_maker.web.contracts import HardErrorCode, parse_capture_config, parse_input_photo
    from handwrite_font_maker.web.server import _validate_capture_objects

    object_root = tmp_path / "objects"
    a_key = "jobs/job_actual_server/input/A.png"
    b_key = "jobs/job_actual_server/input/B.png"
    a_actual = _png(object_root / a_key, size=(72, 72))
    b_actual = _png(object_root / b_key, size=(72, 72))
    outer = parse_input_photo({"objectKey": a_key, "contentType": "image/png", "sizeBytes": 1})
    capture = parse_capture_config(
        {
            "mode": "guided",
            "format": "mask-v1",
            "glyphs": [
                {"char": "A", "inputPhoto": {"objectKey": a_key, "contentType": "image/png", "sizeBytes": 1}, "baseline": 0.8},
                {"char": "B", "inputPhoto": {"objectKey": b_key, "contentType": "image/png", "sizeBytes": 1}, "baseline": 0.8},
            ],
        },
        outer_input_photo=outer,
    )
    monkeypatch.setattr("handwrite_font_maker.web.server.MAX_UPLOAD_BYTES", a_actual + b_actual - 1)

    with pytest.raises(ValueError, match=HardErrorCode.UPLOAD_OBJECT_TOO_LARGE.value):
        _validate_capture_objects(outer, capture, LocalObjectStore(object_root))


def test_worker_guided_cumulative_cap_uses_actual_downloaded_bytes_not_declared(monkeypatch, tmp_path: Path):
    store_path = tmp_path / "jobs.json"
    object_root = tmp_path / "objects"
    a_key = "jobs/job_actual_worker/input/A.png"
    b_key = "jobs/job_actual_worker/input/B.png"
    a_actual = _png(object_root / a_key, size=(72, 72))
    b_actual = _png(object_root / b_key, size=(72, 72))
    monkeypatch.setattr("handwrite_font_maker.web.worker.MAX_GUIDED_TOTAL_BYTES", a_actual + b_actual - 1)

    def fail_if_called(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("build_font_from_masks should not run after cumulative actual-byte rejection")

    monkeypatch.setattr("handwrite_font_maker.web.worker._build_font_from_masks", fail_if_called)
    create_job(
        store_path,
        object_key=a_key,
        content_type="image/png",
        size_bytes=1,
        font_name="ActualCap",
        family_name="Actual Cap",
        capture={
            "mode": "guided",
            "format": "mask-v1",
            "glyphs": [
                {"char": "A", "inputPhoto": {"objectKey": a_key, "contentType": "image/png", "sizeBytes": 1}, "baseline": 0.8},
                {"char": "B", "inputPhoto": {"objectKey": b_key, "contentType": "image/png", "sizeBytes": 1}, "baseline": 0.8},
            ],
        },
    )

    result = worker_once(store_path, object_root)
    assert result is not None
    assert result["status"] == "failed"
    assert result["error"]["code"] == "UPLOAD_OBJECT_TOO_LARGE"
