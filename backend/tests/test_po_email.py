"""Sending a purchase order to the supplier by the company's Gmail. Nothing really goes out: the sender is replaced."""
import pytest

from _patching import patch_app
from test_ai_purchasing import po, po_id


@pytest.fixture
def sent(monkeypatch):
    out = []
    patch_app(monkeypatch, "send_email_background",
              lambda to, subject, body, frm, **k: out.append((to, subject, body, k)) or (True, "ok"))
    return out


def test_the_order_goes_to_the_supplier_with_its_pdf(tenant, sent):
    oid = po_id(po(tenant))
    res = tenant.post("/api/purchase-orders/%d/send-email" % oid, json={})
    assert res.status_code == 200, res.text
    to, subject, body, kw = sent[0]
    assert to == "steel@example.com" and subject.startswith("Purchase order") and kw["pdf_b64"]


def test_an_edited_draft_and_another_address_are_used(tenant, sent):
    oid = po_id(po(tenant))
    tenant.post("/api/purchase-orders/%d/send-email" % oid,
                json={"to": "other@example.com", "subject": "Steel", "body": "Please supply."})
    assert sent[0][:3] == ("other@example.com", "Steel", "Please supply.")


def test_a_bad_address_is_refused_and_a_failed_send_is_reported(tenant, monkeypatch):
    oid = po_id(po(tenant))
    assert tenant.post("/api/purchase-orders/%d/send-email" % oid, json={"to": "nope"}).status_code == 400
    patch_app(monkeypatch, "send_email_background", lambda *a, **k: (False, "Gmail refresh token not configured"))
    res = tenant.post("/api/purchase-orders/%d/send-email" % oid, json={})
    assert res.status_code == 502 and "refresh token" in res.text
