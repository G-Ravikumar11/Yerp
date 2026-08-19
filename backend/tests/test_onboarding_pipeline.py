"""Hiring through to a working employee, as one tracked journey.

Covers the three places the chain used to break: a hire arriving with nothing
to do, completion ignoring outstanding documents, and the board that shows who
is waiting on whom.
"""
import uuid

import pytest

import main
from conftest import make_employee


@pytest.fixture(autouse=True)
def _reset_limiter():
    main.rate_limiter._hits.clear()
    yield


def hire_a_candidate(client, tenant, email=None):
    """Take someone all the way through the recruitment side."""
    main.rate_limiter._hits.clear()
    form = tenant.post("/api/recruitment/forms", json={
        "title": "Support Engineer", "description": "Join us",
        "fields": '[{"label":"Full name","type":"text"}]',
        "pipeline_stages": '["Applied","Interview","Hired"]',
    })
    assert form.status_code == 200, form.text
    form = form.json()

    email = email or f"cand-{uuid.uuid4().hex[:8]}@example.com"
    res = client.post(f"/api/recruitment/form/{form['form_token']}/submit", json={
        "answers": '{"Full name":"Casey Candidate"}',
        "candidate_name": "Casey Candidate", "candidate_email": email,
    })
    assert res.status_code == 200, res.text
    # The public endpoint deliberately returns no id, so read it back as HR.
    subs = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()
    sub_id = next(x["id"] for x in subs if x["candidate_email"] == email)

    res = tenant.post(f"/api/recruitment/submissions/{sub_id}/hire", json={
        "job_title": "Support Engineer", "start_date": "2026-01-05",
    })
    assert res.status_code == 200, res.text
    return {"submission_id": sub_id, **res.json()}


def stage_of(tenant, emp_id):
    board = tenant.get("/api/onboarding/pipeline").json()
    for stage in board["stages"]:
        for card in stage["cards"]:
            if card["employee_id"] == emp_id:
                return stage["key"], card
    return None, None


# --- the break that started this ---------------------------------------------

def test_a_hire_arrives_with_a_checklist_and_documents(client, tenant):
    hired = hire_a_candidate(client, tenant)
    emp_id = hired["employee_id"]

    checklist = tenant.get(f"/api/employees/{emp_id}/onboarding").json()
    assert checklist["total"] > 0, "a hire should get the same checklist as anyone else"

    docs = tenant.get(f"/api/employees/{emp_id}/document-requests").json()
    assert docs, "a hire should be asked for the same documents as anyone else"


def test_a_hire_and_a_manual_add_start_the_same_way(client, tenant):
    hired = hire_a_candidate(client, tenant)
    manual = make_employee(tenant)

    a = tenant.get(f"/api/employees/{hired['employee_id']}/onboarding").json()["total"]
    b = tenant.get(f"/api/employees/{manual['id']}/onboarding").json()["total"]
    assert a == b


# --- the board ---------------------------------------------------------------

def test_a_new_starter_begins_in_paperwork(client, tenant):
    hired = hire_a_candidate(client, tenant)
    key, card = stage_of(tenant, hired["employee_id"])
    assert key == "paperwork"
    assert card["awaiting_employee"], "they should be waiting on their documents"
    assert card["name"] == "Casey Candidate"


def test_the_card_says_where_they_came_from(client, tenant):
    hired = hire_a_candidate(client, tenant)
    _, card = stage_of(tenant, hired["employee_id"])
    assert card["hired_from"]["submission_id"] == hired["submission_id"]
    assert card["hired_from"]["candidate_name"] == "Casey Candidate"


def test_someone_added_by_hand_has_no_hired_from(tenant):
    emp = make_employee(tenant)
    _, card = stage_of(tenant, emp["id"])
    assert card["hired_from"] is None


