"""欄位規格:辨識結果的單一事實來源(對應 damt_db_fields.xlsx Field_Map)。

**為什麼需要這一層**

只靠「找到標籤就把後面的字抓走」會出現欄位互相污染:
標籤 `過敏` 會命中 `過敏史` 的前兩個字、值會跨過表格儲存格吃到隔壁欄的內容、
體溫欄位可能收到 `36.1 脈搏 81` 這種混合字串。

因此每個欄位在此宣告它「長什麼樣」,擷取與驗證都以本檔為準:

- ``kind``     型別:text / int / float / bool
- ``section``  應出現在紀錄單的哪個區塊(用於候選評分,不做硬性排除)
- ``allowed``  允許值集合(如檢傷分類只能是 1/2/3/4/4-1)
- ``lo``/``hi`` 數值合理範圍
- ``pattern``  格式樣式(如身分證字號)
- ``max_len``  文字長度上限,超過通常代表吃到了隔壁欄位

驗證不通過的值不會被當成「辨識成功」放行,而是降為低信心或直接留空,
強制進入人工覆核(架構書 4.1)—— 錯的資料比空白更危險。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .fields import ALL_KEYS, BOOL_KEYS, NUMBER_KEYS

# --- 紀錄單區塊 -------------------------------------------------------------
SEC_TRIAGE = "檢傷分類"
SEC_BASIC = "基本資料"
SEC_VITAL = "生命徵象"
SEC_HISTORY = "過去重要病史"
SEC_ILLNESS = "現病史"
SEC_TRAUMA = "創傷"
SEC_NON_TRAUMA = "非創傷"

#: 區塊標題在轉寫中可能出現的字樣(用於判斷某段文字落在哪一區)
SECTION_MARKERS: dict[str, tuple[str, ...]] = {
    SEC_TRIAGE: ("檢傷分類", "檢傷"),
    SEC_BASIC: ("基本資料", "傷患資料", "個案資料"),
    SEC_VITAL: ("生命徵象", "生命跡象", "評估"),
    SEC_HISTORY: ("過去重要病史", "過去病史", "重要病史", "慢性疾病", "疫苗", "過敏史"),
    SEC_ILLNESS: ("現病史", "主訴"),
    SEC_TRAUMA: ("創傷",),
    SEC_NON_TRAUMA: ("非創傷",),
}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str                              # text / int / float / bool
    labels: tuple[str, ...] = ()           # 值欄位的標籤同義詞
    section: str | None = None
    allowed: tuple[str, ...] = ()          # text:允許值
    lo: float | None = None                # 數值下限
    hi: float | None = None                # 數值上限
    pattern: str | None = None             # text:格式樣式
    max_len: int = 40
    #: 值中若出現這些字樣,代表吃到了別的欄位 → 判定無效
    forbid: tuple[str, ...] = field(default_factory=tuple)
    #: 自由敘述欄位(現病史、過敏原、其他說明)。
    #: 這類欄位的內容本來就會包含診斷名稱 ——「跌倒,下肢挫傷」裡的「挫傷」
    #: 同時也是勾選項目的名稱。若照一般欄位在診斷名稱上截斷,敘述會被切掉半句。
    #: 因此自由敘述只截在「其他值欄位的標籤」與通用的「中文+冒號」樣式上。
    free_text: bool = False
    #: 括號內容屬於值的一部分,不可當成印刷註記剝除。
    #: 意識欄的「15(E4V5M6)」就是這種情況 —— 括號裡是 GCS 分項,不是表格上的說明字。
    keep_parens: bool = False

    def is_number(self) -> bool:
        return self.kind in ("int", "float")


# --- 值欄位規格 -------------------------------------------------------------
# labels 由長到短排列;比對時長標籤優先,避免「過敏」搶走「過敏史」的位置。
_VALUE_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("triage", "text", ("檢傷分類", "檢傷"), SEC_TRIAGE,
              allowed=("1", "2", "3", "4", "4-1"), max_len=4),
    FieldSpec("gender", "text", ("性別",), SEC_BASIC,
              allowed=("男", "女", "其他"), max_len=2),
    FieldSpec("patient_name", "text", ("傷患姓名", "病患姓名", "姓名"), SEC_BASIC,
              pattern=r"^[^\d:：|]{1,20}$", max_len=20,
              forbid=("性別", "年齡", "編號", "生日", "身分證")),
    FieldSpec("patient_age", "int", ("年齡", "歲數"), SEC_BASIC, lo=0, hi=130),
    FieldSpec("patient_tag_id", "text", ("傷票編號", "傷票號碼", "病歷號", "編號"), SEC_BASIC,
              pattern=r"^[A-Za-z0-9\-]{3,30}$", max_len=30),
    FieldSpec("birth_year", "int", ("生日", "出生年月日", "出生日期", "出生"), SEC_BASIC, lo=1890, hi=2035),
    FieldSpec("birth_month", "int", ("生日", "出生年月日", "出生日期", "出生"), SEC_BASIC, lo=1, hi=12),
    FieldSpec("birth_day", "int", ("生日", "出生年月日", "出生日期", "出生"), SEC_BASIC, lo=1, hi=31),
    # 身分證字號格式固定為「1 個英文字母 + 9 個數字」。OCR 很容易漏掉開頭那個字母
    # (手寫的 F 貼著格線時尤其明顯),因此格式檢查不可放寬 —— 少一碼的號碼不能當成有效值。
    FieldSpec("national_id", "text", ("身分證字號", "身份證字號", "身分證號", "身份證號", "統一證號"),
              SEC_BASIC, pattern=r"^[A-Za-z][0-9]{9}$", max_len=10),
    FieldSpec("nationality", "text", ("國籍",), SEC_BASIC,
              pattern=r"^[^\d:：|]{1,10}$", max_len=10),

    # 意識欄位在實務上有三種填法:
    #   AVPU(清/聲/痛/無)、GCS 總分(3~15)、GCS 總分 + EVM 分項(15(E4V5M6))。
    # EVM 分項是臨床判讀的重要依據(同樣是 8 分,E1V1M6 與 E2V3M3 的意義差很多),
    # 所以括號內容要完整保留,不可當成印刷註記剝掉。
    FieldSpec("consciousness", "text", ("意識狀態", "意識程度", "意識"), SEC_VITAL,
              pattern=r"^(清|聲|痛|無|(?:[3-9]|1[0-5])(?:\s*\(E\d+V\d+M\d+\))?|E\d+V\d+M\d+)$",
              max_len=20, keep_parens=True),
    FieldSpec("temperature_c", "float", ("體溫", "耳溫", "TEMP", "T"), SEC_VITAL, lo=30, hi=45),
    FieldSpec("pulse", "int", ("脈搏", "心跳", "PULSE", "HR", "P"), SEC_VITAL, lo=20, hi=250),
    FieldSpec("respiratory_rate", "int", ("呼吸次數", "呼吸速率", "呼吸", "RR", "R"), SEC_VITAL, lo=4, hi=60),
    FieldSpec("blood_pressure_systolic", "int", ("血壓", "BP"), SEC_VITAL, lo=40, hi=300),
    FieldSpec("blood_pressure_diastolic", "int", ("血壓", "BP"), SEC_VITAL, lo=20, hi=200),
    FieldSpec("spo2_percent", "int", ("血氧濃度", "血氧", "SPO2", "SAO2"), SEC_VITAL, lo=50, hi=100),

    FieldSpec("vaccine_other_note", "text", ("其他疫苗", "疫苗其他"), SEC_HISTORY,
              max_len=30, free_text=True),
    FieldSpec("allergy_note", "text", ("過敏原", "過敏史說明"), SEC_HISTORY,
              max_len=40, free_text=True),
    FieldSpec("chronic_disease_other_note", "text", ("其他慢性疾病", "慢性病其他"), SEC_HISTORY,
              max_len=40, free_text=True),
    FieldSpec("present_illness_description", "text", ("現病史", "現在病史", "主訴"), SEC_ILLNESS,
              max_len=200, free_text=True),
    FieldSpec("non_trauma_other_note", "text", ("非創傷其他", "其他內科"), SEC_NON_TRAUMA,
              max_len=40, free_text=True),
)

VALUE_SPECS: dict[str, FieldSpec] = {s.key: s for s in _VALUE_SPECS}


def spec_for(key: str) -> FieldSpec:
    """取得欄位規格;勾選框欄位動態產生 bool 規格。"""
    if key in VALUE_SPECS:
        return VALUE_SPECS[key]
    if key in BOOL_KEYS:
        return FieldSpec(key, "bool")
    if key in NUMBER_KEYS:
        return FieldSpec(key, "int")
    return FieldSpec(key, "text")


#: 所有已知標籤(含勾選框項目名稱),用於「標籤完整性」判斷 ——
#: 比對到的標籤若其實是某個更長標籤的一部分,就不算命中。
def _all_known_labels() -> tuple[str, ...]:
    from .structurer import CHECKBOX_LABELS  # 延遲匯入,避免循環相依

    labels: set[str] = set()
    for s in _VALUE_SPECS:
        labels.update(s.labels)
    for names in CHECKBOX_LABELS.values():
        labels.update(names)
    # 區塊標題(「4.生命徵象」「5.現病史」…)也算標籤:它們是表格的結構文字,
    # 永遠不可能是某個欄位的值。不納入的話,某欄空白時「下一格/下一行」的
    # 退路會把緊接其後的標題抓來當值 —— 國籍讀成「4.生命徵象」就是這樣來的。
    for markers in SECTION_MARKERS.values():
        labels.update(markers)
    return tuple(sorted(labels, key=len, reverse=True))


_KNOWN_LABELS_CACHE: tuple[str, ...] | None = None


def known_labels() -> tuple[str, ...]:
    global _KNOWN_LABELS_CACHE
    if _KNOWN_LABELS_CACHE is None:
        _KNOWN_LABELS_CACHE = _all_known_labels()
    return _KNOWN_LABELS_CACHE


_VALUE_LABELS_CACHE: tuple[str, ...] | None = None


def value_labels() -> tuple[str, ...]:
    """只含「值欄位」的標籤,不含勾選項目名稱。

    自由敘述欄位截斷時要用這一份 —— 用完整版會把「下肢挫傷」切在「挫傷」上。
    """
    global _VALUE_LABELS_CACHE
    if _VALUE_LABELS_CACHE is None:
        labels: set[str] = set()
        for s in _VALUE_SPECS:
            labels.update(s.labels)
        _VALUE_LABELS_CACHE = tuple(sorted(labels, key=len, reverse=True))
    return _VALUE_LABELS_CACHE


def trim_labels(key: str) -> tuple[str, ...]:
    """擷取該欄位的值時,應該在哪些「裸標籤」上截斷。

    自由敘述欄位回傳空集合:病情描述裡出現「意識躁動」「體溫偏高」是正常敘述,
    不是下一個欄位的標籤。這類欄位改為只截在「標籤 + 冒號」的通用樣式上,
    再加上儲存格與列邊界保護,已足以避免污染。
    """
    return () if spec_for(key).free_text else known_labels()


# --- 印刷註記 ---------------------------------------------------------------
# 紀錄單的印刷標籤自帶括號註記,例如:
#   「3.3 編號:( 傷票編號 )」「3.5 身分證字號:(選填)」「3.6 國籍(非本國籍)」
#   「檢傷分類(必填)」「4-1 緩和治療(建議醫師填寫)」
# 這些是表格上印好的說明文字,不是使用者填的值。若不剝掉,覆核畫面就會出現
# 「(選填) 69281」「(非本」「)」這種來自印刷字的垃圾值。
_PAREN_RE = re.compile(r"[(（][^)）]*[)）]")

#: 即使沒有括號也應視為印刷註記的字樣
ANNOTATION_WORDS = (
    "必填", "選填", "傷票編號", "非本國籍", "建議醫師填寫", "可複選",
    "可勾選下面選項", "粗體", "灰色網底",
)


def strip_annotations(text: str) -> str:
    """移除印刷註記,回傳真正屬於「使用者填寫」的部分。"""
    s = _PAREN_RE.sub(" ", text)
    for word in ANNOTATION_WORDS:
        s = s.replace(word, " ")
    # 括號沒閉合時(OCR 常見),把殘留的單邊括號與其後文字一併去掉
    s = re.sub(r"[(（][^)）]*$", " ", s)
    s = re.sub(r"^[^(（]*[)）]", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .·-—_:：=、,")


def strip_annotations_for(key: str, text: str) -> str:
    """依欄位規格決定要不要動括號。

    多數欄位的括號是表格上印好的說明(「(選填)」「( 傷票編號 )」),該剝;
    但意識欄的「(E4V5M6)」是填寫內容,剝掉就等於把臨床資訊丟了。
    """
    if not spec_for(key).keep_parens:
        return strip_annotations(text)
    s = text
    for word in ANNOTATION_WORDS:
        s = s.replace(word, " ")
    return re.sub(r"\s+", " ", s).strip(" .·-—_:：=、,")


# --- GCS(意識)---------------------------------------------------------------
_EVM_RE = re.compile(r"E\s*(\d+)\s*V\s*(\d+)\s*M\s*(\d+)", re.I)
_AVPU = ("清", "聲", "痛", "無")


def parse_consciousness(text: str) -> tuple[str | None, int | None, tuple[int, int, int] | None]:
    """解析意識欄。回傳 (AVPU字, GCS總分, (E,V,M))。

    支援「15」「E4V5M6」「15(E4V5M6)」「15 (E4 V5 M6)」等寫法。
    """
    s = (text or "").strip()
    if not s:
        return None, None, None

    for word in _AVPU:
        if word in s and not any(ch.isdigit() for ch in s):
            return word, None, None

    evm = None
    m = _EVM_RE.search(s)
    if m:
        evm = (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # 總分:取括號外的數字(避免把 E4 的 4 當成總分)
    outside = _PAREN_RE.sub(" ", s)
    if m and m.group() in outside:
        outside = outside.replace(m.group(), " ")
    tm = re.search(r"\b(1[0-5]|[3-9])\b", outside)
    total = int(tm.group()) if tm else None

    return None, total, evm


def format_consciousness(text: str) -> str:
    """正規化為統一顯示格式:「15 (E4V5M6)」;只有分項時自動補上總分。"""
    word, total, evm = parse_consciousness(text)
    if word:
        return word
    if evm and total is None:
        total = sum(evm)
    if evm:
        return f"{total} (E{evm[0]}V{evm[1]}M{evm[2]})"
    return str(total) if total is not None else (text or "").strip()


# --- 驗證 -------------------------------------------------------------------
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def validate(key: str, value: Any) -> tuple[Any, bool]:
    """依規格檢查並收斂值。

    回傳 ``(收斂後的值, 是否合規)``。不合規時值仍會回傳(供人工覆核參考),
    但呼叫端應據 ``ok=False`` 大幅降低信心分數,絕不可當成可信結果直接採用。
    """
    spec = spec_for(key)
    if value is None:
        return (False, True) if spec.kind == "bool" else (None, True)

    if spec.kind == "bool":
        return bool(value), True

    if spec.is_number():
        num = _to_number(value)
        if num is None:
            return None, False
        if spec.kind == "int":
            if float(num).is_integer():
                num = int(num)
            else:
                return num, False          # 整數欄位卻是小數 → 可疑
        if spec.lo is not None and num < spec.lo:
            return num, False
        if spec.hi is not None and num > spec.hi:
            return num, False
        return num, True

    text = str(value).strip()
    if not text:
        return None, True

    if key == "consciousness":
        return _validate_consciousness(text)

    if len(text) > spec.max_len:
        return text[: spec.max_len], False        # 過長 → 幾乎必是吃到隔壁欄位
    if any(bad in text for bad in spec.forbid):
        return text, False
    if spec.allowed and text not in spec.allowed:
        return text, False
    if spec.pattern and not re.match(spec.pattern, text):
        return text, False
    return text, True


def _validate_consciousness(text: str) -> tuple[Any, bool]:
    """意識欄驗證,含 GCS 一致性檢核。

    GCS 有個很好用的性質:**總分必定等於 E+V+M**。兩者不符就代表其中一項被誤讀
    (手寫的 4 和 9、1 和 7 很容易混),不需要再看影像就能斷定有問題。
    這是免費的 OCR 錯誤偵測 —— 不符即降信心送覆核。

    各分項也有上限:E≤4、V≤5、M≤6。
    """
    word, total, evm = parse_consciousness(text)
    if word:
        return word, True

    if evm:
        e, v, m = evm
        formatted = format_consciousness(text)
        if not (1 <= e <= 4 and 1 <= v <= 5 and 1 <= m <= 6):
            return formatted, False                    # 分項超出各自上限
        if total is not None and total != e + v + m:
            return formatted, False                    # 總分與分項不符 → 必有一項誤讀
        return formatted, True

    if total is not None:
        return str(total), 3 <= total <= 15

    return text, False


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUM_RE.search(str(value))
    return float(m.group()) if m else None


def contains_foreign_label(key: str, text: str) -> bool:
    """值裡出現了「別的欄位的標籤」→ 幾乎可以斷定是跨欄位污染。

    自由敘述欄位一律不判定污染:病情描述本來就可能提到診斷名稱與生命徵象用語
    (「意識躁動」「右下肢開放性骨折」),那是內容,不是吃到別欄位。
    這類欄位靠儲存格/列邊界與長度上限把關即可。
    """
    spec = spec_for(key)
    if spec.free_text:
        return False
    own = set(spec.labels)
    for lab in known_labels():
        if len(lab) < 2 or lab in own:
            continue
        if lab in text:
            return True
    return False


__all__ = [
    "FieldSpec", "VALUE_SPECS", "SECTION_MARKERS", "spec_for", "validate",
    "known_labels", "contains_foreign_label", "ALL_KEYS",
    "SEC_TRIAGE", "SEC_BASIC", "SEC_VITAL", "SEC_HISTORY", "SEC_ILLNESS",
    "SEC_TRAUMA", "SEC_NON_TRAUMA",
]
