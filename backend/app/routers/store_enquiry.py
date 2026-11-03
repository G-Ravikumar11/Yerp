"""Store module - stock enquiry under /api/store/enquiry: what is held where, an item's stock card (every movement behind
the balance), the movements one document made, and Excel exports of the first two. Owned by P1.

Read-only: it needs store.enquiry.view and never writes. A member of staff sees only the stores they are assigned to
(store.admin and the account holder see the whole company). Quantities and values travel as strings.
"""
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import models
from app.core.store_auth import store_actor
from app.db import get_db, get_read_db
from app.models.store_core import (
    DBStore, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion, MovementType,
)
from app.services import store_levels, store_reservations
from app.routers.store_masters import my_store, num, visible_store_ids

router = APIRouter(prefix="/api/store/enquiry", tags=["store-enquiry"])

ZERO = Decimal("0")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_EXPORT = 20000


def _day(raw, what) -> Optional[date]:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s is not a date (use YYYY-MM-DD)." % what) from None


def _stock_status(qty, s, override=None):
    """NIL / BELOW_MIN / REORDER / OVER_MAX / OK, from the item's settings and the store's own levels where it has set any."""
    if qty <= 0:
        return "NIL"
    level, low, high = store_levels.effective(s, override)
    if low > 0 and qty < low:
        return "BELOW_MIN"
    if level > 0 and qty <= level:
        return "REORDER"
    if high > 0 and qty > high:
        return "OVER_MAX"
    return "OK"


def _balance_query(db, actor, store_id=0, q="", category="", include_zero=False, status=""):
    query = (db.query(DBStoreStockBalance, DBStore, models.DBItem, DBStoreItemSettings)
             .join(DBStore, DBStore.id == DBStoreStockBalance.store_id)
             .join(models.DBItem, models.DBItem.id == DBStoreStockBalance.item_id)
             .outerjoin(DBStoreItemSettings, DBStoreItemSettings.item_id == models.DBItem.id)
             .filter(DBStore.client_id == actor.client.id))
    seen = visible_store_ids(db, actor)
    if seen is not None:
        query = query.filter(DBStore.id.in_(seen or {0}))
    if store_id:
        my_store(db, actor, store_id)
        query = query.filter(DBStore.id == store_id)
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(models.DBItem.item_code.ilike(like), models.DBItem.item_name.ilike(like)))
    if category:
        query = query.filter(DBStoreItemSettings.category == category.strip().upper())
    if not include_zero:
        query = query.filter(DBStoreStockBalance.qty > 0)
    return query.order_by(DBStore.code, models.DBItem.item_name)


def _balance_rows(db, rows, status=""):
    out = []
    over = store_levels.overrides(db, {r[1].id for r in rows})
    held = store_reservations.reserved_map(db, {r[1].id for r in rows}, {r[2].id for r in rows})
    last = _last_received(db, {r[1].id for r in rows})
    for bal, store, item, s in rows:
        o = over.get((store.id, item.id))
        level, low, high = store_levels.effective(s, o)
        st = _stock_status(bal.qty or ZERO, s, o)
        if status and st != status.strip().upper():
            continue
        out.append({"store_id": store.id, "store_code": store.code, "store_name": store.name, "item_id": item.id, "item_code": item.item_code,
                    "item_name": item.item_name, "category": s.category if s else None, "base_uom": (s.base_uom if s else item.units_of_measure) or "",
                    "qty": num(bal.qty), "reserved": num(held.get((store.id, item.id), ZERO)), "available": num(max(ZERO, Decimal(str(bal.qty or 0)) - held.get((store.id, item.id), ZERO))), "avg_rate": num(bal.avg_rate, "0.0001"), "value": num(bal.value, "0.01"), "status": st,
                    "reorder_level": num(level), "min_qty": num(low), "max_qty": num(high),
                    "last_received": last.get((store.id, item.id), "")})
    return out


RECEIVED = (MovementType.GRN_IN.value, MovementType.CLIENT_SUPPLY_IN.value)


