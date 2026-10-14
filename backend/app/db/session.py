"""The database connection: which database, how connections are kept, and the session each request gets."""
import os

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
        # TCP keepalives, so a network device on the way does not decide a quiet connection is finished and cut it.
        "connect_args": {"keepalives": 1, "keepalives_idle": 10, "keepalives_interval": 5, "keepalives_count": 3},
    })
    # Neon requires TLS. Its dashboard copies a URL with sslmode already on it,
    # but a hand-typed one usually has not, and the failure then reads as a
    # refused connection rather than anything about certificates.
    if "sslmode=" not in DATABASE_URL:
        DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"

engine = create_engine(DATABASE_URL, **ENGINE_OPTIONS)


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
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("SELECT 1")
            finally:
                cursor.close()
        except Exception as error:
            raise exc.DisconnectionError(str(error)) from error


if not DATABASE_URL.startswith("sqlite"):
    install_idle_ping(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
