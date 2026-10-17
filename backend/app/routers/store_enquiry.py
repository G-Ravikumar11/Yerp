"""Store module - enquiry routes under /api/store/enquiry. Owned by P1.

What is held - by store, by item, by project - with its value; an item's ledger card in one store, every movement
with the balance after it and a link to the document behind it; and where else an item is held. Read-only, from
store_stock_balance and store_stock_ledger, and only for the stores this person may work in. store.enquiry.view.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.core.store_auth import store_actor
from app.db import get_db
from app.models.store_core import (
    DBStore, DBStoreItemSettings, DBStoreOpening, DBStoreStockBalance, DBStoreStockLedger, IN_MOVEMENTS, MovementType,
)
from app.routers.store_masters import (
    OPENING_DOC, accessible_store_ids, base_uom_of, company_item, company_store, project_names, s,
)

router = APIRouter(prefix="/api/store/enquiry", tags=["store-enquiry"])

VIEW = "store.enquiry.view"
D = Decimal
_QTY, _RATE, _VALUE = D("0.001"), D("0.0001"), D("0.01")

# Where each kind of document opens, for the item card's drill-down. A slice that posts under a new ref_doc_type
# asks P1 to add its screen here; until then the card shows the type and number without a link.
DOC_PATHS = {
    OPENING_DOC: "/store/hub/masters/opening/{id}",
    "GRN": "/store/hub/inward/grn/{id}",
    "PURCHASE_RETURN": "/store/hub/inward/returns/{id}",
    "CLIENT_SUPPLY": "/store/hub/inward/client-supply/{id}",
    "ISSUE": "/store/hub/outward/issues/{id}",
    "ISSUE_RETURN": "/store/hub/outward/returns/{id}",
    "SUBCON_ISSUE": "/store/hub/outward/subcon/{id}",
    "TRANSFER": "/store/hub/control/transfers/{id}",
    "COUNT": "/store/hub/control/counts/{id}",
    "ADJUST": "/store/hub/control/adjustments/{id}",
    "SCRAP": "/store/hub/control/scrap/{id}",
}
MOVEMENT_LABEL = {
    "OPENING_IN": "Opening stock", "GRN_IN": "Goods received", "CLIENT_SUPPLY_IN": "Client supply",
    "PURCHASE_RETURN_OUT": "Returned to supplier", "ISSUE_OUT": "Issued", "ISSUE_RETURN_IN": "Returned from site",
    "SUBCON_ISSUE_OUT": "Issued to subcontractor", "SUBCON_RETURN_IN": "Returned by subcontractor",
    "TRANSFER_OUT": "Transferred out", "TRANSFER_IN": "Transferred in", "ADJUST_IN": "Adjusted up",
    "ADJUST_OUT": "Adjusted down", "WASTAGE_OUT": "Wastage", "SCRAP_OUT": "Scrapped",
}


def _stores_in_reach(db, actor, store_id=0, project_id=0) -> list:
    """The company's stores this person may work in, narrowed to one store or one project's stores."""
    query = db.query(DBStore).filter(DBStore.client_id == actor.client.id)
    if store_id:
        company_store(db, actor, store_id)               # 404 / 403 for a store out of reach
        query = query.filter(DBStore.id == store_id)
    if project_id:
        query = query.filter(DBStore.project_id == project_id)
    mine = accessible_store_ids(db, actor)
    return [st for st in query.order_by(DBStore.code).all() if mine is None or st.id in mine]


def _balances(db, actor, store_id=0, item_id=0, project_id=0, q="", category="", include_zero=False) -> list:
    stores = {st.id: st for st in _stores_in_reach(db, actor, store_id, project_id)}
    if not stores:
        return []
    query = (db.query(DBStoreStockBalance, models.DBItem)
             .join(models.DBItem, models.DBItem.id == DBStoreStockBalance.item_id)
             .filter(DBStoreStockBalance.store_id.in_(list(stores)), models.DBItem.client_id == actor.client.id))
    if item_id:
        query = query.filter(DBStoreStockBalance.item_id == item_id)
    if not include_zero:
        query = query.filter(DBStoreStockBalance.qty > 0)
    term = (q or "").strip().replace("%", "").replace("_", "")
    if term:
        like = "%" + term + "%"
        query = query.filter(or_(models.DBItem.item_code.ilike(like), models.DBItem.item_name.ilike(like)))
    rows = query.all()
    ids = {it.id for _, it in rows}
    settings = {x.item_id: x for x in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(ids)).all()} if ids else {}
    if category:
        rows = [(b, it) for b, it in rows if it.id in settings and settings[it.id].category == category.upper()]
    projects = project_names(db, actor.client.id)
    out = []
    for b, it in rows:
        st, cfg = stores[b.store_id], settings.get(it.id)
        reorder = D(cfg.reorder_level or 0) if cfg else D(0)
        out.append({"store_id": st.id, "store_code": st.code, "store_name": st.name, "store_type": st.type,
                    "project_id": st.project_id, "project": projects.get(st.project_id, "") if st.project_id else "",
                    "item_id": it.id, "item_code": it.item_code, "item_name": it.item_name,
                    "category": cfg.category if cfg else None, "base_uom": base_uom_of(db, it, cfg),
                    "qty": s(b.qty, _QTY), "value": s(b.value, _VALUE), "avg_rate": s(b.avg_rate, _RATE),
                    "reorder_level": s(reorder, _QTY), "below_reorder": bool(reorder and D(b.qty) < reorder)})
    out.sort(key=lambda r: (r["store_code"], r["item_name"].lower()))
    return out


def _group(rows, key) -> list:
    """Store x item rows added up by item, or by project and item. Average = value / quantity of the group."""
    acc = {}
    for r in rows:
        if key == "item":
            k = r["item_id"]
            head = {"item_id": r["item_id"], "item_code": r["item_code"], "item_name": r["item_name"],
                    "category": r["category"], "base_uom": r["base_uom"]}
        else:
            k = (r["project_id"] or 0, r["item_id"])
            head = {"project_id": r["project_id"], "project": r["project"] or "Not on a project", "item_id": r["item_id"],
                    "item_code": r["item_code"], "item_name": r["item_name"], "category": r["category"], "base_uom": r["base_uom"]}
        a = acc.setdefault(k, dict(head, qty=D(0), value=D(0), stores=[]))
        a["qty"] += D(r["qty"])
        a["value"] += D(r["value"])
        a["stores"].append(r["store_code"])
    out = []
    for a in acc.values():
        a["avg_rate"] = s(a["value"] / a["qty"], _RATE) if a["qty"] else "0.0000"
        a["qty"], a["value"] = s(a["qty"], _QTY), s(a["value"], _VALUE)
        out.append(a)
    out.sort(key=lambda r: ((r.get("project") or ""), r["item_name"].lower()))
    return out


def _summary(rows) -> dict:
    return {"lines": len(rows), "items": len({r["item_id"] for r in rows}), "stores": len({r["store_id"] for r in rows}),
            "total_value": s(sum((D(r["value"]) for r in rows), D(0)), _VALUE),
            "below_reorder": sum(1 for r in rows if r["below_reorder"])}


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door: what is held in the stores this person may work in."""
    actor = store_actor(request, db, VIEW)
    return {"slice": "enquiry", "items": _balances(db, actor)}


