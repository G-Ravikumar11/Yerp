"""Store module - reports under /api/store/reports: stock valuation, stock movement, material consumption, norms against actual use, slow-moving
stock and reorder, each as JSON, Excel and PDF; the material norms that feed the norms report; and saved report filters. Owned by P5.

Rights: store.reports.view runs every report; store.reports.create sets norms and saves filters. A member of staff's reports cover only the
stores they are assigned to (store.admin and the account holder see the whole company). Reports are read-only views of the stock ledger, so they
have no draft, approval or posting of their own.
"""
import io
import json
from datetime import date
from decimal import Decimal
from typing import List, Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.permissions import permissions_for
from app.core.store_auth import store_actor
from app.db import get_db
from app.documents import form_pdf
from app.documents.store import report_forms
from app.models.store_core import DBStore, DBStoreItemSettings, DBStoreUserAssignment
from app.models.store_reports import DBStoreMaterialNorm, DBStoreSavedReport
from app.services import store_integration
from app.services import store_reports as svc
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/reports", tags=["store-reports"])
ZERO = Decimal("0")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REPORTS = ("valuation", "movement", "consumption", "norm-variance", "slow-moving", "reorder")


# --- request bodies ---------------------------------------------------------------------------------------------------

class NormIn(BaseModel):
    boq_item_id: int
    item_id: int
    qty_per_unit: str
    wastage_pct: str = "0"
    notes: str = ""


class SavedIn(BaseModel):
    name: str
    report: str
    params: dict = {}


# --- helpers -----------------------------------------------------------------------------------------------------------

def _visible(db, actor):
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


def _scope(db, actor, store_id):
    """The stores a report covers: the one asked for (which must be the person's own), else every store they may see (None = all)."""
    if store_id:
        store = db.get(DBStore, store_id)
        if store is None or store.client_id != actor.client.id:
            raise HTTPException(404, "Store not found")
        assert_store_access(actor.user, store.id)
        return {store.id}
    return _visible(db, actor)


def _project(db, actor, project_id):
    job = db.query(models.DBJob).filter(models.DBJob.id == project_id, models.DBJob.client_id == actor.client.id).first() if project_id else None
    if project_id and job is None:
        raise HTTPException(404, "Project not found")
    return job


def _may_see_project_cost(db, actor, job) -> bool:
    """A project's material cost is the company's figure: open to whoever holds the company reports (or all bills), the project's own
    manager, and the people who work in that project's stores - not to every storekeeper with a reports right."""
    if actor.employee is None:
        return True
    held = permissions_for(actor.employee)
    if held & {"store.admin", "reports.view", "bills.view_all"}:
        return True
    if job is not None and job.manager_id and job.manager_id == actor.employee.id:
        return True
    mine = _visible(db, actor) or set()
    return job is not None and db.query(DBStore.id).filter(DBStore.id.in_(mine or {0}), DBStore.project_id == job.id).first() is not None


def jsonable(x):
    """Decimals travel as plain strings, dates as ISO text."""
    if isinstance(x, Decimal):
        return format(x, "f")
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    return x


def _positive_decimal(value, what, high=Decimal("100"), allow_zero=True):
    try:
        d = Decimal(str(value if value is not None else "").strip() or "0")
    except Exception:
        raise HTTPException(400, "%s is not a number." % what) from None
    if not d.is_finite() or d < 0 or (d == 0 and not allow_zero) or d > high:
        raise HTTPException(400, "%s must be %s%s." % (what, "more than zero" if not allow_zero else "zero or more", " and at most %s" % high if high < Decimal("1000000") else ""))
    return d


