"""The nightly attendance check, the month-end payroll checks, and payslips emailed when a month is approved."""
from datetime import date, datetime

import pytest

from app import db as database
from app import models
from app.services import attendance_job, lop, payroll_checks
from conftest import make_employee

DAY = date(2026, 10, 14)            # a Wednesday
ISO = DAY.isoformat()


def configure(tenant, **kw):
    body = {"working_days": "1,2,3,4,5", "work_start": "09:00", "grace_minutes": 15, "auto_clockout_hours": 10,
            "late_threshold": 3, "late_penalty_lop": 0.5, "require_location": False, **kw}
    assert tenant.put("/api/attendance/settings", json=body).status_code == 200


def session():
    return database.SessionLocal()


def client_of(s, emp):
    return s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one().client_id


def add_att(s, emp, day, clock_in="09:00:00", clock_out="", status="present"):
    s.add(models.DBAttendance(client_id=client_of(s, emp), employee_id=emp["id"], date=day, clock_in=clock_in,
                              clock_out=clock_out, status=status))


def run_night(s, emp):
    client = s.query(models.DBClient).filter(models.DBClient.id == client_of(s, emp)).one()
    return attendance_job.nightly_for_client(s, client, DAY)


def record(s, emp, day=ISO):
    return s.query(models.DBAttendance).filter(models.DBAttendance.employee_id == emp["id"],
                                               models.DBAttendance.date == day).first()


def notices_for(s, emp):
    return s.query(models.DBNotification).filter(models.DBNotification.employee_id == emp["id"]).all()


# --- closing forgotten shifts ----------------------------------------------------------------------------------------

def test_an_open_shift_is_closed_at_the_auto_clock_out_time_with_no_overtime(tenant):
    configure(tenant)
    emp = make_employee(tenant)
    s = session()
    try:
        add_att(s, emp, ISO, clock_in="09:00:00")
        s.commit()
        assert run_night(s, emp)["closed"] == 1
        att = record(s, emp)
        assert att.clock_out == "19:00:00" and att.total_hours == 10.0 and att.overtime_hours == 0
        assert att.status == "completed" and "automatically" in att.notes
    finally:
        s.close()


def test_a_late_evening_shift_is_closed_the_next_morning(tenant):
    configure(tenant)
    emp = make_employee(tenant)
    s = session()
    try:
        add_att(s, emp, ISO, clock_in="20:00:00")
        s.commit()
        run_night(s, emp)
        att = record(s, emp)
        assert att.clock_out == "06:00:00" and att.total_hours == 10.0, "past midnight, still ten hours"
    finally:
        s.close()


# --- absences --------------------------------------------------------------------------------------------------------

def test_someone_due_at_work_with_no_record_and_no_leave_is_marked_absent(tenant):
    configure(tenant)
    kept, never, away, later = (make_employee(tenant) for _ in range(4))
    s = session()
    try:
        cid = client_of(s, kept)
        for e in (kept, away, later):
            add_att(s, e, "2026-10-13", clock_out="17:00:00")        # attendance is kept for them
        s.add(models.DBLeaveRequest(client_id=cid, employee_id=away["id"], leave_type="annual",
                                    start_date=ISO, end_date=ISO, days=1, status="approved"))
        s.query(models.DBEmployee).filter(models.DBEmployee.id == later["id"]).one().start_date = "2026-10-20"
        s.commit()
        run_night(s, kept)
        assert record(s, kept).status == "absent" and record(s, kept).check_type == "system"
        assert record(s, never) is None, "attendance is not kept for them: not marked"
        assert record(s, away) is None, "on approved leave"
        assert record(s, later) is None, "not on the books yet"
    finally:
        s.close()


def test_nobody_is_marked_absent_on_a_holiday_or_a_day_off(tenant):
    configure(tenant, working_days="1,2,4,5")                       # Wednesday off
    emp = make_employee(tenant)
    s = session()
    try:
        add_att(s, emp, "2026-10-13", clock_out="17:00:00")
        s.commit()
        run_night(s, emp)
        assert record(s, emp) is None
    finally:
        s.close()


