"""Findings from the audit that touch Projects, Planning & Progress and the BOQ.

Each test pins one: money that has moved is not deleted with a project, a bill is drawn at the project's own
retention, and one company can never reach another's BOQ lines, schedule, tasks or progress.
"""
import io
from datetime import date, timedelta

import openpyxl

from conftest import make_invoice
from test_measurement_and_ra_bills import line_of, measure, placed_order, raise_bill


def d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def make_job(client, name="Audit site", **extra):
    res = client.post("/api/jobs", json=dict({"name": name, "customer_name": "L&T"}, **extra))
    assert res.status_code == 200, res.text
    return res.json()


# --- a project is not deleted once money has moved through it ---------------------------------------------------------

def test_a_project_with_money_received_is_not_deleted(tenant):
    job = make_job(tenant)
    inv = make_invoice(tenant, job_id=job["id"], line_items=[{"description": "Stage 1", "qty": 1, "price": 5000.0, "tax_rate": "No Tax"}])
    assert tenant.post("/api/invoices/%s/mark-paid" % inv["number"]).status_code == 200

    preview = tenant.get("/api/jobs/%d/delete-preview" % job["id"]).json()
    assert preview["can_delete"] is False and "Money has moved" in preview["blockers"][0]
    refused = tenant.delete("/api/jobs/%d" % job["id"])
    assert refused.status_code == 409 and "money has moved" in refused.json()["detail"]
    assert tenant.get("/api/jobs/%d" % job["id"]).status_code == 200, "the project and its payment are still there"


def test_a_project_with_a_paid_supplier_bill_is_not_deleted(tenant):
    job = make_job(tenant)
    bill = tenant.post("/api/bills", json={"number": "B1", "vendor_name": "X", "amount": 1000.0, "total": 1000.0, "job_id": job["id"]}).json()
    # Part-paid, as a payment would leave it.
    from app import models
    from app.db.session import SessionLocal
    db = SessionLocal()
    db.query(models.DBBill).filter(models.DBBill.id == bill["id"]).update({"amount_paid": 400.0})
    db.commit()
    db.close()
    assert tenant.get("/api/jobs/%d/delete-preview" % job["id"]).json()["can_delete"] is False
    assert tenant.delete("/api/jobs/%d" % job["id"]).status_code == 409


def test_a_project_nothing_was_paid_on_can_still_be_deleted(tenant):
    job = make_job(tenant)
    tenant.post("/api/bills", json={"number": "B1", "vendor_name": "X", "amount": 10.0, "total": 10.0, "job_id": job["id"]})
    assert tenant.get("/api/jobs/%d/delete-preview" % job["id"]).json()["can_delete"] is True
    assert tenant.delete("/api/jobs/%d" % job["id"]).status_code == 200


# --- an RA bill is drawn at the project's own retention --------------------------------------------------------------

def test_an_ra_bill_takes_the_projects_retention_when_none_is_given(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    tenant.put("/api/jobs/%d" % wo["job_id"], json={"name": "Vizag", "retention_percent": 10})
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 1000)
    bill = raise_bill(tenant, wo["id"]).json()["bill"]
    assert bill["retention_percent"] == 10 and bill["retention_amount"] == 10000


def test_a_retention_given_on_the_bill_still_wins_even_nought(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    tenant.put("/api/jobs/%d" % wo["job_id"], json={"name": "Vizag", "retention_percent": 10})
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 1000)
    bill = raise_bill(tenant, wo["id"], retention_percent=0).json()["bill"]
    assert bill["retention_percent"] == 0 and bill["retention_amount"] == 0


def test_a_project_with_no_retention_set_keeps_the_usual_five_per_cent(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 1000)
    assert raise_bill(tenant, wo["id"]).json()["bill"]["retention_percent"] == 5


# --- one company cannot reach another's BOQ -----------------------------------------------------------------------------

def sheet(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def boq_with_lines(client, name):
    job = make_job(client, name)
    boq = client.post("/api/boqs", json={"job_id": job["id"]}).json()["boq"]
    rows = [["Description", "Unit", "Qty", "Rate"], ["EARTHWORK", None, None, None], ["Excavation", "cum", 100, 200]]
    lines = client.post("/api/boqs/%d/import" % boq["id"], files={"file": ("b.xlsx", sheet(rows))}).json()["lines"]
    saved = client.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines, "issue_codes": True})
    assert saved.status_code == 200, saved.text
    return boq, saved.json()["lines"]


