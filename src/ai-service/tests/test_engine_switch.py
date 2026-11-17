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


def _run_verify_concurrency(concurrency: str | None) -> tuple[int, dict, list[dict]]:
    """以「多執行緒」假端點跑一次會觸發多題複查的辨識,回傳 (同時進行的最大請求數, 欄位, 階段)。

    wsgiref 預設伺服器一次只處理一個請求,測不出併發,這裡改用 ThreadingWSGIServer;
    每題複查刻意延遲 0.4 秒,讓「同時送出」與「逐題送出」在時間上能被區分。
    """
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIServer

    class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    lock = threading.Lock()
    state = {"inflight": 0, "peak": 0}

    def _app(environ, start_response):
        if environ.get("PATH_INFO") == "/v1/models":
            start_response("200 OK", [("Content-Type", "application/json")])
            return [json.dumps({"data": [{"id": "fake"}]}).encode()]
        length = int(environ.get("CONTENT_LENGTH") or 0)
        payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
        prompt = payload["messages"][0]["content"][0]["text"]

        if "記號主體" in prompt or "傷票編號" in prompt:      # 複查題
            with lock:
                state["inflight"] += 1
                state["peak"] = max(state["peak"], state["inflight"])
            time.sleep(0.4)
            with lock:
                state["inflight"] -= 1
            if "7.1 創傷" in prompt:
                reply = "3"
            elif "檢傷分類" in prompt:
                reply = "3"
            else:
                reply = "SIM-20260701-001"
        else:                                                 # 第一輪整頁轉寫
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

    srv = make_server("127.0.0.1", 0, _app, server_class=_ThreadingWSGIServer, handler_class=_Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.1)
    _clear_env(keep_env_file=False)
    try:
        env = {
            "DMAT_ENGINE": "vision",
            "DMAT_VISION_BASE_URL": f"http://127.0.0.1:{srv.server_port}",
            "DMAT_VISION_MODEL": "datalab-to/chandra-ocr-2",
            "DMAT_VERIFY": "1",
        }
        if concurrency is not None:
            env["DMAT_VERIFY_CONCURRENCY"] = concurrency
        os.environ.update(env)
        with _fresh_client() as client:
            r = client.post("/api/v1/ocr/analyze", files={"file": ("a.jpg", _photo(), "image/jpeg")})
            assert r.status_code == 200, r.text
            return state["peak"], r.json()["fields"], r.json()["stages"]
    finally:
        srv.shutdown()
        _clear_env(keep_env_file=False)


def test_verification_questions_are_sent_concurrently():
    """複查各題應同時送出(總耗時≈最慢一題),且合併結果與逐題送出完全相同。"""
    peak, f, stages = _run_verify_concurrency(None)
    verify_stages = [s for s in stages if s["stage"] == "verify"]
    assert len(verify_stages) >= 2, f"此情境應觸發多題複查:{stages}"
    assert peak >= 2, f"複查應同時送出,實際同時進行的請求最多只有 {peak} 個"

    # 結果不因併發而改變(與 test_verification_round_trip_corrects_tick_bleed 相同的期望值)
    assert f["trauma_contusion_sprain"]["value"] is True
    assert f["trauma_superficial_injury"]["value"] is False
    assert f["triage"]["value"] == "3"
    assert f["patient_tag_id"]["value"] == "SIM-20260701-001"

    batch = [s for s in stages if s["stage"] == "verify_batch"]
    assert len(batch) == 1 and batch[0]["tasks"] == len(verify_stages), stages
    # 整批牆鐘時間應明顯小於各題相加(每題 0.4 秒)
    assert batch[0]["elapsedMs"] < sum(s["elapsedMs"] for s in verify_stages), stages


def test_verification_concurrency_can_be_limited_to_one():
    """DMAT_VERIFY_CONCURRENCY=1 時恢復逐題送出(給不支援併發的推論後端用)。"""
    peak, f, stages = _run_verify_concurrency("1")
    assert peak == 1, f"限制為 1 時不應有併發請求,實際最多 {peak} 個"
    assert f["triage"]["value"] == "3"
    assert f["trauma_superficial_injury"]["value"] is False


