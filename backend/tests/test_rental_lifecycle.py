"""Hire agreements end to end: the lifecycle (Upcoming, Active, Overdue, Returned, Closed), what a return records, and how
bills, finance approval and payment stay three separate things."""
from test_plant_checks import day, hired_machine, job


def rental(tenant, rid):
    return next(r for r in tenant.get("/api/plant/rentals").json()["rentals"] if r["id"] == rid)


def bill(tenant, rid, no, amount, period=("2026-09-01", "2026-09-30"), **extra):
    body = {"invoice_no": no, "invoice_date": period[1], "period_from": period[0], "period_to": period[1], "amount": amount}
    body.update(extra)
    res = tenant.post("/api/plant/rentals/%d/invoices" % rid, json=body)
    assert res.status_code == 200, res.text
    return next(i for i in rental(tenant, rid)["invoices"] if i["invoice_no"] == no)


def approve(tenant, invoice_id):
    assert tenant.post("/api/plant/rental-invoices/%d/verify" % invoice_id, json={"decision": "approve"}).status_code == 200


SEPT = {"rate": 90000, "min_billable_hours": 0, "overtime_rate": 0, "start_date": "2026-09-01", "expected_return": "2026-09-30"}


def test_a_plain_return_still_works_as_before(tenant):
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    assert tenant.post("/api/plant/rentals/%d/return" % rid, json={"returned_on": "2026-09-30"}).status_code == 200
    r = rental(tenant, rid)
    assert r["actual_return"] == "2026-09-30" and r["status"] == "Returned"
    assert r["return"] == {"meter": None, "condition": "", "charges": 0, "note": "", "by": r["return"]["by"]} and r["return"]["by"]


def test_upcoming_active_and_overdue_come_from_the_dates_and_overdue_is_never_returned_by_itself(tenant):
    _, up = hired_machine(tenant, job(tenant), start_date=day(5), expected_return=day(30))
    _, on = hired_machine(tenant, job(tenant), start_date=day(-5), expected_return=day(30))
    _, late = hired_machine(tenant, job(tenant), start_date=day(-30), expected_return=day(-2))
    assert rental(tenant, up)["status"] == "Upcoming"
    assert rental(tenant, on)["status"] == "Active"
    r = rental(tenant, late)
    assert r["status"] == "Overdue" and r["days_left"] == -2 and r["actual_return"] == "" and r["return"] is None


def test_the_return_records_its_reading_condition_charges_and_who_confirmed_it(tenant):
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    url = "/api/plant/rentals/%d/return" % rid
    assert tenant.post(url, json={"returned_on": "2026-09-30", "condition": "Broken"}).status_code == 400
    assert tenant.post(url, json={"returned_on": "2026-09-30", "extra_charges": -1}).status_code == 400
    assert tenant.post(url, json={"returned_on": "2026-09-30", "extra_charges": 4000}).status_code == 400          # charges need a reason
    res = tenant.post(url, json={"returned_on": "2026-09-30", "final_meter": 1250, "condition": "Fair", "extra_charges": 4000, "note": "Dent on boom"})
    assert res.status_code == 200, res.text
    r = rental(tenant, rid)
    assert r["return"]["meter"] == 1250 and r["return"]["condition"] == "Fair" and r["return"]["charges"] == 4000 and r["return"]["note"] == "Dent on boom"
    machines = {a["id"]: a for a in tenant.get("/api/assets").json()["assets"]}
    assert machines[m["id"]]["meter_reading"] == 1250 and machines[m["id"]]["status"] == "Returned"
    # Returned once: a second return is refused, and the first stays as it was.
    assert tenant.post(url, json={"returned_on": "2026-09-30"}).status_code == 409


def test_a_final_reading_below_the_register_is_refused(tenant):
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    with __import__("main").SessionLocal() as db:
        from app import models
        db.query(models.DBAsset).filter(models.DBAsset.id == m["id"]).update({"meter_reading": 2000})
        db.commit()
    res = tenant.post("/api/plant/rentals/%d/return" % rid, json={"returned_on": "2026-09-30", "final_meter": 1999})
    assert res.status_code == 400 and "below the last reading" in res.json()["detail"]
    assert rental(tenant, rid)["actual_return"] == ""


