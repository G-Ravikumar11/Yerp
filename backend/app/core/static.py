"""The React app (frontend/dist, served at /next/), the front page at /, and a few files at the root."""
import os
import re

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.application import app
from app.core.config import FRONTEND_DIST, STATIC_DIR, logger


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

HOME_TITLE = "Yalavarti Infra Projects | Homes, Townships &amp; Civil Infrastructure"
HOME_DESCRIPTION = ("Yalavarti Infra Projects - civil engineering and construction: houses and villas, apartments, gated "
                    "townships, roads, drainage, water supply and sewerage, from the land and its approvals to handover.")
HOME_HEAD = (
    '<meta name="description" content="%s">'
    '<meta property="og:type" content="website">'
    '<meta property="og:site_name" content="Yalavarti Infra Projects">'
    '<meta property="og:title" content="Yalavarti Infra Projects | Building homes, townships and the infrastructure around them">'
    '<meta property="og:description" content="Houses and villas, apartments, gated townships, roads, drainage and water '
    'works - one civil builder from the plot to the keys.">'
    '<meta property="og:image" content="%%s/next/site/img/cat3.jpg">'
    '<meta name="theme-color" content="#000000">' % HOME_DESCRIPTION.replace("'", "&#39;"))


def _public_base(request: Request):
    """https://yalavartiinfra.com as the visitor typed it. Behind Railway's proxy the app itself is reached over http, so
    the scheme the visitor used comes from the proxy's header."""
    base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto", "") == "https" and base.startswith("http://"):
        base = "https://" + base[len("http://"):]
    return base


async def home(request: Request):
    """The company's front page is a page of the React app. Its title and description are put into the HTML here, so a
    search engine or a link preview sees them without running the app. The preview picture is a full address: WhatsApp
    and Facebook skip one given as a path."""
    index = os.path.join(FRONTEND_DIST, "index.html")
    if not os.path.exists(index):
        return Response("Front page not built", status_code=404)
    with open(index, encoding="utf8") as f:
        html = f.read()
    html = re.sub(r"<title>.*?</title>", "<title>%s</title>" % HOME_TITLE, html, count=1, flags=re.S)
    html = re.sub(r'<meta name="(description|theme-color)"[^>]*>', "", html)
    html = html.replace("</head>", HOME_HEAD % _public_base(request) + "</head>", 1)
    return HTMLResponse(html)


app.add_api_route("/", home, methods=["GET"], include_in_schema=False)


# What a search engine is told: the front page and the careers page are for it; the ERP and its API are not.
async def robots(request: Request):
    base = str(request.base_url).rstrip("/")
    return Response("User-agent: *\nAllow: /$\nAllow: /next/jobs\nDisallow: /next/\nDisallow: /api/\n\nSitemap: %s/sitemap.xml\n" % base,
                    media_type="text/plain")


async def sitemap(request: Request):
    base = str(request.base_url).rstrip("/")
    # One page: the front page. The careers page needs the company's reference in its link, which the front page carries.
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    '<url><loc>%s/</loc></url></urlset>' % base,
                    media_type="application/xml")


app.add_api_route("/robots.txt", robots, methods=["GET"], include_in_schema=False)
app.add_api_route("/sitemap.xml", sitemap, methods=["GET"], include_in_schema=False)

# Files that must answer at the root of the site, not under /next/.
#   /sw.js and /manifest.webmanifest belong to the old app. A phone that installed it still asks for them; this sw.js
#   removes itself and its caches, so those phones stop showing the old pages. Kept in app/static.
#   The favicons and /icons are the React app's own, taken from its build.
def _file(path, media_type=None):
    async def send():
        if not os.path.exists(path):
            return Response(status_code=404)
        return FileResponse(path, media_type=media_type)
    return send


ROOT_FILES = {
    "/sw.js": (os.path.join(STATIC_DIR, "legacy-sw.js"), "application/javascript"),
    "/manifest.webmanifest": (os.path.join(STATIC_DIR, "legacy-manifest.webmanifest"), "application/manifest+json"),
    "/favicon.ico": (os.path.join(FRONTEND_DIST, "favicon.ico"), "image/x-icon"),
    "/favicon.svg": (os.path.join(FRONTEND_DIST, "favicon.svg"), "image/svg+xml"),
    "/favicon-32.png": (os.path.join(FRONTEND_DIST, "favicon-32.png"), "image/png"),
}
for _path, (_file_path, _type) in ROOT_FILES.items():
    app.add_api_route(_path, _file(_file_path, _type), methods=["GET"], include_in_schema=False)

if os.path.isdir(FRONTEND_DIST):
    # Not every platform's mime table knows the app manifest; without the right type a browser will not offer to install.
    import mimetypes
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    app.mount("/next", SinglePageApp(directory=FRONTEND_DIST, html=True), name="frontend")
    if os.path.isdir(os.path.join(FRONTEND_DIST, "icons")):
        app.mount("/icons", StaticFiles(directory=os.path.join(FRONTEND_DIST, "icons")), name="icons")
else:
    logger.warning("The React app is not built (%s missing): run `npm run build` in frontend/", FRONTEND_DIST)