def run_report(db, actor, report, p):
    """Run one report with its filters `p` (a dict of strings). Returns (data, filter text)."""
    if report not in REPORTS:
        raise HTTPException(404, "There is no such report.")
    stores = _scope(db, actor, int(p.get("store_id") or 0))
    where = []
    if p.get("store_id"):
        where.append("store %s" % p["store_id"])
    if report == "valuation":
        as_on = svc.parse_day(p.get("as_on"), "As-on date")
        category = (p.get("category") or "").strip().upper()
        data = svc.valuation(db, actor.client.id, stores, as_on, category, p.get("q") or "", str(p.get("include_zero")).lower() in ("1", "true", "yes"))
        return data, ", ".join(where + (["category %s" % category] if category else []) + (["matching '%s'" % p["q"]] if p.get("q") else []))
    if report == "movement":
        end = svc.parse_day(p.get("to_date"), "To date") or date.today()
        start = svc.parse_day(p.get("from_date"), "From date") or end.replace(day=1)
        return svc.movement(db, actor.client.id, stores, start, end, p.get("q") or ""), ", ".join(where + ["%s to %s" % (start.isoformat(), end.isoformat())])
    if report == "consumption":
        project = int(p.get("project_id") or 0)
        _project(db, actor, project)
        group = (p.get("group_by") or "project").strip()
        start, end = svc.parse_day(p.get("from_date"), "From date"), svc.parse_day(p.get("to_date"), "To date")
        if start and end and end < start:
            raise HTTPException(400, "The last day cannot be before the first.")
        return svc.consumption(db, actor.client.id, stores, project, start, end, group), ", ".join(where + (["project %s" % project] if project else []) + ["by %s" % group])
    if report == "norm-variance":
        project = int(p.get("project_id") or 0)
        if not project:
            raise HTTPException(400, "Choose a project.")
        _project(db, actor, project)
        tol = _positive_decimal(p.get("tolerance_pct") or "0", "Tolerance", Decimal("1000"))
        return svc.norm_variance(db, actor.client.id, stores, project, tol), ", ".join(where + ["project %s" % project, "tolerance %s%%" % tol])
    if report == "slow-moving":
        try:
            days = int(p.get("days") or 90)
        except ValueError:
            raise HTTPException(400, "Days is not a number.") from None
        return svc.slow_moving(db, actor.client.id, stores, days), ", ".join(where + ["idle %d days" % days])
    return svc.reorder(db, actor.client.id, stores), ", ".join(where)


def _params(request: Request):
    return dict(request.query_params)


# --- the front door: saved reports -------------------------------------------------------------------------------------------

def _saved_dict(r):
    try:
        params = json.loads(r.params or "{}")
    except ValueError:
        params = {}
    return {"id": r.id, "name": r.name, "report": r.report, "params": params, "created_by": r.created_by_name or "", "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else ""}


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door: the reports this company has saved."""
    actor = store_actor(request, db, "store.reports.view")
    rows = db.query(DBStoreSavedReport).filter(DBStoreSavedReport.client_id == actor.client.id).order_by(DBStoreSavedReport.name).all()
    return {"slice": "reports", "items": [_saved_dict(r) for r in rows]}


@router.post("/saved")
def save_report(body: SavedIn, request: Request, db: Session = Depends(get_db)):
    """Keep a report and its filters under a name."""
    actor = store_actor(request, db, "store.reports.create")
    name = " ".join((body.name or "").split())
    if not name or len(name) > 80:
        raise HTTPException(400, "Give the saved report a name of up to 80 characters.")
    if body.report not in REPORTS:
        raise HTTPException(400, "Choose one of the reports: %s." % ", ".join(REPORTS))
    clean = {str(k): str(v) for k, v in (body.params or {}).items() if v not in (None, "")}
    if len(json.dumps(clean)) > 2000:
        raise HTTPException(400, "Too many filters to keep.")
    row = db.query(DBStoreSavedReport).filter(DBStoreSavedReport.client_id == actor.client.id, DBStoreSavedReport.name == name).first()
    if row is None:
        row = DBStoreSavedReport(client_id=actor.client.id, name=name, report=body.report, created_by_name=actor.name)
        db.add(row)
    row.report, row.params = body.report, json.dumps(clean)
    db.commit()
    return _saved_dict(row)


@router.delete("/saved/{saved_id}")
def delete_saved(saved_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.create")
    row = db.query(DBStoreSavedReport).filter(DBStoreSavedReport.id == saved_id, DBStoreSavedReport.client_id == actor.client.id).first()
    if row is None:
        raise HTTPException(404, "Saved report not found")
    db.delete(row)
    db.commit()
    return {"message": "Saved report removed"}


# --- norms ---------------------------------------------------------------------------------------------------------------------

def _norm_dict(db, n, line=None, item=None):
    line = line or db.get(models.DBBoqLine, n.boq_item_id)
    item = item or db.get(models.DBItem, n.item_id)
    need = svc.get_theoretical_requirement(db, n.boq_item_id, n.item_id)
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == n.item_id).first()
    return {"id": n.id, "boq_item_id": n.boq_item_id, "boq_item": ("%s %s" % (line.item_no or "", (line.description or "").split("\n")[0][:60])).strip() if line else "", "boq_qty": svc.q3(line.quantity) if line else ZERO,
            "boq_uom": (line.uom or "") if line else "", "item_id": n.item_id, "item_code": item.item_code if item else "", "item_name": item.item_name if item else "",
            "base_uom": ((s.base_uom if s else item.units_of_measure) or "") if item else "", "qty_per_unit": Decimal(str(n.qty_per_unit)), "wastage_pct": Decimal(str(n.wastage_pct or 0)), "notes": n.notes or "",
            "theoretical_qty": need if need is not None else ZERO}


def _norm_check(db, actor, body, norm_id=None):
    line = (db.query(models.DBBoqLine).join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id)
            .filter(models.DBBoqLine.id == body.boq_item_id, models.DBBoq.client_id == actor.client.id).first())
    if line is None or line.kind not in ("item", "sub"):
        raise HTTPException(400, "That is not a priced BOQ item of this company.")
    item = db.get(models.DBItem, body.item_id)
    if item is None or item.client_id != actor.client.id or item.kind != "RM":
        raise HTTPException(400, "That item is not a stock item of this company.")
    qty = _positive_decimal(body.qty_per_unit, "The quantity per unit", Decimal("999999"), allow_zero=False).quantize(Decimal("0.000001"))
    if qty <= 0:
        raise HTTPException(400, "The quantity per unit is too small: at least 0.000001.")
    wastage = _positive_decimal(body.wastage_pct or "0", "The wastage allowance", Decimal("100"))
    dup = db.query(DBStoreMaterialNorm.id).filter(DBStoreMaterialNorm.boq_item_id == line.id, DBStoreMaterialNorm.item_id == item.id)
    if norm_id:
        dup = dup.filter(DBStoreMaterialNorm.id != norm_id)
    if dup.first():
        raise HTTPException(409, "%s already has a norm for %s. Change that one." % ((line.item_no or "This BOQ item"), item.item_name))
    notes = " ".join((body.notes or "").split())
    if len(notes) > 200:
        raise HTTPException(400, "Keep the notes to 200 characters.")
    return line, item, qty, wastage, notes


@router.get("/norms")
def list_norms(request: Request, project_id: int = 0, boq_item_id: int = 0, db: Session = Depends(get_db)):
    """The material norms of a project's BOQ items (or of one BOQ item)."""
    actor = store_actor(request, db, "store.reports.view")
    _project(db, actor, project_id)
    q = db.query(DBStoreMaterialNorm).filter(DBStoreMaterialNorm.client_id == actor.client.id)
    if boq_item_id:
        q = q.filter(DBStoreMaterialNorm.boq_item_id == boq_item_id)
    if project_id:
        q = q.join(models.DBBoqLine, models.DBBoqLine.id == DBStoreMaterialNorm.boq_item_id).join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id).filter(models.DBBoq.job_id == project_id)
    return {"items": jsonable([_norm_dict(db, n) for n in q.order_by(DBStoreMaterialNorm.boq_item_id, DBStoreMaterialNorm.id).limit(1000).all()])}


