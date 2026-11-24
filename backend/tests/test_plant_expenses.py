"""Equipment expenses: entered, submitted, decided and paid as separate steps; fuel, maintenance and rental bills read
from their own registers, once each; the register's filters, search, summary and export."""
import io
import uuid

import main
from app import models
from conftest import make_employee
from test_plant_checks import day, hired_machine, job, machine
from test_project_files import PDF, upload


def body(m, **over):
    b = {"asset_id": m["id"], "category": "Spare parts", "spent_on": day(-2), "description": "Bucket teeth x 5", "quantity": 5, "unit_rate": 1200,
         "vendor": "JCB Parts", "invoice_no": "JP-%s" % uuid.uuid4().hex[:6]}
    b.update(over)
    return b


def record(tenant, m, **over):
    res = tenant.post("/api/plant/expenses", json=body(m, **over))
    assert res.status_code == 200, res.text
    return res.json()["id"]


def row(tenant, eid, **params):
    params.setdefault("q", "")
    reg = tenant.get("/api/plant/expenses", params=params).json()["expenses"]
    return next(r for r in reg if r["source"] == "expense" and r["id"] == eid)


def submit(tenant, eid):
    res = tenant.post("/api/plant/expenses/%d/submit" % eid)
    assert res.status_code == 200, res.text


def approve(tenant, eid):
    res = tenant.post("/api/plant/expenses/%d/decision" % eid, json={"decision": "approve"})
    assert res.status_code == 200, res.text


def pay(tenant, eid, amount, **over):
    b = {"amount": amount, "paid_on": day(-1), "reference": "UTR-%s" % uuid.uuid4().hex[:6]}
    b.update(over)
    return tenant.post("/api/plant/expenses/%d/payments" % eid, json=b)


def staff_with(tenant, portal, permissions):
    emp = make_employee(tenant, password="EmpPass123")
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    res = tenant.put("/api/employees/%d/permissions" % emp["id"], json={"permission_role": "staff", "permissions": permissions})
    assert res.status_code == 200, res.text
    assert portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"}).status_code == 200
    return portal


# ---- recording and editing ------------------------------------------------------------------------

def test_a_manual_expense_is_recorded_with_its_vendor_and_invoice(tenant):
    m = machine(tenant)
    eid = record(tenant, m, invoice_no="JP-55")
    r = row(tenant, eid)
    assert r["approval_status"] == "Recorded" and r["approval_label"] == "Recorded" and r["amount"] == 6000
    assert r["vendor"] == "JCB Parts" and r["invoice_no"] == "JP-55" and r["number"].startswith("EXP-")
    assert r["payment_status"] == "Unpaid" and r["paid"] == 0 and r["remaining"] == 6000


def test_mandatory_fields_amounts_dates_machines_and_categories_are_checked(tenant):
    m = machine(tenant)
    post = lambda **over: tenant.post("/api/plant/expenses", json=body(m, **over)).status_code
    assert post(description="") == 400
    assert post(quantity=0, unit_rate=0, amount=0) == 400
    assert post(quantity=-1) == 400
    assert post(spent_on=day(5)) == 400
    assert post(spent_on="31-31-2026") == 400
    assert post(category="Lunch") == 400
    assert post(category="Fuel and diesel") == 400                 # has its own register
    assert post(asset_id=999999) == 404


def test_editing_changes_the_same_record_and_sends_it_back_to_recorded(tenant):
    m = machine(tenant)
    eid = record(tenant, m)
    before = len(tenant.get("/api/plant/expenses").json()["expenses"])
    number = row(tenant, eid)["number"]
    submit(tenant, eid)
    res = tenant.put("/api/plant/expenses/%d" % eid, json=body(m, description="Bucket teeth x 6", quantity=6))
    assert res.status_code == 200 and "Submit it again" in res.json()["message"]
    r = row(tenant, eid)
    assert r["number"] == number and r["amount"] == 7200 and r["approval_status"] == "Recorded"
    assert len(tenant.get("/api/plant/expenses").json()["expenses"]) == before                # no second record
    submit(tenant, eid)
    approve(tenant, eid)
    assert tenant.put("/api/plant/expenses/%d" % eid, json=body(m)).status_code == 409        # approved: the record now


