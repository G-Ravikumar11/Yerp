"""The People screens ask the database a fixed handful of questions, and never carry files they do not show.

On the hosted database every question is a trip across an ocean - a quarter of a second, more on a bad
day - so adding an employee that asked forty took the better part of half a minute. These pin the work
down: creating somebody is one short transaction, the onboarding lists do not ask once per person, an
employee's record does not ask once per document, and no list brings back a scan or a template.
"""
import uuid

from sqlalchemy import event

from app import db as database
from app import models
from conftest import make_employee


def statements(client, method, path, **kw):
    """The statements a request sent, as Postgres would send them: back-to-back inserts into one table
    go as one statement there (SQLite sends them one by one, so they are folded together here)."""
    seen = []

    def note(conn, cursor, statement, *_):
        line = " ".join(statement.split())
        if line.startswith("PRAGMA") or (line.startswith("INSERT") and seen and seen[-1] == line):
            return
        seen.append(line)
    event.listen(database.engine, "before_cursor_execute", note)
    try:
        res = getattr(client, method)(path, **kw)
    finally:
        event.remove(database.engine, "before_cursor_execute", note)
    assert res.status_code == 200, (path, res.text)
    return seen, res


def new_starter(tenant, dept_id, site_ids, **extra):
    body = {"first_name": "New", "last_name": "Starter%s" % uuid.uuid4().hex[:4],
            "email": "n-%s@example.com" % uuid.uuid4().hex[:8], "password": "Str0ng!Passw0rd#",
            "job_title": "Engineer", "department_id": dept_id, "permission_role": "staff",
            "site_ids": site_ids, "start_date": "2026-10-01"}
    body.update(extra)
    return statements(tenant, "post", "/api/employees", json=body)


def setup(tenant):
    dept = tenant.post("/api/departments", json={"name": "Ops", "description": "", "color": "#fff", "icon": "x"}).json()
    sites = [tenant.post("/api/jobs", json={"name": "Site %d" % i, "number": "J%d" % i}).json()["id"] for i in range(2)]
    make_employee(tenant)          # the first one seeds the document requirements; the rest find them
    return dept["id"], sites


def test_adding_an_employee_is_one_short_transaction(tenant):
    dept, sites = setup(tenant)
    sent, res = new_starter(tenant, dept, sites, permissions=["projects.view", "people.manage"])
    # Signed-in check, org domain, email free, department, next number, the employee, the department's goals,
    # the requirements, the sites, then one insert per table and one commit - with nothing looked up twice.
    assert len(sent) <= 15, "%d statements:\n%s" % (len(sent), "\n".join(s[:120] for s in sent))
    assert sum(1 for s in sent if s.startswith("COMMIT")) <= 1
    out = res.json()
    assert out["site_ids"] == sorted(sites) and out["all_sites"] is False and out["department_id"] == dept


def test_the_rights_ticked_are_saved_with_the_employee(tenant):
    dept, sites = setup(tenant)
    # Keeps one right the staff level gives, drops the rest, and adds one it does not.
    _, res = new_starter(tenant, dept, [], permissions=["projects.view", "people.manage"])
    emp = tenant.get("/api/employees/%d" % res.json()["id"]).json()
    assert emp["permissions"] == ["people.manage", "projects.view"]
    assert emp["all_sites"] is True and emp["site_ids"] == []
    # Measured against the access level, exactly as the Access screen saves them.
    assert emp["extra_permissions"] == ["people.manage"]
    assert set(emp["denied_permissions"]) == set(emp["role_permissions"]) - {"projects.view"}
    actions = {r["action"] for r in tenant.get("/api/audit-logs").json() if r["entity_id"] == emp["id"]}
    assert {"employee_created", "employee_permissions_changed"} <= actions


def test_left_out_the_rights_are_the_access_levels_own(tenant):
    dept, sites = setup(tenant)
    _, res = new_starter(tenant, dept, sites)
    emp = tenant.get("/api/employees/%d" % res.json()["id"]).json()
    assert emp["extra_permissions"] == [] and emp["denied_permissions"] == []
    assert emp["permissions"] == emp["role_permissions"]


def test_a_new_starter_still_gets_a_checklist_and_document_requests(tenant):
    dept, sites = setup(tenant)
    _, res = new_starter(tenant, dept, sites)
    emp = tenant.get("/api/employees/%d" % res.json()["id"]).json()
    assert emp["onboarding_items"] and emp["document_requests"]
    assert emp["status"] == "onboarding" and emp["department_id"] == dept


