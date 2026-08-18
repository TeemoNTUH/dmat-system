"""NLP 結構化(架構書 5.1 第二階段):把 OCR 轉寫結果對應到紀錄單頁 1 欄位。

**為什麼採規則式而非再叫一次 LLM**

Chandra 這類 OCR 專用模型的強項是「忠實轉寫」,包含勾選框狀態
(輸出 ``<input type="checkbox" checked>``);它並不擅長依自訂 schema 直接填 JSON。
而「1.2 醫療記錄單」是格式固定的官方表單,欄位標籤與 44 項診斷名稱都是已知常數,
因此第二階段用確定性規則對應,比再賭一次 LLM 更準、更快,而且可稽核
(每個欄位都能說出是從哪段文字抓到的,對應架構書 8.4 責任追溯)。

信心分數語意:此階段的分數代表「**擷取**的確定性」,不是 OCR 的字元正確率。
標籤命中且值格式合法 → 較高;命中但值格式可疑 → 較低;找不到 → 0(必進覆核)。
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from typing import Any

from . import field_spec, verify
from .fields import ALL_KEYS, BOOL_KEYS

# --- 信心分數常數(可依現場辨識品質調整) ---------------------------------
CONF_CLEAN = 0.88        # 標籤命中,值格式合法
CONF_FUZZY = 0.62        # 標籤命中,但值格式不合預期 → 傾向送覆核
CONF_CHECKED = 0.90      # 勾選框明確為已勾選
CONF_UNCHECKED = 0.86    # 勾選框明確為未勾選
CONF_ABSENT = 0.0        # 完全找不到 → 強制覆核
CONF_INVALID = 0.20      # 抓到了但不符欄位規格 → 幾乎確定是跨欄位污染,必須覆核
CONF_ADJACENT = 0.55     # 與相鄰項目同時勾選(勾記號可能畫出格線)→ 標黃待確認


@dataclass
class Extraction:
    value: Any
    confidence: float
    evidence: str = ""
    #: 勾選框欄位:命中的勾選框在轉寫中的位置(用於偵測相鄰誤勾)
    seg_pos: int | None = None


# 值欄位的標籤同義詞已移至 app/field_spec.py。
# 刻意不在此保留第二份 —— 標籤清單一旦有兩個來源,兩邊遲早會不一致,
# 而不一致的症狀正是「欄位讀到別的欄位資料」。

# --- 勾選框欄位:項目名稱同義詞 -------------------------------------------
CHECKBOX_LABELS: dict[str, list[str]] = {
    "pregnant": ["懷孕", "妊娠"],
    "vaccine_tetanus": ["破傷風"],
    "vaccine_other": ["疫苗其他", "其他疫苗"],
    "has_allergy": ["過敏史"],
    # 慢性疾病七項
    "chronic_disease_diabetes": ["糖尿病"],
    "chronic_disease_hypertension": ["高血壓"],
    "chronic_disease_long_term_dialysis": ["長期洗腎", "洗腎", "透析"],
    "chronic_disease_heart_failure": ["心衰竭", "心臟衰竭"],
    "chronic_disease_asthma": ["氣喘"],
    "chronic_disease_copd": ["慢性阻塞性肺病", "COPD", "肺阻塞"],
    "chronic_disease_other": ["慢性病其他", "其他慢性"],
    # 創傷 19 項(架構書 7.1)
    "trauma_laceration": ["撕裂傷"],
    "trauma_superficial_injury": ["表淺損傷", "表淺傷"],
    "trauma_contusion_sprain": ["鈍挫傷", "拉扭傷", "挫傷", "扭傷"],
    "trauma_axial_fracture": ["中軸骨折"],
    "trauma_pelvic_fracture": ["骨盆骨折"],
    "trauma_closed_extremity_fracture": ["四肢閉鎖性骨折", "閉鎖性骨折"],
    "trauma_open_extremity_fracture": ["四肢開放性骨折", "開放性骨折"],
    "trauma_amputation": ["截肢"],
    "trauma_dislocation": ["脫臼"],
    "trauma_crush_injury": ["壓砸傷", "壓碎傷"],
    "trauma_mild_head_injury": ["輕度頭部外傷"],
    "trauma_moderate_severe_head_injury": ["中重度頭部外傷", "中度頭部外傷", "重度頭部外傷"],
    "trauma_spinal_cord_injury": ["脊髓損傷"],
    "trauma_hemo_pneumothorax": ["氣血胸", "血氣胸"],
    "trauma_cardiovascular_injury": ["心血管損傷"],
    "trauma_abdominal_organ_injury": ["腹部臟器損傷"],
    "trauma_burn": ["燒傷", "燙傷"],
    "trauma_environmental_emergency": ["環境急症"],
    "trauma_other_surgical": ["其他外科"],
    # 非創傷 25 項(架構書 7.2)
    "non_trauma_fever": ["發燒"],
    "non_trauma_pneumonia": ["肺炎"],
    "non_trauma_asthma_or_copd": ["氣喘或慢性阻塞性肺病", "氣喘或肺阻塞"],
    "non_trauma_acute_abdominal_pain": ["急性腹痛"],
    "non_trauma_gastroenteritis": ["腸胃炎"],
    "non_trauma_bloody_diarrhea": ["出血性腹瀉"],
    "non_trauma_upper_respiratory_infection": ["上呼吸道感染"],
    "non_trauma_urinary_tract_infection": ["泌尿道感染"],
    "non_trauma_dizziness": ["暈眩", "頭暈"],
    "non_trauma_headache": ["頭痛"],
    "non_trauma_diabetes_related": ["糖尿病相關病症", "糖尿病相關"],
    "non_trauma_gastrointestinal_bleeding": ["消化道出血", "腸胃道出血"],
    "non_trauma_hypertension": ["高血壓"],
    "non_trauma_cellulitis": ["蜂窩性組織炎"],
    "non_trauma_allergy_or_eczema": ["過敏或濕疹", "濕疹"],
    "non_trauma_other_skin_disease": ["其他皮膚病"],
    "non_trauma_acute_coronary_syndrome": ["急性冠心症"],
    "non_trauma_heart_failure": ["心衰竭", "心臟衰竭"],
    "non_trauma_respiratory_failure": ["呼吸衰竭"],
    "non_trauma_stroke": ["腦中風", "中風"],
    "non_trauma_anxiety": ["焦慮症"],
    "non_trauma_other_psychiatric_disease": ["其他精神疾病"],
    "non_trauma_poisoning": ["中毒"],
    "non_trauma_obstetric_gynecologic_emergency": ["婦產科急症"],
    "non_trauma_other": ["非創傷其他", "其他內科"],
}

# 同名項目消歧:慢性病區塊的「高血壓」與非創傷診斷的「高血壓」是不同欄位。
# 值為該欄位所屬區塊的起始標題關鍵字。
SECTION_HINTS: dict[str, list[str]] = {
    "chronic_disease_diabetes": ["慢性疾病", "過去重要病史"],
    "chronic_disease_hypertension": ["慢性疾病", "過去重要病史"],
    "chronic_disease_heart_failure": ["慢性疾病", "過去重要病史"],
    "chronic_disease_asthma": ["慢性疾病", "過去重要病史"],
    "chronic_disease_copd": ["慢性疾病", "過去重要病史"],
    "non_trauma_hypertension": ["非創傷", "初步診斷"],
    "non_trauma_heart_failure": ["非創傷", "初步診斷"],
    "non_trauma_asthma_or_copd": ["非創傷", "初步診斷"],
}

_CHECKED = "☑"
_UNCHECKED = "☐"

#: 檢傷分類允許值(架構書附錄 B.3)
_TRIAGE_VALUES = {"1", "2", "3", "4", "4-1"}

_NUM = r"-?\d+(?:\.\d+)?"

#: 全角 → 半角:僅數字、英文字母與分隔符號(中文標點保留)
_WIDTH_MAP = {
    **{0xFF10 + i: ord("0") + i for i in range(10)},
    **{0xFF21 + i: ord("A") + i for i in range(26)},
    **{0xFF41 + i: ord("a") + i for i in range(26)},
    0xFF1A: ord(":"),
    0xFF0F: ord("/"),
    0xFF0D: ord("-"),
    0xFF05: ord("%"),
    0xFF08: ord("("),
    0xFF09: ord(")"),
    0x3000: ord(" "),
}


def structure(ocr_text: str) -> tuple[dict[str, Any], dict[str, str]]:
    """把 OCR 轉寫(HTML 或純文字)結構化為欄位表。

    回傳 (fields, evidence);evidence 為欄位 → 命中的原文片段,供覆核介面說明依據。
    """
    text = normalize_transcript(ocr_text)
    fields: dict[str, Any] = {}
    evidence: dict[str, str] = {}
    extractions: dict[str, Extraction] = {}

    for key in ALL_KEYS:
        if key in BOOL_KEYS:
            ex = _extract_checkbox(text, key)
        elif key == "triage":
            ex = _extract_triage(text)
        elif key == "gender":
            ex = _extract_gender(text)
        elif key in ("birth_year", "birth_month", "birth_day"):
            ex = _extract_birth(text, key)
        elif key in ("blood_pressure_systolic", "blood_pressure_diastolic"):
            ex = _extract_bp(text, key)
        else:
            ex = _extract_value(text, key)

        # 最後一道關卡:依 field_spec 嚴格驗證。
        # 不合規的值(型別錯、超出範圍、格式不符、長度異常、含別欄位標籤)
        # 一律大幅降低信心,確保進入人工覆核,而不是以「看似成功」的樣子放行。
        value, ok = field_spec.validate(key, ex.value)
        conf = ex.confidence
        if not ok:
            conf = min(conf, CONF_INVALID)
        fields[key] = {"value": value, "confidence": round(conf, 3)}
        if ex.evidence:
            evidence[key] = ex.evidence[:120]
        extractions[key] = ex

    _flag_adjacent_checks(text, fields, evidence, extractions)
    return fields, evidence


def _flag_adjacent_checks(
    text: str,
    fields: dict[str, Any],
    evidence: dict[str, str],
    extractions: dict[str, Extraction],
) -> None:
    """相鄰的勾選框同時為「已勾選」時降低信心,標為待確認。

    現場回報:勾記號畫超出格線時,OCR 會把隔壁那格也判成勾選
    (例如只勾了「3 鈍挫傷」,卻連「2 表淺損傷」一起變成已勾選)。

    轉寫只告訴我們 checked / unchecked,看不到筆畫位置,因此**無法**從這裡
    斷定哪一個才是真的。但「相鄰兩格同時勾選」正是溢出的特徵,
    所以降低信心讓兩者都標黃、由覆核人員對照影像確認 ——
    不猜、也不靜默丟棄陽性結果(對醫療資料而言,漏掉比多問一次危險得多)。

    診斷區塊本來就可複選,因此這裡只降信心、不改值。
    """
    seg_index = {seg.pos: i for i, seg in enumerate(_segments(text))}
    checked = [
        (seg_index[ex.seg_pos], key)
        for key, ex in extractions.items()
        if ex.seg_pos is not None and ex.seg_pos in seg_index and fields[key]["value"] is True
    ]
    checked.sort()

    suspicious: set[str] = set()
    for (i1, k1), (i2, k2) in zip(checked, checked[1:]):
        if i2 - i1 == 1:                       # 轉寫中緊鄰的兩個勾選框
            suspicious.update((k1, k2))

    for key in suspicious:
        fields[key]["confidence"] = min(fields[key]["confidence"], CONF_ADJACENT)
        evidence[key] = (evidence.get(key, "") + f" ⚠{verify.ADJACENT_MARK},請對照影像確認")[:120]


# --------------------------------------------------------------------------
# 轉寫正規化
# --------------------------------------------------------------------------
def normalize_transcript(raw: str) -> str:
    """HTML → 帶勾選記號的純文字。

    ``<input type="checkbox" checked>`` → ``☑``、未勾選 → ``☐``;
    其餘標籤去除,全角轉半角以穩定數字與冒號比對。
    """
    s = raw or ""

    # 勾選框:先轉成記號,再拆標籤(順序很重要)
    def _cb(m: re.Match[str]) -> str:
        return _CHECKED if re.search(r"\bchecked\b", m.group(0), re.I) else _UNCHECKED

    s = re.sub(r"<input\b[^>]*>", _cb, s, flags=re.I)

    # 常見手寫/印刷勾選記號一律收斂為 ☑
    s = re.sub(r"\[\s*[xXvV✓✔]\s*\]", _CHECKED, s)
    s = re.sub(r"\[\s*\]", _UNCHECKED, s)
    s = s.replace("✓", _CHECKED).replace("✔", _CHECKED).replace("■", _CHECKED).replace("▣", _CHECKED)
    s = s.replace("□", _UNCHECKED).replace("▢", _UNCHECKED)

    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(?:p|div|tr|li|h[1-6]|table)>", "\n", s, flags=re.I)
    s = re.sub(r"</t[dh]>", " | ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)

    # 全角 → 半角:只轉「數字/英文/分隔符號」。
    # 中文標點(,。、)屬於內容的一部分,轉了會讓現病史等自由文字與原稿不符,故保留。
    s = s.translate(_WIDTH_MAP)

    s = re.sub(r"[ \t　]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


# --------------------------------------------------------------------------
# 各類欄位擷取
# --------------------------------------------------------------------------
def _extract_value(text: str, key: str) -> Extraction:
    """擷取值欄位。

    以往的做法是「找到標籤,把後面 60 個字抓走」,這正是欄位互相污染的來源:
    標籤可能只是更長標籤的一部分、值可能跨過表格儲存格、
    而且只取第一個命中就收工,沒機會挑更好的候選。

    現在改為:列出所有候選 → 逐一評分 → 取最高分。評分依據見 _score_candidate。
    """
    spec = field_spec.spec_for(key)
    if not spec.labels:
        return Extraction(None, CONF_ABSENT)

    best: tuple[float, Extraction] | None = None
    for label in spec.labels:                       # spec.labels 已由長到短
        for m in re.finditer(re.escape(label), text, re.I):
            if not _label_is_whole(text, m.start(), m.end(), label):
                continue                            # 只是更長標籤的一部分,不算命中
            raw_value = _value_after_label(text, m.end(), key)
            if not raw_value:
                continue
            cand = _build_candidate(key, spec, label, raw_value, m.start(), text)
            if cand is None:
                continue
            score, ex = cand
            if best is None or score > best[0]:
                best = (score, ex)

    return best[1] if best else Extraction(None, CONF_ABSENT)


def _label_is_whole(text: str, start: int, end: int, label: str) -> bool:
    """標籤完整性:命中的字串若其實屬於某個更長的已知標籤,就不算數。

    例:`過敏原` 的標籤「過敏」若命中在「過敏史」裡,抓到的會是過敏史勾選框的內容,
    這正是使用者看到「欄位讀到別的欄位資料」的典型成因。
    """
    return _occurrence_is_whole(text, start, end, field_spec.known_labels())


def _occurrence_is_whole(text: str, start: int, end: int, pool: tuple[str, ...]) -> bool:
    """text[start:end] 這次命中是否「完整」,而非某個更長詞彙的一部分。

    中文沒有詞界,`\\b` 不管用,所以必須明確檢查是否被更長的候選詞包住。
    這個判斷同時用於標籤(過敏 vs 過敏史)與區塊標題(創傷 vs 非創傷)——
    兩者都曾因為子字串誤命中而讀錯欄位。
    """
    span = end - start
    for other in pool:
        if len(other) <= span:
            continue
        lo = max(0, start - len(other) + 1)
        window = text[lo : end + len(other) - 1]
        for om in re.finditer(re.escape(other), window):
            o_start = lo + om.start()
            o_end = o_start + len(other)
            if o_start <= start and end <= o_end:
                return False
    return True


def _value_after_label(text: str, pos: int, key: str) -> str:
    """取標籤之後屬於這個欄位的文字。

    依序嘗試三個位置,都要先剝除印刷註記(見 field_spec.strip_annotations)——
    「3.3 編號:( 傷票編號 )」的括號內容是表格上印好的說明,不是填寫的值:

    1. 標籤所在的儲存格
    2. 同一列的下一格(``<td>姓名</td><td>王大明</td>`` 這種版面)
    3. 下一行(手寫值寫在印刷標籤下方,如傷票編號、現病史)

    `|` 是儲存格邊界(由 ``</td>`` 轉來),`\\n` 是列邊界。
    第 3 步有嚴格限制:下一行若以任何已知標籤開頭,就放棄 —— 那是別的欄位,
    不是本欄位的值。少抓一格,好過抓錯一格。
    """
    line_end = text.find("\n", pos)
    if line_end < 0:
        line_end = len(text)
    row = text[pos:line_end]

    cells = row.split("|")
    first = _usable(cells[0].lstrip(" :：=\t"), key)
    if first:
        return first

    # 2) 同列的下一格
    for nxt in cells[1:]:
        cand = _usable(nxt.strip(" :：=\t"), key)
        if cand:
            return cand
        if nxt.strip(" :：=\t☐☑"):   # 有實質內容卻被判定不可用 → 不再往後找
            break

    # 3) 下一行(僅在本列完全取不到值時)
    return _value_on_next_line(text, line_end, key)


def _usable(fragment: str, key: str) -> str:
    """把一格文字整理成「真正可用的值」;整格都是印刷字/節次編號時回傳空字串。

    這個判斷必須在**截斷之後**做。否則「( 傷票編號 ) 3.4 生日:…」會被當成
    「這一格有值」,等到後面截斷完才發現只剩空字串,而那時已經沒機會去看下一行了 ——
    傷票編號讀成「3.4」就是這樣來的。
    """
    cand = field_spec.strip_annotations_for(key, fragment)
    if not _has_content(cand):
        return ""
    cand = field_spec.strip_annotations_for(key, _trim_at_next_label(cand, key))
    return cand if _has_content(cand) else ""


def _value_on_next_line(text: str, line_end: int, key: str) -> str:
    """手寫值寫在印刷標籤下方時的最後嘗試。"""
    if line_end >= len(text):
        return ""
    nxt_end = text.find("\n", line_end + 1)
    if nxt_end < 0:
        nxt_end = len(text)
    line = text[line_end + 1 : nxt_end]

    for cell in line.split("|"):
        cand = _usable(cell.strip(" :：=\t"), key)
        if not cand:
            continue
        # 下一行是別的欄位 → 放棄,寧可留空讓人工覆核
        if _starts_with_known_label(cand) or _CHECKED in cell or _UNCHECKED in cell:
            return ""
        return cand
    return ""


def _starts_with_known_label(s: str) -> bool:
    head = s.lstrip(" 0-9.、")
    return any(head.startswith(lab) for lab in field_spec.known_labels() if len(lab) >= 2)


def _has_content(s: str) -> bool:
    return bool(s.strip(" .·-—_:：=☐☑、,\t"))


def _build_candidate(
    key: str, spec: field_spec.FieldSpec, label: str, raw: str, pos: int, text: str
) -> tuple[float, Extraction] | None:
    """把一段候選文字整理成值,並給分。回傳 None 表示這個候選不可用。"""
    chunk = field_spec.strip_annotations_for(key, _trim_at_next_label(raw, key))
    if not chunk:
        return None

    if spec.is_number():
        num = re.search(_NUM, chunk)
        if not num:
            return None
        value: Any = float(num.group())
        if spec.kind == "int" and float(value).is_integer():
            value = int(value)
    elif key == "consciousness":
        # 支援 AVPU、GCS 總分、以及「15(E4V5M6)」總分+分項三種寫法
        value = field_spec.format_consciousness(chunk)
    elif key == "national_id":
        idm = re.search(r"[A-Za-z][0-9]{9}", chunk.replace(" ", ""))
        value = idm.group().upper() if idm else chunk
    else:
        value = chunk

    score, conf = _score_candidate(key, spec, value, pos, text)
    return score, Extraction(value, conf, f"{label}:{chunk}"[:120])


def _score_candidate(
    key: str, spec: field_spec.FieldSpec, value: Any, pos: int, text: str
) -> tuple[float, float]:
    """候選評分 → (分數, 信心)。分數只用於挑選,信心才是輸出給覆核介面的值。"""
    score = 1.0
    _, valid = field_spec.validate(key, value)

    if valid:
        score += 3.0
    if spec.section and _section_at(text, pos) == spec.section:
        score += 2.0                                   # 落在正確區塊
    if isinstance(value, str) and field_spec.contains_foreign_label(key, value):
        score -= 3.0                                   # 值裡混進別欄位的標籤
        valid = False

    conf = CONF_CLEAN if valid else CONF_FUZZY
    return score, conf


#: 節次編號樣式:1~3 段數字,以點或連字號相接,可帶結尾的點(4. / 3.2 / 4-1)。
#: 後方必須是中文才有意義 —— 純數字後接數字是量測值,不是編號。
_SECT_NO_RE = re.compile(r"\d+(?:[.\-]\d+)*\.?(?=\s*[\u4e00-\u9fff])")


def _trim_at_next_label(chunk: str, key: str) -> str:
    """值常與下一個標籤同格,遇到標籤樣式就截斷。

    除了已知標籤,也截在「中文字 + 冒號」這種通用標籤樣式上 ——
    表單上沒被我們列進字典的欄位同樣會造成污染。

    截斷用的標籤清單依欄位而異(見 field_spec.trim_labels):自由敘述欄位
    不在診斷名稱上截斷,否則「跌倒,下肢挫傷」會被切成「跌倒,下肢」。
    """
    cut = len(chunk)
    generic = re.search(r"[\u4e00-\u9fff]{2,6}\s*[:：]", chunk)
    if generic:
        cut = min(cut, generic.start())

    # 表單的節次編號(4.、3.2、7.1、4-1)同樣代表「下一個欄位開始了」。
    # 「3.1 姓名:陳柏厚 3.2 年齡 42」若只截在「年齡」,姓名會變成「陳柏厚 3.2」。
    #
    # 判定條件有兩個,缺一不可:
    #   (1) 數字本身帶分隔符(點或連字號)—— 純數字是值,不是節次編號。
    #       否則「年齡 42 性別:男」會截在 42 前面,年齡就整個消失。
    #   (2) 後面緊接的是**已知標籤或區塊標題**,而不是任何中文字。
    #       舊版只要求「後接中文」,結果體溫「36.7度C」被當成節次編號從頭截掉,
    #       體溫永遠讀不到 —— 單位是中文字這件事,舊規則沒有考慮到。
    if not field_spec.spec_for(key).free_text:
        for m in _SECT_NO_RE.finditer(chunk):
            if not any(sep in m.group() for sep in ".-"):
                continue
            if _starts_with_known_label(chunk[m.end():]):
                cut = min(cut, m.start())
                break

    for lab in field_spec.trim_labels(key):
        if len(lab) < 2:
            continue
        idx = chunk.find(lab)
        if 0 <= idx < cut:
            cut = idx
    return chunk[:cut].strip(" .·-—_:：=☐☑")


def _section_at(text: str, pos: int) -> str | None:
    """判斷位置 pos 落在紀錄單的哪個區塊(取其之前最後一個完整出現的區塊標題)。"""
    all_markers = tuple(
        m for markers in field_spec.SECTION_MARKERS.values() for m in markers
    )
    best_at, best_sec = -1, None
    head = text[:pos]
    for sec, markers in field_spec.SECTION_MARKERS.items():
        for marker in markers:
            for m in re.finditer(re.escape(marker), head):
                if not _occurrence_is_whole(text, m.start(), m.end(), all_markers):
                    continue
                if m.start() > best_at:
                    best_at, best_sec = m.start(), sec
    return best_sec


def _plausible(key: str, value: float) -> bool:
    """數值合理性一律問 field_spec,不在此另立一份範圍表。"""
    _, ok = field_spec.validate(key, value)
    return ok


#: 檢傷分類選項。「非緊急」字面含「緊急」,故關鍵字比對必須先長後短;
#: 但實際優先採用選項前方的項次數字,最可靠。
_TRIAGE_OPTIONS = [
    ("4-1", ["緩和治療", "緩和"]),
    ("3", ["非緊急", "輕傷", "綠"]),
    ("1", ["復甦急救", "重傷", "紅"]),
    ("2", ["緊急", "中傷", "黃"]),
    ("4", ["死亡", "黑"]),
]


def _extract_triage(text: str) -> Extraction:
    """檢傷分類:**單選**欄位,蒐集所有被勾選的候選後再判斷。

    舊做法是「取第一個勾選的段落」,只要 OCR 多勾一格就直接讀錯 ——
    而檢傷分類錯誤會直接影響後送優先序,是本表最不能錯的欄位。
    因此改為:恰好一個候選才給高信心;多於一個代表 OCR 判讀有疑慮,
    降信心並標記,交由第三階段聚焦複查(見 app/verify.py)。
    """
    candidates: list[tuple[str, str]] = []      # (代碼, 證據)
    for seg in _segments(text):
        if not seg.checked:
            continue
        code = None
        m = re.match(r"\s*(4\s*-\s*1|[1-4])(?![\d])", seg.text)
        if m and m.group(1).replace(" ", "") in _TRIAGE_VALUES:
            code = m.group(1).replace(" ", "")
        else:
            for c, names in _TRIAGE_OPTIONS:
                if any(n in seg.text for n in names):
                    code = c
                    break
        if code and not any(code == c for c, _ in candidates):
            candidates.append((code, seg.text.strip()))

    if len(candidates) == 1:
        code, ev = candidates[0]
        return Extraction(code, CONF_CHECKED, f"檢傷勾選:{ev}")
    if len(candidates) > 1:
        codes = "、".join(c for c, _ in candidates)
        return Extraction(
            candidates[0][0], CONF_ADJACENT,
            f"⚠{verify.MULTI_MARK}({codes}),請對照影像確認",
        )

    m = re.search(r"檢傷(?:分類)?\s*[:：]?\s*(4-1|[1-4])", text)
    if m:
        return Extraction(m.group(1), CONF_FUZZY, m.group(0))
    return Extraction(None, CONF_ABSENT)


def _extract_gender(text: str) -> Extraction:
    for seg in _segments(text):
        if not seg.checked:
            continue
        for g in ("男", "女", "其他"):
            if g in seg.text[:6]:
                return Extraction(g, CONF_CHECKED, f"性別勾選:{seg.text.strip()}")
    m = re.search(r"性別\s*[:：]?\s*([^\n|]{0,20})", text)
    if m:
        for g in ("男", "女"):
            if g in m.group(1):
                return Extraction(g, CONF_FUZZY, m.group(0))
    return Extraction(None, CONF_ABSENT)


def _extract_birth(text: str, key: str) -> Extraction:
    """生日:支援「1986/6/11」「1986年6月11日」「民國75年6月11日」。"""
    m = re.search(r"(?:生日|出生(?:日期|年月日)?)\s*[:：]?\s*([^\n|]{0,40})", text)
    if not m:
        return Extraction(None, CONF_ABSENT)
    chunk = m.group(1)

    roc = re.search(r"民國\s*(\d{1,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})", chunk)
    if roc:
        parts = [int(roc.group(1)) + 1911, int(roc.group(2)), int(roc.group(3))]
    else:
        nums = [int(n) for n in re.findall(r"\d{1,4}", chunk)]
        if len(nums) < 3:
            return Extraction(None, CONF_ABSENT)
        parts = nums[:3]
        if parts[0] < 1900:  # 未標「民國」但顯然是民國年
            parts[0] += 1911

    value = {"birth_year": parts[0], "birth_month": parts[1], "birth_day": parts[2]}[key]
    ok = _plausible(key, value)
    return Extraction(value, CONF_CLEAN if ok else CONF_FUZZY, f"生日:{chunk.strip()}")


def _extract_bp(text: str, key: str) -> Extraction:
    m = re.search(r"血壓\s*[:：]?\s*(" + _NUM + r")\s*[/／over]{1,4}\s*(" + _NUM + r")", text, re.I)
    if not m:
        m2 = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})\s*mmHg", text, re.I)
        if not m2:
            return Extraction(None, CONF_ABSENT)
        m = m2
    sbp, dbp = int(float(m.group(1))), int(float(m.group(2)))
    value = sbp if key == "blood_pressure_systolic" else dbp
    ok = _plausible(key, value) and sbp > dbp
    return Extraction(value, CONF_CLEAN if ok else CONF_FUZZY, m.group(0))


@dataclass
class Segment:
    """一個勾選框「擁有」的文字範圍。

    紀錄單上選項是這樣排的:``☐ 1 撕裂傷  ☑ 2 表淺損傷  ☐ 3 鈍挫傷``。
    每個勾選框管到下一個勾選框(或換行)之前,因此以「區段歸屬」判斷勾選狀態,
    比用固定字元視窗前後找記號可靠得多 — 後者會把下一個項目的記號誤認成自己的。
    """

    checked: bool
    text: str
    pos: int


_MARK_RE = re.compile(f"[{_CHECKED}{_UNCHECKED}]")


def _segments(text: str, max_len: int = 40) -> list[Segment]:
    marks = list(_MARK_RE.finditer(text))
    out: list[Segment] = []
    for i, m in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        chunk = text[m.end() : stop]
        nl = chunk.find("\n")
        if nl >= 0:  # 換行即換列,不跨列歸屬
            chunk = chunk[:nl]
        out.append(Segment(m.group() == _CHECKED, chunk[:max_len], m.start()))
    return out


#: 「有/無」對立選項欄位。紀錄單上是「過敏史:☑無、□有____」這種寫法 ——
#: 標籤後方緊接的勾選框屬於「無」,若只看「標籤後第一個勾選框」就會把
#: 明確勾選「無」讀成「有」,這是會直接影響臨床判斷的錯誤。
NEGATION_OPTIONS: dict[str, tuple[str, str]] = {
    "has_allergy": ("有", "無"),
    "pregnant": ("有", "無"),
}


def _extract_negation_pair(text: str, key: str, labels: list[str]) -> Extraction | None:
    """處理「☑無、□有」版面:找出標籤附近被勾選的是「有」還是「無」。"""
    positive, negative = NEGATION_OPTIONS[key]
    for label in labels:
        for m in re.finditer(re.escape(label), text):
            window = text[m.end() : m.end() + 24]
            if "\n" in window:
                window = window[: window.index("\n")]
            if "|" in window:
                window = window[: window.index("|")]
            for seg in _segments(window, max_len=8):
                if not seg.checked:
                    continue
                head = seg.text.strip(" :：、,")[:2]
                if head.startswith(negative):
                    return Extraction(False, CONF_CHECKED, f"{label}:勾選「{negative}」")
                if head.startswith(positive):
                    return Extraction(True, CONF_CHECKED, f"{label}:勾選「{positive}」")
    return None


#: 表單上多處只印「其他」兩個字,單看字面無法分辨屬於哪一組。
#: 例:「疫苗接種:□破傷風、□其他」「慢性疾病:…、□其他」「非創傷:…25 □其他」。
#: 因此改看同一行是否出現該組的脈絡關鍵字來歸屬。
OTHER_CONTEXT: dict[str, tuple[str, ...]] = {
    "vaccine_other": ("疫苗",),
    "chronic_disease_other": ("慢性",),
    "non_trauma_other": ("非創傷", "內科"),
    "trauma_other_surgical": ("創傷", "外科"),
}


def _extract_bare_other(text: str, key: str) -> Extraction | None:
    """處理只印「其他」的勾選項:靠同行的脈絡關鍵字判斷歸屬。"""
    contexts = OTHER_CONTEXT[key]
    for seg in _segments(text):
        if not seg.text.strip(" :：、,").startswith("其他"):
            continue
        line_start = text.rfind("\n", 0, seg.pos) + 1
        line_end = text.find("\n", seg.pos)
        line = text[line_start : line_end if line_end > 0 else len(text)]
        if not any(c in line for c in contexts):
            continue
        # 「非創傷」的行也含「創傷」,需排除以免外科其他被誤判
        if key == "trauma_other_surgical" and "非創傷" in line:
            continue
        return Extraction(
            seg.checked,
            CONF_CHECKED if seg.checked else CONF_UNCHECKED,
            f"其他(脈絡:{contexts[0]}):{seg.text.strip()[:20]}",
        )
    return None


def _extract_checkbox(text: str, key: str) -> Extraction:
    labels = CHECKBOX_LABELS.get(key)
    if not labels:
        return Extraction(False, CONF_ABSENT)

    if key in NEGATION_OPTIONS:
        pair = _extract_negation_pair(text, key, labels)
        if pair is not None:
            return pair

    hints = SECTION_HINTS.get(key)
    best: Extraction | None = None

    if key in OTHER_CONTEXT:
        bare = _extract_bare_other(text, key)
        if bare is not None:
            return bare

    # 型式一(主要):勾選框在項目名稱前方 → 用區段歸屬
    for seg in _segments(text):
        if hints and not _in_section(text, seg.pos, hints):
            continue
        if not any(label in seg.text for label in labels):
            continue
        if seg.checked:
            return Extraction(True, CONF_CHECKED, seg.text.strip(), seg_pos=seg.pos)
        if best is None:
            best = Extraction(False, CONF_UNCHECKED, seg.text.strip(), seg_pos=seg.pos)
    if best:
        return best

    # 型式二:項目名稱在前、勾選框緊接在後(如「過敏史:☑有」)
    for label in labels:
        for m in re.finditer(re.escape(label), text):
            if hints and not _in_section(text, m.start(), hints):
                continue
            m2 = re.match(rf"[\s:：]{{0,4}}([{_CHECKED}{_UNCHECKED}])", text[m.end() : m.end() + 6])
            if m2:
                checked = m2.group(1) == _CHECKED
                snippet = text[m.start() : m.end() + 8].replace("\n", " ")
                return Extraction(checked, CONF_CHECKED if checked else CONF_UNCHECKED, snippet)

    # 項目名稱與勾選框都對不上 → OCR 沒讀到該區塊,不可斷言「未勾選」
    return Extraction(False, CONF_ABSENT)


#: 區塊標題。「創傷」是「非創傷」的子字串 —— 若不做完整性檢查,
#: 非創傷區塊裡的項目會被判成落在「創傷」區,診斷欄位就整片讀不到。
_SECTION_STARTS = (
    "過去重要病史", "主要初步診斷", "非創傷", "慢性疾病", "生命徵象",
    "基本資料", "檢傷分類", "現病史", "初步診斷", "創傷",
)


def _in_section(text: str, pos: int, hints: list[str]) -> bool:
    """位置 pos 是否落在 hints 任一標題之後、且下一個區塊標題之前。"""
    current = _last_section_before(text, pos, _SECTION_STARTS)
    return current in hints if current else True


def _last_section_before(text: str, pos: int, pool: tuple[str, ...]) -> str:
    """取 pos 之前最後一個「完整」出現的區塊標題。"""
    best_at, best = -1, ""
    head = text[:pos]
    for name in pool:
        for m in re.finditer(re.escape(name), head):
            if not _occurrence_is_whole(text, m.start(), m.end(), pool):
                continue
            if m.start() > best_at:
                best_at, best = m.start(), name
    return best
