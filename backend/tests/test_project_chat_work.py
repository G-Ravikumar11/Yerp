"""Project chat as a working tool: categories and priority, replies, edits, reactions, tasks made from messages,
a notice for each person, search and filters, the trail, and who may see which project."""
import io
from datetime import date, timedelta

from conftest import make_employee
from test_project_chat import PASSWORD, job, site_engineer


def day(n):
    return (date.today() + timedelta(days=n)).isoformat()


def thread(tenant, j, **kw):
    body = {"job_id": j["id"], "title": "Slab cube results", "body": "28-day results are in."}
    body.update(kw)
    res = tenant.post("/api/chat/threads", json=body)
    assert res.status_code == 200, res.text
    return res.json()["thread"]


def test_a_thread_carries_category_priority_people_and_a_link(tenant, portal):
    j = job(tenant)
    e = site_engineer(tenant, portal)
    ins = tenant.post("/api/qc/inspections", json={"job_id": j["id"], "checklist": "Plastering"}).json()["inspection"]
    t = thread(tenant, j, description="Cube set CT-1 is low", category="Quality", priority="Urgent",
               members=["employee:%d" % e["id"]], link_type="quality", link_ref=ins["number"])
    assert (t["category"], t["priority"], t["description"]) == ("Quality", "Urgent", "Cube set CT-1 is low")
    assert t["members"][0]["name"] == "Ravi Kumar" and t["link"]["ref"] == ins["number"] and t["link"]["id"] == ins["id"]
    for bad in ({"category": "Gossip"}, {"priority": "Whenever"}, {"members": ["employee:99999"]}, {"link_type": "weather"},
                {"link_type": "quality", "link_ref": "NCR-9999"}):
        res = tenant.post("/api/chat/threads", json={"job_id": j["id"], "title": "x", **bad})
        if "members" in bad:
            assert res.status_code == 200          # an unknown person is dropped, never stored
            assert res.json()["thread"]["members"] == []
        else:
            assert res.status_code == 400, bad
    assert tenant.post("/api/chat/threads", json={"job_id": j["id"], "title": "  "}).status_code == 400
    edited = tenant.put("/api/chat/threads/%d" % t["id"], json={"priority": "Low", "category": "Safety"}).json()["thread"]
    assert edited["priority"] == "Low" and edited["category"] == "Safety"


def test_replies_edits_and_reactions(tenant, portal):
    j = job(tenant)
    site_engineer(tenant, portal)
    t = thread(tenant, j)
    first = tenant.get("/api/chat/threads/%d" % t["id"]).json()["messages"][0]
    r = portal.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "Checking now", "parent_id": first["id"]}).json()["message"]
    assert r["parent"]["id"] == first["id"] and r["parent"]["body"].startswith("28-day")
    assert portal.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "x", "parent_id": 99999}).status_code == 400
    assert tenant.put("/api/chat/messages/%d" % r["id"], json={"body": "hijack"}).status_code == 403
    ed = portal.put("/api/chat/messages/%d" % r["id"], json={"body": "Checking the lab report"}).json()["message"]
    assert ed["edited"] and ed["body"] == "Checking the lab report"
    assert portal.put("/api/chat/messages/%d" % r["id"], json={"body": " "}).status_code == 400
    on = tenant.post("/api/chat/messages/%d/reactions" % r["id"], json={"emoji": "👍"}).json()["message"]
    assert on["reactions"][0]["count"] == 1 and on["reactions"][0]["mine"]
    assert tenant.post("/api/chat/messages/%d/reactions" % r["id"], json={"emoji": "👍"}).json()["message"]["reactions"] == []
    assert tenant.post("/api/chat/messages/%d/reactions" % r["id"], json={"emoji": "<script>"}).status_code == 400


