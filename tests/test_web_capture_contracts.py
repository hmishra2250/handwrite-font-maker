from __future__ import annotations

import json
import threading
import urllib.error
from types import SimpleNamespace
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
    bundle = output_dir / f"{font_name}-download.zip"
    otf.write_bytes(b"otf")
    ttf.write_bytes(b"ttf")
    bundle.write_bytes(b"zip")
    return {"manifest": str(manifest), "otf": str(otf), "ttf": str(ttf), "download_bundle": str(bundle), "warnings": []}


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
        assert [g["scale"] for g in glyphs] == [1.0, 1.25]
        assert [g["spacing"] for g in glyphs] == [0.0, 0.1]
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
                {"char": "B", "inputPhoto": {"objectKey": b_key, "contentType": "image/png", "sizeBytes": b_size}, "baseline": 0.8, "scale": 1.25, "spacing": 0.1},
            ],
        },
    )

    result = worker_once(store_path, object_root)
    assert result is not None
    assert result["status"] == "succeeded"
    assert calls["font_name"] == "GuidedFont"
    raw_store = json.loads(store_path.read_text(encoding="utf-8"))
    capture = next(iter(raw_store.values()))["capture"]
    assert [glyph["scale"] for glyph in capture["glyphs"]] == [1.0, 1.25]
    assert [glyph["spacing"] for glyph in capture["glyphs"]] == [0.0, 0.1]
    bundle = next(artifact for artifact in result["artifacts"] if artifact["kind"] == "download_bundle")
    assert bundle["contentType"] == "application/zip"