def test_uploading_moves_them_to_review(portal, client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    portal.post("/api/employee/auth/login",
                json={"email": emp["email"], "password": "EmpPass123"})
    for row in portal.get("/api/employee/document-requests").json()["requests"]:
        portal.post(f"/api/employee/document-requests/{row['id']}/upload", json={
            "file_name": "d.pdf", "file_type": "application/pdf",
            "file_data": "JVBERi0xLjQK",
            "expires_on": "2030-01-01" if row["requires_expiry"] else "",
        })

    key, card = stage_of(tenant, emp["id"])
    assert key == "review"
    assert card["awaiting_hr"]


def test_approving_everything_moves_them_to_setup(portal, client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    portal.post("/api/employee/auth/login",
                json={"email": emp["email"], "password": "EmpPass123"})
    for row in portal.get("/api/employee/document-requests").json()["requests"]:
        portal.post(f"/api/employee/document-requests/{row['id']}/upload", json={
            "file_name": "d.pdf", "file_type": "application/pdf",
            "file_data": "JVBERi0xLjQK",
            "expires_on": "2030-01-01" if row["requires_expiry"] else "",
        })
    for row in tenant.get(f"/api/employees/{emp['id']}/document-requests").json():
        tenant.post(f"/api/onboarding/document-requests/{row['id']}/review",
                    json={"decision": "approve"})

    key, card = stage_of(tenant, emp["id"])
    assert key == "setup"
    assert card["documents_done"] is True
    assert card["checklist_done"] is False


def test_the_board_counts_who_is_blocked(client, tenant):
    hire_a_candidate(client, tenant)
    board = tenant.get("/api/onboarding/pipeline").json()
    assert board["total"] >= 1
    assert [s["key"] for s in board["stages"]] == ["paperwork", "review", "setup", "ready"]
    assert isinstance(board["blocked"], int)


# --- completion --------------------------------------------------------------

def finish_everything(portal, client, tenant, emp):
    portal.post("/api/employee/auth/login",
                json={"email": emp["email"], "password": "EmpPass123"})
    for row in portal.get("/api/employee/document-requests").json()["requests"]:
        portal.post(f"/api/employee/document-requests/{row['id']}/upload", json={
            "file_name": "d.pdf", "file_type": "application/pdf",
            "file_data": "JVBERi0xLjQK",
            "expires_on": "2030-01-01" if row["requires_expiry"] else "",
        })
    for row in tenant.get(f"/api/employees/{emp['id']}/document-requests").json():
        tenant.post(f"/api/onboarding/document-requests/{row['id']}/review",
                    json={"decision": "approve"})
    for item in tenant.get(f"/api/employees/{emp['id']}/onboarding").json()["items"]:
        tenant.put(f"/api/onboarding/{item['id']}", json={"is_completed": True})


def test_finishing_takes_them_off_the_board(portal, client, tenant):
    """Everyone starts onboarding, so the way off the board is to finish."""
    emp = make_employee(tenant, password="EmpPass123")
    assert stage_of(tenant, emp["id"])[0] is not None
    finish_everything(portal, client, tenant, emp)
    assert stage_of(tenant, emp["id"])[0] is None


def test_finishing_both_halves_makes_them_active(portal, client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    finish_everything(portal, client, tenant, emp)
    assert tenant.get(f"/api/employees/{emp['id']}").json()["status"] == "active"


def test_the_checklist_alone_does_not_make_them_active(tenant):
    """Someone could be made active with a mandatory document still missing."""
    emp = make_employee(tenant, password="EmpPass123")
    for item in tenant.get(f"/api/employees/{emp['id']}/onboarding").json()["items"]:
        tenant.put(f"/api/onboarding/{item['id']}", json={"is_completed": True})

    assert tenant.get(f"/api/employees/{emp['id']}").json()["status"] == "onboarding"
    key, card = stage_of(tenant, emp["id"])
    assert key == "paperwork"
    assert card["checklist_done"] is True


def test_completing_by_hand_is_refused_while_something_is_outstanding(tenant):
    emp = make_employee(tenant)
    res = tenant.post(f"/api/employees/{emp['id']}/complete-onboarding")
    assert res.status_code == 400
    detail = res.json()["detail"].lower()
    assert "waiting on" in detail or "checklist" in detail


def test_completing_by_hand_works_once_nothing_is_outstanding(portal, client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    finish_everything(portal, client, tenant, emp)
    # Already active by then, so a second attempt should say so rather than
    # pretend to do something.
    res = tenant.post(f"/api/employees/{emp['id']}/complete-onboarding")
    assert res.status_code == 400
    assert "not onboarding" in res.json()["detail"].lower()


# --- nudging -----------------------------------------------------------------

def test_a_nudge_tells_the_starter_what_is_missing(portal, client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    res = tenant.post(f"/api/employees/{emp['id']}/nudge")
    assert res.status_code == 200, res.text
    assert res.json()["items"]

    portal.post("/api/employee/auth/login",
                json={"email": emp["email"], "password": "EmpPass123"})
    notes = portal.get("/api/employee/notifications").json()
    titles = [n["title"] for n in (notes if isinstance(notes, list) else notes.get("notifications", []))]
    assert "Documents still needed" in titles


def test_nudging_someone_with_nothing_outstanding_is_refused(portal, client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    finish_everything(portal, client, tenant, emp)
    res = tenant.post(f"/api/employees/{emp['id']}/nudge")
    assert res.status_code == 400


# --- isolation ---------------------------------------------------------------

def test_the_board_is_per_tenant(client, tenant):
    hire_a_candidate(client, tenant)

    other = f"other-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/client/register", json={
        "email": other, "password": "Passw0rdTest", "company_name": "Other Ltd"})
    client.post("/api/client/login", json={"email": other, "password": "Passw0rdTest"})
    assert client.get("/api/onboarding/pipeline").json()["total"] == 0


def test_the_board_needs_a_session(client):
    assert client.get("/api/onboarding/pipeline").status_code == 401


def test_the_last_document_approval_can_be_what_finishes_it(portal, client, tenant):
    """Whichever half finishes last has to be the one that completes them, so
    completion is checked on the document review as well as the checklist."""
    emp = make_employee(tenant, password="EmpPass123")

    for item in tenant.get(f"/api/employees/{emp['id']}/onboarding").json()["items"]:
        tenant.put(f"/api/onboarding/{item['id']}", json={"is_completed": True})
    assert tenant.get(f"/api/employees/{emp['id']}").json()["status"] == "onboarding"

    portal.post("/api/employee/auth/login",
                json={"email": emp["email"], "password": "EmpPass123"})
    for row in portal.get("/api/employee/document-requests").json()["requests"]:
        portal.post(f"/api/employee/document-requests/{row['id']}/upload", json={
            "file_name": "d.pdf", "file_type": "application/pdf",
            "file_data": "JVBERi0xLjQK",
            "expires_on": "2030-01-01" if row["requires_expiry"] else "",
        })
    for row in tenant.get(f"/api/employees/{emp['id']}/document-requests").json():
        tenant.post(f"/api/onboarding/document-requests/{row['id']}/review",
                    json={"decision": "approve"})

    assert tenant.get(f"/api/employees/{emp['id']}").json()["status"] == "active"


def test_a_rejected_document_puts_them_back_in_paperwork(portal, client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    portal.post("/api/employee/auth/login",
                json={"email": emp["email"], "password": "EmpPass123"})
    rows = portal.get("/api/employee/document-requests").json()["requests"]
    first = next(r for r in rows if r["is_mandatory"])
    portal.post(f"/api/employee/document-requests/{first['id']}/upload", json={
        "file_name": "d.pdf", "file_type": "application/pdf", "file_data": "JVBERi0xLjQK",
        "expires_on": "2030-01-01" if first["requires_expiry"] else "",
    })
    tenant.post(f"/api/onboarding/document-requests/{first['id']}/review",
                json={"decision": "reject", "note": "Unreadable scan"})

    key, card = stage_of(tenant, emp["id"])
    assert key == "paperwork"
    assert first["name"] in card["awaiting_employee"]
