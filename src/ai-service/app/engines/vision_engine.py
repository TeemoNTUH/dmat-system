"""通用視覺引擎:任何 OpenAI 相容的 /v1/chat/completions 視覺端點皆可(架構書 5.4)。

已驗證可用的後端:
- vLLM(GB10/DGX Spark 推薦):``vllm serve datalab-to/chandra-ocr-2 --port 8080``
- SGLang:``python -m sglang.launch_server --model-path datalab-to/chandra-ocr-2 --port 8080``
- llama.cpp:``llama-server -m chandra-ocr-2-Q4_K_M.gguf --mmproj mmproj-F16.gguf --port 8080``
- Ollama:base url 指向 ``http://localhost:11434``

兩種辨識模式(DMAT_TWO_STAGE):

1. **兩階段(預設,建議)** — 第一階段用 Chandra 原生訓練提示把整張表單轉寫為 HTML
   (含 ``<input type="checkbox" checked>`` 勾選狀態),第二階段由 ``structurer``
   以確定性規則對應到欄位。OCR 模型只做它最擅長的轉寫,結構化交給規則,可稽核。
2. **單階段** — 直接以自訂提示要求模型輸出欄位 JSON。通用 VLM(如 Qwen-VL)可行;
   OCR 專用模型的指令跟隨能力較弱,較不建議。
"""
from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from .. import config, verify
from ..structurer import structure
from .base import AnalyzeOutput, EngineError, OcrEngine
from .parsing import ParseError, extract_json, normalize

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"

#: 轉寫提示。``chandra`` 為 Chandra OCR 2 的原生訓練提示(取自 datalab-to/chandra
#: chandra/prompts.py);``generic`` 為中文指示式提示,給 Qwen2.5-VL 等通用 VLM 用。
_TRANSCRIBE_PROMPTS = {
    "chandra": (_PROMPT_DIR / "ocr_transcribe_en.md").read_text(encoding="utf-8"),
    "generic": (_PROMPT_DIR / "ocr_transcribe_generic_zh.md").read_text(encoding="utf-8"),
}

#: 單階段模式用的自訂 JSON 提示
_DIRECT_JSON_PROMPT = (_PROMPT_DIR / "page1_zh.md").read_text(encoding="utf-8")


