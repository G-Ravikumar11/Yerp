"""The controls on a subcontract: closing an order out, the second signature on a contractor's retention, papers and
TDS before anybody is paid, the client's BOQ at approval and at certification, liquidated damages, the bank
guarantee, and the budget an order is held against.

Each was a figure somebody could read and nothing stopped. Here each is shown to stop what it should, to say why
in words, and - where the Master may sign past it - to keep the reason on the record.
"""
from datetime import date, timedelta

from conftest import fund_order
from test_boq import contractor_order, make_boq, saved
from test_subcontract_orders import draft, masters, priced, sign_in, staff
from test_subcontractor_bills import book, live_order, measure, raise_bill


def day(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def certified_bill(tenant, order, qty=100, **extra):
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, qty)
    bill = raise_bill(tenant, order["id"], **extra)
    assert bill.status_code == 200, bill.text
    bill = bill.json()["bill"]
    assert tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).status_code == 200
    res = tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    assert res.status_code == 200, res.text
    return res.json()["bill"]


def close(tenant, order_id, finished=None, comments="Work complete"):
    return tenant.post("/api/wo/orders/%d/close" % order_id,
                       json={"actual_completion_date": finished or day(-1), "comments": comments})


def all_papers(tenant, contractor_id):
    for kind in ("labour_licence", "pf", "esi", "insurance"):
        res = tenant.post("/api/compliance/documents",
                          json={"contractor_id": contractor_id, "kind": kind, "valid_to": day(365)})
        assert res.status_code == 200, res.text


# --- closing an order out -----------------------------------------------------------------------------------

