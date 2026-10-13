"""Quality workflow: who may do what, how a record moves from one status to the next, what the
dashboard counts, and that nothing is accepted on the strength of a number alone."""
import io
from datetime import date, timedelta

from test_site_access import signed_in
from test_quality import job, inspection, mark, set_criteria, overdue


def day(n):
    return (date.today() + timedelta(days=n)).isoformat()


def failed_inspection(tenant, j, checklist="Reinforcement"):
    i = mark(tenant, inspection(tenant, j, checklist), bad=(2,))
    assert tenant.post("/api/qc/inspections/%d/close" % i["id"]).status_code == 200
    return i


def photo(tenant, kind, rec_id, name="proof.jpg"):
    res = tenant.post("/api/files", files={"file": (name, io.BytesIO(b"\xff\xd8\xff" + b"0" * 400), "image/jpeg")},
                      data={"attached_type": kind, "attached_id": str(rec_id)})
    assert res.status_code == 200, res.text


# ---- the dashboard ---------------------------------------------------------------------------

def test_the_dashboard_counts_what_is_stored_and_respects_the_project(tenant):
    a, b = job(tenant), tenant.post("/api/jobs", json={"name": "Second site", "customer_name": "X"}).json()
    failed_inspection(tenant, a)
    ok = mark(tenant, inspection(tenant, b))
    tenant.post("/api/qc/inspections/%d/close" % ok["id"])
    set_criteria(tenant, a, "M30", 28, 30.0)
    tenant.post("/api/qc/cubes", json={"job_id": a["id"], "grade": "M30", "cast_on": day(-40)})
    low = tenant.post("/api/qc/cubes", json={"job_id": a["id"], "grade": "M30", "cast_on": day(-40)}).json()["cube_set"]
    tenant.post("/api/qc/cubes/%d/results" % low["id"], json={"age_days": 28, "strengths": "24, 25, 26"})
    tenant.post("/api/qc/ncrs", json={"job_id": a["id"], "description": "Honeycombing on column C4"})
    tenant.post("/api/qc/ncrs", json={"job_id": b["id"], "description": "Cover short on slab"})

    everything = tenant.get("/api/qc/summary").json()
    assert everything["inspections_failed"] == 1 and everything["below_grade"] == 1 and everything["ncrs_open"] == 2
    # The project tests M30 at 28 days only; two sets cast 40 days ago, one already crushed.
    assert everything["cubes_to_crush"] == 1 and everything["cubes_overdue"] == 1
    one = tenant.get("/api/qc/summary?job_id=%d" % b["id"]).json()
    assert one["inspections_failed"] == 0 and one["below_grade"] == 0 and one["cubes_to_crush"] == 0 and one["ncrs_open"] == 1


def test_a_closed_ncr_is_no_longer_open_in_the_count(tenant):
    j = job(tenant)
    n = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Leak at joint"}).json()["ncr"]
    assert tenant.get("/api/qc/summary").json()["ncrs_open"] == 1
    walk_ncr_to_closure(tenant, n)
    assert tenant.get("/api/qc/summary").json()["ncrs_open"] == 0


# ---- filters, sorting, pages -----------------------------------------------------------------

def test_lists_filter_search_sort_and_page_on_the_server(tenant):
    j = job(tenant)
    for _ in range(5):
        inspection(tenant, j)
    failed_inspection(tenant, j, "Shuttering")
    r = tenant.get("/api/qc/inspections?page_size=4&sort=number&dir=asc").json()
    assert r["total"] == 6 and len(r["inspections"]) == 4 and r["inspections"][0]["number"] == "INS-0001"
    assert len(tenant.get("/api/qc/inspections?page_size=4&page=2").json()["inspections"]) == 2
    assert tenant.get("/api/qc/inspections?status=failed").json()["total"] == 1
    assert tenant.get("/api/qc/inspections?status=pending").json()["total"] == 5
    assert tenant.get("/api/qc/inspections?q=shutter").json()["total"] == 1
    assert tenant.get("/api/qc/inspections?date_from=%s" % day(1)).json()["total"] == 0
    assert tenant.get("/api/qc/inspections?date_to=%s" % day(1)).json()["total"] == 6
    other = tenant.post("/api/jobs", json={"name": "Other", "customer_name": "Y"}).json()
    assert tenant.get("/api/qc/inspections?job_id=%d" % other["id"]).json()["total"] == 0


