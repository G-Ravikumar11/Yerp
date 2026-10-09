"""The AI functions for subcontracts (backend/Ai_service): the model only reads or words things; plain code decides.

No network and no key are used: the model call is replaced in each test.
"""
import pytest

from Ai_service import bill_review, config, contractor_brief, hard_copy_check
from Ai_service.llm_client import AiResult, parse_json
from test_delete_work_order import book, live_order

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def a_draft(tenant, qty=10):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": qty})
    return order, tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AI_ENABLED", "1")


@pytest.fixture
def unkeyed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


# --- the pieces that are plain code -----------------------------------------------------------------------------------

def test_an_answer_wrapped_in_words_or_a_fence_is_still_read():
    assert parse_json('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure. {"a": 2} Hope that helps') == {"a": 2}
    assert parse_json("no object here") is None


def test_the_comparison_calls_a_difference_beyond_a_rupee_or_half_a_percent():
    bill = {"this_bill": 100000.0, "gst_amount": 18000.0, "retention_amount": 5000.0, "tds_amount": 1000.0,
            "net_payable": 112000.0, "lines": []}
    same = hard_copy_check.compare({"work_value": 100000, "gst": 18000, "retention": 5000, "tds": 1000, "net_payable": 112300}, bill)
    assert same["mismatches"] == [] and len(same["agreed"]) == 5          # 300 on 112,000 is within half a percent
    off = hard_copy_check.compare({"work_value": 100000, "net_payable": 105000}, bill)
    assert [m["item"] for m in off["mismatches"]] == ["Net payable"] and off["mismatches"][0]["difference"] == 7000
    assert off["agrees"] is False


def test_a_work_item_on_one_side_only_is_listed():
    bill = {"this_bill": 1000.0, "lines": [{"description": "Shuttering", "this_bill_qty": 10, "amount": 600.0},
                                            {"description": "Plastering", "this_bill_qty": 5, "amount": 400.0}]}
    out = hard_copy_check.compare({"work_value": 1000, "lines": [{"description": "Shuttering", "quantity": 10, "amount": 600},
                                                                  {"description": "Painting", "quantity": 3, "amount": 250}]}, bill)
    assert [l["description"] for l in out["only_on_bill"]] == ["Plastering"]
    assert [l["description"] for l in out["only_on_paper"]] == ["Painting"]


def test_flags_catch_quantity_beyond_the_order_and_a_bill_far_above_the_usual():
    bill = {"this_bill": 90000.0, "net_payable": 80000.0, "status": "DRAFT", "hardcopy": None,
            "lines": [{"description": "Shuttering", "ordered_qty": 100, "previously_billed_qty": 95, "this_bill_qty": 10}],
            "compliance_warnings": ["Contract labour licence is not on record."], "open_back_charges": []}
    flags = bill_review.find_flags(bill, [20000.0, 30000.0])
    assert any(f["level"] == "stop" and "105" in f["text"] for f in flags)
    assert any(f["level"] == "stop" and "Papers" in f["text"] for f in flags)
    assert any("twice the average" in f["text"] for f in flags) and any("No hard copy" in f["text"] for f in flags)
    assert bill_review.find_flags({"this_bill": 1, "net_payable": 1, "lines": [], "hardcopy": {"difference": 0}}, []) == []


# --- the endpoints ----------------------------------------------------------------------------------------------------

def test_with_no_key_the_plain_checks_still_answer_and_the_ai_part_says_so(tenant, unkeyed):
    order, bill = a_draft(tenant)
    status = tenant.get("/api/ai/subcontracts/status").json()
    assert status["available"] is False and status["configured"] is False
    review = tenant.get("/api/ai/subcontracts/bills/%d/review" % bill["id"]).json()
    assert review["summary"] is None and review["flags"], "flags are plain code and need no key"
    brief = tenant.get("/api/ai/subcontracts/contractors/%d/brief" % order["contractor_id"]).json()
    assert brief["summary"] is None and brief["standing"]["contractor"]


def test_the_off_switch_turns_everything_off(tenant, keyed, monkeypatch):
    monkeypatch.setenv("AI_ENABLED", "0")
    order, bill = a_draft(tenant)
    assert tenant.get("/api/ai/subcontracts/status").json()["available"] is False
    assert tenant.get("/api/ai/subcontracts/bills/%d/review" % bill["id"]).json()["summary"] is None


