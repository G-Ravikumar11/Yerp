"""Store module - inward routes under /api/store/inward. Owned by P2.

Rights: store.inward.view to look; .create to raise gate entries, GRNs and returns and submit them; .approve to approve
them and to record quality checks; .post to post; .cancel to cancel. Everything about a store also needs access to it.
A direct receipt (no PO) needs a reason, and is approved by someone other than whoever raised it.
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.store_auth import store_actor, store_errors
from app.db import get_db
from app.documents.store import inward_forms
from app.models.store_core import DBStore, DocStatus, StoreError
from app.models.store_inward import (
    DBStoreClientSupplyRate, DBStoreGateEntry, DBStoreGrn, DBStoreGrnLine, DBStoreGrnQc, DBStorePurchaseReturn,
    DBStorePurchaseReturnLine, DBStoreRejectionMemo, GrnKind, QcStatus,
)
from app.routers.store_masters import accessible_store_ids, company_store, project_names, status_trail
from app.services import store_inward as svc
from app.services.store_numbering import next_doc_number

router = APIRouter(prefix="/api/store/inward", tags=["store-inward"])

VIEW, CREATE, APPROVE, POST, CANCEL = ("store.inward.%s" % a for a in ("view", "create", "approve", "post", "cancel"))
s = str


def _d(x):
    return x.isoformat() if x else None


def _people(db, ids):
    ids = {i for i in ids if i}
    return {e.id: ("%s %s" % (e.first_name or "", e.last_name or "")).strip()
            for e in db.query(models.DBEmployee).filter(models.DBEmployee.id.in_(ids))} if ids else {}


def _mine(db, actor, query, col):
    mine = accessible_store_ids(db, actor)
    return query if mine is None else query.filter(col.in_(mine or {-1}))


def _commit_or_rollback(db, fn):
    """Run a change; any refusal undoes all of it."""
    try:
        with store_errors():
            out = fn()
        db.commit()
        return out
    except (HTTPException, StoreError):
        db.rollback()
        raise


# --- settings ------------------------------------------------------------------------------------------------------

class SettingsIn(BaseModel):
    gst_recoverable: bool


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    row = svc.inward_settings(db, actor.client.id)
    db.commit()
    return {"gst_recoverable": row.gst_recoverable}


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, APPROVE)
    row = svc.inward_settings(db, actor.client.id)
    row.gst_recoverable = body.gst_recoverable
    db.commit()
    return {"gst_recoverable": row.gst_recoverable}


# --- gate inward register ------------------------------------------------------------------------------------------

class GateIn(BaseModel):
    store_id: int
    entry_date: date
    time_in: str = ""
    vehicle_no: str = ""
    supplier_id: Optional[int] = None
    vendor_name: str = ""
    po_id: Optional[int] = None
    challan_no: str = ""
    challan_date: Optional[date] = None
    weighbridge_slip_no: str = ""
    gross_weight: Optional[str] = None
    tare_weight: Optional[str] = None
    remarks: str = ""


def _weights(body):
    gross = svc.q(svc.num(body.gross_weight), svc._QTY) if body.gross_weight not in (None, "") else None
    tare = svc.q(svc.num(body.tare_weight), svc._QTY) if body.tare_weight not in (None, "") else None
    if gross is not None and tare is not None:
        if tare > gross:
            raise HTTPException(400, "Tare weight is more than the gross weight.")
        return gross, tare, gross - tare
    return gross, tare, None


def _gate_dict(db, g, store=None):
    store = store or db.get(DBStore, g.store_id)
    po = db.get(models.DBPurchaseOrder, g.po_id) if g.po_id else None
    grns = db.query(DBStoreGrn).filter(DBStoreGrn.gate_entry_id == g.id, DBStoreGrn.status != DocStatus.CANCELLED.value).all()
    return {"id": g.id, "number": g.number, "store_id": g.store_id, "store_code": store.code, "entry_date": _d(g.entry_date),
            "time_in": g.time_in or "", "vehicle_no": g.vehicle_no or "", "supplier_id": g.supplier_id, "vendor_name": g.vendor_name or "",
            "po_id": g.po_id, "po_number": po.number if po else None, "challan_no": g.challan_no or "", "challan_date": _d(g.challan_date),
            "weighbridge_slip_no": g.weighbridge_slip_no or "", "gross_weight": s(g.gross_weight) if g.gross_weight is not None else None,
            "tare_weight": s(g.tare_weight) if g.tare_weight is not None else None,
            "net_weight": s(g.net_weight) if g.net_weight is not None else None, "remarks": g.remarks or "", "status": g.status,
            "grns": [{"id": x.id, "number": x.number, "status": x.status} for x in grns], "created_by": g.created_by_name or ""}


def _gate_fields(db, actor, g, body):
    if body.po_id:
        svc.po_or_400(db, actor.client.id, body.po_id, db.get(DBStore, g.store_id))
    if body.supplier_id:
        sup = db.get(models.DBSupplier, body.supplier_id)
        if sup is None or sup.client_id != actor.client.id:
            raise HTTPException(400, "Supplier not found.")
        g.vendor_name = body.vendor_name.strip() or sup.name
    else:
        g.vendor_name = body.vendor_name.strip()
    if body.entry_date > date.today():
        raise HTTPException(400, "A gate entry cannot be dated in the future.")
    g.gross_weight, g.tare_weight, g.net_weight = _weights(body)
    g.entry_date, g.time_in, g.vehicle_no = body.entry_date, body.time_in.strip()[:10], body.vehicle_no.strip().upper()
    g.supplier_id, g.po_id, g.challan_no, g.challan_date = body.supplier_id, body.po_id, body.challan_no.strip(), body.challan_date
    g.weighbridge_slip_no, g.remarks = body.weighbridge_slip_no.strip(), body.remarks.strip()


@router.get("/gate")
def list_gate(request: Request, store_id: int = 0, status: str = "", db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    query = _mine(db, actor, db.query(DBStoreGateEntry).filter(DBStoreGateEntry.client_id == actor.client.id), DBStoreGateEntry.store_id)
    if store_id:
        query = query.filter(DBStoreGateEntry.store_id == store_id)
    if status:
        query = query.filter(DBStoreGateEntry.status == status.upper())
    return {"entries": [_gate_dict(db, g) for g in query.order_by(DBStoreGateEntry.id.desc()).limit(500).all()]}


@router.post("/gate")
def create_gate(body: GateIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    store = company_store(db, actor, body.store_id)

    def go():
        g = DBStoreGateEntry(client_id=actor.client.id, store_id=store.id, status="OPEN", created_by=actor.user_id,
                             created_by_name=actor.name, number=next_doc_number(db, "GATE", store.id, on_date=body.entry_date),
                             entry_date=body.entry_date)
        _gate_fields(db, actor, g, body)
        db.add(g)
        db.flush()
        return g
    return _gate_dict(db, _commit_or_rollback(db, go), store)


def _gate_or_404(db, actor, gate_id):
    g = db.get(DBStoreGateEntry, gate_id)
    if g is None or g.client_id != actor.client.id:
        raise HTTPException(404, "Gate entry not found")
    company_store(db, actor, g.store_id)
    return g


@router.get("/gate/{gate_id:int}")
def get_gate(gate_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    return _gate_dict(db, _gate_or_404(db, actor, gate_id))


@router.put("/gate/{gate_id:int}")
def update_gate(gate_id: int, body: GateIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    g = _gate_or_404(db, actor, gate_id)
    if g.status != "OPEN":
        raise HTTPException(409, "Only an open gate entry changes.")
    if body.store_id != g.store_id:
        raise HTTPException(400, "A gate entry stays at its store.")
    return _gate_dict(db, _commit_or_rollback(db, lambda: (_gate_fields(db, actor, g, body), g)[1]))


@router.post("/gate/{gate_id:int}/cancel")
def cancel_gate(gate_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CANCEL)
    g = _gate_or_404(db, actor, gate_id)
    if g.status != "OPEN":
        raise HTTPException(409, "A gate entry with a GRN made from it is not cancelled; cancel the GRN first.")
    g.status = "CANCELLED"
    db.commit()
    return _gate_dict(db, g)


# --- purchase orders, read only ------------------------------------------------------------------------------------

@router.get("/pos")
def list_pos(request: Request, store_id: int, db: Session = Depends(get_db)):
    """Approved orders for the store's project (a central store sees every approved order), with what is still to come."""
    actor = store_actor(request, db, VIEW)
    store = company_store(db, actor, store_id)
    out = []
    for po in svc.approved_pos(db, actor.client.id, store):
        lines = svc.po_line_position(db, actor.client.id, po)
        open_lines = [l for l in lines if l.get("factor") and svc.D(l["pending_base"]) > 0]
        out.append({"id": po.id, "number": po.number, "vendor": po.supplier_name or "", "project_id": po.job_id,
                    "issue_date": po.issue_date or "", "needed_by": po.needed_by or "", "lines": len(lines),
                    "open_lines": len(open_lines), "fully_received": not open_lines})
    return {"orders": out}


