"""The tool register: tools by serial number are registered, given out, taken back with their condition, serviced, lost or retired, each step
kept in a history; and reminders go out once a week for what is overdue."""
import uuid
from datetime import date, timedelta

from app import db as database, models
from app.models.store_extras import DBStoreTool
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()


def _tool_item(t, w, category="TOOL"):
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": category, "base_uom": "kg"}))


def _alerts(client_id):
    with database.SessionLocal() as s:
        return s.query(models.DBAlert).filter(models.DBAlert.client_id == client_id, models.DBAlert.kind == "store_overdue").count()


def test_a_tool_goes_out_and_comes_back_with_its_history(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    body = {"item_id": w["item"], "store_id": central["id"], "serial_no": "DRL-001"}
    assert t.post("/api/store/tools", json=body).status_code == 400                      # a consumable is not kept in the register
    _tool_item(t, w)
    tool = ok(t.post("/api/store/tools", json=body))
    assert tool["status"] == "AVAILABLE" and tool["condition"] == "GOOD" and tool["events"][0]["event"] == "REGISTERED"
    assert t.post("/api/store/tools", json=dict(body, serial_no="drl-001")).status_code == 409
    url = "/api/store/tools/%d/" % tool["id"]

    assert t.post(url + "receive", json={}).status_code == 409                          # not out
    assert t.post(url + "assign", json={}).status_code == 400                           # who is taking it
    assert t.post(url + "assign", json={"holder_name": "Suresh", "due_back": "2020-01-01"}).status_code == 400
    out = ok(t.post(url + "assign", json={"holder_name": "Suresh", "project_id": w["job"], "due_back": (date.today() + timedelta(days=5)).isoformat()}))
    assert out["status"] == "ISSUED" and out["holder_name"] == "Suresh" and out["overdue_days"] == 0
    assert t.post(url + "assign", json={"holder_name": "Ramu"}).status_code == 409      # already out

    assert t.post(url + "receive", json={"condition": "DAMAGED"}).status_code == 400    # say what is wrong
    back = ok(t.post(url + "receive", json={"condition": "DAMAGED", "note": "Chuck is cracked"}))
    assert back["status"] == "IN_SERVICE" and back["condition"] == "DAMAGED" and back["holder_name"] == ""
    assert t.post(url + "assign", json={"holder_name": "Ramu"}).status_code == 409      # not while it is being repaired
    fixed = ok(t.post(url + "service-done", json={"next_service": (date.today() + timedelta(days=90)).isoformat(), "note": "New chuck"}))
    assert fixed["status"] == "AVAILABLE" and fixed["condition"] == "GOOD" and fixed["last_service"] == TODAY
    assert [e["event"] for e in ok(t.get("/api/store/tools/%d" % tool["id"]))["events"]] == ["SERVICE_DONE", "RETURNED", "ISSUED", "REGISTERED"]

    assert t.post(url + "lose", json={}).status_code == 400
    assert ok(t.post(url + "lose", json={"note": "Not found at stock-take"}))["status"] == "LOST"
    assert t.post(url + "lose", json={"note": "again"}).status_code == 409
    assert ok(t.post(url + "retire", json={}))["status"] == "RETIRED"
    assert [x["serial_no"] for x in ok(t.get("/api/store/tools", params={"status": "RETIRED"}))["items"]] == ["DRL-001"]
    assert ok(t.get("/api/store/tools", params={"q": "nobody"}))["items"] == []


def test_overdue_tools_and_service_are_reminded_once_a_week(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _tool_item(t, w)
    a = ok(t.post("/api/store/tools", json={"item_id": w["item"], "store_id": central["id"], "serial_no": "A1", "next_service": (date.today() + timedelta(days=3)).isoformat()}))
    b = ok(t.post("/api/store/tools", json={"item_id": w["item"], "store_id": central["id"], "serial_no": "B1"}))
    ok(t.post("/api/store/tools/%d/assign" % b["id"], json={"holder_name": "Suresh", "due_back": (date.today() + timedelta(days=1)).isoformat()}))
    with database.SessionLocal() as s:
        s.get(DBStoreTool, b["id"]).due_back = date.today() - timedelta(days=2)
        s.commit()
    assert ok(t.get("/api/store/tools/%d" % b["id"]))["overdue_days"] == 2 and ok(t.get("/api/store/tools/%d" % a["id"]))["service_due"] is True
    assert ok(t.post("/api/store/tools/remind"))["mentioned"] == 2                      # B1 overdue, A1 due for service
    assert _alerts(w["client_id"]) == 1
    assert ok(t.post("/api/store/tools/remind"))["mentioned"] == 0                      # not again the same week
    assert _alerts(w["client_id"]) == 1


def test_overdue_returnable_material_is_reminded(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _tool_item(t, w, "RETURNABLE")
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "lines": [{"po_line_id": po_line, "qty": "10", "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    ten_days_ago, five_days_ago = (date.today() - timedelta(days=10)).isoformat(), (date.today() - timedelta(days=5)).isoformat()
    doc = ok(t.post("/api/store/outward/issue", json={"store_id": central["id"], "issue_date": ten_days_ago, "project_id": w["job"], "received_by_type": "FOREMAN", "received_by_name": "Suresh",
                                                       "lines": [{"item_id": w["item"], "qty": "2", "uom": "bag", "cost_head": "OVERHEAD", "expected_return_date": five_days_ago}]}))
    walk(t, "outward", "issue", doc["id"], "submit", "approve", "post")
    assert ok(t.post("/api/store/tools/remind"))["mentioned"] == 1
    assert ok(t.post("/api/store/tools/remind"))["mentioned"] == 0


def test_a_storekeeper_does_not_write_off_a_tool(account):
    from fastapi.testclient import TestClient
    import main
    from conftest import make_employee
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _tool_item(t, w)
    tool = ok(t.post("/api/store/tools", json={"item_id": w["item"], "store_id": central["id"], "serial_no": "WO-1"}))
    people = {}
    for role in ("stores", "store_incharge"):
        email = "%s-%s@example.com" % (role, tag)
        emp = make_employee(t, email=email, password="Crew1234", permission_role=role, status="active")
        ok(t.post("/api/store/masters/stores/%d/assignments" % central["id"], json={"employee_id": emp["id"], "role": "STOREKEEPER"}))
        c = TestClient(main.app)
        c.__enter__()
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        people[role] = c
    try:
        url = "/api/store/tools/%d/" % tool["id"]
        assert ok(people["stores"].post(url + "assign", json={"holder_name": "Suresh"}))["status"] == "ISSUED"      # the keeper gives it out
        assert people["stores"].post(url + "lose", json={"note": "Not found"}).status_code == 403                     # but does not write it off
        assert ok(people["store_incharge"].post(url + "lose", json={"note": "Not found at stock-take"}))["status"] == "LOST"
        assert people["stores"].post(url + "retire", json={}).status_code == 403
    finally:
        for c in people.values():
            c.__exit__(None, None, None)
