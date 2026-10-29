"""The business can mark days off as holidays, and every employee has them off.

They sit on the calendar beside India's public holidays, and they are not working days: a day of
leave is not charged for one, nobody is counted absent on one, and the clock says why it is idle.
"""
from datetime import datetime

from conftest import make_employee, work_every_day


def mark(tenant, date, name="Founders' Day"):
    return tenant.post("/api/calendar/holidays", json={"date": date, "name": name})


def listed(tenant, year):
    res = tenant.get("/api/calendar/holidays", params={"year": year})
    assert res.status_code == 200, res.text
    return res.json()


# --- marking and listing ----------------------------------------------------

def test_a_marked_day_is_on_the_calendar_flagged_as_custom(tenant):
    res = mark(tenant, "2026-09-09")
    assert res.status_code == 200, res.text
    mine = [h for h in listed(tenant, 2026) if h["date"] == "2026-09-09"]
    assert mine == [{"date": "2026-09-09", "name": "Founders' Day", "custom": True, "id": res.json()["holidays"][0]["id"]}]


def test_the_public_holidays_are_still_there_and_not_custom(tenant):
    mark(tenant, "2026-09-09")
    public = [h for h in listed(tenant, 2026) if h["date"] == "2026-01-26"]
    assert public and public[0]["custom"] is False and "id" not in public[0]


def test_a_marked_day_can_share_a_date_with_a_public_holiday(tenant):
    mark(tenant, "2026-01-26", "Office closed")
    day = [h["name"] for h in listed(tenant, 2026) if h["date"] == "2026-01-26"]
    assert len(day) == 2 and "Office closed" in day


def test_a_day_cannot_be_marked_twice(tenant):
    mark(tenant, "2026-09-09")
    again = mark(tenant, "2026-09-09", "Something else")
    assert again.status_code == 400 and "already marked" in again.json()["detail"]


def test_a_holiday_needs_a_real_date_and_a_name(tenant):
    assert mark(tenant, "not-a-date").status_code == 400
    assert mark(tenant, "2026-09-09", "   ").status_code == 400


def test_a_marked_day_can_be_taken_off_again(tenant):
    made = mark(tenant, "2026-09-09").json()["holidays"][0]
    assert tenant.delete("/api/calendar/holidays/%d" % made["id"]).status_code == 200
    assert not [h for h in listed(tenant, 2026) if h["date"] == "2026-09-09"]
    assert tenant.delete("/api/calendar/holidays/%d" % made["id"]).status_code == 404


def test_only_the_master_may_mark_days(tenant, portal):
    emp = make_employee(tenant, password="EmpPass123")
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    assert portal.post("/api/calendar/holidays", json={"date": "2026-09-09", "name": "Nope"}).status_code in (401, 403)


def test_each_business_has_its_own_holidays(tenant, second_tenant):
    mark(tenant, "2026-09-09")
    assert [h for h in listed(tenant, 2026) if h["date"] == "2026-09-09"]
    assert not [h for h in listed(second_tenant, 2026) if h["date"] == "2026-09-09"]
    # ...and the other business can mark the same day for itself.
    assert mark(second_tenant, "2026-09-09", "Their day").status_code == 200


# --- a run of days ----------------------------------------------------------

def mark_run(tenant, first, last, name="Site shutdown"):
    return tenant.post("/api/calendar/holidays", json={"date": first, "end_date": last, "name": name})


def test_a_run_of_days_is_marked_in_one_go(tenant):
    res = mark_run(tenant, "2026-12-24", "2026-12-28")
    assert res.status_code == 200, res.text
    assert res.json()["added"] == 5 and res.json()["skipped"] == 0
    days = [h["date"] for h in listed(tenant, 2026) if h["custom"]]
    assert days == ["2026-12-24", "2026-12-25", "2026-12-26", "2026-12-27", "2026-12-28"]


def test_a_run_can_cross_into_the_next_year(tenant):
    mark_run(tenant, "2026-12-30", "2027-01-02")
    assert [h["date"] for h in listed(tenant, 2026) if h["custom"]] == ["2026-12-30", "2026-12-31"]
    assert [h["date"] for h in listed(tenant, 2027) if h["custom"]] == ["2027-01-01", "2027-01-02"]