def test_the_same_invoice_or_the_same_cost_twice_is_refused(tenant):
    m = machine(tenant)
    record(tenant, m, invoice_no="DUP-9")
    assert tenant.post("/api/plant/expenses", json=body(m, invoice_no="dup-9")).status_code == 409
    record(tenant, m, invoice_no="", description="Grease", quantity=0, unit_rate=0, amount=450)
    assert tenant.post("/api/plant/expenses", json=body(m, invoice_no="", description="Grease", quantity=0, unit_rate=0, amount=450)).status_code == 409


def test_an_expense_carries_its_attachment(tenant):
    m = machine(tenant)
    eid = record(tenant, m)
    res = upload(tenant, "plant_expense", eid, data=PDF, name="bill.pdf", ctype="application/pdf")
    assert res.status_code == 200, res.text
    fid = res.json()["file"]["id"]
    got = tenant.get("/api/files/%d" % fid)
    assert got.status_code == 200 and got.content == PDF


# ---- approval -------------------------------------------------------------------------------------

def test_recorded_then_submitted_then_approved_once_with_who_and_when(tenant):
    m = machine(tenant)
    eid = record(tenant, m)
    assert tenant.post("/api/plant/expenses/%d/decision" % eid, json={"decision": "approve"}).status_code == 409   # not submitted yet
    submit(tenant, eid)
    assert row(tenant, eid)["approval_label"] == "Submitted"
    assert tenant.post("/api/plant/expenses/%d/submit" % eid).status_code == 409             # once
    approve(tenant, eid)
    r = row(tenant, eid)
    assert r["approval_status"] == "Approved" and r["approved_by"] and r["approved_on"]
    assert tenant.post("/api/plant/expenses/%d/decision" % eid, json={"decision": "approve"}).status_code == 409   # decided once


def test_a_rejection_needs_its_reason_and_keeps_it(tenant):
    m = machine(tenant)
    eid = record(tenant, m)
    submit(tenant, eid)
    assert tenant.post("/api/plant/expenses/%d/decision" % eid, json={"decision": "reject"}).status_code == 400
    assert tenant.post("/api/plant/expenses/%d/decision" % eid, json={"decision": "reject", "remarks": "No bill attached"}).status_code == 200
    r = row(tenant, eid)
    assert r["approval_status"] == "Rejected" and r["decision_note"] == "No bill attached"
    # Rejected is put right by editing, which makes it Recorded again, to be submitted again.
    assert tenant.put("/api/plant/expenses/%d" % eid, json=body(m, invoice_no=row(tenant, eid)["invoice_no"])).status_code == 200
    assert row(tenant, eid)["approval_status"] == "Recorded"


def test_an_approval_can_be_reversed_by_rejecting_it_only_before_anything_is_paid(tenant):
    m = machine(tenant)
    a, b = record(tenant, m), record(tenant, m, description="Hydraulic oil")
    for eid in (a, b):
        submit(tenant, eid)
        approve(tenant, eid)
    assert tenant.post("/api/plant/expenses/%d/decision" % a, json={"decision": "reject", "remarks": "Billed to the contractor"}).status_code == 200
    assert pay(tenant, b, 1000).status_code == 200
    res = tenant.post("/api/plant/expenses/%d/decision" % b, json={"decision": "reject", "remarks": "Wrong machine"})
    assert res.status_code == 409 and "payments recorded" in res.json()["detail"]


