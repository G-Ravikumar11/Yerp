"""Store module - the Overview page's figures, gathered from what the other slices already keep.

Nothing here is stored or recalculated a second way: stock and its value are the balances post_movement keeps, low stock is the
reorder report, work waiting is each document's own status, movements are the ledger, and a project's budget position is the work
orders' allocation (subcontract_orders.wo_committed_by_budget) beside what the store has issued to it (store_integration). Each part
is returned only to somebody who may open the screen behind it.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app import models
from app.core.permissions import permissions_for
from app.models.store_control import COUNT, SCRAP, TRANSFER, DBStoreCount, DBStoreScrap, DBStoreTransfer
from app.models.store_core import DBStore, DBStoreStockBalance, DBStoreStockLedger, DocStatus
from app.models.store_inward import (CLIENT_SUPPLY, GRN, OPENING, PURCHASE_RETURN, DBStoreClientSupply, DBStoreGrn, DBStoreOpening,
                                     DBStorePurchaseReturn)
from app.models.store_outward import ISSUE, ISSUE_RETURN, DBStoreIndent, DBStoreIssue, DBStoreIssueReturn
from app.services import store_integration, store_reports
from app.services.store_outward import get_outstanding_returnables
from app.services.subcontract_orders import wo_committed_by_budget

ZERO = Decimal("0")
MONEY = Decimal("0.01")

# What the ledger calls each document, the document itself, and where its page is.
DOCS = {
    GRN: (DBStoreGrn, "inward/grn"), PURCHASE_RETURN: (DBStorePurchaseReturn, "inward/returns"),
    CLIENT_SUPPLY: (DBStoreClientSupply, "inward/client-supply"), OPENING: (DBStoreOpening, "inward/opening"),
    ISSUE: (DBStoreIssue, "outward/issue"), ISSUE_RETURN: (DBStoreIssueReturn, "outward/returns"),
    TRANSFER: (DBStoreTransfer, "control/transfer"), COUNT: (DBStoreCount, "control/count"), SCRAP: (DBStoreScrap, "control/scrap"),
}

# The documents that wait on somebody: (slice, model, list page, label).
WAITING = (
    ("inward", DBStoreGrn, "inward/grn", "Goods receipts"),
    ("inward", DBStorePurchaseReturn, "inward/returns", "Purchase returns"),
    ("inward", DBStoreClientSupply, "inward/client-supply", "Client supplies"),
    ("inward", DBStoreOpening, "inward/opening", "Opening stock"),
    ("outward", DBStoreIssue, "outward/issue", "Issues"),
    ("outward", DBStoreIssueReturn, "outward/returns", "Returns"),
    ("control", DBStoreTransfer, "control/transfer", "Transfers"),
    ("control", DBStoreCount, "control/count", "Stock counts"),
    ("control", DBStoreScrap, "control/scrap", "Wastage and scrap"),
)

RECENT = 10
BUDGET_ROWS = 8


def _rights(actor):
    """The rights to read the screen by: every one for the account holder (no employee record) and for store.admin."""
    if actor.employee is None:
        return None
    perms = permissions_for(actor.employee)
    return None if "store.admin" in perms else perms


def _can(rights, perm):
    return rights is None or perm in rights


def _store_filter(column, store_ids):
    return column.in_(list(store_ids)) if store_ids is not None else True


def _stock(db, client_id, store_ids):
    stores = store_reports._stores(db, client_id, store_ids)
    ids = list(stores)
    if not ids:
        return {"stores": 0, "items_in_stock": 0, "lines_in_stock": 0, "total_value": ZERO, "low_stock": 0, "out_of_stock": 0, "low_rows": []}
    held = (db.query(func.count(DBStoreStockBalance.item_id.distinct()), func.count(DBStoreStockBalance.item_id), func.sum(DBStoreStockBalance.value))
            .filter(DBStoreStockBalance.store_id.in_(ids), DBStoreStockBalance.qty > 0).one())
    low = store_reports.reorder(db, client_id, set(ids))["rows"]
    # Worst first: nothing left before something merely below its level.
    low.sort(key=lambda r: (r["qty"] > 0, r["qty"] - r["reorder_level"]))
    return {"stores": len(ids), "items_in_stock": held[0] or 0, "lines_in_stock": held[1] or 0,
            "total_value": Decimal(str(held[2] or 0)).quantize(MONEY),
            "low_stock": len(low), "out_of_stock": sum(1 for r in low if r["qty"] <= 0), "low_rows": low[:5]}


def _waiting(db, client_id, store_ids, rights):
    """Documents waiting on somebody who may act on them: submitted ones to approve, approved ones to post."""
    out = []
    for slice_, model, path, label in WAITING:
        if not _can(rights, "store.%s.view" % slice_):
            continue
        counts = dict(db.query(model.status, func.count(model.id))
                      .filter(model.client_id == client_id, _store_filter(model.store_id, store_ids),
                              model.status.in_([DocStatus.SUBMITTED.value, DocStatus.APPROVED.value]))
                      .group_by(model.status).all())
        if counts.get(DocStatus.SUBMITTED.value) and _can(rights, "store.%s.approve" % slice_):
            out.append({"label": label, "action": "to approve", "count": counts[DocStatus.SUBMITTED.value], "path": "/store/hub/%s?status=SUBMITTED" % path})
        if counts.get(DocStatus.APPROVED.value) and _can(rights, "store.%s.post" % slice_):
            out.append({"label": label, "action": "to post", "count": counts[DocStatus.APPROVED.value], "path": "/store/hub/%s?status=APPROVED" % path})
    if _can(rights, "store.outward.approve"):
        n = (db.query(func.count(DBStoreIndent.id)).filter(DBStoreIndent.client_id == client_id, _store_filter(DBStoreIndent.store_id, store_ids),
                                                            DBStoreIndent.status == "SUBMITTED").scalar() or 0)
        if n:
            out.append({"label": "Indents", "action": "to approve", "count": n, "path": "/store/hub/outward/indent?status=SUBMITTED"})
    if _can(rights, "store.control.view"):
        # Sent to one of this person's stores and not yet received there.
        n = (db.query(func.count(DBStoreTransfer.id)).filter(DBStoreTransfer.client_id == client_id, DBStoreTransfer.status == DocStatus.POSTED.value,
                                                              DBStoreTransfer.receipt_status == "IN_TRANSIT", _store_filter(DBStoreTransfer.to_store_id, store_ids))
             .scalar() or 0)
        if n:
            out.append({"label": "Transfers", "action": "to receive", "count": n, "path": "/store/hub/control/in-transit"})
    return out


def _overdue_returnables(db, client_id, store_ids):
    """Returnable lines past the date they were due back, in this company's stores (the service reads one store at a time)."""
    rows = []
    for sid in store_reports._stores(db, client_id, store_ids):
        rows.extend(get_outstanding_returnables(db, store_id=sid))
    return sum(1 for r in rows if r.overdue_days > 0)


