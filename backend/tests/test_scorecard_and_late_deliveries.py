"""The supplier scorecard (on time, rejected, price against L1, how fast they answer) beside each supplier in the
comparison and emailed monthly to purchasing; and late deliveries chased until goods arrive. The sender is replaced."""
from datetime import date, datetime, timedelta

import pytest

import main
from app import db as database, models
from _patching import patch_app
from test_comparative_statement import quote, rfq
from test_goods_receipt import post as post_grn, receipt, set_lines


@pytest.fixture
def sent(monkeypatch):
    out = []
    patch_app(monkeypatch, "send_email_background", lambda to, subject, body, frm, **k: out.append((to, subject, body)) or (True, "ok"))
    return out


def order(tenant, supplier, needed_by, qty=10):
    body = {"supplier_name": supplier, "needed_by": needed_by, "amount": qty * 100, "line_items": [{"description": "Cement", "qty": qty, "price": 100}]}
    po = tenant.post("/api/purchase-orders", json=body).json()
    assert tenant.put("/api/purchase-orders/%d" % po["id"], json={**body, "status": "Approved"}).status_code == 200
    return tenant.get("/api/purchase-orders/%d" % po["id"]).json()


def deliver(tenant, po, received, rejected=0):
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": received, "accepted_qty": received - rejected, "rejected_qty": rejected}])
    post_grn(tenant, grn)


def run(job, day):
    with database.SessionLocal() as db:
        db.query(models.DBJobRun).filter(models.DBJobRun.job_name == job).delete()
        db.commit()
    return main.run_due_jobs(now=datetime.combine(day, datetime.min.time()).replace(hour=9), only=job)


def test_the_scorecard_sits_beside_each_supplier_in_the_comparison(tenant):
    late = order(tenant, "ACC Cement", (date.today() - timedelta(days=3)).isoformat())
    deliver(tenant, late, 10, rejected=1)                             # delivered today: after its date; 1 of 10 rejected
    on_time = order(tenant, "ACC Cement", (date.today() + timedelta(days=3)).isoformat())
    deliver(tenant, on_time, 10)
    r = rfq(tenant)
    quote(tenant, r, "ACC Cement", 400, 63000)
    quote(tenant, r, "UltraTech", 380, 61000)                        # UltraTech is L1
    st = tenant.get("/api/rfqs/%d/statement" % r["rfq"]["id"]).json()
    cards = {s["supplier_name"]: s["scorecard"] for s in st["suppliers"]}
    acc = cards["ACC Cement"]
    assert (acc["on_time_pct"], acc["orders_scored"], acc["rejection_pct"]) == (50.0, 2, 5.0)
    assert acc["l1_wins"] == 0 and acc["above_l1_pct"] > 0
    assert cards["UltraTech"]["l1_wins"] == 1 and cards["UltraTech"]["above_l1_pct"] == 0.0


def test_the_monthly_scorecard_goes_to_purchasing_only_when_named(tenant, sent):
    order(tenant, "ACC Cement", (date.today() + timedelta(days=3)).isoformat())
    r = rfq(tenant)
    quote(tenant, r, "ACC Cement", 400, 63000)
    run("supplier_scorecard", date.today())
    assert sent == []                                                # nobody named: nothing goes out
    assert tenant.put("/api/purchase-controls", json={"purchasing_emails": "buying@acme.example.com"}).status_code == 200
    run("supplier_scorecard", date.today())
    assert [m[0] for m in sent] == ["buying@acme.example.com"] and "ACC Cement" in sent[0][2]


def test_a_late_order_is_chased_until_goods_arrive(tenant, sent):
    po = order(tenant, "ACC Cement", (date.today() - timedelta(days=1)).isoformat())
    tenant.post("/api/suppliers", json={"name": "ACC Cement", "email": "sales@acc.example.com"})
    run("late_deliveries", date.today())
    late = [a for a in tenant.get("/api/alerts").json()["alerts"] if a["kind"] == "late_delivery"]
    assert len(late) == 1 and po["number"] in late[0]["title"] and sent == []          # the buyer is told; supplier emails are off
    assert tenant.put("/api/purchase-controls", json={"late_delivery_emails": True}).json()["late_delivery_emails"] is True
    run("late_deliveries", date.today() + timedelta(days=1))                          # the day after: not yet (every 3 days)
    assert sent == []
    run("late_deliveries", date.today() + timedelta(days=3))
    assert [m[0] for m in sent] == ["sales@acc.example.com"] and po["number"] in sent[0][1]
    deliver(tenant, po, 4)                                                            # something has come: chasing stops
    sent.clear()
    run("late_deliveries", date.today() + timedelta(days=6))
    assert sent == []
