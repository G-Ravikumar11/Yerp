"""Store module - reports routes under /api/store/reports. Owned by P5.

  GET  /catalog                     the reports and the parameters each takes
  GET  /summary                     the numbers for the reports home
  GET  /run/{code}?format=json|xlsx|pdf&<params>
  GET|PUT /norms, DELETE /norms/{id}, GET /theoretical   consumption norms per BOQ item (create = edit, cancel = remove)
  GET  /integration/project-cost    material charged to a project (what costing reads)
  POST /integration/subcon-recoveries/sync   make subcontract-bill material recoveries from chargeable subcontractor issues (post)
Rights: view; create (norms); post (the sync); cancel (remove a norm). Staff see only the stores they are assigned to.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.store_auth import store_actor, store_errors
from app.db import get_db
from app.documents import form_pdf
from app.documents.store.report_forms import report_form_spec
from app.models.store_core import DBStore
from app.models.store_reports import DBStoreConsumptionNorm
from app.routers.store_masters import accessible_store_ids
from app.services import store_integration
from app.services import store_reports as svc
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/reports", tags=["store-reports"])


class NormIn(BaseModel):
    boq_item_id: int
    item_id: int
    qty_per_unit: str
    wastage_pct: str = "0"


def _stores(db, actor, store_id: int = 0):
    """The stores a report may cover: the one asked for (access checked), else every store the person can reach."""
    if store_id:
        assert_store_access(actor.user, store_id)
        return [db.get(DBStore, store_id)]
    q = db.query(DBStore).filter(DBStore.client_id == actor.client.id)
    mine = accessible_store_ids(actor, db)
    if mine is not None:
        q = q.filter(DBStore.id.in_(mine or [0]))
    return q.order_by(DBStore.code).all()


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door (kept as the skeleton's smoke test expects); the reports are under /catalog and /run/{code}."""
    store_actor(request, db, "store.reports.view")
    return {"slice": "reports", "items": []}


@router.get("/catalog")
def catalog(request: Request, db: Session = Depends(get_db)):
    store_actor(request, db, "store.reports.view")
    return {"reports": svc.catalog()}


