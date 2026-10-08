"""Passwords, reset tokens and the per-address rate limiter."""
import hashlib
import os
import secrets
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import HTTPException

from app import models
from app.core import passwords

from app.core.config import ADMIN_PANEL_MIN_LENGTH


def hash_password(password: str) -> str:
    return passwords.hash_password(password)


def verify_password(password: str, stored: str) -> bool:
    return passwords.verify_password(password, stored)


def upgrade_password_hash(row, column, password):
    """A password that has just been proved right is stored again in today's form, if it was stored in an older,
    weaker one (the caller commits)."""
    if passwords.needs_rehash(getattr(row, column, "")):
        setattr(row, column, passwords.hash_password(password))


def admin_panel_password():
    """The /admin panel's password - from the environment and nowhere else.

    The panel edits every company's rows directly. It used to fall back to
    "admin", which on a server nobody had set ADMIN_PASSWORD on was a door
    anyone could walk through. Unset, short or "admin" now means the panel
    stays shut.
    """
    pwd = os.getenv("ADMIN_PASSWORD", "") or ""
    if len(pwd) < ADMIN_PANEL_MIN_LENGTH or pwd.strip().lower() == "admin":
        return ""
    return pwd


class RateLimiter:
    """Fixed-memory sliding window.

    The previous version kept a dict entry for every key it ever saw and never
    removed them, so a long-running process grew without bound (one entry per
    distinct client IP, forever). Stale keys are now swept periodically.
    """

    SWEEP_INTERVAL = 300  # seconds
    MAX_KEYS = 10000

    def __init__(self):
        self._hits = defaultdict(list)
        self._lock = threading.Lock()
        self._last_sweep = time.time()

    def _sweep(self, now: float, window: int) -> None:
        cutoff = now - max(window, 3600)
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] < cutoff]:
            self._hits.pop(key, None)
        # Hard ceiling in case of a burst of unique keys between sweeps.
        if len(self._hits) > self.MAX_KEYS:
            for key in sorted(self._hits, key=lambda k: self._hits[k][-1])[: len(self._hits) - self.MAX_KEYS]:
                self._hits.pop(key, None)
        self._last_sweep = now

    def is_rate_limited(self, key: str, max_requests: int = 10, window: int = 60) -> bool:
        now = time.time()
        with self._lock:
            if now - self._last_sweep > self.SWEEP_INTERVAL:
                self._sweep(now, window)
            hits = [t for t in self._hits[key] if now - t < window]
            if len(hits) >= max_requests:
                self._hits[key] = hits
                return True
            hits.append(now)
            self._hits[key] = hits
            return False


rate_limiter = RateLimiter()

# PASSWORD RESET - the way back in for a locked-out account owner
RESET_TOKEN_TTL_MINUTES = 60


def validate_password_strength(password: str):
    """One rule, shared by registering and resetting, so the two cannot drift."""
    if len(password or "") < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not any(c.isupper() for c in password) or not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one uppercase letter and one number",
        )


def hash_reset_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def issue_reset_token(db, user_type, subject_id, ip=""):
    """Start a new link and spend any earlier one, so a forwarded old email
    stops working the moment a fresh link is asked for."""
    q = db.query(models.DBPasswordReset).filter(
        models.DBPasswordReset.user_type == user_type,
        models.DBPasswordReset.used_at == "",
    )
    column = {"client": models.DBPasswordReset.client_id,
              "employee": models.DBPasswordReset.employee_id,
              "member": models.DBPasswordReset.member_id}[user_type]
    q = q.filter(column == subject_id)
    q.update({"used_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
             synchronize_session=False)

    token = secrets.token_urlsafe(32)
    row = models.DBPasswordReset(
        user_type=user_type,
        token_hash=hash_reset_token(token),
        expires_at=(datetime.now() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
                    ).strftime("%Y-%m-%d %H:%M:%S"),
        requested_ip=ip,
    )
    setattr(row, {"client": "client_id", "employee": "employee_id",
                  "member": "member_id"}[user_type], subject_id)
    db.add(row)
    return token


def _portal_token_hash(token):
    return hashlib.sha256((token or "").encode()).hexdigest()
