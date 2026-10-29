"""Request limits, idempotency, security headers and timing, in the order they wrap a request."""
import asyncio
import secrets
import contextvars
import json
import os
import re
import time
from datetime import datetime, timedelta

import itsdangerous
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
    CLIENT_RESET,
    current_build,
    BODY_LIMIT_APPLICATION,
    BODY_LIMIT_DEFAULT,
    BODY_LIMIT_FORMS,
    CORS_ORIGINS,
    COOKIE_SECURE,
    REMEMBER_MAX_AGE,
    SESSION_MAX_AGE,
    SESSION_SAMESITE,
    SECRET_KEY,
    SLOW_REQUEST_MS,
    SMALL_FORM_PATHS,
    logger,
)


class SessionExpiryMiddleware:
    """Innermost: enforces the session's own `exp` (set at sign-in; stamped on first sight for older sessions)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        session = scope.get("session") if scope["type"] in ("http", "websocket") else None
        if session:
            now = int(time.time())
            if session.get("exp") and session["exp"] < now:
                session.clear()
            elif "exp" not in session:
                session["exp"] = now + SESSION_MAX_AGE
        await self.app(scope, receive, send)


class _ClockSafeSigner(itsdangerous.TimestampSigner):
    """The session cookie's signer, untroubled by a clock put back a little.

    The cookie carries the second it was signed, and itsdangerous takes one signed "in the future" as expired. When
    the clock is stepped back (Windows did it by 2 s mid-run; a server's time sync can too), a cookie signed just
    before the step was refused and the person was signed out between two clicks. A stamp up to CLOCK_STEP ahead of
    the clock is taken as now; anything older than its lifetime is refused as before."""

    CLOCK_STEP = 300

    def unsign(self, value, max_age=None, return_timestamp=False):
        try:
            return super().unsign(value, max_age=max_age, return_timestamp=return_timestamp)
        except itsdangerous.SignatureExpired as e:
            ahead = e.date_signed.timestamp() - time.time() if e.date_signed else -1
            if 0 < ahead <= self.CLOCK_STEP:
                return super().unsign(value, max_age=None, return_timestamp=return_timestamp)
            raise


class ClockSafeSessionMiddleware(SessionMiddleware):
    def __init__(self, app, secret_key, **kwargs):
        super().__init__(app, secret_key, **kwargs)
        self.signer = _ClockSafeSigner(str(secret_key))


class SessionCookieLifetimeMiddleware:
    """Outside SessionMiddleware: sets the cookie's Max-Age per sign-in. Remember me gets a persistent cookie; a
    sign-in without it gets none, so the browser drops it on close. (The signature check allows the longest
    lifetime; `exp` above is what actually limits a shorter one.)"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def wrapped(message):
            session = scope.get("session")
            if message["type"] == "http.response.start" and session:
                remember = session.get("remember")
                headers = []
                for k, v in message["headers"]:
                    if k.lower() == b"set-cookie" and v.startswith(b"session=") and not v.startswith(b"session=null"):
                        text = re.sub(r";\s*Max-Age=\d+", "", v.decode("latin-1"), flags=re.I)
                        if remember is True:
                            text += f"; Max-Age={REMEMBER_MAX_AGE}"
                        elif remember is None:
                            text += f"; Max-Age={SESSION_MAX_AGE}"
                        v = text.encode("latin-1")
                    headers.append((k, v))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, wrapped)


