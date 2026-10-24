"""The database connection: which database, how connections are kept, and the session each request gets."""
import logging
import os
import threading
import time
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

# SQLAlchemy 1.4+ requires postgresql:// instead of postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Whether this is a real deployment rather than somebody's laptop. Railway
# sets these itself; ENVIRONMENT is the manual override for anywhere else.
IS_DEPLOYED = bool(
    os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_NAME")
    or os.getenv("ENVIRONMENT", "").lower() in ("production", "staging"))

if not DATABASE_URL:
    if IS_DEPLOYED:
        # Falling back here would put the database on the container's own disk,
        # which is thrown away on every redeploy. The app would work perfectly
        # and quietly lose everything each time it shipped, so it refuses to
        # start instead - a deploy that fails loudly costs an afternoon, and
        # one that fails this way costs the data.
        raise RuntimeError(
            "DATABASE_URL is not set. This looks like a deployment, and "
            "falling back to a local SQLite file would put the database on "
            "disposable container disk - every redeploy would wipe it. Set "
            "DATABASE_URL to the Postgres connection string in the service "
            "Variables tab and deploy again.")
    print("No DATABASE_URL set - using a local SQLite file for development.")
    DATABASE_URL = "sqlite:///./invoicing.db"

# Neon closes idle connections and sits behind a pooler, so a connection left
# in the pool is often already dead by the time it is handed back out, and
# something has to check before it is trusted - the difference between a
# request working and a random OperationalError under light traffic.
#
# pool_pre_ping checks on every checkout: one extra round trip per request,
# which on a database across an ocean is most of a second each time, even for
# a connection used a moment ago. install_idle_ping checks only connections
# that have been sitting; a busy one is trusted, and a dead one is still
# replaced rather than failing the request. SQLite is a local file and needs
# neither.
# 5 seconds, not 20: Neon's proxy drops a connection that has been quiet for a few seconds, and a "busy" one that was
# trusted after 20 failed about one request in three with "SSL connection has been closed unexpectedly".
PING_AFTER_IDLE_SECONDS = float(os.getenv("DB_PING_AFTER_IDLE", "5"))
ENGINE_OPTIONS = {}

if DATABASE_URL.startswith("sqlite"):
    # One file, many threads: FastAPI serves each request on its own.
    ENGINE_OPTIONS["connect_args"] = {"check_same_thread": False}
else:
    ENGINE_OPTIONS.update({
        # A healthy connection is kept: every reconnect is a TLS handshake and a
        # login across the network, seconds on a bad day. A connection Neon has
        # dropped is found by the idle ping, so recycling early is not needed
        # to avoid a dead one - this only bounds how long one lives.
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
        "pool_timeout": 30,
        # The connection used last is handed out next. The default hands out the one idle longest, so after any pause
        # a request got a cold connection that had to be checked (a round trip) or replaced (seconds); now it gets the
        # one keep_warm() below has kept busy, and the rest are the spares.
        "pool_use_lifo": True,
        # TCP keepalives, so a network device on the way does not decide a quiet connection is finished and cut it.
        "connect_args": {"keepalives": 1, "keepalives_idle": 10, "keepalives_interval": 5, "keepalives_count": 3},
    })
    # Neon requires TLS. Its dashboard copies a URL with sslmode already on it,
    # but a hand-typed one usually has not, and the failure then reads as a
    # refused connection rather than anything about certificates.
    if "sslmode=" not in DATABASE_URL:
        DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"

engine = create_engine(DATABASE_URL, **ENGINE_OPTIONS)


def _ping(dbapi_connection):
    """SELECT 1 on the driver's own connection, outside a transaction: one round trip, and the connection is left as
    it was found. In a transaction psycopg2 first sends a BEGIN of its own - a second round trip - and leaves the
    connection inside it, where it cannot be switched to autocommit for a request that only reads."""
    outside = getattr(dbapi_connection, "autocommit", None) is False
    if outside:
        dbapi_connection.autocommit = True
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SELECT 1")
        finally:
            cursor.close()
    finally:
        if outside:
            dbapi_connection.autocommit = False


def install_idle_ping(target_engine, idle_seconds=PING_AFTER_IDLE_SECONDS):
    """Check a pooled connection is alive only if it has been idle a while.

    Raising DisconnectionError from a checkout handler makes the pool throw the
    dead connection away and open a fresh one for the same request."""
    import time
    from sqlalchemy import event, exc

    @event.listens_for(target_engine, "checkin")
    def _remember_when_idle_began(dbapi_connection, record):
        record.info["idle_since"] = time.monotonic()

    @event.listens_for(target_engine, "checkout")
    def _ping_if_it_has_been_idle(dbapi_connection, record, proxy):
        since = record.info.get("idle_since")
        if since is None or time.monotonic() - since < idle_seconds:
            return
        try:
            _ping(dbapi_connection)
        except Exception as error:
            raise exc.DisconnectionError(str(error)) from error