def _onboard(tenant, n):
    for _ in range(n):
        make_employee(tenant)


def test_the_onboarding_lists_do_not_ask_once_per_person(tenant):
    _onboard(tenant, 2)
    few = {p: len(statements(tenant, "get", p)[0]) for p in ("/api/onboarding/hub", "/api/onboarding/pipeline")}
    _onboard(tenant, 6)
    for path, before in few.items():
        many = len(statements(tenant, "get", path)[0])
        assert many <= before, "%s: %d statements for 3 people, %d for 9" % (path, before, many)


def _attach_files(emp_id, n):
    """Give n of their document requests a submitted file, as the employee portal would."""
    s = database.SessionLocal()
    try:
        emp = s.get(models.DBEmployee, emp_id)
        rows = s.query(models.DBDocumentRequest).filter(models.DBDocumentRequest.employee_id == emp_id,
                                                        models.DBDocumentRequest.document_id.is_(None)).limit(n).all()
        for r in rows:
            doc = models.DBDocument(client_id=emp.client_id, employee_id=emp_id, title=r.name, file_name="scan.pdf",
                                    file_type="application/pdf", file_size=9, file_data="SECRETSCAN" * 50)
            s.add(doc)
            s.flush()
            r.document_id, r.status, r.submitted_at = doc.id, "submitted", "2026-10-02"
        s.commit()
        return len(rows)
    finally:
        s.close()


def test_an_employee_record_does_not_ask_once_per_document_or_carry_the_files(tenant):
    emp = make_employee(tenant)
    path = "/api/employees/%d" % emp["id"]
    assert _attach_files(emp["id"], 1) == 1
    few, _ = statements(tenant, "get", path)
    assert _attach_files(emp["id"], 4) >= 2
    many, res = statements(tenant, "get", path)
    assert len(many) <= len(few), "%d statements with one file, %d with more" % (len(few), len(many))
    assert "SECRETSCAN" not in res.text
    assert not any("employee_documents.file_data" in s for s in many)
    assert not any("template_file_data AS" in s for s in many)
    reqs = [r for r in res.json()["document_requests"] if r.get("file_name")]
    assert reqs and all(r["file_name"] == "scan.pdf" for r in reqs)


def test_the_review_queue_does_not_ask_once_per_document_but_the_file_still_opens(tenant):
    emp = make_employee(tenant)
    _attach_files(emp["id"], 1)
    few, _ = statements(tenant, "get", "/api/onboarding/document-queue")
    _attach_files(emp["id"], 4)
    many, res = statements(tenant, "get", "/api/onboarding/document-queue")
    assert len(many) <= len(few)
    assert "SECRETSCAN" not in res.text
    one = res.json()[0]
    opened = tenant.get("/api/onboarding/document-requests/%d/file" % one["id"]).json()
    assert opened["file_data"] == "SECRETSCAN" * 50 and opened["file_name"] == "scan.pdf"


def test_a_template_still_downloads_and_lists_say_it_is_there(tenant):
    make_employee(tenant)
    reqs = tenant.get("/api/onboarding/requirements").json()
    rid = reqs[0]["id"]
    assert tenant.post("/api/onboarding/requirements/%d/template" % rid,
                       json={"file_name": "form.pdf", "file_type": "application/pdf", "file_data": "QkxBTks="}).status_code == 200
    listed = {r["id"]: r for r in tenant.get("/api/onboarding/requirements").json()}
    assert listed[rid]["has_template"] is True and listed[rid]["template_file_name"] == "form.pdf"
    got = tenant.get("/api/onboarding/requirements/%d/template" % rid).json()
    assert got["file_data"] == "QkxBTks="


def test_the_hr_counts_are_one_grouped_read(tenant):
    _onboard(tenant, 3)
    sent, res = statements(tenant, "get", "/api/hr/stats")
    assert len(sent) <= 4, sent
    stats = res.json()
    assert stats["total_employees"] == 3 and stats["onboarding"] == 3 and stats["active"] == 0