@router.get("/balances")
def balances(request: Request, store_id: int = 0, item_id: int = 0, project_id: int = 0, q: str = "", category: str = "",
             include_zero: bool = False, group: str = "store", db: Session = Depends(get_db)):
    """Balance with value: by store (one row per store and item), by item (across stores) or by project."""
    actor = store_actor(request, db, VIEW)
    if group not in ("store", "item", "project"):
        raise HTTPException(400, "Group by store, item or project.")
    rows = _balances(db, actor, store_id, item_id, project_id, q, category, include_zero)
    return {"group": group, "rows": rows if group == "store" else _group(rows, group), "summary": _summary(rows)}


def _doc_numbers(db, entries) -> dict:
    """The printed numbers of the documents this slice owns; another slice's documents show by type and id."""
    ids = {e.ref_doc_id for e in entries if e.ref_doc_type == OPENING_DOC}
    if not ids:
        return {}
    return {(OPENING_DOC, d.id): d.number for d in db.query(DBStoreOpening).filter(DBStoreOpening.id.in_(ids)).all()}


def _card(db, actor, item_id, store_id, date_from=None, date_to=None) -> dict:
    item = company_item(db, actor, item_id)
    store = company_store(db, actor, store_id)
    base = base_uom_of(db, item)
    query = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id == store.id, DBStoreStockLedger.item_id == item.id)
    before = None
    if date_from:
        before = (query.filter(DBStoreStockLedger.txn_date < date_from)
                  .order_by(DBStoreStockLedger.txn_date.desc(), DBStoreStockLedger.id.desc()).first())
        query = query.filter(DBStoreStockLedger.txn_date >= date_from)
    if date_to:
        query = query.filter(DBStoreStockLedger.txn_date <= date_to)
    entries = query.order_by(DBStoreStockLedger.txn_date, DBStoreStockLedger.id).limit(5000).all()
    numbers = _doc_numbers(db, entries)
    reversed_by = {r.reversal_of_id: r.id for r in db.query(DBStoreStockLedger.id, DBStoreStockLedger.reversal_of_id).filter(
        DBStoreStockLedger.reversal_of_id.in_([e.id for e in entries]))} if entries else {}
    people = {e.id: ("%s %s" % (e.first_name or "", e.last_name or "")).strip() for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.id.in_({e.user_id for e in entries if e.user_id}))} if entries else {}
    projects = project_names(db, actor.client.id)
    rows, total_in, total_out = [], D(0), D(0)
    for e in entries:
        is_in = D(e.qty_in) > 0
        total_in += D(e.qty_in)
        total_out += D(e.qty_out)
        path = DOC_PATHS.get(e.ref_doc_type)
        rows.append({
            "id": e.id, "txn_date": e.txn_date.isoformat(), "movement_type": e.movement_type,
            "label": ("Reversal: " if e.reversal_of_id else "") + MOVEMENT_LABEL.get(e.movement_type, e.movement_type),
            "direction": "IN" if is_in else "OUT", "qty_in": s(e.qty_in, _QTY), "qty_out": s(e.qty_out, _QTY),
            "rate": s(e.rate, _RATE), "value": s(e.value, _VALUE), "signed_value": s(D(e.value) if is_in else -D(e.value), _VALUE),
            "running_qty": s(e.running_qty, _QTY), "running_value": s(e.running_value, _VALUE), "avg_rate": s(e.avg_rate, _RATE),
            "ref_doc_type": e.ref_doc_type, "ref_doc_id": e.ref_doc_id, "ref_line_id": e.ref_line_id,
            "doc_number": numbers.get((e.ref_doc_type, e.ref_doc_id)) or "%s #%s" % (e.ref_doc_type, e.ref_doc_id),
            "doc_path": path.format(id=e.ref_doc_id) if path else None,
            "reversal_of_id": e.reversal_of_id, "reversed_by_id": reversed_by.get(e.id),
            "project_id": e.project_id, "project": projects.get(e.project_id, "") if e.project_id else "",
            "cost_head": e.cost_head, "work_order_id": e.work_order_id, "boq_item_id": e.boq_item_id,
            "subcontractor_id": e.subcontractor_id, "user": people.get(e.user_id, "") if e.user_id else "",
            "remarks": e.remarks or ""})
    bal = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == store.id, DBStoreStockBalance.item_id == item.id).first()
    opening_qty = D(before.running_qty) if before else D(0)
    opening_value = D(before.running_value) if before else D(0)
    last = rows[-1] if rows else None
    return {
        "item": {"id": item.id, "code": item.item_code, "name": item.item_name, "base_uom": base},
        "store": {"id": store.id, "code": store.code, "name": store.name},
        "from": date_from.isoformat() if date_from else None, "to": date_to.isoformat() if date_to else None,
        "opening": {"qty": s(opening_qty, _QTY), "value": s(opening_value, _VALUE)},
        "closing": {"qty": last["running_qty"] if last else s(opening_qty, _QTY),
                    "value": last["running_value"] if last else s(opening_value, _VALUE)},
        "totals": {"qty_in": s(total_in, _QTY), "qty_out": s(total_out, _QTY)},
        "balance": {"qty": s(bal.qty if bal else 0, _QTY), "value": s(bal.value if bal else 0, _VALUE),
                    "avg_rate": s(bal.avg_rate if bal else 0, _RATE)},
        "rows": rows, "truncated": len(entries) == 5000,
    }


