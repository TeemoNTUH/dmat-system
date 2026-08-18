"""以現場實際紀錄單的版面為準的回歸測試。

FIXTURE 依據 20260731 實測影像重建 —— 保留該表單真正的印刷字樣,包括:

- 標籤自帶括號註記:「3.3 編號:( 傷票編號 )」「3.5 身分證字號:(選填)」「3.6 國籍(非本國籍)」
- 手寫值寫在印刷標籤的**下一行**(傷票編號、現病史)
- 意識欄填 GCS 數字(15)而非 AVPU
- 過敏史為「☑無、□有」對立選項
- 診斷表為「項次 □ 名稱」三欄並排

這些版面特徵各自對應一次實際誤判,測試在此固定住,避免日後改規則時重蹈覆轍。

執行:cd src/ai-service && python tests/test_real_form_layout.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import field_spec  # noqa: E402
from app.structurer import structure  # noqa: E402

FIXTURE = """
<p>隊名:北區 災難醫療救護隊</p>
<h3>1.2 醫療記錄單</h3>
<p>*粗體、灰色網底為" 必填 "欄位</p>
<table>
<tr><td>1.檢傷分類:</td>
    <td><input type="checkbox">1 復甦急救(重傷) <input type="checkbox">2 緊急(中傷)
        <input type="checkbox" checked>3 非緊急(輕傷)<br>
        <input type="checkbox">4 死亡 <input type="checkbox">4-1 緩和治療(建議醫師填寫)</td>
    <td>2.性別:<input type="checkbox">男 <input type="checkbox" checked>女 <input type="checkbox">其他</td></tr>
</table>
<table>
<tr><td>3.基本資料</td>
    <td>3.1 姓名:黃怡君</td><td>3.2 年齡 31</td>
    <td>3.3 編號:( 傷票編號 )<br>SIH-20260920-006</td></tr>
<tr><td></td><td>3.4 生日:西元1995年7月19日</td></tr>
<tr><td></td><td>3.5 身分證字號:(選填) F692813740</td><td>3.6 國籍(非本國籍):</td></tr>
</table>
<table>
<tr><td>4.生命徵象</td>
    <td>意識:15 、體溫:36.6 、脈搏:78 、呼吸次數:16 、<br>
        血壓:116 / 96 mmHg、血氧:99 %</td></tr>
</table>
<table>
<tr><td>5.過去重要病史</td>
    <td><input type="checkbox">懷孕<br>
        疫苗接種:<input type="checkbox">破傷風、<input type="checkbox" checked>其他 未知<br>
        過敏史:<input type="checkbox" checked>無、<input type="checkbox">有<br>
        慢性疾病:<input type="checkbox">糖尿病、<input type="checkbox" checked>高血壓、
        <input type="checkbox">長期透析、<input type="checkbox">心衰竭、<input type="checkbox">氣喘、
        <input type="checkbox">慢性阻塞性肺病、<input type="checkbox">其他</td></tr>
</table>
<table>
<tr><td>6.現病史</td>
    <td>The simulated patient has a history of hypertension and presents today with
        dizziness and chest tightness.</td></tr>
</table>
<p>7.主要初步診斷(可勾選下面選項,可複選)</p>
<table>
<tr><td>7.1 創傷</td>
    <td>1 <input type="checkbox"> 撕裂傷</td><td>8 <input type="checkbox"> 截肢</td>
    <td>15 <input type="checkbox"> 心血管損傷</td></tr>
<tr><td></td><td>2 <input type="checkbox"> 表淺損傷</td><td>9 <input type="checkbox"> 脫臼</td>
    <td>16 <input type="checkbox"> 腹部臟器損傷</td></tr>
</table>
<table>
<tr><td>7.2 非創傷</td>
    <td>1 <input type="checkbox"> 發燒</td><td>9 <input type="checkbox"> 暈眩</td>
    <td>17 <input type="checkbox" checked> 急性冠心症</td></tr>
<tr><td></td><td>5 <input type="checkbox"> 腸胃炎</td>
    <td>13 <input type="checkbox" checked> 高血壓</td>
    <td>21 <input type="checkbox"> 焦慮症</td></tr>
