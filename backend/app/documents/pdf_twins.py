"""A .pdf beside every .xlsx."""
import contextvars
import functools

from fastapi import HTTPException

from app.core.application import app
from app.core.auth import require_items_access


SHEET_AS_PDF = contextvars.ContextVar("sheet_as_pdf", default=None)


def _pdf_twin(endpoint):
    @functools.wraps(endpoint)
    def twin(*args, **kwargs):
        request, db = kwargs.get("request"), kwargs.get("db")
        client = None
        if request is not None and db is not None:
            try:
                client = require_items_access(request, db, None)
            except HTTPException:
                client = None
        token = SHEET_AS_PDF.set({"client": client})
        try:
            return endpoint(*args, **kwargs)
        finally:
            SHEET_AS_PDF.reset(token)
    return twin


def add_pdf_twins():
    """A .pdf beside every .xlsx - added once every route exists."""
    from fastapi.routing import APIRoute
    import asyncio
    have = {r.path for r in app.routes if isinstance(r, APIRoute)}
    added = 0
    for r in list(app.routes):
        if not isinstance(r, APIRoute) or "GET" not in r.methods or not r.path.endswith(".xlsx"):
            continue
        if "/api/sheets/" in r.path or asyncio.iscoroutinefunction(r.endpoint):
            continue
        path = r.path[:-5] + ".pdf"
        if path in have:
            continue
        app.add_api_route(path, _pdf_twin(r.endpoint), methods=["GET"])
        added += 1
    return added
