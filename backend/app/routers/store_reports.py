"""Store module - reports routes under /api/store/reports. Owned by P5.

Reports (every one filterable by project, store, item, category and dates, as JSON, Excel or PDF), consumption norms,
material reconciliation, the dashboard, and the read-only hooks the rest of the ERP calls. store.reports.view to read;
store.reports.create to keep the norms and record recoveries. A person sees the stores they work in.
"""
import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.core.auth import require_erp_read
from app.core.store_auth import store_actor
from app.db import get_db
from app.documents.store import report_forms
from app.models.store_reports import DBStoreConsumptionNorm
from app.routers.store_masters import accessible_store_ids
from app.services import store_integration as integ
from app.services import store_reports as rep

router = APIRouter(prefix="/api/store/reports", tags=["store-reports"])

VIEW, CREATE = "store.reports.view", "store.reports.create"
D = Decimal


def _filters(db, actor, project_id=0, store_id=0, item_id=0, category="", date_from=None, date_to=None) -> rep.Filters:
    mine = accessible_store_ids(db, actor)
    if store_id and mine is not None and store_id not in mine:
        raise HTTPException(403, "You are not assigned to that store.")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "The period ends before it starts.")
    return rep.Filters(client_id=actor.client.id, store_ids=mine, project_id=project_id, store_id=store_id, item_id=item_id,
                       category=category or "", date_from=date_from, date_to=date_to)