</table>
<p>頁 1 / 8</p>
"""


def _fields():
    f, _ = structure(FIXTURE)
    return f


# --- 印刷註記不可被當成值 ---------------------------------------------------
def test_tag_id_reads_handwriting_below_not_the_annotation():
    """「3.3 編號:( 傷票編號 )」的括號是印刷說明,真值在下一行。"""
    v = _fields()["patient_tag_id"]["value"]
    assert v == "SIH-20260920-006", repr(v)


def test_national_id_ignores_optional_annotation():
    """「(選填)」是印刷字,不可出現在值裡。"""
    v = _fields()["national_id"]["value"]
    assert v == "F692813740", repr(v)


def test_nationality_blank_not_filled_with_annotation():
    """國籍欄空白,不可讀成「(非本國籍)」的殘片。"""
    v = _fields()["nationality"]["value"]
    assert v is None, repr(v)


def test_no_annotation_text_leaks_into_any_field():
    """任何欄位都不該出現印刷註記字樣。"""
    bad = []
    for key, item in _fields().items():
        val = item["value"]
        if isinstance(val, str):
            for word in field_spec.ANNOTATION_WORDS:
                if word in val:
                    bad.append(f"{key}={val!r} 含註記「{word}」")
            if "(" in val or ")" in val or "（" in val or "）" in val:
                bad.append(f"{key}={val!r} 含括號殘留")
    assert not bad, "\n".join(bad)


# --- 意識 GCS ---------------------------------------------------------------
def test_consciousness_accepts_gcs_number():
    item = _fields()["consciousness"]
    assert item["value"] == "15", item
    assert item["confidence"] >= 0.8, item        # 合規,不該被降信心


def test_consciousness_still_accepts_avpu():
    f, _ = structure("<p>4.生命徵象</p><p>意識:清、體溫:36.5</p>")
    assert f["consciousness"]["value"] == "清"
    assert f["consciousness"]["confidence"] >= 0.8


# --- 有/無 對立選項 ---------------------------------------------------------
def test_allergy_checked_none_means_false():
    """過敏史勾的是「無」,不可判成有 —— 這會直接誤導臨床處置。"""
    item = _fields()["has_allergy"]
    assert item["value"] is False, item


def test_allergy_checked_yes_means_true():
    f, _ = structure("<p>5.過去重要病史</p><p>過敏史:<input type='checkbox'>無、"
                     "<input type='checkbox' checked>有 海鮮</p>")
    assert f["has_allergy"]["value"] is True, f["has_allergy"]


# --- 其餘欄位仍要正確 -------------------------------------------------------
def test_basic_and_vitals():
    f = _fields()
    expect = {
        "gender": "女",
        "patient_name": "黃怡君",
        "patient_age": 31,
        "birth_year": 1995,
        "birth_month": 7,
        "birth_day": 19,
        "temperature_c": 36.6,
        "pulse": 78,
        "respiratory_rate": 16,
        "blood_pressure_systolic": 116,
        "blood_pressure_diastolic": 96,
        "spo2_percent": 99,
    }
    bad = [f"{k}: 期望 {w!r} 得到 {f[k]['value']!r}" for k, w in expect.items() if f[k]["value"] != w]
    assert not bad, "\n".join(bad)


def test_triage_reads_the_checked_option():
    """表單勾的是 3 非緊急(輕傷)。"""
    assert _fields()["triage"]["value"] == "3", _fields()["triage"]


def test_present_illness_captured():
    v = _fields()["present_illness_description"]["value"] or ""
    assert "hypertension" in v, repr(v)


def test_chronic_hypertension_checked():
    assert _fields()["chronic_disease_hypertension"]["value"] is True


def test_vaccine_other_checked():
    assert _fields()["vaccine_other"]["value"] is True, _fields()["vaccine_other"]


def test_non_trauma_numbered_table_checkboxes():
    """診斷表為「項次 □ 名稱」版面,勾選框在項次之後、名稱之前。"""
    f = _fields()
    assert f["non_trauma_acute_coronary_syndrome"]["value"] is True, f["non_trauma_acute_coronary_syndrome"]
    assert f["non_trauma_hypertension"]["value"] is True, f["non_trauma_hypertension"]
    assert f["non_trauma_fever"]["value"] is False
    assert f["non_trauma_dizziness"]["value"] is False


def test_trauma_all_unchecked():
    f = _fields()
    assert f["trauma_laceration"]["value"] is False
    assert f["trauma_superficial_injury"]["value"] is False
    assert f["trauma_amputation"]["value"] is False


def test_pregnant_unchecked():
    assert _fields()["pregnant"]["value"] is False


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except AssertionError as e:
                print(f"FAIL {name}: {e}")
                failed += 1
            except Exception as e:  # noqa: BLE001
                print(f"ERROR {name}: {type(e).__name__}: {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
