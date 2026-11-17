"""驗證 AI 服務能「同時」處理多張影像(Web 端 AiService:Concurrency > 1 的前提)。

以真的 uvicorn 啟動服務、接上會延遲回應的假推論端點,同時送出 3 張影像:
若服務內部有任何地方把請求串行化(例如同步前處理卡住事件迴圈),
假端點同時收到的請求數就會小於 3,總耗時也會接近 3 倍。

執行:cd src/ai-service && python -m pytest tests/test_concurrent_requests.py
"""
from __future__ import annotations

import concurrent.futures
import importlib
import io
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

DELAY_S = 0.8


class _Quiet(WSGIRequestHandler):
    def log_message(self, *a):  # noqa: D102
        pass


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def _photo() -> bytes:
    im = Image.new("RGB", (1800, 2400), "white")      # 夠大,前處理會真的縮放與重新壓縮
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    return buf.getvalue()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_three_images_are_processed_concurrently():
    lock = threading.Lock()
    state = {"inflight": 0, "peak": 0}

    def _fake_vllm(environ, start_response):
        if environ.get("PATH_INFO") == "/v1/models":
            start_response("200 OK", [("Content-Type", "application/json")])
            return [json.dumps({"data": [{"id": "fake"}]}).encode()]
        environ["wsgi.input"].read(int(environ.get("CONTENT_LENGTH") or 0))
        with lock:
            state["inflight"] += 1
            state["peak"] = max(state["peak"], state["inflight"])
        time.sleep(DELAY_S)
        with lock:
            state["inflight"] -= 1
        body = {"choices": [{"message": {"content": "<p>姓名:王測試</p>"}, "finish_reason": "stop"}]}
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps(body).encode()]

    vllm = make_server("127.0.0.1", 0, _fake_vllm, server_class=_ThreadingWSGIServer, handler_class=_Quiet)
    threading.Thread(target=vllm.serve_forever, daemon=True).start()

    for k in [k for k in os.environ if k.startswith("DMAT_")]:
        os.environ.pop(k)
    os.environ.update({
        "DMAT_ENGINE": "vision",
        "DMAT_VISION_BASE_URL": f"http://127.0.0.1:{vllm.server_port}",
        "DMAT_VERIFY": "0",
        "DMAT_ENV_FILE": "/nonexistent-dmat-test.env",
    })

    import uvicorn

    for mod in [m for m in list(sys.modules) if m.startswith("app")]:
        del sys.modules[mod]
    main = importlib.import_module("app.main")
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "uvicorn 未啟動"

        photo = _photo()

        def post(_):
            with httpx.Client(timeout=30, trust_env=False) as c:
                r = c.post(f"http://127.0.0.1:{port}/api/v1/ocr/analyze",
                           files={"file": ("a.jpg", photo, "image/jpeg")})
                assert r.status_code == 200, r.text
                return r.json()

        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(3) as ex:
            results = list(ex.map(post, range(3)))
        elapsed = time.perf_counter() - t0

        assert all(r["fields"] for r in results)
        assert state["peak"] == 3, f"3 張應同時送到推論端,實際同時最多 {state['peak']} 張"
        assert elapsed < DELAY_S * 2, f"同時處理 3 張應約 {DELAY_S}s,實際 {elapsed:.2f}s(接近串行)"
    finally:
        server.should_exit = True
        vllm.shutdown()
        for k in [k for k in os.environ if k.startswith("DMAT_")]:
            os.environ.pop(k)
