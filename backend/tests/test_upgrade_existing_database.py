"""A database made before the payroll work starts up cleanly, keeps its data, and gets the new columns, tables and rules.

The suite otherwise only ever builds a fresh database, which would never show a column or table an old one lacks."""
import os
import sqlite3
import tempfile
import uuid

import pytest
from sqlalchemy import create_engine, text

from app import models
from app.db import migrations as M

NEW_TABLES = ("payroll_months", "leave_ledger")


@pytest.fixture
def old_database(monkeypatch):
    """A SQLite database in the shape it had before: the new tables and columns gone, overtime without its rule."""
    if sqlite3.sqlite_version_info < (3, 35):
        pytest.skip("this builds the old shape with ALTER TABLE ... DROP COLUMN, which needs SQLite 3.35 or newer")
    path = os.path.join(tempfile.gettempdir(), "old_shape_%s.db" % uuid.uuid4().hex)
    eng = create_engine("sqlite:///" + path)
    models.Base.metadata.create_all(eng)
    with eng.begin() as conn:
        for table in NEW_TABLES:
            conn.execute(text("DROP TABLE %s" % table))
        for table, column, _ in M.HR_PAYROLL_COLUMNS:
            conn.execute(text("ALTER TABLE %s DROP COLUMN %s" % (table, column)))
        # overtime as it was: no unique rule on (employee, date), so a day could be there twice
        conn.execute(text("DROP TABLE overtime_logs"))
        conn.execute(text("CREATE TABLE overtime_logs (id INTEGER PRIMARY KEY, client_id INTEGER, employee_id INTEGER NOT NULL, "
                          "date VARCHAR NOT NULL, hours FLOAT, reason VARCHAR, announced_by VARCHAR, status VARCHAR, created_at VARCHAR)"))
        conn.execute(text("INSERT INTO clients (id, company_name, email) VALUES (1, 'Old Co', 'old@example.com')"))
        conn.execute(text("INSERT INTO employees (id, client_id, first_name, last_name, email, salary, status) "
                          "VALUES (1, 1, 'Asha', 'Rao', 'asha@example.com', 30000, 'active')"))
        conn.execute(text("INSERT INTO payslips (id, client_id, employee_id, number, period_start, period_end, gross_pay, net_pay, status) "
                          "VALUES (1, 1, 1, 'PS-0001', '2026-01-01', '2026-01-31', 30000, 27000, 'Paid')"))
        conn.execute(text("INSERT INTO attendance_settings (id, client_id, office_name) VALUES (1, 1, 'Head Office')"))
        for oid, hours in ((1, 2.0), (2, 3.0), (3, 1.0)):                        # three entries for one day
            conn.execute(text("INSERT INTO overtime_logs (id, client_id, employee_id, date, hours) VALUES (%d, 1, 1, '2026-01-05', %s)" % (oid, hours)))
        conn.execute(text("INSERT INTO overtime_logs (id, client_id, employee_id, date, hours) VALUES (4, 1, 1, '2026-01-06', 4.0)"))
    monkeypatch.setattr(M, "engine", eng)
    monkeypatch.setattr(M, "DATABASE_URL", "sqlite:///" + path)
    yield eng
    eng.dispose()
    try:
        os.remove(path)
    except OSError:
        pass


def columns(eng, table):
    with eng.connect() as conn:
        return {r[1] for r in conn.execute(text("PRAGMA table_info(%s)" % table))}


def start_up(eng):
    M.create_missing_tables(models.Base.metadata, eng)
    M.migrate_sqlite()


def test_the_old_database_really_lacks_everything_first(old_database):
    for table, column, _ in M.HR_PAYROLL_COLUMNS:
        assert column not in columns(old_database, table)
    with old_database.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert not set(NEW_TABLES) & tables


def test_start_up_adds_every_column_and_table(old_database):
    errors_before = len(M.MIGRATION_ERRORS)
    start_up(old_database)
    for table, column, _ in M.HR_PAYROLL_COLUMNS:
        assert column in columns(old_database, table), "%s.%s was not added" % (table, column)
    with old_database.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert set(NEW_TABLES) <= tables
    assert len(M.MIGRATION_ERRORS) == errors_before, M.MIGRATION_ERRORS[errors_before:]


def test_existing_people_get_the_right_defaults_and_keep_their_data(old_database):
    start_up(old_database)
    with old_database.connect() as conn:
        e = conn.execute(text("SELECT first_name, salary, pf_enabled, esi_enabled, pt_enabled, pt_state, bank_ifsc, "
                              "probation_end_date, contract_end_date FROM employees WHERE id = 1")).one()
        p = conn.execute(text("SELECT number, net_pay, working_days, lop_days, paid_days, professional_tax, employer_pf, "
                              "employer_epf, employer_eps, employer_esi FROM payslips WHERE id = 1")).one()
        a = conn.execute(text("SELECT late_threshold, late_penalty_lop, auto_email_on_approval FROM attendance_settings WHERE id = 1")).one()
    assert tuple(e) == ("Asha", 30000, 1, 1, 1, "TS", "", None, None), "PF, ESI and PT are on for everybody until switched off"
    assert tuple(p) == ("PS-0001", 27000, 0, 0, 0, 0, 0, 0, 0, 0), "an old payslip keeps its figures; the new ones read as nothing"
    assert tuple(a) == (3, 0.5, 0), "the company's late rule starts at the defaults, and e-mailing on approval is off"


def test_duplicate_overtime_is_cleaned_to_the_latest_and_then_cannot_recur(old_database):
    start_up(old_database)
    with old_database.connect() as conn:
        rows = conn.execute(text("SELECT id, date, hours FROM overtime_logs ORDER BY id")).fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [(3, "2026-01-05", 1.0), (4, "2026-01-06", 4.0)], "the newest entry of a day stays"
    with pytest.raises(Exception):
        with old_database.begin() as conn:
            conn.execute(text("INSERT INTO overtime_logs (client_id, employee_id, date, hours) VALUES (1, 1, '2026-01-05', 9)"))


def test_start_up_twice_changes_nothing_more(old_database):
    start_up(old_database)
    with old_database.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM overtime_logs")).scalar()
    start_up(old_database)
    with old_database.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM overtime_logs")).scalar() == before
        assert conn.execute(text("SELECT count(*) FROM employees")).scalar() == 1


def test_the_upgraded_database_works_with_the_application_models(old_database):
    """What the ORM reads and writes on the upgraded database, not only what the catalogue says."""
    from sqlalchemy.orm import sessionmaker
    start_up(old_database)
    s = sessionmaker(bind=old_database)()
    try:
        emp = s.query(models.DBEmployee).filter(models.DBEmployee.id == 1).one()
        assert (emp.pf_enabled, emp.esi_enabled, emp.pt_enabled, emp.pt_state) == (True, True, True, "TS")
        slip = s.query(models.DBPayslip).one()
        assert (slip.professional_tax, slip.paid_days) == (0, 0)
        s.add(models.DBPayrollMonth(client_id=1, month="2026-01", status="Draft"))
        s.add(models.DBLeaveLedger(client_id=1, employee_id=1, leave_type="annual", kind="accrual", period="2026-01",
                                   entry_date="2026-01-01", days=2.0))
        s.commit()
        assert s.query(models.DBPayrollMonth).count() == 1 and s.query(models.DBLeaveLedger).count() == 1
    finally:
        s.close()
