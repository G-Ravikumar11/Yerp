"""Project chat: threads on a project, the office and the site in one
conversation, photos beside the words, @names on the bell, and each
person's unread count their own."""
from conftest import make_employee

PASSWORD = "Crew1234"


def job(tenant, name="Vanya City STP"):
    return tenant.post("/api/jobs", json={"name": name, "customer_name": "Arabtec"}).json()


def site_engineer(tenant, browser, first="Ravi", last="Kumar"):
    """A member of site staff, signed in on their own phone."""
    e = make_employee(tenant, first_name=first, last_name=last, permission_role="supervisor", password=PASSWORD)
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    res = browser.post("/api/employee/auth/login", json={"email": e["email"], "password": PASSWORD})
    assert res.status_code == 200, res.text
    return e


def start(tenant, j, title="Raft pour, grid A-C", body="Pour moved to Thursday 6am."):
    res = tenant.post("/api/chat/threads", json={"job_id": j["id"], "title": title, "body": body})
    assert res.status_code == 200, res.text
    return res.json()["thread"]


def test_a_thread_is_started_on_a_project_and_replied_to_from_site(tenant, portal):
    j = job(tenant)
    t = start(tenant, j)
    assert t["title"] == "Raft pour, grid A-C" and t["messages"] == 1 and t["unread"] == 0
    site_engineer(tenant, portal)
    # The site sees it unread, reads it, answers.
    mine = portal.get("/api/chat/threads", params={"job_id": j["id"]}).json()
    assert mine["threads"][0]["unread"] == 1 and mine["unread"] == 1
    got = portal.get("/api/chat/threads/%d" % t["id"]).json()
    assert got["messages"][0]["body"] == "Pour moved to Thursday 6am." and not got["messages"][0]["mine"]
    assert portal.get("/api/chat/unread").json()["unread"] == 0
    reply = portal.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "Pump booked for 5:30."})
    assert reply.status_code == 200 and reply.json()["message"]["author_name"] == "Ravi Kumar"
    # And the office has one unread - not its own message.
    assert tenant.get("/api/chat/unread").json()["unread"] == 1
    newer = tenant.get("/api/chat/threads/%d" % t["id"], params={"after": got["messages"][0]["id"]}).json()
    assert [m["body"] for m in newer["messages"]] == ["Pump booked for 5:30."]
    assert tenant.get("/api/chat/unread").json()["unread"] == 0


def test_naming_somebody_rings_the_bell(tenant, portal):
    j = job(tenant)
    site_engineer(tenant, portal, "Suresh", "Babu")
    t = start(tenant, j, body="@Suresh Babu please check the cover blocks before 4pm")
    alerts = [a for a in tenant.get("/api/alerts").json()["alerts"] if a["kind"] == "chat_mention"]
    assert alerts and "Suresh Babu" in alerts[0]["title"]
    msg = tenant.get("/api/chat/threads/%d" % t["id"]).json()["messages"][0]
    assert len(msg["mentions"]) == 1 and msg["mentions"][0].startswith("employee:")


def test_the_longest_name_wins_a_mention(tenant, portal):
    import main
    people = [{"key": "a", "name": "Ravi"}, {"key": "b", "name": "Ravi Kumar"}]
    assert [p["key"] for p in main.find_mentions("thanks @Ravi Kumar", people)] == ["b"]
    assert [p["key"] for p in main.find_mentions("@ravi and @Ravi Kumar", people)] == ["b", "a"]
    assert main.find_mentions("email ravi@x.com", people) == []


def test_a_photo_goes_in_beside_the_words(tenant, portal):
    j = job(tenant)
    t = start(tenant, j)
    site_engineer(tenant, portal)
    up = portal.post("/api/chat/threads/%d/files" % t["id"],
                     files={"file": ("crack.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg")})
    assert up.status_code == 200, up.text
    fid = up.json()["file"]["id"]
    m = portal.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "", "file_ids": [fid]}).json()["message"]
    assert m["files"][0]["is_image"] and m["files"][0]["name"] == "crack.jpg"
    assert tenant.get("/api/chat/threads", params={"job_id": j["id"]}).json()["threads"][0]["last"]["body"] == "a photo"


def test_a_file_from_elsewhere_cannot_be_slipped_in(tenant):
    j = job(tenant)
    t = start(tenant, j)
    other = start(tenant, j, title="Another")
    fid = tenant.post("/api/chat/threads/%d/files" % other["id"],
                      files={"file": ("x.pdf", b"%PDF", "application/pdf")}).json()["file"]["id"]
    res = tenant.post("/api/chat/threads/%d/messages" % t["id"], json={"file_ids": [fid]})
    assert res.status_code == 400


def test_an_empty_message_or_subject_is_refused(tenant):
    j = job(tenant)
    assert tenant.post("/api/chat/threads", json={"job_id": j["id"], "title": " "}).status_code == 400
    t = start(tenant, j)
    assert tenant.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "  "}).status_code == 400


def test_only_the_writer_takes_a_message_back(tenant, portal):
    j = job(tenant)
    t = start(tenant, j)
    site_engineer(tenant, portal)
    first = tenant.get("/api/chat/threads/%d" % t["id"]).json()["messages"][0]
    assert portal.delete("/api/chat/messages/%d" % first["id"]).status_code == 403
    gone = tenant.delete("/api/chat/messages/%d" % first["id"]).json()["message"]
    assert gone["deleted"] and gone["body"] == ""


def test_a_closed_thread_takes_no_more_until_reopened(tenant):
    j = job(tenant)
    t = start(tenant, j)
    tenant.post("/api/chat/threads/%d/close" % t["id"])
    assert tenant.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "one more"}).status_code == 409
    assert tenant.post("/api/chat/threads/%d/files" % t["id"],
                       files={"file": ("x.pdf", b"%PDF", "application/pdf")}).status_code == 409
    tenant.post("/api/chat/threads/%d/reopen" % t["id"])
    assert tenant.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "one more"}).status_code == 200


def test_threads_list_across_projects(tenant):
    a, b = job(tenant, "Site A"), job(tenant, "Site B")
    start(tenant, a, title="A1")
    start(tenant, b, title="B1")
    everything = tenant.get("/api/chat/threads").json()["threads"]
    assert {t["title"] for t in everything} == {"A1", "B1"}
    assert [t["title"] for t in tenant.get("/api/chat/threads", params={"job_id": a["id"]}).json()["threads"]] == ["A1"]


def test_another_company_sees_none_of_it(tenant, second_tenant):
    j = job(tenant)
    t = start(tenant, j)
    assert second_tenant.get("/api/chat/threads/%d" % t["id"]).status_code == 404
    assert second_tenant.post("/api/chat/threads/%d/messages" % t["id"], json={"body": "hi"}).status_code == 404
    assert second_tenant.get("/api/chat/threads").json()["threads"] == []
    assert second_tenant.post("/api/chat/threads", json={"job_id": j["id"], "title": "x"}).status_code == 404
