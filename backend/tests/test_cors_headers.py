"""The phone app is another origin: a header it sends that the server does not list is refused before the request leaves, which
the app cannot tell from having no signal. So every header the app adds to a request must be in the CORS list."""
from fastapi.middleware.cors import CORSMiddleware

import main


def allowed_headers():
    mw = next(m for m in main.app.user_middleware if m.cls is CORSMiddleware)
    return {h.lower() for h in (mw.kwargs.get("allow_headers") or [])}


def test_the_headers_the_offline_queue_adds_are_allowed_across_origins():
    allowed = allowed_headers()
    for header in ("Content-Type", "Idempotency-Key", "X-Base-Version"):
        assert header.lower() in allowed, header
