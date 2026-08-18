"""模擬引擎:回傳 20260614 台大版樣張(陳○宏)之辨識結果,供介面開發與展示。

⚠️ **此引擎不會真的看你上傳的照片。** 不論上傳哪一張影像,都回傳同一組寫死的值。
若覆核畫面出現「陳○宏 / A125680363」而你拍的不是那張樣張,就是本引擎生效中 —
請改用 ``DMAT_ENGINE=vision``(vLLM/llama.cpp)或 ``DMAT_ENGINE=chandra_hf``(本機推論)。

值與信心分數對照 damt_db_fields.xlsx 之 DB_Record ground truth;
nationality 刻意給低信心分數(樣張上手寫「美國」但勾選邏輯為本國,實際辨識即有歧義),
以展示人工覆核佇列之運作。
"""
import asyncio
from typing import Any

from ..fields import ALL_KEYS, BOOL_KEYS
from .base import AnalyzeOutput, OcrEngine

_SAMPLE: dict[str, tuple[Any, float]] = {
    "triage": ("2", 0.97),
    "gender": ("男", 0.93),
    "patient_name": ("陳○宏", 0.9),
    "patient_age": (39, 0.95),
    "patient_tag_id": ("A125680363", 0.96),
    "birth_year": (1986, 0.92),
    "birth_month": (6, 0.9),
    "birth_day": (11, 0.72),          # 樣張手寫 11/14 難辨,展示待確認
    "national_id": ("A123456789", 0.9),
    "nationality": ("美國", 0.55),     # 展示低信心 → 人工覆核
    "consciousness": ("清", 0.95),
    "temperature_c": (36.1, 0.88),
    "pulse": (81, 0.9),
    "respiratory_rate": (18, 0.92),
    "blood_pressure_systolic": (144, 0.9),
    "blood_pressure_diastolic": (81, 0.88),
    "spo2_percent": (98, 0.93),
    "vaccine_tetanus": (True, 0.9),
    "present_illness_description": ("跌倒,下肢挫挫傷", 0.82),
    "trauma_superficial_injury": (True, 0.94),
}


class MockEngine(OcrEngine):
    name = "mock-engine(模擬・與上傳影像無關)"
    is_mock = True

    async def analyze(self, image_bytes: bytes, content_type: str) -> AnalyzeOutput:
        await asyncio.sleep(1.0)  # 模擬推論延遲
        fields: dict[str, Any] = {}
        for key in ALL_KEYS:
            if key in _SAMPLE:
                value, conf = _SAMPLE[key]
            elif key in BOOL_KEYS:
                value, conf = False, 0.9
            else:
                value, conf = None, 0.9
            fields[key] = {"value": value, "confidence": conf}

        return AnalyzeOutput(
            fields=fields,
            raw={"note": "模擬引擎未進行任何影像辨識,以下欄位為寫死的樣張資料。"},
            stages=[{"stage": "mock", "elapsedMs": 1000, "imageBytes": len(image_bytes)}],
        )
