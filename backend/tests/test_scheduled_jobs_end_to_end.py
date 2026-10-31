"""The four background jobs of the payroll work, run the way the live site runs them: through the scheduler, which claims
the period, runs the job, and records how it went."""
from datetime import date, datetime

from app import db as database
from app import models
from app.core.scheduler import run_due_jobs
from conftest import make_employee


def run(job, now):
    """The job for that moment, as if it had never run (other tests in this session may have used the same period)."""
    with database.SessionLocal() as db:
        db.query(models.DBJobRun).filter(models.DBJobRun.job_name == job).delete()
        db.commit()
    result = run_due_jobs(now=now, only=job)
    assert len(result) == 1 and result[0]["status"] == "done", result
    return result[0]


def row(emp):
    with database.SessionLocal() as s:
        r = s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one()
        s.expunge(r)
        return r


def alerts(client_id, kind):
    with database.SessionLocal() as s:
        return [(a.title, a.body) for a in s.query(models.DBAlert).filter(
            models.DBAlert.client_id == client_id, models.DBAlert.kind == kind).order_by(models.DBAlert.id)]


def notices(emp_id):
    with database.SessionLocal() as s:
        return [(n.title, n.message) for n in s.query(models.DBNotification).filter(models.DBNotification.employee_id == emp_id)]


# --- the month's payroll ---------------------------------------------------------------------------------------------

def test_the_monthly_run_drafts_the_payslips_checks_them_and_tells_hr(tenant):
    complete = make_employee(tenant, salary=18000.0, tax_rate=0.0)
    tenant.put("/api/employees/%d" % complete["id"], json={"pan_no": "ABCDE1234F", "bank_account": "123456789", "bank_ifsc": "HDFC0001234",
                                                           "uan_no": "100200300400", "esi_no": "3112345678"})
    bare = make_employee(tenant, salary=18000.0, tax_rate=0.0)
    joiner = make_employee(tenant, salary=22000.0, tax_rate=0.0, start_date="2026-09-15")
    cid = row(complete).client_id

    out = run("monthly_payroll", datetime(2026, 10, 1, 6, 0))
    assert "to check" in out["detail"]

    mine = [p for p in tenant.get("/api/payslips").json() if p["period_end"] == "2026-09-30"]
    assert len(mine) == 3 and all(p["status"] == "Draft" for p in mine)
    by_name = {p["employee_id"]: p for p in mine}
    # Statutory deductions and paid days came from each person's own record
    full = by_name[complete["id"]]
    assert full["employee_pf"] == 864.0 and full["employer_pf"] == 864.0 and full["professional_tax"] == 0.0
    assert full["working_days"] == 22 and full["paid_days"] == 22
    part = by_name[joiner["id"]]
    assert part["working_days"] == 22 and part["paid_days"] == 12, "joined on the 15th: 15 to 30 September is 12 working days"

    ready = alerts(cid, "payroll_ready")
    assert ready and "September 2026 payroll is ready" in ready[-1][0] and "PF for" in ready[-1][1]
    checks = " | ".join(t for t, _ in alerts(cid, "payroll_check"))
    assert "no PAN" in checks and "bank transfer" in checks and "no UAN" in checks
    assert tenant.get("/api/payroll/month", params={"month": "2026-09"}).json()["status"] == "Draft"


def test_the_run_leaves_a_locked_month_alone_and_says_so(tenant):
    emp = make_employee(tenant, salary=18000.0)
    tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"})
    for step in ("approve", "pay", "lock"):
        assert tenant.post("/api/payroll/month/%s" % step, json={"month": "2026-09"}).status_code == 200
    before = len(tenant.get("/api/payslips").json())
    run("monthly_payroll", datetime(2026, 10, 1, 6, 0))
    assert len(tenant.get("/api/payslips").json()) == before, "a locked month is not added to"
    assert any("could not run automatically" in t for t, _ in alerts(row(emp).client_id, "payroll_failed"))


# --- the night ---------------------------------------------------------------------------------------------------------

