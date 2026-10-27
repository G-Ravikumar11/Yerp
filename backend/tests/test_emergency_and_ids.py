"""Onboarding: an emergency contact is the one thing that is compulsory. Gender and the Aadhaar, PAN and UAN numbers are
optional and are given by the employee in their own portal, with their documents uploaded there too."""
import base64
import uuid
from datetime import datetime

import pytest

import main
from app import models
from tests.conftest import make_employee


@pytest.fixture(autouse=True)
def _rule_on(monkeypatch):
    monkeypatch.setenv("REQUIRE_EMERGENCY_CONTACT", "1")
    main.rate_limiter._hits.clear()


def new(tenant, **kw):
    body = {"first_name": "Asha", "last_name": "Rao" + uuid.uuid4().hex[:4], "email": f"a-{uuid.uuid4().hex[:8]}@example.com"}
    body.update(kw)
    return tenant.post("/api/employees", json=body)


def without_contact(monkeypatch, **kw):
    """Somebody who came in some other way (recruitment, an older record) and has no emergency contact yet."""
    monkeypatch.setenv("REQUIRE_EMERGENCY_CONTACT", "0")
    try:
        return make_employee(kw.pop("tenant"), **kw)
    finally:
        monkeypatch.setenv("REQUIRE_EMERGENCY_CONTACT", "1")


def sign_in(portal, e, password="Given1Pass"):
    r = portal.post("/api/employee/auth/login", json={"email": e["email"], "password": password})
    assert r.status_code == 200, r.text


def test_an_employee_cannot_be_added_without_an_emergency_contact(tenant):
    assert new(tenant).status_code == 400
    r = new(tenant, emergency_contact="Ravi Rao")
    assert r.status_code == 400 and "phone number" in r.json()["detail"]
    r = new(tenant, emergency_phone="9876543210")
    assert r.status_code == 400 and "name" in r.json()["detail"]
    assert new(tenant, emergency_contact="Ravi Rao", emergency_phone="98765 43210").status_code == 200


def test_nothing_else_is_compulsory(tenant):
    r = new(tenant, emergency_contact="Ravi Rao", emergency_phone="9876543210")
    assert r.status_code == 200
    d = tenant.get(f"/api/employees/{r.json()['id']}").json()
    assert d["gender"] == "" and d["pan_no"] == "" and d["uan_no"] == "" and d["aadhaar_masked"] == ""
    docs = tenant.get(f"/api/employees/{r.json()['id']}/document-requests").json()
    assert {"Aadhaar card", "PAN card", "UAN (EPF) details"} <= {x["name"] for x in docs}
    assert not any(x["is_mandatory"] for x in docs)


def test_gender_is_optional_and_checked(tenant):
    assert new(tenant, emergency_contact="R", emergency_phone="9876543210", gender="female").json()["id"]
    assert new(tenant, emergency_contact="R", emergency_phone="9876543210", gender="robot").status_code == 400
    e = new(tenant, emergency_contact="Ravi", emergency_phone="9876543210", gender="Female").json()
    assert tenant.get(f"/api/employees/{e['id']}").json()["gender"] == "Female"
    assert tenant.put(f"/api/employees/{e['id']}", json={"gender": "Other"}).status_code == 200
    assert tenant.put(f"/api/employees/{e['id']}", json={"gender": "x"}).status_code == 400


def test_somebody_still_onboarding_is_held_up_until_the_contact_is_given(tenant, portal, monkeypatch):
    e = without_contact(monkeypatch, tenant=tenant, password="Given1Pass")
    snap = tenant.get("/api/onboarding/pipeline").json()
    card = next(c for st in snap["stages"] for c in st["cards"] if c["employee_id"] == e["id"])
    assert "Emergency contact" in card["awaiting_employee"]
    refused = tenant.post(f"/api/employees/{e['id']}/complete-onboarding")
    assert refused.status_code == 400 and "Emergency contact" in refused.json()["detail"]
    sign_in(portal, e)
    assert portal.put("/api/employee/profile/details", json={"emergency_contact": "Ravi", "emergency_phone": "9876543210"}).status_code == 200
    card = next(c for st in tenant.get("/api/onboarding/pipeline").json()["stages"] for c in st["cards"] if c["employee_id"] == e["id"])
    assert "Emergency contact" not in card["awaiting_employee"]


def test_the_employee_gives_their_own_numbers_and_they_are_checked(tenant, portal, monkeypatch):
    e = without_contact(monkeypatch, tenant=tenant, password="Given1Pass")
    sign_in(portal, e)
    put = lambda **b: portal.put("/api/employee/profile/details", json=b)  # noqa: E731
    assert put(emergency_contact="Ravi").status_code == 400                       # a name alone is no contact
    assert put(emergency_contact="Ravi", emergency_phone="12").status_code == 400
    assert put(aadhaar_no="1234 5678 9012").status_code == 400                    # may not start with 0 or 1
    assert put(aadhaar_no="12345").status_code == 400
    assert put(pan_no="abcde12345").status_code == 400
    assert put(uan_no="1234").status_code == 400
    assert put().status_code == 400
    ok = put(gender="male", aadhaar_no="2345 6789 0123", pan_no="abcde1234f", uan_no="1001 2345 6789")
    assert ok.status_code == 200, ok.text
    me = portal.get("/api/employee/profile").json()
    assert (me["gender"], me["aadhaar_no"], me["pan_no"], me["uan_no"]) == ("Male", "234567890123", "ABCDE1234F", "100123456789")
    # HR sees Aadhaar masked, and PAN and UAN in full.
    d = tenant.get(f"/api/employees/{e['id']}").json()
    assert d["aadhaar_masked"] == "XXXX XXXX 0123" and "234567890123" not in str(d)
    assert d["pan_no"] == "ABCDE1234F" and d["uan_no"] == "100123456789"