def test_an_order_closes_only_once_its_bills_are_settled_and_its_work_billed(tenant):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    res = close(tenant, order["id"])
    assert res.status_code == 409 and "measured and not billed" in res.json()["detail"]
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    res = close(tenant, order["id"])
    assert res.status_code == 409 and bill["number"] in res.json()["detail"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    assert close(tenant, order["id"], finished=day(3)).status_code == 400, "not a date still to come"
    assert close(tenant, order["id"], comments="").status_code == 400, "says why"
    res = close(tenant, order["id"])
    assert res.status_code == 200, res.text
    closed = res.json()["order"]
    assert closed["status"] == "CLOSED" and closed["actual_completion_date"] == day(-1)
    assert closed["billed_value"] == 100 * 6800


def test_a_closed_order_gives_back_what_it_never_did(tenant):
    order = live_order(tenant, pay_advance=False)
    budgets = lambda: tenant.get("/api/wo/projects/%d/budgets" % order["job_id"]).json()["budgets"][0]  # noqa: E731
    assert budgets()["committed"] == order["gross_amount"]
    certified_bill(tenant, order, qty=100)
    assert close(tenant, order["id"]).status_code == 200
    assert budgets()["committed"] == 100 * 6800
    # And nothing more is measured or billed against it.
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    res = tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": 5})
    assert res.status_code == 409
    assert tenant.post("/api/wo/orders/%d/amend" % order["id"], json={"comments": "more"}).status_code == 409


def test_the_defects_period_runs_from_when_the_work_actually_finished(tenant):
    order = live_order(tenant, pay_advance=False, retention_percent=5)
    certified_bill(tenant, order)
    finished = day(-40)
    assert close(tenant, order["id"], finished=finished).status_code == 200
    p = next(x for x in tenant.get("/api/retention").json()["positions"]
             if x["side"] == "contractor" and x["order_id"] == order["id"])
    assert p["actual_completion_date"] == finished
    assert p["dlp_ends"] > finished and p["dlp_ends"] != "2027-11-30"


def test_an_advance_not_recovered_stops_the_close_unless_the_master_says_why(tenant):
    order = live_order(tenant, mobilization_advance_percent=10, advance_recovery_percent=10)
    certified_bill(tenant, order)
    res = close(tenant, order["id"], comments="")
    assert res.status_code == 409 and "advance" in res.json()["detail"]
    res = close(tenant, order["id"], comments="Contractor refunding the balance by cheque")
    assert res.status_code == 200, res.text
    assert "unrecovered" in res.json()["order"]["close_reason"]
    kinds = {i["kind"] for i in tenant.get("/api/attention").json()["items"]}
    assert "advance_unrecovered" in kinds


# --- a contractor's retention ----------------------------------------------------------------------------------

def release(client, order_id, amount, stage="Practical completion", **over):
    body = {"side": "contractor", "order_id": order_id, "amount": amount, "stage": stage}
    body.update(over)
    return client.post("/api/retention/releases", json=body)


def test_retention_raised_by_staff_is_owed_only_once_somebody_else_certifies_it(tenant, portal):
    order = live_order(tenant, pay_advance=False, retention_percent=5)
    bill = certified_bill(tenant, order)
    first, second = staff(tenant, "project_manager"), staff(tenant, "project_manager")
    sign_in(portal, first)
    res = release(portal, order["id"], bill["retention_amount"] / 2)
    assert res.status_code == 200, res.text
    r = res.json()["release"]
    assert r["status"] == "SUBMITTED" and r["outstanding"] == 0
    assert portal.post("/api/retention/releases/%d/certify" % r["id"], json={}).status_code == 403
    owed = [x for x in tenant.get("/api/money/payables").json()["bills"] if x["doc_type"] == "retention_release"]
    assert owed == []
    sign_in(portal, second)
    inbox = portal.get("/api/approvals/inbox").json()["items"]
    assert any(i["kind"] == "retention_release" and i["id"] == r["id"] for i in inbox)
    res = portal.post("/api/approvals/decide", json={"kind": "retention_release", "id": r["id"], "decision": "approve"})
    assert res.status_code == 200, res.text
    assert tenant.get("/api/retention/releases/%d" % r["id"]).json()["status"] == "CERTIFIED"
    owed = [x for x in tenant.get("/api/money/payables").json()["bills"] if x["doc_type"] == "retention_release"]
    assert len(owed) == 1


def test_retention_waits_for_the_defects_period_and_for_open_back_charges(tenant):
    order = live_order(tenant, pay_advance=False, retention_percent=5)
    bill = certified_bill(tenant, order)
    held = bill["retention_amount"]
    res = release(tenant, order["id"], held, stage="End of defects period")
    assert res.status_code == 409 and "defects period" in res.json()["detail"]
    tenant.post("/api/back-charges", json={"contractor_id": order["contractor_id"], "order_id": order["id"],
                                           "reason": "Debris left on site", "amount": 500})
    res = release(tenant, order["id"], held / 2)
    assert res.status_code == 409 and "back-charges" in res.json()["detail"]
    assert release(tenant, order["id"], held / 2, override=True).status_code == 400, "an override says why"
    res = release(tenant, order["id"], held / 2, override=True, notes="Charge disputed; settled on the final bill")
    assert res.status_code == 200, res.text
    assert "back-charges" in res.json()["release"]["override_note"]


# --- the contractor's papers -----------------------------------------------------------------------------------

def test_a_contractor_whose_papers_have_lapsed_is_not_certified_or_paid(tenant, monkeypatch):
    monkeypatch.setenv("REQUIRE_CONTRACTOR_COMPLIANCE", "1")
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 409 and "Compliance" in res.json()["detail"]
    all_papers(tenant, order["contractor_id"])
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).status_code == 200
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 50)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    # The licence is struck off the record before the bill is certified.
    from app import models
    import main
    with main.SessionLocal() as db:
        db.query(models.DBComplianceDocument).filter(
            models.DBComplianceDocument.contractor_id == order["contractor_id"],
            models.DBComplianceDocument.kind == "labour_licence").delete()
        db.commit()
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).json()["compliance_blocks"]
    res = tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    assert res.status_code == 409 and "labour licence" in res.json()["detail"]
    res = tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={"comments": "Renewal receipt seen"})
    assert res.status_code == 200, res.text
    assert "Renewal receipt seen" in res.json()["bill"]["override_note"]
    pay = {"doc_type": "sub_bill", "doc_id": bill["id"], "amount": 1000, "mode": "NEFT", "reference": "UTR1"}
    assert tenant.post("/api/money/entries", json=pay).status_code == 409
    assert tenant.post("/api/money/entries", json=dict(pay, note="Paid against the renewal receipt")).status_code == 200