def _send(db, actor, out, fmt):
    """A report as JSON, an Excel workbook or a PDF."""
    if fmt == "json":
        return out
    name = out["code"]
    if fmt == "xlsx":
        from app.core.sheets import sheet_response
        cols = out["columns"]
        rows = [tuple(r.get(c["key"], "") for c in cols) for r in out["rows"]]
        pre = [(out["title"].upper(), actor.client.company_name or ""), ("As at", date.today().isoformat())]
        pre += [(k.replace("_", " ").capitalize(), str(v)) for k, v in (out.get("filters") or {}).items() if v]
        closing = [()] + [(k.replace("_", " ").capitalize(), v) for k, v in out["totals"].items()] + [("Note", n) for n in out["notes"]]
        return sheet_response(tuple(c["label"] for c in cols), rows, "%s.xlsx" % name, preamble=pre + [()], closing=closing)
    if fmt == "pdf":
        from app.documents.forms import form_pdf_response
        return form_pdf_response(report_forms.report_spec(db, actor.client, out), name)
    raise HTTPException(400, "Format is json, xlsx or pdf.")


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door: stock value by store, for the stores this person works in."""
    actor = store_actor(request, db, VIEW)
    return {"slice": "reports", "items": rep.dashboard(db, actor.client.id, accessible_store_ids(db, actor))["by_store"]}


@router.get("/catalogue")
def catalogue(request: Request, db: Session = Depends(get_db)):
    store_actor(request, db, VIEW)
    return {"reports": [{"code": c, "title": t} for c, (t, _fn) in rep.REPORTS.items()],
            "consumption_groups": list(rep.GROUPS), "ageing_days": [90, 180, 365]}


@router.get("/run/{code}")
def run(code: str, request: Request, project_id: int = 0, store_id: int = 0, item_id: int = 0, category: str = "",
        date_from: Optional[date] = None, date_to: Optional[date] = None, group: str = "work_order", days: int = 90,
        subcontractor_id: int = 0, format: str = "json", db: Session = Depends(get_db)):
    """One report, filtered: stock-register, valuation (as on date_to), item-ledger, grn-register, issue-register,
    consumption (group=work_order|boq_item|cost_head|subcontractor), ageing (days=90|180|365), subcontractor-account,
    transfers, count-scrap. format=json|xlsx|pdf."""
    actor = store_actor(request, db, VIEW)
    if code not in rep.REPORTS:
        raise HTTPException(404, "No such report")
    f = _filters(db, actor, project_id, store_id, item_id, category, date_from, date_to)
    fn = rep.REPORTS[code][1]
    if code == "consumption":
        out = fn(db, f, group)
    elif code == "ageing":
        if days not in (90, 180, 365):
            raise HTTPException(400, "Non-moving is 90, 180 or 365 days.")
        out = fn(db, f, days)
    elif code == "subcontractor-account":
        out = fn(db, f, subcontractor_id)
    else:
        out = fn(db, f)
    return _send(db, actor, out, format)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    return rep.dashboard(db, actor.client.id, accessible_store_ids(db, actor))


# --- consumption norms ---------------------------------------------------------------------------------------------

class NormIn(BaseModel):
    work_item_code: str
    boq_item_id: Optional[int] = None
    description: str = ""
    work_uom: str = ""
    item_id: int
    coefficient: str
    wastage_pct: str = "0"
    penal_rate: Optional[str] = None
    is_active: bool = True


def _dec(x, what, blank_ok=False):
    s = str(x if x is not None else "").strip().replace(",", "")
    if not s:
        if blank_ok:
            return None
        raise HTTPException(400, "%s is missing." % what)
    try:
        v = D(s)
    except InvalidOperation:
        raise HTTPException(400, "%s is not a number: %r" % (what, x)) from None
    if not v.is_finite() or v < 0:
        raise HTTPException(400, "%s must be a number not below nought." % what)
    return v


def _norm_dict(db, n):
    item = db.get(models.DBItem, n.item_id)
    names = rep.Names(db, n.client_id)
    return {"id": n.id, "work_item_code": n.work_item_code, "boq_item_id": n.boq_item_id, "boq_item": names.boq(n.boq_item_id),
            "description": n.description or "", "work_uom": n.work_uom or "", "item_id": n.item_id,
            "item_code": item.item_code if item else "", "item_name": item.item_name if item else "", "base_uom": names.item(n.item_id)["base_uom"],
            "coefficient": rep.s(n.coefficient), "wastage_pct": rep.s(n.wastage_pct), "penal_rate": rep.s(n.penal_rate) if n.penal_rate is not None else None,
            "is_active": bool(n.is_active)}


def _apply_norm(db, actor, n, body: NormIn):
    code = body.work_item_code.strip()
    if not code:
        raise HTTPException(400, "Give the work-item code (the BOQ item code).")
    item = db.get(models.DBItem, body.item_id)
    if item is None or item.client_id != actor.client.id or item.kind != "RM":
        raise HTTPException(400, "That is not a stock item of this company.")
    if body.boq_item_id:
        boq = db.get(models.DBBoqLine, body.boq_item_id)
        owner = db.query(models.DBBoq.client_id).filter(models.DBBoq.id == boq.boq_id).scalar() if boq else None
        if owner != actor.client.id:
            raise HTTPException(400, "That BOQ item does not exist.")
    coef = _dec(body.coefficient, "Coefficient")
    if coef <= 0:
        raise HTTPException(400, "The coefficient must be more than nought.")
    wastage = _dec(body.wastage_pct, "Wastage %")
    if wastage > 100:
        raise HTTPException(400, "Wastage is a percentage up to 100.")
    clash = db.query(DBStoreConsumptionNorm.id).filter(
        DBStoreConsumptionNorm.client_id == actor.client.id, DBStoreConsumptionNorm.work_item_code == code,
        DBStoreConsumptionNorm.item_id == item.id, DBStoreConsumptionNorm.is_active.is_(True),
        (DBStoreConsumptionNorm.boq_item_id == body.boq_item_id) if body.boq_item_id else DBStoreConsumptionNorm.boq_item_id.is_(None))
    if n.id:
        clash = clash.filter(DBStoreConsumptionNorm.id != n.id)
    if body.is_active and clash.first():
        raise HTTPException(409, "There is already a norm for %s and %s." % (code, item.item_code))
    n.work_item_code, n.boq_item_id, n.item_id = code, body.boq_item_id or None, item.id
    n.description, n.work_uom = body.description.strip(), body.work_uom.strip()
    n.coefficient, n.wastage_pct = rep.q(coef, rep._FACTOR), rep.q(wastage, rep._PCT)
    pr = _dec(body.penal_rate, "Penal rate", blank_ok=True)
    n.penal_rate = rep.q(pr, rep._RATE) if pr is not None else None
    n.is_active = body.is_active


@router.get("/norms")
def list_norms(request: Request, q: str = "", include_inactive: bool = False, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    query = db.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.client_id == actor.client.id)
    if not include_inactive:
        query = query.filter(DBStoreConsumptionNorm.is_active.is_(True))
    if q.strip():
        query = query.filter(func.upper(DBStoreConsumptionNorm.work_item_code).contains(q.strip().upper()))
    return {"norms": [_norm_dict(db, n) for n in query.order_by(DBStoreConsumptionNorm.work_item_code, DBStoreConsumptionNorm.id).all()]}


@router.post("/norms")
def create_norm(body: NormIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    n = DBStoreConsumptionNorm(client_id=actor.client.id)
    _apply_norm(db, actor, n, body)
    db.add(n)
    db.commit()
    return _norm_dict(db, n)


@router.put("/norms/{norm_id:int}")
def update_norm(norm_id: int, body: NormIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    n = db.get(DBStoreConsumptionNorm, norm_id)
    if n is None or n.client_id != actor.client.id:
        raise HTTPException(404, "Norm not found")
    _apply_norm(db, actor, n, body)
    db.commit()
    return _norm_dict(db, n)


@router.delete("/norms/{norm_id:int}")
def retire_norm(norm_id: int, request: Request, db: Session = Depends(get_db)):
    """A norm is retired, not erased: reconciliations already shown were worked out with it."""
    actor = store_actor(request, db, CREATE)
    n = db.get(DBStoreConsumptionNorm, norm_id)
    if n is None or n.client_id != actor.client.id:
        raise HTTPException(404, "Norm not found")
    n.is_active = False
    db.commit()
    return _norm_dict(db, n)


@router.get("/norms/template.csv")
def norms_template(request: Request, db: Session = Depends(get_db)):
    store_actor(request, db, VIEW)
    body = ("work_item_code,item_code,coefficient,wastage_pct,penal_rate,work_uom,description\n"
            "RCC-M25,CEM-OPC53,425,2,9.50,cum,RCC M25: kg of cement a cum\n"
            "REINF-FE500,TMT-12,1050,3,70,MT,Reinforcement: kg of steel a MT\n")
    return Response(body, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="consumption-norms.csv"'})


@router.post("/norms/import")
async def import_norms(request: Request, file: UploadFile = File(...), apply: bool = False, db: Session = Depends(get_db)):
    """A sheet of norms, checked row by row. With apply=true the good rows are saved (an existing norm for the same
    code and item is updated); without it nothing is saved."""
    actor = store_actor(request, db, CREATE)
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    fields = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
    missing = {"work_item_code", "item_code", "coefficient"} - fields
    if missing:
        raise HTTPException(400, "The sheet needs the columns work_item_code, item_code and coefficient. Missing: %s." % ", ".join(sorted(missing)))
    rows, good = [], 0
    for n, raw_row in enumerate(reader, 1):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
        if not any(r.values()):
            continue
        out = {"row": n, "work_item_code": r.get("work_item_code", ""), "item_code": r.get("item_code", ""), "coefficient": r.get("coefficient", ""),
               "wastage_pct": r.get("wastage_pct", "") or "0", "penal_rate": r.get("penal_rate", ""), "errors": [], "action": ""}
        item = db.query(models.DBItem).filter(models.DBItem.client_id == actor.client.id,
                                              func.upper(models.DBItem.item_code) == out["item_code"].upper()).first()
        if item is None or item.kind != "RM":
            out["errors"].append("No stock item %s." % (out["item_code"] or "given"))
        body = NormIn(work_item_code=out["work_item_code"], item_id=item.id if item else 0, coefficient=out["coefficient"],
                      wastage_pct=out["wastage_pct"], penal_rate=out["penal_rate"] or None, work_uom=r.get("work_uom", ""),
                      description=r.get("description", ""))
        existing = None
        if item:
            existing = db.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.client_id == actor.client.id,
                                                               DBStoreConsumptionNorm.work_item_code == body.work_item_code.strip(),
                                                               DBStoreConsumptionNorm.item_id == item.id, DBStoreConsumptionNorm.boq_item_id.is_(None),
                                                               DBStoreConsumptionNorm.is_active.is_(True)).first()
            try:
                with db.begin_nested():
                    target = existing or DBStoreConsumptionNorm(client_id=actor.client.id)
                    _apply_norm(db, actor, target, body)
                    if not existing:
                        db.add(target)
                    db.flush()
                    if not apply:
                        raise _DryRun()
            except _DryRun:
                pass
            except HTTPException as exc:
                out["errors"].append(exc.detail)
        if not out["errors"]:
            good += 1
            out["action"] = "update" if existing else "add"
        rows.append(out)
    if apply:
        db.commit()
    else:
        db.rollback()
    return {"applied": apply, "rows": rows, "summary": {"rows": len(rows), "ok": good, "errors": len(rows) - good}}


class _DryRun(Exception):
    pass


@router.get("/norms/requirement")
def requirement(request: Request, boq_item_id: int, item_id: int, db: Session = Depends(get_db)):
    """get_theoretical_requirement over HTTP."""
    store_actor(request, db, VIEW)
    got = rep.get_theoretical_requirement(db, boq_item_id, item_id)
    return {"boq_item_id": boq_item_id, "item_id": item_id, "theoretical": rep.s(got) if got is not None else None}


@router.get("/work-items")
def work_items(request: Request, project_id: int = 0, db: Session = Depends(get_db)):
    """The work-item codes norms can be written against: the BOQ items with an item code."""
    actor = store_actor(request, db, VIEW)
    query = (db.query(models.DBBoqLine).join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id)
             .filter(models.DBBoq.client_id == actor.client.id, models.DBBoqLine.item_code != "", models.DBBoqLine.kind == "item"))
    if project_id:
        query = query.filter(models.DBBoq.job_id == project_id)
    return {"items": [{"boq_item_id": b.id, "code": b.item_code, "description": (b.description or "").split("\n")[0][:120], "uom": b.uom or "",
                       "quantity": b.quantity or 0} for b in query.order_by(models.DBBoqLine.id).limit(500).all()]}


# --- reconciliation ------------------------------------------------------------------------------------------------

@router.get("/reconciliation")
def material_reconciliation(request: Request, scope: str, scope_id: int, upto: Optional[date] = None, project_id: int = 0,
                            category: str = "", item_id: int = 0, format: str = "json", db: Session = Depends(get_db)):
    """Theoretical against actual per material for a project, a client work order or a subcontractor."""
    actor = store_actor(request, db, VIEW)
    if scope not in ("project", "work_order", "subcontractor"):
        raise HTTPException(400, "Scope is project, work_order or subcontractor.")
    _check_scope(db, actor, scope, scope_id)
    out = rep.reconciliation(db, actor.client.id, scope, scope_id, upto, project_id or None, {item_id} if item_id else None, category)
    return _send(db, actor, out, format)


def _check_scope(db, actor, scope, scope_id):
    model = {"project": models.DBJob, "work_order": models.DBWorkOrder, "subcontractor": models.DBContractor}[scope]
    row = db.get(model, scope_id)
    if row is None or row.client_id != actor.client.id:
        raise HTTPException(404, "%s not found" % scope.replace("_", " ").capitalize())


@router.get("/client-supply")
def client_supply(request: Request, project_id: int = 0, work_order_id: int = 0, upto: Optional[date] = None, format: str = "json",
                  db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    if project_id:
        _check_scope(db, actor, "project", project_id)
    if work_order_id:
        _check_scope(db, actor, "work_order", work_order_id)
    return _send(db, actor, rep.client_supply_reconciliation(db, actor.client.id, project_id, work_order_id, upto), format)


@router.get("/subcontractors")
def subcontractors(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    return {"subcontractors": [{"id": c.id, "name": c.company_name or ""} for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == actor.client.id).order_by(models.DBContractor.company_name).all()]}


# --- the hooks other modules call ----------------------------------------------------------------------------------

@router.get("/integration/status")
def integration_status(request: Request, db: Session = Depends(get_db)):
    """For the old stock and goods-receipt screens: is the Store module in use, and should they hand over to it?"""
    client = require_erp_read(request, db)
    return integ.legacy_status(db, client.id)


@router.get("/integration/po/{po_id:int}")
def po_receipts(po_id: int, request: Request, db: Session = Depends(get_db)):
    """Received and pending per line of a purchase order, for the PO screen."""
    client = require_erp_read(request, db)
    return integ.po_receipts(db, client.id, po_id)


def _bill(db, client_id, bill_id):
    bill = db.get(models.DBSubBill, bill_id)
    if bill is None or bill.client_id != client_id:
        raise HTTPException(404, "Bill not found")
    return bill


@router.get("/integration/sub-bills/{bill_id:int}/recovery")
def subbill_recovery(bill_id: int, request: Request, db: Session = Depends(get_db)):
    """Material recovery due on a subcontractor bill: read-only, for the bill screen's panel."""
    client = require_erp_read(request, db)
    return integ.subbill_recovery_due(db, client.id, _bill(db, client.id, bill_id))