_FIRST_PASS_TRIAGE_UNTICKED = (
    "<p>1.檢傷分類:<input type='checkbox'>1 復甦急救<input type='checkbox'>2 緊急</p>"
    "<p>3.基本資料</p><p>3.3 編號:( 傷票編號 )</p>"
)


def _run_with_verify_reply(verify_reply: str, finish_reason: str, extra_env: dict | None = None):
    """第一輪轉寫讓檢傷分類空白(必觸發複查),複查一律回 verify_reply。

    回傳 (各請求的 max_tokens 清單[(是否複查, max_tokens)], 欄位, 階段)。
    """
    seen: list[tuple[bool, int]] = []

    def _app(environ, start_response):
        if environ.get("PATH_INFO") == "/v1/models":
            start_response("200 OK", [("Content-Type", "application/json")])
            return [json.dumps({"data": [{"id": "fake"}]}).encode()]
        length = int(environ.get("CONTENT_LENGTH") or 0)
        payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
        prompt = payload["messages"][0]["content"][0]["text"]
        is_verify = "記號主體" in prompt or "傷票編號" in prompt
        seen.append((is_verify, payload["max_tokens"]))
        if is_verify:
            body = {"choices": [{"message": {"content": verify_reply}, "finish_reason": finish_reason}]}
        else:
            body = {"choices": [{"message": {"content": _FIRST_PASS_TRIAGE_UNTICKED}, "finish_reason": "stop"}]}
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps(body).encode()]

    srv = make_server("127.0.0.1", 0, _app, handler_class=_Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.1)
    _clear_env(keep_env_file=False)
    try:
        os.environ.update({
            "DMAT_ENGINE": "vision",
            "DMAT_VISION_BASE_URL": f"http://127.0.0.1:{srv.server_port}",
            "DMAT_VISION_MODEL": "datalab-to/chandra-ocr-2",
            "DMAT_VERIFY": "1",
            **(extra_env or {}),
        })
        with _fresh_client() as client:
            r = client.post("/api/v1/ocr/analyze", files={"file": ("a.jpg", _photo(), "image/jpeg")})
            assert r.status_code == 200, r.text
            return seen, r.json()["fields"], r.json()["stages"]
    finally:
        srv.shutdown()
        _clear_env(keep_env_file=False)


def test_verify_uses_small_token_cap_but_transcription_does_not():
    """複查只回答一個選項,上限應為 DMAT_VERIFY_MAX_TOKENS(預設 128);整頁轉寫維持原本上限。"""
    seen, f, _ = _run_with_verify_reply("3", "stop")
    transcribe = [mt for is_v, mt in seen if not is_v]
    verifies = [mt for is_v, mt in seen if is_v]
    assert transcribe == [8192], seen
    assert verifies and all(mt == 128 for mt in verifies), seen
    assert f["triage"]["value"] == "3", "正常簡短的回答仍應被採用"

    seen, _, _ = _run_with_verify_reply("3", "stop", {"DMAT_VERIFY_MAX_TOKENS": "32"})
    assert all(mt == 32 for is_v, mt in seen if is_v), seen


def test_truncated_verify_answer_is_not_applied():
    """模型沒照指示、又把整頁轉寫一遍而被截斷時,不得從中硬抓數字(會抓到標題的「1.檢傷分類」)。"""
    rambling = "<p>1.檢傷分類:<input type='checkbox'>1 復甦急救 <input type='checkbox' checked>3 非緊急</p><p>3.基本"
    _, f, stages = _run_with_verify_reply(rambling, "length")

    assert f["triage"]["value"] != "1", f"不可從被截斷的長篇輸出抓出標題項次:{f['triage']}"
    triage_stage = [s for s in stages if s["stage"] == "verify" and s["target"] == "檢傷分類"]
    assert triage_stage and triage_stage[0]["truncated"] is True and triage_stage[0]["applied"] is False, stages


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
