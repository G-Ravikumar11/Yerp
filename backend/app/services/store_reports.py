"""Store module - reports slice. Owned by P5.

Every report is a function that returns the same plain table, so one screen, one Excel writer and one PDF writer serve them all:

    {"code", "title", "params": {...}, "columns": [{"key", "label", "align", "kind"}], "rows": [{key: value}], "totals": {key: value}}

Numbers travel as strings. Stock reports read the ledger (net of reversals, which are rows in the opposite direction); reports
that belong to another slice call that slice's function and never read its tables.
"""
import io
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import HTTPException

from app import models
from app.models.store_core import DBStore, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, MovementType
from app.models.store_reports import DBStoreConsumptionNorm
from app.services import store_control, store_inward, store_integration, store_outward

ZERO = Decimal("0")
_Q3, _V2, _R4 = Decimal("0.001"), Decimal("0.01"), Decimal("0.0001")


def get_theoretical_requirement(db, boq_item_id, item_id) -> Optional[Decimal]:
    """What the BOQ item should consume of an item by its quantity and norm (with the wastage allowance); None when there is no norm."""
    norm = db.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.boq_item_id == boq_item_id, DBStoreConsumptionNorm.item_id == item_id).first()
    line = db.get(models.DBBoqLine, boq_item_id) if norm is not None else None
    if norm is None or line is None:
        return None
    qty = Decimal(str(line.quantity or 0))
    return (qty * norm.qty_per_unit * (1 + (norm.wastage_pct or ZERO) / 100)).quantize(_Q3, rounding=ROUND_HALF_UP)


def _d(v, what):
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s must be a date like 2026-04-01." % what) from None


def _s(v: Decimal, step=_V2) -> str:
    return str(Decimal(v).quantize(step, rounding=ROUND_HALF_UP))


def col(key, label, align="L", kind="text"):
    return {"key": key, "label": label, "align": align, "kind": kind}


def _qcol(key, label):
    return col(key, label, "R", "qty")


def _mcol(key, label):
    return col(key, label, "R", "money")


class Ctx:
    """What a report may see: the company and the stores the person can reach (narrowed by the store filter)."""

    def __init__(self, db, client_id, stores, params):
        self.db, self.client_id, self.stores, self.params = db, client_id, stores, params
        self.store_ids = [s.id for s in stores]
        self.store = {s.id: s for s in stores}
        self._items = {}

    def item(self, item_id):
        if item_id not in self._items:
            it = self.db.get(models.DBItem, item_id)
            st = self.db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
            self._items[item_id] = (it, st)
        return self._items[item_id]

    def label(self, item_id):
        it, _ = self.item(item_id)
        return it.item_name, it.item_code

    def uom(self, item_id):
        it, st = self.item(item_id)
        return (st.base_uom if st else it.units_of_measure) or ""

    def int_param(self, key):
        try:
            return int(self.params.get(key) or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "%s must be a number." % key) from None


def _ledger(ctx, upto=None, since=None, before=None):
    q = ctx.db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(ctx.store_ids or [0]))
    if upto:
        q = q.filter(DBStoreStockLedger.txn_date <= upto)
    if since:
        q = q.filter(DBStoreStockLedger.txn_date >= since)
    if before:
        q = q.filter(DBStoreStockLedger.txn_date < before)
    return q


# ------------------------------------------------------------------------------------------------ stock reports
def stock_valuation(ctx):
    """Stock and its value per store and item, today or as on a past date."""
    as_on = _d(ctx.params.get("as_on"), "As on")
    groups = {}
    if as_on and as_on < date.today():
        for e in _ledger(ctx, upto=as_on).all():
            q, v = groups.get((e.store_id, e.item_id), (ZERO, ZERO))
            groups[(e.store_id, e.item_id)] = (q + e.qty_in - e.qty_out, v + (e.value if e.qty_in > 0 else -e.value))
    else:
        for b in ctx.db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id.in_(ctx.store_ids or [0])).all():
            groups[(b.store_id, b.item_id)] = (b.qty, b.value)
    cat = ctx.params.get("category")
    rows, tq, tv = [], ZERO, ZERO
    for (sid, iid), (q, v) in sorted(groups.items(), key=lambda kv: (ctx.store[kv[0][0]].code, ctx.label(kv[0][1])[0])):
        if q == 0 and v == 0:
            continue
        _it, st = ctx.item(iid)
        if cat and (not st or st.category != cat):
            continue
        name, code = ctx.label(iid)
        rows.append({"store": ctx.store[sid].code, "code": code, "item": name, "category": st.category if st else "", "uom": ctx.uom(iid), "qty": _s(q, _Q3),
                     "avg_rate": _s(v / q, _R4) if q else "0.0000", "value": _s(v)})
        tq, tv = tq + q, tv + v
    return ("Stock valuation" + (" as on %s" % as_on if as_on else ""),
            [col("store", "Store"), col("code", "Code"), col("item", "Item"), col("category", "Category"), col("uom", "Unit", "C"), _qcol("qty", "Quantity"), _mcol("avg_rate", "Avg rate"), _mcol("value", "Value")],
            rows, {"item": "Total", "value": _s(tv)})


