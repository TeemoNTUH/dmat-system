"""資料合理性檢核(架構書 5.1/附錄 B):生命徵象範圍與檢傷邏輯,回傳警示清單。"""
from typing import Any

# (欄位, 下限, 上限, 名稱)
VITAL_RANGES = [
    ("temperature_c", 30.0, 45.0, "體溫"),
    ("pulse", 20, 250, "脈搏"),
    ("respiratory_rate", 4, 60, "呼吸次數"),
    ("blood_pressure_systolic", 40, 300, "收縮壓"),
    ("blood_pressure_diastolic", 20, 200, "舒張壓"),
    ("spo2_percent", 50, 100, "血氧"),
]

REQUIRED_KEYS = [("triage", "檢傷分類"), ("gender", "性別"), ("patient_tag_id", "傷票編號")]


def _num(fields: dict[str, Any], key: str):
    v = fields.get(key)
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _raw(fields: dict[str, Any], key: str):
    v = fields.get(key)
    return v.get("value") if isinstance(v, dict) else v


def validate_fields(fields: dict[str, Any]) -> list[str]:
    warnings: list[str] = []

    # 必填欄位(粗體灰底,附錄 B.3)
    for key, label in REQUIRED_KEYS:
        if _raw(fields, key) in (None, ""):
            warnings.append(f"必填欄位「{label}」缺漏,請人工確認")

    # 生命徵象合理範圍
    for key, lo, hi, label in VITAL_RANGES:
        v = _num(fields, key)
        if v is not None and not (lo <= v <= hi):
            warnings.append(f"{label} {v:g} 超出合理範圍({lo:g}~{hi:g}),請確認辨識結果")

    # 臨床警示
    sbp = _num(fields, "blood_pressure_systolic")
    if sbp is not None and sbp < 90:
        warnings.append(f"SBP {sbp:g} 低於 90,請確認休克風險")
    spo2 = _num(fields, "spo2_percent")
    if spo2 is not None and spo2 < 90:
        warnings.append(f"SpO2 {spo2:g}% 低於 90%,請確認呼吸狀態")

    # 檢傷邏輯:生命徵象明顯異常但分類為非緊急
    triage = _raw(fields, "triage")
    critical = (sbp is not None and sbp < 90) or (spo2 is not None and spo2 < 90)
    if triage == "3" and critical:
        warnings.append("生命徵象異常但檢傷分類為 3 非緊急,請確認分類")

    return warnings