@router.get("/items/{item_id}/card")
def item_card(item_id: int, request: Request, store_id: int, date_from: Optional[date] = None, date_to: Optional[date] = None,
              db: Session = Depends(get_db)):
    """An item's ledger card in one store: the position before the period, every movement in it with the position after
    it, and where each came from."""
    actor = store_actor(request, db, VIEW)
    return _card(db, actor, item_id, store_id, date_from, date_to)


@router.get("/items/{item_id}/card.pdf")
def item_card_pdf(item_id: int, request: Request, store_id: int, date_from: Optional[date] = None, date_to: Optional[date] = None,
                  db: Session = Depends(get_db)):
    from app.documents import form_pdf
    from app.documents.forms import _field_doc, form_pdf_response
    actor = store_actor(request, db, VIEW)
    c = _card(db, actor, item_id, store_id, date_from, date_to)
    rows = [[form_pdf.date_text(r["txn_date"]), r["label"], r["doc_number"],
             r["qty_in"] if r["direction"] == "IN" else "", r["qty_out"] if r["direction"] == "OUT" else "",
             r["rate"], r["value"], r["running_qty"], r["running_value"]] for r in c["rows"]]
    period = "%s to %s" % (form_pdf.date_text(c["from"]) if c["from"] else "start", form_pdf.date_text(c["to"]) if c["to"] else "today")
    blocks = [
        {"type": "pairs", "rows": [("Item", "%s %s" % (c["item"]["code"], c["item"]["name"])), ("Unit", c["item"]["base_uom"]),
                                   ("Store", "%s - %s" % (c["store"]["code"], c["store"]["name"])), ("Period", period),
                                   ("Opening", "%s %s, value %s" % (c["opening"]["qty"], c["item"]["base_uom"], c["opening"]["value"]))],
         "label_width": 30},
        {"type": "table", "columns": [("Date", 20, "C"), ("Movement", 40, "L"), ("Document", 40, "L"), ("In", 20, "R"),
                                      ("Out", 20, "R"), ("Rate", 20, "R"), ("Value", 24, "R"), ("Balance", 22, "R"),
                                      ("Balance value", 26, "R")],
         "rows": rows, "totals": [("Closing", "%s %s / %s" % (c["closing"]["qty"], c["item"]["base_uom"], c["closing"]["value"]), True)]},
    ]
    name = "Item-card-%s-%s" % (c["item"]["code"], c["store"]["code"])
    return form_pdf_response(_field_doc(db, actor.client, "STOCK LEDGER CARD", [("Store", c["store"]["code"]),
                                                                                ("Item", c["item"]["code"])], blocks, [], name), name)


