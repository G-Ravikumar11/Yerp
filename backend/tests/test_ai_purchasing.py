"""The AI functions for purchasing (backend/app/ai): purchase order review, supplier email, quote recommendation and
the quote reader. The model only words or reads; plain code finds the flags and checks everything it returns.

No network and no key are used: the model call is replaced in each test.
"""
from datetime import date, timedelta

import pytest

from app.ai import llm_client, po_review, po_supplier_email, quote_comparison, quote_reader
from app.ai.llm_client import AiResult
from test_comparative_statement import quote, rfq


def po(tenant, price=100, supplier="Steel Co", qty=10, **over):
    body = {"supplier_name": supplier, "supplier_email": "steel@example.com", "amount": price * qty,
            "line_items": [{"description": "TMT Fe500D 12mm", "item_code": "RM-STL", "qty": qty, "price": price}]}
    body.update(over)
    res = tenant.post("/api/purchase-orders", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def po_id(created):
    return created.get("id") or created["order"]["id"]


@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AI_ENABLED", "1")


@pytest.fixture
def unkeyed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


def says(text):
    return lambda *a, **k: AiResult(True, text=text, provider="groq", model="test", usage={"input": 1, "output": 1})


# --- which provider answers -------------------------------------------------------------------------------------------

def test_text_goes_to_groq_by_default_and_documents_go_to_claude(monkeypatch):
    calls = []
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "c")
    monkeypatch.setattr(llm_client, "_groq", lambda *a, **k: calls.append("groq") or AiResult(True, text="x", provider="groq"))
    monkeypatch.setattr(llm_client, "_claude", lambda *a, **k: calls.append("claude") or AiResult(True, text="x", provider="anthropic"))
    llm_client.ask("s", "p")
    llm_client.ask("s", "p", [llm_client.Attachment(b"x", "application/pdf")])
    assert calls == ["groq", "claude"]
    monkeypatch.setenv("AI_PROVIDER", "claude")
    llm_client.ask("s", "p")
    assert calls[-1] == "claude"