def _recent(db, client_id, store_ids):
    q = (db.query(DBStoreStockLedger, DBStore).join(DBStore, DBStore.id == DBStoreStockLedger.store_id)
         .filter(DBStore.client_id == client_id, _store_filter(DBStoreStockLedger.store_id, store_ids))
         .order_by(DBStoreStockLedger.id.desc()).limit(RECENT).all())
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l, _ in q] or [0])).all()}
    numbers = {}
    for ref, (model, _path) in DOCS.items():
        ids = [l.ref_doc_id for l, _ in q if l.ref_doc_type == ref]
        if ids:
            numbers.update({(ref, d.id): d.number for d in db.query(model.id, model.number).filter(model.id.in_(ids)).all()})
    rows = []
    for l, store in q:
        qty_in, qty_out = Decimal(str(l.qty_in or 0)), Decimal(str(l.qty_out or 0))
        doc = DOCS.get(l.ref_doc_type)
        item = items.get(l.item_id)
        rows.append({"id": l.id, "date": l.txn_date, "store_code": store.code, "item_id": l.item_id,
                     "item_code": item.item_code if item else "", "item_name": item.item_name if item else "",
                     "movement_type": l.movement_type, "qty": store_reports.q3(qty_in - qty_out),
                     "value": Decimal(str(l.value or 0)).quantize(MONEY), "reversal": l.reversal_of_id is not None,
                     "doc_number": numbers.get((l.ref_doc_type, l.ref_doc_id), ""),
                     "doc_path": "/store/hub/%s/%d" % (doc[1], l.ref_doc_id) if doc else ""})
    return rows


