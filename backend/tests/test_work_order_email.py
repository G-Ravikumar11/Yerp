"""A work order is emailed to its sub contractor only when somebody clicks send, and only once it is approved."""
import pytest

from _patching import patch_app
from test_subcontract_orders import draft
from test_subcontractor_bills import live_order


@pytest.fixture
def mail(monkeypatch):
    out = []
    patch_app(monkeypatch, "send_email_background", lambda to, subject, body, frm, **k: out.append((to, subject, body, k)) or (True, ""))
    return out


def test_an_approved_order_goes_to_the_contractor_with_its_pdf(tenant, mail):
    order = live_order(tenant)
    tenant.put("/api/wo/contractors/%d" % order["contractor_id"], json={"company_name": "Rao Builders", "email": "rao@example.com"})
    d = tenant.get("/api/wo/orders/%d/email-draft" % order["id"]).json()
    assert d["to"] == "rao@example.com" and order["wo_number"] in d["subject"]
    assert mail == [], "asking for the draft sends nothing"
    res = tenant.post("/api/wo/orders/%d/send-email" % order["id"], json={"subject": "Your work order", "body": "Please sign."})
    assert res.status_code == 200, res.text
    to, subject, body, extra = mail[0]
    assert to == "rao@example.com" and subject == "Your work order" and body == "Please sign." and extra["pdf_b64"]


def test_a_draft_order_cannot_be_emailed(tenant, mail):
    order = draft(tenant)
    res = tenant.post("/api/wo/orders/%d/send-email" % order["id"], json={"to": "rao@example.com"})
    assert res.status_code == 409 and mail == []


def test_it_needs_a_real_address(tenant, mail):
    order = live_order(tenant)
    res = tenant.post("/api/wo/orders/%d/send-email" % order["id"], json={"to": "not-an-email"})
    assert res.status_code == 400 and mail == []
