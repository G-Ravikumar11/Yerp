"""The work order as the Farvision walkthrough builds it.

Sixteen minutes of a billing engineer creating a work order in Farvision,
screen by screen: heading rows on the schedule, a tolerance on each item, a
billing-terms tab with every head laid out (CGST/SGST or IGST, TDS, retention,
labour welfare cess), copy-an-order, a change history, a searchable register
with an Excel export, and a printed letter. Each of those is a test here.
"""
from test_subcontract_orders import draft, priced, BOQ, staff, sign_in
from test_subcontractor_bills import live_order, book, measure, raise_bill

import main


GROUPED = {"lines": [
    {"activity_no": "E", "item_description": "ELECTRICAL WORK", "is_header": True},
    {"activity_no": "E1", "item_description": "SUB STATION EQUIPMENT", "is_header": True},
    {"activity_no": "E2", "item_code": "ELE-VCB",
     "item_description": "Supply, installation, testing and commissioning of 5-way "
                         "33 kV HT switchboard", "uom": "nos", "quantity": 300,
     "unit_rate": 7000, "tolerance_percent": 5},
    {"activity_no": "E3", "item_code": "ELE-TRF",
     "item_description": "630 kVA oil type transformer", "uom": "nos", "quantity": 2,
     "unit_rate": 1835000},
]}


def grouped(tenant, **over):
    order = draft(tenant, **over)
    res = tenant.put("/api/wo/orders/%d/boq" % order["id"], json=GROUPED)
    assert res.status_code == 200, res.text
    return res.json()["order"]


# --- Item info: headings and tolerance ------------------------------------------

def test_a_heading_row_prices_nothing(tenant):
    """E, E1 are how the schedule reads; E2, E3 are what it costs."""
    order = grouped(tenant)
    heads = [i for i in order["items"] if i["is_header"]]
    assert [h["activity_no"] for h in heads] == ["E", "E1"]
    assert all(h["quantity"] == 0 and h["unit_rate"] == 0 for h in heads)
    assert order["gross_amount"] == 300 * 7000 + 2 * 1835000


