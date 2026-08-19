"""HR decides what new starters must provide; the employee uploads it from
their own portal; HR reviews it. This covers that round trip."""
import base64

import pytest

import main
from conftest import make_employee


def b64(n=512):
    return base64.b64encode(b"d" * n).decode()


@pytest.fixture(autouse=True)
def _clear_limits():
    main.rate_limiter._hits.clear()
    yield


# --- requirements -----------------------------------------------------------

def test_defaults_are_seeded_on_first_read(tenant):
    rows = tenant.get("/api/onboarding/requirements").json()
    assert rows, "HR should see a starting list rather than an empty screen"
    names = [r["name"] for r in rows]
    assert "Photo ID" in names
    # Reading again must not duplicate them.
    assert len(tenant.get("/api/onboarding/requirements").json()) == len(rows)


def test_create_and_update_a_requirement(tenant):
    tenant.get("/api/onboarding/requirements")
    created = tenant.post("/api/onboarding/requirements", json={
        "name": "DBS check", "description": "Enhanced disclosure",
        "doc_type": "compliance", "due_days": 30, "is_mandatory": True,
    })
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["due_days"] == 30

    updated = tenant.put(f"/api/onboarding/requirements/{row['id']}", json={
        "name": "DBS check", "due_days": 45, "is_mandatory": False,
    })
    assert updated.status_code == 200
    assert updated.json()["due_days"] == 45
    assert updated.json()["is_mandatory"] is False


@pytest.mark.parametrize("payload,fragment", [
    ({"name": "  "}, "name is required"),
    ({"name": "X", "due_days": 400}, "between 0 and 365"),
    ({"name": "X", "applies_to": "sideways"}, "all, department or level"),
    ({"name": "X", "applies_to": "department"}, "Choose a department"),
    ({"name": "X", "applies_to": "level"}, "Choose a level"),
    ({"name": "X", "level": "L99"}, "Unknown level"),
])
def test_requirement_validation(tenant, payload, fragment):
    res = tenant.post("/api/onboarding/requirements", json=payload)
    assert res.status_code == 400
    assert fragment in res.json()["detail"]


def test_duplicate_requirement_name_is_rejected(tenant):
    tenant.post("/api/onboarding/requirements", json={"name": "Passport"})
    res = tenant.post("/api/onboarding/requirements", json={"name": "passport"})
    assert res.status_code == 400
    assert "already on the list" in res.json()["detail"]


# --- assignment -------------------------------------------------------------

def test_new_starter_is_asked_for_the_documents(tenant):
    emp = make_employee(tenant, start_date="2026-01-01")
    rows = tenant.get(f"/api/employees/{emp['id']}/document-requests").json()
    assert rows, "a new starter should be asked for the default documents"
    photo = next(r for r in rows if r["name"] == "Photo ID")
    assert photo["status"] == "pending"
    # Due dates are computed from the start date, not the creation date.
    assert photo["due_date"] == "2026-01-04"   # 3 days after start


def test_scoped_requirements_only_reach_the_right_people(tenant):
    dept = tenant.post("/api/departments", json={"name": "Clinical"}).json()
    tenant.get("/api/onboarding/requirements")
    tenant.post("/api/onboarding/requirements", json={
        "name": "Nursing registration", "applies_to": "department",
        "department_id": dept["id"],
    })
    inside = make_employee(tenant, department_id=dept["id"])
    outside = make_employee(tenant)

    names_in = {r["name"] for r in tenant.get(f"/api/employees/{inside['id']}/document-requests").json()}
    names_out = {r["name"] for r in tenant.get(f"/api/employees/{outside['id']}/document-requests").json()}
    assert "Nursing registration" in names_in
    assert "Nursing registration" not in names_out


def test_sync_applies_new_rules_to_existing_staff(tenant):
    emp = make_employee(tenant)
    before = len(tenant.get(f"/api/employees/{emp['id']}/document-requests").json())
    tenant.post("/api/onboarding/requirements", json={"name": "Emergency contact form"})

    res = tenant.post(f"/api/employees/{emp['id']}/document-requests/sync")
    assert res.status_code == 200
    assert res.json()["added"] == 1
    after = tenant.get(f"/api/employees/{emp['id']}/document-requests").json()
    assert len(after) == before + 1
    # Running it again is a no-op rather than a duplicate.
    assert tenant.post(f"/api/employees/{emp['id']}/document-requests/sync").json()["added"] == 0


# --- the employee side ------------------------------------------------------

