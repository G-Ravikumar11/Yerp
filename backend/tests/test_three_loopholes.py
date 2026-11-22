"""Three ways money could slip, closed:
1. A contractor's bank account, PAN or GST changed by staff goes back for somebody else's approval, the Master is told, the
   old and new figures are logged (account masked), and no payment file pays them until it is approved.
2. The budget is set by those given "Edit project budgets" - not by everybody who prepares work orders - and every change
   is logged with its figures.
3. Whoever recorded the measurements on an RA bill does not certify it."""
from app import db as database
from app import models
from app.services.payouts import HELD, beneficiary
from test_entry_codes_and_chosen_billing import add, draw, setup
from test_head_office import vendor_body
from test_subcontract_orders import sign_in, staff


def approved_contractor(tenant):
    con = tenant.post("/api/wo/contractors", json=vendor_body(bank_account="123456789012", bank_ifsc="SBIN0001234",
                                                                bank_name="SBI")).json()
    return con


def body_of(tenant, con_id, **over):
    row = next(c for c in tenant.get("/api/wo/contractors").json()["contractors"] if c["id"] == con_id)
    body = {k: row.get(k) for k in ("company_name", "vendor_code", "pan", "gst_number", "bank_name", "bank_account",
                                    "bank_ifsc", "address", "contact_person", "email", "phone_number")}
    body.update(over)
    return body


def test_a_bank_account_changed_by_staff_waits_for_somebody_elses_approval_and_is_not_paid(tenant, portal):
    con = approved_contractor(tenant)
    pm = staff(tenant, "project_manager")
    sign_in(portal, pm)
    res = portal.put("/api/wo/contractors/%d" % con["id"], json=body_of(tenant, con["id"], bank_account="999988887777"))
    assert res.status_code == 200, res.text
    assert res.json()["registration_status"] == "PENDING" and "waits for somebody else" in res.json()["message"]
    with database.SessionLocal() as db:
        row = db.get(models.DBContractor, con["id"])
        assert beneficiary(db, row.client_id, "contractor", row.company_name, row.id)[2] == HELD
        log = db.query(models.DBAuditLog).filter(models.DBAuditLog.action == "contractor_money_details_changed").order_by(
            models.DBAuditLog.id.desc()).first()
        text = " ".join(str(getattr(log, f, "") or "") for f in ("details", "detail", "description", "new_value", "summary"))
        assert "...9012" in text and "...7777" in text and "999988887777" not in text
    # The person who changed it does not approve it; somebody else does, and then it is paid again.
    assert portal.post("/api/wo/contractors/%d/approve" % con["id"], json={}).status_code == 403
    assert tenant.post("/api/wo/contractors/%d/approve" % con["id"], json={}).status_code == 200
    with database.SessionLocal() as db:
        row = db.get(models.DBContractor, con["id"])
        assert beneficiary(db, row.client_id, "contractor", row.company_name, row.id)[0] == "999988887777"


def test_the_master_changing_bank_details_needs_no_second_approval(tenant):
    con = approved_contractor(tenant)
    res = tenant.put("/api/wo/contractors/%d" % con["id"], json=body_of(tenant, con["id"], bank_account="555566667777"))
    assert res.status_code == 200 and res.json()["registration_status"] == "APPROVED"


def test_the_budget_is_set_by_those_given_the_right_and_logged_with_figures(tenant, portal):
    from test_boq import make_boq, saved
    jid, boq = make_boq(tenant)
    key = next(l["key"] for l in saved(tenant, boq)["lines"] if l["kind"] == "item")
    item = [{"kind": "LABOUR", "description": "Gang", "uom": "cum", "coefficient": 1, "rate": 160}]
    planner = staff(tenant, "planning_billing")
    sign_in(portal, planner)
    assert portal.put("/api/jobs/%d/budget/lines/%s" % (jid, key), json={"items": item}).status_code == 403
    assert tenant.put("/api/jobs/%d/budget/lines/%s" % (jid, key), json={"items": item}).status_code == 200
    with database.SessionLocal() as db:
        log = db.query(models.DBAuditLog).filter(models.DBAuditLog.action == "budget_line").order_by(models.DBAuditLog.id.desc()).first()
        text = " ".join(str(getattr(log, f, "") or "") for f in ("details", "detail", "description", "new_value", "summary"))
        assert "160" in text


def test_whoever_measured_the_work_does_not_certify_its_bill(tenant, portal):
    order, item = setup(tenant)
    add(tenant, order, item, 5)
    bill = draw(tenant, order).json()["bill"]
    assert tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).status_code == 200
    pm = staff(tenant, "project_manager")
    with database.SessionLocal() as db:                         # the project manager measured it, and is on its route
        for m in db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.sub_bill_id == bill["id"]).all():
            m.recorded_by = pm["id"]
        db.add(models.DBApprovalChain(client_id=m.client_id, entity_type="sub_bill", entity_id=bill["id"],
                                      approver_id=pm["id"], step=1, status="pending"))
        db.commit()
    sign_in(portal, pm)
    res = portal.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    assert res.status_code == 403 and "recorded measurements" in res.json()["detail"]


def test_a_contractor_with_changed_bank_details_is_not_paid_by_hand_either(tenant, portal):
    """Pay & Receive holds them as the bank file does, until somebody else approves the change."""
    con = approved_contractor(tenant)
    sign_in(portal, staff(tenant, "project_manager"))
    portal.put("/api/wo/contractors/%d" % con["id"], json=body_of(tenant, con["id"], bank_account="999988887777"))
    pay = {"doc_type": "on_account", "doc_id": None, "direction": "OUT", "party_type": "contractor",
           "party_name": con["company_name"], "amount": 5000, "paid_on": "2026-11-01", "mode": "Cash", "reference": "",
           "note": "", "account_id": None, "job_id": None}
    held = tenant.post("/api/money/entries", json=pay)
    assert held.status_code == 409 and "waiting for approval" in held.json()["detail"], held.text
    assert tenant.post("/api/wo/contractors/%d/approve" % con["id"], json={}).status_code == 200
    assert tenant.post("/api/money/entries", json=pay).status_code == 200
