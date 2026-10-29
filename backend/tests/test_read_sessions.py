"""A request that only reads runs without a transaction around it, and nothing that writes ever does.

From far away every round trip to the database is a fifth of a second or more. psycopg2 spends one on a BEGIN before
the first query and one on a ROLLBACK when the session closes, and a connection that has sat for a few seconds costs
another to check. A read-only request now skips all three (get_read_db); these tests hold the line that makes that safe:
a read session refuses to write, a connection always goes back to the pool ready for a writer, and the connections
kept warm are never all taken from under a request.
"""
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import QueuePool

from app import db as database
from app import models
from app.db import session as S
from conftest import make_employee


class FakeRecord:
    def __init__(self, **info):
        self.info = dict(info)
        self.invalidated = None

    def invalidate(self, error):
        self.invalidated = error


class FakeDriverConnection:
    """What psycopg2's connection looks like to the pool: an autocommit switch and a cursor."""
    def __init__(self, autocommit=False, fail_on=None):
        self.autocommit = autocommit
        self.fail_on = fail_on
        self.ran = []

    def cursor(self):
        outer = self

        class Cursor:
            def execute(self, sql):
                outer.ran.append((sql, outer.autocommit))
                if outer.fail_on:
                    raise outer.fail_on

            def close(self):
                pass
        return Cursor()


# --- the session ---------------------------------------------------------------------------------------------------

def test_a_read_session_reads_and_refuses_to_write(tenant):
    gen = S.get_read_db()
    db = next(gen)
    try:
        assert db.query(models.DBClient).count() >= 1
        row = models.DBSettings(client_id=None, key="read-session-" + uuid.uuid4().hex[:6], value="x")
        db.add(row)
        with pytest.raises(S.ReadOnlySessionWrote):
            db.flush()
        db.expunge(row)
        with pytest.raises(S.ReadOnlySessionWrote):
            db.query(models.DBSettings).filter(models.DBSettings.key == "nothing").update({"value": "y"})
        with pytest.raises(S.ReadOnlySessionWrote):
            db.query(models.DBSettings).filter(models.DBSettings.key == "nothing").delete()
        db.commit()               # nothing changed, so nothing to refuse
    finally:
        gen.close()


def test_a_read_session_refuses_a_change_to_a_row_it_read(tenant):
    make_employee(tenant)
    gen = S.get_read_db()
    db = next(gen)
    try:
        emp = db.query(models.DBEmployee).first()
        emp.job_title = "changed on a read"
        with pytest.raises(S.ReadOnlySessionWrote):
            db.commit()
    finally:
        db.rollback()
        gen.close()


def test_an_ordinary_session_still_writes(tenant):
    key = "ordinary-" + uuid.uuid4().hex[:6]
    gen = database.get_db()
    db = next(gen)
    try:
        db.add(models.DBSettings(client_id=None, key=key, value="x"))
        db.commit()
        assert db.query(models.DBSettings).filter(models.DBSettings.key == key).count() == 1
        db.query(models.DBSettings).filter(models.DBSettings.key == key).delete()
        db.commit()
    finally:
        gen.close()


# --- the connection ------------------------------------------------------------------------------------------------

def test_the_idle_check_runs_outside_a_transaction_and_puts_the_connection_back_as_it_was():
    conn = FakeDriverConnection(autocommit=False)
    S._ping(conn)
    assert conn.ran == [("SELECT 1", True)], "run in autocommit, so psycopg2 sends no BEGIN of its own"
    assert conn.autocommit is False


def test_the_idle_check_leaves_a_connection_already_outside_a_transaction_alone():
    conn = FakeDriverConnection(autocommit=True)
    S._ping(conn)
    assert conn.ran == [("SELECT 1", True)] and conn.autocommit is True


def test_a_failed_idle_check_still_puts_the_switch_back_and_the_failure_gets_out():
    conn = FakeDriverConnection(autocommit=False, fail_on=OSError("the connection was dropped"))
    with pytest.raises(OSError):
        S._ping(conn)
    assert conn.autocommit is False


def test_a_connection_that_was_used_for_reading_goes_back_in_transactions():
    conn, record = FakeDriverConnection(autocommit=True), FakeRecord(reading=True, idle_since=1.0)
    S._back_to_transactions(conn, record)
    assert conn.autocommit is False and "reading" not in record.info and record.invalidated is None


