"""The React app (frontend/dist, served at /next/), the front page at /, and a few files at the root."""
import os
import re
from html import escape as html_escape

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

HOME_TITLE = "Yalavarti Infra Projects | Homes, Townships & Civil Infrastructure"
HOME_DESCRIPTION = ("Yalavarti Infra Projects - civil engineering and construction: houses and villas, apartments, gated "
                    "townships, roads, drainage, water supply and sewerage, from the land and its approvals to handover.")
HOME_IMAGE = "/next/site/img/sites/giddaluru-c2.jpg"
# The site's paper or blueprint, set before the page is drawn so it never flashes the other: the visitor's own choice (the
# top strip's switch), else their device's.
THEME_SCRIPT = ("<script>(function(){try{var t=localStorage.getItem('yip-theme');if(t==='light'||t==='dark')"
                "document.documentElement.setAttribute('data-theme',t)}catch(e){}})()</script>")
PAGES = {"/": "", "/projects": "Projects | "}


def _attr(text):
    return html_escape(text or "", quote=True)


def _seo():
    """The search and sharing words as last published in Settings -> Website: {title, description, image}, empty where unset."""
    try:
        from app.db import SessionLocal
        from app import models
        from app.services import website_content
        with SessionLocal() as db:
            c = db.query(models.DBClient).filter(models.DBClient.is_onboarded.is_(True)).order_by(models.DBClient.id).first()
            return (website_content.published(db, c.id).get("seo") or {}) if c else {}
    except Exception:
        return {}


def home_head(base, seo, prefix=""):
    """The front page's title and the lines a search engine and a shared link read."""
    title = prefix + ((seo.get("title") or "").strip() or HOME_TITLE)
    description = (seo.get("description") or "").strip() or HOME_DESCRIPTION
    image = (seo.get("image") or "").strip()
    image = (base + image) if image.startswith("/api/") else (base + "/next/" + image) if image.startswith("site/") else (base + HOME_IMAGE)
    return title, (
        '<meta name="description" content="%s">'
        '<meta property="og:type" content="website">'
        '<meta property="og:site_name" content="Yalavarti Infra Projects">'
        '<meta property="og:title" content="%s">'
        '<meta property="og:description" content="%s">'
        '<meta property="og:image" content="%s">'
        '<meta name="theme-color" content="#f7f9fb" media="(prefers-color-scheme: light)">'
        '<meta name="theme-color" content="#0a2442" media="(prefers-color-scheme: dark)">%s'
    ) % (_attr(description), _attr(title), _attr(description), _attr(image), THEME_SCRIPT)


HOME_NOSCRIPT = ('<noscript><p style="font-family: system-ui, sans-serif; padding: 2rem; text-align: center">'
                 'Yalavarti Infra Projects - homes, townships and civil infrastructure. This page needs JavaScript; '
                 'please turn it on, or write to us at <a href="mailto:info@yalavartiinfra.com">info@yalavartiinfra.com</a>.'
                 '</p></noscript>')


def _public_base(request: Request):
    """https://yalavartiinfra.com as the visitor typed it. Behind Railway's proxy the app itself is reached over http, so
    the scheme the visitor used comes from the proxy's header."""
    base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto", "") == "https" and base.startswith("http://"):
        base = "https://" + base[len("http://"):]
    return base


async def home(request: Request):
    """The company's front page (and its projects page) is a page of the React app. Its title and description are put into
    the HTML here, so a search engine or a link preview sees them without running the app - as last published in Settings
    -> Website, else the built-in ones. The preview picture is a full address: WhatsApp and Facebook skip one given as a path."""
    index = os.path.join(FRONTEND_DIST, "index.html")
    if not os.path.exists(index):
        return Response("Front page not built", status_code=404)
    with open(index, encoding="utf8") as f:
        html = f.read()
    title, head = home_head(_public_base(request), _seo(), PAGES.get(request.url.path, ""))
    html = re.sub(r"<title>.*?</title>", "<title>%s</title>" % _attr(title), html, count=1, flags=re.S)
    html = re.sub(r'<meta name="(description|theme-color)"[^>]*>', "", html)
    # The ERP's own words stay on the ERP: a visitor without JavaScript, and a search engine, see the company's.
    html = re.sub(r"<noscript>.*?</noscript>", HOME_NOSCRIPT, html, count=1, flags=re.S)
    html = html.replace("</head>", head + "</head>", 1)
    return HTMLResponse(html)


for _path in PAGES:
    app.add_api_route(_path, home, methods=["GET"], include_in_schema=False)


# What a search engine is told: the front page and the careers page are for it; the ERP and its API are not. The front
# page is drawn by the app's script, so the files it is drawn with - the scripts and styles, its photos, the logo and icons,
# and the public figures it reads - stay open too: blocked, Google sees an empty page and keeps an old copy instead. The
# longer rule wins, so these open their own folders and leave the rest of /next/ and /api/ closed.
ROBOTS_OPEN = ("/$", "/projects", "/next/jobs", "/next/assets/", "/next/site/", "/next/brand/", "/next/icons/", "/next/favicon",
               "/next/logo.png", "/next/manifest.webmanifest", "/api/public/site")


async def robots(request: Request):
    base = _public_base(request)
    rules = "".join("Allow: %s\n" % p for p in ROBOTS_OPEN)
    return Response("User-agent: *\n%sDisallow: /next/\nDisallow: /api/\n\nSitemap: %s/sitemap.xml\n" % (rules, base),
                    media_type="text/plain")


async def sitemap(request: Request):
    base = _public_base(request)
    # The front page and its projects page. The careers page needs the company's reference in its link, which the front
    # page carries.
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    '<url><loc>%s/</loc></url><url><loc>%s/projects</loc></url></urlset>' % (base, base),
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
