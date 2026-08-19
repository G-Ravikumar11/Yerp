"""Recruitment: public application intake, document handling and the pipeline."""
import base64

import pytest

import main


def b64(size_bytes=1024, fill=b"x"):
    return base64.b64encode(fill * size_bytes).decode()


@pytest.fixture
def form(tenant):
    res = tenant.post("/api/recruitment/forms", json={
        "title": "Backend Engineer",
        "description": "Build the thing",
        "fields": '[{"label":"Full name","type":"text"},{"label":"Email","type":"email"}]',
        "pipeline_stages": '["Applied","Screening","Interview","Offer","Hired"]',
    })
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture(autouse=True)
def _clear_apply_limit():
    # The public submit endpoint is rate limited per IP; every test shares one.
    main.rate_limiter._hits.clear()
    yield


def apply_to(client, token, **overrides):
    body = {
        "answers": '{"Full name":"Sam Patel"}',
        "candidate_name": "Sam Patel",
        "candidate_email": "sam@example.com",
        "documents": [
            {"doc_type": "resume", "file_name": "cv.pdf", "file_type": "application/pdf", "file_data": b64()},
        ],
    }
    body.update(overrides)
    return client.post(f"/api/recruitment/form/{token}/submit", json=body)


# --- intake ----------------------------------------------------------------

def test_application_accepts_multiple_documents(client, tenant, form):
    res = apply_to(client, form["form_token"], documents=[
        {"doc_type": "resume", "file_name": "cv.pdf", "file_type": "application/pdf", "file_data": b64()},
        {"doc_type": "cover_letter", "file_name": "letter.pdf", "file_type": "application/pdf", "file_data": b64()},
        {"doc_type": "supporting", "file_name": "cert.png", "file_type": "image/png", "file_data": b64()},
    ])
    assert res.status_code == 200, res.text
    assert res.json()["documents_received"] == 3
    assert res.json()["stage"] == "Applied"

    subs = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()
    assert subs[0]["document_count"] == 3
    docs = tenant.get(f"/api/recruitment/submissions/{subs[0]['id']}/documents").json()
    assert {d["file_name"] for d in docs} == {"cv.pdf", "letter.pdf", "cert.png"}
    assert all(d["file_size"] > 0 for d in docs)


def test_oversized_file_rejected(client, form):
    res = apply_to(client, form["form_token"], documents=[
        {"file_name": "huge.pdf", "file_type": "application/pdf", "file_data": b64(6 * 1024 * 1024)},
    ])
    assert res.status_code == 413
    assert "limit" in res.json()["detail"]


def test_disallowed_extension_rejected(client, form):
    res = apply_to(client, form["form_token"], documents=[
        {"file_name": "payload.exe", "file_type": "application/octet-stream", "file_data": b64()},
    ])
    assert res.status_code == 400
    assert "not an accepted file type" in res.json()["detail"]


def test_too_many_documents_rejected(client, form):
    docs = [{"file_name": f"f{i}.pdf", "file_type": "application/pdf", "file_data": b64(10)} for i in range(9)]
    res = apply_to(client, form["form_token"], documents=docs)
    assert res.status_code == 400
    assert "at most" in res.json()["detail"]


def test_empty_file_rejected(client, form):
    res = apply_to(client, form["form_token"], documents=[
        {"file_name": "empty.pdf", "file_type": "application/pdf", "file_data": ""},
    ])
    assert res.status_code == 400


def test_invalid_candidate_email_rejected(client, form):
    res = apply_to(client, form["form_token"], candidate_email="not-an-email")
    assert res.status_code == 400


def test_public_submit_is_rate_limited(client, form):
    codes = [apply_to(client, form["form_token"]).status_code for _ in range(8)]
    assert 429 in codes


def test_inactive_form_rejects_applications(client, tenant, form):
    tenant.put(f"/api/recruitment/forms/{form['id']}", json={"is_active": False})
    assert apply_to(client, form["form_token"]).status_code == 404


def test_legacy_single_file_field_still_works(client, tenant, form):
    res = client.post(f"/api/recruitment/form/{form['form_token']}/submit", json={
        "answers": "{}", "candidate_name": "Legacy", "candidate_email": "legacy@example.com",
        "file_name": "old.pdf", "file_type": "application/pdf", "file_data": b64(),
    })
    assert res.status_code == 200
    assert res.json()["documents_received"] == 1


# --- pipeline --------------------------------------------------------------

