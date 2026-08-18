"""回歸測試:表單節次編號與勾選溢出。

對應 20260731 第二張實測影像的三個回報:

1. 姓名讀成「陳柏厚 3.2」—— 表單節次編號被當成值
2. 傷票編號讀成「3.4」  —— 同上,且真值寫在下一行
3. 勾記號畫超出格線時,隔壁項目也被判成已勾選

執行:cd src/ai-service && python tests/test_section_numbers_and_ticks.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.structurer import CONF_ADJACENT, structure  # noqa: E402


# --- 1/2. 節次編號不可進入值 ------------------------------------------------
def test_name_not_polluted_by_next_section_number():
    """「3.1 姓名:陳柏厚 3.2 年齡 42」→ 姓名只能是「陳柏厚」。"""
    html = "<p>3.基本資料</p><table><tr><td>3.1 姓名:陳柏厚 3.2 年齡 42</td></tr></table>"
    f, _ = structure(html)
    assert f["patient_name"]["value"] == "陳柏厚", f["patient_name"]
    assert f["patient_age"]["value"] == 42, f["patient_age"]


def test_tag_id_not_polluted_by_next_section_number():
    """「3.3 編號:( 傷票編號 ) 3.4 生日…」+ 下一行手寫值 → 取手寫值。"""
    html = ("<p>3.基本資料</p><table>"
            "<tr><td>3.3 編號:( 傷票編號 ) 3.4 生日:西元1984年2月4日<br>"
            "SIM-20260701-001</td></tr></table>")
    f, _ = structure(html)
    assert f["patient_tag_id"]["value"] == "SIM-20260701-001", f["patient_tag_id"]


def test_tag_id_never_becomes_a_section_number():
    """就算下一行沒有手寫值,也不可退而求其次填「3.4」。"""
    html = "<p>3.基本資料</p><table><tr><td>3.3 編號:( 傷票編號 ) 3.4 生日:西元1984年2月4日</td></tr></table>"
    f, _ = structure(html)
    v = f["patient_tag_id"]["value"]
    assert v is None or "3.4" not in str(v), f["patient_tag_id"]


def test_section_number_rule_does_not_break_decimal_values():
    """體溫 36.7 長得像節次編號,絕不可被截掉。"""
    html = "<p>4.生命徵象</p><table><tr><td>體溫:36.7 、脈搏:85 、呼吸次數:19</td></tr></table>"
    f, _ = structure(html)
    assert f["temperature_c"]["value"] == 36.7, f["temperature_c"]
    assert f["pulse"]["value"] == 85
    assert f["respiratory_rate"]["value"] == 19


def test_no_section_number_leaks_into_any_text_field():
    html = ("<p>3.基本資料</p><table>"
            "<tr><td>3.1 姓名:陳柏厚 3.2 年齡 42</td>"
            "<td>3.5 身分證字號:(選填) A483920157 3.6 國籍(非本國籍):</td></tr></table>")
    f, _ = structure(html)
    import re
    bad = [f"{k}={v['value']!r}" for k, v in f.items()
           if isinstance(v["value"], str) and re.search(r"\d+\.\d+", v["value"])]
    assert not bad, bad
    assert f["national_id"]["value"] == "A483920157", f["national_id"]


# --- 3. 勾選溢出 ------------------------------------------------------------
def test_adjacent_checks_are_flagged_for_review():
    """相鄰兩項同時勾選 → 兩者都降信心標黃,但值保留。"""
    html = ("<p>7.主要初步診斷</p><p>7.1 創傷</p>"
            "<p>1 <input type='checkbox'> 撕裂傷 "
            "2 <input type='checkbox' checked> 表淺損傷 "
            "3 <input type='checkbox' checked> 鈍挫傷、拉扭傷 "
            "4 <input type='checkbox'> 中軸骨折</p>")
    f, ev = structure(html)
    a, b = f["trauma_superficial_injury"], f["trauma_contusion_sprain"]
    assert a["value"] is True and b["value"] is True, (a, b)     # 不可靜默丟掉陽性
    assert a["confidence"] <= CONF_ADJACENT, a
    assert b["confidence"] <= CONF_ADJACENT, b
    assert "相鄰" in ev["trauma_superficial_injury"]


def test_isolated_check_keeps_full_confidence():
    """單獨一項勾選不受影響,維持高信心。"""
    html = ("<p>7.主要初步診斷</p><p>7.1 創傷</p>"
            "<p>1 <input type='checkbox'> 撕裂傷 "
            "2 <input type='checkbox' checked> 表淺損傷 "
            "3 <input type='checkbox'> 鈍挫傷、拉扭傷</p>")
    f, _ = structure(html)
    item = f["trauma_superficial_injury"]
    assert item["value"] is True
    assert item["confidence"] > CONF_ADJACENT, item


def test_non_adjacent_checks_not_flagged():
    """隔開的兩項同時勾選是正常複選,不應降信心。"""
    html = ("<p>7.主要初步診斷</p><p>7.1 創傷</p>"
            "<p>1 <input type='checkbox' checked> 撕裂傷 "
            "2 <input type='checkbox'> 表淺損傷 "
            "3 <input type='checkbox'> 鈍挫傷、拉扭傷 "
            "4 <input type='checkbox' checked> 中軸骨折</p>")
    f, _ = structure(html)
    assert f["trauma_laceration"]["confidence"] > CONF_ADJACENT
    assert f["trauma_axial_fracture"]["confidence"] > CONF_ADJACENT


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