def test_extra_charges_at_the_return_are_part_of_the_last_bill_expected(tenant):
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    assert tenant.post("/api/plant/rentals/%d/return" % rid, json={"returned_on": "2026-09-30", "extra_charges": 4000, "note": "Damage"}).status_code == 200
    bill(tenant, rid, "R-1", 94000)
    row = next(x for x in tenant.get("/api/plant/rental-verification?rental_id=%d" % rid).json()["rows"] if x["kind"] == "invoice")
    assert row["expected"] == 94000 and row["return_charges"] == 4000 and row["status"] == "Matched" and row["difference_percent"] == 0


def test_returned_becomes_closed_only_once_every_day_is_billed_and_every_bill_approved(tenant):
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    assert tenant.post("/api/plant/rentals/%d/return" % rid, json={"returned_on": "2026-09-30"}).status_code == 200
    r = rental(tenant, rid)
    assert r["status"] == "Returned" and "No bill recorded yet." in r["closing_gaps"] and r["unbilled_days"] == 30
    first = bill(tenant, rid, "C-1", 45000, ("2026-09-01", "2026-09-15"))
    r = rental(tenant, rid)
    assert r["status"] == "Returned" and "15 days on hire with no bill." in r["closing_gaps"]
    second = bill(tenant, rid, "C-2", 45000, ("2026-09-16", "2026-09-30"))
    r = rental(tenant, rid)
    assert r["status"] == "Returned" and r["closing_gaps"] == ["2 bills not yet approved by finance."]
    approve(tenant, first["id"])
    approve(tenant, second["id"])
    r = rental(tenant, rid)
    assert r["status"] == "Closed" and r["closing_gaps"] == []
    # Closed does not mean paid: what is owed stays owed, and stays visible.
    assert r["payment_status"] == "Unpaid" and r["outstanding"] == 90000
    assert {x["id"] for x in tenant.get("/api/plant/rentals?status=Closed").json()["rentals"]} >= {rid}
    assert tenant.get("/api/plant/rentals").json()["summary"]["Closed"] >= 1


def test_a_duplicate_bill_keeps_it_from_closing(tenant):
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    assert tenant.post("/api/plant/rentals/%d/return" % rid, json={"returned_on": "2026-09-30"}).status_code == 200
    a = bill(tenant, rid, "DUP-1", 90000)
    b = bill(tenant, rid, "DUP-2", 90000)
    approve(tenant, a["id"])
    approve(tenant, b["id"])
    r = rental(tenant, rid)
    assert r["status"] == "Returned" and r["closing_gaps"] == ["Duplicate bill: DUP-2."]


def test_payment_is_tracked_apart_from_approval(tenant):
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    inv = bill(tenant, rid, "P-1", 90000)
    assert inv["payment_status"] == "Unpaid" and inv["verification_status"] == ""
    approve(tenant, inv["id"])
    inv = next(i for i in rental(tenant, rid)["invoices"] if i["id"] == inv["id"])
    assert inv["verification_status"] == "Approved" and inv["payment_status"] == "Unpaid"          # approved is not paid
    assert tenant.post("/api/plant/rental-invoices/%d/payment" % inv["id"], json={"amount": 40000, "paid_on": "2026-10-05"}).status_code == 200
    r = rental(tenant, rid)
    assert r["payment_status"] == "Partially paid" and r["outstanding"] == 50000
    assert tenant.post("/api/plant/rental-invoices/%d/payment" % inv["id"], json={"amount": 50000, "paid_on": "2026-10-20"}).status_code == 200
    r = rental(tenant, rid)
    assert r["payment_status"] == "Paid" and r["outstanding"] == 0
    assert tenant.post("/api/plant/rental-invoices/%d/payment" % inv["id"], json={"amount": 1}).status_code == 400  # nothing more is owed


def test_the_same_invoice_number_cannot_be_recorded_twice(tenant):
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    bill(tenant, rid, "INV-77", 45000, ("2026-09-01", "2026-09-15"))
    res = tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "inv-77", "invoice_date": "2026-09-30", "amount": 45000})
    assert res.status_code == 409


