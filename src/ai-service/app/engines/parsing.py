"""模型輸出解析與正規化。

視覺模型的輸出永遠比文件承諾的髒:```json 圍欄、前後說明文字、尾隨逗號、
中文全角引號、單引號、"true"/"是" 混用、數值帶單位(「36.5 度」「81 次/分」)。
這些如果不在此收斂,最後都會變成覆核人員眼中的「辨識失敗」。
"""
from __future__ import annotations

import json
import re
from typing import Any

from .. import field_spec
from ..fields import ALL_KEYS, BOOL_KEYS, NUMBER_KEYS

_TRUE_WORDS = {"true", "1", "yes", "y", "t", "是", "有", "✓", "v", "x", "打勾", "已勾選", "勾選"}
_FALSE_WORDS = {"false", "0", "no", "n", "f", "否", "無", "空白", "未勾選", "none", "null"}

#: 從「36.5 °C」「81 次/分」「98 %」中撈出數字
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

#: 檢傷分類允許值(架構書附錄 B.3)
_TRIAGE_VALUES = {"1", "2", "3", "4", "4-1"}
_GENDER_VALUES = {"男", "女", "其他"}


class ParseError(ValueError):
    """模型輸出無法解析為 JSON。"""


def extract_json(text: str) -> dict[str, Any]:
    """從模型輸出中擷取第一個完整 JSON 物件,並容忍常見瑕疵。"""
    if not text or not text.strip():
        raise ParseError("模型沒有回傳任何內容(輸出為空)")

    cleaned = re.sub(r"```[a-zA-Z]*", "", text)

    for candidate in _candidate_objects(cleaned):
        for attempt in (candidate, _repair(candidate)):
            try:
                parsed = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

    preview = text.strip()[:300].replace("\n", " ")
    raise ParseError(f"模型輸出中找不到可解析的 JSON 物件。開頭內容:{preview}")


def _candidate_objects(text: str) -> list[str]:
    """依大括號配對切出所有頂層 JSON 物件候選(字串內的大括號不計)。"""
    out: list[str] = []
    depth = 0
    start = -1
    in_str = False
    escaped = False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    out.append(text[start : i + 1])
    if depth > 0 and start >= 0:
        # 輸出被 max_tokens 截斷:把未閉合的括號補上再試一次
        out.append(text[start:] + "}" * depth)
    return out


def _repair(candidate: str) -> str:
    """修掉全角引號、單引號鍵值、尾隨逗號等常見瑕疵。"""
    s = candidate
    s = s.replace("“", '"').replace("”", '"').replace("‘", '"').replace("’", '"')
    s = s.replace("：", ":").replace(",", ",")
    s = re.sub(r"'([^'\n]*)'\s*:", r'"\1":', s)          # 'key': → "key":
    s = re.sub(r":\s*'([^'\n]*)'", r': "\1"', s)          # : 'val' → : "val"
    s = re.sub(r",(\s*[}\]])", r"\1", s)                  # 尾隨逗號
    s = re.sub(r"\bNone\b", "null", s)
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    return s


def normalize(raw: dict[str, Any], default_confidence: float = 0.5) -> dict[str, Any]:
    """補齊缺漏欄位、統一 {value, confidence} 形狀並做型別收斂。

    缺漏欄位信心給 0,確保一定進入人工覆核佇列(架構書 4.1)。
    """
    # 模型有時會把欄位包在 {"fields": {...}} 或 {"data": {...}} 裡
    for wrapper in ("fields", "data", "result", "欄位"):
        if wrapper in raw and isinstance(raw[wrapper], dict) and not _looks_like_fields(raw):
            raw = raw[wrapper]
            break

    lowered = {str(k).strip().lower(): v for k, v in raw.items()}

    fields: dict[str, Any] = {}
    for key in ALL_KEYS:
        entry = lowered.get(key)
        value, conf = _unpack(entry, default_confidence)
        value = _coerce(key, value)
        if value is None and key in BOOL_KEYS:
            value = False
        if entry is None:
            conf = 0.0

        # 套用與兩階段路徑相同的欄位規格(型別/範圍/格式/長度)。
        # 模型自報的信心分數不足採信 —— 它可能很有把握地填了一個超出範圍的值。
        value, ok = field_spec.validate(key, value)
        if not ok:
            conf = min(conf, 0.2)

        fields[key] = {"value": value, "confidence": round(max(0.0, min(1.0, conf)), 3)}
    return fields


def _looks_like_fields(raw: dict[str, Any]) -> bool:
    """判斷這層字典本身是否已經是欄位表(避免誤拆 wrapper)。"""
    keys = {str(k).strip().lower() for k in raw}
    return len(keys & set(ALL_KEYS)) >= 3


def _unpack(entry: Any, default_confidence: float) -> tuple[Any, float]:
    if entry is None:
        return None, 0.0
    if isinstance(entry, dict):
        if "value" in entry:
            conf = entry.get("confidence", entry.get("conf", default_confidence))
            try:
                conf = float(conf)
            except (TypeError, ValueError):
                conf = default_confidence
            return entry.get("value"), conf
        return None, 0.0
    # 模型只給了裸值,沒附信心分數:視為中低信心,交由門檻推進覆核
    return entry, default_confidence


def _coerce(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in ("", "-", "—", "N/A", "n/a", "無資料", "未填", "null", "None"):
            return False if key in BOOL_KEYS else None

    if key in BOOL_KEYS:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        token = str(value).strip().lower()
        if token in _TRUE_WORDS:
            return True
        if token in _FALSE_WORDS:
            return False
        return bool(token)  # 有寫東西就當作有勾

    if key in NUMBER_KEYS:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            num = float(value)
        else:
            m = _NUM_RE.search(str(value))
            if not m:
                return None
            num = float(m.group())
        return num if key == "temperature_c" else _to_int_if_whole(num)

    text = str(value)
    if key == "triage":
        token = text.replace(" ", "").replace("級", "").replace("類", "")
        return token if token in _TRIAGE_VALUES else text
    if key == "gender":
        for g in _GENDER_VALUES:
            if g in text:
                return g
        return text
    return text


def _to_int_if_whole(num: float) -> Any:
    return int(num) if float(num).is_integer() else num
