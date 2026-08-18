"""引擎工廠。依組態建立推論引擎;介面固定,引擎可抽換(架構書 5.4)。"""
from .. import config
from .base import AnalyzeOutput, EngineError, OcrEngine
from .mock_engine import MockEngine

__all__ = ["AnalyzeOutput", "EngineError", "OcrEngine", "create_engine", "KNOWN_ENGINES"]

KNOWN_ENGINES = ("mock", "vision", "chandra", "chandra_hf")


def create_engine() -> OcrEngine:
    engine = config.ENGINE

    if engine in ("vision", "chandra"):
        # chandra 為 vision 的別名(保留架構書 5.4 的稱法)
        from .vision_engine import VisionEngine

        return VisionEngine()

    if engine in ("chandra_hf", "hf", "local"):
        from .chandra_hf_engine import ChandraHfEngine

        return ChandraHfEngine()

    if not config.is_mock():
        raise ValueError(f"未知的 DMAT_ENGINE「{engine}」。可用值:{', '.join(KNOWN_ENGINES)}")

    return MockEngine()