def test_the_company_can_switch_the_papers_check_off(tenant, monkeypatch):
    monkeypatch.setenv("REQUIRE_CONTRACTOR_COMPLIANCE", "1")
    assert tenant.get("/api/approval-rules").json()["compliance_blocks_payment"] is True
    tenant.put("/api/approval-rules", json={"compliance_blocks_payment": False})
    assert tenant.get("/api/approval-rules").json()["compliance_blocks_payment"] is False
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).status_code == 200


# --- TDS --------------------------------------------------------------------------------------------------------

def test_tds_starts_at_the_rate_the_law_sets_for_the_contractor(tenant, monkeypatch):
    monkeypatch.setenv("ENFORCE_STATUTORY_TDS", "1")
    person = masters(tenant)[1]                     # PAN AAAPB1234C - a person
    company = tenant.post("/api/wo/contractors", json={"company_name": "Kaveri Infra Pvt Ltd",
                                                       "pan": "AABCK1234L"}).json()
    nobody = tenant.post("/api/wo/contractors", json={"company_name": "Ramu Labour Works"}).json()
    assert (person["tds_rate"], company["tds_rate"], nobody["tds_rate"]) == (1.0, 2.0, 20.0)
    for con, rate in ((person, 1.0), (company, 2.0), (nobody, 20.0)):
        order = draft(tenant, contractor_id=con["id"], tds_rate=None)
        assert order["tds_rate"] == rate, con["company_name"]


def test_an_order_below_the_statutory_tds_needs_the_masters_reason(tenant, monkeypatch):
    monkeypatch.setenv("ENFORCE_STATUTORY_TDS", "1")
    firm = tenant.post("/api/wo/contractors", json={"company_name": "Kaveri & Sons", "pan": "AABFK1234L",
                                                    "gst_number": "36AABFK1234L1Z5"}).json()
    assert firm["tds_rate"] == 2.0
    order = priced(tenant, contractor_id=firm["id"], tds_rate=1)
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 409 and "194C" in res.json()["detail"]
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={"comments": "Lower deduction certificate 197"})
    assert res.status_code == 200, res.text
    assert any("TDS below the statutory rate" in h["comments"] for h in res.json()["order"]["history"])


def test_a_contractor_is_taken_on_only_with_a_pan_and_a_bank_account(tenant, portal):
    sign_in(portal, staff(tenant, "ho_qs"))
    con = portal.post("/api/wo/contractors", json={"company_name": "Half Filled Works"}).json()
    assert con["registration_status"] == "PENDING"
    res = tenant.post("/api/wo/contractors/%d/approve" % con["id"], json={})
    assert res.status_code == 409 and "PAN" in res.json()["detail"]


# --- the client's BOQ ------------------------------------------------------------------------------------------

def test_an_order_past_the_boq_needs_an_override_to_be_approved(tenant):
    _, boq = make_boq(tenant)
    lines = {l["group_code"]: l for l in saved(tenant, boq)["lines"]}
    _, _, res = contractor_order(tenant, lines, [(lines["EXC"], 600, 150), (lines["RCC"], 100, 9000)])
    order = fund_order(tenant, res["order"])
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    detail = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    assert len(detail["boq_warnings"]) == 2
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 409 and "BOQ" in res.json()["detail"] and "loss" in res.json()["detail"]
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"], json={"override": True}).status_code == 400
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"],
                      json={"override": True, "comments": "Client has agreed the extra excavation"})
    assert res.status_code == 200, res.text
    assert any("BOQ override" in h["comments"] for h in res.json()["order"]["history"])