def test_cube_lists_filter_by_what_the_cards_count(tenant):
    j = job(tenant)
    set_criteria(tenant, j, "M30", 28, 30.0)
    due = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M30", "cast_on": day(-10), "test_ages": "7"}).json()["cube_set"]
    low = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M30", "cast_on": day(-30), "test_ages": "28"}).json()["cube_set"]
    tenant.post("/api/qc/cubes/%d/results" % low["id"], json={"age_days": 28, "strengths": "20, 21, 22"})
    assert [c["id"] for c in tenant.get("/api/qc/cubes?status=to_crush").json()["cubes"]] == [due["id"]]
    assert [c["id"] for c in tenant.get("/api/qc/cubes?status=below_grade").json()["cubes"]] == [low["id"]]
    assert tenant.get("/api/qc/cubes?q=%s" % due["number"]).json()["total"] == 1


# ---- inspections -----------------------------------------------------------------------------

def test_an_inspector_submits_and_the_record_is_locked_until_it_is_decided(tenant, portal):
    j = job(tenant)
    signed_in(tenant, portal, "staff")
    i = portal.post("/api/qc/inspections", json={"job_id": j["id"], "checklist": "Plastering", "location": "Block A",
                                                  "building": "A", "floor_area": "2nd floor", "work_activity": "Internal plaster",
                                                  "assigned_to": "R. Kumar", "measurements": "Thickness 12-14 mm"}).json()["inspection"]
    assert i["building"] == "A" and i["assigned_to"] == "R. Kumar" and i["measurements"].startswith("Thickness")
    assert portal.post("/api/qc/inspections/%d/submit" % i["id"]).status_code == 409        # nothing looked at yet
    items = [dict(x, result="ok") for x in i["items"]]
    assert portal.put("/api/qc/inspections/%d" % i["id"], json={"job_id": j["id"], "items": items}).status_code == 200
    assert portal.post("/api/qc/inspections/%d/submit" % i["id"]).json()["inspection"]["approval_status"] == "submitted"
    # Locked while it waits, and the inspector cannot approve their own work.
    assert portal.put("/api/qc/inspections/%d" % i["id"], json={"job_id": j["id"], "remarks": "x"}).status_code == 409
    no = portal.post("/api/qc/inspections/%d/close" % i["id"])
    assert no.status_code == 403
    assert tenant.get("/api/qc/summary").json()["inspections_awaiting_approval"] == 1


def test_the_approver_can_return_it_or_decide_it(tenant, portal):
    j = job(tenant)
    signed_in(tenant, portal, "staff")
    i = portal.post("/api/qc/inspections", json={"job_id": j["id"], "checklist": "Flooring"}).json()["inspection"]
    items = [dict(x, result="ok") for x in i["items"]]
    portal.put("/api/qc/inspections/%d" % i["id"], json={"job_id": j["id"], "items": items})
    portal.post("/api/qc/inspections/%d/submit" % i["id"])
    assert tenant.post("/api/qc/inspections/%d/return" % i["id"], json={"note": ""}).status_code == 400
    back = tenant.post("/api/qc/inspections/%d/return" % i["id"], json={"note": "Photograph the joints"}).json()["inspection"]
    assert back["approval_status"] == "returned" and back["editable"] and back["return_note"] == "Photograph the joints"
    assert portal.put("/api/qc/inspections/%d" % i["id"], json={"job_id": j["id"], "remarks": "done"}).status_code == 200
    portal.post("/api/qc/inspections/%d/submit" % i["id"])
    done = tenant.post("/api/qc/inspections/%d/close" % i["id"]).json()["inspection"]
    assert done["result"] == "PASSED" and done["approval_status"] == "approved" and done["approved_by"]


