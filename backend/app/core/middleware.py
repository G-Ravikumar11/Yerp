"""Request limits, idempotency, security headers and timing, in the order they wrap a request."""
import asyncio
import contextvars
import json
import os
import time
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import event as sa_event
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.db import engine, SessionLocal

from app.core.application import app
from app.core.auth import WRITE_METHODS
from app.core.cache import _WRITE_VERSION
from app.core.config import (
    BODY_LIMIT_APPLICATION,
    BODY_LIMIT_DEFAULT,
    BODY_LIMIT_FORMS,
    COOKIE_SECURE,
    SECRET_KEY,
    SLOW_REQUEST_MS,
    SMALL_FORM_PATHS,
    logger,
)


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=COOKIE_SECURE,
    max_age=int(os.getenv("SESSION_MAX_AGE", "86400")),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else [],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)

app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)


def body_limit_for(path):
    if path in SMALL_FORM_PATHS:
        return BODY_LIMIT_FORMS
    if path.startswith("/api/recruitment/form/"):
        return BODY_LIMIT_APPLICATION
    return BODY_LIMIT_DEFAULT


class BodyLimitMiddleware:
    """Refuses a request body over its limit - from its declared length, or as it streams in."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = body_limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await JSONResponse(status_code=413, content={"detail": "That is too large to send."})(scope, receive, send)
            return
        seen = [0]

        async def counted():
            message = await receive()
            if message["type"] == "http.request":
                seen[0] += len(message.get("body", b""))
                if seen[0] > limit:
                    raise HTTPException(status_code=413, detail="That is too large to send.")
            return message

        await self.app(scope, counted, send)


app.add_middleware(BodyLimitMiddleware)

_IDEM_LOCKS = {}


@app.middleware("http")
async def idempotency_middleware(request: Request, call_next):
    """A change that carries an Idempotency-Key is made once: sent again with the same key - because the answer
    never reached the phone, and the app kept it to send later - it is answered with the first answer."""
    key = (request.headers.get("idempotency-key") or "").strip()[:80]
    if not key or request.method not in WRITE_METHODS or not request.url.path.startswith("/api/"):
        return await call_next(request)
    scope = "%s %s" % (request.method, request.url.path)
    lock = _IDEM_LOCKS.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            with SessionLocal() as db:
                hit = db.query(models.DBIdempotency).filter(
                    models.DBIdempotency.key == key, models.DBIdempotency.scope == scope).first()
                if hit:
                    return Response(content=hit.body or b"", status_code=hit.status,
                                    headers=dict(json.loads(hit.headers or "{}"), **{"Idempotent-Replay": "true"}))
            response = await call_next(request)
            if not 200 <= response.status_code < 300:
                return response
            body = b"".join([chunk async for chunk in response.body_iterator])
            headers = {k: v for k, v in response.headers.items() if k.lower() in ("content-type", "content-encoding")}
            if len(body) <= 2_000_000:
                try:
                    with SessionLocal() as db:
                        db.query(models.DBIdempotency).filter(models.DBIdempotency.created_at < (
                            datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")).delete()
                        db.add(models.DBIdempotency(key=key, scope=scope, status=response.status_code,
                                                    headers=json.dumps(headers), body=body))
                        db.commit()
                except Exception:
                    logger.exception("Could not keep the answer to a repeatable request")
            return Response(content=body, status_code=response.status_code, headers=headers)
    finally:
        if len(_IDEM_LOCKS) > 2000:
            _IDEM_LOCKS.clear()


# How long each request spends in the database and how many trips it makes. A screen that is slow on the hosted
# database is nearly always one making a trip per row; this names it in the logs (and in the browser's Network
# tab, as Server-Timing) instead of leaving it to be guessed at.
REQUEST_DB = contextvars.ContextVar("request_db", default=None)


@sa_event.listens_for(engine, "before_cursor_execute")
def _db_trip_start(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("trip_started", []).append(time.perf_counter())


@sa_event.listens_for(engine, "after_cursor_execute")
def _db_trip_end(conn, cursor, statement, parameters, context, executemany):
    started = conn.info.get("trip_started")
    took = time.perf_counter() - started.pop() if started else 0.0
    tally = REQUEST_DB.get()
    if tally is not None:
        tally[0] += 1
        tally[1] += took


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    tally = [0, 0.0]
    REQUEST_DB.set(tally)
    began = time.perf_counter()
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/"):
        total_ms = (time.perf_counter() - began) * 1000
        response.headers["Server-Timing"] = 'db;dur=%.0f;desc="%d queries", app;dur=%.0f' % (
            tally[1] * 1000, tally[0], total_ms)
        if total_ms > SLOW_REQUEST_MS or tally[0] > 200:
            logger.warning("Slow %s %s: %.0f ms, %d database queries taking %.0f ms",
                           request.method, path, total_ms, tally[0], tally[1] * 1000)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        _WRITE_VERSION[0] += 1
    if path.endswith(".html") or path == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    elif path.startswith("/next/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.endswith((".js", ".css")):
        # Revalidate rather than trusting a cached copy. Versioned URLs cover
        # the normal case, but a browser holding an older script alongside a
        # fresh page produces a half-working app that no amount of reloading
        # fixes, and the person has no way to tell that is what they are
        # looking at. One conditional request is a cheap price for that.
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    response.headers["X-Content-Type-Options"] = "nosniff"
    # A PDF may be shown inside the app's own pages - so what is on screen is
    # the document that prints - but never framed by anybody else's site.
    response.headers["X-Frame-Options"] = (
        "SAMEORIGIN" if response.headers.get("content-type", "").startswith("application/pdf") else "DENY")
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
