"""Buying in "What needs you": orders billed ahead of their goods, late deliveries, indent lines nobody is buying for,
and drawings waiting for approval - and the morning digest opening with what is owed both ways and the cash."""
from datetime import date, datetime, timedelta

from app import db as database
import main
from test_goods_receipt import order, project


def attention(tenant):
    res = tenant.get("/api/attention")
    assert res.status_code == 200, res.text
    return {i["kind"]: i for i in res.json()["items"]}, res.json()["summary"]


def test_an_order_billed_ahead_of_its_goods_needs_you(tenant):
    po = order(tenant)
    tenant.post("/api/bills", json={"number": "SUP-9", "vendor_name": "Steel Co", "total": 600000, "amount": 600000, "purchase_order_id": po["id"]})
    items, summary = attention(tenant)
    a = items["billed_ahead"]
    assert a["severity"] == "money" and a["value"] == 600000 and po["number"] in a["detail"]
    assert summary["money_at_stake"] >= 600000


def test_a_late_delivery_needs_you(tenant):
    po = order(tenant)
    body = tenant.get("/api/purchase-orders/%d" % po["id"]).json()
    body["needed_by"] = (date.today() - timedelta(days=4)).isoformat()
    assert tenant.put("/api/purchase-orders/%d" % po["id"], json=body).status_code == 200
    items, _ = attention(tenant)
    assert po["number"] in items["late_deliveries"]["detail"] and "4 days late" in items["late_deliveries"]["detail"]


def test_a_drawing_waiting_for_approval_needs_you(tenant):
    import io
    from test_project_files import PDF
    j = project(tenant)
    d = tenant.post("/api/jobs/%d/drawings" % j["id"], json={"number": "STR-7", "title": "Raft"}).json()["drawing"]
    r = tenant.post("/api/drawings/%d/revisions" % d["id"], files={"file": ("STR-7-R0.pdf", io.BytesIO(PDF), "application/pdf")},
                    data={"revision": "R0", "status": "For approval"})
    assert r.status_code == 200, r.text
    items, _ = attention(tenant)
    assert "STR-7" in items["drawings_for_approval"]["detail"]


def test_the_morning_digest_opens_with_the_money(tenant):
    po = order(tenant)
    tenant.post("/api/bills", json={"number": "SUP-10", "vendor_name": "Steel Co", "total": 1000, "amount": 1000,
                                    "purchase_order_id": po["id"], "status": "Awaiting Payment"})
    tenant.post("/api/bank-accounts", json={"name": "SBI current", "kind": "Bank", "opening_balance": 250000})
    s = database.SessionLocal()
    try:
        main.job_morning_digest(s, datetime(2026, 9, 26, 8, 0))
    finally:
        s.close()
    digest = [a for a in tenant.get("/api/alerts").json()["alerts"] if a["kind"] == "daily_digest"]
    body = digest[0]["body"]
    assert body.startswith("Owed to us:") and "We owe: \u20b91,000.00" in body and "Cash in all accounts: \u20b92,50,000.00" in body
    assert "Billed ahead of the goods" in body