if not DATABASE_URL.startswith("sqlite"):
    install_idle_ping(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    note_request()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Keeping round trips out of the way ------------------------------------------------------------------------
#
# From far away every round trip to the database costs a fifth of a second or more, and three of them were spent on
# nothing: psycopg2 opens every transaction with a BEGIN of its own before the first query; closing a session that
# only read sends a ROLLBACK; and a connection that had sat for a few seconds was checked before use. A request that
# only reads now runs without a transaction (get_read_db), and while somebody is using the app the connection the next
# request will get is kept warm (keep_warm), so it needs no check.

_LAST_REQUEST = [0.0]


def note_request():
    _LAST_REQUEST[0] = time.monotonic()


def _read_without_transaction(fairy):
    """Put a pooled connection in autocommit for reading. Only psycopg2's own flag is flipped: SQLAlchemy's
    isolation_level option resets it with a SET on the way back to the pool, which is the round trip saved here."""
    fairy.dbapi_connection.autocommit = True
    fairy.info["reading"] = True


def get_read_db():
    """The session for a request that only reads.

    It runs without a transaction - for reads that is what READ COMMITTED already gives, a fresh view at each
    statement - so there is no BEGIN before the first query and no ROLLBACK at the end: two round trips fewer.
    Never for a request that writes: each statement would commit on its own. The connection goes back to the pool
    as it came (see _back_to_transactions), whatever happens here.
    """
    note_request()
    with read_session() as db:
        yield db


@contextmanager
def read_session():
    """A session that only reads, outside a transaction - see get_read_db. For code that wants a connection of its
    own for a moment, such as a read running beside others (app.core.queries.read_together)."""
    db = SessionLocal()
    db.info["reading"] = True          # see _refuse_writes_when_reading
    try:
        if not DATABASE_URL.startswith("sqlite"):
            _read_without_transaction(db.connection().connection)
        yield db
    finally:
        db.close()


class ReadOnlySessionWrote(RuntimeError):
    """A request that was set up to only read tried to change something."""


def _refuse_writes_when_reading():
    """A session from get_read_db has no transaction around it, so a write in it would commit by itself, a statement
    at a time, with nothing to undo if the next one failed. It must not happen quietly: it is refused, in tests and
    in production alike, and the handler is moved to get_db. (Statements sent as raw SQL text are not seen here.)"""
    from sqlalchemy import event

    @event.listens_for(SessionLocal, "before_flush")
    def _no_flush(session, flush_context, instances):
        if session.info.get("reading") and (
                session.new or session.deleted or any(session.is_modified(o) for o in session.dirty)):
            raise ReadOnlySessionWrote("A read-only request tried to save changes. Use get_db for a request that writes.")

    @event.listens_for(SessionLocal, "do_orm_execute")
    def _no_dml(state):
        if state.session.info.get("reading") and (state.is_insert or state.is_update or state.is_delete):
            raise ReadOnlySessionWrote("A read-only request tried to change data. Use get_db for a request that writes.")


_refuse_writes_when_reading()


def _back_to_transactions(dbapi_connection, record):
    """Every connection returns to the pool in transactions again, however the read that borrowed it ended, so a
    request that writes can never be handed one that commits each statement on its own."""
    if dbapi_connection is not None and record.info.pop("reading", False):
        try:
            dbapi_connection.autocommit = False
        except Exception as error:   # it cannot be trusted any more
            record.invalidate(error)


def install_read_reset(target_engine):
    from sqlalchemy import event
    event.listen(target_engine, "checkin", _back_to_transactions)


KEEP_WARM_FOR = float(os.getenv("DB_KEEP_WARM_FOR", "600"))      # seconds after the last request; 0 = never
SPARE_CONNECTIONS = int(os.getenv("DB_SPARE_CONNECTIONS", "4"))   # opened at start-up and kept warm; 0 = none


def _touch(conn, target_engine):
    """One real statement on a checked-out connection, so it is known to be alive and its idle clock starts again."""
    try:
        if target_engine.dialect.name == "postgresql":
            _read_without_transaction(conn.connection)
        conn.exec_driver_sql("SELECT 1")
    except Exception as error:               # a dropped connection is simply replaced by the next request
        logging.getLogger(__name__).debug("keep-warm: %s", error)


def warm_connections(target_engine, keep):
    """Use up to `keep` of the most recently used idle connections at the same time - a screen sends several requests
    at once and each needs a connection of its own. Always leaves one idle connection alone, so a request arriving
    meanwhile never waits for this or has to open one. Returns how many were used."""
    take = min(keep, target_engine.pool.checkedin() - 1)
    if take < 1:
        return 0
    held = []
    try:
        for _ in range(take):
            held.append(target_engine.connect())
        workers = [threading.Thread(target=_touch, args=(c, target_engine)) for c in held]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
    finally:
        for c in held:
            c.close()
    return len(held)


def keep_warm(target_engine, every=None, active_for=None, keep=None):
    """While somebody is using the app, use the connections the next requests will get every few seconds, so none is
    idle long enough to need checking before use (a round trip) or to be dropped (a new connection: seconds).

    It stops ten minutes after the last request, so a database that sleeps when unused still can."""
    every = every or max(1.0, PING_AFTER_IDLE_SECONDS * 0.6)
    active_for = KEEP_WARM_FOR if active_for is None else active_for
    keep = SPARE_CONNECTIONS if keep is None else keep

    def run():
        while True:
            time.sleep(every)
            try:
                if time.monotonic() - _LAST_REQUEST[0] <= active_for:
                    warm_connections(target_engine, keep)
            except Exception as error:
                logging.getLogger(__name__).debug("keep-warm: %s", error)
    threading.Thread(target=run, name="db-keep-warm", daemon=True).start()


def open_spare_connections(target_engine, count=None):
    """Open a few connections together at start-up. A screen sends several requests at once, and each one that
    found no idle connection waited one to four seconds for a new one across the ocean."""
    count = min(SPARE_CONNECTIONS if count is None else count, ENGINE_OPTIONS.get("pool_size", 5))
    if count < 1:
        return
    together = threading.Barrier(count)

    def one():
        try:
            with target_engine.connect() as conn:
                _touch(conn, target_engine)
                together.wait(timeout=60)   # all held at once, so the pool really holds `count` of them
        except Exception as error:
            together.abort()
            logging.getLogger(__name__).debug("spare connection: %s", error)
    for _ in range(count):
        threading.Thread(target=one, name="db-spare", daemon=True).start()


if not DATABASE_URL.startswith("sqlite"):
    install_read_reset(engine)