@router.get("/items/{item_id}/availability")
def availability(item_id: int, request: Request, db: Session = Depends(get_db)):
    """Where an item is held, across every store this person may work in (an empty store shows as nought)."""
    actor = store_actor(request, db, VIEW)
    item = company_item(db, actor, item_id)
    stores = [st for st in _stores_in_reach(db, actor) if st.is_active]
    held = {b.store_id: b for b in db.query(DBStoreStockBalance).filter(
        DBStoreStockBalance.item_id == item.id, DBStoreStockBalance.store_id.in_([st.id for st in stores]))} if stores else {}
    projects = project_names(db, actor.client.id)
    rows, qty, value = [], D(0), D(0)
    for st in stores:
        b = held.get(st.id)
        bq, bv = (D(b.qty), D(b.value)) if b else (D(0), D(0))
        qty, value = qty + bq, value + bv
        rows.append({"store_id": st.id, "store_code": st.code, "store_name": st.name, "store_type": st.type,
                     "project": projects.get(st.project_id, "") if st.project_id else "",
                     "qty": s(bq, _QTY), "value": s(bv, _VALUE), "avg_rate": s(b.avg_rate if b else 0, _RATE)})
    rows.sort(key=lambda r: (-D(r["qty"]), r["store_code"]))
    return {"item": {"id": item.id, "code": item.item_code, "name": item.item_name, "base_uom": base_uom_of(db, item)},
            "stores": rows, "total": {"qty": s(qty, _QTY), "value": s(value, _VALUE),
                                      "avg_rate": s(value / qty, _RATE) if qty else "0.0000"}}


@router.get("/movement-types")
def movement_types(request: Request, db: Session = Depends(get_db)):
    """The words the card uses for each movement, and which way each goes."""
    store_actor(request, db, VIEW)
    return {"movement_types": [{"code": m.value, "label": MOVEMENT_LABEL[m.value], "direction": "IN" if m in IN_MOVEMENTS else "OUT"}
                               for m in MovementType]}