def test_the_employee_page_is_three_reads_and_carries_what_the_form_needs(tenant):
    dept, sites = setup(tenant)
    _, res = new_starter(tenant, dept, sites, org_email="ns-%s@acme.example" % uuid.uuid4().hex[:6])
    eid = res.json()["id"]
    sent, page = statements(tenant, "get", "/api/employees/%d?view=profile" % eid)
    assert len(sent) <= 3, sent
    p = page.json()
    assert p["org_email"].endswith("@acme.example") and p["department_name"] == "Ops"
    assert p["site_ids"] == sorted(sites) and "permissions" in p and "payslips" not in p
    # The full record is unchanged for the screens that want everything, and carries the same profile.
    full = tenant.get("/api/employees/%d" % eid).json()
    assert "payslips" in full and "document_requests" in full
    assert {k: full[k] for k in p} == p


def test_saving_a_profile_answers_with_it_and_does_not_recheck_what_did_not_change(tenant):
    dept, sites = setup(tenant)
    org = "keep-%s@acme.example" % uuid.uuid4().hex[:6]
    _, res = new_starter(tenant, dept, sites, org_email=org)
    eid = res.json()["id"]
    page = tenant.get("/api/employees/%d?view=profile" % eid).json()
    form = {k: page[k] for k in ("first_name", "last_name", "email", "org_email", "phone", "job_title", "department_id",
                                 "reports_to", "level", "role", "employment_type", "pay_frequency", "salary",
                                 "tax_rate", "start_date", "emergency_contact", "emergency_phone")}
    form.update(phone="0123", job_title="Lead")
    sent, saved = statements(tenant, "put", "/api/employees/%d" % eid, json=form)
    # Signed-in check, the person, the change and its audit line, the profile back, one commit.
    assert len(sent) <= 7, "%d statements:\n%s" % (len(sent), "\n".join(s[:120] for s in sent))
    out = saved.json()
    assert out["job_title"] == "Lead" and out["phone"] == "0123" and out["department_name"] == "Ops"
    # The organisation address the form sends back is kept - it used to be missing from the page, so a save wiped it.
    assert out["org_email"] == org
    assert tenant.get("/api/employees/%d?view=profile" % eid).json() == {k: v for k, v in out.items() if k != "message"}


def test_saving_access_answers_with_the_profile(tenant):
    dept, sites = setup(tenant)
    _, res = new_starter(tenant, dept, [])
    eid = res.json()["id"]
    out = tenant.put("/api/employees/%d/permissions" % eid,
                     json={"permission_role": "staff", "permissions": ["projects.view"], "site_ids": sites[:1]}).json()
    assert out["permissions"] == ["projects.view"] and out["site_ids"] == sites[:1] and out["all_sites"] is False
    assert out["message"] == "Access updated" and out["full_name"].startswith("New ")


def test_the_employee_list_and_counts_are_one_read_each(tenant):
    dept, sites = setup(tenant)
    for _ in range(3):
        new_starter(tenant, dept, sites)
    sent, res = statements(tenant, "get", "/api/employees")
    assert len(sent) <= 2, sent
    rows = {r["id"]: r for r in res.json()}
    starters = [r for r in rows.values() if r["department_id"] == dept]
    assert len(starters) == 3 and all(r["department_name"] == "Ops" and r["site_count"] == 2 for r in starters)
    sent, _ = statements(tenant, "get", "/api/hr/stats")
    assert len(sent) <= 2, sent


def test_deleting_an_employee_still_clears_everything_that_points_at_them(tenant):
    dept, sites = setup(tenant)
    _, boss = new_starter(tenant, dept, sites)
    _, res = new_starter(tenant, dept, sites, reports_to=boss.json()["id"])
    boss_id, eid = boss.json()["id"], res.json()["id"]
    assert tenant.delete("/api/employees/%d" % boss_id).status_code == 200
    assert tenant.get("/api/employees/%d" % boss_id).status_code == 404
    assert tenant.get("/api/employees/%d?view=profile" % eid).json()["reports_to"] is None
    s = database.SessionLocal()
    try:
        for model in (models.DBOnboardingItem, models.DBDocumentRequest, models.DBEmployeeSite):
            assert s.query(model).filter(model.employee_id == boss_id).count() == 0, model.__name__
    finally:
        s.close()


def test_deleting_a_department_lets_its_people_go_in_one_go(tenant):
    dept, sites = setup(tenant)
    _, res = new_starter(tenant, dept, sites)
    assert tenant.delete("/api/departments/%d" % dept).status_code == 200
    assert tenant.get("/api/employees/%d?view=profile" % res.json()["id"]).json()["department_id"] is None
    assert all(d["id"] != dept for d in tenant.get("/api/departments").json())