def test_who_may_record_submit_approve_and_pay(tenant, portal):
    m = machine(tenant)
    eid = record(tenant, m)
    assert portal.post("/api/plant/expenses", json=body(m)).status_code in (401, 403)                # signed out
    clerk = staff_with(tenant, portal, ["stores.manage", "projects.view"])
    own = clerk.post("/api/plant/expenses", json=body(m))
    assert own.status_code == 200, own.text
    assert clerk.post("/api/plant/expenses/%d/submit" % own.json()["id"]).status_code == 200
    # Recording is not approving: the clerk cannot decide on his own expense or anybody else's.
    assert clerk.post("/api/plant/expenses/%d/decision" % own.json()["id"], json={"decision": "approve"}).status_code == 403
    submit(tenant, eid)
    assert clerk.post("/api/plant/expenses/%d/decision" % eid, json={"decision": "approve"}).status_code == 403
    assert row(tenant, eid)["approval_status"] == "Pending"


def test_staff_without_plant_rights_change_nothing(tenant, portal):
    m = machine(tenant)
    eid = record(tenant, m)
    nobody = staff_with(tenant, portal, ["self.service"])
    assert nobody.post("/api/plant/expenses", json=body(m)).status_code == 403
    assert nobody.put("/api/plant/expenses/%d" % eid, json=body(m)).status_code == 403
    assert nobody.post("/api/plant/expenses/%d/submit" % eid).status_code == 403
    assert nobody.delete("/api/plant/expenses/%d" % eid).status_code == 403
    assert row(tenant, eid)["approval_status"] == "Recorded"


# ---- payment --------------------------------------------------------------------------------------

def test_payments_come_after_approval_in_parts_and_never_past_what_is_owed(tenant):
    m = machine(tenant)
    eid = record(tenant, m)                                                         # 6,000
    assert pay(tenant, eid, 1000).status_code == 409                               # not approved yet
    submit(tenant, eid)
    approve(tenant, eid)
    r = row(tenant, eid)
    assert r["approval_status"] == "Approved" and r["payment_status"] == "Unpaid"  # approved is not paid
    assert pay(tenant, eid, 0).status_code == 400
    assert pay(tenant, eid, 7000).status_code == 400                               # more than is owed
    assert pay(tenant, eid, 1000, paid_on=day(3)).status_code == 400               # in the future
    assert pay(tenant, eid, 1000, paid_on=day(-30)).status_code == 400             # before the expense
    assert pay(tenant, eid, 2500).status_code == 200
    r = row(tenant, eid)
    assert r["payment_status"] == "Part paid" and r["paid"] == 2500 and r["remaining"] == 3500 and r["approval_status"] == "Approved"
    assert pay(tenant, eid, 3501).status_code == 400
    assert pay(tenant, eid, 3500).status_code == 200
    r = row(tenant, eid)
    assert r["payment_status"] == "Paid" and r["paid"] == 6000 and r["remaining"] == 0 and r["payments"] == 2
    assert pay(tenant, eid, 1).status_code == 400


def test_a_payment_sent_twice_with_its_key_is_kept_once(tenant):
    m = machine(tenant)
    eid = record(tenant, m)
    submit(tenant, eid)
    approve(tenant, eid)
    once = {"amount": 1000, "paid_on": day(-1), "reference": "UTR-ONCE"}
    key = {"Idempotency-Key": "pay-%s" % uuid.uuid4().hex}
    first = tenant.post("/api/plant/expenses/%d/payments" % eid, json=once, headers=key)
    again = tenant.post("/api/plant/expenses/%d/payments" % eid, json=once, headers=key)
    assert first.status_code == again.status_code == 200 and again.headers.get("Idempotent-Replay") == "true"
    assert row(tenant, eid)["paid"] == 1000


def test_the_history_keeps_every_step_and_every_payment(tenant):
    m = machine(tenant)
    eid = record(tenant, m)
    submit(tenant, eid)
    approve(tenant, eid)
    assert pay(tenant, eid, 2000, reference="UTR-H1").status_code == 200
    h = tenant.get("/api/plant/expenses/%d/history" % eid).json()
    assert [x["action"] for x in h["history"]] == ["recorded", "submitted", "approved", "paid"]
    assert h["payments"][0]["amount"] == 2000 and h["payments"][0]["reference"] == "UTR-H1" and h["payments"][0]["by"]
    assert h["paid"] == 2000 and h["remaining"] == 4000