def test_days_already_marked_are_left_alone_in_a_run(tenant):
    mark(tenant, "2026-12-25", "Christmas close")
    res = mark_run(tenant, "2026-12-24", "2026-12-26")
    assert res.json()["added"] == 2 and res.json()["skipped"] == 1
    names = {h["date"]: h["name"] for h in listed(tenant, 2026) if h["custom"]}
    assert names["2026-12-25"] == "Christmas close", "the one already there keeps its name"


def test_a_run_of_days_all_taken_is_refused(tenant):
    mark_run(tenant, "2026-12-24", "2026-12-26")
    assert mark_run(tenant, "2026-12-24", "2026-12-26").status_code == 400


def test_a_run_must_run_forwards_and_not_too_far(tenant):
    assert mark_run(tenant, "2026-12-26", "2026-12-24").status_code == 400
    assert mark_run(tenant, "2026-01-01", "2027-06-01").status_code == 400
    assert not [h for h in listed(tenant, 2026) if h["custom"]]


def test_leave_skips_every_day_of_a_run(tenant, portal):
    emp = make_employee(tenant, password="EmpPass123")
    mark_run(tenant, "2026-09-08", "2026-09-10")       # Tuesday to Thursday
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    res = portal.post("/api/employee/leave", json={"leave_type": "annual", "start_date": "2026-09-07", "end_date": "2026-09-11"})
    assert res.status_code == 200, res.text
    assert tenant.get("/api/employees/%d" % emp["id"]).json()["leave_balance"]["annual_pending"] == 2.0


# --- every employee has the day off -------------------------------------------

def test_leave_is_not_charged_for_a_marked_day(tenant, portal):
    emp = make_employee(tenant, password="EmpPass123")
    mark(tenant, "2026-09-09")            # a Wednesday inside the week asked for
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    res = portal.post("/api/employee/leave", json={"leave_type": "annual", "start_date": "2026-09-07", "end_date": "2026-09-11"})
    assert res.status_code == 200, res.text
    d = tenant.get("/api/employees/%d" % emp["id"]).json()
    assert d["leave_balance"]["annual_pending"] == 4.0, "Monday to Friday is five days, less the holiday"


def test_leave_on_nothing_but_a_marked_day_is_refused(tenant, portal):
    emp = make_employee(tenant, password="EmpPass123")
    mark(tenant, "2026-09-09")
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    res = portal.post("/api/employee/leave", json={"leave_type": "annual", "start_date": "2026-09-09", "end_date": "2026-09-09"})
    assert res.status_code == 400 and "no working days" in res.json()["detail"]


def test_the_clock_says_today_is_a_holiday(tenant, portal):
    work_every_day(tenant)
    emp = make_employee(tenant, password="EmpPass123")
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    before = portal.get("/api/employee/attendance/today").json()
    assert before["is_working_day"] is True and before["holiday"] == ""
    res = mark(tenant, datetime.now().strftime("%Y-%m-%d"), "Founders' Day")
    assert res.status_code == 200, res.text
    after = portal.get("/api/employee/attendance/today").json()
    assert after["is_working_day"] is False and after["holiday"] == "Founders' Day"


def test_nobody_is_counted_absent_on_a_marked_day(tenant):
    make_employee(tenant, password="EmpPass123")
    today = datetime.now().strftime("%Y-%m-%d")
    assert tenant.get("/api/attendance/stats").json()["absent"] == 1
    mark(tenant, today)
    stats = tenant.get("/api/attendance/stats").json()
    assert stats["absent"] == 0 and stats["holiday"] == "Founders' Day"


def test_working_days_skip_the_marked_ones():
    from app.services.employee_portal import working_days_between
    assert working_days_between("2026-09-07", "2026-09-11") == 5.0
    assert working_days_between("2026-09-07", "2026-09-11", holidays={"2026-09-09": "x"}) == 4.0
    # A weekend holiday takes nothing off a week that was not working it anyway.
    assert working_days_between("2026-09-07", "2026-09-13", holidays={"2026-09-12": "x"}) == 5.0
