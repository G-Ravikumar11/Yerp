"""Document expiry dates and downloadable templates.

HR decides which documents carry an expiry; the employee supplies the actual
date when uploading. Right-to-work and DBS checks lapse quietly, so the
watchlist is what stops a company finding out during an audit.
"""
import base64
from datetime import datetime, timedelta

import pytest

import main
from conftest import make_employee


def b64(n=512):
    return base64.b64encode(b"d" * n).decode()


def future(days=365):
    return (datetime.now().date() + timedelta(days=days)).strftime("%Y-%m-%d")


def past(days=30):
    return (datetime.now().date() - timedelta(days=days)).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _clear_limits():
    main.rate_limiter._hits.clear()
    yield


@pytest.fixture
def expiring_requirement(tenant):
    """A requirement HR has marked as carrying an expiry date."""
    tenant.get("/api/onboarding/requirements")     # seed defaults
    res = tenant.post("/api/onboarding/requirements", json={
        "name": "Right to work visa", "doc_type": "compliance",
        "requires_expiry": True, "expiry_reminder_days": 45,
    })
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def staffer(portal, client, tenant, expiring_requirement):
    emp = make_employee(tenant, password="EmpPass123")
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    return emp


def visa_request(portal, client):
    rows = portal.get("/api/employee/document-requests").json()["requests"]
    return next(r for r in rows if r["name"] == "Right to work visa")


# --- HR decides ------------------------------------------------------------

def test_hr_can_mark_a_document_as_expiring(expiring_requirement):
    assert expiring_requirement["requires_expiry"] is True
    assert expiring_requirement["expiry_reminder_days"] == 45


def test_expiry_reminder_is_validated(tenant):
    res = tenant.post("/api/onboarding/requirements", json={
        "name": "Some doc", "requires_expiry": True, "expiry_reminder_days": 400,
    })
    assert res.status_code == 400
    assert "between 0 and 365" in res.json()["detail"]


def test_requirement_defaults_to_no_expiry(tenant):
    row = tenant.post("/api/onboarding/requirements", json={"name": "Plain doc"}).json()
    assert row["requires_expiry"] is False


def test_the_flag_reaches_the_employees_request(portal, client, staffer):
    assert visa_request(portal, client)["requires_expiry"] is True


# --- employee supplies the date --------------------------------------------

