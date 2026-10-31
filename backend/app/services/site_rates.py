"""Site item pricing: which items a site's BOQ holds, and the rate finalised for each at that site."""
from datetime import datetime

from fastapi import HTTPException

from app import models
from app.constants.boq import BOQ_PRICED
from app.core.currency import money, unit_rate
from app.services.boq import boq_of_job, boq_revision_of
from app.services.item_master import check_rate, default_rate
from app.services.projects import job_or_404, job_or_404_for_employee

PENDING, DRAFT, FINALIZED, CHANGED = "Pending", "Draft", "Finalized", "Changed"


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def site_or_404(db, client_id, emp, job_id):
    """The site, or a 404 for someone with no connection to it (so its existence is not given away)."""
    if emp is None:
        return job_or_404(db, client_id, job_id)
    return job_or_404_for_employee(db, client_id, emp, job_id)


def current_lines_of_item(db, client_id, job_id=None, code=None):
    """Priced, coded lines of current BOQ revisions: of one site, or of one item across every site."""
    query = db.query(models.DBBoqLine).join(models.DBBoqRevision, models.DBBoqRevision.id == models.DBBoqLine.revision_id).join(
        models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id).filter(
        models.DBBoq.client_id == client_id, models.DBBoqRevision.rev_no == models.DBBoq.current_rev,
        models.DBBoqLine.kind.in_(BOQ_PRICED), models.DBBoqLine.item_code != "")
    if job_id:
        query = query.filter(models.DBBoq.job_id == job_id)
    if code:
        query = query.filter(models.DBBoqLine.item_code == code)
    return query.all()


def site_lines(db, client_id, job_id):
    """(boq, revision, every line in order) of the site's current BOQ revision; (None, None, []) when it has no BOQ."""
    boq = boq_of_job(db, client_id, job_id)
    if not boq:
        return None, None, []
    rev = boq_revision_of(db, boq)
    lines = db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).order_by(
        models.DBBoqLine.display_order, models.DBBoqLine.id).all()
    return boq, rev, lines


def rates_of_site(db, client_id, job_id):
    return {r.item_id: r for r in db.query(models.DBSiteItemRate).filter(
        models.DBSiteItemRate.client_id == client_id, models.DBSiteItemRate.job_id == job_id).all()}


def status_of(rate, item):
    if rate is None or rate.site_rate is None:
        return PENDING
    if rate.status == FINALIZED and unit_rate(rate.default_rate_snapshot) != unit_rate(item.selling_rate if item else 0):
        return CHANGED
    return rate.status or DRAFT


def _items_for(db, client_id, lines):
    ids = {l.item_id for l in lines if l.item_id}
    codes = {l.item_code for l in lines if l.item_code}
    by_id, by_code = {}, {}
    if ids or codes:
        for i in db.query(models.DBItem).filter(models.DBItem.client_id == client_id).filter(
                models.DBItem.id.in_(list(ids) or [0]) | models.DBItem.item_code.in_(list(codes) or [""])).all():
            by_id[i.id], by_code[i.item_code] = i, i
    return by_id, by_code


def pricing_rows(db, client_id, job_id):
    """Every priced line of the site's BOQ with its master item (matched on the stable id, then the code) and the site's rate."""
    boq, rev, lines = site_lines(db, client_id, job_id)
    priced = [l for l in lines if l.kind in BOQ_PRICED]
    by_id, by_code = _items_for(db, client_id, priced)
    rates = rates_of_site(db, client_id, job_id)
    from app.services.boq_outline import boq_outline, heading_trail, line_materials
    heads, path, _ = boq_outline(lines)
    grades = line_materials(lines, heads, path)
    rows = []
    for l in lines:
        if l.kind not in BOQ_PRICED:
            continue                                            # headings and notes stay out of pricing
        section = heading_trail(heads, path[l.key][-1]) if path.get(l.key) else ""
        item = by_id.get(l.item_id) or by_code.get(l.item_code)
        rate = rates.get(item.id) if item else None
        site_rate = rate.site_rate if rate is not None else None
        qty = money(l.quantity)
        rows.append({
            "line_key": l.key, "line_id": l.id, "section": section, "description": l.description or "",
            "item_id": item.id if item else None, "item_code": l.item_code or "", "mapped": item is not None,
            "item_name": item.item_name if item else "", "item_active": bool(item and item.is_active is not False),
            "specification": (grades.get(l.key) or (item.specification if item else "")) or "", "uom": l.uom or (item.units_of_measure if item else ""),
            "quantity": qty, "rate_only": bool(l.rate_only), "boq_rate": unit_rate(l.rate),
            "default_rate": default_rate(item) if item else None,
            "site_rate": unit_rate(site_rate) if site_rate is not None else None,
            # A rate-only line has a rate and no quantity: it is in no total until a quantity is put on it.
            "amount": 0.0 if (l.rate_only or site_rate is None) else money(qty * site_rate),
            "status": status_of(rate, item) if item else PENDING, "version": rate.version if rate is not None else 0,
            "effective_date": (rate.effective_date if rate is not None else "") or "",
            "remarks": (rate.remarks if rate is not None else "") or "",
            "finalized_by": (rate.finalized_by_name if rate is not None else "") or "",
            "finalized_at": (rate.finalized_at if rate is not None else "") or "",
            "updated_by": (rate.updated_by_name if rate is not None else "") or "",
            "updated_at": (rate.updated_at if rate is not None else "") or "",
        })
    return boq, rev, rows