def test_a_bill_that_takes_contractors_past_the_boq_needs_the_masters_reason(tenant):
    _, boq = make_boq(tenant)
    lines = {l["group_code"]: l for l in saved(tenant, boq)["lines"]}
    from test_boq import job_of_key
    order = draft(tenant, job_id=job_of_key(lines["EXC"]["key"]))
    pulled = tenant.post("/api/wo/orders/%d/boq-lines" % order["id"],
                         json={"lines": [{"key": lines["EXC"]["key"], "quantity": 500, "rate": 150}]}).json()["lines"]
    pulled[0]["tolerance_percent"] = 20
    order = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": pulled}).json()["order"]
    order = fund_order(tenant, order)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).status_code == 200
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 550)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).json()["boq_warnings"]
    res = tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    assert res.status_code == 409 and "BOQ" in res.json()["detail"]
    res = tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={"comments": "Variation BV-01 being raised"})
    assert res.status_code == 200, res.text


# --- liquidated damages ------------------------------------------------------------------------------------------

def test_a_late_order_carries_liquidated_damages_up_to_the_cap(tenant):
    order = live_order(tenant, pay_advance=False, commencement_date="2026-01-01", completion_date="2026-03-01",
                       ld_percent_per_week=1, ld_cap_percent=5)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    cap = round(order["gross_amount"] * 5 / 100, 2)
    assert bill["ld_amount"] == cap and "capped" in bill["ld_note"]
    plain = bill["this_bill"] - bill["tds_amount"] + bill["gst_amount"] - bill["retention_amount"]
    assert abs(bill["net_payable"] - (plain - cap)) < 1.01
    res = tenant.put("/api/sub-bills/%d" % bill["id"], json={"ld_amount": 0})
    assert res.status_code == 400 and "Say why" in res.json()["detail"]
    res = tenant.put("/api/sub-bills/%d" % bill["id"], json={"ld_amount": 0, "ld_note": "Extension of time agreed"})
    assert res.status_code == 200 and res.json()["bill"]["ld_amount"] == 0


def test_an_order_on_time_carries_none(tenant):
    order = live_order(tenant, pay_advance=False, completion_date=day(60), ld_percent_per_week=1, ld_cap_percent=5)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 10)
    assert raise_bill(tenant, order["id"]).json()["bill"]["ld_amount"] == 0


# --- the order's head --------------------------------------------------------------------------------------------

def test_the_order_head_is_checked(tenant, second_tenant):
    assert tenant.post("/api/wo/orders", json={"retention_percent": 150}).status_code == 400
    assert tenant.post("/api/wo/orders", json={"commencement_date": "2026-06-01",
                                               "completion_date": "2026-05-01"}).status_code == 400
    assert tenant.post("/api/wo/orders", json={"completion_date": "31/05/2026"}).status_code == 400
    theirs = second_tenant.post("/api/wo/contractors", json={"company_name": "Not Ours Ltd"}).json()
    res = tenant.post("/api/wo/orders", json={"contractor_id": theirs["id"]})
    assert res.status_code == 400 and "not on file" in res.json()["detail"]
    # and an order is opened for someone: no sub contractor, no work order
    res = tenant.post("/api/wo/orders", json={"subject": "Shuttering"})
    assert res.status_code == 400 and "sub contractor" in res.json()["detail"]


def test_an_amendment_says_why(tenant):
    order = live_order(tenant, pay_advance=False)
    assert tenant.post("/api/wo/orders/%d/amend" % order["id"], json={}).status_code == 400
    res = tenant.post("/api/wo/orders/%d/amend" % order["id"], json={"comments": "Completion moved to March"})
    assert res.status_code == 200
    assert "Completion moved to March" in res.json()["order"]["history"][0]["comments"]


# --- the bank guarantee ------------------------------------------------------------------------------------------

