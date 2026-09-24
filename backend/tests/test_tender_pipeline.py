"""The tender pipeline: from the notice to the estimate to the win, with the
earnest money tracked until it comes back."""
from datetime import date, timedelta


def lead(tenant, **over):
    body = {"title": "295 KLD STP, Vanya City", "customer_name": "Arabtec",
            "source": "Tender portal", "tender_reference": "ARB/STP/2026/14",
            "estimated_value": 7500000,
            "bid_due_on": (date.today() + timedelta(days=5)).isoformat(),
            "emd_amount": 150000, "emd_mode": "DD", "emd_reference": "DD 004512",
            "emd_paid_on": (date.today() - timedelta(days=40)).isoformat()}
    body.update(over)
    res = tenant.post("/api/leads", json=body)
    assert res.status_code == 200, res.text
    return res.json()["lead"]


def test_a_tender_is_numbered_and_counted(tenant):
    l = lead(tenant)
    assert l["number"] == "TND-0001" and l["status"] == "NEW"
    s = tenant.get("/api/leads").json()["summary"]
    assert s["live"] == 1 and s["pipeline_value"] == 7500000
    assert s["due_this_week"] == 1
    assert s["emd_out"] == 150000


def test_pricing_it_opens_an_estimate_carrying_the_tender(tenant):
    l = lead(tenant)
    out = tenant.post("/api/leads/%d/estimate" % l["id"]).json()
    est = tenant.get("/api/estimates/%d" % out["estimate_id"]).json()
    assert est["title"] == l["title"] and est["tender_reference"] == "ARB/STP/2026/14"
    assert out["lead"]["status"] == "ESTIMATING"
    assert tenant.post("/api/leads/%d/estimate" % l["id"]).status_code == 409


def test_the_estimates_outcome_is_the_tenders(tenant):
    l = lead(tenant)
    eid = tenant.post("/api/leads/%d/estimate" % l["id"]).json()["estimate_id"]
    import main
    from database import SessionLocal
    db = SessionLocal()
    try:
        e = db.query(main.models.DBEstimate).filter(main.models.DBEstimate.id == eid).first()
        e.status = "SUBMITTED"
        db.commit()
    finally:
        db.close()
    assert tenant.get("/api/leads/%d" % l["id"]).json()["status"] == "SUBMITTED"
    res = tenant.post("/api/leads/%d/status" % l["id"], json={"status": "WON"})
    assert res.status_code == 409 and "estimate" in res.json()["detail"]


def test_a_lost_tender_says_why_and_who_won(tenant):
    l = lead(tenant)
    assert tenant.post("/api/leads/%d/status" % l["id"], json={"status": "LOST"}).status_code == 400
    out = tenant.post("/api/leads/%d/status" % l["id"], json={
        "status": "LOST", "lost_reason": "Price - 6% above L1",
        "winning_bidder": "Shapoorji", "winning_price": 7050000}).json()
    assert out["lead"]["winning_bidder"] == "Shapoorji"
    assert tenant.get("/api/leads").json()["summary"]["hit_rate"] == 0.0


def test_the_hit_rate(tenant):
    a, b = lead(tenant, title="A"), lead(tenant, title="B")
    tenant.post("/api/leads/%d/status" % a["id"], json={"status": "LOST", "lost_reason": "price"})
    # B won outside an estimate: a small job priced on the phone.
    import main
    from database import SessionLocal
    db = SessionLocal()
    try:
        x = db.query(main.models.DBLead).filter(main.models.DBLead.id == b["id"]).first()
        x.status = "WON"
        db.commit()
    finally:
        db.close()
    assert tenant.get("/api/leads").json()["summary"]["hit_rate"] == 50.0


def test_the_emd_register_until_it_comes_back(tenant):
    l = lead(tenant)
    reg = tenant.get("/api/leads-emd").json()
    assert reg["summary"]["out"] == 150000 and reg["emds"][0]["days_held"] == 40
    tenant.post("/api/leads/%d/emd-returned" % l["id"], json={})
    assert tenant.get("/api/leads-emd").json()["summary"]["out"] == 0
    assert tenant.post("/api/leads/%d/emd-returned" % l["id"], json={}).status_code == 409


def test_an_emd_on_a_decided_tender_is_called_out(tenant):
    l = lead(tenant)
    tenant.post("/api/leads/%d/status" % l["id"], json={"status": "LOST", "lost_reason": "price"})
    assert tenant.get("/api/leads-emd").json()["summary"]["on_decided_tenders"] == 150000


def test_activities_carry_the_next_step(tenant):
    l = lead(tenant)
    tenant.post("/api/leads/%d/activities" % l["id"], json={
        "kind": "Visit", "note": "Site visited, soil is black cotton", "next_action": "Pre-bid query",
        "next_on": "2026-10-01"})
    acts = tenant.get("/api/leads/%d" % l["id"]).json()["activities"]
    assert acts[0]["kind"] == "Visit" and acts[0]["next_action"] == "Pre-bid query"


def test_dropping_needs_a_reason(tenant):
    l = lead(tenant)
    assert tenant.post("/api/leads/%d/status" % l["id"], json={"status": "DROPPED"}).status_code == 400


def test_another_tenant_sees_none_of_it(tenant, second_tenant):
    l = lead(tenant)
    assert second_tenant.get("/api/leads").json()["leads"] == []
    assert second_tenant.get("/api/leads/%d" % l["id"]).status_code == 404
