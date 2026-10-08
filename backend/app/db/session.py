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
# in the pool is often already dead by the time it is handed back out.
# pool_pre_ping spends one round trip checking, which is the difference
# between a request working and a random OperationalError under light traffic.
ENGINE_OPTIONS = {"pool_pre_ping": True}

if DATABASE_URL.startswith("sqlite"):
    # One file, many threads: FastAPI serves each request on its own.
    ENGINE_OPTIONS["connect_args"] = {"check_same_thread": False}
else:
    ENGINE_OPTIONS.update({
        # Recycle before Neon's own idle timeout rather than after it.
        "pool_recycle": 280,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
        "pool_timeout": 30,
    })
    # Neon requires TLS. Its dashboard copies a URL with sslmode already on it,
    # but a hand-typed one usually has not, and the failure then reads as a
    # refused connection rather than anything about certificates.
    if "sslmode=" not in DATABASE_URL:
        DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"

engine = create_engine(DATABASE_URL, **ENGINE_OPTIONS)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
