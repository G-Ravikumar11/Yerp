"""The FastAPI application object and its start-up and shut-down."""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models
from app.db import engine, ensure_columns, migrate_sqlite

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


app = FastAPI(title="Y ERP", lifespan=lifespan)