def test_the_review_writes_its_summary_from_the_flags_and_is_audited(tenant, keyed, monkeypatch):
    order, bill = a_draft(tenant)
    seen = {}

    def fake(system, prompt, attachments=None, smart=True, max_tokens=2048, temperature=0.1):
        seen["prompt"] = prompt
        return AiResult(True, text="A first bill for the order. Papers are missing.", provider="anthropic", model="test-model", usage={"input": 10, "output": 5})

    monkeypatch.setattr(bill_review, "ask", fake)
    out = tenant.get("/api/ai/subcontracts/bills/%d/review" % bill["id"]).json()
    assert out["summary"].startswith("A first bill") and out["model"] == "test-model"
    assert "not on record" in seen["prompt"], "the model is given the checks, not left to find its own"


def test_a_failed_model_call_leaves_the_flags_and_says_why(tenant, keyed, monkeypatch):
    order, bill = a_draft(tenant)
    monkeypatch.setattr(bill_review, "ask", lambda *a, **k: AiResult(False, reason="rate_limited"))
    out = tenant.get("/api/ai/subcontracts/bills/%d/review" % bill["id"]).json()
    assert out["summary"] is None and "busy" in out["ai_message"] and out["flags"]


def test_hard_copy_check_needs_a_hard_copy_and_then_compares_what_was_read(tenant, keyed, monkeypatch):
    order, bill = a_draft(tenant)
    assert tenant.post("/api/ai/subcontracts/bills/%d/hard-copy-check" % bill["id"]).status_code == 409
    assert tenant.post("/api/sub-bills/%d/hardcopy" % bill["id"], files={"file": ("bill.pdf", PDF, "application/pdf")}, data={"amount": ""}).status_code == 200

    def reads(wrong):
        return lambda data, media: AiResult(True, data={
            "work_value": bill["this_bill"] + (5000 if wrong else 0), "net_payable": bill["net_payable"],
            "lines": [], "confidence": 0.92, "notes": ""}, provider="anthropic", model="test-model")

    monkeypatch.setattr(hard_copy_check, "read_hard_copy", reads(False))
    ok = tenant.post("/api/ai/subcontracts/bills/%d/hard-copy-check" % bill["id"]).json()
    assert ok["available"] and ok["mismatches"] == [] and ok["low_confidence"] is False

    monkeypatch.setattr(hard_copy_check, "read_hard_copy", reads(True))
    off = tenant.post("/api/ai/subcontracts/bills/%d/hard-copy-check" % bill["id"]).json()
    assert [m["item"] for m in off["mismatches"]] == ["Value of work"] and off["mismatches"][0]["difference"] == -5000


def test_hard_copy_check_without_a_claude_key_says_it_cannot_see(tenant, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "only-groq")
    order, bill = a_draft(tenant)
    tenant.post("/api/sub-bills/%d/hardcopy" % bill["id"], files={"file": ("bill.pdf", PDF, "application/pdf")}, data={"amount": ""})
    out = tenant.post("/api/ai/subcontracts/bills/%d/hard-copy-check" % bill["id"]).json()
    assert out["available"] is False and out["reason"] == "needs_vision"


def test_the_brief_marks_a_contractor_with_lapsed_papers_as_careful(tenant, unkeyed):
    order, bill = a_draft(tenant)
    brief = tenant.get("/api/ai/subcontracts/contractors/%d/brief" % order["contractor_id"]).json()
    assert brief["standing"]["verdict"] == "careful" and "papers missing or lapsed" in brief["standing"]["flags"]


def test_another_companys_bill_and_contractor_are_not_reachable(tenant, second_tenant, unkeyed):
    order, bill = a_draft(tenant)
    assert second_tenant.get("/api/ai/subcontracts/bills/%d/review" % bill["id"]).status_code == 404
    assert second_tenant.post("/api/ai/subcontracts/bills/%d/hard-copy-check" % bill["id"]).status_code == 404
    assert second_tenant.get("/api/ai/subcontracts/contractors/%d/brief" % order["contractor_id"]).status_code == 404


def test_config_reads_the_environment_each_time(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", " abc ")
    assert config.anthropic_key() == "abc" and config.configured()
    monkeypatch.setenv("AI_MODEL_SMART", "claude-opus-5-5")
    assert config.model_smart() == "claude-opus-5-5"