def test_a_message_becomes_a_task_that_moves_through_its_statuses(tenant, portal):
    j = job(tenant)
    e = site_engineer(tenant, portal)
    t = thread(tenant, j, members=["employee:%d" % e["id"]])
    msg = tenant.get("/api/chat/threads/%d" % t["id"]).json()["messages"][0]
    path = "/api/chat/threads/%d/tasks" % t["id"]
    who = "employee:%d" % e["id"]
    assert tenant.post(path, json={"message_id": msg["id"], "assignee": who, "due_date": day(-1)}).status_code == 400
    assert tenant.post(path, json={"message_id": msg["id"], "assignee": "employee:99999"}).status_code == 400
    assert tenant.post(path, json={"message_id": msg["id"], "priority": "Meh"}).status_code == 400
    task = tenant.post(path, json={"message_id": msg["id"], "assignee": who, "due_date": day(3), "priority": "High"}).json()["task"]
    assert task["title"].startswith("28-day") and task["status"] == "Open" and task["assignee_name"] == "Ravi Kumar"
    assert any(n["kind"] == "assigned" for n in portal.get("/api/chat/notices").json()["notices"])
    p = "/api/chat/tasks/%d" % task["id"]
    for status in ("In Progress", "Blocked", "Resolved"):
        assert portal.put(p, json={"status": status}).json()["task"]["status"] == status
    assert portal.put(p, json={"status": "Closed"}).status_code == 403
    assert portal.put(p, json={"title": "something else"}).status_code == 403
    assert tenant.put(p, json={"status": "Nonsense"}).status_code == 400
    assert tenant.put(p, json={"status": "Closed"}).json()["task"]["status"] == "Closed"
    assert tenant.get("/api/chat/tasks", params={"status": "Closed"}).json()["tasks"][0]["id"] == task["id"]
    assert portal.get("/api/chat/tasks", params={"mine": True}).json()["tasks"][0]["id"] == task["id"]
    detail = tenant.get("/api/chat/threads/%d" % t["id"]).json()
    assert detail["tasks"][0]["id"] == task["id"]
    assert [h["action"] for h in detail["history"]].count("chat.task.updated") == 4


def test_each_person_gets_their_own_notices_and_a_deadline_reminder(tenant, portal):
    j = job(tenant)
    e = site_engineer(tenant, portal)
    t = thread(tenant, j, members=["employee:%d" % e["id"]])
    assert tenant.get("/api/chat/notices").json()["unread"] == 0
    mine = portal.get("/api/chat/notices").json()
    kinds = {n["kind"] for n in mine["notices"]}
    assert mine["unread"] >= 1 and "update" in kinds and mine["notices"][0]["thread_id"] == t["id"]
    tenant.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "@Ravi Kumar look at this"})
    assert "mention" in {n["kind"] for n in portal.get("/api/chat/notices").json()["notices"]}
    first = tenant.get("/api/chat/threads/%d" % t["id"]).json()["messages"][0]
    portal.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "On it", "parent_id": first["id"]})
    assert any(n["kind"] == "reply" for n in tenant.get("/api/chat/notices").json()["notices"])
    tenant.post("/api/chat/threads/%d/tasks" % t["id"], json={"title": "Send the lab report", "assignee": "employee:%d" % e["id"], "due_date": day(1)})
    portal.get("/api/chat/notices")
    due = [n for n in portal.get("/api/chat/notices").json()["notices"] if n["kind"] == "due"]
    assert len(due) == 1 and "Send the lab report" in due[0]["title"]
    n = portal.get("/api/chat/notices").json()
    assert n["unread"] >= 3 and portal.get("/api/chat/unread").json()["notices"] == n["unread"]
    assert portal.post("/api/chat/notices/read", json={"ids": [n["notices"][0]["id"]]}).json()["unread"] == n["unread"] - 1
    assert portal.post("/api/chat/notices/read", json={}).json()["unread"] == 0
    assert tenant.get("/api/chat/notices").json()["unread"] >= 1


def test_search_and_filters(tenant):
    a, b = job(tenant), job(tenant, "Second site")
    thread(tenant, a, title="Raft pour", body="Pump booked", category="Site Progress", priority="High")
    t2 = thread(tenant, b, title="Cement delivery", body="Late truck", category="Materials")
    tenant.post("/api/chat/threads/%d/close" % t2["id"])

    def ids(**q):
        return [x["title"] for x in tenant.get("/api/chat/threads", params=q).json()["threads"]]

    assert sorted(ids()) == ["Cement delivery", "Raft pour"]
    assert ids(job_id=a["id"]) == ["Raft pour"]
    assert ids(q="pump") == ["Raft pour"]
    assert ids(q="cement") == ["Cement delivery"]
    assert ids(category="Materials") == ["Cement delivery"] and ids(priority="High") == ["Raft pour"]
    assert ids(status="closed") == ["Cement delivery"] and ids(status="open") == ["Raft pour"]
    assert ids(date_from=day(1)) == [] and len(ids(date_to=day(1))) == 2
    assert ids(unread=True) == []