def test_a_reinspection_after_corrective_work_moves_the_ncr_on(tenant):
    j = job(tenant)
    bad = failed_inspection(tenant, j)
    # Only a failed inspection is re-inspected.
    fine = mark(tenant, inspection(tenant, j))
    tenant.post("/api/qc/inspections/%d/close" % fine["id"])
    assert tenant.post("/api/qc/inspections/%d/reinspect" % fine["id"]).status_code == 409
    n = tenant.post("/api/qc/ncrs", json={"source_type": "inspection", "source_id": bad["id"]}).json()["ncr"]
    tenant.post("/api/qc/ncrs/%d/assign" % n["id"], json={"responsible": "Sri Sai", "target_date": day(5)})
    re_ = tenant.post("/api/qc/inspections/%d/reinspect" % bad["id"]).json()["inspection"]
    assert re_["reinspection_of"] == bad["id"] and all(x["result"] == "" for x in re_["items"])
    assert tenant.post("/api/qc/inspections/%d/reinspect" % bad["id"]).status_code == 409          # one at a time
    for x in re_["items"]:
        x["result"] = "ok"
    tenant.put("/api/qc/inspections/%d" % re_["id"], json={"job_id": j["id"], "items": re_["items"]})
    assert tenant.post("/api/qc/inspections/%d/close" % re_["id"]).json()["inspection"]["result"] == "PASSED"
    moved = tenant.get("/api/qc/ncrs/%d" % n["id"]).json()["ncr"]
    assert moved["status"] == "REINSPECTION" and moved["reinspection_ref"] == re_["number"]
    detail = tenant.get("/api/qc/inspections/%d" % bad["id"]).json()["inspection"]
    assert detail["reinspection_number"] == re_["number"] and detail["reinspection_result"] == "PASSED"


def test_checklists_are_kept_by_those_who_sign_off(tenant, portal):
    j = job(tenant)
    standard = tenant.get("/api/qc/checklists").json()["checklists"]
    for name in ("Pre-pour (concrete)", "Reinforcement", "Brickwork / blockwork", "Plastering", "Waterproofing", "Flooring"):
        assert name in standard
    mine = tenant.post("/api/qc/checklists", json={"name": "Flooring", "work_type": "Flooring", "spec_ref": "Spec 09 30",
                                                   "items": [{"item": "Tile batch matches the approved sample", "criteria": "Same batch and shade"},
                                                             {"item": "Joint width", "criteria": "2 mm +/- 0.5"}]})
    assert mine.status_code == 200, mine.text
    assert tenant.get("/api/qc/checklists").json()["checklists"]["Flooring"][1] == "Joint width"
    assert tenant.post("/api/qc/checklists", json={"name": "Flooring", "items": [{"item": "x"}]}).status_code == 409
    assert tenant.post("/api/qc/checklists", json={"name": "Empty", "items": []}).status_code == 400
    i = tenant.post("/api/qc/inspections", json={"job_id": j["id"], "checklist": "Flooring"}).json()["inspection"]
    assert i["items"][0]["criteria"] == "Same batch and shade"
    signed_in(tenant, portal, "staff")
    assert portal.post("/api/qc/checklists", json={"name": "Mine", "items": [{"item": "a"}]}).status_code == 403
    assert portal.put("/api/qc/checklists/%d" % mine.json()["checklist"]["id"], json={"name": "x", "items": [{"item": "a"}]}).status_code == 403
    assert portal.delete("/api/qc/checklists/%d" % mine.json()["checklist"]["id"]).status_code == 403
    assert tenant.delete("/api/qc/checklists/%d" % mine.json()["checklist"]["id"]).status_code == 200
    assert tenant.get("/api/qc/checklists").json()["checklists"]["Flooring"][0].startswith("Sub-base")