def test_groq_alone_reads_photos_and_text_pdfs_but_not_scanned_pdfs(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    seen = []
    monkeypatch.setattr(llm_client, "_groq", lambda system, prompt, mt, t, as_json=False, images=None: seen.append((prompt, images)) or AiResult(True, text="x", provider="groq"))
    monkeypatch.setattr(llm_client, "_claude", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Claude must not be called")))
    assert llm_client.ask("s", "p", [llm_client.Attachment(b"x", "image/png")]).ok
    assert seen[-1][1] and seen[-1][1][0].media_type == "image/png", "a photo goes to Groq's vision model"
    monkeypatch.setattr(llm_client.pdf_text, "extract_text", lambda data, **k: "Quotation No. 7 Cement OPC 53 rate 391 per bag " * 3)
    assert llm_client.ask("s", "p", [llm_client.Attachment(b"%PDF", "application/pdf")]).ok
    assert "Cement OPC 53" in seen[-1][0] and not seen[-1][1], "a PDF with text goes to Groq as words"
    monkeypatch.setattr(llm_client.pdf_text, "extract_text", lambda data, **k: "")
    assert llm_client.ask("s", "p", [llm_client.Attachment(b"%PDF", "application/pdf")]).reason == "scanned_pdf"
    big = llm_client.Attachment(b"x" * (llm_client.GROQ_MAX_IMAGE_BYTES + 1), "image/png")
    assert llm_client.ask("s", "p", [big]).reason == "too_big"


def test_a_photo_too_big_for_groq_goes_to_claude_when_there_is_a_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "c")
    calls = []
    monkeypatch.setattr(llm_client, "_groq", lambda *a, **k: calls.append("groq") or AiResult(True, text="x"))
    monkeypatch.setattr(llm_client, "_claude", lambda *a, **k: calls.append("claude") or AiResult(True, text="x"))
    llm_client.ask("s", "p", [llm_client.Attachment(b"x", "image/png")])
    llm_client.ask("s", "p", [llm_client.Attachment(b"x" * (llm_client.GROQ_MAX_IMAGE_BYTES + 1), "image/png")])
    assert calls == ["groq", "claude"]


# --- purchase order review ----------------------------------------------------------------------------------------------

def test_the_review_flags_a_price_above_the_last_one_paid_and_a_missing_gstin():
    last = {"rm-stl": (100.0, "PO-0001")}
    supplier = type("S", (), {"gstin": "", "name": "Steel Co"})()
    flags = po_review.find_flags({"supplier_name": "Steel Co", "needed_by": "", "billed_total": 0, "total": 1200, "status": "Draft",
                                  "line_items": [{"description": "TMT", "item_code": "RM-STL", "qty": 10, "price": 120}]},
                                 last, supplier, [])
    text = " | ".join(f["text"] for f in flags)
    assert "20% above" in text and "no GSTIN" in text and "No delivery date" in text


def test_a_line_with_no_price_or_a_bill_above_the_order_stops_it():
    flags = po_review.find_flags({"needed_by": "2099-01-01", "billed_total": 5000, "total": 4000, "status": "Approved",
                                  "line_items": [{"description": "Sand", "qty": 0, "price": 0}]}, {}, None, [])
    assert [f["level"] for f in flags].count("stop") == 3


def test_an_order_to_the_same_supplier_this_week_is_called_a_possible_duplicate(tenant, unkeyed):
    po(tenant, supplier="Steel Co", issue_date=date.today().isoformat())
    second = po(tenant, supplier="Steel Co", issue_date=date.today().isoformat())
    out = tenant.get("/api/ai/purchase-orders/%d/review" % po_id(second)).json()
    assert any("may be a duplicate" in f["text"] for f in out["flags"]) and out["summary"] is None


def test_a_later_order_at_a_higher_price_is_flagged_against_the_earlier(tenant, unkeyed):
    po(tenant, price=100, issue_date=(date.today() - timedelta(days=60)).isoformat())
    later = po(tenant, price=130, supplier="Other Steel", issue_date=date.today().isoformat())
    out = tenant.get("/api/ai/purchase-orders/%d/review" % po_id(later)).json()
    assert any("above the" in f["text"] for f in out["flags"])


def test_the_review_summary_is_written_from_the_flags_and_charged_through_the_wallet(tenant, groq, monkeypatch):
    created = po(tenant)
    seen = {}
    monkeypatch.setattr(po_review, "ask", lambda system, prompt, **k: seen.setdefault("p", prompt) and says("Ten bars from Steel Co.")())
    out = tenant.get("/api/ai/purchase-orders/%d/review" % po_id(created)).json()
    assert out["summary"] == "Ten bars from Steel Co." and "checks:" in seen["p"]


# --- supplier email -----------------------------------------------------------------------------------------------------

def test_the_email_is_always_a_draft_even_with_no_key(tenant, unkeyed):
    out = tenant.post("/api/ai/purchase-orders/%d/draft-email" % po_id(po(tenant))).json()
    assert out["written_by_ai"] is False and out["to"] == "steel@example.com"
    assert "Please find our purchase order" in out["body"] and out["subject"].startswith("Purchase order")


def test_the_model_may_reword_the_email_but_a_bad_answer_keeps_the_template(tenant, groq, monkeypatch):
    created = po(tenant)
    monkeypatch.setattr(po_supplier_email, "ask_json", lambda *a, **k: AiResult(True, data={"subject": "PO for steel", "body": "Dear team, please supply."}, model="test"))
    out = tenant.post("/api/ai/purchase-orders/%d/draft-email" % po_id(created)).json()
    assert out["written_by_ai"] is True and out["subject"] == "PO for steel"
    monkeypatch.setattr(po_supplier_email, "ask_json", lambda *a, **k: AiResult(True, data={"oops": 1}, model="test"))
    out = tenant.post("/api/ai/purchase-orders/%d/draft-email" % po_id(created)).json()
    assert out["written_by_ai"] is False and "Please find our purchase order" in out["body"]


# --- quote recommendation ----------------------------------------------------------------------------------------------

def test_the_flags_name_an_incomplete_quote_a_wide_spread_and_the_saving_from_a_split_award(tenant, unkeyed):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000)
    quote(tenant, r, "Half", 300, 0)
    c = quote(tenant, r, "Dalmia", 520, 61000)
    text = " | ".join(f["text"] for f in quote_comparison.find_flags(c))
    assert "Half quoted only 1 of the lines" in text and "above the cheapest" in text and "would cost" in text
    out = tenant.get("/api/ai/rfqs/%d/recommend" % r["rfq"]["id"]).json()
    assert out["l1"] and out["recommendation"] is None


