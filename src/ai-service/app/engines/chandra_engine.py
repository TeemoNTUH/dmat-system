"""【已合併】Chandra 引擎已一般化為 ``vision_engine.VisionEngine``。

原本此模組只支援「單階段、直接要模型吐欄位 JSON」的做法。實務上 OCR 專用模型
在自訂 schema 的指令跟隨上不穩定,因此改為預設兩階段(轉寫 → 規則結構化),
並讓端點/模型名稱完全可組態,以支援 vLLM、SGLang、llama.cpp、Ollama。

``DMAT_ENGINE=chandra`` 仍可用,為 ``vision`` 的別名。保留此檔僅為相容舊 import。
"""
from .vision_engine import VisionEngine

#: 舊名稱別名
ChandraEngine = VisionEngine

__all__ = ["ChandraEngine", "VisionEngine"]