def test_guided_capture_rejects_duplicate_label_and_bad_baseline(tmp_path: Path):
    photo = {"objectKey": "jobs/j/input/A.png", "contentType": "image/png", "sizeBytes": 10}
    for glyphs in (
        [
            {"char": "A", "inputPhoto": photo, "baseline": 0.8},
            {"char": "A", "inputPhoto": {**photo, "objectKey": "jobs/j/input/B.png"}, "baseline": 0.7},
        ],
        [{"char": "A", "inputPhoto": photo, "baseline": 1}],
        [{"char": "A", "inputPhoto": photo, "baseline": 0.8, "scale": 0.49}],
        [{"char": "A", "inputPhoto": photo, "baseline": 0.8, "spacing": 0.251}],
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

    def fake_extract(image_bgr, rectangle, *, method, style, threshold, points):
        seen["shape"] = image_bgr.shape
        seen["rectangle"] = rectangle
        seen["options"] = {"method": method, "style": style, "threshold": threshold, "points": points}
        mask = Image.new("L", (32, 24), 255)
        draw = ImageDraw.Draw(mask)
        draw.rectangle((8, 6, 22, 18), fill=0)
        return SimpleNamespace(mask=__import__("numpy").asarray(mask), method="grabcut", model_id=None, warnings=())

    monkeypatch.setattr("handwrite_font_maker.web.server._extract_foreground", fake_extract)
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(base + "/capture/foreground", {"inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size}, "rectangle": [0.1, 0.2, 0.9, 0.8]})
    finally:
        server.shutdown()
    assert status == 200
    assert payload["method"] == "grabcut"
    assert payload["modelId"] is None
    assert payload["warnings"] == []
    assert payload["width"] == 32
    assert payload["height"] == 24
    assert seen["rectangle"] == (0.1, 0.2, 0.9, 0.8)
    assert seen["options"] == {"method": "auto", "style": "silhouette", "threshold": 128, "points": None}
    prefix = "data:image/png;base64,"
    assert payload["maskDataUrl"].startswith(prefix)
    decoded = base64.b64decode(payload["maskDataUrl"][len(prefix):])
    with Image.open(io.BytesIO(decoded)) as image:
        assert image.mode == "L"
        assert image.size == (32, 24)


def test_capture_foreground_auto_reports_fast_threshold_without_weights(monkeypatch, tmp_path: Path):
    object_key = "jobs/job_foreground_auto/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(96, 96))
    monkeypatch.setenv("HANDWRITE_MODEL_DIR", str(tmp_path / "missing-model"))
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(
            base + "/capture/foreground",
            {
                "inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size},
                "rectangle": [0.1, 0.1, 0.7, 0.7],
                "method": "auto",
            },
        )
    finally:
        server.shutdown()
    assert status == 200
    assert payload["method"] == "threshold"
    assert payload["modelId"] is None
    assert payload["warnings"]
    assert any("threshold" in warning.lower() for warning in payload["warnings"])
    assert payload["maskDataUrl"].startswith("data:image/png;base64,")


def test_capture_foreground_serializes_model_cutout_metadata(monkeypatch, tmp_path: Path):
    object_key = "jobs/job_foreground_model/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(120, 80))
    seen: dict[str, object] = {}

    def fake_extract(_image_bgr, rectangle, *, method, style, threshold, points):
        import numpy as np

        seen["rectangle"] = rectangle
        seen["options"] = {"method": method, "style": style, "threshold": threshold, "points": points}
        mask = np.full((18, 20), 255, dtype=np.uint8)
        mask[4:14, 6:12] = 0
        return SimpleNamespace(mask=mask, method="slimsam", model_id="slimsam-test", warnings=("low confidence",))

    monkeypatch.setattr("handwrite_font_maker.web.server._extract_foreground", fake_extract)
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(
            base + "/api/capture/foreground",
            {
                "inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size},
                "rectangle": [0.15, 0.2, 0.85, 0.75],
                "method": "model",
                "style": "ink",
                "threshold": 93,
                "points": [
                    {"x": 0.2, "y": 0.3, "label": 1},
                    {"x": 0.95, "y": 0.95, "label": 0},
                ],
            },
        )
    finally:
        server.shutdown()
    assert status == 200
    assert payload["method"] == "slimsam"
    assert payload["modelId"] == "slimsam-test"
    assert payload["warnings"] == ["low confidence"]
    assert payload["width"] == 20
    assert payload["height"] == 18
    assert seen["rectangle"] == (0.15, 0.2, 0.85, 0.75)
    assert seen["options"] == {
        "method": "model",
        "style": "ink",
        "threshold": 93,
        "points": [{"x": 0.2, "y": 0.3, "label": 1}, {"x": 0.95, "y": 0.95, "label": 0}],
    }



def test_capture_foreground_box_model_serializes_efficientsam_metadata(monkeypatch, tmp_path: Path):
    object_key = "jobs/job_foreground_box_model/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(120, 80))
    seen: dict[str, object] = {}

    def fake_extract(_image_bgr, rectangle, *, method, style, threshold, points):
        import numpy as np

        seen["rectangle"] = rectangle
        seen["options"] = {"method": method, "style": style, "threshold": threshold, "points": points}
        mask = np.full((18, 20), 255, dtype=np.uint8)
        mask[4:14, 6:12] = 0
        return SimpleNamespace(mask=mask, method="efficientsam", model_id="yunyangx/EfficientSAM@rev:ti-box", warnings=())

    monkeypatch.setattr("handwrite_font_maker.web.server._extract_foreground", fake_extract)
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(
            base + "/api/capture/foreground",
            {
                "inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size},
                "rectangle": [0.15, 0.2, 0.85, 0.75],
                "method": "box-model",
                "style": "ink",
                "threshold": 94,
            },
        )
    finally:
        server.shutdown()
    assert status == 200
    assert payload["method"] == "efficientsam"
    assert payload["modelId"] == "yunyangx/EfficientSAM@rev:ti-box"
    assert payload["warnings"] == []
    assert seen["rectangle"] == (0.15, 0.2, 0.85, 0.75)
    assert seen["options"] == {"method": "box-model", "style": "ink", "threshold": 94, "points": None}


def test_capture_foreground_box_model_rejects_points_before_download(monkeypatch, tmp_path: Path):
    def fail_if_called(_object_root):
        raise AssertionError("box-model requests with points should be rejected before object download")

    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", fail_if_called)
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(
            base + "/api/capture/foreground",
            {
                "inputPhoto": {"objectKey": "jobs/job_box_points/input/original.png", "contentType": "image/png", "sizeBytes": 1},
                "rectangle": [0.1, 0.1, 0.9, 0.9],
                "method": "box-model",
                "points": [{"x": 0.5, "y": 0.5, "label": 1}],
            },
        )
    finally:
        server.shutdown()
    assert status == 422
    assert payload["error"]["code"] == "GLYPH_EXTRACTION_FAILED"


def test_capture_foreground_box_model_missing_weights_is_503(monkeypatch, tmp_path: Path):
    object_key = "jobs/job_box_missing_real/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(96, 96))
    monkeypatch.setenv("HANDWRITE_EFFICIENTSAM_MODEL_DIR", str(tmp_path / "missing-efficient"))
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(
            base + "/capture/foreground",
            {
                "inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size},
                "rectangle": [0.1, 0.1, 0.9, 0.9],
                "method": "box-model",
            },
        )
    finally:
        server.shutdown()
    assert status == 503
    assert payload["error"]["code"] == "MODEL_UNAVAILABLE"
    assert payload["error"]["retryable"] is False

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

    monkeypatch.setattr(
        "handwrite_font_maker.web.server._extract_foreground",
        lambda *_args, **_kwargs: __import__("numpy").full((16, 16), 255, dtype=__import__("numpy").uint8),
    )
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(base + "/api/capture/foreground", {"inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size}, "rectangle": [0.1, 0.1, 0.9, 0.9]})
    finally:
        server.shutdown()
    assert status == 422
    assert payload["error"]["code"] == "GLYPH_EXTRACTION_FAILED"


def test_capture_foreground_rejects_invalid_options_before_download(monkeypatch, tmp_path: Path):
    def fail_if_called(_object_root):
        raise AssertionError("invalid foreground options should be rejected before object download")

    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", fail_if_called)
    base_payload = {
        "inputPhoto": {"objectKey": "jobs/job_options/input/original.png", "contentType": "image/png", "sizeBytes": 1},
        "rectangle": [0.1, 0.1, 0.9, 0.9],
    }
    server, base = _start_server(tmp_path)
    try:
        for override in (
            {"method": "slimsam"},
            {"style": "transparent"},
            {"threshold": 128.0},
            {"threshold": True},
            {"threshold": 0},
            {"threshold": 255},
            {"points": [{"x": 0.2, "y": 0.2, "label": 2}]},
            {"points": [{"x": 0.2, "y": 0.2, "label": 1.0}]},
            {"points": [{"x": 0.2, "y": 0.2, "label": True}]},
            {"points": [{"x": -0.1, "y": 0.2, "label": 0}]},
            {"points": [{"x": 0.05, "y": 0.2, "label": 1}]},
            {"points": [{"x": 0.2, "y": 0.2, "label": 0}] * 17},
            {"points": [{"x": 0.2, "y": 0.2}]},
            {"points": [{"x": 0.2, "y": 0.2, "label": 1, "box": [0.1, 0.1, 0.3, 0.3]}]},
        ):
            status, payload = _post_json(base + "/api/capture/foreground", {**base_payload, **override})
            assert status == 422
            assert payload["error"]["code"] == "GLYPH_EXTRACTION_FAILED"
    finally:
        server.shutdown()


def test_capture_foreground_model_requires_positive_point_before_download(monkeypatch, tmp_path: Path):
    def fail_if_called(_object_root):
        raise AssertionError("model requests without a positive point should be rejected before object download")

    monkeypatch.setattr("handwrite_font_maker.web.server._object_store", fail_if_called)
    base_payload = {
        "inputPhoto": {"objectKey": "jobs/job_required_point/input/original.png", "contentType": "image/png", "sizeBytes": 1},
        "rectangle": [0.1, 0.1, 0.9, 0.9],
        "method": "model",
    }
    server, base = _start_server(tmp_path)
    try:
        for override in ({}, {"points": []}, {"points": [{"x": 0.2, "y": 0.2, "label": 0}]}):
            status, payload = _post_json(base + "/api/capture/foreground", {**base_payload, **override})
            assert status == 422
            assert payload["error"]["code"] == "GLYPH_EXTRACTION_FAILED"
    finally:
        server.shutdown()


def test_capture_foreground_model_missing_weights_is_real_503_after_point_validation(monkeypatch, tmp_path: Path):
    object_key = "jobs/job_model_missing_real/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(96, 96))
    monkeypatch.setenv("HANDWRITE_MODEL_DIR", str(tmp_path / "missing-model"))
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(
            base + "/capture/foreground",
            {
                "inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size},
                "rectangle": [0.1, 0.1, 0.9, 0.9],
                "method": "model",
                "points": [{"x": 0.5, "y": 0.5, "label": 1}],
            },
        )
    finally:
        server.shutdown()
    assert status == 503
    assert payload["error"]["code"] == "MODEL_UNAVAILABLE"
    assert payload["error"]["retryable"] is False


def test_capture_foreground_model_unavailable_is_503_without_fallback(monkeypatch, tmp_path: Path):
    from handwrite_font_maker.segmentation import ModelUnavailableError

    object_key = "jobs/job_model_missing/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(90, 90))
    calls = 0

    def fake_extract(_image_bgr, _rectangle, *, method, points, **_kwargs):
        nonlocal calls
        calls += 1
        assert method == "model"
        assert points == [{"x": 0.5, "y": 0.5, "label": 1}]
        raise ModelUnavailableError("weights missing")

    monkeypatch.setattr("handwrite_font_maker.web.server._extract_foreground", fake_extract)
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(
            base + "/capture/foreground",
            {
                "inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size},
                "rectangle": [0.1, 0.1, 0.9, 0.9],
                "method": "model",
                "points": [{"x": 0.5, "y": 0.5, "label": 1}],
            },
        )
    finally:
        server.shutdown()
    assert status == 503
    assert calls == 1
    assert payload["error"]["code"] == "MODEL_UNAVAILABLE"
    assert payload["error"]["retryable"] is False
    assert "grabcut" in payload["error"]["message"].lower()


def test_capture_foreground_busy_is_retryable_503(monkeypatch, tmp_path: Path):
    from handwrite_font_maker.segmentation import SegmentationBusyError

    object_key = "jobs/job_model_busy/input/original.png"
    size = _png(tmp_path / "objects" / object_key, size=(90, 90))

    def fake_extract(_image_bgr, _rectangle, **_kwargs):
        raise SegmentationBusyError("busy")

    monkeypatch.setattr("handwrite_font_maker.web.server._extract_foreground", fake_extract)
    server, base = _start_server(tmp_path)
    try:
        status, payload = _post_json(
            base + "/api/capture/foreground",
            {
                "inputPhoto": {"objectKey": object_key, "contentType": "image/png", "sizeBytes": size},
                "rectangle": [0.1, 0.1, 0.9, 0.9],
            },
        )
    finally:
        server.shutdown()
    assert status == 503
    assert payload["error"] == {
        "code": "SEGMENTATION_BUSY",
        "message": "Segmentation is temporarily busy. Retry shortly.",
        "retryable": True,
    }


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


def test_capture_diagnostics_record_success_and_failure(monkeypatch, tmp_path):
    diagnostics = tmp_path / 'private-diagnostics'
    monkeypatch.setenv('HANDWRITE_CAPTURE_DIAGNOSTICS_DIR', str(diagnostics))
    key = 'jobs/diagnostic/input/original.png'
    size = _png(tmp_path / 'objects' / key)
    monkeypatch.setattr('handwrite_font_maker.web.server._extract_foreground',
                        lambda *args, **kwargs: __import__('numpy').pad(__import__('numpy').zeros((16, 16), dtype='uint8'), 8, constant_values=255))
    server, base = _start_server(tmp_path)
    body = {'inputPhoto': {'objectKey': key, 'contentType': 'image/png', 'sizeBytes': size},
            'rectangle': [.1, .1, .9, .9], 'method': 'grabcut', 'style': 'silhouette'}
    try:
        status, payload = _post_json(base + '/capture/foreground', body)
        assert status == 200
        records = list(diagnostics.glob('*/record.json'))
        assert len(records) == 1
        record = json.loads(records[0].read_text())
        assert record['request'] == body
        assert record['result']['method'] == payload['method']
        assert (records[0].parent / 'mask.png').is_file()
        def fail(*args, **kwargs):
            raise ValueError('No foreground found')
        monkeypatch.setattr('handwrite_font_maker.web.server._extract_foreground', fail)
        status, _ = _post_json(base + '/capture/foreground', body)
        assert status >= 400
        assert sorted(json.loads(p.read_text())['state'] for p in diagnostics.glob('*/record.json')) == ['failed', 'succeeded']
    finally:
        server.shutdown()


def test_candidate_route_validates_and_records_options(monkeypatch,tmp_path):
    key='jobs/candidate/input/original.png';size=_png(tmp_path/'objects'/key)
    monkeypatch.setenv('HANDWRITE_CAPTURE_DIAGNOSTICS_DIR',str(tmp_path/'diagnostics'))
    seen=[]
    def generate(path,rectangle,stage):
        seen.append((rectangle,stage))
        return {'stage':stage,'candidates':[],'failures':[{'method':'test','message':'test failure'}]}
    monkeypatch.setattr('handwrite_font_maker.candidates.generate_candidates',generate)
    server,base=_start_server(tmp_path)
    body={'inputPhoto':{'objectKey':key,'contentType':'image/png','sizeBytes':size},'rectangle':[.1,.1,.9,.9],'stage':'ink','context':{'character':'A','invert':True}}
    try:
        status,result=_post_json(base+'/capture/candidates',body)
        assert status==200 and result['stage']=='ink'
        assert seen==[((.1,.1,.9,.9),'ink')]
        record=json.loads(next((tmp_path/'diagnostics').glob('*/record.json')).read_text())
        assert record['request']['context']==body['context'] and record['sourceSha256']
        status,_=_post_json(base+'/capture/candidates',{**body,'stage':'invalid'})
        assert status>=400 and len(seen)==1
    finally:server.shutdown()