def test_a_connection_not_used_for_reading_is_left_alone():
    conn, record = FakeDriverConnection(autocommit=False), FakeRecord()
    S._back_to_transactions(conn, record)
    assert conn.autocommit is False and record.invalidated is None


def test_a_connection_that_cannot_be_switched_back_is_thrown_away_not_reused():
    class Broken:
        @property
        def autocommit(self):
            return True

        @autocommit.setter
        def autocommit(self, value):
            raise RuntimeError("connection already closed")
    record = FakeRecord(reading=True)
    S._back_to_transactions(Broken(), record)
    assert isinstance(record.invalidated, RuntimeError)


def test_a_dropped_connection_is_still_replaced_not_raised(monkeypatch):
    engine = create_engine("sqlite://", poolclass=QueuePool, connect_args={"check_same_thread": False})
    S.install_idle_ping(engine, idle_seconds=0)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
    with engine.connect() as conn:
        conn.connection.dbapi_connection.close()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 42")).scalar() == 42


# --- the warm connections -------------------------------------------------------------------------------------------

def pool_engine(size=5):
    engine = create_engine("sqlite://", poolclass=QueuePool, pool_size=size, max_overflow=0, pool_use_lifo=True,
                           connect_args={"check_same_thread": False})
    S.install_idle_ping(engine, idle_seconds=60)
    return engine


def idle_connections(engine, n):
    held = [engine.connect() for _ in range(n)]
    for c in held:
        c.exec_driver_sql("SELECT 1")
    for c in held:
        c.close()


def test_warming_uses_the_recent_connections_together_and_leaves_one_alone():
    engine = pool_engine()
    idle_connections(engine, 4)
    seen = []
    event.listen(engine, "before_cursor_execute", lambda *a: seen.append(a[2]))
    assert S.warm_connections(engine, keep=3) == 3
    assert seen == ["SELECT 1"] * 3
    assert engine.pool.checkedin() == 4, "every one went back, and none was opened for this"
    assert S.warm_connections(engine, keep=10) == 3, "never all four: one is left for a request arriving meanwhile"


def test_warming_does_nothing_with_a_single_idle_connection():
    engine = pool_engine()
    idle_connections(engine, 1)
    assert S.warm_connections(engine, keep=3) == 0


def test_warming_restarts_the_idle_clock_with_real_traffic():
    engine = pool_engine()
    idle_connections(engine, 3)
    with engine.connect() as c:
        raw = c.connection
        before = raw.info["idle_since"]
    # The clock reads when a connection was last put back; a warm-up that touched it would be a lie unless it did I/O.
    seen = []
    event.listen(engine, "before_cursor_execute", lambda *a: seen.append(a[2]))
    S.warm_connections(engine, keep=2)
    assert seen, "the connection was really used, not just checked out and back"
    with engine.connect() as c:
        assert c.connection.info["idle_since"] >= before


# --- the pages -----------------------------------------------------------------------------------------------------

def trips(client, path):
    seen = []

    def note(conn, cursor, statement, *_):
        line = " ".join(statement.split())
        if not line.startswith("PRAGMA") and not (line.startswith("INSERT") and seen and seen[-1] == line):
            seen.append(line)
    event.listen(database.engine, "before_cursor_execute", note)
    try:
        res = client.get(path)
    finally:
        event.remove(database.engine, "before_cursor_execute", note)
    assert res.status_code == 200, (path, res.text)
    return seen, res


@pytest.fixture
def people_data(tenant):
    """Staff with attendance, leave, overtime and a payslip: everything the People pages read."""
    staff = [make_employee(tenant) for _ in range(4)]
    s = database.SessionLocal()
    try:
        client_id = s.query(models.DBEmployee).filter(models.DBEmployee.id == staff[0]["id"]).one().client_id
        for e in staff:
            s.add(models.DBAttendance(client_id=client_id, employee_id=e["id"], date="2026-10-01", clock_in="09:00:00",
                                      clock_out="17:00:00", total_hours=8.0, status="completed"))
            s.add(models.DBLeaveRequest(client_id=client_id, employee_id=e["id"], leave_type="annual",
                                        start_date="2026-10-05", end_date="2026-10-06", days=2.0, status="approved"))
            s.add(models.DBOvertimeLog(client_id=client_id, employee_id=e["id"], date="2026-10-01", hours=2.0,
                                       announced_by="HR", status="announced"))
        s.commit()
    finally:
        s.close()
    slip = tenant.post("/api/payslips", json={"employee_id": staff[0]["id"], "period_start": "2026-10-01",
                                              "period_end": "2026-10-31", "pay_date": "2026-10-31",
                                              "basic_salary": 3000}).json()
    return {"staff": staff, "slip": slip["id"]}


