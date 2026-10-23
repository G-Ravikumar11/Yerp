"""The FastAPI application object and its start-up and shut-down."""
import asyncio
import os
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from starlette.requests import HTTPConnection

from app import models
from app.db import SessionLocal, engine, ensure_columns, migrate_sqlite

from app.core.auth import ensure_admin_user, ensure_super_admin
from app.core.config import logger
from app.core.lifecycle import (
    DB_READY,
    _boot_step,
    backfill_entry_codes,
    convert_legacy_holds_all,
    fill_document_names,
)
from app.core.scheduler import SCHEDULER_TICK_SECONDS, scheduler_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    ok = True
    for label, fn in (("create tables", lambda: models.Base.metadata.create_all(bind=engine)),
                      ("add missing columns", ensure_columns),
                      ("migrate sqlite", migrate_sqlite),
                      ("admin user", ensure_admin_user),
                      ("vendor document names", fill_document_names),
                      ("super admin", ensure_super_admin)):
        ok = _boot_step(label, fn) and ok
    if ok:
        convert_legacy_holds_all()
        _boot_step("number the entries of the measurement book", backfill_entry_codes)
    DB_READY["ok"] = ok
    if ok:
        # Reading the schema's foreign keys is what the first delete after a restart used to wait for.
        from app.services.subcontract_orders import _fk_map

        def warm():
            with SessionLocal() as db:
                _fk_map(db)
        _boot_step("read the schema for deletes", lambda: threading.Thread(target=warm, daemon=True).start())

        def warm_holidays():
            # The festival dates take about a second to work out; done here, nobody's first calendar waits for it.
            from datetime import datetime
            from app.routers.holiday_calendar import holidays_for
            for year in (datetime.now().year, datetime.now().year + 1):
                holidays_for(year)
        _boot_step("work out this year's holidays", lambda: threading.Thread(target=warm_holidays, daemon=True).start())
        DB_READY["error"] = ""
        logger.info("Database initialized successfully")
    else:
        logger.error("Started WITHOUT a working database. %s", DB_READY["error"])

    task = None
    if os.getenv("SCHEDULER_ENABLED", "1") == "1":
        task = asyncio.create_task(scheduler_loop())
        logger.info("Scheduler started, tick every %ss", SCHEDULER_TICK_SECONDS)
    try:
        yield
    finally:
        if task:
            task.cancel()


def require_password_changed(request: HTTPConnection):
    """Every API call: a member of staff whose first password is still the Master's may only change it. Read from the
    signed session, which the sign-in set, so most staff routes (which read the session themselves) are covered too."""
    from app.core.auth import PASSWORD_CHANGE_PATHS, first_password_enforced
    if first_password_enforced() and request.session.get("employee_id") and request.session.get("must_change_pw")             and request.url.path.startswith("/api/") and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise HTTPException(status_code=403, detail="Choose a new password before you continue.",
                            headers={"X-Password-Change-Required": "1"})


app = FastAPI(title="Y ERP", lifespan=lifespan, dependencies=[Depends(require_password_changed)])