def test_stage_move_is_recorded_in_history(client, tenant, form):
    apply_to(client, form["form_token"])
    sub = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]

    res = tenant.put(f"/api/recruitment/submissions/{sub['id']}/stage",
                     json={"stage": "Interview", "stage_order": 2, "note": "Strong CV"})
    assert res.status_code == 200
    assert res.json()["from_stage"] == "Applied"

    history = tenant.get(f"/api/recruitment/submissions/{sub['id']}/history").json()
    assert [e["to_stage"] for e in history] == ["Applied", "Interview"]
    assert history[-1]["note"] == "Strong CV"


def test_stage_must_exist_on_the_form(client, tenant, form):
    apply_to(client, form["form_token"])
    sub = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]
    res = tenant.put(f"/api/recruitment/submissions/{sub['id']}/stage", json={"stage": "Nowhere"})
    assert res.status_code == 400
    assert "not a stage" in res.json()["detail"]


def test_pipeline_includes_empty_stages(client, tenant, form):
    apply_to(client, form["form_token"])
    data = tenant.get(f"/api/recruitment/forms/{form['id']}/pipeline").json()
    assert set(data["stages"]) == set(data["pipeline"].keys())
    assert data["pipeline"]["Offer"] == []


def test_candidate_rating(client, tenant, form):
    apply_to(client, form["form_token"])
    sub = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]
    assert tenant.put(f"/api/recruitment/submissions/{sub['id']}/rating", json={"rating": 4}).status_code == 200
    assert tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]["rating"] == 4
    assert tenant.put(f"/api/recruitment/submissions/{sub['id']}/rating", json={"rating": 9}).status_code == 400


# --- hiring ----------------------------------------------------------------

def test_hire_converts_candidate_to_employee_with_documents(client, tenant, form):
    apply_to(client, form["form_token"], documents=[
        {"doc_type": "resume", "file_name": "cv.pdf", "file_type": "application/pdf", "file_data": b64()},
        {"doc_type": "supporting", "file_name": "id.png", "file_type": "image/png", "file_data": b64()},
    ])
    sub = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]

    res = tenant.post(f"/api/recruitment/submissions/{sub['id']}/hire", json={
        "job_title": "Backend Engineer", "level": "L3", "start_date": "2026-03-01", "salary": 4000,
    })
    assert res.status_code == 200, res.text
    emp_id = res.json()["employee_id"]

    emp = tenant.get(f"/api/employees/{emp_id}").json()
    assert emp["first_name"] == "Sam"
    assert emp["last_name"] == "Patel"
    assert emp["email"] == "sam@example.com"
    assert emp["level"] == "L3"
    assert emp["status"] == "onboarding"

    # The application's files follow the person into their employee record.
    docs = tenant.get(f"/api/employees/{emp_id}/documents").json()
    assert {d["file_name"] for d in docs} == {"cv.pdf", "id.png"}


def test_hire_is_not_repeatable(client, tenant, form):
    apply_to(client, form["form_token"])
    sub = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]
    assert tenant.post(f"/api/recruitment/submissions/{sub['id']}/hire", json={}).status_code == 200
    again = tenant.post(f"/api/recruitment/submissions/{sub['id']}/hire", json={})
    assert again.status_code == 409


def test_hire_rejects_duplicate_employee_email(client, tenant, form):
    from conftest import make_employee
    make_employee(tenant, email="sam@example.com")
    apply_to(client, form["form_token"])
    sub = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]
    res = tenant.post(f"/api/recruitment/submissions/{sub['id']}/hire", json={})
    assert res.status_code == 400
    assert "already exists" in res.json()["detail"]


# --- cleanup and isolation -------------------------------------------------

def test_deleting_a_form_removes_documents_and_history(client, tenant, form):
    apply_to(client, form["form_token"])
    sub = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]
    assert tenant.delete(f"/api/recruitment/forms/{form['id']}").status_code == 200
    assert tenant.get(f"/api/recruitment/submissions/{sub['id']}/documents").status_code == 404


def test_candidate_documents_are_tenant_scoped(client, tenant, form):
    apply_to(client, form["form_token"])
    sub = tenant.get(f"/api/recruitment/forms/{form['id']}/submissions").json()[0]
    doc_id = tenant.get(f"/api/recruitment/submissions/{sub['id']}/documents").json()[0]["id"]

    client.post("/api/client/logout")
    client.post("/api/client/register", json={"email": "rival@example.com", "password": "Passw0rdTest"})
    client.post("/api/client/login", json={"email": "rival@example.com", "password": "Passw0rdTest"})
    assert client.get(f"/api/recruitment/documents/{doc_id}").status_code == 404
    assert client.get(f"/api/recruitment/submissions/{sub['id']}/documents").status_code == 404
    assert client.post(f"/api/recruitment/submissions/{sub['id']}/hire", json={}).status_code == 404
