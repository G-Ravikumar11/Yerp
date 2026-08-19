"""HR changing a requirement must reach the people it was already assigned to.

The existing expiry tests all mark a document as expiring before anyone is
hired. In real use it is the other way round: staff are already on the system
when HR decides a document needs an expiry date.
"""
import pytest

import main
from conftest import make_employee


@pytest.fixture(autouse=True)
def _reset_limiter():
    main.rate_limiter._hits.clear()
    yield


@pytest.fixture
def hired_first(client, tenant):
    """A requirement that does not expire, and someone already holding it."""
    tenant.get("/api/onboarding/requirements")
    req = tenant.post("/api/onboarding/requirements", json={
        "name": "Right to work visa", "doc_type": "compliance",
        "requires_expiry": False,
    }).json()
    emp = make_employee(tenant, password="EmpPass123")
    return {"requirement": req, "employee": emp}


def _their_request(tenant, emp_id, name="Right to work visa"):
    rows = tenant.get(f"/api/employees/{emp_id}/document-requests").json()
    return next(r for r in rows if r["name"] == name)


def test_turning_on_expiry_reaches_staff_already_assigned(tenant, hired_first):
    req = hired_first["requirement"]
    emp = hired_first["employee"]
    assert _their_request(tenant, emp["id"])["requires_expiry"] is False

    res = tenant.put(f"/api/onboarding/requirements/{req['id']}", json={
        **req, "requires_expiry": True, "expiry_reminder_days": 30,
    })
    assert res.status_code == 200, res.text

    assert _their_request(tenant, emp["id"])["requires_expiry"] is True


def test_the_employee_is_then_asked_for_a_date(portal, client, tenant, hired_first):
    req = hired_first["requirement"]
    emp = hired_first["employee"]
    res = tenant.put(f"/api/onboarding/requirements/{req['id']}", json={
        **req, "requires_expiry": True, "expiry_reminder_days": 30,
    })
    assert res.status_code == 200, res.text

    portal.post("/api/employee/auth/login", json={
        "email": emp["email"], "password": "EmpPass123"})
    rows = portal.get("/api/employee/document-requests").json()["requests"]
    mine = next(r for r in rows if r["name"] == "Right to work visa")
    assert mine["requires_expiry"] is True

    # Uploading without one is refused, which is what prompts the portal to ask.
    res = portal.post(f"/api/employee/document-requests/{mine['id']}/upload", json={
        "file_name": "visa.pdf", "file_type": "application/pdf",
        "file_data": "JVBERi0xLjQK", "expires_on": "",
    })
    assert res.status_code == 400
    assert "expiry date" in res.json()["detail"].lower()


def test_the_date_is_stored_and_surfaces_to_hr(portal, client, tenant, hired_first):
    req = hired_first["requirement"]
    emp = hired_first["employee"]
    res = tenant.put(f"/api/onboarding/requirements/{req['id']}", json={
        **req, "requires_expiry": True, "expiry_reminder_days": 365,
    })
    assert res.status_code == 200, res.text

    portal.post("/api/employee/auth/login", json={
        "email": emp["email"], "password": "EmpPass123"})
    rows = portal.get("/api/employee/document-requests").json()["requests"]
    mine = next(r for r in rows if r["name"] == "Right to work visa")

    res = portal.post(f"/api/employee/document-requests/{mine['id']}/upload", json={
        "file_name": "visa.pdf", "file_type": "application/pdf",
        "file_data": "JVBERi0xLjQK", "expires_on": "2027-06-30",
    })
    assert res.status_code == 200, res.text

    stored = _their_request(tenant, emp["id"])
    assert stored["expires_on"] == "2027-06-30"

    # HR approves it, and it reaches the expiring-documents panel.
    tenant.post(f"/api/onboarding/document-requests/{mine['id']}/review",
                json={"decision": "approve"})
    panel = tenant.get("/api/onboarding/expiring-documents?days=3650").json()
    names = [d["name"] for d in panel["expiring"] + panel["expired"]]
    assert "Right to work visa" in names


def test_turning_expiry_off_again_also_reaches_them(tenant, hired_first):
    req = hired_first["requirement"]
    emp = hired_first["employee"]
    assert tenant.put(f"/api/onboarding/requirements/{req['id']}",
                      json={**req, "requires_expiry": True}).status_code == 200
    assert _their_request(tenant, emp["id"])["requires_expiry"] is True

    assert tenant.put(f"/api/onboarding/requirements/{req['id']}",
                      json={**req, "requires_expiry": False}).status_code == 200
    assert _their_request(tenant, emp["id"])["requires_expiry"] is False


def test_renaming_a_requirement_reaches_them_too(tenant, hired_first):
    req = hired_first["requirement"]
    emp = hired_first["employee"]
    assert tenant.put(f"/api/onboarding/requirements/{req['id']}",
                      json={**req, "name": "Visa (right to work)"}).status_code == 200
    assert _their_request(tenant, emp["id"], "Visa (right to work)")


def test_a_document_already_submitted_is_left_alone(portal, client, tenant, hired_first):
    """Changing the rule must not reopen something already handed in."""
    req = hired_first["requirement"]
    emp = hired_first["employee"]

    portal.post("/api/employee/auth/login", json={
        "email": emp["email"], "password": "EmpPass123"})
    rows = portal.get("/api/employee/document-requests").json()["requests"]
    mine = next(r for r in rows if r["name"] == "Right to work visa")
    portal.post(f"/api/employee/document-requests/{mine['id']}/upload", json={
        "file_name": "visa.pdf", "file_type": "application/pdf",
        "file_data": "JVBERi0xLjQK",
    })
    tenant.post(f"/api/onboarding/document-requests/{mine['id']}/review",
                json={"decision": "approve"})

    assert tenant.put(f"/api/onboarding/requirements/{req['id']}",
                      json={**req, "requires_expiry": True}).status_code == 200

    after = _their_request(tenant, emp["id"])
    assert after["status"] == "approved"
    # It keeps the terms it was accepted under; HR would have to ask again.
    assert after["requires_expiry"] is False


def test_a_date_is_not_kept_for_a_document_that_does_not_expire(portal, client, tenant, hired_first):
    """Defence in depth for the portal bug where a date left over from a failed
    upload rode along on the next document."""
    emp = hired_first["employee"]
    portal.post("/api/employee/auth/login", json={
        "email": emp["email"], "password": "EmpPass123"})
    rows = portal.get("/api/employee/document-requests").json()["requests"]
    plain = next(r for r in rows if not r["requires_expiry"])

    res = portal.post(f"/api/employee/document-requests/{plain['id']}/upload", json={
        "file_name": "id.png", "file_type": "image/png",
        "file_data": "aGVsbG8=", "expires_on": "2030-12-31",
    })
    assert res.status_code == 200, res.text

    after = next(r for r in portal.get("/api/employee/document-requests").json()["requests"]
                 if r["id"] == plain["id"])
    assert after["expires_on"] == ""
