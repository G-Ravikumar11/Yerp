"""The access levels open the Store Hub for the jobs people do: a storekeeper keeps a store but approves nothing, the store
in-charge approves and cancels, a site engineer asks for material, a project manager approves a project's indents, and the
departments that only read get only the views. Staff still work only in the stores they are assigned to."""
import uuid
from datetime import date

from fastapi.testclient import TestClient

import main
from app.core.permissions import EMPLOYEE_ROLES, ROLE_PERMISSIONS
from conftest import make_employee
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok  # noqa: F401

TODAY = date.today().isoformat()


def hub(role):
    return {k[len("store."):] for k in ROLE_PERMISSIONS[role] if k.startswith("store.") and k != "store.view"}


def test_a_storekeeper_keeps_a_store_and_approves_nothing():
    keeper = hub("stores")
    assert {"inward.create", "inward.post", "outward.create", "outward.post", "control.create", "control.post", "enquiry.view"} <= keeper
    assert not {k for k in keeper if k.endswith((".approve", ".cancel"))} and "admin" not in keeper and "outward.direct_issue" not in keeper


def test_the_store_in_charge_approves_and_the_coordinator_gets_it():
    incharge = hub("store_incharge")
    assert hub("stores") < incharge
    assert {"inward.approve", "outward.approve", "control.approve", "control.cancel", "masters.create", "control.approve_high_value"} <= incharge
    assert "admin" not in incharge                                                 # every store, every right stays the Master's to give
    assert next(r for r in EMPLOYEE_ROLES if r["code"] == "store_coordinator")["access"] == "store_incharge"
    assert next(r for r in EMPLOYEE_ROLES if r["code"] == "store_assistant")["access"] == "stores"


def test_the_other_jobs_get_what_they_do_in_the_store():
    assert hub("construction") == {"enquiry.view", "outward.view", "outward.create"}            # asks for material
    assert {"outward.approve", "reports.view"} <= hub("project_manager") and "inward.post" not in hub("project_manager")
    for role in ("purchase", "accounts", "ho_qs", "ho_coordinator"):
        assert all(k.endswith(".view") for k in hub(role)), role                                # they only read
    assert hub("staff") == set() and hub("hr_admin") == set()


