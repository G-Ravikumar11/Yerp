"""Retention released: claimed back from the client, or paid out to a gang.

Retention is held on every certified bill. Until now the app could say how
much was held and nothing more - no document ever brought it back, so it
could not be received, did not age, and sat outside the ledgers and the GST
registers. A release is a bill of its own, with the tax the RA bills left off.
"""
import main
from test_measurement_and_ra_bills import placed_order, measure, line_of, raise_bill
from test_subcontractor_bills import live_order, book as sub_book, measure as sub_measure, \
    raise_bill as sub_raise


def certified_ra(tenant):
    """One RA bill of 1,00,000 with 5% retention, certified: 5,000 held."""
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 1000)
    b = raise_bill(tenant, wo["id"], retention_percent=5, tax_percent=18, tds_percent=1).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    res = tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    assert res.status_code == 200, res.text
    return wo, res.json()["bill"]


def position(tenant, side, order_id):
    return next(p for p in tenant.get("/api/retention").json()["positions"]
                if p["side"] == side and p["order_id"] == order_id)


def release(tenant, side, order_id, amount, stage="Practical completion", **over):
    body = {"side": side, "order_id": order_id, "amount": amount, "stage": stage}
    body.update(over)
    return tenant.post("/api/retention/releases", json=body)


def test_half_is_suggested_at_practical_completion(tenant):
    wo, bill = certified_ra(tenant)
    p = position(tenant, "client", wo["id"])
    assert p["held"] == 5000 and p["balance"] == 5000 and p["released"] == 0
    assert p["suggest"] == {"stage": "Practical completion", "amount": 2500}
    assert p["gst_percent"] == 18


def test_a_release_carries_the_gst_the_bills_left_off(tenant):
    wo, bill = certified_ra(tenant)
    res = release(tenant, "client", wo["id"], 2500)
    assert res.status_code == 200, res.text
    r = res.json()["release"]
    assert r["number"] == "RET-0001" and r["status"] == "CERTIFIED"
    assert r["gst_amount"] == 450 and r["net_amount"] == 2950
    assert r["cgst_amount"] + r["sgst_amount"] + r["igst_amount"] == 450
    # What is left is the second half, due at the end of the defects period.
    p = position(tenant, "client", wo["id"])
    assert p["balance"] == 2500 and p["released"] == 2500
    assert p["suggest"]["stage"] == "End of defects period"
    # The register now says what is still held, and what came back.
    reg = tenant.get("/api/money/retention").json()["summary"]
    assert reg["held"] == 2500 and reg["released"] == 2500


def test_never_more_than_is_still_held(tenant):
    wo, bill = certified_ra(tenant)
    assert release(tenant, "client", wo["id"], 3000).status_code == 200
    res = release(tenant, "client", wo["id"], 2500, stage="End of defects period")
    assert res.status_code == 400 and "2,000" in res.json()["detail"]
    assert release(tenant, "client", wo["id"], 100, stage="Whenever").status_code == 400


def test_a_release_is_owed_received_and_in_the_ledger(tenant):
    wo, bill = certified_ra(tenant)
    r = release(tenant, "client", wo["id"], 2500).json()["release"]
    owed = [x for x in tenant.get("/api/money/receivables").json()["invoices"]
            if x["doc_type"] == "retention_release"]
    assert len(owed) == 1 and owed[0]["outstanding"] == 2950 and owed[0]["kind"] == "Retention release"
    got = tenant.post("/api/money/entries", json={"doc_type": "retention_release", "doc_id": r["id"],
                                                  "amount": 2950, "mode": "NEFT", "reference": "UTR9"})
    assert got.status_code == 200, got.text
    assert got.json()["entry"]["direction"] == "IN"
    assert tenant.get("/api/retention/releases/%d" % r["id"]).json()["status"] == "PAID"
    assert not [x for x in tenant.get("/api/money/receivables").json()["invoices"]
                if x["doc_type"] == "retention_release"]
    st = tenant.get("/api/ledger/statement", params={"party_type": "client", "party": r["party"]}).json()
    mine = [x for x in st["rows"] if x["doc_type"] == "retention_release"]
    assert {x["kind"] for x in mine} >= {"Retention released"}
    assert sum(x["billed"] - x["moved"] for x in mine) == 0


