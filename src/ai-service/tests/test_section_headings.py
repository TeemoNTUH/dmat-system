"""區塊標題不可被當成欄位的值。

現場回報:國籍欄經常讀到「4.生命徵象」。

成因是「空白欄位的退路」與「結構文字」撞在一起:國籍是基本資料區的最後一格,
它後面緊接的就是下一區的標題。國籍沒填時,擷取邏輯依序找「同格 → 下一格 →
下一行」,而下一格/下一行正是「4.生命徵象」—— 對規則來說那就是一段文字,
於是被當成值收下。

區塊標題是表格印上去的結構文字,永遠不可能是任何欄位的值,因此一律排除。

此檔另含一組體溫的回歸測試。原本的節次編號規則是「數字+點+數字,後面接中文
就視為編號」,而體溫「36.7度C」完全符合 —— 值會從第一個字就被截掉,體溫因此
永遠讀不到。這是追查國籍問題時一併發現的,規則收斂後必須確認不再復發。

執行:cd src/ai-service && python tests/test_section_headings.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import field_spec  # noqa: E402
from app.structurer import structure  # noqa: E402


def _f(html: str, key: str):
    fields, _ = structure(html)
    return fields[key]["value"]


# --- 國籍吃到下一區標題 -----------------------------------------------------
def test_nationality_empty_does_not_take_next_section_heading():
    """國籍空白時,下一格的「4.生命徵象」不可成為值。"""
    assert _f("| 3.6 國籍(非本國籍) |  | 4.生命徵象 |", "nationality") is None


def test_nationality_does_not_take_heading_on_next_line():
    """「值寫在標籤下一行」的退路也不可撿到區塊標題。"""
    html = "| 3.6 國籍(非本國籍) |  |\n| 4. 生命徵象 | 意識:15 |"
    assert _f(html, "nationality") is None


def test_nationality_heading_without_space():
    """OCR 常把「國籍:」與標題黏成一格,沒有分隔符也要擋。"""
    assert _f("3.6 國籍(非本國籍):4.生命徵象", "nationality") is None


def test_nationality_rejects_section_alias():
    """「評估」是生命徵象區的別名,同樣是結構文字。"""
    assert _f("| 3.6 國籍 |  | 4.評估 |", "nationality") is None


def test_nationality_rejects_heading_across_lines():
    assert _f("| 3.6 國籍 |\n| 4.生命徵象 |", "nationality") is None


# --- 真的有填的時候不能誤殺 -------------------------------------------------
def test_nationality_real_value_still_read():
    """修正不可矯枉過正:國籍真的填了就要讀到。"""
    assert _f("| 3.6 國籍(非本國籍) | 越南 | 4.生命徵象 |", "nationality") == "越南"


def test_nationality_local_value():
    assert _f("| 3.6 國籍 | 中華民國 |", "nationality") == "中華民國"


def test_section_headings_are_known_labels():
    """區塊標題必須全數納入標籤字典,截斷與污染判定才會一致。"""
    labels = field_spec.known_labels()
    for markers in field_spec.SECTION_MARKERS.values():
        for marker in markers:
            assert marker in labels, f"區塊標題未納入 known_labels():{marker}"


# --- 體溫回歸:中文單位不可觸發節次編號截斷 ---------------------------------
def test_temperature_with_chinese_unit():
    """「36.7度」的「度」是單位,不是下一個欄位的開頭。"""
    assert _f("| 4.生命徵象 | 體溫:36.7度 |", "temperature_c") == 36.7


def test_temperature_with_unit_and_following_field():
    """同格還有下一個欄位時,體溫與脈搏都要正確切開。"""
    html = "| 4.生命徵象 | 體溫 36.7度C 脈搏 88 |"
    assert _f(html, "temperature_c") == 36.7
    assert _f(html, "pulse") == 88


def test_temperature_degree_symbol():
    assert _f("| 4.生命徵象 | 體溫 38.2°C |", "temperature_c") == 38.2


# --- 節次編號截斷本身不可失效 -----------------------------------------------
def test_section_number_trim_still_works():
    """收斂規則後,原本的節次編號截斷仍必須有效(見 test_section_numbers_and_ticks)。"""
    html = "| 3.1 姓名:陳柏厚 3.2 年齡 42 |"
    assert _f(html, "patient_name") == "陳柏厚"
    assert _f(html, "patient_age") == 42


def test_bare_number_is_not_treated_as_section_number():
    """純數字沒有分隔符,是值不是編號 —— 誤判會讓年齡整個消失。"""
    assert _f("| 3.2 年齡 42 3.3 性別 |", "patient_age") == 42


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
