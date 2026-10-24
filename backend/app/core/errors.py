"""How errors are answered.

Every error the server sends carries, beside its plain-language `detail`:
  code  - a stable error code that names what happened, by area: YE-AUTH-01 is a wrong email or password, YE-BUSY-02
          a server that is busy or restarting, YE-SRV-01 a fault. It means the same thing every time. The full list
          is CODES below, and the same list is in docs/error-codes.md and frontend/src/lib/errorCodes.ts;
  ref   - a reference unique to this one failure. The same ref is written to the server log with what went wrong
          (the full traceback for a fault), so "YE-SRV-01, ref 7F3A9C21" from a user finds the exact cause.
The two also go out as the X-Error-Code and X-Error-Ref headers. Internals are never echoed back to the client.

The code is worked out from the status and the message every error already has, so the hundreds of places that raise
an error get the right code without each having to name one.
"""
import random
import secrets
import traceback
from datetime import datetime, timedelta

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.application import app
from app.core.config import logger


# Every code, and what it means. Kept in step with frontend/src/lib/errorCodes.ts and docs/error-codes.md.
CODES = {
    "YE-AUTH-01": "Wrong email or password",
    "YE-AUTH-02": "Account disabled",
    "YE-AUTH-03": "Too many sign-in attempts",
    "YE-AUTH-04": "Signed out: the session ended or was never started",
    "YE-AUTH-05": "Access removed",
    "YE-AUTH-06": "Password not set yet",
    "YE-AUTH-07": "Reset link invalid or expired",
    "YE-AUTH-08": "Email already registered",
    "YE-AUTH-09": "Check that you are a person (CAPTCHA)",
    "YE-AUTH-10": "Account locked for a while after wrong passwords",
    "YE-ACCESS-01": "Not allowed: the person's access does not include this",
    "YE-ACCESS-02": "File link expired or for another file",
    "YE-DATA-01": "Not found",
    "YE-DATA-02": "Conflicts with a record that already exists",
    "YE-DATA-03": "Locked: signed off or issued, so it cannot change",
    "YE-DATA-04": "Something entered is not right",
    "YE-FILE-01": "File too large",
    "YE-FILE-02": "File type not accepted",
    "YE-FILE-03": "File empty or could not be read",
    "YE-BUSY-01": "Too many requests at once",
    "YE-BUSY-02": "Server busy or restarting",
    "YE-BUSY-03": "Server took too long",
    "YE-SRV-01": "Server fault",
}

_SIGN_IN_NOISE = ("login attempts", "registration attempts", "too many attempts", "too many tries")


def error_code(status: int, detail=None) -> str:
    """The code for an error, from its status and its message."""
    text = detail.lower() if isinstance(detail, str) else ""
    if status == 401:
        if "invalid credentials" in text:
            return "YE-AUTH-01"
        if "access has been removed" in text:
            return "YE-AUTH-05"
        if "password not set" in text:
            return "YE-AUTH-06"
        return "YE-AUTH-04"
    if status == 403:
        if "account disabled" in text:
            return "YE-AUTH-02"
        if "this link" in text:
            return "YE-ACCESS-02"
        return "YE-ACCESS-01"
    if status == 404:
        return "YE-DATA-01"
    if status == 409:
        if "signed-off" in text or "signed off" in text or "as issued" in text or "locked" in text:
            return "YE-DATA-03"
        return "YE-DATA-02"
    if status == 413 or "too large" in text or "over 15 mb" in text:
        return "YE-FILE-01"
    if status == 428:
        return "YE-AUTH-09"
    if status == 429 and "is locked" in text:
        return "YE-AUTH-10"
    if status == 429:
        return "YE-AUTH-03" if any(w in text for w in _SIGN_IN_NOISE) else "YE-BUSY-01"
    if status in (502, 503):
        return "YE-BUSY-02"
    if status == 504:
        return "YE-BUSY-03"
    if status >= 500:
        return "YE-SRV-01"
    # 400 and 422: the person's to fix, unless the message says it is about a file or an account
    if "reset link" in text:
        return "YE-AUTH-07"
    if "already registered" in text:
        return "YE-AUTH-08"
    if "png or jpeg" in text or text.startswith("a photo, a pdf"):
        return "YE-FILE-02"
    if "file is empty" in text or "could be read" in text or "could not be read" in text:
        return "YE-FILE-03"
    return "YE-DATA-04"