def stock_movement(ctx):
    """Opening, receipts, issues and closing per item for a period."""
    start, end = _d(ctx.params.get("from"), "From date"), _d(ctx.params.get("to"), "To date")
    if not (start and end):
        raise HTTPException(400, "Give the period: from and to dates.")
    groups = {}

    def bucket(e):
        return groups.setdefault((e.store_id, e.item_id), {"oq": ZERO, "ov": ZERO, "rq": ZERO, "rv": ZERO, "iq": ZERO, "iv": ZERO})
    for e in _ledger(ctx, before=start).all():
        b = bucket(e)
        b["oq"] += e.qty_in - e.qty_out
        b["ov"] += e.value if e.qty_in > 0 else -e.value
    for e in _ledger(ctx, since=start, upto=end).all():
        b = bucket(e)
        if e.qty_in > 0:
            b["rq"], b["rv"] = b["rq"] + e.qty_in, b["rv"] + e.value
        else:
            b["iq"], b["iv"] = b["iq"] + e.qty_out, b["iv"] + e.value
    rows, tot = [], {k: ZERO for k in ("ov", "rv", "iv")}
    for (sid, iid), b in sorted(groups.items(), key=lambda kv: (ctx.store[kv[0][0]].code, ctx.label(kv[0][1])[0])):
        cq, cv = b["oq"] + b["rq"] - b["iq"], b["ov"] + b["rv"] - b["iv"]
        name, _ = ctx.label(iid)
        rows.append({"store": ctx.store[sid].code, "item": name, "uom": ctx.uom(iid), "oq": _s(b["oq"], _Q3), "rq": _s(b["rq"], _Q3), "iq": _s(b["iq"], _Q3), "cq": _s(cq, _Q3),
                     "ov": _s(b["ov"]), "rv": _s(b["rv"]), "iv": _s(b["iv"]), "cv": _s(cv)})
        for k in tot:
            tot[k] += b[k]
    totals = {"item": "Total", "ov": _s(tot["ov"]), "rv": _s(tot["rv"]), "iv": _s(tot["iv"]), "cv": _s(tot["ov"] + tot["rv"] - tot["iv"])}
    return ("Stock movement %s to %s" % (start, end),
            [col("store", "Store"), col("item", "Item"), col("uom", "Unit", "C"), _qcol("oq", "Opening qty"), _qcol("rq", "Received"), _qcol("iq", "Issued"), _qcol("cq", "Closing qty"),
             _mcol("ov", "Opening value"), _mcol("rv", "Received value"), _mcol("iv", "Issued value"), _mcol("cv", "Closing value")], rows, totals)


def reorder(ctx):
    """Items at or below their reorder level, with how much would bring them to the maximum."""
    rows = []
    for b in ctx.db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id.in_(ctx.store_ids or [0])).all():
        _it, st = ctx.item(b.item_id)
        level = (st.reorder_level or ZERO) if st else ZERO
        if not level or b.qty > level:
            continue
        name, code = ctx.label(b.item_id)
        top = (st.max_qty or ZERO)
        rows.append({"store": ctx.store[b.store_id].code, "code": code, "item": name, "uom": ctx.uom(b.item_id), "qty": _s(b.qty, _Q3), "reorder": _s(level, _Q3),
                     "short": _s(level - b.qty, _Q3), "suggest": _s(max(top - b.qty, ZERO), _Q3) if top else ""})
    rows.sort(key=lambda r: (r["store"], r["item"]))
    return ("Items to reorder", [col("store", "Store"), col("code", "Code"), col("item", "Item"), col("uom", "Unit", "C"), _qcol("qty", "On hand"), _qcol("reorder", "Reorder level"),
                                 _qcol("short", "Below level by"), _qcol("suggest", "Order to reach maximum")], rows, {})


