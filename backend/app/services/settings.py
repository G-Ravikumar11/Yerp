"""The rules and workings behind the settings endpoints."""
import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import identity
from app import models

from app.constants.settings import (
    ADDRESS_POSITIONS,
    BACKUP_SECRET,
    BACKUP_SKIP_TABLES,
    DEFAULT_TAX_RATES,
    LOGO_POSITIONS,
    OLD_ALERT_DAYS,
    TAX_BREAKDOWNS,
    THEME_BOOLS,
    THEME_FONTS,
    THEME_STRINGS,
    UK_TAX_RATES,
)
from app.core.auth import get_client_user
from app.core.config import logger
from app.core.files import attachment_target
from app.core.notifications import notify
from app.core.scheduler import digest_key, scheduled_job
from app.documents.letterhead import letterhead
from app.services.projects import attention_items
from app.validators.common import valid_hex_colour


def tax_rate_label(name, percent):
    """The string stored on a line item.

    The percentage is always in the label, because parse_tax_rate reads the
    rate back out of it. A label of just "Consulting levy" would parse as the
    default 20%, silently taxing a line nobody meant to tax. The one exception
    is the plain no-tax entries, whose wording parse_tax_rate already knows and
    which would otherwise read as the odd "0% No Tax".
    """
    name = (name or "").strip()
    if not name:
        return f"{percent:g}%"
    if percent == 0 and name.lower() in ("no tax", "none", "exempt"):
        return name
    return f"{percent:g}% {name}"


def seed_default_tax_rates(db, client_id):
    """Give a tenant the standard list the first time they look."""
    rows = db.query(models.DBTaxRate).filter(
        models.DBTaxRate.client_id == client_id).order_by(models.DBTaxRate.sort_order).all()
    # A list still exactly as it was handed out - the UK one - was never
    # chosen by anybody; it is swapped for GST. A list somebody has edited
    # is theirs and is left alone.
    if rows and [(r.name, r.percent) for r in rows] == UK_TAX_RATES:
        for r in rows:
            db.delete(r)
        db.flush()
        rows = []
    if rows:
        return
    for order, (name, percent, is_default) in enumerate(DEFAULT_TAX_RATES):
        db.add(models.DBTaxRate(client_id=client_id, name=name, percent=percent,
                                sort_order=order, is_default=is_default))
    db.commit()


def tax_rate_to_dict(t):
    return {
        "id": t.id,
        "name": t.name,
        "percent": t.percent or 0.0,
        "label": tax_rate_label(t.name, t.percent or 0.0),
        "is_default": bool(t.is_default),
        "sort_order": t.sort_order or 0,
    }


def theme_to_dict(t) -> dict:
    out = {
        "id": t.id, "name": t.name, "is_default": bool(t.is_default),
        "logo_data": t.logo_data or "", "logo_position": t.logo_position or "right",
        "brand_color": t.brand_color or "#4F46E5", "font": t.font or "helvetica",
        "tax_breakdown": t.tax_breakdown or "separate_rates",
        "address_position": t.address_position or "default",
        "updated_at": t.updated_at or "",
    }
    for f in THEME_BOOLS:
        out[f] = bool(getattr(t, f))
    for f in THEME_STRINGS:
        out[f] = getattr(t, f) or ""
    return out


def apply_theme_fields(theme, body: dict):
    """Copy whatever the caller sent, ignoring anything it may not set.

    Deliberately a whitelist: a theme is rendered into a PDF and echoed into
    the preview, so an unexpected key must never reach either.
    """
    if "name" in body:
        name = (body.get("name") or "").strip()[:60]
        if not name:
            raise HTTPException(status_code=400, detail="A theme needs a name")
        theme.name = name
    if "logo_data" in body:
        logo = body.get("logo_data") or ""
        # Matched in full, not just by prefix. This string is written into an
        # <img src> and into a PDF, so a quote or an angle bracket smuggled in
        # after a valid-looking prefix must never be stored.
        if logo and not re.fullmatch(
                r"data:image/(png|jpe?g|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=\s]+",
                logo):
            raise HTTPException(
                status_code=400,
                detail="The logo must be a base64 image (PNG, JPEG, GIF or WebP)")
        if len(logo) > 3_000_000:
            raise HTTPException(status_code=400,
                                detail="That logo is too large - keep it under about 2MB")
        theme.logo_data = logo
    if "logo_position" in body and body["logo_position"] in LOGO_POSITIONS:
        theme.logo_position = body["logo_position"]
    if "brand_color" in body:
        theme.brand_color = valid_hex_colour(body["brand_color"], theme.brand_color or "#4F46E5")
    if "font" in body and body["font"] in THEME_FONTS:
        theme.font = body["font"]
    if "tax_breakdown" in body and body["tax_breakdown"] in TAX_BREAKDOWNS:
        theme.tax_breakdown = body["tax_breakdown"]
    if "address_position" in body and body["address_position"] in ADDRESS_POSITIONS:
        theme.address_position = body["address_position"]
    for f in THEME_BOOLS:
        if f in body:
            setattr(theme, f, bool(body[f]))
    for f in THEME_STRINGS:
        if f in body:
            setattr(theme, f, str(body[f] or "")[:2000])
    theme.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_default_theme(db: Session, client_id: int):
    """Every account has at least one theme, so the PDF code never has to cope
    with there being none."""
    existing = db.query(models.DBBrandingTheme).filter(
        models.DBBrandingTheme.client_id == client_id).count()
    if existing:
        return
    db.add(models.DBBrandingTheme(client_id=client_id, name="Standard", is_default=True))
    db.commit()