def new_ref() -> str:
    """A short reference for one failure, easy to read out over the phone: 8 characters, A-F and 0-9."""
    return secrets.token_hex(4).upper()


# Everyday answers that would bury the real problems: "not found" and "not signed in".
NOT_KEPT = ("YE-DATA-01", "YE-AUTH-04")
KEEP_DAYS = 90


def _who(request: Request):
    """(company id, who) for the error log: from the session, or from what a sign-in route noted on a failed attempt."""
    state = getattr(request, "state", None)
    noted_client, noted_who = getattr(state, "error_client_id", None), getattr(state, "error_who", "")
    session = request.scope.get("session") or {}
    client_id = session.get("client_id") or session.get("employee_client_id") or noted_client
    if session.get("member_id"):
        who = "member:%s" % session["member_id"]
    elif session.get("employee_id"):
        who = "employee:%s" % session["employee_id"]
    elif session.get("client_id"):
        who = "owner"
    else:
        who = noted_who or ""
    return client_id, who


def _write(row: dict):
    from app import models
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        db.add(models.DBErrorLog(**row))
        if random.random() < 0.01:          # now and then, let the old ones go
            cut = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            db.query(models.DBErrorLog).filter(models.DBErrorLog.at < cut).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Could not keep %s ref=%s in the error log", row.get("code"), row.get("ref"), exc_info=True)
    finally:
        db.close()


async def keep(request: Request, status: int, code: str, ref: str, detail, trace: str = ""):
    """Put an error in the error log. Never lets a problem here change the answer the person gets."""
    if code in NOT_KEPT or not request.url.path.startswith("/api/") or getattr(request.state, "error_skip", False):
        return
    try:
        client_id, who = _who(request)
        text = detail if isinstance(detail, str) else "Some of what was sent is not valid."
        await run_in_threadpool(_write, {
            "client_id": client_id, "code": code, "ref": ref, "status": status, "method": request.method,
            "path": request.url.path[:300], "detail": (text or "")[:1000], "who": (who or "")[:200],
            "trace": (trace or "")[-8000:]})
    except Exception:
        logger.warning("Error log skipped for ref=%s", ref, exc_info=True)


def _answer(status: int, detail, ref: str, headers=None) -> JSONResponse:
    code = error_code(status, detail)
    out = dict(headers or {})
    out["X-Error-Code"], out["X-Error-Ref"] = code, ref
    return JSONResponse(status_code=status, content={"detail": detail, "code": code, "ref": ref}, headers=out)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    """An error the code raised on purpose ("Drawing not found", "Not allowed"): its message, now with a code."""
    ref = new_ref()
    code = error_code(exc.status_code, exc.detail)
    if exc.status_code >= 500:
        logger.error("%s ref=%s on %s %s: %s", code, ref, request.method, request.url.path, exc.detail)
    elif code not in ("YE-DATA-01", "YE-AUTH-04"):        # "not found" and "not signed in" are everyday answers
        logger.info("%s ref=%s on %s %s: %s", code, ref, request.method, request.url.path, exc.detail)
    await keep(request, exc.status_code, code, ref, exc.detail)
    return _answer(exc.status_code, exc.detail, ref, getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """What was sent does not have the right shape. The field-by-field list is kept, as before."""
    ref = new_ref()
    logger.info("YE-DATA-04 ref=%s on %s %s", ref, request.method, request.url.path)
    await keep(request, 422, "YE-DATA-04", ref, None)
    return _answer(422, jsonable_encoder(exc.errors()), ref)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """A unique-constraint clash is a client mistake, not a server fault. Without this it surfaced as an opaque 500."""
    ref = new_ref()
    logger.warning("YE-DATA-02 ref=%s integrity error on %s: %s", ref, request.url.path, exc)
    await keep(request, 409, "YE-DATA-02", ref, "That record conflicts with one that already exists.", str(exc.orig)[:2000])
    return _answer(409, "That record conflicts with one that already exists.", ref)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """A fault nobody expected: the full traceback goes to the log under the ref, and only a generic message, the
    code and the ref go back to the client."""
    ref = new_ref()
    logger.exception("YE-SRV-01 ref=%s unhandled error on %s %s", ref, request.method, request.url.path)
    await keep(request, 500, "YE-SRV-01", ref, "An unexpected error occurred.",
               "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    return _answer(500, "An unexpected error occurred.", ref)