def slow_moving(ctx):
    """Stock held that has not been issued for N days (default 90)."""
    days = ctx.int_param("days") or 90
    since = date.today() - timedelta(days=days)
    moved = {(sid, iid) for sid, iid in _ledger(ctx, since=since).filter(DBStoreStockLedger.qty_out > 0, DBStoreStockLedger.movement_type.in_(
        store_integration.COST_MOVEMENTS + (MovementType.TRANSFER_OUT.value, MovementType.SCRAP_OUT.value))).with_entities(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id).all()}
    rows, total = [], ZERO
    for b in ctx.db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id.in_(ctx.store_ids or [0]), DBStoreStockBalance.qty > 0).all():
        if (b.store_id, b.item_id) in moved:
            continue
        last = ctx.db.query(DBStoreStockLedger.txn_date).filter(DBStoreStockLedger.store_id == b.store_id, DBStoreStockLedger.item_id == b.item_id, DBStoreStockLedger.qty_out > 0).order_by(
            DBStoreStockLedger.txn_date.desc()).first()
        name, code = ctx.label(b.item_id)
        rows.append({"store": ctx.store[b.store_id].code, "code": code, "item": name, "uom": ctx.uom(b.item_id), "qty": _s(b.qty, _Q3), "value": _s(b.value),
                     "last_out": last[0].isoformat() if last else "never"})
        total += b.value
    rows.sort(key=lambda r: -Decimal(r["value"]))
    return ("Slow-moving stock (no issue for %d days)" % days, [col("store", "Store"), col("code", "Code"), col("item", "Item"), col("uom", "Unit", "C"), _qcol("qty", "Quantity"),
                                                              _mcol("value", "Value"), col("last_out", "Last issued", "C")], rows, {"item": "Total", "value": _s(total)})


# ------------------------------------------------------------------------------------------------ cost reports
def consumption(ctx):
    """Material charged to a project, against what the BOQ norms say it should have taken."""
    project_id = ctx.int_param("project_id")
    job = ctx.db.get(models.DBJob, project_id) if project_id else None
    if job is None or job.client_id != ctx.client_id:
        raise HTTPException(400, "Choose a project.")
    start, end = _d(ctx.params.get("from"), "From date"), _d(ctx.params.get("to"), "To date")
    group = ctx.params.get("group_by") or "detail"
    if group not in ("detail", "cost_head", "work_order", "item"):
        raise HTTPException(400, "group_by must be detail, cost_head, work_order or item.")
    lines = store_integration.get_project_material_cost(ctx.db, project_id, start, end)
    wo_no = {w.id: w.number for w in ctx.db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id.in_({l.work_order_id for l in lines if l.work_order_id} or {0})).all()}
    boq_no = {b.id: ("%s %s" % (b.item_no, b.description or "")).strip()[:50] for b in ctx.db.query(models.DBBoqLine).filter(models.DBBoqLine.id.in_({l.boq_item_id for l in lines if l.boq_item_id} or {0})).all()}
    agg, order = {}, []
    for l in lines:
        key = {"detail": (l.cost_head, l.work_order_id, l.boq_item_id, l.item_id), "cost_head": (l.cost_head,), "work_order": (l.work_order_id,), "item": (l.item_id,)}[group]
        if key not in agg:
            agg[key] = {"qty": ZERO, "value": ZERO, "theory": None, "line": l}
            order.append(key)
        a = agg[key]
        a["qty"], a["value"] = a["qty"] + l.qty, a["value"] + l.value
        if group == "detail" and l.boq_item_id:
            t = get_theoretical_requirement(ctx.db, l.boq_item_id, l.item_id)
            a["theory"] = t
    rows, total = [], ZERO
    for key in order:
        a, l = agg[key], agg[key]["line"]
        name, code = ctx.label(l.item_id)
        row = {"cost_head": (l.cost_head or "").replace("_", " ").lower() or "—", "work_order": wo_no.get(l.work_order_id, "—"), "boq": boq_no.get(l.boq_item_id, "—"),
               "item": name if group in ("detail", "item") else "", "uom": ctx.uom(l.item_id) if group in ("detail", "item") else "", "qty": _s(a["qty"], _Q3) if group in ("detail", "item") else "",
               "value": _s(a["value"]), "theory": "", "variance": ""}
        if a["theory"] is not None:
            row["theory"], row["variance"] = _s(a["theory"], _Q3), _s(a["qty"] - a["theory"], _Q3)
        rows.append(row)
        total += a["value"]
    cols = {"detail": ["cost_head", "work_order", "boq", "item", "uom", "qty", "theory", "variance", "value"], "cost_head": ["cost_head", "value"], "work_order": ["work_order", "value"], "item": ["item", "uom", "qty", "value"]}[group]
    defs = {"cost_head": col("cost_head", "Cost head"), "work_order": col("work_order", "Work order"), "boq": col("boq", "BOQ item"), "item": col("item", "Item"), "uom": col("uom", "Unit", "C"),
            "qty": _qcol("qty", "Issued (net)"), "theory": _qcol("theory", "Per BOQ norms"), "variance": _qcol("variance", "Over / (under)"), "value": _mcol("value", "Value")}
    return ("Material consumption - %s%s" % (job.name, (" (%s to %s)" % (start or "start", end or "today")) if (start or end) else ""), [defs[c] for c in cols], rows, {cols[0]: "Total", "value": _s(total)})