def test_a_contact_cannot_be_taken_away_and_only_the_session_decides_whose(tenant, portal, monkeypatch):
    a, b = without_contact(monkeypatch, tenant=tenant, password="Given1Pass"), without_contact(monkeypatch, tenant=tenant, password="Given1Pass")
    sign_in(portal, a)
    portal.put("/api/employee/profile/details", json={"emergency_contact": "Ravi", "emergency_phone": "9876543210"})
    assert portal.put("/api/employee/profile/details", json={"emergency_contact": "", "emergency_phone": ""}).status_code == 400
    portal.put("/api/employee/profile/details", json={"pan_no": "ABCDE1234F", "employee_id": b["id"], "id": b["id"]})
    assert tenant.get(f"/api/employees/{b['id']}").json()["pan_no"] == ""
    assert tenant.get(f"/api/employees/{a['id']}").json()["pan_no"] == "ABCDE1234F"
    from fastapi.testclient import TestClient
    with TestClient(main.app) as nobody:
        assert nobody.put("/api/employee/profile/details", json={"pan_no": "ABCDE1234F"}).status_code == 401


def test_the_employee_uploads_their_own_aadhaar_as_a_photo_or_a_pdf(tenant, portal, monkeypatch):
    e = without_contact(monkeypatch, tenant=tenant, password="Given1Pass")
    sign_in(portal, e)
    reqs = portal.get("/api/employee/document-requests").json()
    assert not any(r["is_mandatory"] for r in reqs["requests"]) and {"png", "jpg", "pdf"} <= {x.strip(".") for x in reqs["limits"]["allowed"]}
    aadhaar = next(r for r in reqs["requests"] if r["name"] == "Aadhaar card")
    photo = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 300).decode()
    up = portal.post(f"/api/employee/document-requests/{aadhaar['id']}/upload", json={"file_name": "aadhaar.png", "file_type": "image/png", "file_data": photo})
    assert up.status_code == 200, up.text
    pdf = base64.b64encode(b"%PDF-1.4\n" + b"0" * 300).decode()
    pan = next(r for r in reqs["requests"] if r["name"] == "PAN card")
    assert portal.post(f"/api/employee/document-requests/{pan['id']}/upload", json={"file_name": "pan.pdf", "file_type": "application/pdf", "file_data": pdf}).status_code == 200
    mine = portal.get("/api/employee/document-requests").json()["requests"]
    assert {r["name"]: r["status"] for r in mine}["Aadhaar card"] == "submitted"


def test_an_existing_company_is_brought_to_the_new_defaults_once(tenant):
    """A company set up before this change: every requirement mandatory, no Aadhaar/PAN/UAN. It is moved over once, what
    HR had is kept, and HR making something mandatory again afterwards is not undone."""
    from app.services.hr import INDIA_ONBOARDING_KEY, apply_india_onboarding
    with main.SessionLocal() as db:
        cid = db.query(models.DBClient).order_by(models.DBClient.id.desc()).first().id
        db.query(models.DBSettings).filter(models.DBSettings.client_id == cid, models.DBSettings.key == INDIA_ONBOARDING_KEY).delete()
        db.add(models.DBDocumentRequirement(client_id=cid, name="Photo ID", doc_type="identity", is_mandatory=True, due_days=3, sort_order=0))
        db.commit()
        starter = models.DBEmployee(client_id=cid, first_name="New", last_name="Starter", email="ns@example.com", status="onboarding",
                                    start_date=datetime.now().strftime("%Y-%m-%d"))
        db.add(starter)
        db.commit()
        added = apply_india_onboarding(db, cid)
        assert added == 6
        rules = db.query(models.DBDocumentRequirement).filter(models.DBDocumentRequirement.client_id == cid).all()
        assert {"Photo ID", "Aadhaar card", "PAN card", "UAN (EPF) details"} <= {r.name for r in rules}
        assert not any(r.is_mandatory for r in rules)
        asked = {r.name for r in db.query(models.DBDocumentRequest).filter(models.DBDocumentRequest.employee_id == starter.id)}
        assert {"Aadhaar card", "PAN card", "UAN (EPF) details"} <= asked
        db.query(models.DBDocumentRequirement).filter(models.DBDocumentRequirement.name == "PAN card", models.DBDocumentRequirement.client_id == cid).update({"is_mandatory": True})
        db.commit()
        assert apply_india_onboarding(db, cid) == 0, "once only"
        assert db.query(models.DBDocumentRequirement).filter(models.DBDocumentRequirement.name == "PAN card", models.DBDocumentRequirement.client_id == cid).first().is_mandatory
