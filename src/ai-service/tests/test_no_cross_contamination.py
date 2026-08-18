"""回歸測試:欄位不得讀到「別的欄位」的資料。

現場回報的症狀是「欄位會讀到非自己欄位的資料」。成因有四類,各自對應下面一組測試:

1. **標籤子字串誤命中** — 「過敏」命中在「過敏史」裡,結果過敏原欄位抓到勾選框內容
2. **跨儲存格取值**     — 值抓過了 <td> 邊界,吃到隔壁欄
3. **跨列取值**         — 值抓過了 <tr> 邊界,吃到下一列
4. **抓到但不合規**     — 型別/範圍/格式不符卻仍以高信心放行

執行:cd src/ai-service && python tests/test_no_cross_contamination.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import field_spec  # noqa: E402
from app.structurer import structure  # noqa: E402


def _f(html: str):
    fields, evidence = structure(html)
    return fields, evidence


def _val(html: str, key: str):
    return _f(html)[0][key]["value"]


def _conf(html: str, key: str):
    return _f(html)[0][key]["confidence"]


# --- 1. 標籤子字串誤命中 ----------------------------------------------------
def test_allergy_label_does_not_match_inside_allergy_history():
    """「過敏原」的標籤不可命中「過敏史」——這會把勾選框內容當成過敏原。"""
    html = "<p>過去重要病史</p><p>過敏史:<input type='checkbox' checked>有 | 過敏原:海鮮</p>"
    fields, _ = _f(html)
    assert fields["has_allergy"]["value"] is True
    assert fields["allergy_note"]["value"] == "海鮮", fields["allergy_note"]


def test_tag_id_label_does_not_steal_from_longer_label():
    """「編號」是「傷票編號」的一部分,不可各自抓到不同的東西。"""
    html = "<p>基本資料</p><table><tr><td>傷票編號:A125680363</td></tr></table>"
    assert _val(html, "patient_tag_id") == "A125680363"


def test_pulse_single_letter_label_does_not_match_random_text():
    """單字母標籤 P 不可在無關文字裡亂命中。"""
    html = "<p>基本資料</p><table><tr><td>姓名:PETER CHEN</td></tr></table>"
    fields, _ = _f(html)
    # 沒有生命徵象區塊,脈搏應為空而不是從姓名裡挖出數字
    assert fields["pulse"]["value"] is None, fields["pulse"]


# --- 2. 跨儲存格 ------------------------------------------------------------
def test_value_does_not_cross_table_cell():
    """姓名不可吃到隔壁儲存格的性別/年齡。"""
    html = ("<p>基本資料</p><table><tr>"
            "<td>姓名:王大明</td><td>性別:男</td><td>年齡:45</td>"
            "</tr></table>")
    fields, _ = _f(html)
    assert fields["patient_name"]["value"] == "王大明", fields["patient_name"]
    assert fields["patient_age"]["value"] == 45


def test_label_in_one_cell_value_in_next_cell():
    """標籤與值分屬相鄰儲存格(表單轉寫常見)也要抓得到。"""
    html = ("<p>基本資料</p><table><tr>"
            "<td>姓名</td><td>李小華</td><td>年齡</td><td>32</td>"
            "</tr></table>")
    fields, _ = _f(html)
    assert fields["patient_name"]["value"] == "李小華", fields["patient_name"]
    assert fields["patient_age"]["value"] == 32, fields["patient_age"]


def test_vitals_do_not_bleed_into_each_other():
    html = ("<p>生命徵象</p><table><tr>"
            "<td>體溫:36.5</td><td>脈搏:88</td><td>呼吸:20</td><td>血氧:97</td>"
            "</tr></table>")
    fields, _ = _f(html)
    assert fields["temperature_c"]["value"] == 36.5
    assert fields["pulse"]["value"] == 88
    assert fields["respiratory_rate"]["value"] == 20
    assert fields["spo2_percent"]["value"] == 97


# --- 3. 跨列 ---------------------------------------------------------------
def test_value_does_not_cross_row():
    """本列欄位空白時,不可跑去抓下一列的值。"""
    html = ("<p>基本資料</p><table>"
            "<tr><td>國籍:</td></tr>"
            "<tr><td>姓名:陳小美</td></tr>"
            "</table>")
    fields, _ = _f(html)
    assert fields["nationality"]["value"] is None, fields["nationality"]
    assert fields["patient_name"]["value"] == "陳小美"


def test_empty_field_stays_empty_rather_than_borrowing():
    html = "<p>基本資料</p><table><tr><td>姓名:</td><td>性別:女</td></tr></table>"
    fields, _ = _f(html)
    assert fields["patient_name"]["value"] is None, fields["patient_name"]
    assert fields["gender"]["value"] == "女"


# --- 4. 抓到但不合規 → 必須低信心 -------------------------------------------
def test_out_of_range_value_gets_low_confidence():
    html = "<p>生命徵象</p><table><tr><td>脈搏:8888</td></tr></table>"
    assert _conf(html, "pulse") <= 0.3, _f(html)[0]["pulse"]


def test_malformed_national_id_flagged():
    html = "<p>基本資料</p><table><tr><td>身分證字號:XYZ</td></tr></table>"
    assert _conf(html, "national_id") <= 0.3


def test_triage_only_accepts_defined_codes():
    html = "<p>檢傷分類:<input type='checkbox' checked> 9 未知</p>"
    fields, _ = _f(html)
    v = fields["triage"]["value"]
    assert v is None or v in ("1", "2", "3", "4", "4-1") or fields["triage"]["confidence"] <= 0.3


def test_gender_only_accepts_defined_values():
    html = "<p>基本資料</p><table><tr><td>性別:不明</td></tr></table>"
    assert _conf(html, "gender") <= 0.3


def test_overlong_text_is_rejected():
    """姓名欄抓到一長串 → 幾乎必然是吃到整列,不可高信心放行。"""
    long_name = "王大明" + "某某某" * 20
    html = f"<p>基本資料</p><table><tr><td>姓名:{long_name}</td></tr></table>"
    assert _conf(html, "patient_name") <= 0.3


# --- 5. 自由敘述不可被誤截(過度嚴格的反面) --------------------------------
def test_free_text_not_truncated_at_diagnosis_names():
    """現病史含診斷名稱是正常的,不可被當成下一個欄位而截斷。"""
    html = "<p>現病史:地震倒塌物壓傷,右下肢開放性骨折併大量出血</p>"
    v = _val(html, "present_illness_description")
    assert v == "地震倒塌物壓傷,右下肢開放性骨折併大量出血", repr(v)


def test_free_text_not_truncated_at_vital_words():
    """「意識躁動」「體溫偏高」是敘述用語,不是下一個欄位的標籤。"""
    html = "<p>現病史:病患意識躁動,體溫偏高,持續嘔吐</p>"
    v = _val(html, "present_illness_description")
    assert v == "病患意識躁動,體溫偏高,持續嘔吐", repr(v)


def test_free_text_still_stops_at_real_next_label():
    """但真的遇到「標籤:」還是要停 —— 邊界保護不能因此失效。"""
    html = "<p>現病史:胸悶三小時 意識:清</p>"
    v = _val(html, "present_illness_description")
    assert "清" not in v and "胸悶三小時" in v, repr(v)


def test_free_text_stops_at_cell_boundary():
    html = "<p>過去重要病史</p><p>過敏原:海鮮 | 其他疫苗:流感</p>"
    fields, _ = _f(html)
    assert fields["allergy_note"]["value"] == "海鮮", fields["allergy_note"]
    assert fields["vaccine_other_note"]["value"] == "流感", fields["vaccine_other_note"]


# --- 規格本身 ---------------------------------------------------------------
def test_spec_validate_rejects_wrong_types():
    assert field_spec.validate("pulse", "abc")[1] is False
    assert field_spec.validate("pulse", 88)[1] is True
    assert field_spec.validate("temperature_c", 36.5)[1] is True
    assert field_spec.validate("temperature_c", 361)[1] is False
    assert field_spec.validate("consciousness", "清")[1] is True
    assert field_spec.validate("consciousness", "昏迷不醒")[1] is False
    assert field_spec.validate("national_id", "A123456789")[1] is True
    assert field_spec.validate("national_id", "A12345")[1] is False


def test_foreign_label_detection():
    assert field_spec.contains_foreign_label("patient_name", "王大明 性別:男") is True
    assert field_spec.contains_foreign_label("patient_name", "王大明") is False


def test_every_field_has_a_spec():
    """所有欄位都要有規格,才不會有欄位繞過驗證。"""
    for key in field_spec.ALL_KEYS:
        s = field_spec.spec_for(key)
        assert s.kind in ("text", "int", "float", "bool"), (key, s.kind)


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