def subcon_material(ctx):
    """Material given to a subcontractor, what came back and what is recoverable from their bills."""
    sid = ctx.int_param("subcontractor_id")
    c = ctx.db.get(models.DBContractor, sid) if sid else None
    if c is None or c.client_id != ctx.client_id:
        raise HTTPException(400, "Choose a subcontractor.")
    upto = _d(ctx.params.get("to"), "To date") or date.today()
    rows, total = [], ZERO
    for l in store_outward.get_subcon_issues(ctx.db, sid, upto):
        name, _ = ctx.label(l.item_id)
        rows.append({"date": l.issue_date.isoformat(), "item": name, "uom": ctx.uom(l.item_id), "issued": _s(l.qty_issued, _Q3), "returned": _s(l.qty_returned, _Q3),
                     "chargeable": "Yes" if l.chargeable else "No", "rate": _s(l.recovery_rate, _R4), "recovery": _s(l.recovery_value)})
        total += l.recovery_value
    return ("Material with %s up to %s" % (c.company_name, upto), [col("date", "Issued on", "C"), col("item", "Item"), col("uom", "Unit", "C"), _qcol("issued", "Issued"), _qcol("returned", "Returned"),
                                                                   col("chargeable", "Chargeable", "C"), _mcol("rate", "Recovery rate"), _mcol("recovery", "To recover")], rows, {"item": "Total", "recovery": _s(total)})


# ------------------------------------------------------------------------------------------------ other slices' data
def returnables(ctx):
    """Returnable items still out, who holds them and how late they are."""
    from app.models.store_outward import DBStoreIssue, DBStoreIssueLine
    rows = []
    for r in store_outward.get_outstanding_returnables(ctx.db, project_id=ctx.int_param("project_id") or None):
        line = ctx.db.get(DBStoreIssueLine, r.issue_line_id)
        issue = ctx.db.get(DBStoreIssue, line.issue_id)
        if issue.store_id not in ctx.store:
            continue
        name, _ = ctx.label(r.item_id)
        rows.append({"store": ctx.store[issue.store_id].code, "issue": issue.number, "item": name, "holder": issue.holder_name or r.holder_type, "qty": _s(r.qty_outstanding, _Q3),
                     "due": r.expected_return_date.isoformat() if r.expected_return_date else "", "late": str(r.overdue_days) if r.overdue_days else ""})
    return ("Returnables outstanding", [col("store", "Store"), col("issue", "Issue"), col("item", "Item"), col("holder", "Held by"), _qcol("qty", "Still out"), col("due", "Due", "C"),
                                        _qcol("late", "Days late")], rows, {})


