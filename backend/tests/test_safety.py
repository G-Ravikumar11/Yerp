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


def test_a_worker_is_screened_with_trade_photo_and_medical_certificate(tenant):
    j = job(tenant)
    trades = tenant.get("/api/workers").json()["trades"]
    assert "Carpenter helper" in trades and "Unskilled NMR labour" in trades
    assert tenant.post("/api/workers", json={"job_id": j["id"], "name": "Ravi", "age": 16,
                                             "trade": "Mason"}).status_code == 400          # under 18
    assert tenant.post("/api/workers", json={"job_id": j["id"], "name": "Ravi", "age": 30,
                                             "trade": "Plumber"}).status_code == 400        # not a trade on the list
    res = tenant.post("/api/workers", json={"job_id": j["id"], "name": "Ravi Kumar", "age": 30,
                                            "address": "Kukatpally, Hyderabad", "trade": "Mason helper"})
    assert res.status_code == 200, res.text
    w = res.json()["worker"]
    assert w["number"] == "WKR-0001" and w["trade"] == "Mason helper" and w["screened_on"]
    up = tenant.post("/api/files", data={"attached_type": "worker", "attached_id": str(w["id"]),
                                         "caption": "Medical certificate", "kind": "document"},
                     files={"file": ("fit.pdf", b"%PDF-1.4 fit to work", "application/pdf")})
    assert up.status_code == 200, up.text
    listed = tenant.get("/api/workers?job_id=%d" % j["id"]).json()
    assert listed["summary"]["workers"] == 1 and listed["summary"]["by_trade"]["Mason helper"] == 1
    assert listed["workers"][0]["medical"][0]["name"] == "fit.pdf" and listed["summary"]["without_medical"] == 0
    assert tenant.delete("/api/workers/%d" % w["id"]).status_code == 200
    assert tenant.get("/api/workers").json()["workers"] == []


# --- the full "Screening Of Worker" form: everyone's actual paper form, all its fields ------------------------------

def test_the_full_screening_form_is_saved_and_read_back(tenant):
    j = job(tenant)
    data = tenant.get("/api/workers").json()
    assert "Male" in data["sexes"] and "Married" in data["marital_statuses"]
    body = {
        "job_id": j["id"], "name": "Ravi Kumar", "age": 30, "trade": "Mason helper",
        "contractor_name": "Sri Sai Contractors", "father_name": "Venkat Rao", "dob": "1996-05-14",
        "sex": "Male", "marital_status": "Married", "children": 2,
        "mother_tongue": "Telugu", "other_languages": "Hindi, English",
        "emergency_contact": "Lakshmi, 98765 43210", "identification_mark": "Scar on left hand",
        "vision_normal": False, "vision_problem": "Needs glasses for reading",
        "health_normal": True, "weight_kg": 68, "height_cm": 170, "blood_group": "B+",
        "education": [{"exam": "SSC", "year": "2012", "school": "ZP High School"}],
        "experience": [{"organization": "L&T", "project_site": "Nuzividu", "category": "Mason",
                        "period": "2023-2025", "salary": "700/day"}],
        "certificates_verified": True, "trial_briefed": True, "safety_officer_name": "Prasad",
    }
    res = tenant.post("/api/workers", json=body)
    assert res.status_code == 200, res.text
    w = res.json()["worker"]
    assert w["contractor_name"] == "Sri Sai Contractors" and w["father_name"] == "Venkat Rao"
    assert w["dob"] == "1996-05-14" and w["sex"] == "Male" and w["marital_status"] == "Married" and w["children"] == 2
    assert w["mother_tongue"] == "Telugu" and w["other_languages"] == "Hindi, English"
    assert w["emergency_contact"].startswith("Lakshmi") and w["identification_mark"] == "Scar on left hand"
    assert w["vision_normal"] is False and w["vision_problem"] == "Needs glasses for reading"
    assert w["health_normal"] is True and w["health_problem"] == ""
    assert w["weight_kg"] == 68 and w["height_cm"] == 170 and w["blood_group"] == "B+"
    assert w["education"] == [{"exam": "SSC", "year": "2012", "school": "ZP High School"}]
    assert w["experience"] == [{"organization": "L&T", "project_site": "Nuzividu", "category": "Mason",
                                "period": "2023-2025", "salary": "700/day"}]
    assert w["certificates_verified"] is True and w["trial_briefed"] is True and w["safety_officer_name"] == "Prasad"
    # Reading the worker back (as selecting it in the list would) shows every field, not just the summary columns.
    again = tenant.get("/api/workers?job_id=%d" % j["id"]).json()["workers"][0]
    assert again == w