def _last_received(db, store_ids):
    """{(store id, item id): the last day stock came in from outside - a receipt or a client supply}, in one grouped query."""
    if not store_ids:
        return {}
    rows = (db.query(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id, func.max(DBStoreStockLedger.txn_date))
            .filter(DBStoreStockLedger.store_id.in_(store_ids), DBStoreStockLedger.movement_type.in_(RECEIVED))
            .group_by(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id).all())
    return {(s, i): d.isoformat() for s, i, d in rows if d}


@router.get("")
def index(request: Request, db: Session = Depends(get_read_db)):
    """The slice's front door: the stock position of the stores this person may see."""
    return {"slice": "enquiry", "items": stock_position(request, limit=200, db=db)["items"]}


@router.get("/balances")
def stock_position(request: Request, store_id: int = 0, q: str = "", category: str = "", status: str = "", include_zero: bool = False,
                   limit: int = 200, offset: int = 0, db: Session = Depends(get_read_db)):
    """What is held, store by store and item by item, with its value and whether it is low."""
    actor = store_actor(request, db, "store.enquiry.view")
    rows = _balance_rows(db, _balance_query(db, actor, store_id, q, category, include_zero).all(), status)
    value = sum((Decimal(r["value"]) for r in rows), ZERO)
    start = max(0, offset)
    page = rows[start:start + max(1, min(limit, 1000))]
    return {"total": len(rows), "total_value": num(value, "0.01"), "items": page,
            "low": sum(1 for r in rows if r["status"] in ("BELOW_MIN", "REORDER"))}


@router.get("/balances/export")
def export_balances(request: Request, store_id: int = 0, q: str = "", category: str = "", status: str = "", include_zero: bool = False,
                    db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.enquiry.view")
    rows = _balance_rows(db, _balance_query(db, actor, store_id, q, category, include_zero).limit(MAX_EXPORT).all(), status)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock position"
    ws.append(["Store", "Store name", "Item code", "Item", "Category", "Unit", "Quantity", "Avg rate", "Value", "Status"])
    for r in rows:
        ws.append([r["store_code"], r["store_name"], r["item_code"], r["item_name"], r["category"] or "", r["base_uom"], float(r["qty"]),
                   float(r["avg_rate"]), float(r["value"]), r["status"]])
    ws.append(["", "", "", "", "", "", "", "Total", float(sum((Decimal(r["value"]) for r in rows), ZERO)), ""])
    return _xlsx(wb, "stock-position.xlsx")


@router.get("/quick")
def quick_find(request: Request, q: str = "", limit: int = 8, db: Session = Depends(get_read_db)):
    """Type-ahead for the Store home page: a few matching items with the quantity held across the person's stores. One grouped query."""
    actor = store_actor(request, db, "store.enquiry.view")
    term = (q or "").strip().replace("%", "").replace("_", "").replace("\\", "")
    if len(term) < 2:
        return {"rows": []}
    like = "%" + term + "%"
    seen = visible_store_ids(db, actor)
    store_filter = DBStoreStockBalance.store_id.in_(seen or {0}) if seen is not None else DBStoreStockBalance.store_id.isnot(None)
    held = (db.query(DBStoreStockBalance.item_id.label("item_id"), func.sum(DBStoreStockBalance.qty).label("qty"), func.count(DBStoreStockBalance.store_id).label("stores"))
            .filter(store_filter, DBStoreStockBalance.qty > 0).group_by(DBStoreStockBalance.item_id).subquery())
    rows = (db.query(models.DBItem.id, models.DBItem.item_code, models.DBItem.item_name,
                     func.coalesce(func.nullif(DBStoreItemSettings.base_uom, ""), models.DBItem.units_of_measure), held.c.qty, held.c.stores)
            .outerjoin(held, held.c.item_id == models.DBItem.id)
            .outerjoin(DBStoreItemSettings, DBStoreItemSettings.item_id == models.DBItem.id)
            .filter(models.DBItem.client_id == actor.client.id, models.DBItem.is_active.isnot(False),
                    models.DBItem.item_code.ilike(like) | models.DBItem.item_name.ilike(like))
            .order_by(held.c.qty.is_(None), models.DBItem.item_name).limit(max(1, min(limit, 20))).all())
    return {"rows": [{"item_id": r[0], "item_code": r[1], "item_name": r[2], "uom": r[3] or "", "qty": str(r[4] or 0), "stores": int(r[5] or 0)} for r in rows]}


@router.get("/items/{item_id}")
def item_position(item_id: int, request: Request, db: Session = Depends(get_read_db)):
    """One item: its settings, the units it can be counted in, and what each store holds of it."""
    actor = store_actor(request, db, "store.enquiry.view")
    item = db.get(models.DBItem, item_id)
    if item is None or item.client_id != actor.client.id:
        raise HTTPException(404, "Item not found")
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    rows = _balance_rows(db, _balance_query(db, actor, 0, "", "", True).filter(models.DBItem.id == item.id).all())
    base = (s.base_uom if s else item.units_of_measure) or ""
    convs = db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).order_by(DBStoreUomConversion.id).all()
    total = sum((Decimal(r["qty"]) for r in rows), ZERO)
    return {"item": {"id": item.id, "code": item.item_code, "name": item.item_name, "base_uom": base, "category": s.category if s else None},
            "stores": rows, "total_qty": num(total), "total_value": num(sum((Decimal(r["value"]) for r in rows), ZERO), "0.01"),
            "also_in": [{"uom": c.from_uom, "qty": num(total / Decimal(c.to_base_factor)) if c.to_base_factor else "0.000"} for c in convs]}


