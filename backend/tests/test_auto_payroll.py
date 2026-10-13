"""When a month ends, its payslips are drafted without anybody pressing Run payroll."""
from datetime import datetime

import main
from test_department_members import person


def paid_person(tenant, first, salary=60000):
    emp = person(tenant, first)
    assert tenant.put(f"/api/employees/{emp}", json={"salary": salary}).status_code == 200
    return emp


def payslips(tenant):
    return tenant.get("/api/payslips").json()


def run_job(day):
    with main.SessionLocal() as db:
        db.query(main.models.DBJobRun).filter_by(job_name="monthly_payroll").delete()
        db.commit()
    return main.run_due_jobs(now=day, only="monthly_payroll")


def test_last_months_payslips_are_drafted_when_the_month_ends(tenant):
    paid_person(tenant, "Auto")
    run_job(datetime(2026, 10, 1, 6, 0))
    rows = payslips(tenant)
    assert len(rows) == 1
    assert rows[0]["period_start"] == "2026-09-01" and rows[0]["period_end"] == "2026-09-30"
    assert rows[0]["pay_date"] == "2026-09-30" and rows[0]["status"] == "Draft"


def test_the_month_is_run_once_and_never_double_paid(tenant):
    paid_person(tenant, "Once")
    main.run_due_jobs(now=datetime(2026, 10, 1, 6, 0), only="monthly_payroll")
    again = main.run_due_jobs(now=datetime(2026, 10, 20, 6, 0), only="monthly_payroll")
    assert again[0]["status"] == "already_done"
    # Even if the job record were lost, the same period is skipped, not paid twice.
    run_job(datetime(2026, 10, 20, 6, 0))
    assert len(payslips(tenant)) == 1


def test_a_payslip_run_by_hand_is_not_repeated(tenant):
    emp = paid_person(tenant, "Hand")
    res = tenant.post("/api/payslips", json={"employee_id": emp, "period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30", "basic_salary": 60000})
    assert res.status_code == 200, res.text
    run_job(datetime(2026, 10, 1, 6, 0))
    assert len(payslips(tenant)) == 1


def test_it_can_be_switched_off(tenant):
    paid_person(tenant, "Off")
    assert tenant.get("/api/payroll/auto").json() == {"enabled": True}
    assert tenant.put("/api/payroll/auto", json={"enabled": False}).json()["enabled"] is False
    assert tenant.get("/api/payroll/auto").json() == {"enabled": False}
    run_job(datetime(2026, 10, 1, 6, 0))
    assert payslips(tenant) == []


def test_january_pays_december(tenant):
    paid_person(tenant, "Year")
    run_job(datetime(2027, 1, 1, 6, 0))
    assert payslips(tenant)[0]["period_end"] == "2026-12-31"
