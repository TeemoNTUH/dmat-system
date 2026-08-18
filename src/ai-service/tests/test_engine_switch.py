"""驗證「把模擬辨識換成真實 OCR」這個切換動作本身是可靠的。

這支測試回答的問題是:寫好 `.env`(或設好環境變數)之後,服務是不是真的
不再回傳樣張假資料、而是把影像送去推論?—— 用一個假的推論端點代替 vLLM,
所以不需要 GPU 或模型權重就能驗證整條路。

真實模型權重無法在此驗證(需 GPU),但除了「模型本身讀得多準」之外,
其餘每一段都在這裡被檢查過了。

執行:cd src/ai-service && python tests/test_engine_switch.py
"""
from __future__ import annotations

import base64
import importlib
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

# 測試用設定檔寫在暫存目錄,透過 DMAT_ENV_FILE 指過去,不動到專案裡的 .env
ENV_PATH = Path(tempfile.gettempdir()) / "dmat-test-engine.env"

_received: dict = {}


class _Quiet(WSGIRequestHandler):
    def log_message(self, *a):  # noqa: D102
        pass


def _fake_vllm(environ, start_response):
    """假的 OpenAI 相容視覺端點,回傳一份簡短轉寫。"""
    if environ.get("PATH_INFO") == "/v1/models":
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps({"data": [{"id": "fake"}]}).encode()]

    length = int(environ.get("CONTENT_LENGTH") or 0)
    payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
    _received.update(payload)

    transcript = (
        "<p>檢傷分類:<input type='checkbox'> 1 復甦急救/重傷 "
        "<input type='checkbox' checked> 2 緊急/中傷</p>"
        "<table><tr><td>姓名:王測試</td>"
        "<td>性別:<input type='checkbox'>男 <input type='checkbox' checked>女</td></tr>"
        "<tr><td>傷票編號:B998877</td><td>體溫:37.8</td></tr></table>"
    )
    start_response("200 OK", [("Content-Type", "application/json")])
    return [json.dumps({"choices": [{"message": {"content": transcript}}]}).encode()]


def _serve():
    srv = make_server("127.0.0.1", 0, _fake_vllm, handler_class=_Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.1)
    return f"http://127.0.0.1:{srv.server_port}", srv


def _photo() -> bytes:
    im = Image.new("RGB", (900, 1200), "white")
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    return buf.getvalue()


def _fresh_client():
    """重新載入 app 模組(config 只在 import 時讀 .env / 環境變數)。"""
    from fastapi.testclient import TestClient

    for mod in [m for m in list(sys.modules) if m.startswith("app")]:
        del sys.modules[mod]
    main = importlib.import_module("app.main")
    return TestClient(main.app)


def _clear_env(keep_env_file: bool = True):
    for k in list(os.environ):
        if k.startswith("DMAT_"):
            os.environ.pop(k)
    if keep_env_file:
        os.environ["DMAT_ENV_FILE"] = str(ENV_PATH)


