"""What the phone app may do, on top of what a person's ordinary access allows.

The website and the phone app are the same server and the same accounts. They differ in how much each lets a person
change. Signing in from the app stamps the session `channel = "app"` (set_session_lifetime in auth.py); from then on
every request on that session is held to the rules below. The stamp is in the signed cookie, so a copy of it cannot be
used to slip out of them, and a person who signs in on the website is not held to them at all.

Who is NOT held to them: the Master (the account holder), the account's admins, and staff whose access level is Master.
The app is the whole website to them.

Everybody else, in the app:
  - looks at everything their access lets them see (a read is never refused here),
  - changes nothing, except what one of the four "Phone app" rights allows (app.* in permissions.py), which the Master
    gives or takes away person by person on the Access screen:
        app.site_edit      record site work: diary, photos, measurements, material in, safety, quality, task progress
        app.approve        approve and reject
        app.download_pdf   download a PDF (a bill, an order, a report)
        app.download_excel download an Excel report
  - and does their own things whatever the rights: sign in and out, clock in, apply for leave, chat, push token.
Billing, orders, settings, people, deleting anything: not from the app, for anyone but the Master and admins.

This is the one place the rules live. To open or close something in the app, change the tables here.
"""
import re

from fastapi import HTTPException

READS = frozenset({"GET", "HEAD", "OPTIONS"})

APP_PDF = "app.download_pdf"
APP_EXCEL = "app.download_excel"
APP_SITE = "app.site_edit"
APP_APPROVE = "app.approve"
APP_KEYS = (APP_SITE, APP_APPROVE, APP_PDF, APP_EXCEL)

_LABELS = {
    APP_SITE: "Record site work in the app",
    APP_APPROVE: "Approve and reject in the app",
    APP_PDF: "Download PDFs in the app",
    APP_EXCEL: "Download Excel reports in the app",
}

# A person's own business, open whatever they hold: signing in and out, their clock-in and leave, chat, the phone's
# push token, the public pages, and the app's own update check.
_OWN = re.compile(
    r"^/api/(client/(login|logout|forgot-password|reset-password)|employee/|devices|chat|attendance|leave|auth/|public/|app/)")

# Site work: what a site engineer does from the site.
_SITE = re.compile(
    r"^/api/(diary|files|schedule|mb|sub-mb|grn|stock-issues|stock|safety|qc|plant"
    r"|jobs/\d+/(schedule/tasks|diary|photos))(/|$)")

# Approving: the approvals inbox and any step that is a decision.
_APPROVE = re.compile(r"^/api/approvals(/|$)|/(approve|reject|certify|decide|sign-off|signoff)$")

# Asking for a link to a stored file (how the app hands a PDF to the phone's browser): a download, not an edit.
_FILE_LINK = re.compile(r"^/api/files/\d+/link$")

_DOWNLOAD_EXCEL = (".xlsx", ".xls", ".csv")


def free_account(team_role):
    """The account holder (no team role) and the account's admins are not held to the app's rules."""
    return team_role in (None, "owner", "admin")


def free_staff(permission_role):
    """Staff at the Master access level are not held to them either."""
    return (permission_role or "").lower() == "owner"


def account_rights(team_role):
    """What a read-only member of the account is given in the app: the downloads, since they may already see it all."""
    return {APP_PDF, APP_EXCEL} if team_role == "viewer" else set()


def _refuse(permission):
    if permission is None:
        return "That is not available in the app. Use the website."
    return "Your access does not include: %s. Ask your administrator." % _LABELS[permission]


def refusal(method, path, held):
    """None if this request may go ahead from the app, else the plain-language reason it may not. `held` is the set of
    rights the person holds (the app.* ones matter here)."""
    path = path or ""
    if method in READS:
        low = path.lower()
        if low.endswith(".pdf") and APP_PDF not in held:
            return _refuse(APP_PDF)
        if low.endswith(_DOWNLOAD_EXCEL) and APP_EXCEL not in held:
            return _refuse(APP_EXCEL)
        return None
    if _OWN.match(path):
        return None
    if _FILE_LINK.match(path):
        return None if APP_PDF in held else _refuse(APP_PDF)
    if _APPROVE.search(path):
        return None if APP_APPROVE in held else _refuse(APP_APPROVE)
    if _SITE.match(path):
        return None if APP_SITE in held else _refuse(APP_SITE)
    return _refuse(None)


def enforce(request, held, free):
    """Raise 403 when this app-channel request is not allowed. Does nothing on the website, or for someone who is free."""
    # Kept for the rest of this request: a route that learns more later (the type of a stored file) can ask again.
    request.state.app_rights = (held, free)
    if free or channel_of(request) != "app":
        return
    why = refusal(request.method, request.url.path, held)
    if why:
        raise HTTPException(status_code=403, detail=why)


_SPREADSHEETS = ("spreadsheetml", "ms-excel", "csv")


def check_stored_file(request, content_type):
    """A stored file fetched by its number: a picture is site work and may always be seen, but a PDF, a drawing or any other
    document is a download (and a spreadsheet an Excel download), which in the app is a right. Only the app is checked."""
    held_free = getattr(request.state, "app_rights", None)
    if channel_of(request) != "app" or not held_free or held_free[1]:
        return
    kind = (content_type or "").lower()
    if kind.startswith("image/"):
        return
    need = APP_EXCEL if any(s in kind for s in _SPREADSHEETS) else APP_PDF
    if need not in held_free[0]:
        raise HTTPException(status_code=403, detail=_refuse(need))


def channel_of(request):
    """"app" or "web": where this session was signed in."""
    try:
        return "app" if request.session.get("channel") == "app" else "web"
    except (AssertionError, AttributeError):
        return "web"


def summary(request, held, free):
    """What the screens need to match the server: the channel, and which of the four rights apply."""
    app = channel_of(request) == "app"
    return {
        "channel": "app" if app else "web",
        "app_limited": bool(app and not free),
        "app_rights": {k: (not app) or free or k in held for k in APP_KEYS},
    }
