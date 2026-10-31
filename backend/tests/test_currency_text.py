"""Amounts in the company's own currency in the emails it sends, and one overtime multiplier for pay and costing."""
import pytest

from _patching import patch_app
from app.core.currency import money_text


@pytest.mark.parametrize("code,amount,expected", [
    ("INR", 1500000, "₹15,00,000.00"),     # rupees grouped the Indian way
    ("INR", 999.5, "₹999.50"),
    ("", 1234.5, "₹1,234.50"),              # no currency set: rupees
    ("USD", 1234.5, "$1,234.50"),
    ("GBP", 99, "£99.00"),
])
def test_money_text(code, amount, expected):
    assert money_text(code, amount) == expected


def test_the_invoice_email_draft_names_the_amount_in_rupees(tenant, monkeypatch):
    patch_app(monkeypatch, "llm_chat", lambda *a, **k: None)         # the model is down: the plain fallback is used
    res = tenant.post("/api/ai/personalize-email", json={"client_name": "Acme", "invoice_number": "INV-1", "total": 150000,
                                                         "due_date": "2026-11-30"})
    assert res.status_code == 200, res.text
    body = res.json()["body"]
    assert "₹1,50,000.00" in body and "£" not in body


def test_the_reminder_draft_names_the_amount_in_rupees(tenant, monkeypatch):
    patch_app(monkeypatch, "llm_chat", lambda *a, **k: None)
    res = tenant.post("/api/ai/generate-followup", json={"client_name": "Acme", "invoice_number": "INV-1", "total": 25000, "days_overdue": 12})
    assert res.status_code == 200, res.text
    assert "₹25,000.00" in res.json()["body"] and "£" not in res.json()["body"]


def test_job_costing_prices_overtime_at_the_same_multiplier_as_payroll():
    from app.constants.common import OVERTIME_MULTIPLIER
    from app.services import payroll, plant
    assert OVERTIME_MULTIPLIER == 2.0 and payroll.OVERTIME_MULTIPLIER is OVERTIME_MULTIPLIER
    assert plant.OVERTIME_MULTIPLIER is OVERTIME_MULTIPLIER
