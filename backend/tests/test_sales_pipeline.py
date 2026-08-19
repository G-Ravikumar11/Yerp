"""Quotes and invoices as one flow.

Stages are derived from the documents, so the interesting cases are the ones
where a document should move itself, or should drop off the board entirely.
"""
import uuid
from datetime import date, timedelta

import pytest

import main


@pytest.fixture(autouse=True)
def _reset_limiter():
    main.rate_limiter._hits.clear()
    yield


def make_quote(tenant, **overrides):
    payload = {
        "contact": "Prospect Ltd", "email": "buyer@example.com",
        "issue_date": "2026-01-01", "expiry_date": "2026-12-31",
        "tax_type": "none",
        "line_items": [{"description": "Work", "qty": 1, "price": 1000.0,
                        "tax_rate": "No Tax"}],
    }
    payload.update(overrides)
    res = tenant.post("/api/quotes", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def make_invoice(tenant, status="Awaiting Payment", price=400.0, due_in=14):
    # Issue always precedes due, including when the due date is in the past -
    # the API rightly refuses an invoice due before it was issued.
    due = date.today() + timedelta(days=due_in)
    issue = min(date.today(), due - timedelta(days=14))
    res = tenant.post("/api/invoices", json={
        "contact": "Customer Ltd", "email": "c@example.com",
        "issue_date": issue.strftime("%Y-%m-%d"),
        "due_date": due.strftime("%Y-%m-%d"),
        "status": status, "tax_type": "none",
        "line_items": [{"description": "Work", "qty": 1, "price": price,
                        "tax_rate": "No Tax"}],
    })
    assert res.status_code == 200, res.text
    return res.json()



def amount(totals, currency="GBP"):
    """Money is reported per currency now, because adding GBP to INR without a
    rate produces a number nobody can act on."""
    for t in totals or []:
        if t["currency"] == currency:
            return t["value"]
    return 0


def board(tenant):
    return tenant.get("/api/sales/pipeline").json()


def where(b, number):
    for stage in b["stages"]:
        for card in stage["cards"]:
            if card["number"] == number:
                return stage["key"], card
    return None, None


# --- shape --------------------------------------------------------------------

def test_the_board_has_the_money_stages_in_order(tenant):
    assert [s["key"] for s in board(tenant)["stages"]] == [
        "drafted", "sent", "accepted", "invoiced", "paid"]


def test_an_empty_board_is_all_zeros(tenant):
    b = board(tenant)
    assert b["outstanding"] == []
    assert all(s["count"] == 0 and s["totals"] == [] for s in b["stages"])


# --- a quote moving through ---------------------------------------------------

def test_a_new_quote_starts_in_drafted(tenant):
    q = make_quote(tenant)
    key, card = where(board(tenant), q["number"])
    assert key == "drafted"
    assert card["kind"] == "quote"
    assert card["total"] == 1000.0


def test_marking_a_quote_sent_moves_it(tenant):
    q = make_quote(tenant)
    tenant.post(f"/api/quotes/{q['number']}/status", json={"status": "Sent"})
    assert where(board(tenant), q["number"])[0] == "sent"


def test_accepting_a_quote_moves_it(tenant):
    q = make_quote(tenant)
    tenant.post(f"/api/quotes/{q['number']}/status", json={"status": "Accepted"})
    assert where(board(tenant), q["number"])[0] == "accepted"


def test_converting_hands_over_to_the_invoice(tenant):
    """The quote leaves the board; its invoice carries it from there, so the
    same money is never counted in two columns."""
    q = make_quote(tenant)
    res = tenant.post(f"/api/quotes/{q['number']}/convert", json={})
    inv_number = res.json()["invoice_number"]

    b = board(tenant)
    assert where(b, q["number"])[0] is None
    assert where(b, inv_number)[0] == "drafted"      # converted invoices start as drafts


def test_a_declined_quote_leaves_the_board_and_counts_as_lost(tenant):
    q = make_quote(tenant)
    tenant.post(f"/api/quotes/{q['number']}/status", json={"status": "Declined"})

    b = board(tenant)
    assert where(b, q["number"])[0] is None
    assert b["lost"]["count"] == 1
    assert amount(b["lost"]["totals"]) == 1000.0


def test_an_expired_quote_counts_as_lost(tenant):
    make_quote(tenant, issue_date="2020-01-01", expiry_date="2020-02-01")
    assert board(tenant)["lost"]["count"] == 1


# --- invoices -----------------------------------------------------------------

def test_an_issued_invoice_sits_in_invoiced(tenant):
    inv = make_invoice(tenant)
    key, card = where(board(tenant), inv["number"])
    assert key == "invoiced"
    assert card["kind"] == "invoice"
    assert card["outstanding"] == 400.0


def test_a_paid_invoice_moves_to_paid(tenant):
    inv = make_invoice(tenant)
    tenant.post(f"/api/invoices/{inv['number']}/mark-paid")
    key, _ = where(board(tenant), inv["number"])
    assert key == "paid"


def test_outstanding_counts_only_what_is_still_owed(tenant):
    make_invoice(tenant, price=400.0)
    paid = make_invoice(tenant, price=250.0)
    tenant.post(f"/api/invoices/{paid['number']}/mark-paid")

    b = board(tenant)
    assert amount(b["outstanding"]) == 400.0


def test_an_overdue_invoice_is_flagged(tenant):
    inv = make_invoice(tenant, due_in=-5)
    _, card = where(board(tenant), inv["number"])
    assert card["is_overdue"] is True
    assert card["days_overdue"] >= 5
    assert board(tenant)["overdue_count"] == 1


def test_a_void_invoice_is_off_the_board(tenant):
    inv = make_invoice(tenant)
    tenant.put(f"/api/invoices/{inv['number']}", json={
        "contact": "Customer Ltd", "email": "c@example.com",
        "issue_date": inv["date"], "due_date": inv["due_date"],
        "status": "Void", "tax_type": "none",
        "line_items": [{"description": "Work", "qty": 1, "price": 400.0,
                        "tax_rate": "No Tax"}],
    })
    assert where(board(tenant), inv["number"])[0] is None


def test_stage_values_add_up(tenant):
    make_quote(tenant)                       # 1000, drafted
    make_invoice(tenant, price=400.0)        # 400, invoiced

    b = board(tenant)
    by_key = {s["key"]: s for s in b["stages"]}
    assert amount(by_key["drafted"]["totals"]) == 1000.0
    assert amount(by_key["invoiced"]["totals"]) == 400.0


# --- isolation ----------------------------------------------------------------

def test_the_board_is_per_tenant(client, tenant):
    make_quote(tenant)
    make_invoice(tenant)

    other = f"other-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/client/register", json={
        "email": other, "password": "Passw0rdTest", "company_name": "Other Ltd"})
    client.post("/api/client/login", json={"email": other, "password": "Passw0rdTest"})

    b = client.get("/api/sales/pipeline").json()
    assert all(s["count"] == 0 for s in b["stages"])
    assert b["outstanding"] == []