def test_every_people_page_loads_on_a_read_session(tenant, people_data):
    eid, slip = people_data["staff"][0]["id"], people_data["slip"]
    for path in ["/api/employees", "/api/employees?status=active", "/api/employees/%d" % eid,
                 "/api/employees/%d?view=profile" % eid, "/api/departments", "/api/hr/stats", "/api/hr/levels",
                 "/api/hr/suggest-email?first_name=a&last_name=b", "/api/hr/org-domain", "/api/master/access",
                 "/api/org-chart", "/api/onboarding/hub", "/api/onboarding/pipeline", "/api/onboarding/templates",
                 "/api/onboarding/document-queue", "/api/onboarding/expiring-documents",
                 "/api/employees/%d/onboarding" % eid, "/api/employees/%d/document-requests" % eid,
                 "/api/employees/%d/pay-details" % eid, "/api/employees/%d/ytd" % eid,
                 "/api/employees/%d/leave-balance" % eid, "/api/employees/%d/leave" % eid,
                 "/api/employees/%d/goals" % eid, "/api/employees/%d/documents" % eid,
                 "/api/attendance", "/api/attendance/today", "/api/attendance/stats", "/api/attendance/live",
                 "/api/attendance/analytics", "/api/attendance/export", "/api/attendance/overtime/logs",
                 "/api/attendance/settings", "/api/attendance/by-site",
                 "/api/leave/requests", "/api/payslips", "/api/payslips/%d" % slip, "/api/payroll/auto"]:
        res = tenant.get(path)
        assert res.status_code == 200, (path, res.status_code, res.text[:200])


def test_the_attendance_export_asks_once_for_everybody_not_once_per_row(tenant, people_data):
    few, _ = trips(tenant, "/api/attendance/export")
    s = database.SessionLocal()
    try:
        client_id = s.get(models.DBEmployee, people_data["staff"][0]["id"]).client_id
        for e in people_data["staff"]:
            for day in range(2, 12):
                s.add(models.DBAttendance(client_id=client_id, employee_id=e["id"], date="2026-09-%02d" % day,
                                          clock_in="09:00:00", status="present"))
        s.commit()
    finally:
        s.close()
    many, res = trips(tenant, "/api/attendance/export")
    assert len(res.json()) == 44 and len(many) <= len(few), "%d statements for 4 rows, %d for 44" % (len(few), len(many))


def test_a_payslip_opens_in_a_handful_of_reads_and_keeps_its_figures(tenant, people_data):
    eid, slip = people_data["staff"][0]["id"], people_data["slip"]
    sent, res = trips(tenant, "/api/payslips/%d" % slip)
    assert len(sent) <= 8, "%d statements:\n%s" % (len(sent), "\n".join(s[:110] for s in sent))
    body = res.json()
    assert body["employee"]["full_name"].startswith("Test ") and body["ytd"]["payslip_count"] == 1
    assert body["ytd"]["year"] == "2026" and body["ytd"]["gross_pay"] > 0
    assert body["days"]["total"] == 31 and "company" in body
    # The same totals come from the employee's own endpoint.
    assert tenant.get("/api/employees/%d/ytd?year=2026" % eid).json() == body["ytd"]


def test_year_to_date_totals_for_somebody_who_is_not_there_are_still_a_404(tenant, people_data):
    assert tenant.get("/api/employees/999999/ytd").status_code == 404
    quiet = tenant.get("/api/employees/%d/ytd?year=1999" % people_data["staff"][1]["id"])
    assert quiet.status_code == 200 and quiet.json()["payslip_count"] == 0


def test_somebody_elses_employee_has_no_year_to_date_either(tenant, second_tenant, people_data):
    theirs = make_employee(second_tenant)
    assert tenant.get("/api/employees/%d/ytd" % theirs["id"]).status_code == 404