@router.get("/summary")
def summary(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.view")
    return svc.summary(db, actor.client.id, _stores(db, actor))


@router.get("/run/{code}")
def run(code: str, request: Request, format: str = "json", db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.view")
    params = {k: v for k, v in request.query_params.items() if k != "format"}
    try:
        store_id = int(params.get("store_id") or 0)
    except ValueError:
        raise HTTPException(400, "store_id must be a number.") from None
    rep = svc.run_report(db, actor.client.id, _stores(db, actor, store_id), code, params)
    if format == "json":
        return rep
    name = re.sub(r"[^A-Za-z0-9]+", "_", rep["title"]).strip("_")
    if format == "xlsx":
        return Response(svc.to_xlsx(rep, actor.client.company_name or ""), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="%s.xlsx"' % name})
    if format == "pdf":
        if not form_pdf.PDF_AVAILABLE:
            raise HTTPException(503, "The PDF library is not installed on this server.")
        return Response(form_pdf.build_form_pdf(report_form_spec(db, actor.client, rep)), media_type="application/pdf",
                        headers={"Content-Disposition": 'inline; filename="%s.pdf"' % name})
    raise HTTPException(400, "format must be json, xlsx or pdf.")


# ------------------------------------------------------------------------------------------------ consumption norms
def _norm_row(db, n):
    item = db.get(models.DBItem, n.item_id)
    line = db.get(models.DBBoqLine, n.boq_item_id)
    return {"id": n.id, "boq_item_id": n.boq_item_id, "boq_label": ("%s %s" % (line.item_no, line.description or "")).strip()[:60] if line else "", "boq_qty": str(line.quantity) if line else "0",
            "boq_uom": line.uom if line else "", "item_id": n.item_id, "item_code": item.item_code, "item_name": item.item_name, "qty_per_unit": str(n.qty_per_unit),
            "wastage_pct": str(n.wastage_pct or 0), "theoretical": str(svc.get_theoretical_requirement(db, n.boq_item_id, n.item_id))}


@router.get("/norms")
def list_norms(request: Request, boq_item_id: int = 0, work_order_id: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.view")
    q = db.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.client_id == actor.client.id)
    if boq_item_id:
        q = q.filter(DBStoreConsumptionNorm.boq_item_id == boq_item_id)
    if work_order_id:
        wo = db.get(models.DBWorkOrder, work_order_id)
        q = q.filter(DBStoreConsumptionNorm.boq_item_id.in_([b.id for b in db.query(models.DBBoqLine.id).filter(models.DBBoqLine.boq_id == (wo.boq_id if wo else 0)).all()] or [0]))
    return {"rows": [_norm_row(db, n) for n in q.order_by(DBStoreConsumptionNorm.id).limit(500).all()]}


@router.put("/norms")
def save_norm(body: NormIn, request: Request, db: Session = Depends(get_db)):
    """Set how much of an item one unit of a BOQ item should take (replaces an earlier norm for the same pair)."""
    actor = store_actor(request, db, "store.reports.create")
    line = db.get(models.DBBoqLine, body.boq_item_id)
    boq = db.get(models.DBBoq, line.boq_id) if line else None
    if line is None or boq is None or boq.client_id != actor.client.id:
        raise HTTPException(404, "BOQ item not found")
    item = db.get(models.DBItem, body.item_id)
    if item is None or item.client_id != actor.client.id:
        raise HTTPException(404, "Item not found")
    try:
        per, waste = Decimal(body.qty_per_unit), Decimal(body.wastage_pct or "0")
    except InvalidOperation:
        raise HTTPException(400, "The norm and the wastage must be numbers.") from None
    if per <= 0 or waste < 0 or waste > 100:
        raise HTTPException(400, "The norm must be more than zero and wastage between 0 and 100%.")
    n = db.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.boq_item_id == line.id, DBStoreConsumptionNorm.item_id == item.id).first()
    if n is None:
        n = DBStoreConsumptionNorm(client_id=actor.client.id, boq_item_id=line.id, item_id=item.id)
        db.add(n)
    n.qty_per_unit, n.wastage_pct = per, waste
    db.commit()
    return _norm_row(db, n)


@router.delete("/norms/{norm_id}")
def delete_norm(norm_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.cancel")
    n = db.get(DBStoreConsumptionNorm, norm_id)
    if n is None or n.client_id != actor.client.id:
        raise HTTPException(404, "Norm not found")
    db.delete(n)
    db.commit()
    return {"id": norm_id, "deleted": True}


# ------------------------------------------------------------------------------------------------ integration
@router.get("/integration/project-cost")
def project_cost(request: Request, project_id: int, from_date: str = "", to_date: str = "", db: Session = Depends(get_db)):
    """Material charged to a project, net of returns and reversals - what project costing reads."""
    actor = store_actor(request, db, "store.reports.view")
    if not db.query(models.DBJob.id).filter(models.DBJob.id == project_id, models.DBJob.client_id == actor.client.id).first():
        raise HTTPException(404, "Project not found")
    lines = store_integration.get_project_material_cost(db, project_id, svc._d(from_date, "From date"), svc._d(to_date, "To date"))
    return {"project_id": project_id, "total": str(sum((l.value for l in lines), Decimal("0"))),
            "lines": [{"cost_head": l.cost_head, "work_order_id": l.work_order_id, "boq_item_id": l.boq_item_id, "item_id": l.item_id, "qty": str(l.qty), "value": str(l.value)} for l in lines]}


@router.post("/integration/subcon-recoveries/sync")
def sync_recoveries(request: Request, db: Session = Depends(get_db)):
    """Create, refresh or withdraw the subcontract billing's material-recovery rows from chargeable subcontractor issues."""
    actor = store_actor(request, db, "store.reports.post")
    try:
        with store_errors():
            out = store_integration.sync_subcon_recoveries(db, actor.client.id)
        db.commit()
        return out
    except BaseException:
        db.rollback()
        raise
