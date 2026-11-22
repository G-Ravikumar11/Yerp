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


def test_cors_is_the_outermost_layer_so_no_reply_loses_its_headers():
    """The idempotency layer rebuilds a reply keeping only its type, and a replay never reaches the layers inside it. Were
    CORS inside, those replies would reach the phone without Access-Control-Allow-Origin: the browser hides the answer, the
    app reads a dropped connection, and the saved day is sent again and again though the server has it."""
    layers = main.app.user_middleware      # the first is the outermost
    assert layers[0].cls is CORSMiddleware, [m.cls.__name__ for m in layers]
