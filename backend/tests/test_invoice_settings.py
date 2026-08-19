"""Settings that used to be stored and read by nothing.

invoice_prefix and default_payment_terms sat in the settings table for a long
time with no UI and no consumer, so every tenant was stuck on INV- and a
fortnight whatever they thought they had set.
"""
import pytest

import main


@pytest.fixture(autouse=True)
def _reset_limiter():
    main.rate_limiter._hits.clear()
    yield


def test_the_default_prefix_is_unchanged(tenant):
    assert tenant.get("/api/next-invoice-number").json()["next_number"].startswith("INV-")


def test_a_tenant_can_use_their_own_prefix(tenant):
    tenant.post("/api/settings", json={"invoice_prefix": "ACL-"})
    assert tenant.get("/api/next-invoice-number").json()["next_number"] == "ACL-0001"


def test_an_invoice_is_issued_with_that_prefix(tenant):
    tenant.post("/api/settings", json={"invoice_prefix": "ACL-"})
    inv = tenant.post("/api/invoices", json={
        "contact": "C", "email": "c@example.com", "issue_date": "2026-01-01",
        "due_date": "2026-01-31",
        "line_items": [{"description": "x", "qty": 1, "price": 10.0}],
    }).json()
    assert inv["number"] == "ACL-0001"


def test_numbering_continues_within_a_prefix(tenant):
    tenant.post("/api/settings", json={"invoice_prefix": "ACL-"})
    for _ in range(2):
        tenant.post("/api/invoices", json={
            "contact": "C", "email": "c@example.com", "issue_date": "2026-01-01",
            "due_date": "2026-01-31",
            "line_items": [{"description": "x", "qty": 1, "price": 10.0}],
        })
    assert tenant.get("/api/next-invoice-number").json()["next_number"] == "ACL-0003"


def test_changing_prefix_leaves_issued_invoices_alone(tenant):
    first = tenant.post("/api/invoices", json={
        "contact": "C", "email": "c@example.com", "issue_date": "2026-01-01",
        "due_date": "2026-01-31",
        "line_items": [{"description": "x", "qty": 1, "price": 10.0}],
    }).json()
    tenant.post("/api/settings", json={"invoice_prefix": "ACL-"})
    assert tenant.get(f"/api/invoices/{first['number']}").json()["number"] == first["number"]


@pytest.mark.parametrize("bad,expected", [
    ("", "INV-"),
    ("   ", "INV-"),
    ("<script>", "script"),          # stripped to safe characters
])
def test_a_silly_prefix_falls_back_or_is_cleaned(tenant, bad, expected):
    tenant.post("/api/settings", json={"invoice_prefix": bad})
    assert tenant.get("/api/next-invoice-number").json()["next_number"].startswith(expected)


def test_a_very_long_prefix_is_trimmed(tenant):
    tenant.post("/api/settings", json={"invoice_prefix": "A" * 50})
    number = tenant.get("/api/next-invoice-number").json()["next_number"]
    assert number.startswith("A" * 12)
    assert not number.startswith("A" * 13)


# --- payment terms -------------------------------------------------------------

def test_payment_terms_default_to_a_fortnight(tenant):
    assert tenant.get("/api/next-invoice-number").json()["payment_terms_days"] == 14


def test_a_tenant_can_set_their_own_terms(tenant):
    tenant.post("/api/settings", json={"default_payment_terms": "30"})
    assert tenant.get("/api/next-invoice-number").json()["payment_terms_days"] == 30


@pytest.mark.parametrize("bad", ["-5", "999", "abc", ""])
def test_silly_terms_fall_back(tenant, bad):
    tenant.post("/api/settings", json={"default_payment_terms": bad})
    assert tenant.get("/api/next-invoice-number").json()["payment_terms_days"] == 14


def test_one_tenant_s_prefix_is_not_another_s(client, tenant):
    import uuid
    tenant.post("/api/settings", json={"invoice_prefix": "ACL-"})

    other = f"other-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/client/register", json={
        "email": other, "password": "Passw0rdTest", "company_name": "Other Ltd"})
    client.post("/api/client/login", json={"email": other, "password": "Passw0rdTest"})
    assert client.get("/api/next-invoice-number").json()["next_number"] == "INV-0001"
