"""The settings endpoints."""
import io
import json
import os
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.settings import OLD_ALERT_DAYS, SETTINGS_ON_THE_COMPANY, THEME_FONTS
from app.core.audit import log_audit
from app.core.auth import get_client_user, get_employee_user, require_erp_read, require_owner
from app.core.currency import DEFAULT_CURRENCY
from app.core.files import file_bytes
from app.core.gst import state_from_gstin
from app.core.notifications import NOTIFY_KINDS, get_stored_refresh_token, notify, notify_settings
from app.core.security import rate_limiter
from app.schemas.settings import NotificationReadIn, NotificationSettingsIn, TaxRatesIn
from app.services.settings import (
    _backup_clean,
    _put_setting,
    apply_theme_fields,
    backup_owner,
    backup_tables,
    company_identity,
    default_theme_for,
    ensure_default_theme,
    seed_default_tax_rates,
    storage_old_alerts,
    storage_orphan_files,
    tax_rate_label,
    tax_rate_to_dict,
    theme_to_dict,
    viewer_key,
)
from app.services.subcontract_orders import sweep_referrers
from app.validators.common import validate_email_address, validate_tax_rate


router = APIRouter()


@router.get("/api/settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    settings = db.query(models.DBSettings).filter(models.DBSettings.client_id == client.id).all()
    out = {s.key: s.value for s in settings}
    # The company's own details, where Settings has none of its own: the form
    # showed a blank name for a company whose name is on every document.
    for key, column in SETTINGS_ON_THE_COMPANY.items():
        if not (out.get(key) or "").strip():
            out[key] = getattr(client, column, "") or ""
    if not (out.get("company_email") or "").strip():
        out["company_email"] = client.email or ""
    if client.gstin:
        out["company_abn"] = client.gstin      # the one the documents use
    if not (out.get("currency") or "").strip():
        out["currency"] = client.currency or DEFAULT_CURRENCY
    return out


@router.post("/api/settings")
def save_settings(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    # The box on the Company details form is headed GSTIN but was stored as
    # an "ABN" setting nothing read - bills and e-invoices take the company's
    # GSTIN, set only on the GST screen. What is typed there is that GSTIN.
    gstin = ((body or {}).get("company_abn") or "").strip().upper().replace(" ", "")
    if gstin:
        if len(gstin) != 15 or not state_from_gstin(gstin):
            raise HTTPException(400, "A GSTIN is fifteen characters and starts with a state code.")
        client.gstin, client.state_code = gstin, state_from_gstin(gstin)
        body["company_abn"] = gstin
    if body:
        for key, val in body.items():
            setting = db.query(models.DBSettings).filter(models.DBSettings.key == key, models.DBSettings.client_id == client.id).first()
            if setting:
                setting.value = str(val)
            else:
                setting = models.DBSettings(key=key, value=str(val), client_id=client.id)
                db.add(setting)
            column = SETTINGS_ON_THE_COMPANY.get(key)
            if column and str(val or "").strip():
                setattr(client, column, str(val).strip())
    db.commit()
    return {"message": "Settings saved"}


@router.get("/api/audit-logs")
def get_audit_logs(request: Request, limit: int = 100, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    logs = db.query(models.DBAuditLog).filter(
        models.DBAuditLog.client_id == client.id
    ).order_by(models.DBAuditLog.created_at.desc()).limit(limit).all()
    return [{
        "id": l.id, "user_type": l.user_type, "user_name": l.user_name,
        "action": l.action, "entity_type": l.entity_type, "entity_id": l.entity_id,
        "entity_name": l.entity_name, "details": l.details, "ip_address": l.ip_address,
        "created_at": l.created_at,
    } for l in logs]


@router.get("/api/tax-rates")
def list_tax_rates(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    seed_default_tax_rates(db, client.id)
    rows = db.query(models.DBTaxRate).filter(
        models.DBTaxRate.client_id == client.id
    ).order_by(models.DBTaxRate.sort_order.asc(), models.DBTaxRate.id.asc()).all()
    return [tax_rate_to_dict(t) for t in rows]


@router.put("/api/tax-rates")
def replace_tax_rates(body: TaxRatesIn, request: Request, db: Session = Depends(get_db)):
    """Save the whole list at once, which is how the settings screen edits it.

    Validated in full before anything is written, so a bad row cannot leave the
    tenant with half a list.
    """
    client = get_client_user(request, db)
    if not body.tax_rates:
        raise HTTPException(status_code=400, detail="Keep at least one tax rate")
    if len(body.tax_rates) > 40:
        raise HTTPException(status_code=400, detail="That is more tax rates than the picker can hold (40 max)")

    cleaned = []
    seen = set()
    for row in body.tax_rates:
        name, pct = validate_tax_rate(row.name, row.percent)
        label = tax_rate_label(name, pct)
        key = label.lower()
        if key in seen:
            raise HTTPException(status_code=400,
                                detail=f"'{label}' is in the list twice")
        seen.add(key)
        cleaned.append((name, pct, bool(row.is_default)))

    # Exactly one default, so the line editor always has something to preselect.
    if not any(d for _, _, d in cleaned):
        cleaned[0] = (cleaned[0][0], cleaned[0][1], True)
    else:
        first_default = next(i for i, (_, _, d) in enumerate(cleaned) if d)
        cleaned = [(n, p, i == first_default) for i, (n, p, _) in enumerate(cleaned)]

    db.query(models.DBTaxRate).filter(models.DBTaxRate.client_id == client.id).delete()
    for order, (name, pct, is_default) in enumerate(cleaned):
        db.add(models.DBTaxRate(client_id=client.id, name=name, percent=pct,
                                sort_order=order, is_default=is_default))
    log_audit(db, client.id, "tax_rates_updated", "settings", None, "Tax rates",
              f"{len(cleaned)} rates", request)
    db.commit()

    rows = db.query(models.DBTaxRate).filter(
        models.DBTaxRate.client_id == client.id
    ).order_by(models.DBTaxRate.sort_order.asc()).all()
    return [tax_rate_to_dict(t) for t in rows]


@router.get("/api/branding-themes")
def list_branding_themes(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    ensure_default_theme(db, client.id)
    rows = db.query(models.DBBrandingTheme).filter(
        models.DBBrandingTheme.client_id == client.id
    ).order_by(models.DBBrandingTheme.is_default.desc(),
               models.DBBrandingTheme.name.asc()).all()
    return {"themes": [theme_to_dict(t) for t in rows],
            "fonts": list(THEME_FONTS)}


@router.get("/api/branding-themes/default")
def get_default_branding_theme(request: Request, db: Session = Depends(get_db)):
    """What the PDF renderer asks for. Always answers with a theme."""
    client = get_client_user(request, db)
    return theme_to_dict(default_theme_for(db, client.id))


@router.post("/api/branding-themes")
def create_branding_theme(request: Request, body: dict = None,
                          db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    body = body or {}
    ensure_default_theme(db, client.id)

    name = (body.get("name") or "").strip()[:60] or "New theme"
    clash = db.query(models.DBBrandingTheme).filter(
        models.DBBrandingTheme.client_id == client.id,
        models.DBBrandingTheme.name == name).first()
    if clash:
        raise HTTPException(status_code=400,
                            detail=f"You already have a theme called '{name}'")

    theme = models.DBBrandingTheme(client_id=client.id, name=name)
    body = dict(body)
    body.pop("name", None)
    apply_theme_fields(theme, body)
    db.add(theme)
    db.commit()
    db.refresh(theme)
    log_audit(db, client.id, "branding_theme_created", "branding", theme.id,
              theme.name, "", request)
    db.commit()
    return theme_to_dict(theme)


@router.put("/api/branding-themes/{theme_id}")
def update_branding_theme(theme_id: int, request: Request, body: dict = None,
                          db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    theme = db.query(models.DBBrandingTheme).filter(
        models.DBBrandingTheme.id == theme_id,
        models.DBBrandingTheme.client_id == client.id).first()
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    body = dict(body or {})
    new_name = (body.get("name") or "").strip()[:60]
    if new_name and new_name != theme.name:
        clash = db.query(models.DBBrandingTheme).filter(
            models.DBBrandingTheme.client_id == client.id,
            models.DBBrandingTheme.name == new_name,
            models.DBBrandingTheme.id != theme.id).first()
        if clash:
            raise HTTPException(status_code=400,
                                detail=f"You already have a theme called '{new_name}'")

    apply_theme_fields(theme, body)
    log_audit(db, client.id, "branding_theme_updated", "branding", theme.id,
              theme.name, "", request)
    db.commit()
    db.refresh(theme)
    return theme_to_dict(theme)


@router.post("/api/branding-themes/{theme_id}/default")
def set_default_branding_theme(theme_id: int, request: Request,
                               db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    theme = db.query(models.DBBrandingTheme).filter(
        models.DBBrandingTheme.id == theme_id,
        models.DBBrandingTheme.client_id == client.id).first()
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")
    db.query(models.DBBrandingTheme).filter(
        models.DBBrandingTheme.client_id == client.id
    ).update({models.DBBrandingTheme.is_default: False})
    theme.is_default = True
    db.commit()
    return theme_to_dict(theme)


@router.delete("/api/branding-themes/{theme_id}")
def delete_branding_theme(theme_id: int, request: Request,
                          db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    theme = db.query(models.DBBrandingTheme).filter(
        models.DBBrandingTheme.id == theme_id,
        models.DBBrandingTheme.client_id == client.id).first()
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    remaining = db.query(models.DBBrandingTheme).filter(
        models.DBBrandingTheme.client_id == client.id).count()
    if remaining <= 1:
        raise HTTPException(status_code=400,
                            detail="This is your only theme, so it cannot be deleted")

    was_default = bool(theme.is_default)
    db.delete(theme)
    db.commit()
    if was_default:
        # Never leave an account with no default; the renderer relies on one.
        fallback = db.query(models.DBBrandingTheme).filter(
            models.DBBrandingTheme.client_id == client.id
        ).order_by(models.DBBrandingTheme.id.asc()).first()
        if fallback:
            fallback.is_default = True
            db.commit()
    return {"ok": True}


@router.get("/api/storage")
def storage_report(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    kinds = {}
    for kind, n, size in db.query(models.DBFile.kind, sqlfunc.count(models.DBFile.id),
                                  sqlfunc.coalesce(sqlfunc.sum(models.DBFile.size), 0)).filter(
            models.DBFile.client_id == client.id, models.DBFile.blob_of.is_(None)).group_by(models.DBFile.kind).all():
        kinds[kind or "document"] = {"count": n, "bytes": int(size or 0)}
    orphans = storage_orphan_files(db, client.id)
    alerts = storage_old_alerts(db, client.id)
    return {
        "files": {"count": sum(v["count"] for v in kinds.values()), "bytes": sum(v["bytes"] for v in kinds.values()), "by_kind": kinds},
        "clean": [
            {"key": "orphan_files", "label": "Files whose record was deleted",
             "detail": "Photos, drawings and documents kept against a work order, diary day or other record that no longer exists.",
             "count": len(orphans), "bytes": sum(s for _, s in orphans)},
            {"key": "old_alerts", "label": "Old alerts on the bell",
             "detail": "Alerts older than %d days." % OLD_ALERT_DAYS, "count": len(alerts), "bytes": 0},
        ],
    }


@router.post("/api/storage/clean")
def storage_clean(body: dict, request: Request, db: Session = Depends(get_db)):
    """Clear what the owner chose from the storage report. Irreversible, so only what the report listed."""
    client = get_client_user(request, db)
    require_owner(request, db)
    keys = set(body.get("keys") or [])
    freed, removed = 0, {}
    if "orphan_files" in keys:
        gone = storage_orphan_files(db, client.id)
        ids = [i for i, _ in gone]
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            sweep_referrers(db, {"project_files": chunk})
            db.query(models.DBFile).filter(models.DBFile.id.in_(chunk)).delete(synchronize_session=False)
        freed += sum(s for _, s in gone)
        removed["orphan_files"] = len(ids)
    if "old_alerts" in keys:
        ids = storage_old_alerts(db, client.id)
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            sweep_referrers(db, {"office_alerts": chunk})
            db.query(models.DBAlert).filter(models.DBAlert.id.in_(chunk)).delete(synchronize_session=False)
        removed["old_alerts"] = len(ids)
    if removed:
        log_audit(db, client.id, "storage_cleaned", "company", client.id, "", ", ".join("%s %d" % kv for kv in removed.items()), request)
    db.commit()
    return {"ok": True, "removed": removed, "freed_bytes": freed,
            "message": "Cleared %s." % (", ".join("%d %s" % (n, k.replace("_", " ")) for k, n in removed.items()) or "nothing")}


@router.get("/api/alerts")
def list_notifications(request: Request, limit: int = 30, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    me = viewer_key(request)
    rows = db.query(models.DBAlert).filter(models.DBAlert.client_id == client.id).order_by(
        models.DBAlert.id.desc()).limit(min(max(limit, 1), 200)).all()
    seen = {r.alert_id for r in db.query(models.DBAlertRead.alert_id).filter(
        models.DBAlertRead.viewer == me,
        models.DBAlertRead.alert_id.in_([n.id for n in rows] or [0])).all()}
    unread = db.query(sqlfunc.count(models.DBAlert.id)).filter(
        models.DBAlert.client_id == client.id,
        ~models.DBAlert.id.in_(db.query(models.DBAlertRead.alert_id).filter(
            models.DBAlertRead.viewer == me))).scalar() or 0
    return {"alerts": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body or "",
                               "view": n.view or "", "ref_type": n.ref_type or "", "ref_id": n.ref_id,
                               "severity": n.severity or "info", "created_at": n.created_at,
                               "sent_to": n.sent_to or "", "read": n.id in seen} for n in rows],
            "unread": unread}


@router.post("/api/alerts/read")
def mark_notifications_read(body: NotificationReadIn, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    me = viewer_key(request)
    q = db.query(models.DBAlert.id).filter(models.DBAlert.client_id == client.id)
    if not body.all:
        q = q.filter(models.DBAlert.id.in_(body.ids or [0]))
    already = {r.alert_id for r in db.query(models.DBAlertRead.alert_id).filter(
        models.DBAlertRead.viewer == me).all()}
    n = 0
    for (nid,) in q.all():
        if nid not in already:
            db.add(models.DBAlertRead(alert_id=nid, viewer=me))
            n += 1
    db.commit()
    return {"marked": n}


@router.get("/api/alerts/settings")
def get_notification_settings(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    cfg = notify_settings(db, client.id)
    return {"emails": cfg["emails"], "whatsapp": cfg["whatsapp"], "channels": cfg["channels"],
            "kinds": NOTIFY_KINDS, "whatsapp_ready": cfg["whatsapp_ready"],
            "wa_phone_id": cfg["wa_phone_id"], "wa_token_set": bool(cfg["wa_token"]),
            "email_ready": bool(get_stored_refresh_token(db, client_id=client.id))}


@router.put("/api/alerts/settings")
def save_notification_settings(body: NotificationSettingsIn, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if body.emails is not None:
        bad = [e for e in body.emails if e.strip() and not validate_email_address(e.strip())]
        if bad:
            raise HTTPException(400, "Not an email address: %s" % bad[0])
        _put_setting(db, client.id, "notify_emails", ", ".join(e.strip() for e in body.emails if e.strip()))
    if body.whatsapp is not None:
        nums = [re.sub(r"\D", "", x) for x in body.whatsapp if x.strip()]
        bad = [x for x in nums if not (10 <= len(x) <= 15)]
        if bad:
            raise HTTPException(400, "A WhatsApp number with its country code, e.g. 919848012345: %s" % bad[0])
        nums = ["91" + x if len(x) == 10 else x for x in nums]
        _put_setting(db, client.id, "notify_whatsapp", ", ".join(nums))
    if body.channels is not None:
        clean = {k: [c for c in (v or []) if c in ("email", "whatsapp")]
                 for k, v in body.channels.items() if k in NOTIFY_KINDS}
        _put_setting(db, client.id, "notify_channels", json.dumps(clean))
    if body.wa_phone_id is not None:
        _put_setting(db, client.id, "WHATSAPP_PHONE_NUMBER_ID", body.wa_phone_id.strip())
    if body.wa_token:
        _put_setting(db, client.id, "WHATSAPP_ACCESS_TOKEN", body.wa_token.strip())
    db.commit()
    return get_notification_settings(request, db)


@router.post("/api/alerts/test")
def test_notification(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    cfg = notify_settings(db, client.id)
    saved = cfg["channels"]
    _put_setting(db, client.id, "notify_channels", json.dumps(dict(saved, daily_digest=["email", "whatsapp"])))
    db.commit()
    n = notify(db, client.id, "daily_digest", "Test from Y ERP",
               "If this arrived, notifications reach you here.", view="dashboard-view")
    _put_setting(db, client.id, "notify_channels", json.dumps(saved))
    db.commit()
    return {"sent_to": (n.sent_to if n else "") or "",
            "message": ("Sent to " + n.sent_to) if n and n.sent_to else
                       "Shown on the bell. Add an email or a WhatsApp number to have it sent too."}


@router.get("/api/backup/info")
def backup_info(request: Request, db: Session = Depends(get_db)):
    client = backup_owner(request, db)
    tables = backup_tables(db, client.id)
    from sqlalchemy import func
    size = db.query(func.coalesce(func.sum(models.DBFile.size), 0)).filter(
        models.DBFile.client_id == client.id).scalar() or 0
    last = db.query(models.DBAuditLog).filter(models.DBAuditLog.client_id == client.id,
                                              models.DBAuditLog.action == "backup_downloaded").order_by(
        models.DBAuditLog.id.desc()).first()
    return {"tables": len([t for t, rows in tables.items() if rows]),
            "rows": sum(len(r) for r in tables.values()),
            "files": len(tables.get("project_files", [])), "files_bytes": int(size),
            "last_backup": (getattr(last, "created_at", "") or getattr(last, "timestamp", "") or "") if last else "",
            "last_backup_details": last.details if last else ""}


@router.get("/api/backup")
def download_backup(request: Request, files: int = 0, db: Session = Depends(get_db)):
    client = backup_owner(request, db)
    if rate_limiter.is_rate_limited("backup:%d" % client.id, max_requests=6, window=3600):
        raise HTTPException(429, "Six backups in an hour is plenty. Try again later.")
    import csv as _csv
    import tempfile
    import zipfile
    tables = backup_tables(db, client.id)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    spool = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    counts, file_count = {}, 0
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as z:
        for name, rows in sorted(tables.items()):
            clean = [_backup_clean(name, r) for r in rows]
            counts[name] = len(clean)
            if name == "project_files":
                for r in clean:
                    r["file"] = ("files/%d-%s" % (r["id"], re.sub(r"[^\w.\-]+", "_", r.get("name") or "file"))
                                 if files else None)
            z.writestr("data/%s.json" % name, json.dumps(clean, ensure_ascii=False, indent=1, default=str))
            if clean:
                buf = io.StringIO()
                w = _csv.DictWriter(buf, fieldnames=list(clean[0].keys()), extrasaction="ignore")
                w.writeheader()
                for r in clean:
                    w.writerow({k: ("" if v is None else v) for k, v in r.items()})
                z.writestr("sheets/%s.csv" % name, buf.getvalue().encode("utf-8-sig"))
        if files:
            for f in db.query(models.DBFile.id, models.DBFile.name).filter(
                    models.DBFile.client_id == client.id).order_by(models.DBFile.id).all():
                blob = db.query(models.DBFile.data).filter(models.DBFile.id == f.id).scalar()
                if not blob:
                    row = db.query(models.DBFile).filter(models.DBFile.id == f.id).first()
                    blob = file_bytes(db, row) if row else None
                if blob:
                    z.writestr("files/%d-%s" % (f.id, re.sub(r"[^\w.\-]+", "_", f.name or "file")), bytes(blob))
                    file_count += 1
        z.writestr("manifest.json", json.dumps({
            "company": client.company_name or "", "gstin": client.gstin or "",
            "exported_at": stamp, "tables": counts, "rows": sum(counts.values()),
            "files_included": bool(files), "files": file_count,
            "left_out": "passwords, sign-in tokens and API keys",
            "app_version": os.getenv("RAILWAY_GIT_COMMIT_SHA", "")[:12]}, indent=1))
        z.writestr("README.txt", (
            "Y ERP backup of %s, taken %s.\n\n"
            "data/    every table the company owns, as JSON - one file per table.\n"
            "sheets/  the same tables as CSV, to open in Excel.\n"
            "files/   photos, drawings and documents%s.\n\n"
            "Rows point at each other by id: a ra_bill_lines row's ra_bill_id is the id of a row in\n"
            "ra_bills.json. Passwords, sign-in tokens and API keys are not in this file.\n"
            "Keep it somewhere the office computer is not.\n"
            % (client.company_name or "the company", stamp,
               "" if files else " - not in this backup; take one with files to include them")))
    size = spool.tell()
    spool.seek(0)
    log_audit(db, client.id, "backup_downloaded", "company", client.id, client.company_name or "",
              "%d rows, %s, %d KB" % (sum(counts.values()), "with %d files" % file_count if files else "data only",
                                      size // 1024), request)
    db.commit()

    def chunks():
        try:
            while True:
                part = spool.read(1024 * 256)
                if not part:
                    break
                yield part
        finally:
            spool.close()

    name = "yerp-backup-%s-%s.zip" % (re.sub(r"[^A-Za-z0-9]+", "-", client.company_name or "company").strip("-").lower(),
                                      date.today().isoformat())
    return StreamingResponse(chunks(), media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % name,
                                      "Content-Length": str(size)})


@router.get("/api/company/identity")
def company_identity_api(request: Request, db: Session = Depends(get_db)):
    """The company as its documents show it. Anyone signed in may read it - it is on every page they print."""
    client = get_client_user(request, db) if request.session.get("client_id") else None
    if client is None:
        emp = get_employee_user(request, db)
        client = db.query(models.DBClient).filter(models.DBClient.id == emp.client_id).first()
    return company_identity(db, client)