def test_verification_rows_show_the_difference_as_a_share_and_the_days_billed_and_not(tenant):
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    assert tenant.post("/api/plant/rentals/%d/return" % rid, json={"returned_on": "2026-09-30"}).status_code == 200
    bill(tenant, rid, "V-1", 47250, ("2026-09-01", "2026-09-15"))
    rows = tenant.get("/api/plant/rental-verification?rental_id=%d" % rid).json()["rows"]
    inv = next(x for x in rows if x["kind"] == "invoice")
    gap = next(x for x in rows if x["kind"] == "missing")
    assert inv["expected"] == 45000 and inv["difference"] == 2250 and inv["difference_percent"] == 5.0 and inv["status"] == "Mismatch"
    assert inv["billed_days"] == 15 and inv["invoice_date"] == "2026-09-15"
    assert gap["unbilled_days"] == 15 and gap["billed_days"] == 15 and gap["status"] == "Incomplete"


# ---- providers, bill attachments and alerts -------------------------------------------------------

def test_a_provider_shows_its_agreements_open_and_finished_and_what_is_billed_paid_and_owed(tenant):
    m, done = hired_machine(tenant, job(tenant), **SEPT)
    pid = rental(tenant, done)["provider"]["id"]
    assert tenant.post("/api/plant/rentals/%d/return" % done, json={"returned_on": "2026-09-30"}).status_code == 200
    inv = bill(tenant, done, "PV-1", 90000)
    approve(tenant, inv["id"])
    assert tenant.post("/api/plant/rental-invoices/%d/payment" % inv["id"], json={"amount": 60000, "paid_on": "2026-10-10", "payment_ref": "UTR-1"}).status_code == 200
    d = tenant.get("/api/plant/rental-providers/%d" % pid).json()
    assert d["provider"]["id"] == pid and d["open"] == []
    assert [x["number"] for x in d["completed"]] == [rental(tenant, done)["number"]] and d["completed"][0]["status"] == "Closed"
    assert d["totals"] == {"agreements": 1, "billed": 90000, "paid": 60000, "outstanding": 30000, "approved_outstanding": 30000}
    assert d["payments"] == [{"invoice_no": "PV-1", "rental": rental(tenant, done)["number"], "paid": 60000, "paid_on": "2026-10-10", "payment_ref": "UTR-1"}]
    assert tenant.get("/api/plant/rental-providers/999999").status_code == 404


def test_a_rental_bill_can_carry_its_own_attachment(tenant):
    from test_project_files import PDF, upload
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    inv = bill(tenant, rid, "ATT-1", 90000)
    res = upload(tenant, "plant_rental_invoice", inv["id"], data=PDF, name="att-1.pdf", ctype="application/pdf")
    assert res.status_code == 200, res.text
    assert upload(tenant, "plant_rental_invoice", 999999, data=PDF, name="x.pdf", ctype="application/pdf").status_code == 404


def test_a_bill_that_differs_or_repeats_is_alerted_once_and_an_approved_bill_left_unpaid_too(tenant):
    from datetime import date
    import main
    from app.services.plant_checks import run_bill_alerts
    from test_plant_checks import _client_id
    m, rid = hired_machine(tenant, job(tenant), **SEPT)
    off = bill(tenant, rid, "AL-1", 99000)                        # 10% over: a difference
    bill(tenant, rid, "AL-2", 99000)                              # the same days again: a duplicate
    cid = _client_id(m)
    with main.SessionLocal() as db:
        assert run_bill_alerts(db, cid, date(2026, 10, 1)) == 2
        assert run_bill_alerts(db, cid, date(2026, 10, 2)) == 0   # one alert per bill and issue
    kinds = {a["kind"]: a for a in tenant.get("/api/plant/alerts").json()["alerts"] if a["rental_id"] == rid}
    assert {"bill_difference", "bill_duplicate"} <= set(kinds)
    assert "AL-1" in kinds["bill_difference"]["title"] and "tolerance 2%" in kinds["bill_difference"]["body"]
    # Approved, then still unpaid a month after its date.
    approve(tenant, off["id"])
    with main.SessionLocal() as db:
        assert run_bill_alerts(db, cid, date(2026, 10, 15)) == 0  # not yet a month
        assert run_bill_alerts(db, cid, date(2026, 11, 5)) == 1
        assert run_bill_alerts(db, cid, date(2026, 11, 6)) == 0
    unpaid = [a for a in tenant.get("/api/plant/alerts?kind=bill_unpaid").json()["alerts"] if a["rental_id"] == rid]
    assert len(unpaid) == 1 and "99000" in unpaid[0]["body"]