def test_an_absence_marked_at_night_is_loss_of_pay(tenant):
    configure(tenant)
    emp = make_employee(tenant)
    s = session()
    try:
        add_att(s, emp, "2026-10-13", clock_out="17:00:00")
        s.commit()
        run_night(s, emp)
        row = s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one()
        d = lop.pay_days(s, row.client_id, row, "2026-10-14", "2026-10-14", today=DAY)
        assert d["absent"] == 1 and d["paid_days"] == 0
    finally:
        s.close()


# --- lates -----------------------------------------------------------------------------------------------------------

def test_a_late_day_still_counts_after_the_person_has_clocked_out(tenant):
    """The bug this guards: clocking out marks the day "completed", which hid the late arrival from the penalty."""
    configure(tenant)
    emp = make_employee(tenant)
    s = session()
    try:
        for d in ("2026-10-05", "2026-10-06", "2026-10-07"):
            add_att(s, emp, d, clock_in="09:40:00", clock_out="18:00:00", status="completed")
        s.commit()
        row = s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one()
        d = lop.pay_days(s, row.client_id, row, "2026-10-05", "2026-10-07", today=DAY)
        assert d["late_count"] == 3 and d["late_penalty"] == 0.5
    finally:
        s.close()


def test_the_third_late_arrival_warns_the_person_and_hr(tenant):
    configure(tenant)
    emp = make_employee(tenant)
    s = session()
    try:
        for d in ("2026-10-07", "2026-10-12"):
            add_att(s, emp, d, clock_in="09:30:00", clock_out="18:00:00", status="completed")
        add_att(s, emp, ISO, clock_in="09:50:00", clock_out="18:00:00", status="completed")
        s.commit()
        r = run_night(s, emp)
        assert r["late"] == 1 and r["warned"] == 1
        mine = [n for n in notices_for(s, emp) if n.title.startswith("Late 3 times")]
        assert mine and "0.5 day" in mine[0].message
        bell = s.query(models.DBAlert).filter(models.DBAlert.kind == "attendance_late_penalty",
                                              models.DBAlert.client_id == client_of(s, emp)).all()
        assert bell and "3 lates" in bell[-1].body
    finally:
        s.close()


def test_coming_in_within_the_grace_period_is_not_late(tenant):
    configure(tenant)
    emp = make_employee(tenant)
    s = session()
    try:
        add_att(s, emp, ISO, clock_in="09:14:00", clock_out="18:00:00", status="completed")
        s.commit()
        assert run_night(s, emp)["late"] == 0
    finally:
        s.close()


# --- managers --------------------------------------------------------------------------------------------------------

def test_a_manager_hears_about_their_own_team_only(tenant):
    configure(tenant)
    boss, other_boss = make_employee(tenant), make_employee(tenant)
    late_one, absent_one, elsewhere = make_employee(tenant), make_employee(tenant), make_employee(tenant)
    s = session()
    try:
        for e, b in ((late_one, boss), (absent_one, boss), (elsewhere, other_boss)):
            s.query(models.DBEmployee).filter(models.DBEmployee.id == e["id"]).one().reports_to = b["id"]
        for e in (absent_one, elsewhere):
            add_att(s, e, "2026-10-13", clock_out="17:00:00")
        add_att(s, late_one, ISO, clock_in="10:00:00", clock_out="18:00:00", status="completed")
        add_att(s, elsewhere, ISO, clock_in="09:00:00", clock_out="18:00:00", status="completed")
        s.commit()
        run_night(s, late_one)
        team = [n for n in notices_for(s, boss) if n.title.startswith("Your team")]
        assert len(team) == 1
        assert "Absent: " + absent_one["first_name"] in team[0].message and "Late: " in team[0].message
        assert "45 min" in team[0].message, "10:00 is 45 minutes past 09:00 and the 15 minutes' grace"
        assert not [n for n in notices_for(s, other_boss) if n.title.startswith("Your team")], "their person was on time"
    finally:
        s.close()


