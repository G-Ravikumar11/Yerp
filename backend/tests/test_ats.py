"""Applicant tracking: requisitions, interviews, offers, analytics, job board."""
import base64

import pytest

import main
from conftest import make_employee


def b64(n=256):
    return base64.b64encode(b"x" * n).decode()


@pytest.fixture(autouse=True)
def _clear_limits():
    main.rate_limiter._hits.clear()
    yield


@pytest.fixture
def dept(tenant):
    return tenant.post("/api/departments", json={"name": "Engineering"}).json()


@pytest.fixture
def job(tenant, dept):
    manager = make_employee(tenant, level="L6", role="manager")
    res = tenant.post("/api/recruitment/jobs", json={
        "title": "Senior Backend Engineer", "department_id": dept["id"],
        "hiring_manager_id": manager["id"], "location": "London", "work_mode": "hybrid",
        "level": "L4", "salary_min": 65000, "salary_max": 85000, "openings": 2,
        "status": "open", "description": "Build things", "requirements": "Python",
    })
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def form(tenant, job):
    res = tenant.post("/api/recruitment/forms", json={
        "title": "Backend Application", "job_id": job["id"], "fields": "[]",
        "pipeline_stages": '["Applied","Screening","Interview","Offer","Hired"]',
    })
    assert res.status_code == 200, res.text
    return res.json()


def apply_once(client, token, name="Sam Patel", email="sam@example.com"):
    return client.post(f"/api/recruitment/form/{token}/submit", json={
        "answers": "{}", "candidate_name": name, "candidate_email": email,
        "documents": [{"doc_type": "resume", "file_name": "cv.pdf",
                       "file_type": "application/pdf", "file_data": b64()}],
    })


@pytest.fixture
def candidate(client, tenant, form):
    assert apply_once(client, form["form_token"]).status_code == 200
    return tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]


# --- requisitions ----------------------------------------------------------

def test_job_gets_a_reference_and_denormalised_names(job):
    assert job["reference"] == "JOB-0001"
    assert job["department_name"] == "Engineering"
    assert job["hiring_manager_name"]
    assert job["is_published"] is True     # opening a job publishes it


def test_job_references_do_not_collide_after_delete(tenant):
    a = tenant.post("/api/recruitment/jobs", json={"title": "A"}).json()
    b = tenant.post("/api/recruitment/jobs", json={"title": "B"}).json()
    assert tenant.delete(f"/api/recruitment/jobs/{b['id']}").status_code == 200
    c = tenant.post("/api/recruitment/jobs", json={"title": "C"}).json()
    assert c["reference"] != a["reference"]


@pytest.mark.parametrize("payload,fragment", [
    ({"title": "X", "salary_min": 90000, "salary_max": 50000}, "exceed"),
    ({"title": "X", "status": "whatever"}, "Status must be"),
    ({"title": "X", "work_mode": "astral"}, "Work mode must be"),
    ({"title": "X", "openings": 0}, "between 1 and 999"),
    ({"title": "X", "salary_min": -5}, "negative"),
    ({"title": "", "salary_min": 0}, "title is required"),
    ({"title": "X", "level": "L99"}, "Unknown level"),
])
def test_job_validation(tenant, payload, fragment):
    res = tenant.post("/api/recruitment/jobs", json=payload)
    assert res.status_code == 400
    assert fragment in res.json()["detail"]


def test_job_rejects_another_tenants_department(client, tenant, dept):
    client.post("/api/client/logout")
    client.post("/api/client/register", json={"email": "rival-job@example.com", "password": "Passw0rdTest"})
    client.post("/api/client/login", json={"email": "rival-job@example.com", "password": "Passw0rdTest"})
    res = client.post("/api/recruitment/jobs", json={"title": "X", "department_id": dept["id"]})
    assert res.status_code == 400
    assert "Department not found" in res.json()["detail"]


def test_job_with_attached_form_cannot_be_deleted(tenant, job, form):
    res = tenant.delete(f"/api/recruitment/jobs/{job['id']}")
    assert res.status_code == 409
    assert "application form" in res.json()["detail"]