# --- the stock card ---------------------------------------------------------------------------------------------------

def _ledger_query(db, actor, store_id, item_id, from_date, to_date, movement_type, project_id, ref_doc_type, ref_doc_id):
    query = (db.query(DBStoreStockLedger).join(DBStore, DBStore.id == DBStoreStockLedger.store_id).filter(DBStore.client_id == actor.client.id))
    seen = visible_store_ids(db, actor)
    if seen is not None:
        query = query.filter(DBStore.id.in_(seen or {0}))
    if store_id:
        my_store(db, actor, store_id)
        query = query.filter(DBStoreStockLedger.store_id == store_id)
    if item_id:
        query = query.filter(DBStoreStockLedger.item_id == item_id)
    if from_date:
        query = query.filter(DBStoreStockLedger.txn_date >= from_date)
    if to_date:
        query = query.filter(DBStoreStockLedger.txn_date <= to_date)
    if movement_type:
        if movement_type.strip().upper() not in {m.value for m in MovementType}:
            raise HTTPException(400, "%s is not a movement type." % movement_type)
        query = query.filter(DBStoreStockLedger.movement_type == movement_type.strip().upper())
    if project_id:
        query = query.filter(DBStoreStockLedger.project_id == project_id)
    if ref_doc_type:
        query = query.filter(DBStoreStockLedger.ref_doc_type == ref_doc_type.strip().upper())
    if ref_doc_id:
        query = query.filter(DBStoreStockLedger.ref_doc_id == ref_doc_id)
    return query