@router.post("/norms")
def add_norm(body: NormIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.create")
    line, item, qty, wastage, notes = _norm_check(db, actor, body)
    n = DBStoreMaterialNorm(client_id=actor.client.id, boq_item_id=line.id, item_id=item.id, qty_per_unit=qty, wastage_pct=wastage, notes=notes, updated_by_name=actor.name)
    db.add(n)
    db.flush()
    log_audit(db, actor.client.id, "store_norm_added", "boq_item", line.id, item.item_code, "%s per unit, wastage %s%%" % (qty, wastage), request=request,
              user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
    db.commit()
    return jsonable(_norm_dict(db, n, line, item))


@router.put("/norms/{norm_id}")
def edit_norm(norm_id: int, body: NormIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.create")
    n = db.query(DBStoreMaterialNorm).filter(DBStoreMaterialNorm.id == norm_id, DBStoreMaterialNorm.client_id == actor.client.id).first()
    if n is None:
        raise HTTPException(404, "Norm not found")
    line, item, qty, wastage, notes = _norm_check(db, actor, body, norm_id)
    n.boq_item_id, n.item_id, n.qty_per_unit, n.wastage_pct, n.notes, n.updated_by_name = line.id, item.id, qty, wastage, notes, actor.name
    log_audit(db, actor.client.id, "store_norm_edited", "boq_item", line.id, item.item_code, "%s per unit, wastage %s%%" % (qty, wastage), request=request,
              user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
    db.commit()
    return jsonable(_norm_dict(db, n, line, item))


@router.delete("/norms/{norm_id}")
def delete_norm(norm_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.create")
    n = db.query(DBStoreMaterialNorm).filter(DBStoreMaterialNorm.id == norm_id, DBStoreMaterialNorm.client_id == actor.client.id).first()
    if n is None:
        raise HTTPException(404, "Norm not found")
    log_audit(db, actor.client.id, "store_norm_removed", "boq_item", n.boq_item_id, str(n.item_id), "", request=request,
              user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
    db.delete(n)
    db.commit()
    return {"message": "Norm removed"}


@router.get("/pick/boq-items")
def pick_boq_items(project_id: int, request: Request, q: str = "", db: Session = Depends(get_db)):
    """A project's priced BOQ items (current revision), for setting norms against."""
    actor = store_actor(request, db, "store.reports.view")
    _project(db, actor, project_id)
    boq = db.query(models.DBBoq).filter(models.DBBoq.job_id == project_id, models.DBBoq.client_id == actor.client.id).first()
    if boq is None:
        return {"items": []}
    query = (db.query(models.DBBoqLine).join(models.DBBoqRevision, models.DBBoqRevision.id == models.DBBoqLine.revision_id)
             .filter(models.DBBoqLine.boq_id == boq.id, models.DBBoqRevision.rev_no == boq.current_rev, models.DBBoqLine.kind.in_(["item", "sub"])))
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(models.DBBoqLine.description.ilike(like) | models.DBBoqLine.item_no.ilike(like))
    return {"items": [{"id": r.id, "item_no": r.item_no or "", "description": (r.description or "").split("\n")[0][:90], "uom": r.uom or "", "quantity": svc.q3(r.quantity).__str__()}
                      for r in query.order_by(models.DBBoqLine.display_order).limit(300).all()]}


# --- project material cost (the integration read) ------------------------------------------------------------------------------

@router.get("/project-cost/{project_id}")
def project_cost(project_id: int, request: Request, from_date: str = "", to_date: str = "", db: Session = Depends(get_db)):
    """Material the stores issued to a project, by cost head, work order and BOQ item: the same figures the project's costing reads."""
    actor = store_actor(request, db, "store.reports.view")
    job = _project(db, actor, project_id)
    if not _may_see_project_cost(db, actor, job):
        raise HTTPException(403, "A project's material cost is for its manager, its stores and those who see the company's reports.")
    start, end = svc.parse_day(from_date, "From date"), svc.parse_day(to_date, "To date")
    lines = store_integration.get_project_material_cost(db, project_id, start or date(2000, 1, 1), end or date.today())
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}
    wos = {w.id: w for w in db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id.in_([l.work_order_id for l in lines if l.work_order_id] or [0])).all()}
    boqs = {b.id: b for b in db.query(models.DBBoqLine).filter(models.DBBoqLine.id.in_([l.boq_item_id for l in lines if l.boq_item_id] or [0])).all()}
    return jsonable({"project_id": project_id, "total_value": sum((l.value for l in lines), ZERO), "items": [
        {"cost_head": l.cost_head, "work_order_id": l.work_order_id, "work_order": wos[l.work_order_id].number if l.work_order_id in wos else "", "boq_item_id": l.boq_item_id,
         "boq_item": ("%s %s" % (boqs[l.boq_item_id].item_no or "", (boqs[l.boq_item_id].description or "").split("\n")[0][:60])).strip() if l.boq_item_id in boqs else "",
         "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "qty": l.qty, "value": l.value} for l in lines]})


# --- the reports ----------------------------------------------------------------------------------------------------------------

@router.get("/{report}")
def get_report(report: str, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.view")
    data, filters = run_report(db, actor, report, _params(request))
    return jsonable({"report": report, "filters": filters, **data})


@router.get("/{report}/export")
def export_report(report: str, request: Request, db: Session = Depends(get_db)):
    """The report as an Excel workbook: the same rows as the PDF."""
    actor = store_actor(request, db, "store.reports.view")
    data, filters = run_report(db, actor, report, _params(request))
    title, subtitle, columns, rows, totals = report_forms.flatten(report, data)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:30]
    ws.append([title])
    ws.append([subtitle + (" - " + filters if filters else "")])
    ws.append([c["title"] for c in columns])
    for row in rows:
        ws.append([float(v) if isinstance(v, Decimal) else ("" if v is None else v) for v in row])
    for label, value in totals:
        ws.append([label, value])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="store-%s.xlsx"' % report})


@router.get("/{report}/print")
def print_report(report: str, request: Request, db: Session = Depends(get_db)):
    """The report as a printed form (PDF, landscape)."""
    actor = store_actor(request, db, "store.reports.view")
    data, filters = run_report(db, actor, report, _params(request))
    try:
        pdf = form_pdf.build_form_pdf(report_forms.report_pdf_spec(db, actor.client, report, data, filters))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="store-%s.pdf"' % report})
