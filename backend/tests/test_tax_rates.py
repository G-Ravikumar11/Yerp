"""Tenant-defined tax rates.

The list is only a picker. Documents store the rendered label, so what matters
most here is that editing the list never restates a document already issued.
"""
import uuid

import pytest

import main


def test_a_new_tenant_gets_the_standard_list(tenant):
    rates = tenant.get("/api/tax-rates").json()
    labels = [r["label"] for r in rates]
    assert labels == ["20% VAT", "5% VAT", "0% Zero Rated", "No Tax"]
    assert sum(1 for r in rates if r["is_default"]) == 1


def test_a_tenant_can_define_their_own(tenant):
    res = tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "GST", "percent": 18, "is_default": True},
        {"name": "GST (reduced)", "percent": 5},
        {"name": "No Tax", "percent": 0},
    ]})
    assert res.status_code == 200, res.text
    assert [r["label"] for r in res.json()] == ["18% GST", "5% GST (reduced)", "No Tax"]


def test_a_custom_rate_actually_prices_a_line(tenant):
    tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "GST", "percent": 18, "is_default": True},
    ]})
    label = tenant.get("/api/tax-rates").json()[0]["label"]
    inv = tenant.post("/api/invoices", json={
        "contact": "C", "email": "c@example.com", "issue_date": "2026-01-01",
        "due_date": "2026-01-31", "tax_type": "exclusive",
        "line_items": [{"description": "x", "qty": 1, "price": 100.0, "tax_rate": label}],
    }).json()
    assert inv["subtotal"] == 100.0
    assert inv["tax_total"] == 18.0
    assert inv["total"] == 118.0


def test_editing_the_list_does_not_restate_an_issued_invoice(tenant):
    """The whole reason the label carries the percentage."""
    inv = tenant.post("/api/invoices", json={
        "contact": "C", "email": "c@example.com", "issue_date": "2026-01-01",
        "due_date": "2026-01-31", "tax_type": "exclusive",
        "line_items": [{"description": "x", "qty": 1, "price": 100.0,
                        "tax_rate": "20% VAT"}],
    }).json()
    assert inv["total"] == 120.0

    # The tenant later drops 20% entirely and moves to 10%.
    tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "VAT", "percent": 10, "is_default": True},
    ]})

    again = tenant.get(f"/api/invoices/{inv['number']}").json()
    assert again["total"] == 120.0
    assert again["line_items"][0]["tax_rate"] == "20% VAT"


def test_the_percentage_is_always_in_the_label(tenant):
    """A bare name would parse as the default rate and tax a line silently."""
    res = tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "Consulting levy", "percent": 0, "is_default": True},
    ]})
    label = res.json()[0]["label"]
    assert label == "0% Consulting levy"
    assert main.parse_tax_rate(label) == 0.0


def test_plain_no_tax_keeps_its_wording(tenant):
    res = tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "No Tax", "percent": 0, "is_default": True},
    ]})
    assert res.json()[0]["label"] == "No Tax"
    assert main.parse_tax_rate("No Tax") == 0.0


# --- validation --------------------------------------------------------------

@pytest.mark.parametrize("percent", [-1, 101, 500])
def test_a_rate_outside_nought_to_a_hundred_is_refused(tenant, percent):
    res = tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "Silly", "percent": percent},
    ]})
    assert res.status_code == 400
    assert "between 0 and 100" in res.json()["detail"]


def test_a_nameless_rate_is_refused(tenant):
    res = tenant.put("/api/tax-rates", json={"tax_rates": [{"name": "  ", "percent": 5}]})
    assert res.status_code == 400


def test_an_empty_list_is_refused(tenant):
    assert tenant.put("/api/tax-rates", json={"tax_rates": []}).status_code == 400


def test_duplicates_are_refused(tenant):
    res = tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "VAT", "percent": 20},
        {"name": "VAT", "percent": 20},
    ]})
    assert res.status_code == 400
    assert "twice" in res.json()["detail"]


def test_same_name_at_different_rates_is_fine(tenant):
    res = tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "VAT", "percent": 20},
        {"name": "VAT", "percent": 5},
    ]})
    assert res.status_code == 200
    assert [r["label"] for r in res.json()] == ["20% VAT", "5% VAT"]


def test_a_bad_row_leaves_the_existing_list_untouched(tenant):
    before = [r["label"] for r in tenant.get("/api/tax-rates").json()]
    res = tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "Fine", "percent": 10},
        {"name": "Broken", "percent": 900},
    ]})
    assert res.status_code == 400
    assert [r["label"] for r in tenant.get("/api/tax-rates").json()] == before


def test_exactly_one_default_survives(tenant):
    res = tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "A", "percent": 1, "is_default": True},
        {"name": "B", "percent": 2, "is_default": True},
        {"name": "C", "percent": 3},
    ]})
    defaults = [r["label"] for r in res.json() if r["is_default"]]
    assert defaults == ["1% A"]


def test_a_list_with_no_default_gets_one(tenant):
    res = tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "A", "percent": 1},
        {"name": "B", "percent": 2},
    ]})
    assert sum(1 for r in res.json() if r["is_default"]) == 1


# --- isolation ---------------------------------------------------------------

def test_one_tenant_s_rates_are_not_another_s(client, tenant):
    tenant.put("/api/tax-rates", json={"tax_rates": [
        {"name": "Secret Levy", "percent": 42, "is_default": True},
    ]})

    other = f"other-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/client/register", json={
        "email": other, "password": "Passw0rdTest", "company_name": "Other Ltd"})
    client.post("/api/client/login", json={"email": other, "password": "Passw0rdTest"})

    labels = [r["label"] for r in client.get("/api/tax-rates").json()]
    assert "42% Secret Levy" not in labels
    assert labels == ["20% VAT", "5% VAT", "0% Zero Rated", "No Tax"]


def test_tax_rates_require_a_session(client):
    assert client.get("/api/tax-rates").status_code == 401
    assert client.put("/api/tax-rates", json={"tax_rates": []}).status_code == 401
