"""
Who is speaking on a document.

One place decides what the company puts at the head of everything it issues - the work order, the RA
bill, a register exported to Excel, a statement, a site form - and which of those details are
mandatory. Every document and every screen asks here rather than reading the company's fields itself,
so a logo or a GSTIN added once shows everywhere, and a missing one is noticed everywhere.

An "identity" is the dict `letterhead()` in main.py builds: name, code, address, gstin, pan, state and
logo_url (a data: URI). Nothing here touches the database.
"""
import base64
import io

# What must be on file before a document can honestly be issued, and the words used to ask for it.
REQUIRED = (
    ("name", "company name"),
    ("address", "address"),
    ("gstin", "GSTIN"),
    ("pan", "PAN"),
    ("logo_url", "logo"),
)


def missing_details(identity):
    """The mandatory details the company has not given, in the words a person would use."""
    identity = identity or {}
    return [label for key, label in REQUIRED if not str(identity.get(key) or "").strip()]


def logo_bytes(identity):
    """The logo as image bytes, or None when there is none or it will not decode."""
    value = str((identity or {}).get("logo_url") or "")
    if not value.startswith("data:image"):
        return None
    try:
        raw = base64.b64decode(value.partition(",")[2], validate=False)
    except Exception:
        return None
    return raw or None


def address_line(identity):
    return ", ".join(p.strip() for p in str((identity or {}).get("address") or "").splitlines() if p.strip())


def tax_line(identity):
    """"GSTIN : ...   PAN : ...   State" on one line, for what has a single line to spare."""
    i = identity or {}
    parts = []
    for label, key in (("GSTIN", "gstin"), ("PAN", "pan"), ("State", "state")):
        if i.get(key):
            parts.append("%s : %s" % (label, i[key]))
    return "   ".join(parts)


def sheet_head_rows(identity):
    """The company's lines for the top of a workbook: name, address, tax numbers."""
    i = identity or {}
    rows = []
    if i.get("name"):
        rows.append([str(i["name"]).upper()])
    if address_line(i):
        rows.append([address_line(i)])
    if tax_line(i):
        rows.append([tax_line(i)])
    return rows


def add_logo(ws, identity, anchor="A1", height=56):
    """Put the logo on a worksheet, scaled to `height` pixels. A logo that will not load is skipped -
    the sheet is still worth having."""
    raw = logo_bytes(identity)
    if not raw:
        return False
    try:
        from openpyxl.drawing.image import Image as XLImage
        image = XLImage(io.BytesIO(raw))
        if not image.height or not image.width:
            return False
        scale = height / float(image.height)
        image.height, image.width = height, max(1, int(image.width * scale))
        ws.add_image(image, anchor)
        return True
    except Exception:
        return False