def test_a_heading_cannot_be_measured(tenant):
    order = grouped(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    head = [l for l in book(tenant, order["id"])["lines"] if l.get("is_header")][0]
    res = tenant.post("/api/sub-mb/%d/entries" % order["id"],
                      json={"item_id": head["item_id"], "quantity": 1})
    assert res.status_code == 400
    assert "heading" in res.json()["detail"]


def test_the_tolerance_is_the_ceiling_on_the_book(tenant):
    """300 ordered at 5% tolerance: 315 may be measured, 316 may not."""
    order = grouped(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    e2 = [l for l in book(tenant, order["id"])["lines"] if l["activity_no"] == "E2"][0]
    assert e2["max_quantity"] == 315
    measure(tenant, order["id"], e2["item_id"], 300)
    measure(tenant, order["id"], e2["item_id"], 15)
    res = tenant.post("/api/sub-mb/%d/entries" % order["id"],
                      json={"item_id": e2["item_id"], "quantity": 1})
    assert res.status_code == 409
    assert "Amend the order" in res.json()["detail"]
    assert "+5% tolerance" in res.json()["detail"]


def test_without_a_tolerance_the_order_quantity_is_the_ceiling(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]     # 250 cum ordered
    measure(tenant, order["id"], item, 250)
    res = tenant.post("/api/sub-mb/%d/entries" % order["id"],
                      json={"item_id": item, "quantity": 0.5})
    assert res.status_code == 409


def test_a_correction_always_goes_in(tenant):
    """A negative entry brings the book back; it is never refused."""
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 250)
    measure(tenant, order["id"], item, -10)
    measure(tenant, order["id"], item, 10)
    assert book(tenant, order["id"])["lines"][0]["measured_to_date"] == 250


def test_a_tolerance_is_a_percentage(tenant):
    order = draft(tenant)
    bad = {"lines": [dict(BOQ["lines"][0], tolerance_percent=150)]}
    assert tenant.put("/api/wo/orders/%d/boq" % order["id"], json=bad).status_code == 400


def test_headings_survive_an_amendment(tenant):
    order = grouped(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    rev = tenant.post("/api/wo/orders/%d/amend" % order["id"], json={}).json()["order"]
    assert [i["is_header"] for i in rev["items"]] == [True, True, False, False]
    assert rev["items"][2]["tolerance_percent"] == 5


# --- Billing terms: every head, the way the return and the bill want it --------

def heads(order):
    return {r["head"]: r for r in order["billing_schedule"]["rows"]}


def test_the_schedule_splits_gst_by_the_contractors_state(tenant):
    """Telangana gang on a Telangana site: CGST and SGST, half each."""
    order = priced(tenant)                       # contractor GSTIN 36..., our GSTIN 36...
    job_id = order["job_id"]
    tenant.put("/api/jobs/%d/place-of-supply" % job_id, json={"state_code": "36"})
    order = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    h = heads(order)
    assert order["billing_schedule"]["intra_state"] is True
    assert h["CGST"]["rate"] == 9 and h["SGST"]["rate"] == 9
    assert round(h["CGST"]["amount"] + h["SGST"]["amount"], 2) == order["gst_amount"]
    assert "IGST" not in h


def test_a_site_across_the_border_is_igst_on_the_order_and_the_bill(tenant):
    order = live_order(tenant)
    tenant.put("/api/jobs/%d/place-of-supply" % order["job_id"], json={"state_code": "37"})
    order = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    assert heads(order)["IGST"]["amount"] == order["gst_amount"]
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    assert bill["igst_amount"] == bill["gst_amount"] > 0


def test_it_is_the_gangs_state_that_counts_not_ours(tenant):
    """We are in Telangana, the site is in Telangana, but the gang is
    registered in Andhra: their supply crosses a border, so it is IGST."""
    tenant.put("/api/gst/settings", json={"gstin": "36AABCY1234H1ZX"})
    unit = tenant.post("/api/wo/business-units", json={"name": "YP", "code": "YP"}).json()
    con = tenant.post("/api/wo/contractors", json={
        "company_name": "Andhra Erectors", "pan": "AAAPA1234C",
        "gst_number": "37AAAPA1234C1Z5"}).json()
    job = tenant.post("/api/jobs", json={"name": "TS site", "customer_name": "X"}).json()
    tenant.put("/api/jobs/%d/place-of-supply" % job["id"], json={"state_code": "36"})
    order = priced(tenant, business_unit_id=unit["id"], contractor_id=con["id"],
                   job_id=job["id"])
    assert order["billing_schedule"]["intra_state"] is False
    assert order["billing_schedule"]["contractor_state"] == "37"


def test_labour_cess_comes_off_like_tds(tenant):
    """1% BOCW cess: withheld from the gang and remitted, never received."""
    order = priced(tenant, labour_cess_percent=1)
    gross = order["gross_amount"]
    assert order["labour_cess_amount"] == round(gross * 0.01, 2)
    assert order["net_order_value"] == round(
        gross + order["gst_amount"] - order["tds_amount"] - order["labour_cess_amount"], 2)
    assert heads(order)["Labour welfare cess (BOCW)"]["kind"] == "less"


def test_labour_cess_is_deducted_on_every_bill(tenant):
    order = live_order(tenant, labour_cess_percent=1, retention_percent=5)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    assert bill["labour_cess_percent"] == 1
    assert bill["labour_cess_amount"] == round(bill["this_bill"] * 0.01, 2)
    after = bill["this_bill"] - bill["retention_amount"] - bill["advance_recovery"]
    assert bill["net_payable"] == round(
        after + bill["gst_amount"] - bill["tds_amount"] - bill["labour_cess_amount"], 2)


def test_an_order_without_cess_is_unchanged(tenant):
    order = priced(tenant)
    assert order["labour_cess_amount"] == 0
    assert order["net_order_value"] == round(
        order["gross_amount"] + order["gst_amount"] - order["tds_amount"], 2)
    assert "Labour welfare cess (BOCW)" not in heads(order)


def test_the_schedule_reads_in_the_order_the_money_moves(tenant):
    order = priced(tenant, retention_percent=5, mobilization_advance_percent=10,
                   advance_recovery_percent=10, labour_cess_percent=1)
    kinds = [r["kind"] for r in order["billing_schedule"]["rows"]]
    # No place of supply set yet, so the tax is one IGST line.
    assert kinds == ["base", "add", "total", "info", "hold", "less", "less", "net"]
    tenant.put("/api/jobs/%d/place-of-supply" % order["job_id"], json={"state_code": "36"})
    order = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    kinds = [r["kind"] for r in order["billing_schedule"]["rows"]]
    assert kinds == ["base", "add", "add", "total", "info", "hold", "less", "less", "net"]
    assert order["billing_schedule"]["rows"][-1]["amount"] == order["net_order_value"]


# --- Main info: payment terms, copy, change history -----------------------------

def test_payment_terms_are_two_fields_and_one_sentence(tenant):
    order = priced(tenant, billing_cycle="Monthly", payment_days=30)
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert doc["payment_terms"] == ("Running Account bills may be raised monthly, and "
                                    "payment shall be released within 30 days of "
                                    "certification.")


def test_a_billing_cycle_is_one_of_the_known_ones(tenant):
    assert tenant.post("/api/wo/orders", json={"billing_cycle": "Whenever",
                                                "subject": "x"}).status_code == 400


def test_an_order_copies_with_its_schedule_and_clauses_but_not_its_dates(tenant):
    """The same trade on the next site starts as a copy far more often than
    it starts blank."""
    order = priced(tenant, retention_percent=5, labour_cess_percent=1,
                   billing_cycle="Fortnightly", payment_days=15)
    tenant.put("/api/wo/orders/%d/terms" % order["id"],
               json={"terms": [{"clause_category": "Payment", "clause_text": "Net 15."}]})
    res = tenant.post("/api/wo/orders/%d/copy" % order["id"])
    assert res.status_code == 200, res.text
    copy = res.json()["order"]
    assert copy["id"] != order["id"]
    assert copy["wo_number"] != order["wo_number"]
    assert copy["status"] == "DRAFT"
    assert copy["copied_from"] == order["wo_number"]
    assert [i["item_code"] for i in copy["items"]] == [i["item_code"] for i in order["items"]]
    assert copy["gross_amount"] == order["gross_amount"]
    assert copy["terms"][0]["clause_text"] == "Net 15."
    assert copy["retention_percent"] == 5 and copy["labour_cess_percent"] == 1
    assert copy["billing_cycle"] == "Fortnightly" and copy["payment_days"] == 15
    assert copy["commencement_date"] == "" and copy["completion_date"] == ""
    assert copy["history"][0]["action"] == "COPY"
    assert order["wo_number"] in copy["history"][0]["comments"]


def test_a_copy_is_a_fresh_draft_even_from_an_executed_order(tenant):
    order = live_order(tenant)
    tenant.post("/api/wo/orders/%d/execute" % order["id"], json={})
    copy = tenant.post("/api/wo/orders/%d/copy" % order["id"]).json()["order"]
    assert copy["editable"] is True
    assert copy["approved_at"] == ""


def test_every_edit_to_the_head_is_written_into_the_history(tenant):
    """Who moved the completion date, and when, has an answer."""
    order = priced(tenant)
    body = dict(order, completion_date="2026-12-31", retention_percent=10)
    out = tenant.put("/api/wo/orders/%d" % order["id"], json=body).json()["order"]
    edits = [h for h in out["history"] if h["action"] == "EDIT"]
    assert len(edits) == 1
    assert "Completion: 2026-11-30 -> 2026-12-31" in edits[0]["comments"]
    assert "Retention %: 0 -> 10" in edits[0]["comments"]


def test_a_save_that_changes_nothing_writes_nothing(tenant):
    order = priced(tenant)
    out = tenant.put("/api/wo/orders/%d" % order["id"], json=order).json()["order"]
    assert not [h for h in out["history"] if h["action"] == "EDIT"]


def test_a_provisional_order_says_whose_desk_it_is_on(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    manager = staff(tenant, "manager")
    out = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    assert out["provisional"] is True
    assert any(manager["first_name"] in n for n in out["pending_with"])
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["pending_with"] == []


# --- Copy rate: what it was last ordered at -------------------------------------

def test_the_last_rate_for_a_code_is_offered(tenant):
    live_order(tenant)                                    # CIV-RMC-25 @ 6800, approved
    priced(tenant)                                        # a draft at the same rate: ignored
    out = tenant.get("/api/wo/rates?item_code=civ-rmc-25").json()["rates"]
    assert len(out) == 1
    assert out[0]["unit_rate"] == 6800
    assert out[0]["contractor"].startswith("Sri Balaji")
    assert tenant.get("/api/wo/rates?item_code=NOPE").json()["rates"] == []


def test_rates_can_be_found_by_a_word_in_the_description(tenant):
    live_order(tenant)
    out = tenant.get("/api/wo/rates?description=reinforcement").json()["rates"]
    assert out and out[0]["item_code"] == "CIV-STL"


# --- The register ------------------------------------------------------------------

def test_the_register_searches_by_contractor_number_and_subject(tenant):
    a = priced(tenant, subject="Waterproofing of basement raft")
    priced(tenant, subject="HT cabling")
    found = tenant.get("/api/wo/orders?q=waterproofing").json()["orders"]
    assert [o["id"] for o in found] == [a["id"]]
    assert len(tenant.get("/api/wo/orders?q=" + a["wo_number"]).json()["orders"]) == 1
    assert len(tenant.get("/api/wo/orders?q=balaji").json()["orders"]) == 2
    assert tenant.get("/api/wo/orders?q=zzz").json()["orders"] == []


def test_the_register_filters_by_contractor_and_project(tenant):
    a = priced(tenant)
    priced(tenant)
    only = tenant.get("/api/wo/orders?contractor_id=%d" % a["contractor_id"]).json()["orders"]
    assert [o["id"] for o in only] == [a["id"]]
    only = tenant.get("/api/wo/orders?job_id=%d" % a["job_id"]).json()["orders"]
    assert [o["id"] for o in only] == [a["id"]]


def test_the_register_downloads(tenant):
    priced(tenant)
    res = tenant.get("/api/wo/orders.xlsx")
    assert res.status_code == 200 and res.content[:2] == b"PK"


# --- The letter ----------------------------------------------------------------------

def test_the_pdf_carries_the_heads_and_the_payment_clause(tenant):
    order = grouped(tenant, labour_cess_percent=1, billing_cycle="Monthly",
                    payment_days=30, retention_percent=5)
    tenant.put("/api/jobs/%d/place-of-supply" % order["job_id"], json={"state_code": "36"})
    res = tenant.get("/api/wo/orders/%d/document.pdf" % order["id"])
    assert res.status_code == 200 and res.content[:4] == b"%PDF"
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert doc["billing_schedule"]["intra_state"] is True
    assert doc["items"][0]["is_header"] is True
    assert doc["items"][2]["tolerance_percent"] == 5
    assert "30 days" in doc["payment_terms"]


def test_another_tenant_cannot_copy_or_price_from_it(tenant, second_tenant):
    order = live_order(tenant)
    assert second_tenant.post("/api/wo/orders/%d/copy" % order["id"]).status_code == 404
    assert second_tenant.get("/api/wo/rates?item_code=CIV-RMC-25").json()["rates"] == []


def test_an_owner_working_alone_is_named_as_the_approver(tenant):
    """Told nobody could approve, with the Approve button on the same screen."""
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    out = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    assert len(out["pending_with"]) == 1 and "(owner)" in out["pending_with"][0]