def test_job_list_counts_applicants(client, tenant, job, form):
    apply_once(client, form["form_token"])
    listed = {j["id"]: j for j in tenant.get("/api/recruitment/jobs").json()}
    assert listed[job["id"]]["applicant_count"] == 1
    assert listed[job["id"]]["remaining_openings"] == 2


def test_closing_a_job_stamps_closed_at(tenant, job):
    res = tenant.put(f"/api/recruitment/jobs/{job['id']}", json={
        "title": job["title"], "status": "filled", "openings": 2,
    })
    assert res.status_code == 200
    assert res.json()["closed_at"]
    assert res.json()["is_published"] is False


# --- public job board ------------------------------------------------------

def test_public_board_lists_only_open_published_jobs(client, tenant, job, form):
    tenant.post("/api/recruitment/jobs", json={"title": "Secret draft role", "status": "draft"})
    me = tenant.get("/api/client/me").json()
    client.post("/api/client/logout")

    board = client.get(f"/api/public/jobs/{me['id']}")
    assert board.status_code == 200
    data = board.json()
    titles = [j["title"] for j in data["jobs"]]
    assert "Senior Backend Engineer" in titles
    assert "Secret draft role" not in titles
    listing = data["jobs"][0]
    assert listing["apply_token"] == form["form_token"]
    assert listing["salary_min"] == 65000


def test_public_board_hides_salary_when_asked(client, tenant, job):
    tenant.put(f"/api/recruitment/jobs/{job['id']}", json={
        "title": job["title"], "status": "open", "openings": 1,
        "salary_min": 65000, "salary_max": 85000, "show_salary": False,
    })
    me = tenant.get("/api/client/me").json()
    client.post("/api/client/logout")
    listing = client.get(f"/api/public/jobs/{me['id']}").json()["jobs"][0]
    assert listing["salary_min"] is None
    assert listing["salary_max"] is None


def test_public_board_unknown_company(client):
    assert client.get("/api/public/jobs/not-a-number").status_code == 404
    assert client.get("/api/public/jobs/999999").status_code == 404


# --- interviews ------------------------------------------------------------

def test_schedule_and_score_an_interview(tenant, candidate):
    emp = make_employee(tenant)
    res = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/interviews", json={
        "round_name": "Technical Screen", "scheduled_at": "2026-09-10 14:00",
        "duration_minutes": 60, "mode": "video", "interviewer_id": emp["id"],
    })
    assert res.status_code == 200, res.text
    iv = res.json()
    assert iv["status"] == "scheduled"
    assert iv["interviewer_name"]

    scored = tenant.put(f"/api/recruitment/interviews/{iv['id']}", json={
        "outcome": "pass", "score": 4, "feedback": "Strong",
    }).json()
    # Recording an outcome implies the interview happened.
    assert scored["status"] == "completed"
    assert scored["score"] == 4


def test_datetime_local_format_is_accepted(tenant, candidate):
    res = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/interviews",
                      json={"scheduled_at": "2026-09-10T14:00"})
    assert res.status_code == 200
    assert res.json()["scheduled_at"] == "2026-09-10 14:00"


def test_interviewer_double_booking_is_blocked(tenant, candidate):
    emp = make_employee(tenant)
    base = {"scheduled_at": "2026-09-10 14:00", "duration_minutes": 60, "interviewer_id": emp["id"]}
    assert tenant.post(f"/api/recruitment/submissions/{candidate['id']}/interviews", json=base).status_code == 200
    clash = dict(base, scheduled_at="2026-09-10 14:30")
    res = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/interviews", json=clash)
    assert res.status_code == 409
    assert "already has an interview" in res.json()["detail"]


@pytest.mark.parametrize("payload,code", [
    ({"scheduled_at": "next tuesday"}, 400),
    ({"scheduled_at": "2026-09-10 14:00", "mode": "telepathy"}, 400),
    ({"scheduled_at": "2026-09-10 14:00", "duration_minutes": 2}, 400),
])
def test_interview_validation(tenant, candidate, payload, code):
    assert tenant.post(f"/api/recruitment/submissions/{candidate['id']}/interviews",
                       json=payload).status_code == code