def test_upload_is_refused_without_an_expiry_date(portal, client, staffer):
    req = visa_request(portal, client)
    res = portal.post(f"/api/employee/document-requests/{req['id']}/upload", json={
        "file_name": "visa.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    assert res.status_code == 400
    assert "needs an expiry date" in res.json()["detail"]


def test_an_already_expired_document_is_refused(portal, client, staffer):
    req = visa_request(portal, client)
    res = portal.post(f"/api/employee/document-requests/{req['id']}/upload", json={
        "file_name": "visa.pdf", "file_type": "application/pdf",
        "file_data": b64(), "expires_on": past(10),
    })
    assert res.status_code == 400
    assert "already expired" in res.json()["detail"]


def test_a_malformed_date_is_refused(portal, client, staffer):
    req = visa_request(portal, client)
    res = portal.post(f"/api/employee/document-requests/{req['id']}/upload", json={
        "file_name": "visa.pdf", "file_type": "application/pdf",
        "file_data": b64(), "expires_on": "next tuesday",
    })
    assert res.status_code == 400
    assert "YYYY-MM-DD" in res.json()["detail"]


def test_upload_with_a_valid_expiry_is_recorded(portal, client, tenant, staffer):
    req = visa_request(portal, client)
    expiry = future(400)
    res = portal.post(f"/api/employee/document-requests/{req['id']}/upload", json={
        "file_name": "visa.pdf", "file_type": "application/pdf",
        "file_data": b64(), "expires_on": expiry,
    })
    assert res.status_code == 200

    queue = tenant.get("/api/onboarding/document-queue?status=submitted").json()
    row = next(q for q in queue if q["id"] == req["id"])
    assert row["expires_on"] == expiry
    assert row["is_expired"] is False
    assert row["days_until_expiry"] > 300


def test_a_document_without_expiry_does_not_demand_one(portal, client, staffer):
    rows = portal.get("/api/employee/document-requests").json()["requests"]
    plain = next(r for r in rows if not r["requires_expiry"])
    res = portal.post(f"/api/employee/document-requests/{plain['id']}/upload", json={
        "file_name": "id.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    assert res.status_code == 200


# --- templates -------------------------------------------------------------

def test_hr_attaches_a_template_and_the_employee_can_fetch_it(portal, client, tenant, expiring_requirement, staffer):
    res = tenant.post(f"/api/onboarding/requirements/{expiring_requirement['id']}/template", json={
        "file_name": "visa-form.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    assert res.status_code == 200

    listed = tenant.get("/api/onboarding/requirements").json()
    row = next(r for r in listed if r["id"] == expiring_requirement["id"])
    assert row["has_template"] is True
    assert row["template_file_name"] == "visa-form.pdf"

    # The employee sees it exists and can download it.
    mine = visa_request(portal, client)
    assert mine["has_template"] is True
    got = client.get(f"/api/onboarding/requirements/{expiring_requirement['id']}/template")
    assert got.status_code == 200
    assert got.json()["file_name"] == "visa-form.pdf"


def test_template_files_are_validated(tenant, expiring_requirement):
    res = tenant.post(f"/api/onboarding/requirements/{expiring_requirement['id']}/template", json={
        "file_name": "payload.exe", "file_type": "application/octet-stream", "file_data": b64(),
    })
    assert res.status_code == 400


def test_template_can_be_removed(tenant, expiring_requirement):
    tenant.post(f"/api/onboarding/requirements/{expiring_requirement['id']}/template", json={
        "file_name": "f.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    assert tenant.delete(f"/api/onboarding/requirements/{expiring_requirement['id']}/template").status_code == 200
    listed = tenant.get("/api/onboarding/requirements").json()
    row = next(r for r in listed if r["id"] == expiring_requirement["id"])
    assert row["has_template"] is False


def test_missing_template_is_a_404(tenant, expiring_requirement):
    assert tenant.get(f"/api/onboarding/requirements/{expiring_requirement['id']}/template").status_code == 404


def test_templates_are_tenant_scoped(client, tenant, expiring_requirement):
    tenant.post(f"/api/onboarding/requirements/{expiring_requirement['id']}/template", json={
        "file_name": "f.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    client.post("/api/client/logout")
    client.post("/api/client/register", json={"email": "rival-doc@example.com", "password": "Passw0rdTest"})
    client.post("/api/client/login", json={"email": "rival-doc@example.com", "password": "Passw0rdTest"})
    assert client.get(f"/api/onboarding/requirements/{expiring_requirement['id']}/template").status_code == 404


# --- the watchlist ---------------------------------------------------------

def approve_with_expiry(portal, client, tenant, expiry):
    req = visa_request(portal, client)
    portal.post(f"/api/employee/document-requests/{req['id']}/upload", json={
        "file_name": "visa.pdf", "file_type": "application/pdf",
        "file_data": b64(), "expires_on": expiry,
    })
    tenant.post(f"/api/onboarding/document-requests/{req['id']}/review", json={"decision": "approve"})
    return req


def test_a_document_expiring_soon_is_flagged(portal, client, tenant, staffer):
    approve_with_expiry(portal, client, tenant, future(20))
    data = tenant.get("/api/onboarding/expiring-documents?days=60").json()
    assert data["expiring"], "a document 20 days out should be on the watchlist"
    assert data["expiring"][0]["employee_name"]
    assert data["expiring"][0]["days_until_expiry"] <= 20


def test_a_far_future_document_is_not_flagged(portal, client, tenant, staffer):
    approve_with_expiry(portal, client, tenant, future(400))
    data = tenant.get("/api/onboarding/expiring-documents?days=60").json()
    assert not data["expiring"]
    assert not data["expired"]


def test_expiry_state_is_derived_not_stored(portal, client, tenant, staffer):
    """Storing a flag would go stale the day after it was written."""
    req = approve_with_expiry(portal, client, tenant, future(10))
    row = next(r for r in tenant.get(f"/api/employees/{staffer['id']}/document-requests").json()
               if r["id"] == req["id"])
    assert row["expiring_soon"] is True      # inside the 45-day reminder window
    assert row["is_expired"] is False


def test_watchlist_is_tenant_scoped(portal, client, tenant, staffer):
    approve_with_expiry(portal, client, tenant, future(15))
    portal.post("/api/employee/auth/logout")
    client.post("/api/client/register", json={"email": "rival-exp@example.com", "password": "Passw0rdTest"})
    client.post("/api/client/login", json={"email": "rival-exp@example.com", "password": "Passw0rdTest"})
    data = client.get("/api/onboarding/expiring-documents").json()
    assert data["expired"] == [] and data["expiring"] == []
