"""Chandra OCR 2 本機推論引擎(HuggingFace transformers,不需另跑推論伺服器)。

適用於 DGX Spark / GB10 這類「模型與應用同機」的部署:GB10 的 128GB 統一記憶體
放得下 BF16 的 5B 模型(約 10GB),不必為了 vLLM 去處理 SM121 相容性問題。
代價是沒有 continuous batching,單張推論較慢(數十秒等級),對逐張覆核的
現場流程可接受。大量批次補傳時建議改用 ``vision`` 引擎 + vLLM。

模型載入是阻塞且耗時的,因此:
- 於背景執行緒惰性載入,不擋住 FastAPI 啟動與 /health;
- 推論以 ``run_in_executor`` 丟到執行緒池,避免卡住事件迴圈。
"""
from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .. import config
from ..structurer import structure
from .base import AnalyzeOutput, EngineError, OcrEngine

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"
_PROMPT_FILES = {
    "chandra": "ocr_transcribe_en.md",
    "generic": "ocr_transcribe_generic_zh.md",
}


class ChandraHfEngine(OcrEngine):
    is_mock = False

    def __init__(self) -> None:
        self.prompt_style = config.resolve_prompt_style(config.HF_MODEL_ID)
        self._prompt = (_PROMPT_DIR / _PROMPT_FILES[self.prompt_style]).read_text(encoding="utf-8")
        self.name = f"{config.HF_MODEL_ID}(本機 transformers・兩階段/{self.prompt_style})"
        self._model: Any = None
        self._processor: Any = None
        self._load_error: str | None = None
        self._lock = threading.Lock()
        self._loading = False
        threading.Thread(target=self._ensure_loaded, name="chandra-hf-load", daemon=True).start()

    # -- 模型載入 -----------------------------------------------------------
    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._model is not None or self._load_error:
                return
            self._loading = True
            try:
                import torch
                from transformers import AutoModelForImageTextToText, AutoProcessor

                dtype = getattr(torch, config.HF_DTYPE, torch.bfloat16)
                logger.info("載入 %s(dtype=%s, device_map=%s)…", config.HF_MODEL_ID, config.HF_DTYPE, config.HF_DEVICE_MAP)
                t0 = time.perf_counter()
                model = AutoModelForImageTextToText.from_pretrained(
                    config.HF_MODEL_ID, dtype=dtype, device_map=config.HF_DEVICE_MAP
                )
                model.eval()
                processor = AutoProcessor.from_pretrained(config.HF_MODEL_ID)
                processor.tokenizer.padding_side = "left"
                self._model, self._processor = model, processor
                logger.info("模型載入完成,耗時 %.1f 秒", time.perf_counter() - t0)
            except ImportError as exc:
                self._load_error = (
                    f"缺少本機推論相依套件({exc})。請執行:pip install 'chandra-ocr[hf]' "
                    "(DGX Spark/GB10 請先依 NVIDIA 指引安裝對應 aarch64+CUDA 的 torch)"
                )
                logger.error(self._load_error)
            except Exception as exc:  # noqa: BLE001
                self._load_error = f"模型載入失敗:{exc}"
                logger.exception("模型載入失敗")
            finally:
                self._loading = False

    # -- 推論 ---------------------------------------------------------------
    async def analyze(self, image_bytes: bytes, content_type: str) -> AnalyzeOutput:
        if self._model is None:
            self._ensure_loaded()
        if self._load_error:
            raise EngineError(self._load_error)
        if self._model is None:
            raise EngineError("模型仍在載入中,請稍候後重新辨識(可查詢 /api/v1/health)")

        loop = asyncio.get_running_loop()
        t0 = time.perf_counter()
        transcript = await loop.run_in_executor(None, self._generate, image_bytes)
        elapsed = round((time.perf_counter() - t0) * 1000)

        if not transcript.strip():
            raise EngineError("模型回傳空白轉寫結果,請確認影像是否過暗或方向錯誤")

        t1 = time.perf_counter()
        fields, evidence = structure(transcript)
        return AnalyzeOutput(
            fields=fields,
            raw={"transcript": transcript},
            stages=[
                {"stage": "ocr_transcribe", "model": config.HF_MODEL_ID, "elapsedMs": elapsed, "chars": len(transcript)},
                {
                    "stage": "structure_rules",
                    "elapsedMs": round((time.perf_counter() - t1) * 1000),
                    "extracted": sum(1 for f in fields.values() if f["confidence"] > 0),
                    "evidence": evidence,
                },
            ],
        )

    def _generate(self, image_bytes: bytes) -> str:
        import torch
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        messages = [
            {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": self._prompt}]}
        ]
        prompt_text = self._processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        inputs = self._processor(text=[prompt_text], images=[image], return_tensors="pt").to(self._model.device)

        with torch.inference_mode():
            out = self._model.generate(
                **inputs, max_new_tokens=config.HF_MAX_NEW_TOKENS, do_sample=False
            )
        generated = out[0][inputs["input_ids"].shape[-1] :]
        return self._processor.decode(generated, skip_special_tokens=True)

    async def is_ready(self) -> bool:
        return self._model is not None

    async def describe(self) -> dict[str, Any]:
        base = await super().describe()
        base.update(
            {
                "model": config.HF_MODEL_ID,
                "loading": self._loading,
                "loadError": self._load_error,
                "twoStage": True,
                "promptStyle": self.prompt_style,
            }
        )
        return base
