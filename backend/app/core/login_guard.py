"""Keeping sign-in pages from being hammered: the real address of whoever is asking, a CAPTCHA once there is reason to
doubt them, and an account that stops answering for a while after too many wrong passwords.

The address
    Behind Railway's proxy every request arrives from the proxy. Uvicorn, told to trust forwarded headers from
    anywhere, took the left-most X-Forwarded-For entry - the one the visitor writes himself - so anybody could name a
    new address on every request and walk past every per-address limit. The proxy appends the address that actually
    connected to it, so that, the right-most entry, is taken instead (TRUSTED_PROXY_HOPS when there is more than one
    proxy in front).

The CAPTCHA
    Nobody is asked for one on an ordinary day. After three failed sign-ins from one address, or against one account,
    within fifteen minutes, the next attempt needs one - and the forgotten-password form always does, so it cannot be
    used to flood somebody's inbox. Cloudflare Turnstile is used when its keys are set (TURNSTILE_SITE_KEY,
    TURNSTILE_SECRET_KEY); without them a picture of letters drawn here does the job, so it works from the first
    deploy. Solving one is good for one sign-in - the page tries the owner's door and then the staff door, so that is
    two requests - and no more: a solved CAPTCHA is not a licence to keep guessing.

The lock
    Ten wrong passwords against one account from one address in fifteen minutes, and that account stops answering
    that address - even to the right password - until fifteen minutes have passed since the last. It is the guesser
    who is shut out, not the person: the same account still signs in from anywhere else. A lock on the account itself
    let anybody who knew an email keep its owner out for good, fifteen minutes at a time.
    The company's Master is never locked out at all: what stands in front of their account is the CAPTCHA, which every
    attempt needs once it has been guessed at, and the limit on how fast one address may try. When their account (or
    anybody's) has been guessed at ten times in fifteen minutes, from wherever, the Master is told once.
    Setting a new password - a reset link, or the Master giving one - clears what was counted against the account.

All of it is kept in memory: a restart forgets it, which is the right way round for a lock.
"""
import base64
import hashlib
import io
import json
import math
import os
import random
import secrets
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict

from fastapi import HTTPException
from itsdangerous import BadSignature, URLSafeTimedSerializer

WINDOW = 15 * 60                  # seconds the failures are counted over
CAPTCHA_AFTER = 3                 # failures (per address or per account) before a CAPTCHA is asked for
LOCK_AFTER = 10                   # failures against one account before it is locked
CAPTCHA_TTL = 10 * 60             # how long a drawn CAPTCHA can be answered
CREDITS = 2                       # requests one solved CAPTCHA covers: the owner's door, then the staff door
# Capital and small letters both, and the answer must match them: only letters whose capital and small forms look
# different (no C/c, K/k, O/o, P/p, S/s, U/u, V/v, W/w, X/x, Z/z), and none that pass for one another (0/O, 1/I/l).
ALPHABET = "ABDEFGHJLMNQRTY" + "abdefghjmnqrty" + "23456789"


def mode():
    """"off" (tests, a closed network), "turnstile" when its keys are set, else the built-in picture."""
    m = os.getenv("CAPTCHA_MODE", "auto").strip().lower()
    if m == "off":
        return "off"
    if os.getenv("TURNSTILE_SITE_KEY") and os.getenv("TURNSTILE_SECRET_KEY") and m in ("auto", "turnstile"):
        return "turnstile"
    return "builtin"


# --- who is asking ----------------------------------------------------------------------------------------------------

def _hops():
    try:
        return max(1, int(os.getenv("TRUSTED_PROXY_HOPS", "1")))
    except ValueError:
        return 1


def behind_proxy():
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("TRUST_PROXY", "").strip().lower() in ("1", "true", "yes"))


def address_from(headers, fallback):
    """The address that connected to our proxy: the right-most X-Forwarded-For entry (or the n-th from the right),
    never one the visitor wrote. Two X-Forwarded-For headers are read as one list, in order."""
    values = [v.decode("latin1") if isinstance(v, bytes) else v for k, v in headers
              if (k.decode("latin1") if isinstance(k, bytes) else k).lower() == "x-forwarded-for"]
    hosts = [h.strip() for v in values for h in v.split(",") if h.strip()]
    if not hosts:
        return fallback
    return hosts[-min(_hops(), len(hosts))]


