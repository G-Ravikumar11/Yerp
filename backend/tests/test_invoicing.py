"""Invoice maths, payment flow and tenant isolation."""
import pytest

from conftest import make_invoice
from main import compute_invoice_totals, parse_tax_rate


class _Line:
    def __init__(self, qty, price, tax_rate, disc=0):
        self.qty, self.price, self.tax_rate, self.disc = qty, price, tax_rate, disc


# --- tax label parsing -----------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("20% VAT", 0.20),
    ("5% VAT", 0.05),
    ("0% Zero Rated", 0.0),
    ("No Tax", 0.0),
    ("20% (VAT on Income)", 0.20),
    ("17.5% VAT", 0.175),
    ("", 0.20),          # empty falls back to the default
    (None, 0.20),
])
def test_parse_tax_rate(label, expected):
    assert parse_tax_rate(label) == pytest.approx(expected)


def test_line_items_use_their_own_tax_rate():
    """The bug this guards: every line was taxed at 20% regardless of the rate
    chosen in the UI."""
    lines = [
        _Line(1, 100.0, "20% VAT"),
        _Line(1, 100.0, "5% VAT"),
        _Line(1, 100.0, "No Tax"),
    ]
    subtotal, tax, total = compute_invoice_totals(lines, "exclusive")
    assert subtotal == 300.00
    assert tax == 25.00          # 20 + 5 + 0, not 60
    assert total == 325.00


def test_inclusive_tax_backs_out_the_right_amount():
    subtotal, tax, total = compute_invoice_totals([_Line(1, 120.0, "20% VAT")], "inclusive")
    assert subtotal == 100.00
    assert tax == 20.00
    assert total == 120.00


def test_discount_applies_before_tax():
    subtotal, tax, total = compute_invoice_totals([_Line(2, 100.0, "20% VAT", disc=10)], "exclusive")
    assert subtotal == 180.00
    assert tax == 36.00
    assert total == 216.00


def test_no_tax_type_charges_nothing():
    subtotal, tax, total = compute_invoice_totals([_Line(1, 100.0, "20% VAT")], "none")
    assert (subtotal, tax, total) == (100.00, 0.0, 100.00)


# --- creation and validation ----------------------------------------------

def test_create_invoice_totals_match_mixed_rates(tenant):
    inv = make_invoice(tenant, line_items=[
        {"description": "A", "qty": 1, "price": 100.0, "tax_rate": "20% VAT"},
        {"description": "B", "qty": 1, "price": 100.0, "tax_rate": "5% VAT"},
    ])
    assert inv["subtotal"] == 200.00
    assert inv["tax_total"] == 25.00
    assert inv["due"] == 225.00


def test_duplicate_invoice_number_is_a_conflict_not_a_crash(tenant):
    inv = make_invoice(tenant, invoice_number="INV-9001")
    res = tenant.post("/api/invoices", json={
        "contact": "Other", "issue_date": "2026-01-01", "due_date": "2026-01-31",
        "invoice_number": inv["number"],
        "line_items": [{"description": "X", "qty": 1, "price": 10.0}],
    })
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_invoice_requires_line_items(tenant):
    res = tenant.post("/api/invoices", json={
        "contact": "C", "issue_date": "2026-01-01", "due_date": "2026-01-31", "line_items": [],
    })
    assert res.status_code == 400


def test_due_date_cannot_precede_issue_date(tenant):
    res = tenant.post("/api/invoices", json={
        "contact": "C", "issue_date": "2026-02-01", "due_date": "2026-01-01",
        "line_items": [{"description": "X", "qty": 1, "price": 10.0}],
    })
    assert res.status_code == 400


def test_negative_price_rejected(tenant):
    res = tenant.post("/api/invoices", json={
        "contact": "C", "issue_date": "2026-01-01", "due_date": "2026-01-31",
        "line_items": [{"description": "X", "qty": 1, "price": -10.0}],
    })
    assert res.status_code == 400


def test_invoice_numbers_do_not_collide_after_a_delete(tenant):
    first = make_invoice(tenant)
    second = make_invoice(tenant)
    assert tenant.delete(f"/api/invoices/{second['number']}").status_code == 200
    third = make_invoice(tenant)
    # Sequence is based on the highest number issued, so it must not reuse the
    # deleted one and collide with `first`.
    assert third["number"] != first["number"]
    assert third["number"] == second["number"] or third["number"] > second["number"]


# --- payments --------------------------------------------------------------

def test_partial_payment_moves_status_and_balance(tenant):
    inv = make_invoice(tenant)          # 100 + 20% = 120
    assert inv["due"] == 120.00

    res = tenant.post(f"/api/invoices/{inv['number']}/payments", json={"amount": 50.0})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Partially Paid"
    assert body["paid"] == 50.00
    assert body["due"] == 70.00

    res = tenant.post(f"/api/invoices/{inv['number']}/payments", json={"amount": 70.0})
    assert res.json()["status"] == "Paid"
    assert res.json()["due"] == 0.0


