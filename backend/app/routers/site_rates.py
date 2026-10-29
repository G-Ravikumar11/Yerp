"""Site item pricing: a site's BOQ items matched to the item master, and the rate finalised for each at that site."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.db import get_db, get_read_db

from app.constants.boq import BOQ_PRICED
from app.core.audit import log_audit
from app.core.auth import require_items_access, session_employee, wo_actor
from app.core.currency import money, unit_rate
from app.core.units import canonical_unit
from app.schemas.item_master import MasterItemIn
from app.services import item_master as im
from app.services import site_rates as sr
from app.services.boq import boq_lines_with_subtotals, boq_stamp_item_ids, boq_summary
from app.services.projects import filter_jobs_for_employee

router = APIRouter()

VIEW = ("siteprices.view", "siteprices.edit", "siteprices.finalize", "workorders.manage", "reports.view")
EDIT, FINALIZE = "siteprices.edit", "siteprices.finalize"


class RateIn(BaseModel):
    rate: Optional[float] = None
    remarks: Optional[str] = ""
    effective_date: Optional[str] = ""
    version: Optional[int] = None


class BulkRateIn(RateIn):
    item_id: int


class BulkIn(BaseModel):
    rates: List[BulkRateIn]


class ActionIn(BaseModel):
    remarks: Optional[str] = ""
    version: Optional[int] = None


class MapIn(BaseModel):
    item_id: int


class CreateFromLineIn(BaseModel):
    item_code: Optional[str] = ""
    item_name: Optional[str] = ""
    description: Optional[str] = ""
    units_of_measure: Optional[str] = ""
    item_category: Optional[str] = ""
    item_subcategory: Optional[str] = ""
    item_type: Optional[str] = "Work"
    specification: Optional[str] = ""


def _viewer(request, db, job_id):
    client = require_items_access(request, db, VIEW)
    return client, sr.site_or_404(db, client.id, session_employee(request, db), job_id)


def _writer(request, db, job_id, permission):
    client, _, who = wo_actor(request, db, permission)
    return client, sr.site_or_404(db, client.id, session_employee(request, db), job_id), who


def _site(job):
    return {"id": job.id, "site_code": job.number or "", "site_name": job.name or "", "customer": job.customer_name or ""}


def _boq_info(boq, rev):
    if not boq:
        return None
    return {"id": boq.id, "number": boq.number or "", "title": boq.title or "", "revision": rev.label or "R%d" % rev.rev_no,
            "editable": rev.status == "OPEN"}


def _respond(db, client_id, job_id, message, item_id=None):
    _, _, rows = sr.pricing_rows(db, client_id, job_id)
    out = {"summary": sr.summary_of(rows), "message": message}
    if item_id is not None:
        out["rows"] = [r for r in rows if r["item_id"] == item_id]
    return out


@router.get("/api/sites")
def sites_list(request: Request, db: Session = Depends(get_read_db)):
    """The sites this person may open, each with whether it has a BOQ yet."""
    client = require_items_access(request, db, VIEW)
    query = db.query(models.DBJob).filter(models.DBJob.client_id == client.id)
    query = filter_jobs_for_employee(query, db, client.id, session_employee(request, db))
    has_boq = {b[0]: b[1] for b in db.query(models.DBBoq.job_id, models.DBBoq.id).filter(models.DBBoq.client_id == client.id).all()}
    return {"sites": [{**_site(j), "boq_id": has_boq.get(j.id)} for j in query.order_by(models.DBJob.name).all()]}


@router.get("/api/sites/{job_id}/boq-items")
def site_boq_items(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    """Every priced line of the site's current BOQ revision, matched to the master, with the site's rate."""
    client, job = _viewer(request, db, job_id)
    boq, rev, rows = sr.pricing_rows(db, client.id, job.id)
    return {"site": _site(job), "boq": _boq_info(boq, rev), "rows": rows, "summary": sr.summary_of(rows)}


@router.get("/api/sites/{job_id}/boq-items/unmapped")
def site_boq_unmapped(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    client, job = _viewer(request, db, job_id)
    _, _, rows = sr.pricing_rows(db, client.id, job.id)
    return {"rows": [r for r in rows if not r["mapped"]]}


@router.get("/api/sites/{job_id}/item-prices")
def site_prices(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    client, job = _viewer(request, db, job_id)
    _, _, rows = sr.pricing_rows(db, client.id, job.id)
    return {"site_id": job.id, "rows": [r for r in rows if r["mapped"]], "summary": sr.summary_of(rows)}


def _revision_line(db, client_id, job, key):
    boq, rev, lines = sr.site_lines(db, client_id, job.id)
    if not boq:
        raise HTTPException(404, "This site has no BOQ yet. Open or import one first.")
    line = next((l for l in lines if l.key == key and l.kind in BOQ_PRICED), None)
    if not line:
        raise HTTPException(404, "That BOQ line is not a priced line of this site's BOQ.")
    if rev.status != "OPEN":
        raise HTTPException(409, "%s is issued and cannot be changed. Start a new revision to map its items." % (rev.label or "R%d" % rev.rev_no))
    return boq, rev, lines, line


def _attach(db, client_id, line, item):
    line.item_code, line.item_id = item.item_code, item.id
    line.uom = line.uom or item.units_of_measure or ""
    line.material = line.material or (item.specification or "")[:60]          # the line's own description and grade are kept
    boq_stamp_item_ids(db, client_id, [line])


@router.post("/api/sites/{job_id}/boq-items/{line_key}/map-item")
def site_map_item(job_id: int, line_key: str, body: MapIn, request: Request, db: Session = Depends(get_db)):
    """Tie a BOQ line to an existing master item. The line keeps its own description; only the code and id are set."""
    client, job, _ = _writer(request, db, job_id, ("items.manage", "workorders.manage"))
    boq, rev, lines, line = _revision_line(db, client.id, job, line_key)
    item = db.query(models.DBItem).filter(models.DBItem.id == body.item_id, models.DBItem.client_id == client.id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    if item.is_active is False:
        raise HTTPException(409, "%s is deactivated and cannot be put on new lines." % item.item_code)
    if item.kind != "FG":
        raise HTTPException(422, "%s is a raw material. Only finished-goods codes can go on a BOQ." % item.item_code)
    if line.item_code == item.item_code:
        return {**_respond(db, client.id, job.id, "%s is already on this line." % item.item_code, item.id)}
    if any(l.id != line.id and l.kind in BOQ_PRICED and l.item_code == item.item_code for l in lines):
        raise HTTPException(409, "%s is already on another line of this BOQ. A code is for one line only." % item.item_code)
    _attach(db, client.id, line, item)
    log_audit(db, client.id, "boq_line_mapped", "boq", boq.id, boq.number, "%s -> %s" % (line.key, item.item_code), request)
    db.commit()
    return _respond(db, client.id, job.id, "%s mapped to %s." % (item.item_code, job.name), item.id)


@router.post("/api/sites/{job_id}/boq-items/{line_key}/create-item")
def site_create_item(job_id: int, line_key: str, body: CreateFromLineIn, request: Request, db: Session = Depends(get_db)):
    """Make a new master item from an unmapped BOQ line and tie the line to it, in one step."""
    client, job, who = _writer(request, db, job_id, "items.manage")
    boq, rev, lines, line = _revision_line(db, client.id, job, line_key)
    if line.item_code:
        raise HTTPException(409, "This line already has the code %s. Map it to a different item instead." % line.item_code)
    first = re.sub(r"\s+", " ", (line.description or "").split("\n")[0]).strip()
    data = MasterItemIn(
        item_code=body.item_code, item_name=(body.item_name or first)[:200], description=body.description or (line.description or "").strip(),
        units_of_measure=body.units_of_measure or canonical_unit(line.uom) or "Nos", item_category=body.item_category,
        item_subcategory=body.item_subcategory, item_type=body.item_type or "Work", specification=body.specification or line.material or "")
    try:
        item = im.create_master_item(db, client.id, data, who)
        if any(l.kind in BOQ_PRICED and l.item_code == item.item_code for l in lines):
            raise HTTPException(409, "%s is already on another line of this BOQ. A code is for one line only." % item.item_code)
        _attach(db, client.id, line, item)
        log_audit(db, client.id, "item_created", "item", item.id, item.item_code, "from BOQ line %s" % line.key, request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**_respond(db, client.id, job.id, "%s created and mapped." % item.item_code, item.id), "item": im.item_dict(item)}


@router.put("/api/sites/{job_id}/item-prices/{item_id}")
def site_price_save(job_id: int, item_id: int, body: RateIn, request: Request, db: Session = Depends(get_db)):
    client, job, who = _writer(request, db, job_id, EDIT)
    item = sr.item_of_site(db, client.id, job.id, item_id)
    rate = im.check_rate(body.rate, "Rate")
    date = sr.check_date(body.effective_date)
    try:
        sr.apply_rate(db, client.id, job.id, item, rate, who, body.version, body.remarks, date)
        db.commit()
    except IntegrityError:
        # Two first saves raced: the other one won, and this is now an edit of its row.
        db.rollback()
        sr.apply_rate(db, client.id, job.id, item, rate, who, None, body.remarks, date)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _respond(db, client.id, job.id, "Rate saved for %s." % item.item_code, item.id)


@router.post("/api/sites/{job_id}/item-prices/bulk")
def site_prices_bulk(job_id: int, body: BulkIn, request: Request, db: Session = Depends(get_db)):
    """All or nothing: every row is checked first, and one bad row saves none of them."""
    client, job, who = _writer(request, db, job_id, EDIT)
    if not body.rates:
        raise HTTPException(422, "Nothing to save.")
    if len(body.rates) > 2000:
        raise HTTPException(422, "Save at most 2,000 rates at once.")
    _, _, rows = sr.pricing_rows(db, client.id, job.id)
    onsite = {r["item_id"]: r for r in rows if r["item_id"]}
    existing = sr.rates_of_site(db, client.id, job.id)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.client_id == client.id, models.DBItem.id.in_(list(onsite) or [0])).all()}
    errors, seen, checked = [], set(), []
    for entry in body.rates:
        label = items[entry.item_id].item_code if entry.item_id in items else entry.item_id
        try:
            if entry.item_id in seen:
                raise HTTPException(422, "Item listed twice.")
            seen.add(entry.item_id)
            if entry.item_id not in onsite:
                raise HTTPException(404, "Not in this site's BOQ.")
            rate = im.check_rate(entry.rate, "Rate")
            date = sr.check_date(entry.effective_date)
            cur = existing.get(entry.item_id)
            if cur is not None and cur.status == sr.FINALIZED:
                raise HTTPException(409, "Finalised - reopen it first.")
            if cur is not None and entry.version is not None and entry.version != cur.version:
                raise HTTPException(409, "Changed by someone else.")
            if cur is not None and cur.site_rate is not None and cur.site_rate != rate and not (entry.remarks or "").strip():
                raise HTTPException(422, "A reason is needed to change an existing rate.")
            checked.append((items[entry.item_id], rate, entry, date))
        except HTTPException as exc:
            errors.append({"item_id": entry.item_id, "item_code": label, "message": exc.detail})
    if errors:
        shown = "; ".join("%s: %s" % (e["item_code"], e["message"]) for e in errors[:5])
        raise HTTPException(422, "Nothing was saved. %s%s" % (shown, " ..." if len(errors) > 5 else ""))
    try:
        for item, rate, entry, date in checked:
            sr.apply_rate(db, client.id, job.id, item, rate, who, entry.version, entry.remarks, date)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(409, "The rates could not be saved together - someone else changed them. Nothing was saved; refresh and try again.")
    return _respond(db, client.id, job.id, "%d rate%s saved." % (len(checked), "" if len(checked) == 1 else "s"))


@router.post("/api/sites/{job_id}/item-prices/{item_id}/finalize")
def site_price_finalize(job_id: int, item_id: int, body: ActionIn, request: Request, db: Session = Depends(get_db)):
    client, job, who = _writer(request, db, job_id, FINALIZE)
    item = sr.item_of_site(db, client.id, job.id, item_id)
    row = sr.locked_rate(db, client.id, job.id, item.id)
    if row is None or row.site_rate is None:
        raise HTTPException(422, "Enter a rate for %s before finalising it." % item.item_code)
    if row.status == sr.FINALIZED:
        raise HTTPException(409, "%s is already finalised at this site." % item.item_code)
    if body.version is not None and body.version != row.version:
        raise HTTPException(409, "%s was changed by someone else. Refresh and try again." % item.item_code)
    row.status, row.version = sr.FINALIZED, (row.version or 1) + 1
    row.default_rate_snapshot = unit_rate(item.selling_rate)
    row.finalized_by_name, row.finalized_at = who, sr.now()
    row.updated_by_name, row.updated_at = who, row.finalized_at
    sr.write_audit(db, client.id, job.id, item, "finalized", row.site_rate, sr.DRAFT, row.site_rate, sr.FINALIZED, who, body.remarks)
    db.commit()
    return _respond(db, client.id, job.id, "%s finalised for %s." % (item.item_code, job.name), item.id)


@router.post("/api/sites/{job_id}/item-prices/{item_id}/reopen")
def site_price_reopen(job_id: int, item_id: int, body: ActionIn, request: Request, db: Session = Depends(get_db)):
    """Back to draft so it can be changed. Needs the right to finalise and a reason; who and why are kept."""
    client, job, who = _writer(request, db, job_id, FINALIZE)
    item = sr.item_of_site(db, client.id, job.id, item_id)
    reason = (body.remarks or "").strip()
    if not reason:
        raise HTTPException(422, "Give a reason for reopening the rate.")
    row = sr.locked_rate(db, client.id, job.id, item.id)
    if row is None or row.status != sr.FINALIZED:
        raise HTTPException(409, "%s is not finalised at this site." % item.item_code)
    row.status, row.version = sr.DRAFT, (row.version or 1) + 1
    row.finalized_by_name, row.finalized_at = "", ""
    row.updated_by_name, row.updated_at = who, sr.now()
    sr.write_audit(db, client.id, job.id, item, "reopened", row.site_rate, sr.FINALIZED, row.site_rate, sr.DRAFT, who, reason)
    db.commit()
    return _respond(db, client.id, job.id, "%s reopened for %s." % (item.item_code, job.name), item.id)


@router.post("/api/sites/{job_id}/item-prices/apply-to-boq")
def site_prices_apply(job_id: int, body: ActionIn, request: Request, db: Session = Depends(get_db)):
    """Write the finalised site rates onto the open BOQ revision and recompute its amounts and totals.

    Only an open revision is changed, and only lines whose rate is finalised. An issued revision is never edited in place,
    and work orders already drawn from the BOQ keep the rate they were drawn at."""
    client, job, who = _writer(request, db, job_id, FINALIZE)
    boq, rev, lines = sr.site_lines(db, client.id, job.id)
    if not boq:
        raise HTTPException(404, "This site has no BOQ yet.")
    if rev.status != "OPEN":
        raise HTTPException(409, "%s is issued and cannot be changed. Start a new revision to bring the new rates in." % (rev.label or "R%d" % rev.rev_no))
    rates = {r.item_id: r for r in sr.rates_of_site(db, client.id, job.id).values() if r.status == sr.FINALIZED and r.site_rate is not None}
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.client_id == client.id, models.DBItem.id.in_(list(rates) or [0])).all()}
    applied = 0
    for line in lines:
        rate = rates.get(line.item_id) if line.kind in BOQ_PRICED else None
        if rate is None or unit_rate(line.rate) == unit_rate(rate.site_rate):
            continue
        sr.write_audit(db, client.id, job.id, items[line.item_id], "applied", line.rate, sr.FINALIZED, rate.site_rate, sr.FINALIZED, who,
                       "Applied to %s. %s" % (rev.label or "R%d" % rev.rev_no, body.remarks or ""))
        line.rate = unit_rate(rate.site_rate)
        line.amount = 0.0 if line.rate_only else money((line.quantity or 0) * line.rate)
        applied += 1
    log_audit(db, client.id, "site_rates_applied", "boq", boq.id, boq.number, "%d line(s) on %s" % (applied, job.name), request)
    db.commit()
    _, total = boq_lines_with_subtotals(db, rev)
    return {**_respond(db, client.id, job.id, "%d line%s updated on %s." % (applied, "" if applied == 1 else "s", boq.number)),
            "applied": applied, "boq_total": total, "boq_summary": boq_summary(db, rev)}


@router.get("/api/sites/{job_id}/item-prices/audit")
def site_prices_audit(job_id: int, request: Request, item_id: Optional[int] = None, limit: int = 200, db: Session = Depends(get_read_db)):
    client, job = _viewer(request, db, job_id)
    query = db.query(models.DBRateAuditLog).filter(models.DBRateAuditLog.client_id == client.id, models.DBRateAuditLog.job_id == job.id)
    if item_id:
        query = query.filter(models.DBRateAuditLog.item_id == item_id)
    rows = query.order_by(models.DBRateAuditLog.id.desc()).limit(max(1, min(limit, 1000))).all()
    return {"audit": [{"id": a.id, "item_id": a.item_id, "item_code": a.item_code, "previous_rate": a.previous_rate,
                       "new_rate": a.new_rate, "previous_status": a.previous_status, "new_status": a.new_status,
                       "action": a.action, "changed_by": a.changed_by_name, "changed_at": a.changed_at, "reason": a.remarks}
                      for a in rows]}