def _ledger_rows(db, entries):
    """Entries as the stock card shows them, with the names behind the ids and which entries have been reversed."""
    ids = [e.id for e in entries]
    reversed_ids = {r for (r,) in db.query(DBStoreStockLedger.reversal_of_id).filter(DBStoreStockLedger.reversal_of_id.in_(ids)).all()} if ids else set()
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.id.in_({e.store_id for e in entries})).all()} if entries else {}
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_({e.item_id for e in entries})).all()} if entries else {}
    job_ids = {e.project_id for e in entries if e.project_id}
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.id.in_(job_ids)).all()} if job_ids else {}
    emp_ids = {e.user_id for e in entries if e.user_id}
    emps = {x.id: x for x in db.query(models.DBEmployee).filter(models.DBEmployee.id.in_(emp_ids)).all()} if emp_ids else {}
    out = []
    for e in entries:
        st, it, job, emp = stores.get(e.store_id), items.get(e.item_id), jobs.get(e.project_id), emps.get(e.user_id)
        out.append({"id": e.id, "txn_date": e.txn_date.isoformat(), "store_id": e.store_id, "store_code": st.code if st else "", "item_id": e.item_id,
                    "item_code": it.item_code if it else "", "item_name": it.item_name if it else "", "movement_type": e.movement_type,
                    "qty_in": num(e.qty_in), "qty_out": num(e.qty_out), "rate": num(e.rate, "0.0001"), "value": num(e.value, "0.01"),
                    "running_qty": num(e.running_qty), "running_value": num(e.running_value, "0.01"), "avg_rate": num(e.avg_rate, "0.0001"),
                    "project_id": e.project_id, "project": ("%s - %s" % (job.number, job.name)) if job else "", "work_order_id": e.work_order_id,
                    "boq_item_id": e.boq_item_id, "cost_head": e.cost_head, "ref_doc_type": e.ref_doc_type, "ref_doc_id": e.ref_doc_id,
                    "ref_line_id": e.ref_line_id, "reversal_of_id": e.reversal_of_id, "is_reversal": e.reversal_of_id is not None,
                    "reversed": e.id in reversed_ids, "user": ("%s %s" % (emp.first_name, emp.last_name)).strip() if emp else "",
                    "created_at": e.created_at.isoformat() if e.created_at else "", "remarks": e.remarks or ""})
    return out


@router.get("/ledger")
def stock_card(request: Request, store_id: int = 0, item_id: int = 0, from_date: str = "", to_date: str = "", movement_type: str = "",
               project_id: int = 0, ref_doc_type: str = "", ref_doc_id: int = 0, limit: int = 200, offset: int = 0, db: Session = Depends(get_db)):
    """Every movement, oldest first. With one store and one item it is that item's stock card: it also says what was held
    before the first day shown and what is held after the last, so the page adds up."""
    actor = store_actor(request, db, "store.enquiry.view")
    start, end = _day(from_date, "From date"), _day(to_date, "To date")
    if start and end and end < start:
        raise HTTPException(400, "The last day cannot be before the first.")
    query = _ledger_query(db, actor, store_id, item_id, start, end, movement_type, project_id, ref_doc_type, ref_doc_id)
    total = query.count()
    sums = query.with_entities(func.coalesce(func.sum(DBStoreStockLedger.qty_in), 0), func.coalesce(func.sum(DBStoreStockLedger.qty_out), 0)).one()
    entries = query.order_by(DBStoreStockLedger.txn_date, DBStoreStockLedger.id).offset(max(0, offset)).limit(max(1, min(limit, 1000))).all()
    out = {"total": total, "qty_in": num(sums[0]), "qty_out": num(sums[1]), "items": _ledger_rows(db, entries)}
    if store_id and item_id:
        before = ZERO
        if start:
            prior = (db.query(func.coalesce(func.sum(DBStoreStockLedger.qty_in - DBStoreStockLedger.qty_out), 0))
                     .filter(DBStoreStockLedger.store_id == store_id, DBStoreStockLedger.item_id == item_id, DBStoreStockLedger.txn_date < start).scalar())
            before = Decimal(str(prior or 0))
        out["opening_qty"] = num(before)
        out["closing_qty"] = num(before + Decimal(str(sums[0])) - Decimal(str(sums[1])))
    return out


