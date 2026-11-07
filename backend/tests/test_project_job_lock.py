"""Job Lock: a project the Master locks takes no change from anybody - staff, other users or the Master - until the Master
unlocks it. Reading it goes on as before."""
from datetime import date

from conftest import make_employee
from test_boq import make_boq, saved
from test_subcontract_orders import draft
from test_stock_control import receive, rm_item

PASSWORD = "Crew1234"
TODAY = date.today().isoformat()


def lock(tenant, jid, reason="Client dispute"):
    res = tenant.post("/api/jobs/%d/lock" % jid, json={"reason": reason})
    assert res.status_code == 200, res.text


def unlock(tenant, jid):
    assert tenant.post("/api/jobs/%d/unlock" % jid, json={}).status_code == 200


def refused(res):
    return res.status_code == 423 and "locked by the Master" in res.json()["detail"]


def test_a_locked_project_refuses_every_kind_of_change_and_says_why(tenant):
    jid, boq = make_boq(tenant)
    lines = saved(tenant, boq)["lines"]
    lock(tenant, jid, "Client dispute")
    res = tenant.post("/api/diary", json={"job_id": jid, "diary_date": TODAY, "weather": "Clear", "working_hours": 8})
    assert refused(res) and "Client dispute" in res.json()["detail"]
    assert refused(tenant.put("/api/jobs/%d" % jid, json={"name": "Renamed", "customer_name": "Kokapet LLP"}))
    # A child record: the BOQ's lines are the project's through the BOQ.
    assert refused(tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines[:1]}))
    assert refused(tenant.post("/api/safety/incidents", json={"job_id": jid, "kind": "Near miss", "happened_on": TODAY, "happened_at": "10:00",
                                                             "location": "A", "description": "x", "injured_name": "", "injury": "",
                                                             "treatment": "", "lost_days": 0, "immediate_action": "x"}))


def test_reading_it_goes_on(tenant):
    jid, boq = make_boq(tenant)
    lock(tenant, jid)
    assert tenant.get("/api/jobs/%d" % jid).status_code == 200
    assert tenant.get("/api/boqs/%d" % boq["id"]).status_code == 200
    got = tenant.get("/api/jobs/%d" % jid).json()
    assert got["locked"] and got["lock_reason"]


def test_a_work_order_and_a_store_issue_for_it_are_refused(tenant):
    jid, _ = make_boq(tenant)
    order = draft(tenant, job_id=jid)
    item = rm_item(tenant)
    receive(tenant, item, 10, 100)
    lock(tenant, jid)
    assert refused(tenant.put("/api/wo/orders/%d" % order["id"], json={**order, "subject": "Changed"}))
    assert refused(tenant.post("/api/stock-issues", json={"job_id": jid, "lines": [{"item_code": item, "quantity": 1}]}))


def test_other_projects_carry_on(tenant):
    locked, _ = make_boq(tenant, job_name="Frozen")
    open_job, _ = make_boq(tenant, job_name="Open")
    lock(tenant, locked)
    res = tenant.post("/api/diary", json={"job_id": open_job, "diary_date": TODAY, "weather": "Clear", "working_hours": 8})
    assert res.status_code == 200, res.text


def test_once_unlocked_it_takes_changes_again(tenant):
    jid, _ = make_boq(tenant)
    lock(tenant, jid)
    unlock(tenant, jid)
    assert not tenant.get("/api/jobs/%d" % jid).json()["locked"]
    res = tenant.post("/api/diary", json={"job_id": jid, "diary_date": TODAY, "weather": "Clear", "working_hours": 8})
    assert res.status_code == 200, res.text


def test_only_the_master_locks_and_unlocks(tenant, portal):
    jid, _ = make_boq(tenant)
    e = make_employee(tenant, permission_role="head_projects", password=PASSWORD, emergency_contact="Asha", emergency_phone="9999999999")
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    assert portal.post("/api/employee/auth/login", json={"email": e["email"], "password": PASSWORD}).status_code == 200
    assert portal.post("/api/jobs/%d/lock" % jid, json={"reason": "x"}).status_code in (401, 403)
    lock(tenant, jid)
    assert portal.post("/api/jobs/%d/unlock" % jid, json={}).status_code in (401, 403)
    # Staff are refused too.
    res = portal.post("/api/diary", json={"job_id": jid, "diary_date": TODAY, "weather": "Clear", "working_hours": 8})
    assert res.status_code in (423, 403, 404)


def test_a_lock_needs_a_reason(tenant):
    jid, _ = make_boq(tenant)
    assert tenant.post("/api/jobs/%d/lock" % jid, json={}).status_code == 400


def test_another_company_cannot_lock_it(tenant, second_tenant):
    jid, _ = make_boq(tenant)
    assert second_tenant.post("/api/jobs/%d/lock" % jid, json={"reason": "x"}).status_code == 404
