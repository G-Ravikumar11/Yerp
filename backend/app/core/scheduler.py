"""The background scheduler: which jobs exist and which are due."""
import asyncio
import os
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app import models
from app.db import SessionLocal

from app.core.config import logger


# SCHEDULER - the small amount of work that has to happen without a user
# How often the loop wakes. Jobs decide for themselves whether they are due,
# so this only sets how soon after becoming due something runs.
SCHEDULER_TICK_SECONDS = int(os.getenv("SCHEDULER_TICK_SECONDS", "900"))
# Registered as (name, period_key_fn, run_fn). period_key_fn turns "now" into a
# string identifying this run, which is what stops a job running twice.
SCHEDULED_JOBS = []


def daily_key(now=None):
    return (now or datetime.now()).strftime("%Y-%m-%d")


def each_active_client(db):
    """Every active company, one at a time, each read fresh and let go of before the next.

    A job that goes through every company and commits as it goes must not keep what it read: each commit expires every
    object the session holds, so carrying all companies' records along made each commit slower than the last and a
    run grew with the square of the data (it stalled with a few hundred companies). What a company's turn changed and did
    not commit is written first (flushed - still in the job's transaction), so letting go of it loses nothing."""
    ids = [cid for (cid,) in db.query(models.DBClient.id).filter(models.DBClient.is_active.is_(True))
           .order_by(models.DBClient.id).all()]
    for cid in ids:
        client = db.get(models.DBClient, cid)
        if client is None:
            continue
        try:
            yield client
        finally:
            try:
                db.flush()
            except Exception:
                db.rollback()
            db.expunge_all()


def scheduled_job(name, period_key_fn=daily_key):
    def register(fn):
        SCHEDULED_JOBS.append((name, period_key_fn, fn))
        return fn
    return register


def claim_job_run(db, job_name, period_key):
    """Take this period, or find that another worker already has it.

    The unique index does the arbitrating, so this is safe with any number of
    workers and needs no separate lock service.
    """
    row = models.DBJobRun(job_name=job_name, period_key=period_key, status="running")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return row


def run_due_jobs(now=None, only=None):
    """Run whatever is due. Safe to call as often as you like.

    Returns what happened, which is what the tests and the operator endpoint
    both read.
    """
    now = now or datetime.now()
    results = []
    for name, period_key_fn, fn in SCHEDULED_JOBS:
        if only and name != only:
            continue
        period_key = period_key_fn(now)
        with SessionLocal() as db:
            claim = claim_job_run(db, name, period_key)
            if claim is None:
                results.append({"job": name, "period": period_key, "status": "already_done"})
                continue
            try:
                detail = fn(db, now) or ""
                claim.status = "done"
                claim.detail = str(detail)[:500]
            except Exception as exc:
                # A job that throws must not take the loop down with it, and
                # must not silently look like it succeeded.
                logger.exception("Scheduled job %s failed", name)
                claim.status = "failed"
                claim.detail = str(exc)[:500]
            claim.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.commit()
            results.append({"job": name, "period": period_key,
                            "status": claim.status, "detail": claim.detail})
    return results


async def scheduler_loop():
    while True:
        try:
            await asyncio.to_thread(run_due_jobs)
        except Exception:
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(SCHEDULER_TICK_SECONDS)


def digest_key(now=None):
    """The day, once it is past seven; before that a key per hour, so an early
    tick cannot use up the day's digest before there is anything to send."""
    now = now or datetime.now()
    return now.strftime("%Y-%m-%d") if now.hour >= 7 else now.strftime("early-%Y-%m-%d-%H")