@router.get("/ledger/export")
def export_ledger(request: Request, store_id: int = 0, item_id: int = 0, from_date: str = "", to_date: str = "", movement_type: str = "",
                  project_id: int = 0, ref_doc_type: str = "", ref_doc_id: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.enquiry.view")
    query = _ledger_query(db, actor, store_id, item_id, _day(from_date, "From date"), _day(to_date, "To date"), movement_type, project_id,
                          ref_doc_type, ref_doc_id)
    entries = query.order_by(DBStoreStockLedger.txn_date, DBStoreStockLedger.id).limit(MAX_EXPORT).all()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock ledger"
    ws.append(["Date", "Store", "Item code", "Item", "Movement", "In", "Out", "Rate", "Value", "Balance qty", "Balance value", "Project", "Document", "Reversal", "Remarks"])
    for r in _ledger_rows(db, entries):
        ws.append([r["txn_date"], r["store_code"], r["item_code"], r["item_name"], r["movement_type"], float(r["qty_in"]), float(r["qty_out"]),
                   float(r["rate"]), float(r["value"]), float(r["running_qty"]), float(r["running_value"]), r["project"],
                   "%s #%s" % (r["ref_doc_type"], r["ref_doc_id"]), "Yes" if r["is_reversal"] else "", r["remarks"]])
    return _xlsx(wb, "stock-ledger.xlsx")


@router.get("/documents/{ref_doc_type}/{ref_doc_id}")
def document_movements(ref_doc_type: str, ref_doc_id: int, request: Request, db: Session = Depends(get_read_db)):
    """The stock movements one document made (and the reversals of them)."""
    actor = store_actor(request, db, "store.enquiry.view")
    query = _ledger_query(db, actor, 0, 0, None, None, "", 0, ref_doc_type, ref_doc_id)
    entries = query.order_by(DBStoreStockLedger.id).limit(1000).all()
    if not entries:
        raise HTTPException(404, "No stock movements were found for that document.")
    return {"ref_doc_type": ref_doc_type.upper(), "ref_doc_id": ref_doc_id, "items": _ledger_rows(db, entries)}


def _xlsx(wb, name):
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="%s"' % name})


# ---- registers: posted receipts and issues, one row per line ------------------------------------------------------

def _like(q):
    term = (q or "").strip().replace("%", "").replace("_", "")
    return "%" + term + "%" if term else ""


def _uoms(db, items):
    from app.models.store_core import DBStoreItemSettings as S
    got = {s.item_id: s.base_uom for s in db.query(S).filter(S.item_id.in_([i.id for i in items] or [0])).all()}
    return {i.id: got.get(i.id) or i.units_of_measure or "" for i in items}


@router.get("/receipts")
def receipt_register(request: Request, q: str = "", store_id: int = 0, limit: int = 500, db: Session = Depends(get_read_db)):
    """Every goods receipt line not cancelled, newest first: what came in, from whom, who took it in, and how far it has got.
    Only a posted one is in stock; the others wait to be submitted, approved and posted."""
    from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
    actor = store_actor(request, db, ("store.enquiry.view", "store.inward.view"))
    query = (db.query(DBStoreGrnLine, DBStoreGrn, models.DBItem, DBStore)
             .join(DBStoreGrn, DBStoreGrn.id == DBStoreGrnLine.grn_id)
             .join(models.DBItem, models.DBItem.id == DBStoreGrnLine.item_id)
             .join(DBStore, DBStore.id == DBStoreGrn.store_id)
             .filter(DBStoreGrn.client_id == actor.client.id, DBStoreGrn.status != "CANCELLED"))
    seen = visible_store_ids(db, actor)
    if seen is not None:
        query = query.filter(DBStoreGrn.store_id.in_(seen or {0}))
    if store_id:
        my_store(db, actor, store_id)
        query = query.filter(DBStoreGrn.store_id == store_id)
    like = _like(q)
    if like:
        query = query.filter(or_(models.DBItem.item_name.ilike(like), models.DBItem.item_code.ilike(like), DBStoreGrn.supplier_name.ilike(like), DBStoreGrn.number.ilike(like)))
    rows = query.order_by(DBStoreGrn.grn_date.desc(), DBStoreGrn.id.desc(), DBStoreGrnLine.line_no).limit(max(1, min(limit, 2000))).all()
    pos = {p.id: p.number for p in db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.id.in_({g.po_id for _l, g, _i, _s in rows if g.po_id} or {0})).all()}
    uom = _uoms(db, [i for _l, _g, i, _s in rows])
    return {"items": [{"id": l.id, "grn_id": g.id, "number": g.number, "item_id": i.id, "item_code": i.item_code, "item_name": i.item_name,
                       "qty": num(l.accepted_qty), "uom": uom.get(i.id, ""), "supplier": g.supplier_name or "", "po_number": pos.get(g.po_id, "") if g.po_id else "",
                       "date": g.grn_date.isoformat() if g.grn_date else "", "received_by": g.created_by_name or "", "status": g.status, "store_code": st.code, "store_name": st.name}
                      for l, g, i, st in rows]}