def test_validation_on_the_inspection_form(tenant):
    j = job(tenant)
    assert tenant.post("/api/qc/inspections", json={"job_id": j["id"], "checklist": "Nonsense"}).status_code == 400
    assert tenant.post("/api/qc/inspections", json={"job_id": j["id"], "checklist": "Plastering", "inspected_on": day(3)}).status_code == 400
    assert tenant.post("/api/qc/inspections", json={"job_id": j["id"], "checklist": "Plastering", "inspected_on": "soon"}).status_code == 400
    assert tenant.post("/api/qc/inspections", json={"job_id": 99999, "checklist": "Plastering"}).status_code == 404


# ---- concrete cubes --------------------------------------------------------------------------

def test_a_result_with_no_criteria_is_not_accepted_and_needs_review(tenant):
    j = job(tenant)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    out = tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "40, 41, 42"}).json()["cube_set"]
    r = out["results"][0]
    assert r["evaluation"] == "no_criteria" and not r["ok"] and not r["failed"]
    assert out["status"] == "criteria not set" and out["needs_review"]
    assert any("No approved acceptance criteria" in x for x in out["review_reasons"])


def test_criteria_come_from_the_project_not_from_the_grade_name(tenant):
    j = job(tenant)
    set_criteria(tenant, j, "M25", 28, 33.0, single=30.0, standard="Project spec 03300 cl. 4.2")
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    out = tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "34, 35, 29"}).json()["cube_set"]
    r = out["results"][0]
    # The average clears 33 but one cube is under the 30 the specification allows.
    assert r["evaluation"] == "below" and r["criteria_min"] == 33.0 and r["criteria_single"] == 30.0
    assert r["criteria_ref"] == "Project spec 03300 cl. 4.2" and out["status"] == "below grade"
    # Changing the criteria afterwards does not rewrite what was recorded.
    cid = tenant.get("/api/qc/criteria?job_id=%d" % j["id"]).json()["criteria"][0]["id"]
    tenant.put("/api/qc/criteria/%d" % cid, json={"job_id": j["id"], "grade": "M25", "age_days": 28, "min_mean": 20, "min_single": 0, "standard": "Revised"})
    again = tenant.get("/api/qc/cubes/%d" % s["id"]).json()["cube_set"]["results"][0]
    assert again["evaluation"] == "below" and again["criteria_min"] == 33.0


def test_criteria_are_validated_and_signed_off_only(tenant, portal):
    j = job(tenant)
    base = {"job_id": j["id"], "grade": "M25", "age_days": 28, "min_mean": 25, "min_single": 0, "standard": "IS 456"}
    assert tenant.post("/api/qc/criteria", json=dict(base, grade="25")).status_code == 400
    assert tenant.post("/api/qc/criteria", json=dict(base, min_mean=0)).status_code == 400
    assert tenant.post("/api/qc/criteria", json=dict(base, min_single=30)).status_code == 400
    assert tenant.post("/api/qc/criteria", json=dict(base, standard="")).status_code == 400
    assert tenant.post("/api/qc/criteria", json=base).status_code == 200
    assert tenant.post("/api/qc/criteria", json=base).status_code == 409
    signed_in(tenant, portal, "staff")
    assert portal.post("/api/qc/criteria", json=dict(base, grade="M30")).status_code == 403
    assert portal.get("/api/qc/criteria").status_code == 200


def test_the_schedule_follows_the_project_and_due_dates_are_worked_out(tenant):
    j = job(tenant)
    set_criteria(tenant, j, "M30", 7, 20.0)
    set_criteria(tenant, j, "M30", 28, 30.0)
    set_criteria(tenant, j, "M30", 56, 33.0)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M30", "cast_on": day(-28), "pour_ref": "P-14",
                                           "cube_ids": "A1, A2, A3"}).json()["cube_set"]
    assert s["test_ages"] == [7, 28, 56] and s["pour_ref"] == "P-14" and s["cube_ids"] == "A1, A2, A3"
    by_age = {x["age_days"]: x for x in s["schedule"]}
    assert by_age[28]["state"] == "due" and by_age[7]["state"] == "overdue" and by_age[56]["state"] == "upcoming"
    assert by_age[56]["due_on"] == day(28)
    # Not being tested yet is not due.
    assert {d["age_days"] for d in s["due"] if d["overdue"] or d["today"]} == {7, 28}