def test_an_expense_marked_paid_before_payments_were_recorded_stays_paid(tenant):
    m = machine(tenant)
    old_paid, old_part = record(tenant, m), record(tenant, m, description="Old part paid")
    with main.SessionLocal() as db:
        for eid, st in ((old_paid, "Paid"), (old_part, "Part paid")):
            db.query(models.DBPlantExpense).filter(models.DBPlantExpense.id == eid).update({"payment_status": st, "approval_status": "Approved"})
        db.commit()
    a, b = row(tenant, old_paid), row(tenant, old_part)
    assert a["payment_status"] == "Paid" and a["paid"] == 6000 and a["remaining"] == 0 and a["legacy_payment"]
    assert b["payment_status"] == "Part paid" and b["legacy_payment"] and b["remaining"] == 6000
    assert pay(tenant, old_paid, 1).status_code == 400                     # nothing left on a paid one


# ---- the register: filters, search, summary ------------------------------------------------------

def test_filters_search_and_the_summary_follow_the_records(tenant):
    j = job(tenant)
    a, b = machine(tenant, name="Excavator"), machine(tenant, name="Roller")
    spares = record(tenant, a, invoice_no="SP-1", vendor="JCB Parts", spent_on=day(-3))                       # 6,000
    trans = record(tenant, b, category="Transportation and shifting", description="Low-bed", quantity=0, unit_rate=0, amount=9000,
                   invoice_no="TR-1", vendor="Sai Logistics", spent_on=day(-10))
    dropped = record(tenant, a, category="Other", description="Doubtful", quantity=0, unit_rate=0, amount=500, invoice_no="OT-1", vendor="X", spent_on=day(-3))
    submit(tenant, dropped)
    tenant.post("/api/plant/expenses/%d/decision" % dropped, json={"decision": "reject", "remarks": "No bill"})
    reg = lambda **p: tenant.get("/api/plant/expenses", params=p).json()
    mine = lambda d: {r["id"] for r in d["expenses"] if r["source"] == "expense"} & {spares, trans, dropped}
    everything = reg(asset_id=a["id"])
    assert everything["by_category"] == {"Spare parts": 6000} and everything["total_all"] == 6000      # rejected is not counted
    assert mine(reg(date_from=day(-5), date_to=day(0))) == {spares, dropped}
    assert mine(reg(date_from=day(-12), date_to=day(-8))) == {trans}
    assert tenant.get("/api/plant/expenses", params={"date_from": day(0), "date_to": day(-5)}).status_code == 400
    assert mine(reg(asset_id=b["id"])) == {trans}
    by_cat = reg(category="Transportation and shifting")
    assert mine(by_cat) == {trans}
    # The cards keep every category so any can be chosen; the total of what is shown follows the category.
    assert {"Spare parts", "Transportation and shifting"} <= set(by_cat["by_category"]) and by_cat["total"] < by_cat["total_all"]
    assert mine(reg(q="sai log")) == {trans}                     # vendor
    assert mine(reg(q="sp-1")) == {spares}                       # invoice
    number = row(tenant, spares)["number"]
    assert mine(reg(q=number)) == {spares}                       # expense id
    assert reg(q="nothing-like-this")["expenses"] == []


