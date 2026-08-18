"""意識欄位:AVPU / GCS 總分 / GCS 總分 + EVM 分項。

現場需求:意識若寫成「15(E4V5M6)」,總分與 EVM 分項都要保留。
EVM 是臨床判讀的重要依據 —— 同樣是 8 分,E1V1M6(去皮質姿勢)與 E2V3M3
的處置方向完全不同,只留總分等於把資訊丟了。

同時利用 GCS 的性質做免費的錯誤偵測:**總分必定等於 E+V+M**。

執行:cd src/ai-service && python tests/test_consciousness_gcs.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import field_spec  # noqa: E402
from app.structurer import structure  # noqa: E402


def _c(html: str):
    f, _ = structure(html)
    return f["consciousness"]


def _vital(inner: str) -> str:
    return f"<p>4.生命徵象</p><table><tr><td>{inner}</td></tr></table>"


# --- 解析 -------------------------------------------------------------------
def test_parse_total_only():
    assert field_spec.parse_consciousness("15") == (None, 15, None)


def test_parse_evm_only():
    assert field_spec.parse_consciousness("E4V5M6") == (None, None, (4, 5, 6))


def test_parse_total_with_evm():
    assert field_spec.parse_consciousness("15(E4V5M6)") == (None, 15, (4, 5, 6))


def test_parse_tolerates_spaces():
    assert field_spec.parse_consciousness("15 (E4 V5 M6)") == (None, 15, (4, 5, 6))


def test_parse_avpu():
    assert field_spec.parse_consciousness("清")[0] == "清"


def test_total_not_taken_from_inside_parens():
    """括號內的 E4 不可被當成總分。"""
    _, total, evm = field_spec.parse_consciousness("(E4V5M6)")
    assert total is None and evm == (4, 5, 6)


# --- 顯示格式 ---------------------------------------------------------------
def test_format_keeps_both_total_and_evm():
    assert field_spec.format_consciousness("15(E4V5M6)") == "15 (E4V5M6)"


def test_format_fills_in_missing_total():
    """只寫分項時自動補上總分,覆核人員不必自己加。"""
    assert field_spec.format_consciousness("E3V4M5") == "12 (E3V4M5)"


def test_format_total_only_stays_plain():
    assert field_spec.format_consciousness("15") == "15"


# --- 端到端 -----------------------------------------------------------------
def test_extract_total_with_evm_from_form():
    item = _c(_vital("意識:15(E4V5M6) 、體溫:36.6 、脈搏:78"))
    assert item["value"] == "15 (E4V5M6)", item
    assert item["confidence"] >= 0.8, item


def test_extract_does_not_strip_parentheses_here():
    """一般欄位的括號是印刷註記要剝掉,意識欄的括號是內容,不可剝。"""
    assert "(" in (_c(_vital("意識:15(E4V5M6)"))["value"] or "")


def test_extract_evm_only():
    item = _c(_vital("意識:E4V5M6 、體溫:36.6"))
    assert item["value"] == "15 (E4V5M6)", item


def test_extract_avpu_still_works():
    item = _c(_vital("意識:清 、體溫:36.5"))
    assert item["value"] == "清"
    assert item["confidence"] >= 0.8


def test_extract_plain_gcs_still_works():
    item = _c(_vital("意識:15 、體溫:36.6"))
    assert item["value"] == "15"
    assert item["confidence"] >= 0.8


def test_evm_does_not_leak_into_other_vitals():
    f, _ = structure(_vital("意識:15(E4V5M6) 、體溫:36.6 、脈搏:78 、呼吸次數:16"))
    assert f["temperature_c"]["value"] == 36.6
    assert f["pulse"]["value"] == 78
    assert f["respiratory_rate"]["value"] == 16


# --- 一致性檢核 -------------------------------------------------------------
def test_mismatched_total_is_flagged():
    """15 但 E3V4M5=12 → 必有一項誤讀,要降信心送覆核。"""
    item = _c(_vital("意識:15(E3V4M5)"))
    assert item["confidence"] <= 0.3, item
    assert item["value"] == "15 (E3V4M5)", "值仍要保留給覆核人員參考"


def test_component_out_of_range_is_flagged():
    """E 最高 4、V 最高 5、M 最高 6。"""
    assert field_spec.validate("consciousness", "16(E5V5M6)")[1] is False
    assert field_spec.validate("consciousness", "15(E4V6M6)")[1] is False


def test_consistent_gcs_passes():
    for text in ("15(E4V5M6)", "3(E1V1M1)", "8 (E2V2M4)", "12(E3V4M5)"):
        assert field_spec.validate("consciousness", text)[1] is True, text


def test_gcs_total_range():
    assert field_spec.validate("consciousness", "15")[1] is True
    assert field_spec.validate("consciousness", "3")[1] is True
    assert field_spec.validate("consciousness", "16")[1] is False
    assert field_spec.validate("consciousness", "2")[1] is False


def test_value_fits_database_column():
    """TriageRecord.Consciousness 為 MaxLength(20),格式化後不可超過。"""
    assert len(field_spec.format_consciousness("15(E4V5M6)")) <= 20


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