def test_a_guarantee_needs_its_figures_and_is_watched_until_it_is_returned(tenant):
    order = priced(tenant, bank_guarantee_applicable=True, bank_guarantee_amount=150000)
    res = tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert res.status_code == 400 and "bank guarantee" in res.json()["detail"]
    head = {k: order[k] for k in ("business_unit_id", "contractor_id", "job_id", "department", "work_type",
                                  "subject", "commencement_date", "completion_date")}
    head.update(bank_guarantee_applicable=True, bank_guarantee_amount=150000, bank_guarantee_validity=day(20),
                bank_guarantee_number="BG/0042", bank_guarantee_bank="HDFC Bank", tds_rate=1)
    res = tenant.put("/api/wo/orders/%d" % order["id"], json=head)
    assert res.status_code == 200, res.text
    head["completion_date"] = day(10)
    tenant.put("/api/wo/orders/%d" % order["id"], json=head)
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    rows = tenant.get("/api/registers/guarantees").json()["guarantees"]
    mine = next(r for r in rows if r["order_id"] == order["id"])
    assert mine["state"] == "lapses within 30 days" and mine["number"] == "BG/0042" and mine["bank"] == "HDFC Bank"
    assert "bank_guarantees" in {i["kind"] for i in tenant.get("/api/attention").json()["items"]}
    res = tenant.post("/api/wo/orders/%d/bank-guarantee/return" % order["id"], json={})
    assert res.status_code == 400, "an open order's guarantee goes back only with a reason"
    res = tenant.post("/api/wo/orders/%d/bank-guarantee/return" % order["id"], json={"comments": "Replaced by BG/0043"})
    assert res.status_code == 200
    assert all(r["order_id"] != order["id"] for r in tenant.get("/api/registers/guarantees").json()["guarantees"])
    assert res.json()["order"]["bank_guarantee_state"] == "returned"


# --- the budget -------------------------------------------------------------------------------------------------

def test_a_budget_set_by_whoever_prices_the_order_is_confirmed_by_the_approver(tenant, portal):
    order = priced(tenant, fund=False)
    # Planning & Billing keep the orders up to date but cannot approve them.
    sign_in(portal, staff(tenant, "planning_billing"))
    res = portal.post("/api/wo/projects/%d/budgets" % order["job_id"], json={"name": "Civil", "allocated_amount": 9e6})
    assert res.status_code == 200 and res.json()["confirmed"] is False
    tenant.post("/api/wo/orders/%d/charge-budget" % order["id"], json={"budget_id": res.json()["id"]})
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["unconfirmed_budgets"]
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).status_code == 200
    row = tenant.get("/api/wo/projects/%d/budgets" % order["job_id"]).json()["budgets"][0]
    assert row["confirmed"] is True


def test_an_allocation_cannot_be_set_to_nothing_under_a_committed_order(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    budget = tenant.get("/api/wo/projects/%d/budgets" % order["job_id"]).json()["budgets"][0]
    res = tenant.put("/api/wo/projects/budgets/%d" % budget["id"], json={"name": budget["name"], "allocated_amount": 0})
    assert res.status_code == 409


# --- paying a bill ----------------------------------------------------------------------------------------------

def test_paying_a_bill_goes_through_the_ledger(tenant):
    order = live_order(tenant, pay_advance=False)
    bill = certified_bill(tenant, order)
    res = tenant.post("/api/sub-bills/%d/pay" % bill["id"], json={"reference": "NEFT 77"})
    assert res.status_code == 200, res.text
    assert res.json()["bill"]["status"] == "PAID"
    out = tenant.get("/api/money/outstanding/sub_bill/%d" % bill["id"]).json()
    assert out["outstanding"] == 0 and len(out["entries"]) == 1 and out["entries"][0]["reference"] == "NEFT 77"
    assert tenant.post("/api/sub-bills/%d/pay" % bill["id"], json={}).status_code == 409

