"""How errors the code did not expect are answered."""
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.application import app
from app.core.config import logger


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """A unique-constraint clash is a client mistake, not a server fault.
    Without this it surfaced as an opaque 500."""
    logger.warning("Integrity error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=409,
        content={"detail": "That record conflicts with one that already exists."},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """Log the traceback server-side, return a generic message to the client so
    internals are never echoed back."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred."})