def test_overpayment_is_rejected(tenant):
    inv = make_invoice(tenant)
    res = tenant.post(f"/api/invoices/{inv['number']}/payments", json={"amount": 999.0})
    assert res.status_code == 400
    assert "exceeds" in res.json()["detail"]


def test_zero_or_negative_payment_rejected(tenant):
    inv = make_invoice(tenant)
    assert tenant.post(f"/api/invoices/{inv['number']}/payments", json={"amount": 0}).status_code == 400
    assert tenant.post(f"/api/invoices/{inv['number']}/payments", json={"amount": -5}).status_code == 400


def test_payment_can_be_reversed(tenant):
    inv = make_invoice(tenant)
    pay = tenant.post(f"/api/invoices/{inv['number']}/payments", json={"amount": 40.0}).json()
    res = tenant.delete(f"/api/invoices/{inv['number']}/payments/{pay['payment_id']}")
    assert res.status_code == 200
    assert res.json()["paid"] == 0.0
    assert res.json()["due"] == 120.00


def test_mark_paid_records_a_ledger_entry(tenant):
    inv = make_invoice(tenant)
    tenant.post(f"/api/invoices/{inv['number']}/mark-paid")
    detail = tenant.get(f"/api/invoices/{inv['number']}").json()
    assert detail["status"] == "Paid"
    assert detail["due"] == 0.0
    assert len(detail["payments"]) == 1
    assert detail["payments"][0]["amount"] == 120.00


# --- editing ---------------------------------------------------------------

def test_edit_invoice_recomputes_totals(tenant):
    inv = make_invoice(tenant)
    res = tenant.put(f"/api/invoices/{inv['number']}", json={
        "contact": "Customer Ltd", "issue_date": "2026-01-01", "due_date": "2026-01-31",
        "tax_type": "exclusive",
        "line_items": [{"description": "Bigger job", "qty": 2, "price": 250.0, "tax_rate": "5% VAT"}],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["subtotal"] == 500.00
    assert body["tax_total"] == 25.00
    assert body["due"] == 525.00
    assert len(body["line_items"]) == 1


def test_cannot_edit_an_invoice_with_payments(tenant):
    inv = make_invoice(tenant)
    tenant.post(f"/api/invoices/{inv['number']}/payments", json={"amount": 10.0})
    res = tenant.put(f"/api/invoices/{inv['number']}", json={
        "contact": "X", "issue_date": "2026-01-01", "due_date": "2026-01-31",
        "line_items": [{"description": "Y", "qty": 1, "price": 1.0}],
    })
    assert res.status_code == 409


# --- overdue / aging -------------------------------------------------------

def test_overdue_flag_and_aging_buckets(tenant):
    inv = make_invoice(tenant, issue_date="2020-01-01", due_date="2020-01-31")
    tenant.post(f"/api/invoices/{inv['number']}/payments", json={"amount": 20.0})

    listing = {i["number"]: i for i in tenant.get("/api/invoices").json()}
    assert listing[inv["number"]]["is_overdue"] is True
    assert listing[inv["number"]]["days_overdue"] > 90

    aging = tenant.get("/api/reports/aged-receivables").json()
    assert aging["buckets"]["over_90"] >= 100.00
    assert any(row["number"] == inv["number"] for row in aging["invoices"])


def test_draft_invoice_is_never_overdue(tenant):
    inv = make_invoice(tenant, issue_date="2020-01-01", due_date="2020-01-31", status="Draft")
    listing = {i["number"]: i for i in tenant.get("/api/invoices").json()}
    assert listing[inv["number"]]["is_overdue"] is False


# --- multi-tenancy ---------------------------------------------------------

def test_one_tenant_cannot_read_anothers_invoice(client, tenant):
    inv = make_invoice(tenant)
    client.post("/api/client/logout")
    client.post("/api/client/register", json={
        "email": "intruder@example.com", "password": "Passw0rdTest", "company_name": "Other",
    })
    client.post("/api/client/login", json={"email": "intruder@example.com", "password": "Passw0rdTest"})

    assert client.get(f"/api/invoices/{inv['number']}").status_code == 404
    assert client.delete(f"/api/invoices/{inv['number']}").status_code == 404
    assert client.post(f"/api/invoices/{inv['number']}/payments", json={"amount": 1}).status_code == 404
    assert client.get("/api/invoices").json() == []


def test_anonymous_access_is_refused(client):
    client.post("/api/client/logout")
    assert client.get("/api/invoices").status_code == 401
    assert client.get("/api/dashboard-summary").status_code == 401