def test_one_quote_is_not_a_comparison(tenant, unkeyed):
    r = rfq(tenant)
    c = quote(tenant, r, "ACC", 390, 62000)
    assert any("at least two" in f["text"] for f in quote_comparison.find_flags(c))


def test_an_expired_quote_stops_the_recommendation_and_the_model_is_given_the_checks(tenant, groq, monkeypatch):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000, valid_until="2020-01-01")
    quote(tenant, r, "UltraTech", 380, 63500)
    seen = {}
    monkeypatch.setattr(quote_comparison, "ask", lambda system, prompt, **k: seen.setdefault("p", prompt) and says("Award UltraTech.")())
    out = tenant.get("/api/ai/rfqs/%d/recommend" % r["rfq"]["id"]).json()
    assert any(f["level"] == "stop" and "expired" in f["text"] for f in out["flags"])
    assert out["recommendation"] == "Award UltraTech." and "expired" in seen["p"] and "landed" in seen["p"]


# --- the quote reader -----------------------------------------------------------------------------------------------------

def test_the_reader_keeps_only_lines_that_belong_to_the_enquiry():
    read = {"supplier_name": "ACC", "freight": 1500, "delivery_days": 7, "confidence": 0.9, "lines": [
        {"rfq_line_id": 5, "rate": 390, "tax_percent": 18, "remarks": "ex-works"},
        {"rfq_line_id": 99, "rate": 10},                      # not a line of this enquiry
        {"rfq_line_id": 6, "rate": "free"},                   # not a rate
        {"rfq_line_id": 5, "rate": 400}],                     # the same line twice
        "unmatched": ["Binding wire"]}
    out = quote_reader.clean(read, {5, 6})
    assert [l["rfq_line_id"] for l in out["lines"]] == [5] and out["lines"][0]["rate"] == 390
    assert out["freight"] == 1500 and out["delivery_days"] == 7
    assert "Binding wire" in out["unmatched"] and len(out["unmatched"]) == 4


def test_pasted_text_is_read_and_nothing_is_saved(tenant, groq, monkeypatch):
    r = rfq(tenant)
    ids = [l["rfq_line_id"] for l in r["lines"]]
    monkeypatch.setattr(quote_reader, "ask_json", lambda *a, **k: AiResult(True, model="test", data={
        "supplier_name": "ACC", "confidence": 0.95, "lines": [{"rfq_line_id": ids[0], "rate": 391}, {"rfq_line_id": 99999, "rate": 5}]}))
    out = tenant.post("/api/ai/rfqs/%d/read-quote" % r["rfq"]["id"], data={"text": "Cement OPC 53 at 391 per bag"}).json()
    assert out["available"] and out["lines_priced"] == 1 and out["lines_in_enquiry"] == 2 and len(out["unmatched"]) == 1
    assert tenant.get("/api/rfqs/%d" % r["rfq"]["id"]).json()["suppliers"] == [], "reading a quote records nothing"


def test_the_reader_needs_something_to_read_and_a_scanned_pdf_needs_the_claude_key(tenant, groq):
    r = rfq(tenant)
    assert tenant.post("/api/ai/rfqs/%d/read-quote" % r["rfq"]["id"]).status_code == 400
    out = tenant.post("/api/ai/rfqs/%d/read-quote" % r["rfq"]["id"], files={"file": ("q.pdf", b"%PDF-1.4", "application/pdf")}).json()
    assert out["available"] is False and out["reason"] == "scanned_pdf"
    assert tenant.post("/api/ai/rfqs/%d/read-quote" % r["rfq"]["id"], files={"file": ("q.exe", b"x", "application/octet-stream")}).status_code == 400


def test_another_company_cannot_reach_these(tenant, second_tenant, unkeyed):
    created, r = po(tenant), rfq(tenant)
    assert second_tenant.get("/api/ai/purchase-orders/%d/review" % po_id(created)).status_code == 404
    assert second_tenant.post("/api/ai/purchase-orders/%d/draft-email" % po_id(created)).status_code == 404
    assert second_tenant.get("/api/ai/rfqs/%d/recommend" % r["rfq"]["id"]).status_code == 404
    assert second_tenant.post("/api/ai/rfqs/%d/read-quote" % r["rfq"]["id"], data={"text": "x"}).status_code == 404
