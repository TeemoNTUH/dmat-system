"""第三階段「針對性複查」的測試。

驗證三件事:
1. 只在真的不確定時才觸發(不確定 → 問;確定 → 不浪費一輪推論)
2. 問題本身有把「勾記號跨格時只算主體所在那格」講清楚
3. 答案能正確合併,且答案不合規時不會覆蓋掉原本的結果

執行:cd src/ai-service && python tests/test_verify.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import verify  # noqa: E402
from app.structurer import structure  # noqa: E402


def _baseline(**overrides):
    """一份「全部都很有把握」的欄位表;測試只覆寫要驗的那幾欄。

    複查的觸發條件會看多個欄位,若測試只給兩三欄,其餘欄位會因為「缺漏」
    而意外觸發額外的複查 —— 所以基準值要完整。
    """
    base = {
        "triage": {"value": "3", "confidence": 0.9},
        "patient_tag_id": {"value": "SIM-20260701-001", "confidence": 0.88},
        "national_id": {"value": "F692813740", "confidence": 0.88},
        "patient_name": {"value": "黃怡君", "confidence": 0.88},
    }
    base.update(overrides)
    return base


# --- 觸發條件 ---------------------------------------------------------------
def test_no_verification_when_everything_is_confident():
    assert verify.plan(_baseline(), {}) == []


def test_triage_verified_when_missing():
    tasks = verify.plan(_baseline(triage={"value": None, "confidence": 0.0}), {})
    assert [t.label for t in tasks] == ["檢傷分類"]
    assert tasks[0].kind == "single"


def test_triage_verified_when_multiple_boxes_ticked():
    """單選欄位被勾成多個 → 一定要複查,不可沿用第一個。"""
    fields = _baseline(triage={"value": "2", "confidence": 0.55})
    ev = {"triage": f"⚠{verify.MULTI_MARK}(2、3),請對照影像確認"}
    assert [t.label for t in verify.plan(fields, ev)] == ["檢傷分類"]


def test_tag_id_verified_when_missing():
    tasks = verify.plan(_baseline(patient_tag_id={"value": None, "confidence": 0.0}), {})
    assert [t.label for t in tasks] == ["傷票編號"]
    assert tasks[0].kind == "value"


def test_adjacent_checks_trigger_group_verification():
    """實際跑一次結構化,相鄰同時勾選要能觸發該群組的複查。"""
    html = ("<p>7.主要初步診斷</p><p>7.1 創傷</p>"
            "<p>1 <input type='checkbox'> 撕裂傷 "
            "2 <input type='checkbox' checked> 表淺損傷 "
            "3 <input type='checkbox' checked> 鈍挫傷、拉扭傷</p>")
    fields, ev = structure(html)
    fields.update(_baseline())          # 其餘欄位視為已確認,只留勾選疑慮
    labels = [t.label for t in verify.plan(fields, ev)]
    assert "7.1 創傷" in labels, labels


def test_task_count_is_bounded():
    fields = _baseline(triage={"value": None, "confidence": 0.0},
                       patient_tag_id={"value": None, "confidence": 0.0})
    assert len(verify.plan(fields, {}, max_tasks=1)) == 1


def test_national_id_missing_leading_letter_triggers_verification():
    """身分證字號少了開頭英文字母(OCR 常見)→ 必須複查。"""
    fields = _baseline(national_id={"value": "692813740", "confidence": 0.2})
    tasks = verify.plan(fields, {})
    assert [t.label for t in tasks] == ["身分證字號"], [t.label for t in tasks]
    assert "1 個大寫英文字母 + 9 個數字" in tasks[0].prompt


def test_blank_optional_field_does_not_waste_a_round():
    """選填欄位本來就空白時不該複查 —— 每一輪推論都要數十秒。"""
    fields = _baseline(national_id={"value": None, "confidence": 0.0})
    assert verify.plan(fields, {}) == []


def test_diagnosis_groups_take_priority_over_optional_fields():
    """診斷牽涉臨床處置,排在選填的身分證字號之前。"""
    html = ("<p>7.主要初步診斷</p><p>7.1 創傷</p>"
            "<p>1 <input type='checkbox'> 撕裂傷 "
            "2 <input type='checkbox' checked> 表淺損傷 "
            "3 <input type='checkbox' checked> 鈍挫傷、拉扭傷</p>")
    fields, ev = structure(html)
    fields.update(_baseline(national_id={"value": "692813740", "confidence": 0.2}))
    labels = [t.label for t in verify.plan(fields, ev)]
    assert labels.index("7.1 創傷") < labels.index("身分證字號"), labels


# --- 提示詞內容 -------------------------------------------------------------
def test_prompts_state_the_tie_break_rule():
    """使用者的要求:勾記號跨格時只算主體所在那一格 —— 必須寫進提示。"""
    task = verify.plan(_baseline(triage={"value": None, "confidence": 0.0}), {})[0]
    assert "記號主體" in task.prompt, task.prompt
    assert "裡面" in task.prompt


def test_group_prompt_lists_items_with_numbers():
    html = ("<p>7.主要初步診斷</p><p>7.2 非創傷</p>"
            "<p>1 <input type='checkbox' checked> 發燒 "
            "2 <input type='checkbox' checked> 肺炎</p>")
    fields, ev = structure(html)
    fields.update(_baseline())
    task = next(t for t in verify.plan(fields, ev) if t.label == "7.2 非創傷")
    assert "1 發燒" in task.prompt and "2 肺炎" in task.prompt
    assert "記號主體" in task.prompt
    assert task.index_map["1"] == "non_trauma_fever"


# --- 合併答案 ---------------------------------------------------------------
def test_apply_single_sets_triage():
    task = verify.plan(_baseline(triage={"value": None, "confidence": 0.0}), {})[0]
    fields, ev = {"triage": {"value": None, "confidence": 0.0}}, {}
    assert verify.apply(task, "3", fields, ev) is True
    assert fields["triage"]["value"] == "3"
    assert fields["triage"]["confidence"] > 0.85
    assert "複查" in ev["triage"]


def test_apply_single_accepts_4_1():
    task = verify._triage_task()
    fields, ev = {"triage": {"value": None, "confidence": 0.0}}, {}
    assert verify.apply(task, "4-1", fields, ev) is True
    assert fields["triage"]["value"] == "4-1"


def test_apply_single_none_keeps_original():
    task = verify._triage_task()
    fields = {"triage": {"value": "2", "confidence": 0.55}}
    assert verify.apply(task, "NONE", fields, {}) is False
    assert fields["triage"]["value"] == "2"


def test_apply_value_rejects_invalid_answer():
    """複查答案不合欄位規格時,不可覆蓋原值。"""
    fields = {"patient_tag_id": {"value": None, "confidence": 0.0}}
    task = verify.plan(_baseline(patient_tag_id={"value": None, "confidence": 0.0}), {})[0]
    assert verify.apply(task, "UNKNOWN", fields, {}) is False
    assert verify.apply(task, "我看不清楚這個欄位的內容因為影像太模糊了無法判讀", fields, {}) is False
    assert fields["patient_tag_id"]["value"] is None


def test_apply_value_accepts_and_strips_noise():
    fields, ev = {"patient_tag_id": {"value": None, "confidence": 0.0}}, {}
    task = verify.plan(_baseline(patient_tag_id={"value": None, "confidence": 0.0}), {})[0]
    assert verify.apply(task, "「SIM-20260701-001」", fields, ev) is True
    assert fields["patient_tag_id"]["value"] == "SIM-20260701-001"


def test_apply_multi_sets_only_answered_items():
    """複查說只有第 3 項有勾 → 第 2 項要被更正為未勾選。"""
    html = ("<p>7.主要初步診斷</p><p>7.1 創傷</p>"
            "<p>1 <input type='checkbox'> 撕裂傷 "
            "2 <input type='checkbox' checked> 表淺損傷 "
            "3 <input type='checkbox' checked> 鈍挫傷、拉扭傷</p>")
    fields, ev = structure(html)
    fields.update(_baseline())
    task = next(t for t in verify.plan(fields, ev) if t.label == "7.1 創傷")

    assert verify.apply(task, "3", fields, ev) is True
    assert fields["trauma_contusion_sprain"]["value"] is True
    assert fields["trauma_superficial_injury"]["value"] is False, "溢出的那格應被更正"
    assert fields["trauma_contusion_sprain"]["confidence"] > 0.85


def test_apply_multi_none_clears_group():
    html = ("<p>7.主要初步診斷</p><p>7.1 創傷</p>"
            "<p>1 <input type='checkbox' checked> 撕裂傷 "
            "2 <input type='checkbox' checked> 表淺損傷</p>")
    fields, ev = structure(html)
    fields.update(_baseline())
    task = next(t for t in verify.plan(fields, ev) if t.label == "7.1 創傷")
    assert verify.apply(task, "NONE", fields, ev) is True
    assert fields["trauma_laceration"]["value"] is False
    assert fields["trauma_superficial_injury"]["value"] is False


def test_apply_multi_ignores_out_of_range_numbers():
    html = ("<p>7.主要初步診斷</p><p>7.1 創傷</p>"
            "<p>1 <input type='checkbox' checked> 撕裂傷 "
            "2 <input type='checkbox' checked> 表淺損傷</p>")
    fields, ev = structure(html)
    fields.update(_baseline())
    task = next(t for t in verify.plan(fields, ev) if t.label == "7.1 創傷")
    assert verify.apply(task, "99", fields, ev) is False   # 沒有第 99 項 → 不套用


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