@pytest.fixture
def staffer(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    client.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    return emp


def test_employee_sees_what_is_required(client, staffer):
    data = client.get("/api/employee/document-requests").json()
    assert data["outstanding"] > 0
    assert data["complete"] is False
    assert data["limits"]["max_mb"] >= 1
    assert ".pdf" in data["limits"]["allowed"]


def test_employee_upload_reaches_the_hr_queue(client, tenant, staffer):
    """The point of the feature: what the employee sends lands in HR's queue."""
    req = client.get("/api/employee/document-requests").json()["requests"][0]
    res = client.post(f"/api/employee/document-requests/{req['id']}/upload", json={
        "file_name": "passport.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "submitted"

    queue = tenant.get("/api/onboarding/document-queue?status=submitted").json()
    match = [q for q in queue if q["id"] == req["id"]]
    assert match, "the submission should appear in the HR review queue"
    assert match[0]["file_name"] == "passport.pdf"
    assert match[0]["employee_name"]


@pytest.mark.parametrize("payload,code", [
    ({"file_name": "virus.exe", "file_type": "application/octet-stream", "file_data": "QUJD"}, 400),
    ({"file_name": "huge.pdf", "file_type": "application/pdf", "file_data": base64.b64encode(b"x" * 6 * 1024 * 1024).decode()}, 413),
    ({"file_name": "empty.pdf", "file_type": "application/pdf", "file_data": ""}, 400),
])
def test_employee_upload_is_validated(client, staffer, payload, code):
    req = client.get("/api/employee/document-requests").json()["requests"][0]
    assert client.post(f"/api/employee/document-requests/{req['id']}/upload", json=payload).status_code == code


def test_employee_cannot_upload_against_someone_elses_request(client, tenant, staffer):
    other = make_employee(tenant, password="OtherPass123")
    other_req = tenant.get(f"/api/employees/{other['id']}/document-requests").json()[0]
    res = client.post(f"/api/employee/document-requests/{other_req['id']}/upload", json={
        "file_name": "x.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    assert res.status_code == 404


# --- review -----------------------------------------------------------------

def submit_first(client, tenant, staffer):
    req = client.get("/api/employee/document-requests").json()["requests"][0]
    client.post(f"/api/employee/document-requests/{req['id']}/upload", json={
        "file_name": "id.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    return req


def test_approve_a_submission(client, tenant, staffer):
    req = submit_first(client, tenant, staffer)
    res = tenant.post(f"/api/onboarding/document-requests/{req['id']}/review",
                      json={"decision": "approve"})
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    assert res.json()["reviewed_at"]


def test_rejection_requires_a_reason_and_allows_resubmission(client, tenant, staffer):
    req = submit_first(client, tenant, staffer)
    assert tenant.post(f"/api/onboarding/document-requests/{req['id']}/review",
                       json={"decision": "reject"}).status_code == 400

    res = tenant.post(f"/api/onboarding/document-requests/{req['id']}/review",
                      json={"decision": "reject", "note": "Photo is unreadable"})
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"

    # The employee sees why and can send a replacement.
    mine = client.get("/api/employee/document-requests").json()["requests"]
    rejected = next(r for r in mine if r["id"] == req["id"])
    assert rejected["review_note"] == "Photo is unreadable"

    again = client.post(f"/api/employee/document-requests/{req['id']}/upload", json={
        "file_name": "id2.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    assert again.status_code == 200
    assert again.json()["status"] == "submitted"


def test_approved_document_cannot_be_overwritten(client, tenant, staffer):
    req = submit_first(client, tenant, staffer)
    tenant.post(f"/api/onboarding/document-requests/{req['id']}/review", json={"decision": "approve"})
    res = client.post(f"/api/employee/document-requests/{req['id']}/upload", json={
        "file_name": "swap.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    assert res.status_code == 409


def test_reviewing_something_never_submitted_is_refused(tenant):
    emp = make_employee(tenant)
    req = tenant.get(f"/api/employees/{emp['id']}/document-requests").json()[0]
    res = tenant.post(f"/api/onboarding/document-requests/{req['id']}/review",
                      json={"decision": "approve"})
    assert res.status_code == 400


def test_hr_can_download_what_was_submitted(client, tenant, staffer):
    req = submit_first(client, tenant, staffer)
    res = tenant.get(f"/api/onboarding/document-requests/{req['id']}/file")
    assert res.status_code == 200
    assert res.json()["file_name"] == "id.pdf"
    assert res.json()["file_data"]


def test_profile_shows_outstanding_paperwork(tenant):
    emp = make_employee(tenant)
    d = tenant.get(f"/api/employees/{emp['id']}").json()
    assert d["documents_outstanding"] > 0
    assert d["document_requests"]


# --- isolation --------------------------------------------------------------

def test_document_records_are_tenant_scoped(client, tenant, staffer):
    req = submit_first(client, tenant, staffer)
    client.post("/api/employee/auth/logout")
    client.post("/api/client/register", json={"email": "prying@example.com", "password": "Passw0rdTest"})
    client.post("/api/client/login", json={"email": "prying@example.com", "password": "Passw0rdTest"})

    assert client.get(f"/api/onboarding/document-requests/{req['id']}/file").status_code == 404
    assert client.post(f"/api/onboarding/document-requests/{req['id']}/review",
                       json={"decision": "approve"}).status_code == 404
    assert client.get("/api/onboarding/document-queue").json() == []
