"""第三階段:針對性複查(架構書 5.1 之延伸)。

**為什麼需要**

整頁轉寫時,模型要同時處理上百個文字與勾選框,注意力被攤薄,於是出現:

- 勾記號畫超出格線 → 隔壁那格也被判成已勾選
- 檢傷分類這種「只能選一個」的欄位被勾成兩個
- 手寫的傷票編號夾在密集表格裡,整頁轉寫時被略過

但如果只問模型一個聚焦的問題(「這一列裡哪一個方框內有勾選記號?」),
它的判斷準確得多 —— 這是視覺模型的已知特性,不是這個專案獨有的問題。

因此本模組負責:
1. 從第一輪結果中找出「值得再問一次」的地方(``plan``)
2. 產生聚焦提示詞交給引擎執行
3. 把答案合併回欄位表(``apply``)

複查會多花一次推論時間(數十秒),所以只在真的不確定時觸發,
並以 ``DMAT_VERIFY_MAX_TASKS`` 設上限。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any

from . import field_spec
from .fields import CHRONIC_KEYS, NON_TRAUMA_KEYS, TRAUMA_KEYS

#: 勾選溢出的處置原則。使用者的要求很明確:記號主體在哪一格,就只算哪一格。
_TIE_BREAK = "若勾選記號跨在兩格之間,只算「記號主體(面積較大的部分)」所在的那一格。"

#: 結構化階段標記「與相鄰項目同時勾選」時寫進 evidence 的字樣
ADJACENT_MARK = "與相鄰項目同時勾選"

#: 單選欄位被判定為多選時的字樣
MULTI_MARK = "多個選項同時勾選"


@dataclass
class VerifyTask:
    """一次聚焦提問。"""

    kind: str                       # "single" | "multi" | "value"
    prompt: str
    keys: list[str] = dc_field(default_factory=list)
    #: multi 專用:項次 → 欄位鍵
    index_map: dict[str, str] = dc_field(default_factory=dict)
    #: single 專用:允許的答案 → 值
    choice_map: dict[str, Any] = dc_field(default_factory=dict)
    label: str = ""


# --- 診斷群組定義 -----------------------------------------------------------
_GROUPS: list[tuple[str, str, list[str]]] = [
    ("7.1 創傷", "trauma", TRAUMA_KEYS),
    ("7.2 非創傷", "non_trauma", NON_TRAUMA_KEYS),
    ("5. 慢性疾病", "chronic", CHRONIC_KEYS),
]


def _group_of(key: str) -> tuple[str, list[str]] | None:
    for title, _prefix, keys in _GROUPS:
        if key in keys:
            return title, keys
    return None


def _item_names() -> dict[str, str]:
    """欄位鍵 → 中文品項名稱(取 CHECKBOX_LABELS 的第一個同義詞)。"""
    from .structurer import CHECKBOX_LABELS

    return {k: v[0] for k, v in CHECKBOX_LABELS.items() if v}


# --- 值欄位的複查規格 -------------------------------------------------------
# 依「錯了多嚴重」排序:必填欄位在前。每一項都把**格式**明確寫進提示 ——
# 告訴模型「身分證字號是 1 個英文字母 + 9 個數字」,它就會回頭去找那個字母,
# 而不是把貼著格線的手寫 F 整個略過。
@dataclass
class ValueCheck:
    key: str
    label: str
    where: str          # 表單上的位置描述
    format_hint: str
    #: 必填欄位:空白也要問。選填欄位空白很可能本來就沒填,問了只是浪費一輪推論,
    #: 因此只在「讀到了東西但不合格式」時才複查。
    required: bool = False


_VALUE_CHECKS: tuple[ValueCheck, ...] = (
    ValueCheck(
        key="patient_tag_id",
        label="傷票編號",
        where="「3.3 編號(傷票編號)」這一格(手寫值可能寫在印刷標籤的下方)",
        format_hint="編號通常是英文字母開頭,後面接數字與連字號,例如 SIM-20260920-006。",
        required=True,
    ),
    ValueCheck(
        key="national_id",
        label="身分證字號",
        where="「3.5 身分證字號(選填)」這一格",
        format_hint=(
            "身分證字號的格式固定為「1 個大寫英文字母 + 9 個數字」,共 10 碼,例如 F692813740。\n"
            "開頭的英文字母很容易貼著格線而被漏掉,請特別確認第一個字元是不是英文字母。\n"
            "若你只看到 9 個數字,請再回頭找那個英文字母。"
        ),
    ),
    ValueCheck(
        key="patient_name",
        label="姓名",
        where="「3.1 姓名」這一格",
        format_hint="只輸出姓名本身,不要包含年齡、性別或「3.2」這類欄位編號。",
    ),
)


def _needs_value_check(check: ValueCheck, fields: dict[str, Any]) -> bool:
    item = fields.get(check.key, {})
    value = item.get("value")
    conf = item.get("confidence", 0)
    if value in (None, ""):
        return check.required          # 選填欄位空白 → 可能本來就沒填,不浪費推論
    return conf < NEEDS_CHECK_BELOW    # 讀到了但不合格式/信心不足 → 值得再問


def _value_task(check: ValueCheck) -> VerifyTask:
    return VerifyTask(
        kind="value",
        label=check.label,
        keys=[check.key],
        prompt=(
            f"這是一張「1.2 醫療記錄單」。請只看{check.where},"
            f"讀出裡面手寫的內容。\n\n"
            f"{check.format_hint}\n\n"
            "只輸出該欄位的值本身,不要輸出欄位名稱、括號註記或任何說明文字。\n"
            "若該格空白或無法辨識,只輸出 UNKNOWN。"
        ),
    )


# --- 規劃 -------------------------------------------------------------------
#: 低於此信心即視為「值得再問一次」。與 Web 端的預設門檻(0.85)一致。
NEEDS_CHECK_BELOW = 0.85


def plan(fields: dict[str, Any], evidence: dict[str, str], max_tasks: int = 4) -> list[VerifyTask]:
    """依第一輪結果決定要複查什麼。回傳的順序即執行順序(重要的先問)。"""
    tasks: list[VerifyTask] = []

    # 1) 檢傷分類:必填且單選,錯了影響後送優先序 —— 只要不確定就問
    triage = fields.get("triage", {})
    if triage.get("value") is None or triage.get("confidence", 0) < NEEDS_CHECK_BELOW \
            or MULTI_MARK in evidence.get("triage", ""):
        tasks.append(_triage_task())

    # 2) 必填的值欄位(傷票編號、姓名):缺漏或格式可疑
    for check in _VALUE_CHECKS:
        if check.required and _needs_value_check(check, fields):
            tasks.append(_value_task(check))

    # 3) 相鄰同時勾選的診斷群組 —— 診斷牽涉臨床處置,優先於選填欄位
    for title, keys in _ambiguous_groups(fields, evidence):
        tasks.append(_group_task(title, keys, fields))

    # 4) 選填的值欄位(身分證字號):只在讀到了但不合格式時才問
    for check in _VALUE_CHECKS:
        if not check.required and _needs_value_check(check, fields):
            tasks.append(_value_task(check))

    return tasks[:max_tasks]


def _triage_task() -> VerifyTask:
    return VerifyTask(
        kind="single",
        label="檢傷分類",
        keys=["triage"],
        prompt=(
            "這是一張「1.2 醫療記錄單」。請只看最上方「1.檢傷分類」那一列的五個方框:\n"
            "1 復甦急救(重傷)、2 緊急(中傷)、3 非緊急(輕傷)、4 死亡、4-1 緩和治療\n\n"
            "哪一個方框「裡面」有勾選記號?\n"
            f"{_TIE_BREAK}\n"
            "只輸出 1、2、3、4、4-1 其中一個,不要輸出其他文字。\n"
            "若五個方框都沒有勾選記號,只輸出 NONE。"
        ),
        choice_map={"1": "1", "2": "2", "3": "3", "4": "4", "4-1": "4-1"},
    )


def _ambiguous_groups(
    fields: dict[str, Any], evidence: dict[str, str]
) -> list[tuple[str, list[str]]]:
    """找出有「相鄰同時勾選」疑慮的診斷群組。"""
    out: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for key, ev in evidence.items():
        if ADJACENT_MARK not in ev:
            continue
        grp = _group_of(key)
        if grp is None or grp[0] in seen:
            continue
        seen.add(grp[0])
        out.append(grp)
    return out


def _group_task(title: str, keys: list[str], fields: dict[str, Any]) -> VerifyTask:
    names = _item_names()
    listing = "、".join(f"{i + 1} {names.get(k, k)}" for i, k in enumerate(keys))
    index_map = {str(i + 1): k for i, k in enumerate(keys)}
    return VerifyTask(
        kind="multi",
        label=title,
        keys=list(keys),
        index_map=index_map,
        prompt=(
            f"這是一張「1.2 醫療記錄單」。請只看「{title}」這個區塊的勾選欄。\n"
            f"項目依序為:{listing}\n\n"
            "哪些項目的方框「裡面」有勾選記號?\n"
            f"{_TIE_BREAK}\n"
            "只輸出項次數字,以半形逗號分隔(例如:2,7)。\n"
            "若完全沒有任何勾選,只輸出 NONE。"
        ),
    )


# --- 合併 -------------------------------------------------------------------
CONF_VERIFIED = 0.93        # 聚焦複查的結果比整頁轉寫可信
CONF_VERIFIED_NONE = 0.90


def apply(task: VerifyTask, answer: str, fields: dict[str, Any], evidence: dict[str, str]) -> bool:
    """把複查答案合併回欄位表。回傳是否真的更新了內容。"""
    text = (answer or "").strip()
    if not text:
        return False

    if task.kind == "value":
        return _apply_value(task, text, fields, evidence)
    if task.kind == "single":
        return _apply_single(task, text, fields, evidence)
    if task.kind == "multi":
        return _apply_multi(task, text, fields, evidence)
    return False


def _apply_value(task: VerifyTask, text: str, fields, evidence) -> bool:
    if "UNKNOWN" in text.upper():
        return False
    # 模型可能多話,取第一行、去掉引號與說明
    line = text.strip().splitlines()[0].strip(" 「」\"'。:：")
    line = field_spec.strip_annotations(line)
    if not line:
        return False
    key = task.keys[0]
    value, ok = field_spec.validate(key, line)
    if not ok:
        return False
    fields[key] = {"value": value, "confidence": CONF_VERIFIED}
    evidence[key] = f"複查({task.label}):{line}"[:120]
    return True


def _apply_single(task: VerifyTask, text: str, fields, evidence) -> bool:
    if "NONE" in text.upper():
        return False
    m = re.search(r"4\s*-\s*1|[1-4]", text)
    if not m:
        return False
    choice = m.group().replace(" ", "")
    if choice not in task.choice_map:
        return False
    key = task.keys[0]
    fields[key] = {"value": task.choice_map[choice], "confidence": CONF_VERIFIED}
    evidence[key] = f"複查({task.label}):勾選 {choice}"[:120]
    return True


def _apply_multi(task: VerifyTask, text: str, fields, evidence) -> bool:
    upper = text.upper()
    if "NONE" in upper:
        picked: set[str] = set()
    else:
        picked = {n for n in re.findall(r"\d+", text) if n in task.index_map}
        if not picked:
            return False

    for idx, key in task.index_map.items():
        checked = idx in picked
        fields[key] = {
            "value": checked,
            "confidence": CONF_VERIFIED if checked else CONF_VERIFIED_NONE,
        }
        evidence[key] = f"複查({task.label}):{'已勾選' if checked else '未勾選'}"[:120]
    return True
