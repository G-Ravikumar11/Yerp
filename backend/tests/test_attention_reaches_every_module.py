"""The Monday list: what goes wrong in the ledger, the plant register, the
tender pipeline, the enquiries and the programme reaches it too."""
from datetime import date, timedelta

from test_measurement_and_ra_bills import placed_order, book, measure


def d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def kinds(tenant):
    return {i["kind"]: i for i in tenant.get("/api/attention").json()["items"]}


def test_a_certified_bill_nobody_has_paid(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 250)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    # Certified today it is not yet late; the list must not cry wolf.
    assert "ra_receivable" not in kinds(tenant)
    import database, models
    s = database.SessionLocal()
    try:
        s.query(models.DBRABill).filter(models.DBRABill.id == b["id"]).update(
            {"certified_at": d(-45) + " 10:00:00"})
        s.commit()
    finally:
        s.close()
    item = kinds(tenant)["ra_receivable"]
    assert item["count"] == 1 and item["view"] == "ledger-view"
    # A part-payment takes off what came in.
    before = item["value"]
    tenant.post("/api/money/entries", json={"direction": "IN", "doc_type": "ra_bill",
                                            "doc_id": b["id"], "amount": 5000, "mode": "NEFT",
                                            "reference": "UTR1"})
    assert kinds(tenant)["ra_receivable"]["value"] == before - 5000


def test_earnest_money_on_a_decided_tender(tenant):
    l = tenant.post("/api/leads", json={
        "title": "STP", "customer_name": "Arabtec", "emd_amount": 150000,
        "emd_paid_on": d(-60), "bid_due_on": d(-30)}).json()["lead"]
    tenant.post("/api/leads/%d/status" % l["id"], json={
        "status": "LOST", "lost_reason": "Price", "winning_bidder": "X", "winning_price": 1})
    item = kinds(tenant)["emd"]
    assert item["value"] == 150000 and item["view"] == "leads-view"


def test_a_bid_due_this_week(tenant):
    tenant.post("/api/leads", json={"title": "Kokapet towers", "customer_name": "NCC",
                                    "bid_due_on": d(2)})
    item = kinds(tenant)["bids_due"]
    assert item["count"] == 1 and "in 2 days" in item["detail"]


def test_a_slipping_programme(tenant):
    j = tenant.post("/api/jobs", json={"name": "Vizag STP", "customer_name": "L&T"}).json()
    a = tenant.post("/api/jobs/%d/schedule/activities" % j["id"], json={
        "name": "Columns", "planned_start": d(-20), "planned_finish": d(-1)}).json()["schedule"]["activities"][0]
    tenant.post("/api/schedule/activities/%d/progress" % a["id"], json={"percent": 50, "reported_on": d(-15)})
    tenant.post("/api/jobs/%d/schedule/activities" % j["id"], json={
        "name": "Slab", "planned_start": d(0), "planned_finish": d(10), "depends_on_id": a["id"]})
    item = kinds(tenant)["programme"]
    assert item["count"] >= 1 and "Vizag STP" in item["detail"]


def test_plant_past_its_service(tenant):
    tenant.post("/api/assets", json={"name": "JCB 3DX backhoe", "ownership": "Owned",
                                     "meter_unit": "Hours", "meter_reading": 1200,
                                     "last_service_meter": 900, "service_every": 250})
    item = kinds(tenant)["plant"]
    assert "JCB" in item["detail"] and item["view"] == "equipment-view"


def test_an_enquiry_with_one_price(tenant):
    r = tenant.post("/api/rfqs", json={"title": "Cement for raft", "needed_by": d(3),
                                       "lines": [{"description": "OPC 53", "uom": "Bags", "qty": 500}]})
    assert r.status_code == 200, r.text
    assert kinds(tenant)["rfq"]["count"] == 1
