"""推論引擎抽象介面:引擎(mock / Chandra via vLLM、llama.cpp / 本機 transformers)可抽換,
對 Web 應用之 REST 介面不變(架構書 5.4)。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalyzeOutput:
    """引擎辨識結果。

    ``fields``  欄位鍵 → {"value":…, "confidence":…},為 Web 端唯一依賴的內容。
    ``raw``     模型原始輸出(兩階段模式下含各階段輸出),僅供除錯用。
    ``stages``  各階段耗時、輸出長度等診斷資訊。
    """

    fields: dict[str, Any]
    raw: dict[str, str] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)


class EngineError(RuntimeError):
    """引擎推論失敗。訊息會沿 REST 介面回傳給 Web 端顯示,請寫成人看得懂的中文。"""


class OcrEngine(ABC):
    name: str = "base"

    #: 是否為模擬引擎(回傳與影像無關的假資料)。介面需據此顯示警示。
    is_mock: bool = False

    @abstractmethod
    async def analyze(self, image_bytes: bytes, content_type: str) -> AnalyzeOutput:
        """辨識紀錄單頁 1,回傳 AnalyzeOutput。失敗請拋出 EngineError。"""

    async def is_ready(self) -> bool:
        return True

    async def describe(self) -> dict[str, Any]:
        """引擎自我描述,供 /api/v1/health 回報。"""
        return {"engine": self.name, "isMock": self.is_mock, "ready": await self.is_ready()}
