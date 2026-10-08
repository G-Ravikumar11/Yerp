"""The React app and the old front page, served last."""
import os

from fastapi.staticfiles import StaticFiles

from app.core.application import app
from app.core.config import frontend_path, logger, next_path


class SinglePageApp(StaticFiles):
    """The React app: any address that is not a file is the app's own route.

    /next/subcontractors/work-orders is a page inside the app, not a file, so
    reloading it (or opening a link to it) has to serve the app and let its
    router draw the page. A missing file with an extension is a real 404."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except Exception as exc:  # starlette's HTTPException for a missing file
            if getattr(exc, "status_code", None) == 404 and "." not in os.path.basename(path):
                return await super().get_response("index.html", scope)
            raise


if os.path.isdir(next_path):
    # Not every platform's mime table knows the app manifest; without the right type a browser will not offer to install.
    import mimetypes
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    # Before the "/" mount below, which would otherwise answer /next itself.
    app.mount("/next", SinglePageApp(directory=next_path, html=True), name="frontend-next")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
else:
    logger.warning(f"Frontend directory not found at {frontend_path}")