class ClientAddressMiddleware:
    """Puts the real address where every route, limit and log already looks for it: request.client.host."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and behind_proxy():
            client = scope.get("client") or ("", 0)
            host = address_from(scope.get("headers") or [], client[0])
            if host and host != client[0]:
                scope = dict(scope, client=(host, client[1] if len(client) > 1 else 0))
        await self.app(scope, receive, send)


def client_ip(request):
    return request.client.host if request and request.client else "unknown"


# --- failures, counted ------------------------------------------------------------------------------------------------

class _Failures:
    def __init__(self):
        self._hits = defaultdict(list)
        self._notified = {}
        self._lock = threading.Lock()

    def _live(self, key, now):
        hits = [t for t in self._hits.get(key, ()) if now - t < WINDOW]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def add(self, key):
        now = time.time()
        with self._lock:
            self._live(key, now)
            self._hits[key].append(now)
            if len(self._hits) > 20000:                     # a flood of made-up keys: drop the oldest half
                for k in sorted(self._hits, key=lambda k: self._hits[k][-1])[:10000]:
                    self._hits.pop(k, None)

    def count(self, key):
        with self._lock:
            return len(self._live(key, time.time()))

    def clear(self, key):
        with self._lock:
            self._hits.pop(key, None)

    def clear_prefix(self, key):
        """The key and every key built on it ("acct:x" and each "acct:x|ip:...")."""
        with self._lock:
            for k in [k for k in self._hits if k == key or k.startswith(key + "|")]:
                self._hits.pop(k, None)

    def first_lock(self, email):
        """True once per lock-out, so the Master is told once and not at every attempt."""
        now = time.time()
        with self._lock:
            if now - self._notified.get(email, 0) < WINDOW:
                return False
            self._notified[email] = now
            return True

    def reset(self):
        with self._lock:
            self._hits.clear()
            self._notified.clear()


failures = _Failures()


def _email_key(email):
    return "acct:" + (email or "").strip().lower()


def captcha_needed(request, email=""):
    if mode() == "off":
        return False
    return (failures.count("ip:" + client_ip(request)) >= CAPTCHA_AFTER
            or bool(email) and failures.count(_email_key(email)) >= CAPTCHA_AFTER)


def _pair_key(email, request):
    """One account as tried from one address: what a lock is counted on."""
    return "%s|ip:%s" % (_email_key(email), client_ip(request))


def locked(email, request=None):
    """Whether this address is shut out of this account. Without a request there is no address to lock, so nothing is."""
    return bool(email) and request is not None and failures.count(_pair_key(email, request)) >= LOCK_AFTER


def guard(request, email="", body=None, always=False, lockable=True):
    """Before a sign-in is tried: refuse an address that has guessed too often at this account, and ask for a CAPTCHA
    where there is reason to. `lockable` is False for the company's Master, who is never locked out."""
    if lockable and locked(email, request):
        raise HTTPException(429, "Sign-in to this account is locked from here for 15 minutes after too many wrong passwords. "
                                 "Try again later, from another device, or use Forgot password.")
    if mode() != "off" and (always or captcha_needed(request, email)):
        require_captcha(request, body or {})


def failed(request, email="", db=None, client_id=None):
    """A wrong password (or an address trying accounts that do not exist). Counted against the address, against the
    account (which asks for a CAPTCHA and tells the Master), and against the account from this address (the lock)."""
    failures.add("ip:" + client_ip(request))
    if not email:
        return
    failures.add(_email_key(email))
    failures.add(_pair_key(email, request))
    if (failures.count(_email_key(email)) >= LOCK_AFTER and failures.first_lock(email.strip().lower())
            and db is not None and client_id):
        from app.core.notifications import notify
        notify(db, client_id, "security_lock", "Repeated wrong passwords for %s" % email,
               "Ten wrong passwords in fifteen minutes, the last from %s. Sign-ins from where they came are paused "
               "for 15 minutes; the account itself still signs in. If it was not them, change their password."
               % client_ip(request), severity="danger")


def succeeded(request, email=""):
    """The right password: the account's count starts again, and so does this address's against it. The address's
    own count does not - one right password among many wrong ones for other accounts is no reason to stop asking."""
    if email:
        failures.clear(_email_key(email))
        failures.clear(_pair_key(email, request))


def clear_account(email):
    """A new password has been set (a reset link, or the Master giving one): nothing counted against the account,
    from any address, still stands."""
    if email:
        failures.clear_prefix(_email_key(email))


# --- the CAPTCHA ------------------------------------------------------------------------------------------------------

def _signer():
    from app.core.config import SECRET_KEY
    return URLSafeTimedSerializer(SECRET_KEY, salt="captcha")


_used = {}
_used_lock = threading.Lock()


def _spend(token):
    """A drawn CAPTCHA answers once."""
    now = time.time()
    with _used_lock:
        for t in [t for t, at in _used.items() if now - at > CAPTCHA_TTL]:
            _used.pop(t, None)
        if token in _used:
            return False
        _used[token] = now
        return True