def test_the_board_needs_a_session(client):
    assert client.get("/api/sales/pipeline").status_code == 401


def test_currencies_are_totalled_separately(tenant):
    """The bug this replaced: pounds and rupees added into one figure, printed
    with a single symbol. In production that read as forty-four trillion."""
    tenant.post("/api/invoices", json={
        "contact": "UK", "email": "uk@example.com",
        "issue_date": "2026-01-01", "due_date": "2026-01-31",
        "status": "Awaiting Payment", "tax_type": "none", "currency": "GBP",
        "line_items": [{"description": "w", "qty": 1, "price": 100.0, "tax_rate": "No Tax"}],
    })
    tenant.post("/api/invoices", json={
        "contact": "IN", "email": "in@example.com",
        "issue_date": "2026-01-01", "due_date": "2026-01-31",
        "status": "Awaiting Payment", "tax_type": "none", "currency": "INR",
        "line_items": [{"description": "w", "qty": 1, "price": 5000.0, "tax_rate": "No Tax"}],
    })

    b = board(tenant)
    invoiced = next(s for s in b["stages"] if s["key"] == "invoiced")
    by = {t["currency"]: t["value"] for t in invoiced["totals"]}
    assert by == {"GBP": 100.0, "INR": 5000.0}
    # Never one merged number.
    assert len(invoiced["totals"]) == 2
    assert {t["currency"]: t["value"] for t in b["outstanding"]} == {"GBP": 100.0, "INR": 5000.0}


def test_a_long_column_is_capped_with_a_count(tenant):
    """A column of hundreds used to stretch the page past a screen of nothing."""
    for i in range(45):
        tenant.post("/api/invoices", json={
            "contact": f"C{i}", "email": "c@example.com",
            "issue_date": "2026-01-01", "due_date": "2026-01-31",
            "status": "Awaiting Payment", "tax_type": "none",
            "line_items": [{"description": "w", "qty": 1, "price": 10.0, "tax_rate": "No Tax"}],
        })
    invoiced = next(s for s in board(tenant)["stages"] if s["key"] == "invoiced")
    assert invoiced["count"] == 45
    assert invoiced["shown"] == 40
    assert len(invoiced["cards"]) == 40
