"""端到端測試:REST 介面 + 前處理 + 引擎切換。

用一個假的 OpenAI 相容視覺端點取代 vLLM,驗證 ``vision`` 引擎的
請求格式、兩階段流程、錯誤處理與 EXIF 轉正,不需要 GPU 或模型權重。

執行:cd src/ai-service && python tests/test_pipeline.py
"""
from __future__ import annotations

import io
import json
import sys
import threading
import time
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from tests.test_structurer import FIXTURE  # noqa: E402

# --------------------------------------------------------------------------
# 假的 OpenAI 相容端點
# --------------------------------------------------------------------------
_state: dict = {"last_request": None, "reply": FIXTURE, "status": 200}


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):  # noqa: D102
        pass


def _fake_app(environ, start_response):
    path = environ.get("PATH_INFO", "")
    if path == "/v1/models":
        body = json.dumps({"data": [{"id": "fake-chandra"}]}).encode()
        start_response("200 OK", [("Content-Type", "application/json")])
        return [body]

    length = int(environ.get("CONTENT_LENGTH") or 0)
    payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
    _state["last_request"] = payload

    if _state["status"] != 200:
        start_response(f"{_state['status']} Error", [("Content-Type", "text/plain")])
        return [b"model is overloaded"]

    body = json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": _state["reply"]}}]}
    ).encode()
    start_response("200 OK", [("Content-Type", "application/json")])
    return [body]


def _start_fake_server() -> tuple[str, object]:
    srv = make_server("127.0.0.1", 0, _fake_app, handler_class=_QuietHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.1)
    return f"http://127.0.0.1:{srv.server_port}", srv


# --------------------------------------------------------------------------
# 測試影像
# --------------------------------------------------------------------------
def _rotated_photo(width=3200, height=2400) -> bytes:
    """模擬手機直立拍攝:像素為橫向,但 EXIF Orientation=6 表示需順時針轉 90°。"""
    im = Image.new("RGB", (width, height), "white")
    exif = im.getexif()
    exif[274] = 6
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _run(env: dict, fn) -> None:
    """以指定環境變數重新載入模組後執行 fn(client)。"""
    import os

    from fastapi.testclient import TestClient

    old = {k: os.environ.get(k) for k in env}
    os.environ.update({k: str(v) for k, v in env.items()})
    for mod in [m for m in list(sys.modules) if m.startswith("app")]:
        del sys.modules[mod]
    try:
        from app.main import app

        with TestClient(app) as client:
            fn(client)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# --------------------------------------------------------------------------
# 測試
# --------------------------------------------------------------------------
def test_mock_engine_is_flagged_as_mock():
    """模擬引擎必須自我揭露,否則使用者會誤以為是真實辨識結果。"""

    def check(client):
        health = client.get("/api/v1/health").json()
        assert health["isMock"] is True, health

        files = {"file": ("p.jpg", _rotated_photo(400, 300), "image/jpeg")}
        r = client.post("/api/v1/ocr/analyze", files=files)
        assert r.status_code == 200
        body = r.json()
        assert body["isMock"] is True
        assert any("模擬引擎" in w for w in body["warnings"]), body["warnings"]
        assert body["fields"]["patient_name"]["value"] == "陳○宏"

    _run({"DMAT_ENGINE": "mock"}, check)


def test_preprocess_applies_exif_and_downscale():
    base_url, srv = _start_fake_server()
    try:

        def check(client):
            files = {"file": ("p.jpg", _rotated_photo(), "image/jpeg")}
            r = client.post("/api/v1/ocr/analyze", files=files)
            assert r.status_code == 200, r.text
            pre = r.json()["preprocess"]
            assert pre["originalSize"] == "3200x2400"
            # EXIF Orientation=6 → 轉正後變直立,再把長邊縮到 2000
            assert pre["finalSize"] == "1500x2000", pre
            assert pre["exifTransposed"] is True
            assert pre["resized"] is True
            assert pre["finalBytes"] < pre["originalBytes"]

        _run({"DMAT_ENGINE": "vision", "DMAT_VISION_BASE_URL": base_url}, check)
    finally:
        srv.shutdown()


def test_vision_engine_two_stage_structures_transcript():
    base_url, srv = _start_fake_server()
    _state["reply"] = FIXTURE
    _state["status"] = 200
    try:

        def check(client):
            files = {"file": ("p.jpg", _rotated_photo(800, 600), "image/jpeg")}
            r = client.post("/api/v1/ocr/analyze", files=files)
            assert r.status_code == 200, r.text
            body = r.json()

            assert body["isMock"] is False
            f = body["fields"]
            assert f["patient_name"]["value"] == "陳○宏"
            assert f["triage"]["value"] == "2"
            assert f["blood_pressure_systolic"]["value"] == 144
            assert f["trauma_superficial_injury"]["value"] is True
            assert f["chronic_disease_hypertension"]["value"] is True

            # 送出的請求必須是 OpenAI 視覺格式:文字提示 + base64 data URI
            req = _state["last_request"]
            content = req["messages"][0]["content"]
            assert content[0]["type"] == "text"
            assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
            assert req["temperature"] == 0.0

            stages = [s["stage"] for s in body["stages"]]
            assert stages == ["ocr_transcribe", "structure_rules"], stages

        _run({"DMAT_ENGINE": "vision", "DMAT_VISION_BASE_URL": base_url, "DMAT_RETURN_RAW": "1"}, check)
    finally:
        srv.shutdown()


def test_engine_failure_returns_actionable_message():
    """推論服務掛掉時,必須回傳看得懂的原因,而不是靜默變成假資料。"""

    def check(client):
        files = {"file": ("p.jpg", _rotated_photo(400, 300), "image/jpeg")}
        r = client.post("/api/v1/ocr/analyze", files=files)
        assert r.status_code == 502, r.status_code
        err = r.json()["error"]
        assert "無法連線" in err and "vLLM" in err, err

    # 指向一個沒人在聽的埠
    _run({"DMAT_ENGINE": "vision", "DMAT_VISION_BASE_URL": "http://127.0.0.1:9"}, check)


def test_http_error_from_inference_server_is_surfaced():
    base_url, srv = _start_fake_server()
    _state["status"] = 500
    try:

        def check(client):
            files = {"file": ("p.jpg", _rotated_photo(400, 300), "image/jpeg")}
            r = client.post("/api/v1/ocr/analyze", files=files)
            assert r.status_code == 502
            assert "HTTP 500" in r.json()["error"]

        _run({"DMAT_ENGINE": "vision", "DMAT_VISION_BASE_URL": base_url}, check)
    finally:
        _state["status"] = 200
        srv.shutdown()


def test_transcribe_endpoint_returns_raw_ocr():
    base_url, srv = _start_fake_server()
    _state["reply"] = FIXTURE
    try:

        def check(client):
            files = {"file": ("p.jpg", _rotated_photo(600, 400), "image/jpeg")}
            r = client.post("/api/v1/ocr/transcribe", files=files)
            assert r.status_code == 200, r.text
            assert "陳○宏" in r.json()["raw"]["transcript"]

        _run({"DMAT_ENGINE": "vision", "DMAT_VISION_BASE_URL": base_url}, check)
    finally:
        srv.shutdown()


def test_unknown_engine_reported_via_health_not_crash():
    def check(client):
        r = client.get("/api/v1/health")
        assert r.status_code == 503
        assert "未知的 DMAT_ENGINE" in r.json()["error"]

    _run({"DMAT_ENGINE": "totally-bogus"}, check)


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except Exception as e:  # noqa: BLE001
                print(f"FAIL {name}: {type(e).__name__}: {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