def test_cube_entry_is_validated(tenant):
    j = job(tenant)
    assert tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25", "cast_on": day(2)}).status_code == 400
    assert tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25", "test_ages": "weekly"}).status_code == 400
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25", "cast_on": day(-10)}).json()["cube_set"]
    path = "/api/qc/cubes/%d/results" % s["id"]
    assert tenant.post(path, json={"age_days": 7, "strengths": "20", "tested_on": day(-20)}).status_code == 400    # before casting
    assert tenant.post(path, json={"age_days": 7, "strengths": "20", "tested_on": day(1)}).status_code == 400      # in the future
    assert tenant.post(path, json={"age_days": 0, "strengths": "20"}).status_code == 400
    assert tenant.post(path, json={"age_days": 7, "strengths": "999"}).status_code == 400
    ok = tenant.post(path, json={"age_days": 7, "strengths": "20, 21", "tested_on": day(-3), "lab": "ABC Labs", "remarks": "Wet cubes"}).json()["cube_set"]
    assert ok["results"][0]["lab"] == "ABC Labs" and ok["results"][0]["actual_age"] == 7 and ok["results"][0]["remarks"] == "Wet cubes"


def test_only_the_engineer_accepts_concrete_and_only_with_a_reason(tenant, portal):
    j = job(tenant)
    set_criteria(tenant, j, "M25", 28, 25.0)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25", "test_ages": "28"}).json()["cube_set"]
    path = "/api/qc/cubes/%d" % s["id"]
    assert tenant.post(path + "/decision", json={"decision": "accepted", "note": "x"}).status_code == 409        # no result yet
    tenant.post(path + "/results", json={"age_days": 28, "strengths": "30, 31, 29"})
    signed_in(tenant, portal, "staff")
    assert portal.post(path + "/decision", json={"decision": "accepted", "note": "ok"}).status_code == 403
    # The recorder can send it for review, and it stays in review until somebody who signs off decides.
    assert portal.post(path + "/flag", json={"note": ""}).status_code == 400
    flagged = portal.post(path + "/flag", json={"note": "Cubes looked honeycombed"}).json()["cube_set"]
    assert flagged["needs_review"] and "Flagged for engineering review" in flagged["review_reasons"]
    as_owner = tenant
    assert as_owner.post(path + "/decision", json={"decision": "accepted", "note": ""}).status_code == 400
    assert as_owner.post(path + "/decision", json={"decision": "great", "note": "x"}).status_code == 400
    done = as_owner.post(path + "/decision", json={"decision": "accepted", "note": "Reviewed mix records and curing log"}).json()["cube_set"]
    assert done["status"] == "accepted" and not done["needs_review"] and done["accepted_by"]
    assert tenant.get("/api/qc/summary").json()["cubes_for_review"] == 0


def test_a_failed_cube_cannot_simply_be_accepted(tenant):
    j = job(tenant)
    set_criteria(tenant, j, "M25", 28, 25.0)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "18, 19, 20"})
    p = "/api/qc/cubes/%d/decision" % s["id"]
    assert tenant.post(p, json={"decision": "accepted", "note": "fine"}).status_code == 409
    out = tenant.post(p, json={"decision": "rejected", "note": "Core test ordered"}).json()["cube_set"]
    assert out["status"] == "rejected" and out["counted_below"] == 1       # still counted until the concrete is dealt with
    out2 = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    tenant.post("/api/qc/cubes/%d/results" % out2["id"], json={"age_days": 28, "strengths": "18, 19, 20"})
    tenant.post("/api/qc/cubes/%d/decision" % out2["id"], json={"decision": "conditional", "note": "Cores passed, load test to follow"})
    assert tenant.get("/api/qc/cubes/%d" % out2["id"]).json()["cube_set"]["counted_below"] == 0