def test_env_file_switches_engine_off_mock():
    """核心驗證:.env 寫入 vision 引擎後,服務不再是 mock,且真的把影像送去推論。"""
    base_url, srv = _serve()
    _clear_env()
    try:
        # --- 情境 A:沒有 .env → 預設 mock,回樣張假資料 ---
        ENV_PATH.unlink(missing_ok=True)
        with _fresh_client() as client:
            health = client.get("/api/v1/health").json()
            assert health["isMock"] is True, "沒有 .env 時應為模擬引擎"

            r = client.post("/api/v1/ocr/analyze", files={"file": ("a.jpg", _photo(), "image/jpeg")})
            assert r.json()["fields"]["patient_name"]["value"] == "陳○宏", "mock 應回樣張假資料"

        # --- 情境 B:寫入 .env(等同 setup-ocr.sh 的動作)→ 切為真實引擎 ---
        _clear_env()
        ENV_PATH.write_text(
            "DMAT_ENGINE=vision\n"
            f"DMAT_VISION_BASE_URL={base_url}\n"
            "DMAT_VISION_MODEL=datalab-to/chandra-ocr-2\n"
            "DMAT_TWO_STAGE=1\n"
            "DMAT_PROMPT_STYLE=auto\n",
            encoding="utf-8",
        )
        _received.clear()
        with _fresh_client() as client:
            health = client.get("/api/v1/health").json()
            assert health["isMock"] is False, "寫入 .env 後不應再是模擬引擎"
            assert health["engineReady"] is True, health
            assert health["detail"]["promptStyle"] == "chandra", health["detail"]

            r = client.post("/api/v1/ocr/analyze", files={"file": ("a.jpg", _photo(), "image/jpeg")})
            assert r.status_code == 200, r.text
            body = r.json()

            # 1) 影像真的被送出去了(base64 data URI)
            content = _received["messages"][0]["content"]
            uri = content[1]["image_url"]["url"]
            assert uri.startswith("data:image/jpeg;base64,")
            assert len(base64.b64decode(uri.split(",", 1)[1])) > 1000, "送出的影像不應是空的"

            # 2) 回來的是這張照片的內容,不是樣張
            f = body["fields"]
            assert f["patient_name"]["value"] == "王測試", f["patient_name"]
            assert f["patient_tag_id"]["value"] == "B998877"
            assert f["triage"]["value"] == "2"
            assert f["gender"]["value"] == "女"
            assert abs(f["temperature_c"]["value"] - 37.8) < 0.01
            assert body["isMock"] is False
            assert not any("模擬引擎" in w for w in body["warnings"])
    finally:
        srv.shutdown()
        ENV_PATH.unlink(missing_ok=True)
        _clear_env(keep_env_file=False)


def test_env_var_overrides_env_file():
    """指令列的環境變數優先於 .env,方便臨時切回 mock 做介面測試。"""
    _clear_env()
    try:
        ENV_PATH.write_text("DMAT_ENGINE=vision\nDMAT_VISION_BASE_URL=http://127.0.0.1:9\n", encoding="utf-8")
        os.environ["DMAT_ENGINE"] = "mock"
        with _fresh_client() as client:
            assert client.get("/api/v1/health").json()["isMock"] is True
    finally:
        ENV_PATH.unlink(missing_ok=True)
        _clear_env(keep_env_file=False)


def test_generic_prompt_style_for_non_chandra_model():
    """換成 Qwen2.5-VL 等通用視覺模型時,自動改用中文指示式轉寫提示。"""
    base_url, srv = _serve()
    _clear_env()
    try:
        os.environ.update(
            {
                "DMAT_ENGINE": "vision",
                "DMAT_VISION_BASE_URL": base_url,
                "DMAT_VISION_MODEL": "nvidia/Qwen2.5-VL-7B-Instruct-NVFP4",
            }
        )
        _received.clear()
        with _fresh_client() as client:
            assert client.get("/api/v1/health").json()["detail"]["promptStyle"] == "generic"
            r = client.post("/api/v1/ocr/analyze", files={"file": ("a.jpg", _photo(), "image/jpeg")})
            assert r.status_code == 200, r.text
            # 通用提示為中文,且仍能結構化出欄位
            prompt = _received["messages"][0]["content"][0]["text"]
            assert "勾選框" in prompt, prompt[:200]
            assert r.json()["fields"]["patient_name"]["value"] == "王測試"
    finally:
        srv.shutdown()
        _clear_env(keep_env_file=False)