def test_fuel_maintenance_and_rental_bills_appear_once_from_their_own_registers(tenant):
    j = job(tenant)
    m = machine(tenant)
    stored = lambda: main.SessionLocal().query(models.DBPlantExpense).count()
    before = stored()
    fuel = tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 10, "rate": 100, "voucher_no": "FV-%s" % uuid.uuid4().hex[:5]})
    assert fuel.status_code == 200, fuel.text
    raised = tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Corrective", "description": "Hose"}).json()
    assert tenant.post("/api/plant/maintenance/%d/complete" % raised["id"], json={"work_performed": "Hose replaced", "parts_cost": 1200, "labour_cost": 300}).status_code == 200
    hm, rid = hired_machine(tenant, j)
    assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "RB-%s" % uuid.uuid4().hex[:5], "invoice_date": "2026-09-30", "amount": 45000}).status_code == 200
    assert stored() == before                                    # nothing copied into expenses
    rows = tenant.get("/api/plant/expenses").json()["expenses"]
    src = lambda s, aid: [r for r in rows if r["source"] == s and r["asset_id"] == aid]
    assert len(src("fuel", m["id"])) == 1 and src("fuel", m["id"])[0]["amount"] == 1000
    assert len(src("maintenance", m["id"])) == 1 and src("maintenance", m["id"])[0]["amount"] == 1500
    rental = src("rental", hm["id"])
    assert len(rental) == 1 and rental[0]["amount"] == 45000 and rental[0]["remaining"] == 45000
    # A source removed where it was recorded is gone from the register too.
    assert tenant.delete("/api/plant/fuel/%d" % src("fuel", m["id"])[0]["id"]).status_code == 200
    assert [r for r in tenant.get("/api/plant/expenses").json()["expenses"] if r["source"] == "fuel" and r["asset_id"] == m["id"]] == []


def test_the_export_follows_the_screens_filters(tenant):
    from openpyxl import load_workbook
    a = machine(tenant, name="Paver")
    record(tenant, a, invoice_no="EX-1", vendor="Alpha Spares")
    record(tenant, a, category="Other", description="Permit", quantity=0, unit_rate=0, amount=800, invoice_no="EX-2", vendor="Beta")
    res = tenant.get("/api/plant/reports/expenses.xlsx", params={"asset_id": a["id"], "category": "Other"})
    assert res.status_code == 200
    ws = load_workbook(io.BytesIO(res.content)).active
    cells = [str(c.value) for r in ws.iter_rows() for c in r if c.value is not None]
    assert "Permit" in cells and "Beta" in cells and "Alpha Spares" not in cells
    res = tenant.get("/api/plant/reports/expenses.xlsx", params={"asset_id": a["id"], "q": "alpha"})
    cells = [str(c.value) for r in load_workbook(io.BytesIO(res.content)).active.iter_rows() for c in r if c.value is not None]
    assert "Alpha Spares" in cells and "Beta" not in cells


# ---- the same invoice number: one vendor's, or two vendors' ---------------------------------------

def test_the_same_invoice_number_from_two_vendors_is_two_invoices_from_one_vendor_it_is_one(tenant):
    m = machine(tenant)
    record(tenant, m, invoice_no="INV-123", vendor="Vendor A")
    record(tenant, m, invoice_no="INV-123", vendor="Vendor B", description="Hydraulic hose")     # another vendor: allowed
    for again in ({"invoice_no": "INV-123", "vendor": "Vendor A"}, {"invoice_no": " inv - 123 ", "vendor": " vendor  a "}, {"invoice_no": "INV-123", "vendor": "Vendor B"}):
        res = tenant.post("/api/plant/expenses", json=body(m, description="Again", **again))
        assert res.status_code == 409, (again, res.text)
    # No vendor named: the number alone decides, as before vendors were compared - a blank never lets a repeat through.
    assert tenant.post("/api/plant/expenses", json=body(m, invoice_no="INV-123", vendor="")).status_code == 409