def test_a_test_report_can_be_attached_to_the_sample(tenant):
    j = job(tenant)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    res = tenant.post("/api/files", files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
                      data={"attached_type": "cube_set", "attached_id": str(s["id"]), "kind": "document"})
    assert res.status_code == 200, res.text
    listed = tenant.get("/api/files?attached_type=cube_set&attached_id=%d" % s["id"])
    assert listed.status_code == 200 and "report.pdf" in listed.text


def test_sample_history_records_who_did_what(tenant):
    j = job(tenant)
    set_criteria(tenant, j, "M25", 28, 25.0)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "30, 31"})
    h = tenant.get("/api/qc/cubes/%d" % s["id"]).json()["history"]
    assert [x["action"] for x in h] == ["qc.cube.result", "qc.cube.registered"] and "meets the criteria" in h[0]["details"]


# ---- non-conformances ------------------------------------------------------------------------

def walk_ncr_to_closure(tenant, n):
    base = "/api/qc/ncrs/%d" % n["id"]
    assert tenant.post(base + "/assign", json={"responsible": "Sri Sai", "target_date": day(7)}).status_code == 200
    assert tenant.post(base + "/work", json={"corrective_done": "Chipped and re-cast"}).status_code == 200
    assert tenant.post(base + "/request-verification").status_code == 200
    assert tenant.post(base + "/verify", json={"result": "verified", "note": "Checked on site"}).status_code == 200
    return tenant.post(base + "/close", json={"closure_note": "Repaired and verified"}).json()["ncr"]


def test_an_ncr_moves_through_every_status_in_order(tenant):
    j = job(tenant)
    n = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Honeycombing on column C4", "location": "Grid C4"}).json()["ncr"]
    base = "/api/qc/ncrs/%d" % n["id"]
    assert n["status"] == "OPEN"
    # Out of order is refused at every step.
    assert tenant.post(base + "/work", json={"corrective_done": "x"}).status_code == 409
    assert tenant.post(base + "/request-verification").status_code == 409
    assert tenant.post(base + "/verify", json={"result": "verified"}).status_code == 409
    assert tenant.post(base + "/close", json={"closure_note": "x"}).status_code == 409
    a = tenant.post(base + "/assign", json={"responsible": "Sri Sai Constructions", "target_date": day(7), "corrective_action": "Cut back and re-cast"}).json()["ncr"]
    assert a["status"] == "ASSIGNED" and a["responsible"] == "Sri Sai Constructions" and a["assigned_by"]
    w = tenant.post(base + "/work", json={"corrective_done": "Cut back and re-cast with micro-concrete"}).json()["ncr"]
    assert w["status"] == "UNDER_CORRECTION" and w["corrective_on"] == date.today().isoformat()
    assert tenant.post(base + "/request-verification").json()["ncr"]["status"] == "REINSPECTION"
    # Rejected: back under correction, with the reason kept.
    assert tenant.post(base + "/verify", json={"result": "rejected", "note": ""}).status_code == 400
    r = tenant.post(base + "/verify", json={"result": "rejected", "note": "Still a void at the top"}).json()["ncr"]
    assert r["status"] == "UNDER_CORRECTION" and r["verification_result"] == "rejected" and r["verification_note"] == "Still a void at the top"
    tenant.post(base + "/work", json={"corrective_done": "Voids grouted"})
    tenant.post(base + "/request-verification")
    assert tenant.post(base + "/close", json={"closure_note": "x"}).status_code == 409          # not yet verified
    tenant.post(base + "/verify", json={"result": "verified", "note": "Sound"})
    assert tenant.post(base + "/close", json={"closure_note": ""}).status_code == 400
    closed = tenant.post(base + "/close", json={"closure_note": "Voids grouted and verified"}).json()["ncr"]
    assert closed["status"] == "CLOSED" and closed["closed_by"] and closed["closed_on"] == date.today().isoformat()
    # Nothing moves after it is closed.
    assert tenant.post(base + "/assign", json={"responsible": "x", "target_date": day(3)}).status_code == 409
    assert tenant.post(base + "/close", json={"closure_note": "again"}).status_code == 409


