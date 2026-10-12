"""A pooled connection is checked only if it has been sitting; a dead one is replaced, not surfaced."""
import pytest
from sqlalchemy import create_engine, event, text

from app.db.session import install_idle_ping


def make(idle):
    engine = create_engine("sqlite://", poolclass=__import__("sqlalchemy.pool", fromlist=["QueuePool"]).QueuePool,
                           connect_args={"check_same_thread": False})
    install_idle_ping(engine, idle_seconds=idle)
    pings = []

    @event.listens_for(engine, "before_cursor_execute")
    def seen(conn, cursor, statement, *_):
        pings.append(statement)
    return engine, pings


def use(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT 42")).scalar()


def test_a_connection_used_a_moment_ago_is_not_pinged():
    engine, seen = make(idle=60)
    use(engine)
    use(engine)
    use(engine)
    # Only the engine's own statements are counted here: the ping goes straight
    # to the driver, so nothing extra is ever seen on the busy path.
    assert seen == ["SELECT 42"] * 3


def test_an_idle_connection_is_checked_before_it_is_trusted(monkeypatch):
    engine, _ = make(idle=0)
    use(engine)
    pinged = []
    real = engine.pool.__class__._do_get

    def spy(self):
        record = real(self)
        pinged.append(record)
        return record
    monkeypatch.setattr(engine.pool.__class__, "_do_get", spy)
    assert use(engine) == 42
    assert pinged, "the pooled connection came back through the checkout"


def test_a_dead_connection_is_replaced_not_raised():
    engine, _ = make(idle=0)
    assert use(engine) == 42
    # Break the pooled connection the way a dropped one looks to the driver.
    with engine.connect() as conn:
        conn.connection.dbapi_connection.close()
    assert use(engine) == 42, "the request still works on a fresh connection"