def test_the_job_is_registered_for_every_night():
    from app.core.scheduler import SCHEDULED_JOBS, daily_key
    jobs = {name: key for name, key, _ in SCHEDULED_JOBS}
    assert jobs["nightly_attendance"] is daily_key


# --- month end -------------------------------------------------------------------------------------------------------

MONTH = "2026-06"
SLIP = {"period_start": "2026-06-01", "period_end": "2026-06-30", "pay_date": "2026-06-30"}


def test_the_month_checks_find_missing_details_and_build_the_files(tenant):
    ok = make_employee(tenant, salary=18000.0)
    tenant.put("/api/employees/%d" % ok["id"], json={"pan_no": "ABCDE1234F", "bank_account": "123456789",
                                                     "bank_ifsc": "HDFC0001234", "uan_no": "100200300400", "esi_no": "3112345678"})
    bare = make_employee(tenant, salary=18000.0)
    for e in (ok, bare):
        assert tenant.post("/api/payslips", json={"employee_id": e["id"], **SLIP}).status_code == 200
    s = session()
    try:
        checks = payroll_checks.month_checks(s, client_of(s, ok), MONTH)
        names = lambda kind: " ".join(checks.get(kind, {}).get("people", []))
        for kind in ("no_pan", "no_bank", "no_uan", "no_esi"):
            assert bare["last_name"] in names(kind) and ok["last_name"] not in names(kind), kind
        assert checks["_files"]["ecr_members"] == 1 and checks["_files"]["esic_members"] == 1
        raised = payroll_checks.announce(s, client_of(s, ok), MONTH, checks)
        assert raised == 4
        bell = s.query(models.DBAlert).filter(models.DBAlert.kind == "payroll_check",
                                              models.DBAlert.client_id == client_of(s, ok)).all()
        assert any("no UAN" in a.title for a in bell) and all("June 2026" in a.title for a in bell)
    finally:
        s.close()


def test_a_big_swing_from_last_month_is_flagged(tenant):
    emp = make_employee(tenant, salary=18000.0)
    tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-05-01",
                                       "period_end": "2026-05-31", "pay_date": "2026-05-31"})
    tenant.post("/api/payslips", json={"employee_id": emp["id"], **SLIP, "bonus": 9000})
    s = session()
    try:
        checks = payroll_checks.month_checks(s, client_of(s, emp), MONTH)
        assert emp["last_name"] in " ".join(checks["wage_swing"]["people"])
    finally:
        s.close()


# --- emailed on approval ---------------------------------------------------------------------------------------------

@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr("app.routers.payroll.send_email_background", lambda *a, **k: sent.append(a))
    return sent


def test_payslips_go_out_when_the_month_is_approved_if_asked(tenant, outbox):
    configure(tenant, auto_email_on_approval=True)
    a, b = make_employee(tenant), make_employee(tenant)
    ids = [tenant.post("/api/payslips", json={"employee_id": e["id"], **SLIP}).json()["id"] for e in (a, b)]
    res = tenant.post("/api/payroll/month/approve", json={"month": MONTH})
    assert res.status_code == 200, res.text
    assert res.json()["emails"]["queued"] == 2 and len(outbox) == 2
    assert {o[0] for o in outbox} == {a["email"], b["email"]}
    assert all(tenant.get("/api/payslips/%d" % i).json()["status"] == "Sent" for i in ids)


def test_nothing_is_emailed_on_approval_unless_switched_on(tenant, outbox):
    configure(tenant, auto_email_on_approval=False)
    emp = make_employee(tenant)
    tenant.post("/api/payslips", json={"employee_id": emp["id"], **SLIP})
    res = tenant.post("/api/payroll/month/approve", json={"month": MONTH})
    assert res.status_code == 200 and res.json()["emails"]["enabled"] is False and outbox == []
