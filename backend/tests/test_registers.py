"""The three sheets the accountant kept by hand.

TDS by quarter for the 26Q, bank guarantees and when they lapse, advances
and what has come back. Every figure was already in the app; these make
sure the sheets can be thrown away.
"""
from test_measurement_and_ra_bills import placed_order, book, measure
from test_subcontractor_bills import (live_order, book as sub_book,
                                      measure as sub_measure, raise_bill)

import main


def certified_sub_bill(tenant, qty=100, **over):
    order = live_order(tenant, **over)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, qty)
    b = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % b["id"], json={})
    return order, tenant.get("/api/sub-bills/%d" % b["id"]).json()


# --- TDS ------------------------------------------------------------------------

def test_the_indian_quarter():
    assert main.fy_quarter("2026-04-01") == ("2026-27", "Q1")
    assert main.fy_quarter("2026-06-30") == ("2026-27", "Q1")
    assert main.fy_quarter("2026-09-21") == ("2026-27", "Q2")
    assert main.fy_quarter("2026-12-15") == ("2026-27", "Q3")
    assert main.fy_quarter("2027-02-01") == ("2026-27", "Q4")
    assert main.fy_quarter("") == ("", "")


def test_tds_we_deducted_lands_in_the_register_with_the_pan(tenant):
    order, bill = certified_sub_bill(tenant)
    reg = tenant.get("/api/registers/tds").json()
    row = [r for r in reg["deducted"] if r["bill"] == bill["number"]][0]
    assert row["section"] == "194C"
    assert row["tds"] == bill["tds_amount"] > 0
    assert row["amount_credited"] == bill["this_bill"]
    assert row["pan"] == "AAAPB1234C"
    assert row["missing_pan"] is False
    assert reg["summary"]["deducted"] == bill["tds_amount"]


def test_a_draft_bill_is_not_tds_yet(tenant):
    order = live_order(tenant)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 100)
    raise_bill(tenant, order["id"])
    assert tenant.get("/api/registers/tds").json()["deducted"] == []


def test_tds_deducted_from_us_is_the_other_side(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 100)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    reg = tenant.get("/api/registers/tds").json()
    assert len(reg["suffered"]) == 1
    assert reg["suffered"][0]["tds"] > 0
    assert reg["summary"]["suffered"] == reg["suffered"][0]["tds"]
    assert reg["deducted"] == []


def test_the_register_filters_by_quarter(tenant):
    order, bill = certified_sub_bill(tenant)
    fy, q = main.fy_quarter(bill["certified_at"])
    assert tenant.get("/api/registers/tds?year=%s&quarter=%s" % (fy, q)).json()["deducted"]
    other = "Q1" if q != "Q1" else "Q2"
    assert tenant.get("/api/registers/tds?year=%s&quarter=%s" % (fy, other)).json()["deducted"] == []
    assert tenant.get("/api/registers/tds?year=1999-00").json()["deducted"] == []
    assert fy in tenant.get("/api/registers/tds").json()["years"]


def test_a_deductee_without_a_pan_is_called_out(tenant):
    unit = tenant.post("/api/wo/business-units", json={"name": "YP", "code": "YP"}).json()
    con = tenant.post("/api/wo/contractors", json={"company_name": "Unregistered Gang"}).json()
    job = tenant.post("/api/jobs", json={"name": "Site", "customer_name": "X"}).json()
    order, bill = certified_sub_bill(tenant, business_unit_id=unit["id"],
                                     contractor_id=con["id"], job_id=job["id"])
    reg = tenant.get("/api/registers/tds").json()
    assert reg["deducted"][0]["missing_pan"] is True
    assert reg["summary"]["deductees_without_pan"] == 1


# --- Guarantees ----------------------------------------------------------------

def test_a_guarantee_is_listed_with_its_days_left(tenant):
    live_order(tenant, bank_guarantee_applicable=True, bank_guarantee_amount=250000,
               bank_guarantee_validity="2099-12-31")
    reg = tenant.get("/api/registers/guarantees").json()
    assert len(reg["guarantees"]) == 1
    g = reg["guarantees"][0]
    assert g["amount"] == 250000 and g["days_left"] > 1000 and g["state"] == "in force"
    assert reg["summary"]["held"] == 250000


def test_a_lapsed_guarantee_is_called_out(tenant):
    live_order(tenant, bank_guarantee_applicable=True, bank_guarantee_amount=100000,
               bank_guarantee_validity="2020-01-01")
    live_order(tenant, bank_guarantee_applicable=True, bank_guarantee_amount=50000)
    reg = tenant.get("/api/registers/guarantees").json()
    states = {g["state"] for g in reg["guarantees"]}
    assert "lapsed" in states and "no expiry recorded" in states
    assert reg["summary"]["lapsed"] == 1 and reg["summary"]["no_expiry"] == 1
    assert reg["summary"]["held"] == 50000            # the lapsed one is worth nothing


def test_an_order_without_a_guarantee_is_not_listed(tenant):
    live_order(tenant)
    assert tenant.get("/api/registers/guarantees").json()["guarantees"] == []


# --- Advances --------------------------------------------------------------------

def test_the_advance_and_what_has_come_back(tenant):
    order, bill = certified_sub_bill(tenant, mobilization_advance_percent=10,
                                     advance_recovery_percent=10)
    reg = tenant.get("/api/registers/advances").json()
    row = reg["advances"][0]
    assert row["advance"] == order["mobilization_advance_amount"]
    assert row["recovered"] == bill["advance_recovery"] > 0
    assert row["outstanding"] == round(row["advance"] - row["recovered"], 2)
    assert row["secured_by_bg"] is False
    assert reg["summary"]["unsecured"] == row["outstanding"]


def test_a_cancelled_bill_gives_its_recovery_back(tenant):
    order, bill = certified_sub_bill(tenant, mobilization_advance_percent=10,
                                     advance_recovery_percent=10)
    # Certified bills are not cancelled; a draft one is, and its recovery
    # must not count. Raise a second, leave it draft, then cancel it.
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 50)
    second = raise_bill(tenant, order["id"]).json()["bill"]
    before = tenant.get("/api/registers/advances").json()["advances"][0]["recovered"]
    tenant.post("/api/sub-bills/%d/cancel" % second["id"], json={"comments": "raised twice"})
    after = tenant.get("/api/registers/advances").json()["advances"][0]["recovered"]
    assert before == after == bill["advance_recovery"]


def test_another_tenant_sees_empty_registers(tenant, second_tenant):
    certified_sub_bill(tenant, mobilization_advance_percent=10, advance_recovery_percent=10,
                       bank_guarantee_applicable=True, bank_guarantee_amount=1)
    assert second_tenant.get("/api/registers/tds").json()["deducted"] == []
    assert second_tenant.get("/api/registers/guarantees").json()["guarantees"] == []
    assert second_tenant.get("/api/registers/advances").json()["advances"] == []