@router.get("/issues")
def issue_register(request: Request, q: str = "", store_id: int = 0, limit: int = 500, db: Session = Depends(get_read_db)):
    """Every issue line not cancelled, newest first: what went out, where it was used, for which project, who issued it and
    how far it has got. Only a posted one has left stock."""
    from app.models.boq import DBBoqLine
    from app.models.store_outward import DBStoreIssue, DBStoreIssueLine
    actor = store_actor(request, db, ("store.enquiry.view", "store.outward.view"))
    query = (db.query(DBStoreIssueLine, DBStoreIssue, models.DBItem, DBStore)
             .join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
             .join(models.DBItem, models.DBItem.id == DBStoreIssueLine.item_id)
             .join(DBStore, DBStore.id == DBStoreIssue.store_id)
             .filter(DBStoreIssue.client_id == actor.client.id, DBStoreIssue.status != "CANCELLED"))
    seen = visible_store_ids(db, actor)
    if seen is not None:
        query = query.filter(DBStoreIssue.store_id.in_(seen or {0}))
    if store_id:
        my_store(db, actor, store_id)
        query = query.filter(DBStoreIssue.store_id == store_id)
    like = _like(q)
    if like:
        query = query.filter(or_(models.DBItem.item_name.ilike(like), models.DBItem.item_code.ilike(like), DBStoreIssue.number.ilike(like), DBStoreIssue.purpose.ilike(like)))
    rows = query.order_by(DBStoreIssue.issue_date.desc(), DBStoreIssue.id.desc(), DBStoreIssueLine.line_no).limit(max(1, min(limit, 2000))).all()
    jobs = {j.id: j.name for j in db.query(models.DBJob).filter(models.DBJob.id.in_({d.project_id for _l, d, _i, _s in rows} or {0})).all()}
    boqs = {b.id: b for b in db.query(DBBoqLine).filter(DBBoqLine.id.in_({l.boq_item_id for l, _d, _i, _s in rows if l.boq_item_id} or {0})).all()}
    subs = {c.id: c.company_name for c in db.query(models.DBContractor).filter(models.DBContractor.id.in_({d.subcontractor_id for _l, d, _i, _s in rows if d.subcontractor_id} or {0})).all()}
    uom = _uoms(db, [i for _l, _d, i, _s in rows])

    def used_for(l, d):
        if l.boq_item_id in boqs:
            b = boqs[l.boq_item_id]
            return ("%s %s" % (b.item_no or "", (b.description or "").split(chr(10))[0][:60])).strip()
        if d.purpose:
            return d.purpose
        return (l.cost_head or "").replace("_", " ").capitalize()

    return {"items": [{"id": l.id, "issue_id": d.id, "number": d.number, "item_id": i.id, "item_code": i.item_code, "item_name": i.item_name,
                       "qty": num(l.qty), "uom": uom.get(i.id, ""), "used_for": used_for(l, d), "subcontractor": subs.get(d.subcontractor_id, ""),
                       "received_by": d.received_by_name or d.holder_name or "", "project": jobs.get(d.project_id, ""),
                       "date": d.issue_date.isoformat() if d.issue_date else "", "issued_by": d.created_by_name or "", "status": d.status, "store_code": st.code}
                      for l, d, i, st in rows]}
