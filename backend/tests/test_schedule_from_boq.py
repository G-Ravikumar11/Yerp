"""Planning & Progress drawn from the project's BOQ: what the client's sheet lists, put on the programme."""
from datetime import date, timedelta

from test_boq import make_boq, saved


def d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def draw(tenant, job_id, by="section", start=None, finish=None):
    return tenant.post("/api/jobs/%d/schedule/from-boq" % job_id, json={"start": start or d(0), "finish": finish or d(60), "by": by})


def activities(tenant, job_id):
    return tenant.get("/api/jobs/%d/schedule" % job_id).json()["activities"]


def test_by_section_each_section_is_an_activity_with_its_lines_as_tasks(tenant):
    jid, boq = make_boq(tenant)
    saved(tenant, boq)
    res = draw(tenant, jid)
    assert res.status_code == 200, res.text
    assert "2 activities with 4 tasks" in res.json()["message"]
    acts = activities(tenant, jid)
    assert [a["name"] for a in acts] == ["SUBSTRUCTURE", "SUPERSTRUCTURE"]
    # weighted by what each is worth, and spread end to end across the span
    assert acts[0]["weight"] == 90000 + 984000 + 32800 and acts[1]["weight"] == 366000
    # the programme does not start on a Sunday
    assert acts[0]["planned_start"] == (d(1) if date.today().weekday() == 6 else d(0)) and acts[1]["planned_finish"] == (d(59) if (date.today() + timedelta(days=60)).weekday() == 6 else d(60))
    assert acts[1]["depends_on_id"] == acts[0]["id"]
    tasks = tenant.get("/api/schedule/activities/%d" % acts[0]["id"]).json()["activity"]["tasks"]
    texts = [t["text"] for t in tasks]
    assert len(texts) == 3 and any("Excavation in all types of soil" in x for x in texts)
    assert all(" - " in x for x in texts), "each task carries the line's item code"


def test_ticking_the_tasks_moves_the_section(tenant):
    jid, boq = make_boq(tenant)
    saved(tenant, boq)
    draw(tenant, jid)
    act = activities(tenant, jid)[0]
    tasks = tenant.get("/api/schedule/activities/%d" % act["id"]).json()["activity"]["tasks"]
    tenant.put("/api/schedule/tasks/%d" % tasks[0]["id"], json={"done": True})
    tenant.put("/api/schedule/tasks/%d" % tasks[1]["id"], json={"percent": 50})
    assert tenant.get("/api/schedule/activities/%d" % act["id"]).json()["activity"]["actual_percent"] == 50


def test_by_item_each_priced_line_is_an_activity(tenant):
    jid, boq = make_boq(tenant)
    saved(tenant, boq)
    res = draw(tenant, jid, by="item")
    assert res.status_code == 200 and "4 activities" in res.json()["message"]
    names = [a["name"] for a in activities(tenant, jid)]
    assert names == ["Excavation in all types of soil", "M25 grade RCC in raft", "Shuttering to raft edges", "Brick masonry in CM 1:6"]


def test_drawing_again_adds_only_what_is_new(tenant):
    jid, boq = make_boq(tenant)
    lines = saved(tenant, boq)["lines"]
    assert draw(tenant, jid).status_code == 200
    again = draw(tenant, jid)
    assert again.status_code == 409 and "already on the programme" in again.json()["detail"]
    # a new section added to the BOQ is drawn on its own
    lines.append({"kind": "section", "description": "FINISHES"})
    lines.append({"kind": "item", "description": "Painting", "uom": "sqm", "quantity": 100, "rate": 50})
    assert tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines, "issue_codes": True}).status_code == 200
    more = draw(tenant, jid)
    assert more.status_code == 200 and "1 activity with 1 task" in more.json()["message"]
    assert [a["name"] for a in activities(tenant, jid)] == ["SUBSTRUCTURE", "SUPERSTRUCTURE", "FINISHES"]


def test_an_item_takes_its_progress_from_the_book_when_a_client_order_was_made_from_the_boq(tenant):
    jid, boq = make_boq(tenant)
    saved(tenant, boq)
    assert tenant.post("/api/boqs/%d/client-order" % boq["id"], json={}).status_code == 200
    draw(tenant, jid, by="item")
    acts = activities(tenant, jid)
    assert all(a["work_order_line_id"] for a in acts) and all(a["progress_from"] == "measurement book" for a in acts)


def test_drawing_needs_a_boq_and_a_real_span(tenant):
    job = tenant.post("/api/jobs", json={"name": "No BOQ site", "customer_name": "X"}).json()
    res = draw(tenant, job["id"])
    assert res.status_code == 409 and "no BOQ" in res.json()["detail"]
    jid, boq = make_boq(tenant, "Second site")
    saved(tenant, boq)
    assert draw(tenant, jid, start=d(10), finish=d(5)).status_code == 400
    assert draw(tenant, jid, by="everything").status_code == 400


def test_one_company_cannot_draw_from_anothers_project(tenant, second_tenant):
    jid, boq = make_boq(second_tenant, "Rival site")
    saved(second_tenant, boq)
    assert draw(tenant, jid).status_code == 404
    assert activities(second_tenant, jid) == []