def test_a_worker_with_only_the_required_fields_is_still_fine(tenant):
    j = job(tenant)
    res = tenant.post("/api/workers", json={"job_id": j["id"], "name": "Suresh", "age": 25, "trade": "Fitter"})
    assert res.status_code == 200, res.text
    w = res.json()["worker"]
    assert w["education"] == [] and w["experience"] == [] and w["vision_normal"] is True
    assert w["certificates_verified"] is False and w["contractor_name"] == ""


def test_an_invalid_sex_or_marital_status_is_refused(tenant):
    j = job(tenant)
    assert tenant.post("/api/workers", json={"job_id": j["id"], "name": "X", "age": 25, "trade": "Fitter",
                                             "sex": "Robot"}).status_code == 400
    assert tenant.post("/api/workers", json={"job_id": j["id"], "name": "X", "age": 25, "trade": "Fitter",
                                             "marital_status": "Engaged"}).status_code == 400


def test_blank_rows_in_education_and_experience_are_dropped(tenant):
    j = job(tenant)
    res = tenant.post("/api/workers", json={
        "job_id": j["id"], "name": "X", "age": 25, "trade": "Fitter",
        "education": [{"exam": "", "year": "2020", "school": ""}, {"exam": "ITI", "year": "2019", "school": "Govt ITI"}],
        "experience": [{"organization": "", "project_site": ""}],
    })
    assert res.status_code == 200, res.text
    w = res.json()["worker"]
    assert w["education"] == [{"exam": "ITI", "year": "2019", "school": "Govt ITI"}]
    assert w["experience"] == []


# --- the HSE plan's site check: the site held against the plan from what is already recorded ------------------------

def check(tenant, j):
    res = tenant.get("/api/safety/hse-check?job_id=%d" % j["id"])
    assert res.status_code == 200, res.text
    body = res.json()
    return body, {x["key"]: x for x in body["items"]}


def test_an_empty_site_says_nobody_is_screened_and_no_talk_was_held(tenant):
    j = job(tenant)
    body, items = check(tenant, j)
    assert items["screened"]["status"] == "info"
    assert items["talk"]["status"] == "warn"
    assert items["incidents"]["status"] == "ok" and items["permits"]["status"] == "ok"
    assert body["total"] == len(body["items"]) - 1        # the "info" line is not scored


def test_an_unbriefed_worker_without_a_certificate_is_flagged_by_name(tenant):
    j = job(tenant)
    tenant.post("/api/workers", json={"job_id": j["id"], "name": "Ravi Kumar", "age": 30, "trade": "Mason"})
    tenant.post("/api/workers", json={"job_id": j["id"], "name": "Suresh", "age": 30, "trade": "Fitter",
                                      "trial_briefed": True})
    _, items = check(tenant, j)
    assert items["briefed"]["status"] == "bad" and items["briefed"]["count"] == 1
    assert "Ravi Kumar" in items["briefed"]["detail"] and "Suresh" not in items["briefed"]["detail"]
    assert items["medical"]["status"] == "warn" and items["medical"]["count"] == 2


def test_a_talk_this_week_and_a_run_out_permit_show(tenant):
    j = job(tenant)
    tenant.post("/api/safety/talks", json={"job_id": j["id"], "topic": "Working at height", "attendees": 12})
    then = datetime.now() - timedelta(hours=10)
    p = tenant.post("/api/safety/permits", json=permit_body(
        j, valid_from=then.strftime("%Y-%m-%d %H:%M"),
        valid_to=(then + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"))).json()["permit"]
    _, items = check(tenant, j)
    assert items["talk"]["status"] == "ok"
    assert items["permits"]["status"] == "bad" and p["number"] in items["permits"]["detail"]


def test_a_serious_injury_left_open_past_7_days_is_overdue(tenant):
    j = job(tenant)
    i = tenant.post("/api/safety/incidents", json={
        "job_id": j["id"], "kind": "Lost time injury", "description": "Fell from ladder",
        "injured_name": "Ramaiah K", "lost_days": 5,
        "happened_on": (date.today() - timedelta(days=10)).isoformat()}).json()["incident"]
    _, items = check(tenant, j)
    assert items["incidents"]["status"] == "bad"
    assert items["reported"]["status"] == "bad" and i["number"] in items["reported"]["detail"]


def test_another_company_sees_nothing_of_this_sites_check(tenant, second_tenant):
    j = job(tenant)
    tenant.post("/api/workers", json={"job_id": j["id"], "name": "Ravi Kumar", "age": 30, "trade": "Mason"})
    items = {x["key"]: x for x in second_tenant.get("/api/safety/hse-check").json()["items"]}
    assert items["screened"]["count"] == 0 and items["briefed"]["count"] == 0