def test_the_vendor_rule_holds_across_fuel_maintenance_rental_bills_and_expenses(tenant):
    j = job(tenant)
    m = machine(tenant)
    assert tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 10, "rate": 100, "voucher_no": "V-77", "supplier": "HP Pump"}).status_code == 200
    assert tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 10, "rate": 100, "voucher_no": "v-77", "supplier": "HP Pump"}).status_code == 409
    assert tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 10, "rate": 100, "voucher_no": "V-77", "supplier": "IOC Pump"}).status_code == 200
    assert tenant.post("/api/plant/expenses", json=body(m, invoice_no="V-77", vendor="HP Pump")).status_code == 409   # the fuel voucher
    record(tenant, m, invoice_no="V-77", vendor="Sri Spares")                                                         # another vendor's
    raised = tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Corrective", "description": "Hose", "mechanic": "Ravi Works"}).json()
    done = tenant.post("/api/plant/maintenance/%d/complete" % raised["id"], json={"work_performed": "Hose", "parts_cost": 1200, "labour_cost": 0, "invoice_no": "MW-5"})
    assert done.status_code == 200, done.text
    assert tenant.post("/api/plant/expenses", json=body(m, invoice_no="MW-5", vendor="Ravi Works")).status_code == 409
    record(tenant, m, invoice_no="MW-5", vendor="Other Garage")
    # Rental bills: the provider is the vendor.
    _, r1 = hired_machine(tenant, j)
    _, r2 = hired_machine(tenant, j)
    bill = lambda rid, no: tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": no, "invoice_date": "2026-09-30", "amount": 1000}).status_code
    assert bill(r1, "RB-1") == 200
    assert bill(r2, "RB-1") == 200                     # another provider's bill with the same number
    assert bill(r1, " rb - 1") == 409                  # the same provider's, again


# ---- fuel, maintenance and rental payments as their registers keep them ---------------------------

def test_fuel_and_maintenance_are_never_shown_paid_for_want_of_a_record(tenant):
    m = machine(tenant)
    assert tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 10, "rate": 100, "voucher_no": "FP-%s" % uuid.uuid4().hex[:5]}).status_code == 200
    raised = tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Corrective", "description": "Hose"}).json()
    assert tenant.post("/api/plant/maintenance/%d/complete" % raised["id"], json={"work_performed": "Hose", "parts_cost": 500, "labour_cost": 0}).status_code == 200
    payments_before = main.SessionLocal().query(models.DBPlantExpensePayment).count()
    rows = [r for r in tenant.get("/api/plant/expenses").json()["expenses"] if r["asset_id"] == m["id"]]
    for r in rows:
        assert r["payment_status"] == "Not tracked" and r["paid"] is None and r["remaining"] is None, r
    assert {r["payment_note"] for r in rows} == {"Payment is not recorded in the Fuel register", "Payment is not recorded in Maintenance"}
    assert main.SessionLocal().query(models.DBPlantExpensePayment).count() == payments_before     # nothing paid twice, nothing invented


def test_a_rental_bills_payments_show_in_expenses_as_the_rental_register_keeps_them(tenant):
    m, rid = hired_machine(tenant, job(tenant))
    assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "RP-%s" % rid, "invoice_date": "2026-09-30", "amount": 45000}).status_code == 200
    inv = lambda: next(r for r in tenant.get("/api/plant/expenses").json()["expenses"] if r["source"] == "rental" and r["asset_id"] == m["id"])
    assert inv()["payment_status"] == "Unpaid" and inv()["remaining"] == 45000
    paid = tenant.post("/api/plant/rental-invoices/%d/payment" % inv()["id"], json={"amount": 20000, "paid_on": "2026-10-05", "payment_ref": "UTR-R1"})
    assert paid.status_code == 200
    r = inv()
    assert r["payment_status"] == "Part paid" and r["paid"] == 20000 and r["remaining"] == 25000 and r["payment_ref"] == "UTR-R1" and "2026-10-05" in r["payment_note"]
    assert tenant.post("/api/plant/rental-invoices/%d/payment" % r["id"], json={"amount": 25000, "paid_on": "2026-10-20", "payment_ref": "UTR-R2"}).status_code == 200
    r = inv()
    assert r["payment_status"] == "Paid" and r["remaining"] == 0 and r["payment_ref"] == "UTR-R2"
    rows = [x for x in tenant.get("/api/plant/expenses").json()["expenses"] if x["source"] == "rental" and x["asset_id"] == m["id"]]
    assert len(rows) == 1                                             # one bill, one row
