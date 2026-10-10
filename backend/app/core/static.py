"""The React app and the old front page, served last."""
import os
import re

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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


# The pages that used to be separate HTML files now live inside the React app. Links already sent in emails, saved
# bookmarks and Google's redirects still name the old addresses, so each one is forwarded, with its query string.
LEGACY_PAGES = {
    "index.html": "/",
    "login.html": "/next/login",
    "employee-login.html": "/next/login",
    "reset-password.html": "/next/reset-password",
    "superadmin-login.html": "/next/superadmin/login",
    "superadmin.html": "/next/superadmin",
    "portal.html": "/next/portal",
    "onboard.html": "/next/onboard",
    "jobs.html": "/next/jobs",
    "recruitment.html": "/next/apply",
    "meeting.html": "/next/meeting",
    "app.html": "/next/",
    "employee-dashboard.html": "/next/",
    "hr.html": "/next/people/employees",
}


def _forward(target: str):
    async def go(request: Request):
        query = request.url.query
        return RedirectResponse(target + (("?" + query) if query else ""))
    return go


for _page, _target in LEGACY_PAGES.items():
    app.add_api_route("/" + _page, _forward(_target), methods=["GET"], include_in_schema=False)

HOME_TITLE = "Yalavarti Projects | Electrical, Fire &amp; PHE Contractors, Hyderabad"
HOME_DESCRIPTION = ("Yalavarti Projects Pvt. Ltd. - electrical works up to 33 kV, fire protection, plumbing and panels for "
                    "India's landmarks. Hyderabad, since 1998.")
HOME_HEAD = (
    '<meta name="description" content="%s">'
    '<meta property="og:type" content="website">'
    '<meta property="og:title" content="Yalavarti Projects | Powering India&#39;s landmarks">'
    '<meta property="og:description" content="Electrical works up to 33 kV, fire protection, plumbing and panels for '
    'India&#39;s leading developers. Hyderabad, since 1998.">'
    '<meta property="og:image" content="/next/site/img/banner1.jpg">'
    '<meta name="theme-color" content="#000000">' % HOME_DESCRIPTION.replace("'", "&#39;"))


async def home():
    """The company's front page is a page of the React app. Its title and description are put into the HTML here, so a
    search engine or a link preview sees them without running the app."""
    index = os.path.join(next_path, "index.html")
    if not os.path.exists(index):
        return Response("Front page not built", status_code=404)
    with open(index, encoding="utf8") as f:
        html = f.read()
    html = re.sub(r"<title>.*?</title>", "<title>%s</title>" % HOME_TITLE, html, count=1, flags=re.S)
    html = re.sub(r'<meta name="(description|theme-color)"[^>]*>', "", html)
    html = html.replace("</head>", HOME_HEAD + "</head>", 1)
    return HTMLResponse(html)


app.add_api_route("/", home, methods=["GET"], include_in_schema=False)

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
