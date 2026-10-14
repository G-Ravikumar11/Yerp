"""AI in the Planning area. The model call is replaced in each test.

What the model proposes is checked against the project's own records before it is shown, nothing is saved until a person
applies it, and the delay findings are plain code that must be right with no key at all.
"""
from datetime import date, timedelta
from types import SimpleNamespace as NS

from app.ai import planning
from app.ai.llm_client import AiResult
from test_ai_subcontracts import unkeyed  # noqa: F401  (fixture)
from test_measurement_and_ra_bills import placed_order
from test_schedule import act, d, job
from test_boq import make_boq, saved

S, F = date(2026, 1, 1), date(2026, 1, 31)


def lines(*ids):
    return [NS(id=i, description="Line %d" % i, item_name="", fg_code="", amount=100.0 * i) for i in ids]


def wo_job(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    return wo, tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]


def test_a_draft_keeps_only_real_lines_inside_the_span_and_covers_every_line():
    out = planning.clean_draft([
        {"line_id": 1, "start": "2025-12-01", "finish": "2026-01-10", "after_line_id": None},
        {"line_id": 99, "start": "2026-01-01", "finish": "2026-01-05"},                       # not on the order
        {"line_id": 1, "start": "2026-01-02", "finish": "2026-01-03"},                        # twice
        {"line_id": 2, "start": "2026-01-20", "finish": "2026-01-05", "after_line_id": 7},    # backwards, follows nothing placed
    ], lines(1, 2, 3), S, F)
    assert [o["line_id"] for o in out] == [1, 2, 3]
    assert out[0]["start"] == "2026-01-01" and out[0]["finish"] == "2026-01-10"
    assert out[1]["start"] <= out[1]["finish"] and out[1]["after_line_id"] is None
    assert out[2]["after_line_id"] == 2 and out[2]["finish"] == "2026-01-31"                  # the one it missed is laid after


def test_a_draft_that_is_not_a_list_still_lays_the_lines_end_to_end():
    out = planning.clean_draft("nonsense", lines(1, 2), S, F)
    assert [o["line_id"] for o in out] == [1, 2] and out[0]["start"] == "2026-01-01" and out[1]["finish"] == "2026-01-31"


def test_drafting_without_a_key_says_so_and_saves_nothing(tenant, unkeyed):
    wo, job_id = wo_job(tenant)
    out = tenant.post("/api/ai/planning/jobs/%d/draft" % job_id, json={"work_order_id": wo["id"], "start": d(0), "finish": d(60)}).json()
    assert out["available"] is False and out["activities"] == []
    assert tenant.get("/api/jobs/%d/schedule" % job_id).json()["activities"] == []


