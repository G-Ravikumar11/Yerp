"""Quality: the checklist walked before work is covered, the cubes read
against the grade, and anything not as specified followed to a close."""
from datetime import date, timedelta


def job(tenant):
    return tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()


def inspection(tenant, j, checklist="Reinforcement"):
    res = tenant.post("/api/qc/inspections", json={"job_id": j["id"], "checklist": checklist,
                                                   "location": "Raft, grid A-C"})
    assert res.status_code == 200, res.text
    return res.json()["inspection"]


def mark(tenant, i, bad=()):
    items = [dict(x, result="not ok" if n in bad else "ok", remark="lap short" if n in bad else "")
             for n, x in enumerate(i["items"])]
    return tenant.put("/api/qc/inspections/%d" % i["id"], json={"job_id": i["job_id"], "items": items}).json()["inspection"]


def test_a_checklist_starts_from_the_standard_items(tenant):
    i = inspection(tenant, job(tenant))
    assert i["number"] == "INS-0001" and len(i["items"]) == 8
    assert i["items"][2]["item"].startswith("Lap lengths") and i["result"] == "OPEN"


def test_it_cannot_close_with_items_not_looked_at(tenant):
    i = inspection(tenant, job(tenant))
    res = tenant.post("/api/qc/inspections/%d/close" % i["id"])
    assert res.status_code == 409 and "Not looked at yet" in res.json()["detail"]


def test_passed_when_all_is_well_failed_when_anything_is_not(tenant):
    j = job(tenant)
    good = mark(tenant, inspection(tenant, j))
    assert tenant.post("/api/qc/inspections/%d/close" % good["id"]).json()["inspection"]["result"] == "PASSED"
    bad = mark(tenant, inspection(tenant, j), bad=(2,))
    out = tenant.post("/api/qc/inspections/%d/close" % bad["id"]).json()["inspection"]
    assert out["result"] == "FAILED" and out["failed_items"] == 1
    assert tenant.put("/api/qc/inspections/%d" % bad["id"], json={"job_id": j["id"], "remarks": "x"}).status_code == 409
    alerts = tenant.get("/api/alerts").json()["alerts"]
    assert any(a["kind"] == "qc_failed" for a in alerts)


def set_criteria(tenant, j, grade="M25", age=28, mean=25.0, single=0, standard="IS 456:2000 cl.16 / project spec 03300"):
    res = tenant.post("/api/qc/criteria", json={"job_id": j["id"], "grade": grade, "age_days": age,
                                                 "min_mean": mean, "min_single": single, "standard": standard})
    assert res.status_code == 200, res.text
    return res.json()["criteria"]


def overdue(tenant, ncr_id):
    """Back-date an NCR's due date: the API refuses a date already past, as it should."""
    from app import db as database, models
    s = database.SessionLocal()
    try:
        s.query(models.DBNcr).filter(models.DBNcr.id == ncr_id).update({"target_date": (date.today() - timedelta(days=1)).isoformat()})
        s.commit()
    finally:
        s.close()


def test_a_failed_inspection_becomes_an_ncr_with_what_failed(tenant):
    j = job(tenant)
    bad = mark(tenant, inspection(tenant, j), bad=(2,))
    tenant.post("/api/qc/inspections/%d/close" % bad["id"])
    n = tenant.post("/api/qc/ncrs", json={"source_type": "inspection", "source_id": bad["id"],
                                          "responsible": "Sri Sai Constructions", "severity": "Major"}).json()["ncr"]
    assert n["number"] == "NCR-0001" and "Lap lengths" in n["description"] and "lap short" in n["description"]
    assert n["location"] == "Raft, grid A-C" and n["status"] == "OPEN"
    overdue(tenant, n["id"])
    kinds = {i["kind"] for i in tenant.get("/api/attention").json()["items"]}
    assert "ncr_overdue" in kinds
    # It cannot be closed on the word of whoever closes it: the correction is verified first.
    assert tenant.post("/api/qc/ncrs/%d/close" % n["id"], json={"closure_note": "done"}).status_code == 409


def test_cubes_are_read_against_the_projects_criteria(tenant):
    j = job(tenant)
    set_criteria(tenant, j, "M25", 28, 25.0)
    set_criteria(tenant, j, "M25", 7, 16.0)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "m25", "location": "Raft pour 1",
                                           "cast_on": (date.today() - timedelta(days=30)).isoformat()}).json()["cube_set"]
    assert s["fck"] == 25 and s["number"] == "CT-0001" and s["status"] == "awaiting results"
    assert s["test_ages"] == [7, 28]
    assert {d["age_days"] for d in s["due"] if d["overdue"]} == {7, 28}
    kinds = {i["kind"] for i in tenant.get("/api/attention").json()["items"]}
    assert "cubes_due" in kinds
    early = tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 7, "strengths": "17.5, 18.2, 16.9"}).json()["cube_set"]
    assert early["results"][0]["ok"] and "meets the criteria" in early["results"][0]["verdict"]
    final = tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "31.2, 29.8, 30.5"}).json()["cube_set"]
    # Passing the numbers is not acceptance: the engineer accepts the concrete.
    assert final["status"] == "for engineering review" and final["needs_review"] and final["due"] == []
    again = tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "30"})
    assert again.status_code == 409


def test_a_set_below_grade_is_called_out_and_becomes_an_ncr(tenant):
    j = job(tenant)
    set_criteria(tenant, j, "M30", 28, 30.0)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M30", "location": "Column C4"}).json()["cube_set"]
    out = tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "26.1, 27.0, 25.4"}).json()["cube_set"]
    assert out["status"] == "below grade"
    kinds = {i["kind"] for i in tenant.get("/api/attention").json()["items"]}
    assert "cubes_below" in kinds
    n = tenant.post("/api/qc/ncrs", json={"source_type": "cube_set", "source_id": s["id"]}).json()["ncr"]
    assert "M30" in n["description"] and "28-day average 26.17" in n["description"]


def test_a_cube_far_off_the_average_makes_the_set_doubtful(tenant):
    j = job(tenant)
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    out = tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "30, 31, 22"}).json()["cube_set"]
    assert out["results"][0]["spread_ok"] is False


def test_what_is_typed_is_checked(tenant):
    j = job(tenant)
    assert tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "25"}).status_code == 400
    s = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": "M25"}).json()["cube_set"]
    assert tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": 28, "strengths": "strong"}).status_code == 400
    assert tenant.post("/api/qc/ncrs", json={"job_id": j["id"]}).status_code == 400


def test_photos_can_be_kept_against_an_inspection(tenant):
    import io
    i = inspection(tenant, job(tenant))
    res = tenant.post("/api/files", files={"file": ("rebar.jpg", io.BytesIO(b"\xff\xd8\xff" + b"0" * 500), "image/jpeg")},
                      data={"attached_type": "inspection", "attached_id": str(i["id"])})
    assert res.status_code == 200, res.text


def test_another_company_sees_none_of_it(tenant, second_tenant):
    j = job(tenant)
    i = inspection(tenant, j)
    assert second_tenant.get("/api/qc/inspections").json()["inspections"] == []
    assert second_tenant.post("/api/qc/inspections/%d/close" % i["id"]).status_code == 404