def in_transit(ctx):
    """Stock dispatched between stores and not yet received."""
    rows, total = [], ZERO
    for l in store_control.get_in_transit(ctx.db, project_id=ctx.int_param("project_id") or None):
        if l.from_store_id not in ctx.store and l.to_store_id not in ctx.store:
            continue
        name, _ = ctx.label(l.item_id)
        rows.append({"transfer": str(l.transfer_id), "from": ctx.db.get(DBStore, l.from_store_id).code, "to": ctx.db.get(DBStore, l.to_store_id).code, "item": name,
                     "qty": _s(l.qty, _Q3), "value": _s(l.value), "sent": l.dispatched_on.isoformat(), "inter": "Yes" if l.inter_project else ""})
        total += l.value
    return ("Stock in transit", [col("transfer", "Transfer", "C"), col("from", "From"), col("to", "To"), col("item", "Item"), _qcol("qty", "Quantity"), _mcol("value", "Value"),
                                 col("sent", "Sent on", "C"), col("inter", "Inter-project", "C")], rows, {"item": "Total", "value": _s(total)})


def count_variances(ctx):
    """What stock counts found against the books."""
    sid = ctx.int_param("store_id")
    if not sid:
        raise HTTPException(400, "Choose a store.")
    rows, total = [], ZERO
    for l in store_control.get_count_variances(ctx.db, sid, _d(ctx.params.get("from"), "From date"), _d(ctx.params.get("to"), "To date")):
        name, _ = ctx.label(l.item_id)
        rows.append({"count": str(l.count_id), "item": name, "uom": ctx.uom(l.item_id), "system": _s(l.system_qty, _Q3), "counted": _s(l.counted_qty, _Q3), "diff": _s(l.variance_qty, _Q3), "value": _s(l.variance_value)})
        total += l.variance_value
    return ("Stock count differences", [col("count", "Count", "C"), col("item", "Item"), col("uom", "Unit", "C"), _qcol("system", "Books"), _qcol("counted", "Counted"), _qcol("diff", "Difference"),
                                        _mcol("value", "Value")], rows, {"item": "Net", "value": _s(total)})


def scrap(ctx):
    """Scrap taken out for a project: book value against what it fetched."""
    rows, book, got = [], ZERO, ZERO
    for l in store_control.get_scrap_realisation(ctx.db, ctx.int_param("project_id") or None, _d(ctx.params.get("from"), "From date"), _d(ctx.params.get("to"), "To date")):
        from app.models.store_control import DBStoreScrap
        doc = ctx.db.get(DBStoreScrap, l.scrap_doc_id)
        if doc.store_id not in ctx.store:
            continue
        name, _ = ctx.label(l.item_id)
        rows.append({"scrap": doc.number, "date": doc.scrap_date.isoformat(), "item": name, "qty": _s(l.qty, _Q3), "book": _s(l.book_value), "got": _s(l.realised_value), "gain": _s(l.realised_value - l.book_value)})
        book, got = book + l.book_value, got + l.realised_value
    return ("Scrap realisation", [col("scrap", "Scrap note"), col("date", "Date", "C"), col("item", "Item"), _qcol("qty", "Quantity"), _mcol("book", "Book value"), _mcol("got", "Realised"), _mcol("gain", "Gain / (loss)")],
            rows, {"item": "Total", "book": _s(book), "got": _s(got), "gain": _s(got - book)})


def po_pending(ctx):
    """Purchase order lines still to be received."""
    rows = []
    q = ctx.db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == ctx.client_id, models.DBPurchaseOrder.status == "Approved")
    if ctx.int_param("project_id"):
        q = q.filter(models.DBPurchaseOrder.job_id == ctx.int_param("project_id"))
    for po in q.order_by(models.DBPurchaseOrder.id.desc()).limit(300).all():
        for r in store_inward.get_po_receipt_summary(ctx.db, po.id):
            if r.pending_qty <= 0:
                continue
            line = ctx.db.get(models.DBPurchaseOrderLineItem, r.po_line_id)
            rows.append({"po": po.number, "supplier": po.supplier_name or "", "item": line.description or line.item_code, "ordered": _s(r.ordered_qty, _Q3), "received": _s(r.received_qty, _Q3),
                         "rejected": _s(r.rejected_qty, _Q3), "pending": _s(r.pending_qty, _Q3), "needed": po.needed_by or ""})
    return ("Purchase orders pending receipt", [col("po", "PO"), col("supplier", "Supplier"), col("item", "Item"), _qcol("ordered", "Ordered"), _qcol("received", "Received"), _qcol("rejected", "Rejected"),
                                                _qcol("pending", "Pending"), col("needed", "Needed by", "C")], rows, {})