def test_a_storekeeper_can_now_work_in_the_hub_but_only_in_their_store(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    other = ok(t.post("/api/store/masters/stores", json={"code": "OT" + tag[:3].upper(), "name": "Other", "type": "CENTRAL"}))
    email = "keeper-%s@example.com" % tag
    emp = make_employee(t, email=email, password="Crew1234", permission_role="stores", status="active")
    ok(t.post("/api/store/masters/stores/%d/assignments" % central["id"], json={"employee_id": emp["id"], "role": "STOREKEEPER"}))
    c = TestClient(main.app)
    c.__enter__()
    try:
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        po_id, po_line = w["pos"][0]
        body = {"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "lines": [{"po_line_id": po_line, "qty": "10", "uom": "bag"}]}
        grn = ok(c.post("/api/store/inward/grn", json=body))                                     # receives
        assert c.post("/api/store/inward/grn/%d/submit" % grn["id"]).status_code == 200
        assert c.post("/api/store/inward/grn/%d/approve" % grn["id"]).status_code == 403          # but does not approve
        assert c.post("/api/store/inward/grn", json=dict(body, store_id=other["id"])).status_code == 403      # nor work in a store not theirs
    finally:
        c.__exit__(None, None, None)


def test_putting_people_in_a_store_needs_the_approve_right(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    url = "/api/store/masters/stores/%d/assignments" % central["id"]
    colleague = make_employee(t, email="col-%s@example.com" % tag, password="Crew1234", permission_role="staff", status="active")
    logins = {}
    for role, extra in (("stores", "store.masters.create"), ("store_incharge", "")):
        email = "%s-%s@example.com" % (role, tag)
        emp = make_employee(t, email=email, password="Crew1234", permission_role=role, status="active")
        if extra:
            t.put("/api/employees/%d" % emp["id"], json={"extra_permissions": extra})
        ok(t.post(url, json={"employee_id": emp["id"], "role": "STOREKEEPER"}))
        c = TestClient(main.app)
        c.__enter__()
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        logins[role] = c
    try:
        assert logins["stores"].post(url, json={"employee_id": colleague["id"], "role": "ASSISTANT"}).status_code == 403      # edits masters, cannot hand out a store
        assert ok(logins["store_incharge"].post(url, json={"employee_id": colleague["id"], "role": "ASSISTANT"}))["role"] == "ASSISTANT"
        assert logins["stores"].delete(url + "/%d" % colleague["id"]).status_code == 403
        assert logins["store_incharge"].delete(url + "/%d" % colleague["id"]).status_code == 200
    finally:
        for c in logins.values():
            c.__exit__(None, None, None)


def test_someone_who_leaves_is_taken_out_of_their_stores(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    url = "/api/store/masters/stores/%d/assignments" % central["id"]
    a = make_employee(t, email="a-%s@example.com" % tag, password="Crew1234", permission_role="stores", status="active")
    b = make_employee(t, email="b-%s@example.com" % tag, password="Crew1234", permission_role="stores", status="active")
    for e in (a, b):
        ok(t.post(url, json={"employee_id": e["id"], "role": "STOREKEEPER"}))
    assert ok(t.get("/api/store/masters/stores/%d" % central["id"]))["staff"] == 2

    ok(t.post("/api/employees/%d/offboard" % a["id"]))                          # still working out their notice: still in the store
    assert ok(t.get("/api/store/masters/stores/%d" % central["id"]))["staff"] == 2
    ok(t.post("/api/employees/%d/terminate" % a["id"]))                         # gone: out of the store
    ok(t.put("/api/employees/%d" % b["id"], json={"status": "inactive"}))       # switched off by an edit: out as well
    assert ok(t.get("/api/store/masters/stores/%d" % central["id"]))["staff"] == 0

    ok(t.put("/api/employees/%d" % b["id"], json={"status": "active"}))         # coming back does not put them back on its own
    assert ok(t.get("/api/store/masters/stores/%d" % central["id"]))["staff"] == 0
    assert ok(t.post(url, json={"employee_id": b["id"], "role": "STOREKEEPER"}))["is_active"] is True


def test_a_projects_material_cost_is_for_its_stores_manager_and_reports(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    site = ok(t.post("/api/store/masters/stores", json={"code": "SI" + tag[:3].upper(), "name": "Site", "type": "SITE", "project_id": w["job"]}))
    url = "/api/store/reports/project-cost/%d" % w["job"]
    logins, emps = {}, {}
    for key, role in (("keeper", "stores"), ("accounts", "accounts")):
        email = "%s-%s@example.com" % (key, tag)
        emps[key] = make_employee(t, email=email, password="Crew1234", permission_role=role, status="active")
        c = TestClient(main.app)
        c.__enter__()
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        logins[key] = c
    try:
        ok(t.post("/api/store/masters/stores/%d/assignments" % central["id"], json={"employee_id": emps["keeper"]["id"], "role": "STOREKEEPER"}))
        assert logins["keeper"].get(url).status_code == 403                    # a storekeeper elsewhere does not see this project's cost
        ok(t.post("/api/store/masters/stores/%d/assignments" % site["id"], json={"employee_id": emps["keeper"]["id"], "role": "STOREKEEPER"}))
        assert logins["keeper"].get(url).status_code == 200                    # working in the project's own store, they do
        assert logins["accounts"].get(url).status_code == 200                  # the company's reports, whatever store
    finally:
        for c in logins.values():
            c.__exit__(None, None, None)


def test_the_store_administrator_right_is_the_masters_to_give_and_says_what_it_opens(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    from app.core.permissions import PORTAL_PERMISSIONS
    admin = next(p for p in PORTAL_PERMISSIONS if p["key"] == "store.admin")
    assert "every store" in admin["warning"]
    for role in ROLE_PERMISSIONS:                                          # no access level carries it but the Master's
        assert ("store.admin" in ROLE_PERMISSIONS[role]) == (role == "owner"), role
    # A member of staff - even one who manages people - cannot hand it to anyone.
    email = "hr-%s@example.com" % tag
    make_employee(t, email=email, password="Crew1234", permission_role="hr_admin", status="active")
    target = make_employee(t, email="tg-%s@example.com" % tag, password="Crew1234", permission_role="stores", status="active")
    c = TestClient(main.app)
    c.__enter__()
    try:
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        res = c.put("/api/employees/%d" % target["id"], json={"extra_permissions": "store.admin"})
        assert res.status_code in (401, 403)
    finally:
        c.__exit__(None, None, None)