def test_interview_score_bounds(tenant, candidate):
    iv = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/interviews",
                     json={"scheduled_at": "2026-09-10 14:00"}).json()
    assert tenant.put(f"/api/recruitment/interviews/{iv['id']}", json={"score": 9}).status_code == 400
    assert tenant.put(f"/api/recruitment/interviews/{iv['id']}", json={"outcome": "maybe"}).status_code == 400


def test_upcoming_interviews_excludes_completed(tenant, candidate):
    from datetime import datetime, timedelta
    soon = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d 10:00")
    iv = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/interviews",
                     json={"scheduled_at": soon}).json()
    assert len(tenant.get("/api/recruitment/interviews/upcoming?days=30").json()) == 1
    tenant.put(f"/api/recruitment/interviews/{iv['id']}", json={"status": "completed"})
    assert tenant.get("/api/recruitment/interviews/upcoming?days=30").json() == []


# --- offers ----------------------------------------------------------------

def test_offer_lifecycle(tenant, candidate):
    res = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/offers", json={
        "job_title": "Senior Backend Engineer", "level": "L4",
        "salary": 78000, "start_date": "2026-10-01", "expires_on": "2026-09-20",
    })
    assert res.status_code == 200, res.text
    offer = res.json()
    assert offer["status"] == "draft"

    sent = tenant.put(f"/api/recruitment/offers/{offer['id']}", json={"status": "sent"}).json()
    assert sent["sent_at"]
    accepted = tenant.put(f"/api/recruitment/offers/{offer['id']}", json={"status": "accepted"}).json()
    assert accepted["responded_at"]


def test_only_one_live_offer_at_a_time(tenant, candidate):
    tenant.post(f"/api/recruitment/submissions/{candidate['id']}/offers", json={"salary": 1000})
    res = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/offers", json={"salary": 2000})
    assert res.status_code == 409
    # Withdrawing frees the slot.
    offer_id = tenant.get(f"/api/recruitment/submissions/{candidate['id']}/offers").json()[0]["id"]
    tenant.put(f"/api/recruitment/offers/{offer_id}", json={"status": "withdrawn"})
    assert tenant.post(f"/api/recruitment/submissions/{candidate['id']}/offers",
                       json={"salary": 2000}).status_code == 200


def test_offer_cannot_expire_after_it_starts(tenant, candidate):
    res = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/offers", json={
        "salary": 100, "start_date": "2026-01-01", "expires_on": "2026-06-01",
    })
    assert res.status_code == 400
    assert "expire after the start date" in res.json()["detail"]


# --- rejection and hiring --------------------------------------------------

def test_rejection_requires_a_reason(tenant, candidate):
    assert tenant.post(f"/api/recruitment/submissions/{candidate['id']}/reject", json={}).status_code == 400
    res = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/reject",
                      json={"reason": "Not enough depth"})
    assert res.status_code == 200
    listed = tenant.get(f"/api/recruitment/forms/{candidate['form_id']}/submissions").json()[0]
    assert listed["status"] == "rejected"
    assert listed["rejected_reason"] == "Not enough depth"


def test_rejected_candidate_must_be_reopened_before_hiring(tenant, candidate):
    tenant.post(f"/api/recruitment/submissions/{candidate['id']}/reject", json={"reason": "No"})
    res = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/hire", json={})
    assert res.status_code == 409
    assert "Reopen" in res.json()["detail"]

    assert tenant.post(f"/api/recruitment/submissions/{candidate['id']}/reopen").status_code == 200
    assert tenant.post(f"/api/recruitment/submissions/{candidate['id']}/hire", json={}).status_code == 200


def test_hiring_moves_candidate_to_the_final_stage(tenant, candidate):
    tenant.post(f"/api/recruitment/submissions/{candidate['id']}/hire", json={"job_title": "Engineer"})
    listed = tenant.get(f"/api/recruitment/forms/{candidate['form_id']}/submissions").json()[0]
    assert listed["current_stage"] == "Hired"


# --- candidate email -------------------------------------------------------