def test_attachments_are_listed_and_uploads_are_checked(tenant):
    j = job(tenant)
    t = thread(tenant, j)
    url = "/api/chat/threads/%d/files" % t["id"]
    ok = tenant.post(url, files={"file": ("crack.jpg", io.BytesIO(b"\xff\xd8\xff" + b"0" * 300), "image/jpeg")}, data={"caption": "Crack at C4"})
    assert ok.status_code == 200, ok.text
    assert tenant.post(url, files={"file": ("spec.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")}).status_code == 200
    bad = tenant.post(url, files={"file": ("run.exe", io.BytesIO(b"MZ" + b"0" * 50), "application/x-msdownload")})
    assert bad.status_code in (400, 415, 422)
    files = tenant.get("/api/chat/threads/%d" % t["id"]).json()["files"]
    assert {f["name"] for f in files} == {"crack.jpg", "spec.pdf"} and any(f["caption"] == "Crack at C4" for f in files)
    other = thread(tenant, j, title="Another")
    fid = files[0]["id"]
    assert tenant.post("/api/chat/threads/%d/messages" % other["id"], json={"body": "x", "file_ids": [fid]}).status_code == 400
    assert tenant.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "see", "file_ids": [fid]}).json()["message"]["files"][0]["name"]


def test_staff_see_only_the_projects_they_are_on(tenant, portal):
    from app import db as database, models
    a, b = job(tenant), job(tenant, "Not yours")
    ta, tb = thread(tenant, a, title="Mine"), thread(tenant, b, title="Not mine")
    e = make_employee(tenant, first_name="Site", last_name="Hand", permission_role="staff", password=PASSWORD)
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    s = database.SessionLocal()
    try:
        emp = s.query(models.DBEmployee).filter(models.DBEmployee.id == e["id"]).first()
        s.add(models.DBEmployeeSite(client_id=emp.client_id, employee_id=emp.id, job_id=a["id"]))
        s.commit()
    finally:
        s.close()
    assert portal.post("/api/employee/auth/login", json={"email": e["email"], "password": PASSWORD}).status_code == 200
    assert [x["title"] for x in portal.get("/api/chat/threads").json()["threads"]] == ["Mine"]
    assert portal.get("/api/chat/threads/%d" % ta["id"]).status_code == 200
    assert portal.get("/api/chat/threads/%d" % tb["id"]).status_code == 403
    assert portal.get("/api/chat/threads", params={"job_id": b["id"]}).status_code == 403
    assert portal.post("/api/chat/threads/%d/messages" % tb["id"], json={"body": "hi"}).status_code == 403
    assert portal.post("/api/chat/threads", json={"job_id": b["id"], "title": "sneak"}).status_code == 403
    assert portal.post("/api/chat/threads/%d/tasks" % tb["id"], json={"title": "x"}).status_code == 403
    assert portal.put("/api/chat/threads/%d" % ta["id"], json={"priority": "Low"}).status_code == 403
    assert tenant.put("/api/chat/threads/%d" % ta["id"], json={"priority": "Low"}).status_code == 200


def test_the_trail_records_decisions_and_another_company_sees_nothing(tenant, second_tenant):
    j = job(tenant)
    t = thread(tenant, j)
    tenant.put("/api/chat/threads/%d" % t["id"], json={"priority": "Urgent"})
    tenant.post("/api/chat/threads/%d/close" % t["id"])
    tenant.post("/api/chat/threads/%d/reopen" % t["id"])
    h = tenant.get("/api/chat/threads/%d" % t["id"]).json()["history"]
    assert [x["action"] for x in h][::-1] == ["chat.thread.started", "chat.thread.updated", "chat.thread.closed", "chat.thread.reopened"]
    assert all(x["who"] for x in h)
    assert second_tenant.get("/api/chat/threads/%d" % t["id"]).status_code == 404
    assert second_tenant.get("/api/chat/threads").json()["threads"] == []
    assert second_tenant.post("/api/chat/threads/%d/tasks" % t["id"], json={"title": "x"}).status_code == 404
    assert second_tenant.get("/api/chat/tasks").json()["tasks"] == []
