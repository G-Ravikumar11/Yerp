"""AI for the measurement book and the readers for sheets and papers. The model call is replaced in each test.

The findings are plain code: they must be right with no key at all. The readers return only rows that name a real item
and save nothing.
"""
from datetime import date

import pytest

from Ai_service import compliance_reader, measurement_analysis, measurement_reader
from Ai_service.llm_client import AiResult
from test_ai_subcontracts import a_draft, unkeyed  # noqa: F401  (fixtures)
from test_delete_work_order import book

TODAY = date(2026, 6, 15)
ITEM = {"id": 1, "label": "1.1 Footing", "uom": "cum", "quantity": 100, "rate": 1000, "tolerance": 0}


def entry(qty, on="2026-06-01", loc="A", item=1, kind=""):
    return {"id": 0, "item_id": item, "quantity": qty, "location": loc, "measured_on": on, "kind": kind}


def texts(out):
    return " | ".join(f["text"] for f in out["findings"])


def test_measuring_past_the_ordered_quantity_is_a_stop_and_tolerance_is_respected():
    over = measurement_analysis.find_findings([ITEM], [entry(105)], "2026-06-01", "2026-12-01", TODAY)
    assert over["findings"][0]["level"] == "stop" and "5.0% over" in over["findings"][0]["text"]
    allowed = dict(ITEM, tolerance=10)
    ok = measurement_analysis.find_findings([allowed], [entry(105)], "2026-06-01", "2026-12-01", TODAY)
    assert not [f for f in ok["findings"] if f["level"] == "stop"]


def test_an_item_with_nothing_measured_late_in_the_order_is_flagged():
    out = measurement_analysis.find_findings([ITEM], [], "2026-01-01", "2026-07-01", TODAY)
    assert "nothing measured" in texts(out)
    early = measurement_analysis.find_findings([ITEM], [], "2026-06-01", "2026-12-31", TODAY)
    assert "nothing measured" not in texts(early)


def test_an_entry_far_above_the_usual_a_double_entry_and_a_future_date_are_flagged():
    entries = [entry(5, loc="A"), entry(6, loc="B"), entry(5, loc="C"), entry(6, loc="D"), entry(60, loc="E"),
               entry(7, on="2026-06-10", loc="F"), entry(7, on="2026-06-10", loc="F"), entry(3, on="2027-01-01", loc="G")]
    out = measurement_analysis.find_findings([dict(ITEM, quantity=1000)], entries, "2026-06-01", "2027-06-01", TODAY)
    said = texts(out)
    assert "more than three times" in said and "measured twice" in said and "in the future" in said


def test_work_behind_time_is_noted_and_holds_are_not_counted_as_work():
    out = measurement_analysis.find_findings([ITEM], [entry(10), entry(500, kind="hold")], "2026-05-01", "2026-07-01", TODAY)
    assert out["measured_value"] == 10000 and "Work is behind" in texts(out)


def test_the_analysis_works_without_a_key_and_reads_the_real_book(tenant, unkeyed):
    order, _bill = a_draft(tenant, qty=10)
    out = tenant.get("/api/ai/subcontracts/orders/%d/measurement-analysis" % order["id"]).json()
    assert out["available"] is False and out["entries"] >= 1 and out["rows"] and out["measured_value"] > 0