@pytest.mark.parametrize("template,fragment", [
    ("interview", "Interview invitation"),
    ("offer", "Offer of employment"),
    ("rejection", "Your application for"),
])
def test_email_templates_render(tenant, candidate, template, fragment):
    tenant.post(f"/api/recruitment/submissions/{candidate['id']}/interviews",
                json={"scheduled_at": "2026-09-10 14:00"})
    tenant.post(f"/api/recruitment/submissions/{candidate['id']}/offers", json={"salary": 50000})
    res = tenant.get(f"/api/recruitment/submissions/{candidate['id']}/email-preview?template={template}")
    assert res.status_code == 200
    body = res.json()
    assert fragment in body["subject"]
    assert body["to"] == "sam@example.com"
    assert "Sam" in body["body"]


def test_email_requires_an_address(client, tenant, form):
    client.post(f"/api/recruitment/form/{form['form_token']}/submit",
                json={"answers": "{}", "candidate_name": "No Email"})
    sub = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]
    res = tenant.post(f"/api/recruitment/submissions/{sub['id']}/email", json={"template": "rejection"})
    assert res.status_code == 400


# --- analytics and talent pool ---------------------------------------------

def test_analytics_reflect_the_pipeline(client, tenant, form, candidate):
    apply_once(client, form["form_token"], name="Omar", email="omar@example.com")
    subs = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()
    other = [s for s in subs if s["id"] != candidate["id"]][0]
    tenant.put(f"/api/recruitment/submissions/{other['id']}/stage", json={"stage": "Interview"})
    tenant.post(f"/api/recruitment/submissions/{candidate['id']}/hire", json={})

    a = tenant.get("/api/recruitment/analytics").json()
    assert a["total_applicants"] == 2
    assert a["hired"] == 1
    assert a["in_progress"] == 1
    assert a["conversion_rate"] == 50.0
    assert a["open_jobs"] == 1
    assert a["by_stage"]["Interview"] == 1


def test_analytics_offer_acceptance_rate(tenant, candidate):
    offer = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/offers",
                        json={"salary": 1000}).json()
    tenant.put(f"/api/recruitment/offers/{offer['id']}", json={"status": "sent"})
    tenant.put(f"/api/recruitment/offers/{offer['id']}", json={"status": "accepted"})
    a = tenant.get("/api/recruitment/analytics").json()
    assert a["offers_sent"] == 1
    assert a["offer_acceptance_rate"] == 100.0


def test_talent_pool_search_and_duplicate_detection(client, tenant, form, candidate):
    # Same person applies twice; the pool should say so.
    apply_once(client, form["form_token"], name="Sam Patel", email="sam@example.com")
    pool = tenant.get("/api/recruitment/talent-pool").json()
    assert all(c["applications"] == 2 for c in pool if c["candidate_email"] == "sam@example.com")

    found = tenant.get("/api/recruitment/talent-pool?q=sam").json()
    assert found and all("sam" in c["candidate_email"].lower() for c in found)
    assert tenant.get("/api/recruitment/talent-pool?q=nobodyhere").json() == []


# --- isolation -------------------------------------------------------------

def test_ats_records_are_tenant_scoped(client, tenant, job, candidate):
    iv = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/interviews",
                     json={"scheduled_at": "2026-09-10 14:00"}).json()
    offer = tenant.post(f"/api/recruitment/submissions/{candidate['id']}/offers",
                        json={"salary": 100}).json()

    client.post("/api/client/logout")
    client.post("/api/client/register", json={"email": "spy@example.com", "password": "Passw0rdTest"})
    client.post("/api/client/login", json={"email": "spy@example.com", "password": "Passw0rdTest"})

    assert client.get(f"/api/recruitment/jobs/{job['id']}").status_code == 404
    assert client.put(f"/api/recruitment/interviews/{iv['id']}", json={"score": 1}).status_code == 404
    assert client.put(f"/api/recruitment/offers/{offer['id']}", json={"status": "sent"}).status_code == 404
    assert client.get(f"/api/recruitment/submissions/{candidate['id']}/interviews").status_code == 404
    assert client.get("/api/recruitment/jobs").json() == []
    assert client.get("/api/recruitment/talent-pool").json() == []