app.add_middleware(SessionExpiryMiddleware)
app.add_middleware(
    ClockSafeSessionMiddleware,
    secret_key=SECRET_KEY,
    same_site=SESSION_SAMESITE,
    https_only=COOKIE_SECURE,
    max_age=REMEMBER_MAX_AGE,
)
app.add_middleware(SessionCookieLifetimeMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    # The installed phone app talks to the server from another origin; these are read by lib/freshness.ts.
    expose_headers=["X-App-Build", "X-Client-Reset"],
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
            await JSONResponse(status_code=413, content={"detail": "That is too large to send.", "code": "YE-FILE-01", "ref": secrets.token_hex(4).upper()})(scope, receive, send)
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


_STABLE_NAME_FILES = (".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".ico", ".woff", ".woff2")


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
    served_html = response.headers.get("content-type", "").startswith("text/html")
    if path.endswith(".html") or path == "/" or (path.startswith("/next") and served_html):
        # The app's own pages included: /next/ and every deep link under it are
        # answered with index.html though no ".html" is in the address. Without
        # this they carried no instruction at all, so a browser could keep a
        # copy that names script files a later deploy has since removed - a
        # blank app until the cache is cleared by hand.
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    elif path.startswith("/next/assets/"):
        # Named by a hash of their contents, so the name changes when they do.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith(("/next/", "/icons/")) and path.endswith(_STABLE_NAME_FILES):
        # Pictures and fonts that keep their name from one deploy to the next:
        # kept for an hour, then checked with the file's ETag (a 304, no body).
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"
    elif path.endswith((".js", ".css")):
        # Revalidate rather than trusting a cached copy. Versioned URLs cover
        # the normal case, but a browser holding an older script alongside a
        # fresh page produces a half-working app that no amount of reloading
        # fixes, and the person has no way to tell that is what they are
        # looking at. One conditional request is a cheap price for that.
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    if path.startswith("/api/"):
        # Which build is live, on every answer: an open app that sees a newer one loads it at the next change of screen
        # (frontend/src/lib/freshness.ts). Costs no extra request.
        build = current_build()
        if build:
            response.headers["X-App-Build"] = build
        if CLIENT_RESET:
            response.headers["X-Client-Reset"] = CLIENT_RESET
    if path.rstrip("/") == "/next/reset":
        # The page that starts a device clean also empties the browser's own HTTP cache for this site. Only the cache:
        # storage holds offline saves not yet sent, and cookies the sign-in; the page itself clears what is safe to.
        response.headers["Clear-Site-Data"] = '"cache"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    # A PDF may be shown inside the app's own pages - so what is on screen is
    # the document that prints - but never framed by anybody else's site.
    response.headers["X-Frame-Options"] = (
        "SAMEORIGIN" if response.headers.get("content-type", "").startswith("application/pdf") else "DENY")
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Only our own pages may frame ours (the PDF beside a bill), whatever an old browser makes of X-Frame-Options.
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
    # The camera (scanning, bill photos) and location (attendance) for this site only; nothing else asked for.
    response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=(), payment=(), usb=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# A FLOOD OF REQUESTS
#
# One address asking the API more than API_FLOOD_PER_MINUTE times a minute is not a person: the rest of that minute it
# is told to wait (429). Generous - a whole site office behind one connection, every screen open, does not come near
# it - so it only stops a script. 0 turns it off. Counted per real address (ClientAddressMiddleware runs first).
class FloodMiddleware:
    def __init__(self, app):
        self.app = app
        self.windows = {}

    @staticmethod
    def limit():
        try:
            return int(os.getenv("API_FLOOD_PER_MINUTE", "1200"))
        except ValueError:
            return 1200

    async def __call__(self, scope, receive, send):
        limit = self.limit()
        if limit > 0 and scope["type"] == "http" and scope.get("path", "").startswith("/api/") \
                and scope.get("path") != "/api/health":
            ip = (scope.get("client") or ("unknown",))[0]
            minute = int(time.time() // 60)
            seen = self.windows.get(ip)
            if not seen or seen[0] != minute:
                if len(self.windows) > 50000:
                    self.windows = {k: v for k, v in self.windows.items() if v[0] == minute}
                seen = [minute, 0]
                self.windows[ip] = seen
            seen[1] += 1
            if seen[1] > limit:
                response = JSONResponse({"detail": "Too many requests from this connection. Wait a minute and try again.",
                                         "code": "YE-BUSY-01"}, status_code=429, headers={"Retry-After": "60"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


from app.core.login_guard import ClientAddressMiddleware  # noqa: E402

# Added last, so they run first: the real address is put in place, then the flood is counted against it.
app.add_middleware(FloodMiddleware)
app.add_middleware(ClientAddressMiddleware)