@router.get("/pos/{po_id:int}/lines")
def po_lines(po_id: int, request: Request, store_id: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    store = company_store(db, actor, store_id) if store_id else None
    po = svc.po_or_400(db, actor.client.id, po_id, store)
    return {"po_id": po.id, "number": po.number, "vendor": po.supplier_name or "", "lines": svc.po_line_position(db, actor.client.id, po)}


@router.get("/pos/{po_id:int}/receipt-summary")
def receipt_summary(po_id: int, request: Request, db: Session = Depends(get_db)):
    """get_po_receipt_summary over HTTP: per line, in the order's unit."""
    actor = store_actor(request, db, VIEW)
    po = db.get(models.DBPurchaseOrder, po_id)
    if po is None or po.client_id != actor.client.id:
        raise HTTPException(404, "Purchase order not found")
    return {"po_id": po.id, "number": po.number, "lines": [
        {k: (s(v) if not isinstance(v, (int, type(None))) else v) for k, v in r.__dict__.items()}
        for r in svc.get_po_receipt_summary(db, po.id)]}


@router.get("/pending")
def pending(request: Request, group: str = "po", store_id: int = 0, db: Session = Depends(get_db)):
    """What approved orders still have to deliver: by order, by vendor, or line by line."""
    actor = store_actor(request, db, VIEW)
    if group not in ("po", "vendor", "lines"):
        raise HTTPException(400, "Group by po, vendor or lines.")
    store = company_store(db, actor, store_id) if store_id else None
    return {"group": group, "rows": svc.pending_to_receive(db, actor.client.id, group, store)}


# --- client supply rates -------------------------------------------------------------------------------------------

class ClientRateIn(BaseModel):
    work_order_id: int
    item_id: int
    rate: str
    reference: str = ""


@router.get("/work-orders")
def client_work_orders(request: Request, store_id: int, db: Session = Depends(get_db)):
    """The client work orders of the store's project, for client-supplied material."""
    actor = store_actor(request, db, VIEW)
    store = company_store(db, actor, store_id)
    query = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.client_id == actor.client.id)
    if store.project_id:
        query = query.filter(models.DBWorkOrder.job_id == store.project_id)
    return {"work_orders": [{"id": w.id, "number": w.number, "job_id": w.job_id, "status": w.status}
                            for w in query.order_by(models.DBWorkOrder.id.desc()).all()]}