class VisionEngine(OcrEngine):
    is_mock = False

    def __init__(self) -> None:
        mode = "兩階段" if config.TWO_STAGE else "單階段"
        self.prompt_style = config.resolve_prompt_style(config.VISION_MODEL)
        self.name = f"{config.VISION_MODEL}@{config.VISION_BASE_URL}({mode}/{self.prompt_style})"

    async def analyze(self, image_bytes: bytes, content_type: str) -> AnalyzeOutput:
        data_uri = f"data:{content_type or 'image/jpeg'};base64,{base64.b64encode(image_bytes).decode()}"
        raw: dict[str, str] = {}
        stages: list[dict[str, Any]] = []

        # trust_env=False:推論端點在本機/同區網,絕不可走 HTTP(S)_PROXY / ALL_PROXY。
        # 現場工作站若設了公司代理,連線會被導去代理而失敗(且錯誤訊息難以理解)。
        async with httpx.AsyncClient(timeout=config.VISION_TIMEOUT_S, trust_env=False) as client:
            if config.TWO_STAGE:
                t0 = time.perf_counter()
                transcript = await self._chat(client, _TRANSCRIBE_PROMPTS[self.prompt_style], data_uri)
                raw["transcript"] = transcript
                stages.append(
                    {
                        "stage": "ocr_transcribe",
                        "model": config.VISION_MODEL,
                        "promptStyle": self.prompt_style,
                        "elapsedMs": round((time.perf_counter() - t0) * 1000),
                        "chars": len(transcript),
                    }
                )
                if not transcript.strip():
                    raise EngineError("OCR 模型回傳空白轉寫結果,請確認模型已正確載入視覺投影層(mmproj)")

                t1 = time.perf_counter()
                fields, evidence = structure(transcript)
                stages.append(
                    {
                        "stage": "structure_rules",
                        "elapsedMs": round((time.perf_counter() - t1) * 1000),
                        "extracted": sum(1 for f in fields.values() if f["confidence"] > 0),
                        "evidence": evidence,
                    }
                )

                if config.VERIFY_ENABLED:
                    await self._verify(client, data_uri, fields, evidence, raw, stages)

                return AnalyzeOutput(fields=fields, raw=raw, stages=stages)

            # 單階段
            t0 = time.perf_counter()
            text = await self._chat(client, _DIRECT_JSON_PROMPT, data_uri)
            raw["json"] = text
            stages.append(
                {
                    "stage": "direct_json",
                    "model": config.VISION_MODEL,
                    "elapsedMs": round((time.perf_counter() - t0) * 1000),
                    "chars": len(text),
                }
            )
            try:
                fields = normalize(extract_json(text))
            except ParseError as exc:
                raise EngineError(
                    f"模型輸出無法解析為欄位 JSON:{exc}。"
                    "建議改用兩階段模式(DMAT_TWO_STAGE=1),OCR 專用模型較不擅長直接輸出 JSON。"
                ) from exc
            return AnalyzeOutput(fields=fields, raw=raw, stages=stages)

    async def _verify(
        self,
        client: httpx.AsyncClient,
        data_uri: str,
        fields: dict[str, Any],
        evidence: dict[str, str],
        raw: dict[str, str],
        stages: list[dict[str, Any]],
    ) -> None:
        """第三階段:對不確定的地方帶著同一張影像回頭問模型(見 app/verify.py)。

        任何一題失敗都只跳過該題 —— 複查是加分項,不能讓它拖垮整筆辨識。
        """
        tasks = verify.plan(fields, evidence, max_tasks=config.VERIFY_MAX_TASKS)
        if not tasks:
            return

        for task in tasks:
            t0 = time.perf_counter()
            try:
                answer = await self._chat(client, task.prompt, data_uri)
            except EngineError as exc:
                logger.warning("複查「%s」失敗,沿用第一輪結果:%s", task.label, exc)
                stages.append({"stage": "verify", "target": task.label, "error": str(exc)})
                continue

            applied = verify.apply(task, answer, fields, evidence)
            raw[f"verify:{task.label}"] = answer
            stages.append(
                {
                    "stage": "verify",
                    "target": task.label,
                    "kind": task.kind,
                    "elapsedMs": round((time.perf_counter() - t0) * 1000),
                    "answer": answer.strip()[:80],
                    "applied": applied,
                }
            )

    async def _chat(self, client: httpx.AsyncClient, prompt: str, data_uri: str) -> str:
        payload = {
            "model": config.VISION_MODEL,
            "temperature": config.VISION_TEMPERATURE,
            "max_tokens": config.VISION_MAX_TOKENS,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {config.VISION_API_KEY}"} if config.VISION_API_KEY else {}
        url = f"{config.VISION_BASE_URL}/v1/chat/completions"

        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.ConnectError as exc:
            raise EngineError(
                f"無法連線至推論服務 {config.VISION_BASE_URL}。"
                "請確認 vLLM / llama.cpp server 已啟動,且 DMAT_VISION_BASE_URL 設定正確。"
            ) from exc
        except httpx.TimeoutException as exc:
            raise EngineError(
                f"推論逾時({config.VISION_TIMEOUT_S:g} 秒)。"
                "可調高 DMAT_VISION_TIMEOUT_S,或縮小 DMAT_PREPROCESS_MAX_EDGE 降低影像 token 數。"
            ) from exc

        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise EngineError(f"推論服務回傳 HTTP {resp.status_code}:{detail}")

        try:
            body = resp.json()
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise EngineError(f"推論服務回應格式非預期:{resp.text[:300]}") from exc

    async def is_ready(self) -> bool:
        try:
            headers = {"Authorization": f"Bearer {config.VISION_API_KEY}"} if config.VISION_API_KEY else {}
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                resp = await client.get(f"{config.VISION_BASE_URL}/v1/models", headers=headers)
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def describe(self) -> dict[str, Any]:
        base = await super().describe()
        base.update(
            {
                "baseUrl": config.VISION_BASE_URL,
                "model": config.VISION_MODEL,
                "twoStage": config.TWO_STAGE,
                "promptStyle": self.prompt_style,
            }
        )
        return base
