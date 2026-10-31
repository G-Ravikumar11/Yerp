"""Award goes straight to the supplier: awarding an enquiry sends its orders for approval, and the final approval
emails each order and its PDF to the supplier. Nothing really goes out: the sender is replaced."""
import pytest

from _patching import patch_app
from test_comparative_statement import quote, rfq
from test_jobs_and_orders import sign_in, sign_out, staff


@pytest.fixture
def sent(monkeypatch):
    out = []
    patch_app(monkeypatch, "send_email_background", lambda to, subject, body, frm, **k: out.append((to, subject, k.get("pdf_filename"))) or (True, "ok"))
    return out


def _supplier(tenant, name, email):
    res = tenant.post("/api/suppliers", json={"name": name, "email": email})
    assert res.status_code == 200, res.text


def test_the_masters_award_is_approved_and_sent_with_its_pdf(tenant, sent):
    _supplier(tenant, "ACC Cement", "sales@acc.example.com")
    r = rfq(tenant)
    quote(tenant, r, "ACC Cement", 390, 62000)
    res = tenant.post("/api/rfqs/%d/award" % r["rfq"]["id"], json={"mode": "lowest_per_line"})
    assert res.status_code == 200, res.text
    [order] = res.json()["orders"]
    assert order["approval"] == "approved"
    po = tenant.get("/api/purchase-orders/%d" % order["id"]).json()
    assert po["approval_status"] == "approved" and po["supplier_email"] == "sales@acc.example.com"
    assert sent == [("sales@acc.example.com", sent[0][1], "%s.pdf" % order["number"].replace("-", "_"))]


def test_a_staff_award_waits_for_approval_and_is_sent_only_when_approved(portal, tenant, sent):
    _supplier(tenant, "ACC Cement", "sales@acc.example.com")
    buyer = staff(tenant, permission_role="manager")
    r = rfq(tenant)
    quote(tenant, r, "ACC Cement", 390, 62000)
    sign_in(portal, buyer)
    res = portal.post("/api/rfqs/%d/award" % r["rfq"]["id"], json={"mode": "lowest_per_line"})
    sign_out(portal)
    assert res.status_code == 200, res.text
    [order] = res.json()["orders"]
    assert order["approval"] == "pending" and sent == []
    step = [i for i in tenant.get("/api/approvals/inbox").json()["items"] if i["kind"] == "step" and i["number"] == order["number"]][0]
    assert tenant.post("/api/approvals/decide", json={"kind": "step", "id": step["id"], "decision": "approve", "note": "ok"}).status_code == 200
    assert [s[0] for s in sent] == ["sales@acc.example.com"]


def test_an_order_with_no_supplier_email_is_approved_and_the_buyer_is_told(tenant, sent):
    r = rfq(tenant)
    quote(tenant, r, "Nobody Mailable", 390, 62000)
    res = tenant.post("/api/rfqs/%d/award" % r["rfq"]["id"], json={"mode": "lowest_per_line"})
    assert res.status_code == 200, res.text
    assert res.json()["orders"][0]["approval"] == "approved" and sent == []
    from app import db as database, models
    with database.SessionLocal() as db:
        alerts = db.query(models.DBAlert).filter(models.DBAlert.kind == "po_not_sent").all()
        assert any(res.json()["orders"][0]["number"] in a.title and "no email" in a.title for a in alerts)


def test_an_order_typed_by_hand_is_not_sent_by_itself(tenant, sent):
    res = tenant.post("/api/purchase-orders", json={"supplier_name": "Steel Co", "supplier_email": "s@example.com", "amount": 100, "total": 100,
                                                    "line_items": [{"description": "Steel", "qty": 1, "price": 100}]})
    assert res.status_code == 200, res.text
    body = tenant.get("/api/purchase-orders/%d" % res.json()["id"]).json()
    body["status"] = "Approved"
    assert tenant.put("/api/purchase-orders/%d" % body["id"], json=body).status_code == 200
    assert sent == []