def summary_of(rows):
    s = {"lines": len(rows), "mapped": 0, "unmapped": 0, "pending": 0, "draft": 0, "finalized": 0, "changed": 0,
         "rate_only": 0, "amount": 0.0}
    for r in rows:
        s["mapped" if r["mapped"] else "unmapped"] += 1
        s["rate_only"] += 1 if r["rate_only"] else 0
        if r["mapped"]:
            s[r["status"].lower()] += 1
        s["amount"] += r["amount"]
    s["amount"] = money(s["amount"])
    return s


def row_of_item(db, client_id, job_id, item_id):
    """The site's priced lines for one item, or a 404: an item not on the site's BOQ cannot be priced at it."""
    _, _, rows = pricing_rows(db, client_id, job_id)
    mine = [r for r in rows if r["item_id"] == item_id]
    if not mine:
        raise HTTPException(404, "That item is not in this site's BOQ.")
    return mine


def item_of_site(db, client_id, job_id, item_id):
    row_of_item(db, client_id, job_id, item_id)
    return db.query(models.DBItem).filter(models.DBItem.id == item_id, models.DBItem.client_id == client_id).first()


def write_audit(db, client_id, job_id, item, action, prev_rate, prev_status, new_rate, new_status, who, remarks=""):
    db.add(models.DBRateAuditLog(
        client_id=client_id, job_id=job_id, item_id=item.id, item_code=item.item_code, previous_rate=prev_rate,
        new_rate=new_rate, previous_status=prev_status, new_status=new_status, action=action,
        changed_by_name=who, changed_at=now(), remarks=remarks or ""))


def locked_rate(db, client_id, job_id, item_id):
    """The rate row, locked for this transaction on databases that support it, or None if there is none yet."""
    return db.query(models.DBSiteItemRate).filter(
        models.DBSiteItemRate.client_id == client_id, models.DBSiteItemRate.job_id == job_id,
        models.DBSiteItemRate.item_id == item_id).with_for_update().first()


def apply_rate(db, client_id, job_id, item, rate, who, version=None, remarks="", effective_date=""):
    """Save a draft rate. A finalised rate or a stale version is a 409; changing a rate that already has a value needs a reason.

    Does not commit."""
    row = locked_rate(db, client_id, job_id, item.id)
    if row is not None and row.status == FINALIZED:
        raise HTTPException(409, "%s is finalised at this site. Reopen it to change the rate." % item.item_code)
    if row is not None and version is not None and version != row.version:
        raise HTTPException(409, "%s was changed by someone else. Refresh and try again." % item.item_code)
    remarks = (remarks or "").strip()
    if row is None:
        if rate is None:
            return None
        row = models.DBSiteItemRate(client_id=client_id, job_id=job_id, item_id=item.id, item_code=item.item_code, site_rate=rate,
                                    status=DRAFT, version=1, effective_date=effective_date or "", remarks=remarks,
                                    created_by_name=who, updated_by_name=who)
        db.add(row)
        db.flush()
        write_audit(db, client_id, job_id, item, "created", None, PENDING, rate, DRAFT, who, remarks)
        return row
    prev_rate, prev_status = row.site_rate, status_of(row, item)
    if prev_rate == rate:
        return row
    if prev_rate is not None and not remarks:
        raise HTTPException(422, "Give a reason for changing the rate of %s." % item.item_code)
    row.site_rate, row.status, row.version = rate, DRAFT, (row.version or 1) + 1
    row.updated_by_name, row.updated_at = who, now()
    if effective_date:
        row.effective_date = effective_date
    if remarks:
        row.remarks = remarks
    write_audit(db, client_id, job_id, item, "edited", prev_rate, prev_status, rate, status_of(row, item), who, remarks)
    return row


def check_date(value):
    value = (value or "").strip()
    if not value:
        return ""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(422, "The effective date must be a date (YYYY-MM-DD).")
    return value


__all__ = ["check_rate"]