def test_who_may_do_what_on_an_ncr(tenant, portal):
    j = job(tenant)
    n = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Cover short on slab"}).json()["ncr"]
    base = "/api/qc/ncrs/%d" % n["id"]
    signed_in(tenant, portal, "staff")                    # may record, may not sign off
    assert portal.post(base + "/assign", json={"responsible": "Gang A", "target_date": day(4)}).status_code == 403
    tenant.post(base + "/assign", json={"responsible": "Gang A", "target_date": day(4)})
    assert portal.post(base + "/work", json={"corrective_done": "Re-laid"}).status_code == 200
    assert portal.post(base + "/request-verification").status_code == 200
    assert portal.post(base + "/verify", json={"result": "verified"}).status_code == 403
    assert portal.post(base + "/close", json={"closure_note": "ok"}).status_code == 403
    assert portal.get(base).status_code == 200 and portal.get("/api/qc/ncrs").status_code == 200


def test_a_serious_ncr_needs_its_root_cause_and_evidence_before_verification(tenant):
    j = job(tenant)
    n = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Column out of plumb", "severity": "Major"}).json()["ncr"]
    base = "/api/qc/ncrs/%d" % n["id"]
    assert n["needs_root_cause"]
    tenant.post(base + "/assign", json={"responsible": "Gang A", "target_date": day(4)})
    tenant.post(base + "/work", json={"corrective_done": "Jacked and propped"})
    assert tenant.post(base + "/request-verification").status_code == 409                    # no root cause
    tenant.post(base + "/work", json={"corrective_done": "Jacked and propped", "root_cause": "Shuttering moved during the pour"})
    assert tenant.post(base + "/request-verification").status_code == 409                    # no evidence
    photo(tenant, "ncr", n["id"])
    assert tenant.post(base + "/request-verification").json()["ncr"]["status"] == "REINSPECTION"
    assert tenant.get(base).json()["ncr"]["evidence"] == 1


def test_one_issue_gets_one_ncr(tenant):
    j = job(tenant)
    bad = failed_inspection(tenant, j)
    first = tenant.post("/api/qc/ncrs", json={"source_type": "inspection", "source_id": bad["id"]})
    assert first.status_code == 200
    dup = tenant.post("/api/qc/ncrs", json={"source_type": "inspection", "source_id": bad["id"], "severity": "Major"})
    assert dup.status_code == 409 and first.json()["ncr"]["number"] in dup.json()["detail"]
    # Not for an inspection that did not fail.
    ok = mark(tenant, inspection(tenant, j))
    tenant.post("/api/qc/inspections/%d/close" % ok["id"])
    assert tenant.post("/api/qc/ncrs", json={"source_type": "inspection", "source_id": ok["id"]}).status_code == 409
    # The same words on the same project while the first is open.
    a = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Leak at joint"})
    assert a.status_code == 200
    assert tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "  leak at JOINT "}).status_code == 409
    # Cubes: one NCR per result.
    set_criteria(tenant, j, "M25", 28, 25.0)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "15, 16, 17"})
    assert tenant.post("/api/qc/ncrs", json={"source_type": "cube_set", "source_id": s["id"]}).status_code == 200
    assert tenant.post("/api/qc/ncrs", json={"source_type": "cube_set", "source_id": s["id"]}).status_code == 409


def test_ncr_numbers_stay_unique_after_a_record_is_deleted(tenant):
    j = job(tenant)
    a = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "One"}).json()["ncr"]
    b = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Two"}).json()["ncr"]
    from app import db as database, models
    s = database.SessionLocal()
    try:
        s.query(models.DBNcr).filter(models.DBNcr.id == a["id"]).delete()
        s.commit()
    finally:
        s.close()
    c = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Three"}).json()["ncr"]
    assert (a["number"], b["number"], c["number"]) == ("NCR-0001", "NCR-0002", "NCR-0003")


