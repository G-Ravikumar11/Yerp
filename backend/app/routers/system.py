"""The system endpoints."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db import engine

from app.core.config import logger
from app.core.lifecycle import DB_READY


router = APIRouter()


@router.get("/api/health")
def health_check():
    """Liveness + database readiness.

    This is the path Railway restarts on, so it has to fail when the app
    cannot actually serve traffic - a bare 'ok' kept a database-less instance
    in rotation. It takes no database dependency of its own: a session that
    cannot be opened would fail before the handler ran, and the one endpoint
    whose job is to report that the database is down must not be the one
    endpoint the database takes down with it.
    """
    from sqlalchemy import text as sql_text
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return JSONResponse(status_code=503, content={
            "status": "degraded", "database": "unavailable",
            "detail": DB_READY.get("error") or str(exc)[:200]})
    if not DB_READY.get("ok"):
        return JSONResponse(status_code=503, content={
            "status": "degraded", "database": "reachable, but start-up did not finish",
            "detail": DB_READY.get("error", "")[:200]})

    # Schema updates are applied non-fatally so a partial failure cannot stop
    # the app booting, but a migration that never ran must not look identical
    # to one that succeeded.
    try:
        from app.db import migration_report
        problems = migration_report()
    except Exception:
        problems = []
    body = {"status": "ok", "database": "ok"}
    if problems:
        body["status"] = "ok_with_warnings"
        body["migration_warnings"] = len(problems)
    return body