def _rate_dict(db, r):
    item, wo = db.get(models.DBItem, r.item_id), db.get(models.DBWorkOrder, r.work_order_id)
    return {"id": r.id, "work_order_id": r.work_order_id, "work_order": wo.number if wo else "", "item_id": r.item_id,
            "item_code": item.item_code if item else "", "item_name": item.item_name if item else "",
            "base_uom": svc.base_uom(db, item) if item else "", "rate": s(r.rate), "reference": r.reference or ""}


@router.get("/client-rates")
def list_client_rates(request: Request, work_order_id: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    query = db.query(DBStoreClientSupplyRate).filter(DBStoreClientSupplyRate.client_id == actor.client.id)
    if work_order_id:
        query = query.filter(DBStoreClientSupplyRate.work_order_id == work_order_id)
    return {"rates": [_rate_dict(db, r) for r in query.order_by(DBStoreClientSupplyRate.id).all()]}


@router.post("/client-rates")
def save_client_rate(body: ClientRateIn, request: Request, db: Session = Depends(get_db)):
    """The rate the contract fixes for material the client supplies, per base unit. Saving again changes it for
    receipts from now on; posted receipts keep the rate they went in at."""
    actor = store_actor(request, db, APPROVE)
    svc.client_work_order(db, actor.client.id, body.work_order_id)
    item = svc.company_item(db, actor.client.id, body.item_id)
    rate = svc.q(svc.num(body.rate, "Rate", False), svc._RATE)
    if rate < 0:
        raise HTTPException(400, "The rate cannot be negative.")
    row = svc.client_rate(db, body.work_order_id, item.id)
    if row is None:
        row = DBStoreClientSupplyRate(client_id=actor.client.id, work_order_id=body.work_order_id, item_id=item.id, rate=rate)
        db.add(row)
    row.rate, row.reference = rate, body.reference.strip()
    db.commit()
    return _rate_dict(db, row)


# --- GRNs ----------------------------------------------------------------------------------------------------------

class GrnLineIn(BaseModel):
    po_line_id: Optional[int] = None
    item_id: Optional[int] = None
    uom: str = ""
    received_qty: str = "0"
    accepted_qty: str = "0"
    rejected_qty: str = "0"
    shortage_qty: str = "0"
    rate: Optional[str] = None                # direct receipts: per the unit entered
    gst_pct: Optional[str] = None             # direct receipts
    batch_no: str = ""
    mtc_ref: str = ""
    bundles: Optional[int] = None
    nos: Optional[int] = None
    dia_mm: Optional[str] = None
    bar_length_m: Optional[str] = None
    actual_weight: Optional[str] = None
    remarks: str = ""


class GrnIn(BaseModel):
    store_id: int
    kind: GrnKind = GrnKind.PO
    grn_date: date
    po_id: Optional[int] = None
    gate_entry_id: Optional[int] = None
    work_order_id: Optional[int] = None
    supplier_id: Optional[int] = None
    vendor_name: str = ""
    challan_no: str = ""
    challan_date: Optional[date] = None
    invoice_no: str = ""
    invoice_date: Optional[date] = None
    freight: str = "0"
    loading: str = "0"
    other_charges: str = "0"
    gst_recoverable: Optional[bool] = None    # the company setting when left out
    reason: str = ""
    remarks: str = ""
    lines: List[GrnLineIn]


class GrnUpdate(BaseModel):
    grn_date: Optional[date] = None
    challan_no: Optional[str] = None
    challan_date: Optional[date] = None
    invoice_no: Optional[str] = None
    invoice_date: Optional[date] = None
    freight: Optional[str] = None
    loading: Optional[str] = None
    other_charges: Optional[str] = None
    gst_recoverable: Optional[bool] = None
    reason: Optional[str] = None
    remarks: Optional[str] = None
    lines: Optional[List[GrnLineIn]] = None


class QcIn(BaseModel):
    accepted_qty: str
    rejected_qty: str
    test_type: str = ""
    test_ref: str = ""
    remarks: str = ""


class ReasonIn(BaseModel):
    reason: str = ""


def _grn_or_404(db, actor, grn_id) -> DBStoreGrn:
    g = db.get(DBStoreGrn, grn_id)
    if g is None or g.client_id != actor.client.id:
        raise HTTPException(404, "GRN not found")
    company_store(db, actor, g.store_id)
    return g


def _line_dict(db, l, gate_net, single):
    item = db.get(models.DBItem, l.item_id)
    qc = db.query(DBStoreGrnQc).filter(DBStoreGrnQc.grn_line_id == l.id).order_by(DBStoreGrnQc.id.desc()).first()
    value = svc.q(svc.D(l.accepted_base) * svc.D(l.landed_rate), svc._VALUE)
    return {"id": l.id, "line_no": l.line_no, "po_line_id": l.po_line_id, "item_id": item.id, "item_code": item.item_code,
            "item_name": item.item_name, "uom": l.uom, "factor": s(l.factor), "base_uom": svc.base_uom(db, item),
            "received_qty": s(l.received_qty), "accepted_qty": s(l.accepted_qty), "rejected_qty": s(l.rejected_qty),
            "shortage_qty": s(l.shortage_qty), "received_base": s(l.received_base), "accepted_base": s(l.accepted_base),
            "rejected_base": s(l.rejected_base), "base_rate": s(l.base_rate), "gst_pct": s(l.gst_pct),
            "charges_share": s(l.charges_share), "landed_rate": s(l.landed_rate), "stock_value": s(value),
            "qc_status": l.qc_status, "posted": bool(l.posted), "batch_no": l.batch_no or "", "mtc_ref": l.mtc_ref or "",
            "bundles": l.bundles, "nos": l.nos, "dia_mm": s(l.dia_mm) if l.dia_mm is not None else None,
            "bar_length_m": s(l.bar_length_m) if l.bar_length_m is not None else None,
            "actual_weight": s(l.actual_weight) if l.actual_weight is not None else None,
            "steel": svc.steel_check(l, gate_net, single), "remarks": l.remarks or "",
            "qc": None if qc is None else {"accepted_qty": s(qc.accepted_qty), "rejected_qty": s(qc.rejected_qty), "test_type": qc.test_type,
                                           "test_ref": qc.test_ref, "remarks": qc.remarks, "inspector": qc.inspector_name,
                                           "at": qc.inspected_at.isoformat(timespec="seconds")}}


def grn_dict(db, g, detail=False) -> dict:
    store = db.get(DBStore, g.store_id)
    po = db.get(models.DBPurchaseOrder, g.po_id) if g.po_id else None
    wo = db.get(models.DBWorkOrder, g.work_order_id) if g.work_order_id else None
    gate = db.get(DBStoreGateEntry, g.gate_entry_id) if g.gate_entry_id else None
    lines = svc.grn_lines(db, g)
    total = sum((svc.D(l.accepted_base) * svc.D(l.landed_rate) for l in lines), svc.ZERO)
    row = {"id": g.id, "number": g.number, "kind": g.kind, "doc_type": svc.doc_type_of(g), "store_id": g.store_id, "store_code": store.code,
           "store_name": store.name, "grn_date": _d(g.grn_date), "status": g.status, "po_id": g.po_id, "po_number": po.number if po else None,
           "gate_entry_id": g.gate_entry_id, "gate_number": gate.number if gate else None, "work_order_id": g.work_order_id,
           "work_order": wo.number if wo else None, "project_id": g.project_id, "supplier_id": g.supplier_id, "vendor_name": g.vendor_name or "",
           "challan_no": g.challan_no or "", "challan_date": _d(g.challan_date), "invoice_no": g.invoice_no or "",
           "invoice_date": _d(g.invoice_date), "freight": s(g.freight), "loading": s(g.loading), "other_charges": s(g.other_charges),
           "gst_recoverable": bool(g.gst_recoverable), "reason": g.reason or "", "remarks": g.remarks or "",
           "created_by": g.created_by_name or "", "created_at": g.created_at.isoformat(timespec="seconds") if g.created_at else "",
           "posted_at": g.posted_at.isoformat(timespec="seconds") if g.posted_at else None, "cancel_reason": g.cancel_reason or "",
           "lines_count": len(lines), "stock_value": s(svc.q(total, svc._VALUE)),
           "qc_pending": sum(1 for l in lines if l.qc_status == QcStatus.QC_PENDING.value),
           "unposted": sum(1 for l in lines if not l.posted and svc.D(l.accepted_base) > 0)}
    if detail:
        steel_lines = [l for l in lines if l.nos and l.dia_mm]
        net = gate.net_weight if gate else None
        row["lines"] = [_line_dict(db, l, net, len(steel_lines) == 1) for l in lines]
        memo = db.query(DBStoreRejectionMemo).filter(DBStoreRejectionMemo.grn_id == g.id).first()
        row["rejection_memo"] = memo.number if memo else None
        row["returns"] = [{"id": r.id, "number": r.number, "status": r.status} for r in db.query(DBStorePurchaseReturn)
                          .filter(DBStorePurchaseReturn.grn_id == g.id).order_by(DBStorePurchaseReturn.id).all()]
        row["trail"] = status_trail(db, svc.doc_type_of(g), g.id)
        row["gate"] = _gate_dict(db, gate) if gate else None
    return row


def _grn_head(db, actor, store, g, body, creating):
    """The header fields, checked."""
    if body.grn_date is not None:
        if body.grn_date > date.today():
            raise HTTPException(400, "A GRN cannot be dated in the future.")
        g.grn_date = body.grn_date
    for f in ("challan_no", "invoice_no", "reason", "remarks"):
        v = getattr(body, f)
        if v is not None:
            setattr(g, f, v.strip())
    for f in ("challan_date", "invoice_date"):
        if getattr(body, f) is not None or creating:
            setattr(g, f, getattr(body, f))
    for f in ("freight", "loading", "other_charges"):
        v = getattr(body, f)
        if v is not None:
            amount = svc.q(svc.num(v, f.replace("_", " ").capitalize()), svc._VALUE)
            if amount < 0:
                raise HTTPException(400, "%s cannot be negative." % f.replace("_", " ").capitalize())
            setattr(g, f, amount)
    if body.gst_recoverable is not None:
        g.gst_recoverable = body.gst_recoverable


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door: the latest GRNs in the stores this person works in."""
    actor = store_actor(request, db, VIEW)
    query = _mine(db, actor, db.query(DBStoreGrn).filter(DBStoreGrn.client_id == actor.client.id), DBStoreGrn.store_id)
    return {"slice": "inward", "items": [grn_dict(db, g) for g in query.order_by(DBStoreGrn.id.desc()).limit(50).all()]}


@router.get("/grn")
def list_grns(request: Request, store_id: int = 0, status: str = "", kind: str = "", po_id: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    query = _mine(db, actor, db.query(DBStoreGrn).filter(DBStoreGrn.client_id == actor.client.id), DBStoreGrn.store_id)
    if store_id:
        query = query.filter(DBStoreGrn.store_id == store_id)
    if status:
        query = query.filter(DBStoreGrn.status == status.upper())
    if kind:
        query = query.filter(DBStoreGrn.kind == kind.upper())
    if po_id:
        query = query.filter(DBStoreGrn.po_id == po_id)
    return {"grns": [grn_dict(db, g) for g in query.order_by(DBStoreGrn.id.desc()).limit(500).all()]}


@router.post("/grn")
def create_grn(body: GrnIn, request: Request, db: Session = Depends(get_db)):
    """A GRN against an order, a direct receipt (with a reason) or a receipt of client-supplied material, as a draft."""
    actor = store_actor(request, db, CREATE)
    store = company_store(db, actor, body.store_id)
    if not store.is_active:
        raise HTTPException(400, "%s is not active." % store.code)

    def go():
        settings = svc.inward_settings(db, actor.client.id)
        g = DBStoreGrn(client_id=actor.client.id, store_id=store.id, kind=body.kind.value, grn_date=body.grn_date, status=DocStatus.DRAFT.value,
                       project_id=store.project_id, created_by=actor.user_id, created_by_name=actor.name,
                       gst_recoverable=settings.gst_recoverable if body.gst_recoverable is None else body.gst_recoverable,
                       freight=0, loading=0, other_charges=0)
        _grn_head(db, actor, store, g, body, creating=True)
        if body.kind == GrnKind.PO:
            po = svc.po_or_400(db, actor.client.id, body.po_id, store)
            g.po_id, g.vendor_name = po.id, (body.vendor_name.strip() or po.supplier_name or "")
            g.project_id = store.project_id or po.job_id
        elif body.kind == GrnKind.DIRECT:
            if not body.reason.strip():
                raise HTTPException(400, "Say why this is being bought without a purchase order.")
            if not body.vendor_name.strip() and not body.supplier_id:
                raise HTTPException(400, "Name who it was bought from.")
            g.vendor_name = body.vendor_name.strip()
        else:
            wo = svc.client_work_order(db, actor.client.id, body.work_order_id, store)
            g.work_order_id, g.project_id, g.vendor_name = wo.id, wo.job_id, body.vendor_name.strip() or "Client supply"
        if body.supplier_id:
            sup = db.get(models.DBSupplier, body.supplier_id)
            if sup is None or sup.client_id != actor.client.id:
                raise HTTPException(400, "Supplier not found.")
            g.supplier_id, g.vendor_name = sup.id, g.vendor_name or sup.name
        if body.gate_entry_id:
            gate = _gate_or_404(db, actor, body.gate_entry_id)
            if gate.store_id != store.id or gate.status == "CANCELLED":
                raise HTTPException(400, "That gate entry is not open at %s." % store.code)
            g.gate_entry_id = gate.id
            g.challan_no = g.challan_no or gate.challan_no
            g.challan_date = g.challan_date or gate.challan_date
            g.vendor_name = g.vendor_name or gate.vendor_name
            gate.status = "GRN_MADE"
        g.number = next_doc_number(db, "CSR" if body.kind == GrnKind.CLIENT_SUPPLY else "GRN", store.id, on_date=body.grn_date)
        db.add(g)
        db.flush()
        svc.replace_lines(db, actor.client.id, store, g, [l.model_dump() for l in body.lines])
        svc.log(db, actor.client.id, svc.doc_type_of(g), g.id, None, DocStatus.DRAFT.value, actor,
                ("From gate entry %s" % db.get(DBStoreGateEntry, g.gate_entry_id).number) if g.gate_entry_id else "")
        return g
    return grn_dict(db, _commit_or_rollback(db, go), detail=True)


@router.get("/grn/{grn_id:int}")
def get_grn(grn_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    return grn_dict(db, _grn_or_404(db, actor, grn_id), detail=True)


@router.put("/grn/{grn_id:int}")
def update_grn(grn_id: int, body: GrnUpdate, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    g = _grn_or_404(db, actor, grn_id)
    if g.status != DocStatus.DRAFT.value:
        raise HTTPException(409, "Only a draft GRN changes; this one is %s." % g.status.lower())
    store = db.get(DBStore, g.store_id)

    def go():
        _grn_head(db, actor, store, g, body, creating=False)
        if body.lines is not None:
            svc.replace_lines(db, actor.client.id, store, g, [l.model_dump() for l in body.lines])
        else:
            svc.apportion(g, svc.grn_lines(db, g))      # charges may have changed
        return g
    return grn_dict(db, _commit_or_rollback(db, go), detail=True)


GRN_FLOW = {
    "submit": (CREATE, (DocStatus.DRAFT,), DocStatus.SUBMITTED),
    "approve": (APPROVE, (DocStatus.SUBMITTED,), DocStatus.APPROVED),
    "post": (POST, (DocStatus.APPROVED,), DocStatus.POSTED),
    "cancel": (CANCEL, (DocStatus.DRAFT, DocStatus.SUBMITTED, DocStatus.APPROVED, DocStatus.POSTED), DocStatus.CANCELLED),
}
_DONE = {"submit": "submitted", "approve": "approved", "post": "posted", "cancel": "cancelled"}


@router.post("/grn/{grn_id:int}/{action}")
def grn_action(grn_id: int, action: str, request: Request, body: Optional[ReasonIn] = None, db: Session = Depends(get_db)):
    """submit / approve / post / cancel. Post moves every ready line in one transaction; cancelling a posted GRN
    reverses it, and is refused (409) when its stock has been issued since."""
    if action not in GRN_FLOW:
        raise HTTPException(404, "Unknown action")
    right, sources, target = GRN_FLOW[action]
    actor = store_actor(request, db, right)
    g = _grn_or_404(db, actor, grn_id)
    if DocStatus(g.status) not in sources:
        raise HTTPException(409, "A %s GRN cannot be %s." % (g.status.lower(), _DONE[action]))
    reason = ((body.reason if body else "") or "").strip()
    was = g.status

    def go():
        if action == "submit":
            svc.check_ready(db, g, svc.grn_lines(db, g))
        elif action == "approve":
            if g.kind == GrnKind.DIRECT.value and actor.employee is not None and g.created_by == actor.user_id:
                raise HTTPException(403, "A direct receipt is approved by someone other than whoever raised it.")
        elif action == "post":
            svc.post_grn(db, g, actor)
        else:
            if not reason:
                raise HTTPException(400, "Say why the GRN is being cancelled.")
            svc.cancel_grn(db, g, actor, reason)
        g.status = target.value
        svc.log(db, actor.client.id, svc.doc_type_of(g), g.id, was, target.value, actor, reason)
        return g
    return grn_dict(db, _commit_or_rollback(db, go), detail=True)


@router.post("/grn/lines/{line_id:int}/qc")
def grn_qc(line_id: int, body: QcIn, request: Request, db: Session = Depends(get_db)):
    """The inspector's result for a QC_PENDING line: accepted and rejected quantity (in the line's unit), the test
    reference and remarks. On a posted GRN the accepted quantity goes into stock straight away."""
    actor = store_actor(request, db, APPROVE)
    line = db.get(DBStoreGrnLine, line_id)
    if line is None:
        raise HTTPException(404, "GRN line not found")
    g = _grn_or_404(db, actor, line.grn_id)
    _commit_or_rollback(db, lambda: svc.record_qc(db, g, line, actor, body.accepted_qty, body.rejected_qty, body.test_type,
                                                  body.test_ref, body.remarks))
    return grn_dict(db, g, detail=True)


# --- purchase returns ----------------------------------------------------------------------------------------------

class ReturnLineIn(BaseModel):
    grn_line_id: int
    source: str = "REJECTED"
    qty: str
    remarks: str = ""


class ReturnIn(BaseModel):
    grn_id: int
    return_date: date
    reason: str
    vehicle_no: str = ""
    remarks: str = ""
    lines: List[ReturnLineIn]


def _return_or_404(db, actor, return_id):
    r = db.get(DBStorePurchaseReturn, return_id)
    if r is None or r.client_id != actor.client.id:
        raise HTTPException(404, "Purchase return not found")
    company_store(db, actor, r.store_id)
    return r


def return_dict(db, r, detail=False):
    grn = db.get(DBStoreGrn, r.grn_id)
    note = svc.debit_note(db, r)
    row = {"id": r.id, "number": r.number, "grn_id": r.grn_id, "grn_number": grn.number, "store_id": r.store_id,
           "return_date": _d(r.return_date), "status": r.status, "reason": r.reason or "", "vehicle_no": r.vehicle_no or "",
           "remarks": r.remarks or "", "vendor": note["vendor"], "created_by": r.created_by_name or "",
           "posted_at": r.posted_at.isoformat(timespec="seconds") if r.posted_at else None, "cancel_reason": r.cancel_reason or "",
           "total": note["total"]}
    if detail:
        row["debit_note"] = note
        row["trail"] = status_trail(db, svc.RETURN_DOC, r.id)
    return row


@router.get("/returns")
def list_returns(request: Request, store_id: int = 0, grn_id: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    query = _mine(db, actor, db.query(DBStorePurchaseReturn).filter(DBStorePurchaseReturn.client_id == actor.client.id),
                  DBStorePurchaseReturn.store_id)
    if store_id:
        query = query.filter(DBStorePurchaseReturn.store_id == store_id)
    if grn_id:
        query = query.filter(DBStorePurchaseReturn.grn_id == grn_id)
    return {"returns": [return_dict(db, r) for r in query.order_by(DBStorePurchaseReturn.id.desc()).limit(500).all()]}


@router.post("/returns")
def create_return(body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    """A return against a posted GRN: what was rejected (a debit only) and/or what was accepted (leaves stock)."""
    actor = store_actor(request, db, CREATE)
    grn = _grn_or_404(db, actor, body.grn_id)
    if not body.reason.strip():
        raise HTTPException(400, "Say why the material is going back.")
    if body.return_date > date.today() or body.return_date < grn.grn_date:
        raise HTTPException(400, "A return is dated between its GRN and today.")

    def go():
        lines = svc.build_return_lines(db, grn, [l.model_dump() for l in body.lines])
        r = DBStorePurchaseReturn(client_id=actor.client.id, store_id=grn.store_id, grn_id=grn.id, return_date=body.return_date,
                                  status=DocStatus.DRAFT.value, reason=body.reason.strip(), vehicle_no=body.vehicle_no.strip().upper(),
                                  remarks=body.remarks.strip(), created_by=actor.user_id, created_by_name=actor.name,
                                  number=next_doc_number(db, "PRN", grn.store_id, on_date=body.return_date))
        db.add(r)
        db.flush()
        for l in lines:
            l.return_id = r.id
            db.add(l)
        svc.log(db, actor.client.id, svc.RETURN_DOC, r.id, None, DocStatus.DRAFT.value, actor, "Against %s" % grn.number)
        db.flush()
        return r
    return return_dict(db, _commit_or_rollback(db, go), detail=True)


@router.get("/returns/{return_id:int}")
def get_return(return_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    return return_dict(db, _return_or_404(db, actor, return_id), detail=True)


@router.get("/returns/{return_id:int}/debit-note")
def get_debit_note(return_id: int, request: Request, db: Session = Depends(get_db)):
    """The debit-note data - quantity, rate and GST per line - for accounts to raise against the supplier."""
    actor = store_actor(request, db, VIEW)
    return svc.debit_note(db, _return_or_404(db, actor, return_id))


@router.post("/returns/{return_id:int}/{action}")
def return_action(return_id: int, action: str, request: Request, body: Optional[ReasonIn] = None, db: Session = Depends(get_db)):
    if action not in GRN_FLOW:
        raise HTTPException(404, "Unknown action")
    right, sources, target = GRN_FLOW[action]
    actor = store_actor(request, db, right)
    r = _return_or_404(db, actor, return_id)
    if DocStatus(r.status) not in sources:
        raise HTTPException(409, "A %s return cannot be %s." % (r.status.lower(), _DONE[action]))
    reason = ((body.reason if body else "") or "").strip()
    was = r.status

    def go():
        if action == "post":
            svc.post_return(db, r, actor)
        elif action == "cancel":
            if not reason:
                raise HTTPException(400, "Say why the return is being cancelled.")
            svc.cancel_return(db, r, actor, reason)
        r.status = target.value
        svc.log(db, actor.client.id, svc.RETURN_DOC, r.id, was, target.value, actor, reason)
        return r
    return return_dict(db, _commit_or_rollback(db, go), detail=True)


# --- printables ----------------------------------------------------------------------------------------------------

def _pdf(db, actor, code, data):
    from app.documents.forms import form_pdf_response
    spec, name = inward_forms.build(code, db, actor.client, data)
    return form_pdf_response(spec, name)


@router.get("/grn/{grn_id:int}/document.pdf")
def grn_pdf(grn_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    return _pdf(db, actor, "GRN", grn_dict(db, _grn_or_404(db, actor, grn_id), detail=True))


@router.get("/grn/{grn_id:int}/qc.pdf")
def qc_pdf(grn_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    return _pdf(db, actor, "QC", grn_dict(db, _grn_or_404(db, actor, grn_id), detail=True))


@router.get("/grn/{grn_id:int}/rejection.pdf")
def rejection_pdf(grn_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    d = grn_dict(db, _grn_or_404(db, actor, grn_id), detail=True)
    if not d["rejection_memo"]:
        raise HTTPException(404, "Nothing on this GRN has been rejected.")
    return _pdf(db, actor, "REJECTION", d)


@router.get("/returns/{return_id:int}/document.pdf")
def return_pdf(return_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    return _pdf(db, actor, "RETURN", return_dict(db, _return_or_404(db, actor, return_id), detail=True))
