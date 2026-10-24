"""Start-up asks the database what it has once, and only acts on what is missing.

Every statement sent to a hosted database is a round trip - a quarter of a second or more from far away. Start-up used to
send an ALTER TABLE ... ADD COLUMN IF NOT EXISTS for each of about 350 columns and check each of about 265 tables on its
own, nearly all of them doing nothing: several minutes before the first page could load. These keep that from creeping back,
and keep the thing it replaced - adding what really is missing - working.
"""
import re

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect

from app.db import migrations as M

COLUMNS_QUERY = "FROM information_schema.columns WHERE table_schema = current_schema()"
TABLES_QUERY = "FROM information_schema.tables WHERE table_schema = current_schema()"
INDEXES_QUERY = "FROM pg_indexes WHERE schemaname = current_schema()"


class Rows(list):
    def fetchone(self):
        return self[0] if self else None

    def fetchall(self):
        return list(self)


class FakeConnection:
    """What ensure_columns sees of Postgres: it records every statement and answers the questions it asks."""
    def __init__(self, columns=(), break_columns_query=False, tables=(), indexes=()):
        self.columns = set(columns)
        self.tables = set(tables)
        self.indexes = set(indexes)
        self.sent = []
        self.rollbacks = 0
        self.break_columns_query = break_columns_query

    def execute(self, statement, *args, **kwargs):
        sql = " ".join(str(statement).split())
        self.sent.append(sql)
        if COLUMNS_QUERY in sql:
            if self.break_columns_query:
                raise RuntimeError("no permission")
            return Rows(sorted(self.columns))
        if TABLES_QUERY in sql:
            return Rows((t,) for t in sorted(self.tables))
        if INDEXES_QUERY in sql:
            return Rows((i,) for i in sorted(self.indexes))
        # every other question ("is there a line_items.name?") is answered "yes"
        return Rows([("assets",), ("brand",)])

    def commit(self):
        pass

    def rollback(self):
        self.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def adds(conn):
    return [s for s in conn.sent if re.search(r"ADD COLUMN", s, re.I)]


def added(conn):
    out = set()
    for s in adds(conn):
        m = re.search(r"ALTER TABLE (\w+) ADD COLUMN (?:IF NOT EXISTS )?(\w+)", s, re.I)
        out.add((m.group(1).lower(), m.group(2).lower()))
    return out


def run_ensure_columns(monkeypatch, conn):
    class FakeEngine:
        def connect(self):
            return conn
    monkeypatch.setattr(M, "engine", FakeEngine())
    monkeypatch.setattr(M, "DATABASE_URL", "postgresql://fake")
    M.ensure_columns()


# --- the connection wrapper -----------------------------------------------------------------------------------------

def test_a_column_the_database_has_is_not_sent_and_one_it_lacks_is():
    raw = FakeConnection(columns={("invoices", "currency")})
    conn = M.SkipWhatExists(raw)
    conn.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'INR'")
    conn.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS brand_new INTEGER")
    sent = [s for s in raw.sent if "ALTER" in s]
    assert sent == ["ALTER TABLE invoices ADD COLUMN IF NOT EXISTS brand_new INTEGER"]
    assert sum(1 for s in raw.sent if COLUMNS_QUERY in s) == 1, "what exists is read once, however many columns are checked"


def test_a_column_just_added_is_not_added_twice():
    raw = FakeConnection()
    conn = M.SkipWhatExists(raw)
    for _ in range(3):
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retention_percent DOUBLE PRECISION")
    assert len(adds(raw)) == 1


def test_names_are_compared_the_way_postgres_does_not_by_case():
    raw = FakeConnection(columns={("invoices", "currency")})
    M.SkipWhatExists(raw).execute("ALTER TABLE Invoices ADD COLUMN IF NOT EXISTS Currency VARCHAR")
    assert adds(raw) == []