def test_verification_round_trip_corrects_tick_bleed():
    """端到端:整頁轉寫把相鄰兩格都判成勾選,聚焦複查把溢出那格更正回來。"""
    prompts_seen: list[str] = []

    def _app(environ, start_response):
        if environ.get("PATH_INFO") == "/v1/models":
            start_response("200 OK", [("Content-Type", "application/json")])
            return [json.dumps({"data": [{"id": "fake"}]}).encode()]

        length = int(environ.get("CONTENT_LENGTH") or 0)
        payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
        prompt = payload["messages"][0]["content"][0]["text"]
        prompts_seen.append(prompt)

        if "7.1 創傷" in prompt and "記號主體" in prompt:
            reply = "3"                      # 複查:其實只有第 3 項有勾
        elif "檢傷分類" in prompt and "記號主體" in prompt:
            reply = "3"
        elif "傷票編號" in prompt:
            reply = "SIM-20260701-001"
        else:                                 # 第一輪整頁轉寫:2 和 3 都被判成勾選
            reply = (
                "<p>1.檢傷分類:<input type='checkbox'>1 復甦急救<input type='checkbox'>2 緊急</p>"
                "<p>3.基本資料</p><p>3.3 編號:( 傷票編號 )</p>"
                "<p>7.主要初步診斷</p><p>7.1 創傷</p>"
                "<p>1 <input type='checkbox'> 撕裂傷 "
                "2 <input type='checkbox' checked> 表淺損傷 "
                "3 <input type='checkbox' checked> 鈍挫傷、拉扭傷</p>"
            )
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps({"choices": [{"message": {"content": reply}}]}).encode()]

    srv = make_server("127.0.0.1", 0, _app, handler_class=_Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.1)
    base_url = f"http://127.0.0.1:{srv.server_port}"
    _clear_env(keep_env_file=False)
    try:
        os.environ.update({
            "DMAT_ENGINE": "vision",
            "DMAT_VISION_BASE_URL": base_url,
            "DMAT_VISION_MODEL": "datalab-to/chandra-ocr-2",
            "DMAT_VERIFY": "1",
        })
        with _fresh_client() as client:
            r = client.post("/api/v1/ocr/analyze", files={"file": ("a.jpg", _photo(), "image/jpeg")})
            assert r.status_code == 200, r.text
            f = r.json()["fields"]

            assert f["trauma_contusion_sprain"]["value"] is True, f["trauma_contusion_sprain"]
            assert f["trauma_superficial_injury"]["value"] is False, "溢出那格應被複查更正"
            assert f["triage"]["value"] == "3", f["triage"]
            assert f["patient_tag_id"]["value"] == "SIM-20260701-001", f["patient_tag_id"]

            stages = [s for s in r.json()["stages"] if s["stage"] == "verify"]
            assert stages, "應該有複查階段"
            assert all(s.get("applied") for s in stages), stages
    finally:
        srv.shutdown()
        _clear_env(keep_env_file=False)


def test_verification_can_be_disabled():
    """DMAT_VERIFY=0 時不得發出額外推論請求(現場想省時間時可關閉)。"""
    calls: list[str] = []

    def _app(environ, start_response):
        if environ.get("PATH_INFO") == "/v1/models":
            start_response("200 OK", [("Content-Type", "application/json")])
            return [json.dumps({"data": [{"id": "fake"}]}).encode()]
        length = int(environ.get("CONTENT_LENGTH") or 0)
        payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
        calls.append(payload["messages"][0]["content"][0]["text"])
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps({"choices": [{"message": {"content": "<p>姓名:王小明</p>"}}]}).encode()]

    srv = make_server("127.0.0.1", 0, _app, handler_class=_Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.1)
    _clear_env(keep_env_file=False)
    try:
        os.environ.update({
            "DMAT_ENGINE": "vision",
            "DMAT_VISION_BASE_URL": f"http://127.0.0.1:{srv.server_port}",
            "DMAT_VERIFY": "0",
        })
        with _fresh_client() as client:
            r = client.post("/api/v1/ocr/analyze", files={"file": ("a.jpg", _photo(), "image/jpeg")})
            assert r.status_code == 200
            assert len(calls) == 1, f"關閉複查後只該有一次推論,實際 {len(calls)}"
    finally:
        srv.shutdown()
        _clear_env(keep_env_file=False)


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