def test_with_a_key_the_model_words_the_summary(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setattr(measurement_analysis, "ask", lambda *a, **k: AiResult(True, text="Work has started.", provider="groq", model="t"))
    order, _bill = a_draft(tenant)
    out = tenant.get("/api/ai/subcontracts/orders/%d/measurement-analysis" % order["id"]).json()
    assert out["available"] and out["summary"] == "Work has started."


def test_a_sheet_is_read_into_rows_for_real_items_only_and_nothing_is_saved(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    order, _bill = a_draft(tenant, qty=10)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    before = book(tenant, order["id"])["lines"][0]
    monkeypatch.setattr(measurement_reader, "ask_json", lambda *a, **k: AiResult(True, model="t", data={
        "confidence": 0.9, "rows": [{"item_id": item, "quantity": 4.5, "location": "Block A", "measured_on": "2026-06-02"},
                                    {"item_id": 99999, "quantity": 3}, {"item_id": item, "quantity": "none"}],
        "unmatched": ["Painting"]}))
    out = tenant.post("/api/ai/subcontracts/orders/%d/read-measurements" % order["id"], data={"text": "Block A footing 4.5 cum"}).json()
    assert out["available"] and len(out["rows"]) == 1 and out["rows"][0]["quantity"] == 4.5
    assert len(out["unmatched"]) == 3
    assert book(tenant, order["id"])["lines"][0] == before, "reading a sheet records nothing"
    assert tenant.post("/api/ai/subcontracts/orders/%d/read-measurements" % order["id"]).status_code == 400


def test_a_paper_is_read_checked_against_the_fixed_kinds_and_the_holder(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    order, _bill = a_draft(tenant)
    monkeypatch.setattr(compliance_reader, "ask_json", lambda *a, **k: AiResult(True, model="t", data={
        "kind": "esi", "number": "ESI-1", "holder_name": "Totally Different Traders", "valid_from": "2026-01-01",
        "valid_to": "2027-01-01", "confidence": 0.5}))
    out = tenant.post("/api/ai/subcontracts/contractors/%d/read-document" % order["contractor_id"], data={"text": "ESI certificate"}).json()
    assert out["available"] and out["kind"] == "esi" and out["valid_to"] == "2027-01-01"
    assert out["low_confidence"] and any("does not look like" in w for w in out["warnings"])


def test_clean_paper_drops_an_unknown_kind_and_a_bad_date():
    out = compliance_reader.clean({"kind": "driving", "valid_to": "31/12/2027"}, "Sri Ram Constructions")
    assert out["kind"] == "other" and out["valid_to"] == "" and any("expiry" in w for w in out["warnings"])


def test_another_company_cannot_reach_these(tenant, second_tenant, unkeyed):
    order, _bill = a_draft(tenant)
    assert second_tenant.get("/api/ai/subcontracts/orders/%d/measurement-analysis" % order["id"]).status_code == 404
    assert second_tenant.post("/api/ai/subcontracts/orders/%d/read-measurements" % order["id"], data={"text": "x"}).status_code == 404
    assert second_tenant.post("/api/ai/subcontracts/contractors/%d/read-document" % order["contractor_id"], data={"text": "x"}).status_code == 404


def test_each_finding_about_one_entry_is_tied_to_it_so_the_table_can_mark_it():
    entries = [entry(5, loc="A"), entry(6, loc="B"), entry(5, loc="C"), entry(6, loc="D"), dict(entry(60, loc="E"), id=77)]
    out = measurement_analysis.find_findings([dict(ITEM, quantity=1000)], entries, "2026-06-01", "2027-06-01", TODAY)
    assert 77 in out["by_entry"] and out["by_entry"][77][0]["level"] == "check"


def test_the_plain_checks_alone_are_free_and_never_call_the_model(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setattr(measurement_analysis, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model call")))
    order, _bill = a_draft(tenant)
    out = tenant.get("/api/ai/subcontracts/orders/%d/measurement-analysis?ai=0" % order["id"]).json()
    assert out["by_entry"] is not None and out["available"] is False and out["summary"] == ""


def test_a_question_about_the_book_is_answered_from_its_own_figures(tenant, monkeypatch):
    from Ai_service import measurement_ask
    monkeypatch.setenv("GROQ_API_KEY", "g")
    seen = {}
    def fake(system, prompt, *a, **k):
        seen["prompt"] = prompt
        return AiResult(True, text="Ten units are measured.", provider="groq", model="t")
    monkeypatch.setattr(measurement_ask, "ask", fake)
    order, _bill = a_draft(tenant, qty=10)
    out = tenant.post("/api/ai/subcontracts/orders/%d/ask-book" % order["id"], json={"question": "How much is measured?"}).json()
    assert out["available"] and out["answer"] == "Ten units are measured."
    assert "measured 10" in seen["prompt"] and "Question: How much is measured?" in seen["prompt"]
    assert tenant.post("/api/ai/subcontracts/orders/%d/ask-book" % order["id"], json={"question": "  "}).status_code == 400


def test_asking_without_a_key_says_so_and_another_company_cannot_ask(tenant, second_tenant, unkeyed):
    order, _bill = a_draft(tenant)
    out = tenant.post("/api/ai/subcontracts/orders/%d/ask-book" % order["id"], json={"question": "Anything odd?"}).json()
    assert out["available"] is False and out["answer"] == ""
    assert second_tenant.post("/api/ai/subcontracts/orders/%d/ask-book" % order["id"], json={"question": "x"}).status_code == 404