def test_a_table_or_index_that_exists_is_not_created_again_and_one_that_does_not_is():
    raw = FakeConnection(tables={"employees"}, indexes={"ix_employees_client_id"})
    conn = M.SkipWhatExists(raw)
    conn.execute("CREATE TABLE IF NOT EXISTS employees ( id SERIAL PRIMARY KEY )")
    conn.execute("CREATE TABLE IF NOT EXISTS payslips ( id SERIAL PRIMARY KEY )")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_employees_client_id ON employees (client_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_new ON employees (email)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_new ON employees (status)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_new ON employees (status)")        # just made: not made twice
    made = [s for s in raw.sent if s.startswith("CREATE")]
    assert made == ["CREATE TABLE IF NOT EXISTS payslips ( id SERIAL PRIMARY KEY )",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_new ON employees (email)",
                    "CREATE INDEX IF NOT EXISTS ix_new ON employees (status)"]
    reads = [s for s in raw.sent if TABLES_QUERY in s or INDEXES_QUERY in s]
    assert len(reads) == 2, "one read for the tables and one for the indexes, however many are checked"


def test_anything_else_goes_straight_through():
    raw = FakeConnection(columns={("invoices", "currency")})
    conn = M.SkipWhatExists(raw)
    conn.execute("UPDATE invoices SET currency = 'INR' WHERE currency IS NULL")
    conn.execute("ALTER TABLE assets RENAME COLUMN make TO brand")
    conn.execute("ALTER TABLE invoices ADD COLUMN currency2 VARCHAR")         # no IF NOT EXISTS: its own guard decides
    assert raw.sent == ["UPDATE invoices SET currency = 'INR' WHERE currency IS NULL",
                        "ALTER TABLE assets RENAME COLUMN make TO brand",
                        "ALTER TABLE invoices ADD COLUMN currency2 VARCHAR"]


def test_a_rollback_forgets_what_was_added_so_it_is_looked_at_again():
    raw = FakeConnection()
    conn = M.SkipWhatExists(raw)
    conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retention_percent FLOAT")
    conn.rollback()                      # the ALTER was undone with the transaction
    conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retention_percent FLOAT")
    assert len(adds(raw)) == 2 and raw.rollbacks == 1


def test_when_the_columns_cannot_be_read_everything_is_added_as_it_always_was():
    raw = FakeConnection(columns={("invoices", "currency")}, break_columns_query=True)
    conn = M.SkipWhatExists(raw)
    conn.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS currency VARCHAR")
    assert len(adds(raw)) == 1 and raw.rollbacks == 1, "the failed read is rolled back so the transaction stays usable"


# --- ensure_columns as a whole ---------------------------------------------------------------------------------------

def creates(conn):
    """The CREATE TABLE / CREATE INDEX IF NOT EXISTS statements: name -> statement."""
    out = {}
    for s in conn.sent:
        m = re.match(r"CREATE (?:UNIQUE )?(TABLE|INDEX) IF NOT EXISTS (\w+)", s)
        if m:
            out[(m.group(1), m.group(2).lower())] = s
    return out


def test_a_database_that_is_up_to_date_gets_no_creation_statements_at_all(monkeypatch):
    first = FakeConnection()
    run_ensure_columns(monkeypatch, first)
    everything, wanted = added(first), creates(first)
    assert len(everything) > 300 and len(wanted) > 100, "these are what start-up used to send one by one"

    second = FakeConnection(columns=everything,
                            tables={n for (k, n) in wanted if k == "TABLE"}, indexes={n for (k, n) in wanted if k == "INDEX"})
    run_ensure_columns(monkeypatch, second)
    assert adds(second) == [] and creates(second) == {}, "%d ADD COLUMN and %d CREATE statements for what was already there" % (len(adds(second)), len(creates(second)))
    assert len(second.sent) < len(first.sent) - 400


def test_a_database_missing_two_columns_gets_exactly_those_two(monkeypatch):
    first = FakeConnection()
    run_ensure_columns(monkeypatch, first)
    everything = added(first)
    lacking = sorted(everything)[:2]

    second = FakeConnection(columns=everything - set(lacking))
    run_ensure_columns(monkeypatch, second)
    assert added(second) == set(lacking)


# --- the tables ----------------------------------------------------------------------------------------------------

def three_tables():
    meta = MetaData()
    for name in ("alpha", "beta", "gamma"):
        Table(name, meta, Column("id", Integer, primary_key=True), Column("name", String))
    return meta


def test_only_the_tables_that_are_missing_are_created_and_checked(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///%s" % (tmp_path / "t.db"))
    meta = three_tables()
    meta.tables["alpha"].create(engine)

    checked = []
    real = engine.dialect.has_table
    monkeypatch.setattr(engine.dialect, "has_table", lambda conn, name, *a, **k: (checked.append(name), real(conn, name, *a, **k))[1])

    assert sorted(M.create_missing_tables(meta, engine)) == ["beta", "gamma"]
    assert sorted(inspect(engine).get_table_names()) == ["alpha", "beta", "gamma"]
    assert "alpha" not in checked, "a table that is there is not asked about again"
    assert M.create_missing_tables(meta, engine) == []


def test_a_new_table_that_points_at_an_existing_one_is_created(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "t.db"))
    meta = MetaData()
    parent = Table("parent", meta, Column("id", Integer, primary_key=True))
    parent.create(engine)
    from sqlalchemy import ForeignKey
    Table("child", meta, Column("id", Integer, primary_key=True), Column("parent_id", Integer, ForeignKey("parent.id")))
    assert M.create_missing_tables(meta, engine) == ["child"]
    assert [fk["referred_table"] for fk in inspect(engine).get_foreign_keys("child")] == ["parent"]


def test_the_real_models_are_created_on_an_empty_database(tmp_path):
    from app import models
    engine = create_engine("sqlite:///%s" % (tmp_path / "empty.db"))
    created = M.create_missing_tables(models.Base.metadata, engine)
    assert len(created) > 200 and set(created) == set(inspect(engine).get_table_names())