def test_the_nightly_job_marks_the_absent_and_tells_their_manager(tenant):
    boss, present, away = make_employee(tenant), make_employee(tenant), make_employee(tenant)
    tenant.put("/api/employees/%d" % away["id"], json={"reports_to": boss["id"]})
    assert tenant.put("/api/attendance/settings", json={"working_days": "1,2,3,4,5", "require_location": False,
                                                        "work_start": "09:00", "grace_minutes": 15}).status_code == 200
    with database.SessionLocal() as s:
        cid = s.query(models.DBEmployee).filter(models.DBEmployee.id == away["id"]).one().client_id
        for e in (present, away):                                       # attendance is kept for both
            s.add(models.DBAttendance(client_id=cid, employee_id=e["id"], date="2026-10-13", clock_in="09:00:00",
                                      clock_out="17:00:00", status="completed"))
        s.add(models.DBAttendance(client_id=cid, employee_id=present["id"], date="2026-10-14", clock_in="09:00:00",
                                  clock_out="17:00:00", status="completed"))
        s.commit()
    out = run("nightly_attendance", datetime(2026, 10, 15, 0, 10))         # for Wednesday 14 October
    assert "2026-10-14" in out["detail"]
    with database.SessionLocal() as s:
        mark = s.query(models.DBAttendance).filter(models.DBAttendance.employee_id == away["id"],
                                                   models.DBAttendance.date == "2026-10-14").one()
        assert mark.status == "absent" and mark.check_type == "system"
        assert s.query(models.DBAttendance).filter(models.DBAttendance.employee_id == present["id"],
                                                   models.DBAttendance.date == "2026-10-14").count() == 1
    assert any(t.startswith("Your team") and "Absent: " + away["first_name"] in m for t, m in notices(boss["id"]))


# --- leave and reminders -----------------------------------------------------------------------------------------------

def test_the_leave_job_carries_forward_and_credits_the_new_year(tenant):
    emp = make_employee(tenant)
    with database.SessionLocal() as s:
        r = s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one()
        r.annual_leave_entitlement, r.sick_leave_entitlement = 24.0, 12.0
        s.commit()
    assert tenant.put("/api/leave/accrual", json={"enabled": True, "carry_max": {"annual": 10, "sick": 0}}).status_code == 200
    out = run("leave_accrual", datetime(2027, 1, 1, 6, 0))
    assert out["detail"].startswith("leave credited for")
    ledger = tenant.get("/api/employees/%d/leave-ledger" % emp["id"], params={"year": 2027}).json()
    kinds = {(e["leave_type"], e["kind"]) for e in ledger["entries"]}
    assert ("annual", "accrual") in kinds and ledger["balance"]["annual_total"] >= 2.0


def test_the_reminder_job_tells_hr_and_the_manager(tenant):
    boss, new = make_employee(tenant), make_employee(tenant)
    tenant.put("/api/employees/%d" % new["id"], json={"probation_end_date": "2026-11-09", "reports_to": boss["id"]})
    out = run("hr_reminders", datetime(2026, 11, 2, 6, 0))
    assert out["detail"].startswith("reminders for")
    assert any("Probation ending" in t for t, _ in notices(boss["id"]))
    assert any("Probation ending" in t for t, _ in alerts(row(new).client_id, "probation_ending"))


# --- one fault does not take the rest down -----------------------------------------------------------------------------

def test_a_fault_in_the_month_end_checks_neither_fails_the_run_nor_hides_the_ready_notice(tenant, monkeypatch):
    emp = make_employee(tenant, salary=18000.0, tax_rate=0.0)

    def boom(*a, **k):
        raise RuntimeError("a bug in a check")
    monkeypatch.setattr("app.services.payroll_checks.month_checks", boom)
    out = run("monthly_payroll", datetime(2026, 10, 1, 6, 0))           # still a successful run
    assert [p for p in tenant.get("/api/payslips").json() if p["period_end"] == "2026-09-30"], "the payslips were made and kept"
    assert any("payroll is ready" in t for t, _ in alerts(row(emp).client_id, "payroll_ready"))
    assert "to check" not in out["detail"]


def test_one_companys_failure_leaves_the_others_reminders_intact(tenant, second_tenant, monkeypatch):
    from app.services import hr_reminders
    mine, theirs = make_employee(tenant), make_employee(second_tenant)
    for client, emp in ((tenant, mine), (second_tenant, theirs)):
        assert client.put("/api/employees/%d" % emp["id"], json={"probation_end_date": "2026-11-09"}).status_code == 200
    broken, fine = row(mine).client_id, row(theirs).client_id
    real = hr_reminders.send

    def flaky(db, client_id, found):
        if client_id == broken:
            raise RuntimeError("trouble in one company")
        return real(db, client_id, found)
    monkeypatch.setattr(hr_reminders, "send", flaky)
    with database.SessionLocal() as db:
        db.query(models.DBJobRun).filter(models.DBJobRun.job_name == "hr_reminders").delete()
        db.commit()
    result = run_due_jobs(now=datetime(2026, 11, 2, 6, 0), only="hr_reminders")[0]
    assert result["status"] == "failed" and "Failed for %d" % broken in result["detail"], "recorded, not hidden"
    assert alerts(fine, "probation_ending"), "the other company still heard"
    assert not alerts(broken, "probation_ending")