def _budgets(db, client_id):
    """Each project with an allocation, or material from the store: allocated, committed by work orders, issued from the store, and
    what is left after both. Shown, never enforced - an issue to site is not refused for it."""
    allocated = dict(db.query(models.DBProjectBudget.job_id, func.sum(models.DBProjectBudget.allocated_amount))
                     .filter(models.DBProjectBudget.client_id == client_id, models.DBProjectBudget.is_active.is_(True))
                     .group_by(models.DBProjectBudget.job_id).all())
    budget_job = dict(db.query(models.DBProjectBudget.id, models.DBProjectBudget.job_id)
                      .filter(models.DBProjectBudget.client_id == client_id, models.DBProjectBudget.is_active.is_(True)).all())
    committed = {}
    for budget_id, amount in wo_committed_by_budget(db, client_id).items():
        job = budget_job.get(budget_id)
        if job is not None:
            committed[job] = committed.get(job, ZERO) + Decimal(str(amount or 0))
    material = store_integration.store_material_by_project(db, client_id)
    ids = set(allocated) | set(material)
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id, models.DBJob.id.in_(list(ids) or [0])).all()}
    rows = []
    for jid in ids:
        job = jobs.get(jid)
        if job is None:
            continue
        alloc = Decimal(str(allocated.get(jid) or 0)).quantize(MONEY)
        wo = committed.get(jid, ZERO).quantize(MONEY)
        mat = material.get(jid, ZERO).quantize(MONEY)
        rows.append({"project_id": jid, "project": ("%s %s" % (job.number or "", job.name or "")).strip(), "allocated": alloc,
                     "committed": wo, "store_material": mat, "left": (alloc - wo - mat).quantize(MONEY),
                     # An allocation of zero is one nobody has set yet, not one that is spent.
                     "over": bool(alloc > 0 and wo + mat > alloc),
                     "used_pct": int(((wo + mat) * 100 / alloc).to_integral_value()) if alloc > 0 else None})
    rows.sort(key=lambda r: (not r["over"], -(r["used_pct"] or -1), r["project"]))
    total = {k: sum((r[k] for r in rows), ZERO) for k in ("allocated", "committed", "store_material", "left")}
    return {"rows": rows[:BUDGET_ROWS], "projects": len(rows), "over": sum(1 for r in rows if r["over"]), "totals": total}


def dashboard(db, actor, store_ids):
    """The Overview: each part only for somebody who may open what it summarises. `store_ids` None means every store."""
    rights = _rights(actor)
    client_id = actor.client.id
    see_stock = _can(rights, "store.enquiry.view") or _can(rights, "store.reports.view")
    out = {"as_on": date.today(), "waiting": _waiting(db, client_id, store_ids, rights)}
    out["stock"] = _stock(db, client_id, store_ids) if see_stock else None
    out["recent"] = _recent(db, client_id, store_ids) if _can(rights, "store.enquiry.view") else None
    out["overdue_returnables"] = _overdue_returnables(db, client_id, store_ids) if _can(rights, "store.outward.view") else None
    out["budgets"] = _budgets(db, client_id) if _can(rights, "store.reports.view") else None
    return out
