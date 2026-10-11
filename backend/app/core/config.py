"""Environment, logging, time zone, the secret key and the limits the rest of the app reads."""
import logging
import os
import secrets
import time

from dotenv import load_dotenv

from app import db as database


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()
# The business runs on Indian time; the server it is hosted on runs on UTC.
# Every clock-in, diary stamp, approval and chat message took the server's
# clock, five and a half hours behind the site. The POSIX form needs no
# time-zone database on the server image, and TZ still overrides it.
os.environ.setdefault("TZ", "IST-5:30")
if hasattr(time, "tzset"):
    time.tzset()


def generate_secret_key() -> str:
    return secrets.token_hex(32)


SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY == "generate_a_random_secret_string":
    if database.IS_DEPLOYED:
        # On a container the generated key cannot be persisted, so it differs
        # on every boot and signs the whole tenancy out each redeploy. That is
        # a security setting quietly degrading rather than a missing one, so
        # the deploy stops here.
        raise RuntimeError(
            "SECRET_KEY is not set. Sessions are signed with it, so a "
            "generated one would change on every redeploy and sign every user "
            "out. Generate one with "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"` and "
            "set it in the service Variables tab.")
    SECRET_KEY = generate_secret_key()
    # Writing to .env only helps on a machine with a persistent disk. On a
    # container platform the file is discarded on redeploy, so a generated key
    # differs every boot and every session is invalidated - all users are
    # silently signed out. Say so loudly rather than logging it as info.
    persisted = False
    try:
        env_path = os.path.join(BACKEND_DIR, ".env")
        with open(env_path, "a") as f:
            f.write(f"\nSECRET_KEY={SECRET_KEY}\n")
        persisted = True
    except Exception:
        pass
    logger.warning(
        "SECRET_KEY was not set, so a temporary one was generated%s. "
        "Every restart will sign all users out. Set SECRET_KEY in the "
        "environment to fix this.",
        " and written to .env" if persisted else "",
    )
ADMIN_PANEL_MIN_LENGTH = 10

# Secure cookies are required in production but silently break local http
# development (the browser refuses to store the session at all). Default to
# secure, and let a local run opt out with COOKIE_SECURE=false.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").strip().lower() not in ("false", "0", "no")

# The largest request body each kind of address accepts. A signed-in upload may be a 40 MB photo; a login form
# is a few hundred bytes, and the public application form takes its attachments (6 x 5 MB, as text) and no more.
BODY_LIMIT_DEFAULT = 64 * 1024 * 1024
BODY_LIMIT_FORMS = 64 * 1024
BODY_LIMIT_APPLICATION = 16 * 1024 * 1024
SMALL_FORM_PATHS = ("/api/client/login", "/api/client/register", "/api/client/forgot-password",
                    "/api/client/reset-password", "/api/employee/auth/login", "/api/employee/forgot-password",
                    "/api/portal/login", "/api/portal/accept-invite", "/api/superadmin/login")

SLOW_REQUEST_MS = int(os.getenv("SLOW_REQUEST_MS", "1500"))

# The React app, compiled by `npm run build` in frontend/. Not committed: the deploy builds it (nixpacks.toml).
FRONTEND_DIST = os.path.join(BACKEND_DIR, "..", "frontend", "dist")
# Files the server sends itself rather than the React app: see app/static/README.md.
STATIC_DIR = os.path.join(BACKEND_DIR, "app", "static")