def _picture(text):
    """The letters on a noisy background, each turned a little: easy for a person, not for a script reading pixels."""
    from PIL import Image, ImageDraw, ImageFont
    # Drawn at twice the size it is shown, so it stays sharp on any screen. Pillow's own font, not one from the
    # machine: the main site (Linux) and a laptop (Windows) have different fonts, and the picture must look the same.
    s = 2
    w, h = 220 * s, 70 * s
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):                       # a soft wash from pale blue to pale lavender
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(238 + 6 * t), int(243 - 3 * t), 255))
    for _ in range(140):                     # faint speckle, lighter than any letter
        x0, y0, r = random.randint(0, w), random.randint(0, h), random.randint(1, 3)
        d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=(random.randint(185, 215), random.randint(195, 220), 240))
    for _ in range(2):                       # two gentle waves behind the letters
        amp, phase, base = random.uniform(8, 16) * s, random.uniform(0, 6.3), random.uniform(0.3, 0.7) * h
        d.line([(x, base + amp * math.sin(x / (34 * s) + phase)) for x in range(0, w + 1, 4)],
               fill=(172, 186, 230), width=2 * s, joint="curve")
    font = ImageFont.load_default(size=40 * s)
    colours = [(30, 58, 138), (55, 48, 163), (29, 78, 216), (91, 33, 182), (15, 118, 110)]
    step = (w - 36 * s) / len(text)
    for i, ch in enumerate(text):
        tile = Image.new("RGBA", (60 * s, 64 * s), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        box = td.textbbox((0, 0), ch, font=font, stroke_width=s)
        colour = random.choice(colours) + (255,)
        td.text(((tile.width - box[2] - box[0]) / 2, (tile.height - box[3] - box[1]) / 2), ch, font=font,
                fill=colour, stroke_width=s, stroke_fill=colour)
        tile = tile.rotate(random.randint(-14, 14), resample=Image.BICUBIC)
        img.paste(tile, (int(18 * s + i * step + random.randint(-3, 3) * s - 8 * s),
                         int((h - tile.height) / 2 + random.randint(-5, 5) * s)), tile)
    # one thin line across the letters themselves, so they cannot be lifted off a clean background
    y0 = random.uniform(0.4, 0.6) * h
    d.line([(12 * s, y0), (w - 12 * s, y0 + random.uniform(-0.2, 0.2) * h)], fill=(99, 102, 241), width=s)
    img = img.resize((220, 70), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _digest(answer):
    from app.core.config import SECRET_KEY
    return hashlib.sha256(("%s|%s" % (SECRET_KEY, (answer or "").strip())).encode()).hexdigest()


def challenge():
    """What the page draws: Turnstile's widget (its site key), or a picture of letters and the token to send back."""
    m = mode()
    if m == "turnstile":
        return {"provider": "turnstile", "site_key": os.getenv("TURNSTILE_SITE_KEY", "")}
    if m == "off":
        return {"provider": "off"}
    text = "".join(secrets.choice(ALPHABET) for _ in range(5))
    token = _signer().dumps({"d": _digest(text), "n": secrets.token_hex(8)})
    return {"provider": "builtin", "token": token, "image": _picture(text)}


def _turnstile_ok(response, ip):
    data = urllib.parse.urlencode({"secret": os.getenv("TURNSTILE_SECRET_KEY", ""), "response": response,
                                   "remoteip": ip}).encode()
    try:
        with urllib.request.urlopen("https://challenges.cloudflare.com/turnstile/v0/siteverify", data, timeout=8) as r:
            return bool(json.loads(r.read().decode() or "{}").get("success"))
    except Exception:
        return False


# What a solved CAPTCHA still covers, kept HERE and not in the session: the session is a signed cookie the visitor holds,
# so a count kept in it could be put back by sending the old cookie again - one solved CAPTCHA, unlimited guesses.
# The cookie carries only an id; how many tries it has left is this process's to say.
_passes = {}                      # id -> [tries left, expires at]
_passes_lock = threading.Lock()


def _use_pass(pid):
    now = time.time()
    with _passes_lock:
        for k in [k for k, (_, until) in _passes.items() if until < now]:
            _passes.pop(k, None)
        held = _passes.get(pid) if pid else None
        if not held or held[0] <= 0:
            return False
        held[0] -= 1
        if held[0] <= 0:
            _passes.pop(pid, None)
        return True


def _grant_pass(request):
    pid = secrets.token_urlsafe(16)
    with _passes_lock:
        _passes[pid] = [CREDITS - 1, time.time() + CAPTCHA_TTL]     # this request is the first of its CREDITS
    request.session["captcha_pass"] = pid


def require_captcha(request, body):
    """Passed, or refused with 428 for the page to show the CAPTCHA. A solved one covers this sign-in and no more."""
    session = request.session
    if _use_pass(session.get("captcha_pass")):
        return
    token = (body.get("captcha_token") or "").strip() if isinstance(body, dict) else ""
    answer = (body.get("captcha_answer") or "").strip() if isinstance(body, dict) else ""
    if not token:
        raise HTTPException(428, "Please confirm you are a person: complete the check below and try again.")
    ok = False
    if mode() == "turnstile":
        ok = _turnstile_ok(token, client_ip(request))
    else:
        try:
            data = _signer().loads(token, max_age=CAPTCHA_TTL)
            ok = secrets.compare_digest(data.get("d", ""), _digest(answer)) and _spend(token)
        except BadSignature:
            ok = False
    if not ok:
        raise HTTPException(428, "That check did not match. Try the new one below.")
    _grant_pass(request)


def body_of(body):
    """A sign-in body as a dict, whether it came as a model or a dict."""
    if body is None:
        return {}
    if isinstance(body, dict):
        return body
    return body.model_dump() if hasattr(body, "model_dump") else dict(body)
