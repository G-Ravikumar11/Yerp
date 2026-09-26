"""Safety: incidents with their cause and fix, toolbox talks, and permits to
work issued only on their precautions and closed when the work stops."""
from datetime import date, datetime, timedelta

import main


def job(tenant):
    return tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()


def test_a_near_miss_is_logged_and_announced(tenant):
    j = job(tenant)
    res = tenant.post("/api/safety/incidents", json={"job_id": j["id"], "kind": "Near miss",
                                                     "description": "Plank fell from level 3, nobody below",
                                                     "location": "Tower A"})
    assert res.status_code == 200, res.text
    i = res.json()["incident"]
    assert i["number"] == "INC-0001" and i["status"] == "OPEN" and not i["serious"]
    assert any(a["kind"] == "safety_incident" for a in tenant.get("/api/alerts").json()["alerts"])


def test_an_injury_needs_a_name_and_closes_only_with_cause_and_fix(tenant):
    j = job(tenant)
    assert tenant.post("/api/safety/incidents", json={"job_id": j["id"], "kind": "Lost time injury",
                                                      "description": "Fell from ladder"}).status_code == 400
    i = tenant.post("/api/safety/incidents", json={
        "job_id": j["id"], "kind": "Lost time injury", "description": "Fell from ladder",
        "injured_name": "Ramaiah K", "injury": "Fractured wrist", "lost_days": 21,
        "happened_on": (date.today() - timedelta(days=10)).isoformat()}).json()["incident"]
    assert i["serious"]
    kinds = {x["kind"] for x in tenant.get("/api/attention").json()["items"]}
    assert "incidents_open" in kinds
    assert tenant.post("/api/safety/incidents/%d/close" % i["id"], json={}).status_code == 400
    out = tenant.post("/api/safety/incidents/%d/close" % i["id"], json={
        "root_cause": "Ladder not footed", "corrective_action": "Ladders tied at top; toolbox talk held"}).json()
    assert out["incident"]["status"] == "CLOSED"
    s = tenant.get("/api/safety?job_id=%d" % j["id"]).json()["summary"]
    assert s["days_without_lti"] == 10


def test_a_toolbox_talk_counts_who_stood_through_it(tenant):
    j = job(tenant)
    assert tenant.post("/api/safety/talks", json={"job_id": j["id"], "topic": "Working at height"}).status_code == 400
    tenant.post("/api/safety/talks", json={"job_id": j["id"], "topic": "Working at height",
                                           "attendee_names": "Ramaiah, Suresh, Anil"})
    s = tenant.get("/api/safety").json()
    assert s["talks"][0]["attendees"] == 3 and s["summary"]["talks_this_week"] == 1


def permit_body(j, **over):
    now = datetime.now()
    body = {"job_id": j["id"], "kind": "Hot work", "location": "STP tank roof", "receiver": "Welder Babu",
            "valid_from": now.strftime("%Y-%m-%d %H:%M"),
            "valid_to": (now + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
            "precautions": [{"item": x, "done": True} for x in main.PERMIT_PRECAUTIONS["Hot work"]]}
    body.update(over)
    return body


def test_a_permit_is_issued_only_on_its_precautions(tenant):
    j = job(tenant)
    short = permit_body(j, precautions=[{"item": "Fire extinguisher at hand", "done": True}])
    res = tenant.post("/api/safety/permits", json=short)
    assert res.status_code == 409 and "Combustibles" in res.json()["detail"]
    p = tenant.post("/api/safety/permits", json=permit_body(j)).json()["permit"]
    assert p["number"] == "PTW-0001" and p["status"] == "ACTIVE" and not p["expired"]


def test_a_permit_is_for_one_shift(tenant):
    j = job(tenant)
    now = datetime.now()
    res = tenant.post("/api/safety/permits", json=permit_body(j, valid_to=(now + timedelta(hours=20)).strftime("%Y-%m-%d %H:%M")))
    assert res.status_code == 400


def test_a_permit_run_out_and_still_open_is_flagged_until_closed(tenant):
    j = job(tenant)
    then = datetime.now() - timedelta(hours=10)
    p = tenant.post("/api/safety/permits", json=permit_body(
        j, valid_from=then.strftime("%Y-%m-%d %H:%M"),
        valid_to=(then + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"))).json()["permit"]
    assert p["expired"]
    assert "permits_expired" in {x["kind"] for x in tenant.get("/api/attention").json()["items"]}
    closed = tenant.post("/api/safety/permits/%d/close" % p["id"], json={"note": "Work done, area cleared"}).json()["permit"]
    assert closed["status"] == "CLOSED"
    assert "permits_expired" not in {x["kind"] for x in tenant.get("/api/attention").json()["items"]}


def test_another_company_sees_none_of_it(tenant, second_tenant):
    j = job(tenant)
    tenant.post("/api/safety/incidents", json={"job_id": j["id"], "kind": "Near miss", "description": "x"})
    assert second_tenant.get("/api/safety").json()["incidents"] == []