class RecoveryIn(BaseModel):
    kind: str
    amount: str
    note: str = ""


@router.post("/integration/sub-bills/{bill_id:int}/recovery")
def record_subbill_recovery(bill_id: int, body: RecoveryIn, request: Request, db: Session = Depends(get_db)):
    """Note a recovery decided against the bill. The bill itself is not changed."""
    actor = store_actor(request, db, CREATE)
    bill = _bill(db, actor.client.id, bill_id)
    try:
        integ.record_recovery(db, actor.client.id, bill, body.kind, _dec(body.amount, "Amount"), body.note, actor)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return integ.subbill_recovery_due(db, actor.client.id, bill)


@router.get("/integration/client-billing")
def client_billing(request: Request, project_id: int = 0, work_order_id: int = 0, db: Session = Depends(get_db)):
    """Read-only data for client RA bills: client-supplied material to recover, and material at site."""
    client = require_erp_read(request, db)
    if not project_id and not work_order_id:
        raise HTTPException(400, "Give a project or a work order.")
    return integ.client_billing_data(db, client.id, project_id, work_order_id)


@router.get("/integration/project-cost/{project_id:int}")
def project_cost(project_id: int, request: Request, date_from: Optional[date] = None, date_to: Optional[date] = None,
                 db: Session = Depends(get_db)):
    """get_project_material_cost over HTTP: material charged to a project, by cost head, work order and BOQ item."""
    actor = store_actor(request, db, VIEW)
    _check_scope(db, actor, "project", project_id)
    lines = integ.get_project_material_cost(db, project_id, date_from, date_to)
    names = rep.Names(db, actor.client.id)
    return {"project_id": project_id, "total": rep.s(sum((l.value for l in lines), rep.ZERO), rep._VALUE),
            "lines": [dict(cost_head=l.cost_head, work_order=names.work_order(l.work_order_id), boq_item=names.boq(l.boq_item_id),
                           **names.item(l.item_id), qty=rep.s(l.qty), value=rep.s(l.value)) for l in lines]}
