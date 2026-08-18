"""結構化規則測試。

FIXTURE 模擬 Chandra OCR 2 對「1.2 醫療記錄單」頁 1 的實際輸出風格:
表格 + <input type="checkbox" checked> 勾選狀態。內容取自架構書樣張(陳○宏)。

執行:cd src/ai-service && python -m pytest tests/ -q
      (或不裝 pytest:python tests/test_structurer.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.structurer import normalize_transcript, structure  # noqa: E402

FIXTURE = """
<div data-label="Section-Header"><h3>1.2 醫療記錄單 (1/8)</h3></div>
<div data-label="Form">
<p>檢傷分類:<input type="checkbox"> 1 復甦急救/重傷
<input type="checkbox" checked> 2 緊急/中傷
<input type="checkbox"> 3 非緊急/輕傷
<input type="checkbox"> 4 死亡
<input type="checkbox"> 4-1 緩和治療</p>
<table>
<tr><td>姓名:陳○宏</td><td>性別:<input type="checkbox" checked>男 <input type="checkbox">女</td><td>年齡:39</td></tr>
<tr><td>傷票編號:A125680363</td><td>生日:1986/6/11</td></tr>
<tr><td>身分證字號:A123456789</td><td>國籍:美國</td></tr>
</table>
<p>生命徵象</p>
<table>
<tr><td>意識:清</td><td>體溫:36.1 &deg;C</td><td>脈搏:81 次/分</td></tr>
<tr><td>呼吸次數:18</td><td>血壓:144/81 mmHg</td><td>血氧:98 %</td></tr>
</table>
<p>過去重要病史</p>
<p><input type="checkbox">懷孕 &nbsp; 疫苗:<input type="checkbox" checked>破傷風 <input type="checkbox">其他疫苗</p>
<p>過敏史:<input type="checkbox">有 &nbsp; 過敏原:</p>
<p>慢性疾病:<input type="checkbox">糖尿病 <input type="checkbox" checked>高血壓
<input type="checkbox">長期洗腎 <input type="checkbox">心衰竭 <input type="checkbox">氣喘
<input type="checkbox">慢性阻塞性肺病 <input type="checkbox">慢性病其他</p>
<p>現病史:跌倒,下肢挫傷</p>
<p>主要初步診斷</p>
<p>創傷:<input type="checkbox">1 撕裂傷 <input type="checkbox" checked>2 表淺損傷
<input type="checkbox">3 鈍挫傷、拉扭傷 <input type="checkbox">17 燒傷</p>
<p>非創傷:<input type="checkbox">1 發燒 <input type="checkbox">13 高血壓
<input type="checkbox">20 腦中風 <input type="checkbox">25 其他</p>
</div>
"""

EXPECTED = {
    "triage": "2",
    "gender": "男",
    "patient_name": "陳○宏",
    "patient_age": 39,
    "patient_tag_id": "A125680363",
    "birth_year": 1986,
    "birth_month": 6,
    "birth_day": 11,
    "national_id": "A123456789",
    "nationality": "美國",
    "consciousness": "清",
    "temperature_c": 36.1,
    "pulse": 81,
    "respiratory_rate": 18,
    "blood_pressure_systolic": 144,
    "blood_pressure_diastolic": 81,
    "spo2_percent": 98,
    "vaccine_tetanus": True,
    "chronic_disease_hypertension": True,
    "chronic_disease_diabetes": False,
    "trauma_superficial_injury": True,
    "trauma_laceration": False,
    "trauma_burn": False,
    "pregnant": False,
    "non_trauma_hypertension": False,
    "non_trauma_stroke": False,
    "present_illness_description": "跌倒,下肢挫傷",
}


def test_normalize_marks_checkboxes():
    text = normalize_transcript(FIXTURE)
    assert "☑" in text and "☐" in text
    assert "<input" not in text
    assert "&nbsp;" not in text


def test_structure_extracts_expected_fields():
    fields, evidence = structure(FIXTURE)
    failures = []
    for key, want in EXPECTED.items():
        got = fields[key]["value"]
        if isinstance(want, float):
            ok = isinstance(got, (int, float)) and abs(float(got) - want) < 0.05
        else:
            ok = got == want
        if not ok:
            failures.append(f"  {key}: 期望 {want!r} 得到 {got!r}  (證據:{evidence.get(key, '—')})")
    assert not failures, "欄位擷取不符:\n" + "\n".join(failures)


def test_missing_section_gets_zero_confidence():
    """OCR 沒讀到的項目必須是信心 0,才會被門檻推進人工覆核。"""
    fields, _ = structure("<p>姓名:王小明</p>")
    assert fields["patient_name"]["value"] == "王小明"
    assert fields["pulse"]["confidence"] == 0.0
    assert fields["trauma_burn"]["confidence"] == 0.0


def test_roc_calendar_birthdate():
    fields, _ = structure("<p>生日:民國75年6月11日</p>")
    assert fields["birth_year"]["value"] == 1986
    assert fields["birth_month"]["value"] == 6
    assert fields["birth_day"]["value"] == 11


def test_implausible_value_gets_low_confidence():
    """體溫 361(小數點漏掉)不能給高信心,必須送覆核。"""
    fields, _ = structure("<p>體溫:361</p>")
    assert fields["temperature_c"]["value"] == 361
    assert fields["temperature_c"]["confidence"] < 0.85


def test_bracket_style_checkboxes():
    """純文字轉寫(非 HTML)以 [x] / [ ] 表示勾選也要能解析。"""
    fields, _ = structure("創傷:[ ] 撕裂傷  [x] 表淺損傷  [ ] 燒傷")
    assert fields["trauma_superficial_injury"]["value"] is True
    assert fields["trauma_laceration"]["value"] is False


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except AssertionError as e:
                print(f"FAIL {name}\n{e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