def test_ncr_form_is_validated(tenant):
    j = job(tenant)
    base = {"job_id": j["id"], "description": "Crack in slab"}
    assert tenant.post("/api/qc/ncrs", json=dict(base, severity="Catastrophic")).status_code == 400
    assert tenant.post("/api/qc/ncrs", json=dict(base, target_date="yesterday")).status_code == 400
    assert tenant.post("/api/qc/ncrs", json=dict(base, target_date=day(-2))).status_code == 400
    n = tenant.post("/api/qc/ncrs", json=base).json()["ncr"]
    assert tenant.post("/api/qc/ncrs/%d/assign" % n["id"], json={"responsible": "", "target_date": day(3)}).status_code == 400
    assert tenant.post("/api/qc/ncrs/%d/assign" % n["id"], json={"responsible": "A", "target_date": ""}).status_code == 400
    assert tenant.post("/api/qc/ncrs/%d/assign" % n["id"], json={"responsible": "A", "target_date": day(-1)}).status_code == 400


def test_ncr_list_filters_and_overdue(tenant):
    j = job(tenant)
    a = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Leak", "target_date": day(3), "severity": "Major"}).json()["ncr"]
    tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Crack"})
    overdue(tenant, a["id"])
    assert tenant.get("/api/qc/ncrs?status=overdue").json()["total"] == 1
    assert tenant.get("/api/qc/ncrs?severity=Major").json()["total"] == 1
    assert tenant.get("/api/qc/ncrs?status=closed").json()["total"] == 0
    assert tenant.get("/api/qc/ncrs?q=crack").json()["total"] == 1
    s = tenant.get("/api/qc/ncrs").json()["summary"]
    assert s["open"] == 2 and s["overdue"] == 1 and s["major_open"] == 1


# ---- the audit trail -------------------------------------------------------------------------

def test_every_status_change_is_in_the_trail(tenant):
    j = job(tenant)
    n = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Leak at joint"}).json()["ncr"]
    walk_ncr_to_closure(tenant, n)
    actions = [h["action"] for h in tenant.get("/api/qc/ncrs/%d" % n["id"]).json()["history"]]
    assert actions[::-1] == ["qc.ncr.raised", "qc.ncr.assigned", "qc.ncr.corrective_recorded",
                             "qc.ncr.verification_requested", "qc.ncr.verified", "qc.ncr.closed"]
    assert all(h["who"] for h in tenant.get("/api/qc/ncrs/%d" % n["id"]).json()["history"])
    i = failed_inspection(tenant, j)
    assert [h["action"] for h in tenant.get("/api/qc/inspections/%d" % i["id"]).json()["history"]][::-1] == [
        "qc.inspection.created", "qc.inspection.edited", "qc.inspection.failed"]


def test_the_registers_export_with_filters(tenant):
    j = job(tenant)
    failed_inspection(tenant, j)
    tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"})
    tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Leak"})
    for kind in ("inspections", "cubes", "ncrs"):
        res = tenant.get("/api/qc/%s.xlsx?job_id=%d" % (kind, j["id"]))
        assert res.status_code == 200 and len(res.content) > 500, kind
    pdf = tenant.get("/api/qc/inspections/1/document.pdf")
    assert pdf.status_code in (200, 404)


def test_another_company_cannot_reach_the_new_endpoints(tenant, second_tenant):
    j = job(tenant)
    set_criteria(tenant, j)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    n = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Leak"}).json()["ncr"]
    for path in ("/api/qc/cubes/%d" % s["id"], "/api/qc/ncrs/%d" % n["id"]):
        assert second_tenant.get(path).status_code == 404
    assert second_tenant.post("/api/qc/ncrs/%d/assign" % n["id"], json={"responsible": "x", "target_date": day(2)}).status_code == 404
    assert second_tenant.post("/api/qc/cubes/%d/decision" % s["id"], json={"decision": "accepted", "note": "x"}).status_code == 404
    assert second_tenant.get("/api/qc/criteria").json()["criteria"] == []
    assert second_tenant.get("/api/qc/summary").json()["ncrs_open"] == 0
    assert second_tenant.post("/api/qc/criteria", json={"job_id": j["id"], "grade": "M25", "age_days": 28, "min_mean": 25, "standard": "x"}).status_code == 404