def test_a_release_with_money_against_it_is_not_cancelled(tenant):
    wo, bill = certified_ra(tenant)
    r = release(tenant, "client", wo["id"], 2500).json()["release"]
    e = tenant.post("/api/money/entries", json={"doc_type": "retention_release", "doc_id": r["id"],
                                                "amount": 1000, "mode": "NEFT", "reference": "UTR1"}).json()["entry"]
    assert tenant.post("/api/retention/releases/%d/cancel" % r["id"], json={"reason": "wrong"}).status_code == 409
    tenant.post("/api/money/entries/%d/void" % e["id"], json={"reason": "posted twice"})
    assert tenant.post("/api/retention/releases/%d/cancel" % r["id"], json={}).status_code == 400
    res = tenant.post("/api/retention/releases/%d/cancel" % r["id"], json={"reason": "raised early"})
    assert res.status_code == 200 and res.json()["release"]["status"] == "CANCELLED"
    assert position(tenant, "client", wo["id"])["balance"] == 5000


def test_the_release_is_an_outward_supply(tenant):
    wo, bill = certified_ra(tenant)
    release(tenant, "client", wo["id"], 2500)
    out = tenant.get("/api/gst/outward").json()
    rel = [x for x in out["supplies"] if x["kind"] == "Retention release"]
    assert len(rel) == 1 and rel[0]["taxable"] == 2500 and rel[0]["tax"] == 450


def test_the_project_money_counts_it(tenant):
    wo, bill = certified_ra(tenant)
    before = tenant.get("/api/costs/by-project/%d" % bill["job_id"])
    assert before.status_code == 200, before.text
    release(tenant, "client", wo["id"], 2500)
    after = tenant.get("/api/costs/by-project/%d" % bill["job_id"]).json()
    assert after["retention_held"] == before.json()["retention_held"] - 2500
    assert after["outstanding"] == before.json()["outstanding"] + 2950


def gang_with_retention(tenant, **over):
    order = live_order(tenant, retention_percent=5, **over)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 100)
    bill = sub_raise(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    return order, tenant.get("/api/sub-bills/%d" % bill["id"]).json()


def test_a_gangs_retention_is_released_as_money_we_owe(tenant):
    order, bill = gang_with_retention(tenant)
    held = bill["retention_amount"]
    p = position(tenant, "contractor", order["id"])
    assert p["held"] == held and p["party"].startswith("Sri Balaji")
    assert p["dlp_ends"] == "2027-11-30" and not p["dlp_over"]
    r = release(tenant, "contractor", order["id"], held / 2).json()["release"]
    assert r["number"] == "RETG-0001"
    owe = [x for x in tenant.get("/api/money/payables").json()["bills"]
           if x["doc_type"] == "retention_release"]
    assert len(owe) == 1 and owe[0]["outstanding"] == r["net_amount"]
    paid = tenant.post("/api/money/entries", json={"doc_type": "retention_release", "doc_id": r["id"],
                                                   "amount": r["net_amount"], "mode": "NEFT", "reference": "UTR2"})
    assert paid.json()["entry"]["direction"] == "OUT"
    assert tenant.get("/api/sub-bills?order_id=%d" % order["id"]).json()["summary"]["retention_held"] == held - held / 2
    inward = [x for x in tenant.get("/api/gst/inward").json()["supplies"] if x["kind"] == "Retention release"]
    assert len(inward) == 1 and inward[0]["taxable"] == held / 2


def test_a_gang_whose_defects_period_has_run_out_is_flagged(tenant):
    order, bill = gang_with_retention(tenant, commencement_date="2024-01-01", completion_date="2024-06-30")
    p = position(tenant, "contractor", order["id"])
    assert p["dlp_ends"] == "2025-06-30" and p["dlp_over"]
    items = {i["kind"]: i for i in tenant.get("/api/attention").json()["items"]}
    assert items["retention_gangs"]["value"] == bill["retention_amount"]
    release(tenant, "contractor", order["id"], bill["retention_amount"], stage="End of defects period")
    assert "retention_gangs" not in {i["kind"] for i in tenant.get("/api/attention").json()["items"]}


def test_the_release_prints(tenant):
    wo, bill = certified_ra(tenant)
    r = release(tenant, "client", wo["id"], 2500).json()["release"]
    res = tenant.get("/api/retention/releases/%d/export.xlsx" % r["id"])
    assert res.status_code == 200 and len(res.content) > 1000


def test_another_company_sees_none_of_it(tenant, second_tenant):
    wo, bill = certified_ra(tenant)
    r = release(tenant, "client", wo["id"], 2500).json()["release"]
    assert second_tenant.get("/api/retention/releases/%d" % r["id"]).status_code == 404
    assert second_tenant.get("/api/retention").json()["positions"] == []
    assert release(second_tenant, "client", wo["id"], 100).status_code == 404


def test_months_run_to_the_end_of_a_short_month():
    assert main.months_after("2024-01-31", 1) == "2024-02-29"
    assert main.months_after("2025-11-30", 12) == "2026-11-30"
    assert main.months_after("", 12) == ""