def test_a_draft_is_shown_then_saved_only_when_applied(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    wo, job_id = wo_job(tenant)
    line_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["lines"][0]["id"]
    monkeypatch.setattr(planning, "ask_json", lambda *a, **k: AiResult(True, model="t", data={"activities": [
        {"line_id": line_id, "start": d(2), "finish": d(40), "after_line_id": None}]}))
    out = tenant.post("/api/ai/planning/jobs/%d/draft" % job_id, json={"work_order_id": wo["id"], "start": d(0), "finish": d(60)}).json()
    assert out["available"] and out["activities"][0]["start"] == d(2)
    assert tenant.get("/api/jobs/%d/schedule" % job_id).json()["activities"] == []            # still nothing saved
    res = tenant.post("/api/ai/planning/jobs/%d/draft/apply" % job_id, json={"work_order_id": wo["id"], "activities": out["activities"]})
    assert res.status_code == 200, res.text
    a = res.json()["schedule"]["activities"]
    assert len(a) == 1 and a[0]["work_order_line_id"] == line_id and a[0]["planned_finish"] == d(40) and a[0]["code"] == "A10"
    again = tenant.post("/api/ai/planning/jobs/%d/draft/apply" % job_id, json={"work_order_id": wo["id"], "activities": out["activities"]})
    assert again.status_code == 409                                                           # already on the programme


def test_applying_refuses_an_empty_or_foreign_request(tenant, second_tenant):
    wo, job_id = wo_job(tenant)
    assert tenant.post("/api/ai/planning/jobs/%d/draft/apply" % job_id, json={"work_order_id": wo["id"], "activities": []}).status_code == 400
    assert second_tenant.post("/api/ai/planning/jobs/%d/draft/apply" % job_id, json={"work_order_id": wo["id"], "activities": [{"line_id": 1}]}).status_code == 404


# --- drafting from the BOQ: for this business the BOQ is the client's order -----------------------------------------

def boq_draft(tenant, job_id, **extra):
    return tenant.post("/api/ai/planning/jobs/%d/draft" % job_id, json={"boq": True, "start": d(0), "finish": d(60), **extra})


def test_a_project_with_only_a_boq_is_drafted_from_it(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setattr(planning, "ask_json", lambda *a, **k: AiResult(True, model="t", data={"activities": []}))
    jid, boq = make_boq(tenant)
    saved(tenant, boq)
    out = boq_draft(tenant, jid).json()
    assert out["available"] and out["boq_id"] == boq["id"]
    assert [a["name"] for a in out["activities"]] == ["Excavation in all types of soil", "M25 grade RCC in raft",
                                                      "Shuttering to raft edges", "Brick masonry in CM 1:6"]
    assert tenant.get("/api/jobs/%d/schedule" % jid).json()["activities"] == []              # nothing saved yet
    res = tenant.post("/api/ai/planning/jobs/%d/draft/apply" % jid, json={"boq": True, "activities": out["activities"]})
    assert res.status_code == 200, res.text
    acts = res.json()["schedule"]["activities"]
    assert len(acts) == 4 and acts[0]["planned_start"] == d(0) and acts[-1]["planned_finish"] == d(60)
    again = boq_draft(tenant, jid)
    assert again.status_code == 409 and "already on the programme" in again.json()["detail"]
    # drawing from the BOQ by item afterwards finds the same lines already placed
    assert tenant.post("/api/jobs/%d/schedule/from-boq" % jid, json={"start": d(0), "finish": d(60), "by": "item"}).status_code == 409


def test_a_boq_draft_takes_its_progress_from_the_book_when_a_client_order_was_made_from_the_boq(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setattr(planning, "ask_json", lambda *a, **k: AiResult(True, model="t", data={"activities": []}))
    jid, boq = make_boq(tenant)
    saved(tenant, boq)
    assert tenant.post("/api/boqs/%d/client-order" % boq["id"], json={}).status_code == 200
    out = boq_draft(tenant, jid).json()
    acts = tenant.post("/api/ai/planning/jobs/%d/draft/apply" % jid, json={"boq": True, "activities": out["activities"]}).json()["schedule"]["activities"]
    assert all(a["work_order_line_id"] for a in acts) and all(a["progress_from"] == "measurement book" for a in acts)


def test_drafting_from_a_boq_needs_one(tenant, second_tenant):
    job = tenant.post("/api/jobs", json={"name": "No BOQ site", "customer_name": "X"}).json()
    res = boq_draft(tenant, job["id"])
    assert res.status_code == 409 and "no BOQ" in res.json()["detail"]
    jid, boq = make_boq(second_tenant, "Rival site")
    saved(second_tenant, boq)
    assert boq_draft(tenant, jid).status_code == 404


def test_day_tasks_are_tied_to_real_activities_and_not_repeated(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-5), d(5))
    aid = s["activities"][0]["id"]
    tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Mark out grid", "date": d(0), "activity_id": aid})
    monkeypatch.setattr(planning, "ask_json", lambda *a, **k: AiResult(True, model="t", data={"tasks": [
        {"text": "Mark out grid", "activity_id": aid}, {"text": "Excavate bay 1", "activity_id": aid},
        {"text": "Order sand", "activity_id": 99999}, {"text": "  ", "activity_id": aid}]}))
    out = tenant.post("/api/ai/planning/jobs/%d/day-plan" % j["id"], json={}).json()
    assert [t["text"] for t in out["tasks"]] == ["Excavate bay 1", "Order sand"]
    assert out["tasks"][0]["activity_id"] == aid and out["tasks"][1]["activity_id"] is None
    assert len(tenant.get("/api/jobs/%d/schedule/day" % j["id"]).json()["tasks"]) == 1       # suggestions are not saved


def test_a_day_with_nothing_on_the_programme_does_not_call_the_model(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setattr(planning, "ask_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model call")))
    j = job(tenant)
    out = tenant.post("/api/ai/planning/jobs/%d/day-plan" % j["id"], json={}).json()
    assert out["tasks"] == [] and out["message"]
    assert tenant.post("/api/ai/planning/jobs/%d/day-plan" % j["id"], json={"on": "not a date"}).status_code == 400


def test_the_delay_findings_are_plain_code_and_work_with_no_key(tenant, unkeyed):
    j = job(tenant)
    act(tenant, j, "Excavation", d(-30), d(-10))
    s = act(tenant, j, "Raft", d(-5), d(20), depends_on_id=None)
    first = s["activities"][0]["id"]
    act(tenant, j, "Walls", d(3), d(30), depends_on_id=first)
    out = tenant.get("/api/ai/planning/jobs/%d/review" % j["id"]).json()
    text = " | ".join(f["text"] for f in out["findings"])
    assert out["available"] is False and out["summary"] == ""
    assert "Excavation should have finished" in text and "Walls starts in 3 days but" in text and "forecast to finish" in text
    assert out["findings"][0]["level"] == "stop"


def test_with_a_key_the_model_words_the_summary_from_the_findings(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    seen = {}
    monkeypatch.setattr(planning, "ask", lambda system, prompt, **k: seen.update(prompt=prompt) or AiResult(True, text="Excavation is late.", provider="groq", model="t"))
    j = job(tenant)
    act(tenant, j, "Excavation", d(-30), d(-10))
    out = tenant.get("/api/ai/planning/jobs/%d/review" % j["id"]).json()
    assert out["available"] and out["summary"] == "Excavation is late." and "Excavation should have finished" in seen["prompt"]


def test_a_project_with_no_programme_gets_a_plain_message_and_no_model_call(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setattr(planning, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model call")))
    j = job(tenant)
    assert "no programme" in tenant.get("/api/ai/planning/jobs/%d/review" % j["id"]).json()["message"]
    assert "no programme" in tenant.post("/api/ai/planning/jobs/%d/ask" % j["id"], json={"question": "Why?"}).json()["answer"]


def test_a_question_is_answered_from_the_plans_figures(tenant, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    seen = {}
    monkeypatch.setattr(planning, "ask", lambda system, prompt, **k: seen.update(prompt=prompt) or AiResult(True, text="Excavation.", provider="groq", model="t"))
    j = job(tenant)
    act(tenant, j, "Excavation", d(-30), d(-10))
    out = tenant.post("/api/ai/planning/jobs/%d/ask" % j["id"], json={"question": "What is late?"}).json()
    assert out["available"] and out["answer"] == "Excavation." and "Excavation" in seen["prompt"] and "What is late?" in seen["prompt"]
    assert tenant.post("/api/ai/planning/jobs/%d/ask" % j["id"], json={"question": " "}).status_code == 400


def test_another_company_cannot_reach_these(tenant, second_tenant, unkeyed):
    j = job(tenant)
    act(tenant, j, "Excavation", d(-30), d(-10))
    assert second_tenant.get("/api/ai/planning/jobs/%d/review" % j["id"]).status_code == 404
    assert second_tenant.post("/api/ai/planning/jobs/%d/ask" % j["id"], json={"question": "x"}).status_code == 404
    assert second_tenant.post("/api/ai/planning/jobs/%d/day-plan" % j["id"], json={}).status_code == 404