def test_a_variation_cannot_name_another_companys_boq_line(tenant, second_tenant):
    theirs, their_lines = boq_with_lines(second_tenant, "Rival site")
    their_key = [l for l in their_lines if l["kind"] != "section"][0]["key"]
    mine, my_lines = boq_with_lines(tenant, "My site")
    res = tenant.post("/api/boq-variations", json={"boq_id": mine["id"], "reason": "x", "lines": [{"kind": "quantity", "boq_key": their_key, "change_qty": 900}]})
    assert res.status_code == 400, res.text
    # Nor can it be raised against their BOQ at all.
    assert tenant.post("/api/boq-variations", json={"boq_id": theirs["id"], "reason": "x", "lines": []}).status_code == 404
    assert [l["quantity"] for l in second_tenant.get("/api/boqs/%d" % theirs["id"]).json()["lines"] if l["kind"] != "section"] == [100]


def test_one_company_cannot_read_or_change_anothers_boq(tenant, second_tenant):
    theirs, _ = boq_with_lines(second_tenant, "Rival site")
    for url in ("/api/boqs/%d", "/api/boqs/%d/summary", "/api/boqs/%d/tracker", "/api/boqs/%d/export.xlsx"):
        assert tenant.get(url % theirs["id"]).status_code == 404, url
    assert tenant.put("/api/boqs/%d/lines" % theirs["id"], json={"lines": []}).status_code == 404
    assert "Rival" not in str(tenant.get("/api/boqs").json())


def test_a_typed_item_code_cannot_take_another_companys_item(tenant, second_tenant):
    _, their_lines = boq_with_lines(second_tenant, "Rival site")
    their_code = [l for l in their_lines if l["kind"] != "section"][0]["item_code"]
    job = make_job(tenant, "My site")
    boq = tenant.post("/api/boqs", json={"job_id": job["id"]}).json()["boq"]
    res = tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": [
        {"kind": "item", "description": "Excavation", "uom": "cum", "quantity": 1, "rate": 1, "item_code": their_code}], "issue_codes": True})
    assert res.status_code == 409


# --- one company cannot reach another's schedule, tasks or progress -----------------------------------------------------

def schedule_with_task(client):
    job = make_job(client, "Schedule site")
    s = client.post("/api/jobs/%d/schedule/activities" % job["id"], json={"name": "Excavation", "planned_start": d(-4), "planned_finish": d(5)}).json()["schedule"]
    aid = s["activities"][0]["id"]
    task = client.post("/api/jobs/%d/schedule/tasks" % job["id"], json={"text": "Dig", "date": d(0), "activity_id": aid}).json()["task"]
    return job, aid, task["id"]


def test_one_company_cannot_read_anothers_plan(tenant, second_tenant):
    job, _, _ = schedule_with_task(second_tenant)
    assert tenant.get("/api/jobs/%d/schedule" % job["id"]).status_code == 404
    assert tenant.get("/api/jobs/%d/schedule/day" % job["id"]).status_code == 404


def test_one_company_cannot_change_anothers_tasks_or_progress(tenant, second_tenant):
    job, aid, tid = schedule_with_task(second_tenant)
    assert tenant.put("/api/schedule/tasks/%d" % tid, json={"done": True}).status_code == 404
    assert tenant.delete("/api/schedule/tasks/%d" % tid).status_code == 404
    assert tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 100}).status_code == 404
    assert tenant.post("/api/jobs/%d/schedule/tasks" % job["id"], json={"text": "x", "date": d(0)}).status_code == 404
    day = second_tenant.get("/api/jobs/%d/schedule/day" % job["id"]).json()
    assert day["tasks"][0]["done"] is False and day["today"][0]["actual_percent"] == 0


def test_a_task_cannot_be_hung_on_another_companys_activity(tenant, second_tenant):
    _, their_activity, _ = schedule_with_task(second_tenant)
    mine = make_job(tenant, "My schedule site")
    res = tenant.post("/api/jobs/%d/schedule/tasks" % mine["id"], json={"text": "x", "date": d(0), "activity_id": their_activity})
    assert res.status_code == 400