REPORTS = {
    "stock-valuation": (stock_valuation, "Stock valuation", ["as_on", "store_id", "category"]),
    "stock-movement": (stock_movement, "Stock movement", ["from", "to", "store_id"]),
    "reorder": (reorder, "Items to reorder", ["store_id"]),
    "slow-moving": (slow_moving, "Slow-moving stock", ["days", "store_id"]),
    "consumption": (consumption, "Material consumption", ["project_id", "from", "to", "group_by"]),
    "subcon-material": (subcon_material, "Material with subcontractors", ["subcontractor_id", "to"]),
    "returnables": (returnables, "Returnables outstanding", ["project_id", "store_id"]),
    "in-transit": (in_transit, "Stock in transit", ["project_id", "store_id"]),
    "count-variances": (count_variances, "Stock count differences", ["store_id", "from", "to"]),
    "scrap": (scrap, "Scrap realisation", ["project_id", "from", "to", "store_id"]),
    "po-pending": (po_pending, "Purchase orders pending receipt", ["project_id"]),
}


def catalog():
    return [{"code": code, "title": title, "params": params} for code, (_fn, title, params) in REPORTS.items()]


def run_report(db, client_id, stores, code, params) -> dict:
    if code not in REPORTS:
        raise HTTPException(404, "Unknown report")
    ctx = Ctx(db, client_id, stores, params)
    title, columns, rows, totals = REPORTS[code][0](ctx)
    return {"code": code, "title": title, "params": {k: v for k, v in params.items() if v not in (None, "")}, "columns": columns, "rows": rows, "totals": totals,
            "generated_at": datetime.now().isoformat(timespec="minutes")}


def to_xlsx(rep: dict, company: str = "") -> bytes:
    """The report as an Excel workbook: title, parameters, header row, data (numbers as numbers) and totals."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = rep["code"][:31]
    ws.append([company or "Store report"])
    ws.append([rep["title"]])
    ws.append(["  ".join("%s: %s" % (k, v) for k, v in rep["params"].items()) or "All records"])
    ws.append([])
    head = [c["label"] for c in rep["columns"]]
    ws.append(head)
    for cell in ws[5]:
        cell.font, cell.fill = Font(bold=True), PatternFill("solid", fgColor="E8E8E8")
    ws["A1"].font, ws["A2"].font = Font(bold=True, size=13), Font(bold=True)

    def cellval(c, v):
        if c["kind"] in ("qty", "money") and v not in ("", None):
            try:
                return float(v)
            except ValueError:
                return v
        return v
    for r in rep["rows"]:
        ws.append([cellval(c, r.get(c["key"], "")) for c in rep["columns"]])
    if rep["totals"]:
        ws.append([cellval(c, rep["totals"].get(c["key"], "")) for c in rep["columns"]])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
    for i, c in enumerate(rep["columns"], 1):
        letter = ws.cell(row=5, column=i).column_letter
        ws.column_dimensions[letter].width = max(10, min(40, max([len(c["label"])] + [len(str(r.get(c["key"], ""))) for r in rep["rows"][:200]]) + 2))
        for row in ws.iter_rows(min_row=6, min_col=i, max_col=i):
            for cell in row:
                if c["kind"] == "money":
                    cell.number_format = "#,##0.00"
                elif c["kind"] == "qty":
                    cell.number_format = "#,##0.###"
                if c["align"] == "R":
                    cell.alignment = Alignment(horizontal="right")
    ws.freeze_panes = "A6"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def summary(db, client_id, stores) -> dict:
    """The numbers on the reports home."""
    ctx = Ctx(db, client_id, stores, {})
    _t, _c, val_rows, val_tot = stock_valuation(ctx)
    low = reorder(ctx)[2]
    late = [r for r in returnables(ctx)[2] if r["late"]]
    return {"stock_value": val_tot.get("value", "0.00"), "stock_lines": len(val_rows), "below_reorder": len(low), "in_transit": len({r["transfer"] for r in in_transit(ctx)[2]}),
            "returnables_late": len(late), "open_writeoffs": len([w for w in store_outward.list_writeoff_requests(db, "OPEN") if w.store_id in ctx.store])}