def default_theme_for(db: Session, client_id: int):
    ensure_default_theme(db, client_id)
    theme = db.query(models.DBBrandingTheme).filter(
        models.DBBrandingTheme.client_id == client_id,
        models.DBBrandingTheme.is_default == True).first()  # noqa: E712
    if not theme:
        theme = db.query(models.DBBrandingTheme).filter(
            models.DBBrandingTheme.client_id == client_id
        ).order_by(models.DBBrandingTheme.id.asc()).first()
    return theme


def storage_orphan_files(db, client_id):
    """Files kept against a record that no longer exists: [(id, size)]."""
    rows = db.query(models.DBFile.id, models.DBFile.attached_type, models.DBFile.attached_id, models.DBFile.size,
                    models.DBFile.blob_of).filter(models.DBFile.client_id == client_id).all()
    pinned = {r[0] for r in db.query(models.DBDrawingRevision.file_id).filter(
        models.DBDrawingRevision.file_id.isnot(None)).all()}
    gone, seen = [], {}
    for fid, atype, aid, size, blob_of in rows:
        if not aid or fid in pinned:
            continue
        key = (atype or "job", aid)
        if key not in seen:
            try:
                attachment_target(db, client_id, key[0], key[1])
                seen[key] = False
            except HTTPException as exc:
                # Only a record that is not there counts; a kind this does not know is left alone.
                seen[key] = exc.status_code == 404
        if seen[key]:
            gone.append((fid, 0 if blob_of else (size or 0)))
    # A file that a living one reads its bytes from has to stay, whatever it was kept against.
    dead = {fid for fid, _ in gone}
    if dead:
        alive_readers = {r[0] for r in db.query(models.DBFile.blob_of).filter(
            models.DBFile.client_id == client_id, models.DBFile.blob_of.in_(list(dead)),
            ~models.DBFile.id.in_(list(dead))).all()}
        gone = [(fid, size) for fid, size in gone if fid not in alive_readers]
    return gone


def storage_old_alerts(db, client_id):
    cutoff = (datetime.now() - timedelta(days=OLD_ALERT_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    return [r[0] for r in db.query(models.DBAlert.id).filter(
        models.DBAlert.client_id == client_id, models.DBAlert.created_at < cutoff).all()]


def viewer_key(request):
    member = request.session.get("member_id")
    return "member:%s" % member if member else "owner"


def _put_setting(db, client_id, key, value):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id,
                                             models.DBSettings.key == key).first()
    if row:
        row.value = value
    else:
        db.add(models.DBSettings(client_id=client_id, key=key, value=value))


@scheduled_job("morning_digest", digest_key)
def job_morning_digest(db, now):
    """Every morning, the dashboard's list as one message - only when there
    is something on it, and not before seven."""
    if now.hour < 7:
        return "too early"
    sent = 0
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        try:
            items = attention_items(db, client.id)
        except Exception as exc:
            logger.error("Digest for %s failed: %s", client.id, exc)
            continue
        if not items:
            continue
        lines = ["- %s: %s" % (i["title"], i["detail"]) for i in items[:8]]
        notify(db, client.id, "daily_digest",
               "%d thing%s worth a look today" % (len(items), "" if len(items) == 1 else "s"),
               "\n".join(lines), view="dashboard-view", severity="action")
        sent += 1
    return "%d digest(s)" % sent


def backup_tables(db, client_id):
    """{table name: [row dicts]} for everything this company owns: the rows
    carrying its client_id, then the lines hanging off those, and so on down."""
    from sqlalchemy import select
    tables = [t for t in models.Base.metadata.sorted_tables if t.name not in BACKUP_SKIP_TABLES]
    out, ids = {}, {}
    for t in tables:
        if t.name == "clients":
            rows = db.execute(select(t).where(t.c.id == client_id)).mappings().all()
        elif "client_id" in t.c:
            rows = db.execute(select(t).where(t.c.client_id == client_id)).mappings().all()
        else:
            continue
        out[t.name] = [dict(r) for r in rows]
        ids[t.name] = {r["id"] for r in out[t.name] if "id" in r}
    # Lines of lines: follow each table's first foreign key that leads to
    # something already taken, until nothing more joins.
    pending = [t for t in tables if t.name not in out]
    progress = True
    while pending and progress:
        progress = False
        for t in list(pending):
            owner = next((c for c in t.c for fk in c.foreign_keys
                          if fk.column.table.name in ids), None)
            if owner is None:
                continue
            parent = next(iter(owner.foreign_keys)).column.table.name
            wanted = sorted(ids[parent])
            rows = []
            for i in range(0, len(wanted), 500):
                chunk = wanted[i:i + 500]
                if chunk:
                    rows += [dict(r) for r in db.execute(select(t).where(owner.in_(chunk))).mappings().all()]
            out[t.name] = rows
            ids[t.name] = {r["id"] for r in rows if "id" in r}
            pending.remove(t)
            progress = True
    return out


def _backup_clean(table, row):
    """A row as it goes in the backup: secrets out, binary left to the files."""
    clean = {}
    for k, v in row.items():
        if BACKUP_SECRET.search(k):
            v = "[removed]" if v else v
        elif isinstance(v, (bytes, bytearray, memoryview)):
            v = None
        clean[k] = v
    if table == "settings" and BACKUP_SECRET.search(str(clean.get("key") or "")):
        clean["value"] = "[removed]" if clean.get("value") else clean.get("value")
    return clean


def backup_owner(request, db):
    """The account holder alone. A backup is the whole business in one file."""
    client = get_client_user(request, db)
    if request.session.get("member_id"):
        raise HTTPException(403, "Only the account holder can take a full backup.")
    return client


def company_identity(db, client, unit_id=None):
    """The one company block every document and screen is headed with, and what of it is still missing."""
    me = letterhead(db, client, unit_id)
    me["missing"] = identity.missing_details(me)
    return me
