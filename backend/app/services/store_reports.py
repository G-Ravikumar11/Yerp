"""Store module - reports slice. Owned by P5.

Every report is read from store_stock_ledger (and the balances kept from it); nothing here writes stock. Other slices'
data comes through their published functions (store_inward / store_outward / store_control), never their tables.

Netting. A reversal is a row of the same movement_type with the quantity in the other column, so totals by type are
always "qty_in - qty_out" for an IN type and "qty_out - qty_in" for an OUT type, and value is signed by direction.
Reversed documents therefore drop out of every total without being filtered.

Each report returns {"code", "title", "columns": [{key, label, align}], "rows": [...], "totals": {...}, "notes": [...]},
which the router sends as JSON, an Excel workbook or a PDF. Quantities and money are strings.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from app import models
from app.models.store_core import (
    IN_MOVEMENTS, OUT_MOVEMENTS, DBStore, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger,
    MovementType,
)
from app.models.store_reports import DBStoreConsumptionNorm, DBStoreSubconRecovery

D = Decimal
ZERO = D(0)
_QTY, _RATE, _VALUE, _FACTOR, _PCT = D("0.001"), D("0.0001"), D("0.01"), D("0.000001"), D("0.001")
M = MovementType

ISSUES = {M.ISSUE_OUT.value, M.SUBCON_ISSUE_OUT.value}
RETURNS = {M.ISSUE_RETURN_IN.value, M.SUBCON_RETURN_IN.value}
# What a project consumed: issues net of returns, plus what was written off or lost (wastage, scrap at book value,
# count and transit losses booked as adjustments) - adjustments up count back.
CONSUMPTION = ISSUES | RETURNS | {M.WASTAGE_OUT.value, M.SCRAP_OUT.value, M.ADJUST_OUT.value, M.ADJUST_IN.value}
RECEIPTS = {M.GRN_IN.value, M.CLIENT_SUPPLY_IN.value, M.PURCHASE_RETURN_OUT.value}
IN_TYPES = {m.value for m in IN_MOVEMENTS}
OUT_TYPES = {m.value for m in OUT_MOVEMENTS}


def q(x, step) -> Decimal:
    return D(str(x) if not isinstance(x, Decimal) else x).quantize(step, rounding=ROUND_HALF_UP)


def s(x, step=None) -> str:
    return format(q(x, step) if step is not None else D(x), "f")


def plain(x) -> str:
    """3.400 -> 3.4, 425.000000 -> 425: a number as a person writes it."""
    v = format(D(x), "f")
    return v.rstrip("0").rstrip(".") if "." in v else v


def as_date(x):
    if x is None or isinstance(x, date):
        return x
    from datetime import datetime
    return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()


def net_qty(e) -> Decimal:
    """+ for stock in, - for stock out."""
    return D(e.qty_in) - D(e.qty_out)


def net_value(e) -> Decimal:
    return D(e.value) if D(e.qty_in) > 0 else -D(e.value)


def consumed(e):
    """(qty, value) an entry adds to consumption: an OUT counts up, its reversal or a return counts down."""
    return -net_qty(e), -net_value(e)


@dataclass
class Filters:
    client_id: int
    store_ids: Optional[set] = None          # the stores this person may see (None = every store of the company)
    project_id: int = 0
    store_id: int = 0
    item_id: int = 0
    category: str = ""
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    extra: dict = field(default_factory=dict)


# --- lookups -------------------------------------------------------------------------------------------------------

def stores(db, f: Filters, by_project=True) -> dict:
    """{id: store} the filters reach: the company's, the person's, one store, or a project's stores."""
    query = db.query(DBStore).filter(DBStore.client_id == f.client_id)
    if f.store_id:
        query = query.filter(DBStore.id == f.store_id)
    if f.project_id and by_project:
        query = query.filter(DBStore.project_id == f.project_id)
    return {st.id: st for st in query.all() if f.store_ids is None or st.id in f.store_ids}


def item_ids(db, f: Filters) -> Optional[set]:
    """The items the filters allow, or None for any."""
    if f.item_id:
        return {f.item_id}
    if f.category:
        return {r for (r,) in db.query(DBStoreItemSettings.item_id).join(models.DBItem, models.DBItem.id == DBStoreItemSettings.item_id)
                .filter(models.DBItem.client_id == f.client_id, DBStoreItemSettings.category == f.category.upper()).all()}
    return None


class Names:
    """Codes and names for the ids a report prints, looked up once."""

    def __init__(self, db, client_id):
        self.db, self.client_id = db, client_id
        self._items, self._projects, self._wos, self._boq, self._subs, self._stores = {}, None, None, {}, None, None

    def item(self, item_id):
        if item_id not in self._items:
            it = self.db.get(models.DBItem, item_id)
            cfg = self.db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
            self._items[item_id] = {"item_code": it.item_code if it else "", "item_name": it.item_name if it else "",
                                    "base_uom": ((cfg.base_uom if cfg else None) or (it.units_of_measure if it else "")) or "",
                                    "category": cfg.category if cfg else ""}
        return self._items[item_id]

    def project(self, pid):
        if self._projects is None:
            self._projects = {j.id: ("%s %s" % (j.number or "", j.name or "")).strip() for j in self.db.query(models.DBJob).filter(
                models.DBJob.client_id == self.client_id)}
        return self._projects.get(pid, "") if pid else ""

    def work_order(self, wid):
        if self._wos is None:
            self._wos = {w.id: w.number or "" for w in self.db.query(models.DBWorkOrder).filter(models.DBWorkOrder.client_id == self.client_id)}
        return self._wos.get(wid, "") if wid else ""

    def boq(self, bid):
        if bid and bid not in self._boq:
            b = self.db.get(models.DBBoqLine, bid)
            self._boq[bid] = ("%s %s" % (b.item_no or "", (b.description or "").split("\n")[0][:80])).strip() if b else ""
        return self._boq.get(bid, "") if bid else ""

    def subcontractor(self, sid):
        if self._subs is None:
            self._subs = {c.id: c.company_name or "" for c in self.db.query(models.DBContractor).filter(models.DBContractor.client_id == self.client_id)}
        return self._subs.get(sid, "") if sid else ""

    def store(self, sid):
        if self._stores is None:
            self._stores = {st.id: st for st in self.db.query(DBStore).filter(DBStore.client_id == self.client_id)}
        st = self._stores.get(sid)
        return st.code if st else ""


def ledger(db, f: Filters, types=None, by_project_store=True, up_to=None, since=None):
    """Ledger entries the filters reach, in posting order."""
    sts = stores(db, f, by_project=by_project_store)
    if not sts:
        return []
    query = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(list(sts)))
    ids = item_ids(db, f)
    if ids is not None:
        if not ids:
            return []
        query = query.filter(DBStoreStockLedger.item_id.in_(list(ids)))
    if types:
        query = query.filter(DBStoreStockLedger.movement_type.in_(list(types)))
    if since:
        query = query.filter(DBStoreStockLedger.txn_date >= since)
    if up_to:
        query = query.filter(DBStoreStockLedger.txn_date <= up_to)
    return query.order_by(DBStoreStockLedger.id).all()


def report(code, title, columns, rows, totals=None, notes=None, f: Filters = None) -> dict:
    cols = [{"key": k, "label": label, "align": align} for k, label, align in columns]
    return {"code": code, "title": title, "columns": cols, "rows": rows, "totals": totals or {}, "notes": notes or [],
            "filters": None if f is None else {"project_id": f.project_id, "store_id": f.store_id, "item_id": f.item_id,
                                               "category": f.category, "date_from": f.date_from.isoformat() if f.date_from else None,
                                               "date_to": f.date_to.isoformat() if f.date_to else None}}


ITEM_COLS = [("item_code", "Item code", "L"), ("item_name", "Item", "L"), ("base_uom", "Unit", "C")]


# --- stock register and valuation ----------------------------------------------------------------------------------

def stock_register(db, f: Filters) -> dict:
    """Per store and item: opening before the period, in and out during it (net of reversals, by direction of the
    movement type), closing - quantity and value."""
    names = Names(db, f.client_id)
    acc = defaultdict(lambda: {k: ZERO for k in ("oq", "ov", "iq", "iv", "xq", "xv")})
    for e in ledger(db, f, up_to=f.date_to):
        a = acc[(e.store_id, e.item_id)]
        nq, nv = net_qty(e), net_value(e)
        if f.date_from and e.txn_date < f.date_from:
            a["oq"] += nq
            a["ov"] += nv
        elif e.movement_type in IN_TYPES:
            a["iq"] += nq
            a["iv"] += nv
        else:
            a["xq"] -= nq
            a["xv"] -= nv
    rows, tot = [], defaultdict(lambda: ZERO)
    for (sid, iid), a in sorted(acc.items(), key=lambda kv: (names.store(kv[0][0]), names.item(kv[0][1])["item_name"])):
        cq, cv = a["oq"] + a["iq"] - a["xq"], a["ov"] + a["iv"] - a["xv"]
        if not any(a.values()):
            continue
        rows.append(dict(store=names.store(sid), **names.item(iid), opening_qty=s(a["oq"], _QTY), opening_value=s(a["ov"], _VALUE),
                         in_qty=s(a["iq"], _QTY), in_value=s(a["iv"], _VALUE), out_qty=s(a["xq"], _QTY), out_value=s(a["xv"], _VALUE),
                         closing_qty=s(cq, _QTY), closing_value=s(cv, _VALUE)))
        for k, v in (("opening_value", a["ov"]), ("in_value", a["iv"]), ("out_value", a["xv"]), ("closing_value", cv)):
            tot[k] += v
    return report("stock-register", "Stock register", [("store", "Store", "L")] + ITEM_COLS + [
        ("opening_qty", "Opening", "R"), ("opening_value", "Opening value", "R"), ("in_qty", "In", "R"), ("in_value", "In value", "R"),
        ("out_qty", "Out", "R"), ("out_value", "Out value", "R"), ("closing_qty", "Closing", "R"), ("closing_value", "Closing value", "R")],
        rows, {k: s(v, _VALUE) for k, v in tot.items()}, f=f)


def valuation(db, f: Filters) -> dict:
    """What each store held of each item on a date, and what it was worth (the ledger summed to that date)."""
    names = Names(db, f.client_id)
    as_on = f.date_to or date.today()
    acc = defaultdict(lambda: [ZERO, ZERO])
    for e in ledger(db, f, up_to=as_on):
        a = acc[(e.store_id, e.item_id)]
        a[0] += net_qty(e)
        a[1] += net_value(e)
    rows, total = [], ZERO
    for (sid, iid), (qty, value) in sorted(acc.items(), key=lambda kv: (names.store(kv[0][0]), names.item(kv[0][1])["item_name"])):
        if not qty and not value:
            continue
        rows.append(dict(store=names.store(sid), **names.item(iid), qty=s(qty, _QTY), avg_rate=s(value / qty, _RATE) if qty else "0.0000",
                         value=s(value, _VALUE)))
        total += value
    return report("valuation", "Stock valuation as on %s" % as_on.isoformat(), [("store", "Store", "L")] + ITEM_COLS + [
        ("qty", "Quantity", "R"), ("avg_rate", "Average rate", "R"), ("value", "Value", "R")], rows, {"value": s(total, _VALUE)}, f=f)


def item_ledger(db, f: Filters) -> dict:
    """Every movement the filters reach, with the store's position after it - the item card as a sheet."""
    names = Names(db, f.client_id)
    rows = []
    for e in ledger(db, f, up_to=f.date_to, since=f.date_from)[:20000]:
        rows.append(dict(date=e.txn_date.isoformat(), store=names.store(e.store_id), **names.item(e.item_id),
                         movement=e.movement_type + (" (reversal)" if e.reversal_of_id else ""), document="%s #%s" % (e.ref_doc_type, e.ref_doc_id),
                         qty_in=s(e.qty_in, _QTY), qty_out=s(e.qty_out, _QTY), rate=s(e.rate, _RATE), value=s(net_value(e), _VALUE),
                         balance_qty=s(e.running_qty, _QTY), balance_value=s(e.running_value, _VALUE),
                         project=names.project(e.project_id), remarks=e.remarks or ""))
    return report("item-ledger", "Item ledger", [("date", "Date", "C"), ("store", "Store", "L")] + ITEM_COLS + [
        ("movement", "Movement", "L"), ("document", "Document", "L"), ("qty_in", "In", "R"), ("qty_out", "Out", "R"), ("rate", "Rate", "R"),
        ("value", "Value", "R"), ("balance_qty", "Balance", "R"), ("balance_value", "Balance value", "R"), ("project", "Project", "L"),
        ("remarks", "Remarks", "L")], rows, f=f)


# --- registers -----------------------------------------------------------------------------------------------------

def _by_document(entries, names, sign):
    """Entries -> one row per document, store and item, netted; `sign` turns an entry into (qty, value)."""
    acc = {}
    for e in entries:
        key = (e.ref_doc_type, e.ref_doc_id, e.store_id, e.item_id, e.movement_type)
        a = acc.setdefault(key, {"date": e.txn_date, "qty": ZERO, "value": ZERO, "project_id": e.project_id, "work_order_id": e.work_order_id,
                                 "boq_item_id": e.boq_item_id, "cost_head": e.cost_head, "subcontractor_id": e.subcontractor_id, "reversed": False})
        qty, value = sign(e)
        a["qty"] += qty
        a["value"] += value
        a["reversed"] = a["reversed"] or bool(e.reversal_of_id)
    return acc


def grn_register(db, f: Filters) -> dict:
    """Receipts (GRN and client supply) and purchase returns, per document and item, net of reversals."""
    names = Names(db, f.client_id)
    entries = ledger(db, f, types=RECEIPTS, up_to=f.date_to, since=f.date_from)
    rows, total = [], ZERO
    for (doc, did, sid, iid, mtype), a in sorted(_by_document(entries, names, lambda e: (net_qty(e), net_value(e))).items(),
                                                 key=lambda kv: (kv[1]["date"], kv[0][1])):
        rows.append(dict(date=a["date"].isoformat(), document="%s #%s" % (doc, did), kind=mtype, store=names.store(sid), **names.item(iid),
                         qty=s(a["qty"], _QTY), value=s(a["value"], _VALUE), status="Cancelled" if a["reversed"] and not a["qty"] else "",
                         project=names.project(a["project_id"])))
        total += a["value"]
    return report("grn-register", "GRN register", [("date", "Date", "C"), ("document", "Document", "L"), ("kind", "Movement", "L"),
                                                   ("store", "Store", "L")] + ITEM_COLS + [("qty", "Quantity", "R"), ("value", "Value", "R"),
                                                                                           ("status", "Status", "L"), ("project", "Project", "L")],
                  rows, {"value": s(total, _VALUE)}, f=f)


def issue_register(db, f: Filters) -> dict:
    """Issues to site and subcontractors and their returns, per document and item (returns negative)."""
    names = Names(db, f.client_id)
    entries = ledger(db, f, types=ISSUES | RETURNS, up_to=f.date_to, since=f.date_from)
    rows, total = [], ZERO
    for (doc, did, sid, iid, mtype), a in sorted(_by_document(entries, names, consumed).items(), key=lambda kv: (kv[1]["date"], kv[0][1])):
        rows.append(dict(date=a["date"].isoformat(), document="%s #%s" % (doc, did), kind=mtype, store=names.store(sid), **names.item(iid),
                         qty=s(a["qty"], _QTY), value=s(a["value"], _VALUE), project=names.project(a["project_id"]),
                         work_order=names.work_order(a["work_order_id"]), boq_item=names.boq(a["boq_item_id"]), cost_head=a["cost_head"] or "",
                         subcontractor=names.subcontractor(a["subcontractor_id"]), status="Cancelled" if a["reversed"] and not a["qty"] else ""))
        total += a["value"]
    return report("issue-register", "Issue register", [("date", "Date", "C"), ("document", "Document", "L"), ("kind", "Movement", "L"),
                                                       ("store", "Store", "L")] + ITEM_COLS + [
        ("qty", "Quantity", "R"), ("value", "Value", "R"), ("project", "Project", "L"), ("work_order", "Work order", "L"),
        ("boq_item", "BOQ item", "L"), ("cost_head", "Cost head", "L"), ("subcontractor", "Subcontractor", "L"), ("status", "Status", "L")],
        rows, {"value": s(total, _VALUE)}, f=f)


# --- consumption ---------------------------------------------------------------------------------------------------

GROUPS = {"work_order": ("work_order_id", "Work order"), "boq_item": ("boq_item_id", "BOQ item"), "cost_head": ("cost_head", "Cost head"),
          "subcontractor": ("subcontractor_id", "Subcontractor")}


def consumption_entries(db, f: Filters):
    """Consumption movements charged to a project (the entry's project, wherever the store), in the period."""
    entries = ledger(db, f, types=CONSUMPTION, by_project_store=False, up_to=f.date_to, since=f.date_from)
    return [e for e in entries if not f.project_id or e.project_id == f.project_id]


def consumption(db, f: Filters, group: str = "work_order") -> dict:
    """Material consumed by project, by work order / BOQ item / cost head / subcontractor, and item: issues net of
    returns, plus wastage, scrap and count or transit losses."""
    if group not in GROUPS:
        group = "work_order"
    col, label = GROUPS[group]
    names = Names(db, f.client_id)
    acc = defaultdict(lambda: [ZERO, ZERO])
    for e in consumption_entries(db, f):
        a = acc[(e.project_id, getattr(e, col), e.item_id)]
        qty, value = consumed(e)
        a[0] += qty
        a[1] += value
    show = {"work_order_id": names.work_order, "boq_item_id": names.boq, "cost_head": lambda v: v or "",
            "subcontractor_id": names.subcontractor}[col]
    rows, total = [], ZERO
    for (pid, key, iid), (qty, value) in sorted(acc.items(), key=lambda kv: (names.project(kv[0][0]), str(show(kv[0][1])), names.item(kv[0][2])["item_name"])):
        if not qty and not value:
            continue
        rows.append(dict(project=names.project(pid) or "(no project)", group=show(key) or "-", **names.item(iid), qty=s(qty, _QTY),
                         value=s(value, _VALUE)))
        total += value
    return report("consumption", "Material consumption by %s" % label.lower(), [("project", "Project", "L"), ("group", label, "L")] + ITEM_COLS + [
        ("qty", "Consumed", "R"), ("value", "Value", "R")], rows, {"value": s(total, _VALUE)}, f=f)


# --- ageing and slow movers ----------------------------------------------------------------------------------------

def ageing(db, f: Filters, days: int = 90) -> dict:
    """What is held, how old it is (oldest stock assumed used first) and when anything last went out. Non-moving =
    no OUT movement in `days` days (90 / 180 / 365)."""
    names = Names(db, f.client_id)
    today = f.date_to or date.today()
    per = defaultdict(list)
    for e in ledger(db, f, up_to=today):
        per[(e.store_id, e.item_id)].append(e)
    rows, total, slow_value = [], ZERO, ZERO
    for (sid, iid), entries in sorted(per.items(), key=lambda kv: (names.store(kv[0][0]), names.item(kv[0][1])["item_name"])):
        qty = sum((net_qty(e) for e in entries), ZERO)
        value = sum((net_value(e) for e in entries), ZERO)
        if qty <= 0:
            continue
        outs = [e.txn_date for e in entries if e.movement_type in OUT_TYPES and D(e.qty_out) > 0 and not e.reversal_of_id]
        last_out = max(outs) if outs else None
        first_in = min(e.txn_date for e in entries)
        idle = (today - (last_out or first_in)).days
        # Age the quantity held against the receipts that brought it, newest first.
        buckets, left = {"0_90": ZERO, "91_180": ZERO, "181_365": ZERO, "over_365": ZERO}, qty
        for e in sorted((e for e in entries if e.movement_type in IN_TYPES and D(e.qty_in) > 0 and not e.reversal_of_id),
                        key=lambda e: (e.txn_date, e.id), reverse=True):
            if left <= 0:
                break
            take = min(left, D(e.qty_in))
            age = (today - e.txn_date).days
            buckets["0_90" if age <= 90 else "91_180" if age <= 180 else "181_365" if age <= 365 else "over_365"] += take
            left -= take
        if left > 0:
            buckets["over_365"] += left
        rate = value / qty
        moving = "Non-moving" if idle >= days else ""
        rows.append(dict(store=names.store(sid), **names.item(iid), qty=s(qty, _QTY), value=s(value, _VALUE),
                         last_out=last_out.isoformat() if last_out else "never", days_idle=idle, status=moving,
                         **{"age_" + k: s(v * rate, _VALUE) for k, v in buckets.items()}))
        total += value
        if moving:
            slow_value += value
    return report("ageing", "Ageing and non-moving stock (no issue in %d days)" % days, [("store", "Store", "L")] + ITEM_COLS + [
        ("qty", "Held", "R"), ("value", "Value", "R"), ("age_0_90", "0-90 days", "R"), ("age_91_180", "91-180", "R"),
        ("age_181_365", "181-365", "R"), ("age_over_365", "Over 365", "R"), ("last_out", "Last issued", "C"), ("days_idle", "Days idle", "R"),
        ("status", "Status", "L")], rows, {"value": s(total, _VALUE), "non_moving_value": s(slow_value, _VALUE)}, f=f)


# --- subcontractor material account --------------------------------------------------------------------------------

def recovered_by_subcontractor(db, client_id, kind=None) -> dict:
    query = db.query(DBStoreSubconRecovery).filter(DBStoreSubconRecovery.client_id == client_id)
    if kind:
        query = query.filter(DBStoreSubconRecovery.kind == kind)
    out = defaultdict(lambda: ZERO)
    for r in query.all():
        bill = db.get(models.DBSubBill, r.sub_bill_id)
        if bill is None or (bill.status or "") == "CANCELLED":
            continue
        out[r.subcontractor_id] += D(r.amount)
    return out


def subcontractor_account(db, f: Filters, subcontractor_id: int = 0) -> dict:
    """Per subcontractor: material issued and returned (the ledger), what is recoverable (P3's issue records, net of
    returns, at the recovery rate) and what has been recovered on their bills."""
    from app.services import store_outward
    names = Names(db, f.client_id)
    acc = defaultdict(lambda: {"iq": ZERO, "iv": ZERO, "rq": ZERO, "rv": ZERO})
    for e in ledger(db, f, types={M.SUBCON_ISSUE_OUT.value, M.SUBCON_RETURN_IN.value}, by_project_store=False, up_to=f.date_to):
        if not e.subcontractor_id or (subcontractor_id and e.subcontractor_id != subcontractor_id):
            continue
        if f.project_id and e.project_id != f.project_id:
            continue
        a = acc[e.subcontractor_id]
        qty, value = consumed(e)
        if e.movement_type == M.SUBCON_ISSUE_OUT.value:
            a["iq"] += qty
            a["iv"] += value
        else:
            a["rq"] -= qty
            a["rv"] -= value
    recovered = recovered_by_subcontractor(db, f.client_id)
    upto = f.date_to or date.today()
    rows, tot = [], defaultdict(lambda: ZERO)
    for sid in sorted(set(acc) | {k for k in recovered if k and (not subcontractor_id or k == subcontractor_id)}, key=names.subcontractor):
        a = acc[sid]
        lines = store_outward.get_subcon_issues(db, sid, upto) or []
        recoverable = sum((D(l.recovery_value) for l in lines if l.chargeable), ZERO)
        got = recovered.get(sid, ZERO)
        row = dict(subcontractor=names.subcontractor(sid), issued_value=s(a["iv"], _VALUE), returned_value=s(a["rv"], _VALUE),
                   net_value=s(a["iv"] - a["rv"], _VALUE), recoverable=s(recoverable, _VALUE), recovered=s(got, _VALUE),
                   balance=s(recoverable - got, _VALUE))
        rows.append(row)
        for k in ("issued_value", "returned_value", "net_value", "recoverable", "recovered", "balance"):
            tot[k] += D(row[k])
    return report("subcontractor-account", "Subcontractor material account", [
        ("subcontractor", "Subcontractor", "L"), ("issued_value", "Issued (cost)", "R"), ("returned_value", "Returned (cost)", "R"),
        ("net_value", "Net issued", "R"), ("recoverable", "Recoverable", "R"), ("recovered", "Recovered", "R"), ("balance", "Still to recover", "R")],
        rows, {k: s(v, _VALUE) for k, v in tot.items()},
        notes=["Recoverable comes from the outward slice's subcontractor issue records (chargeable lines at their recovery rate)."], f=f)


# --- transfers, counts, scrap --------------------------------------------------------------------------------------

def transfers(db, f: Filters) -> dict:
    """Transfers between stores from the ledger - sent, received, still on the road - flagged when they cross
    projects, followed by what the control slice reports in transit."""
    from app.services import store_control
    names = Names(db, f.client_id)
    entries = ledger(db, f, types={M.TRANSFER_OUT.value, M.TRANSFER_IN.value}, by_project_store=False, up_to=f.date_to, since=f.date_from)
    st = {x.id: x for x in db.query(DBStore).filter(DBStore.client_id == f.client_id)}
    acc = {}
    for e in entries:
        a = acc.setdefault((e.ref_doc_id, e.item_id), {"date": e.txn_date, "from": None, "to": None, "out_q": ZERO, "out_v": ZERO, "in_q": ZERO, "in_v": ZERO})
        if e.movement_type == M.TRANSFER_OUT.value:
            a["from"] = e.store_id
            a["out_q"] -= net_qty(e)
            a["out_v"] -= net_value(e)
        else:
            a["to"] = e.store_id
            a["in_q"] += net_qty(e)
            a["in_v"] += net_value(e)
    rows, tot = [], defaultdict(lambda: ZERO)
    for (did, iid), a in sorted(acc.items(), key=lambda kv: (kv[1]["date"], kv[0][0])):
        if f.project_id and f.project_id not in {getattr(st.get(a["from"]), "project_id", None), getattr(st.get(a["to"]), "project_id", None)}:
            continue
        pf, pt = getattr(st.get(a["from"]), "project_id", None), getattr(st.get(a["to"]), "project_id", None)
        transit = a["out_q"] - a["in_q"]
        rows.append(dict(date=a["date"].isoformat(), document="TRANSFER #%s" % did, from_store=names.store(a["from"]), to_store=names.store(a["to"]),
                         **names.item(iid), sent=s(a["out_q"], _QTY), received=s(a["in_q"], _QTY), in_transit=s(transit, _QTY),
                         value=s(a["out_v"], _VALUE), inter_project="Yes" if a["from"] and a["to"] and pf != pt else ""))
        tot["value"] += a["out_v"]
        if transit > 0:
            tot["in_transit_value"] += a["out_v"] * transit / a["out_q"] if a["out_q"] else ZERO
    notes = []
    for t in store_control.get_in_transit(db, f.project_id or None) or []:
        notes.append("In transit (control): transfer %s, %s %s of item %s from %s to %s since %s%s" % (
            t.transfer_id, t.qty, names.item(t.item_id)["base_uom"], names.item(t.item_id)["item_code"], names.store(t.from_store_id),
            names.store(t.to_store_id), t.dispatched_on, " (inter-project)" if t.inter_project else ""))
    return report("transfers", "Transfers and in transit", [("date", "Date", "C"), ("document", "Document", "L"), ("from_store", "From", "L"),
                                                            ("to_store", "To", "L")] + ITEM_COLS + [
        ("sent", "Sent", "R"), ("received", "Received", "R"), ("in_transit", "In transit", "R"), ("value", "Value", "R"),
        ("inter_project", "Inter-project", "C")], rows, {k: s(v, _VALUE) for k, v in tot.items()}, notes, f=f)


def count_and_scrap(db, f: Filters) -> dict:
    """Stock count variances (from the control slice, with the adjustments the ledger holds for counts) and scrap
    sold or written off against its book value."""
    from app.services import store_control
    names = Names(db, f.client_id)
    rows, tot = [], defaultdict(lambda: ZERO)
    frm, to = f.date_from or date(2000, 1, 1), f.date_to or date.today()
    for sid in stores(db, f):
        for v in store_control.get_count_variances(db, sid, frm, to) or []:
            if f.item_id and v.item_id != f.item_id:
                continue
            rows.append(dict(kind="Count variance", reference="COUNT #%s" % v.count_id, store=names.store(sid), **names.item(v.item_id),
                             system_qty=s(v.system_qty, _QTY), actual_qty=s(v.counted_qty, _QTY), variance_qty=s(v.variance_qty, _QTY),
                             book_value=s(v.variance_value, _VALUE), realised="", gain_loss=s(v.variance_value, _VALUE)))
            tot["variance_value"] += D(v.variance_value)
    projects = {f.project_id} if f.project_id else {x.project_id for x in stores(db, f).values() if x.project_id}
    for pid in sorted(p for p in projects if p):
        for sc in store_control.get_scrap_realisation(db, pid, frm, to) or []:
            if f.item_id and sc.item_id != f.item_id:
                continue
            gain = D(sc.realised_value) - D(sc.book_value)
            rows.append(dict(kind="Scrap", reference="SCRAP #%s" % sc.scrap_doc_id, store=names.project(pid), **names.item(sc.item_id),
                             system_qty="", actual_qty=s(sc.qty, _QTY), variance_qty="", book_value=s(sc.book_value, _VALUE),
                             realised=s(sc.realised_value, _VALUE), gain_loss=s(gain, _VALUE)))
            tot["scrap_book"] += D(sc.book_value)
            tot["scrap_realised"] += D(sc.realised_value)
    adj = defaultdict(lambda: ZERO)
    for e in ledger(db, f, types={M.ADJUST_IN.value, M.ADJUST_OUT.value}, up_to=to, since=frm):
        if e.ref_doc_type == "COUNT":
            adj[e.ref_doc_id] += net_value(e)
    notes = ["Adjustments posted for count %s: %s" % (k, s(v, _VALUE)) for k, v in sorted(adj.items())]
    return report("count-scrap", "Count variances and scrap realisation", [("kind", "What", "L"), ("reference", "Reference", "L"),
                                                                          ("store", "Store / project", "L")] + ITEM_COLS + [
        ("system_qty", "Book qty", "R"), ("actual_qty", "Counted / scrapped", "R"), ("variance_qty", "Variance", "R"), ("book_value", "Book value", "R"),
        ("realised", "Realised", "R"), ("gain_loss", "Gain / (loss)", "R")], rows, {k: s(v, _VALUE) for k, v in tot.items()}, notes, f=f)


REPORTS = {
    "stock-register": ("Stock register", stock_register), "valuation": ("Stock valuation", valuation),
    "item-ledger": ("Item ledger", item_ledger), "grn-register": ("GRN register", grn_register),
    "issue-register": ("Issue register", issue_register), "consumption": ("Material consumption", consumption),
    "ageing": ("Ageing and non-moving", ageing), "subcontractor-account": ("Subcontractor material account", subcontractor_account),
    "transfers": ("Transfers and in transit", transfers), "count-scrap": ("Count variance and scrap", count_and_scrap),
}


# --- consumption norms ---------------------------------------------------------------------------------------------

def norms_for(db, client_id, work_item_code=None, item_id=None, boq_item_id=None, active=True):
    query = db.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.client_id == client_id)
    if active:
        query = query.filter(DBStoreConsumptionNorm.is_active.is_(True))
    if work_item_code is not None:
        query = query.filter(DBStoreConsumptionNorm.work_item_code == work_item_code)
    if item_id:
        query = query.filter(DBStoreConsumptionNorm.item_id == item_id)
    if boq_item_id:
        query = query.filter(DBStoreConsumptionNorm.boq_item_id == boq_item_id)
    return query.order_by(DBStoreConsumptionNorm.id).all()


def _norm_for_boq(db, boq, item_id):
    """The norm for a BOQ line and item: one pinned to the line first, else the one for its work-item code."""
    client_id = db.query(models.DBBoq.client_id).filter(models.DBBoq.id == boq.boq_id).scalar()
    pinned = db.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.client_id == client_id, DBStoreConsumptionNorm.boq_item_id == boq.id,
                                                     DBStoreConsumptionNorm.item_id == item_id, DBStoreConsumptionNorm.is_active.is_(True)).first()
    if pinned or not (boq.item_code or "").strip():
        return pinned
    return db.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.client_id == client_id, DBStoreConsumptionNorm.boq_item_id.is_(None),
                                                   DBStoreConsumptionNorm.work_item_code == boq.item_code.strip(), DBStoreConsumptionNorm.item_id == item_id,
                                                   DBStoreConsumptionNorm.is_active.is_(True)).first()


def get_theoretical_requirement(db, boq_item_id, item_id) -> Optional[Decimal]:
    """What the BOQ item should consume of an item by its quantity and norms; None when there is no norm.

    The BOQ line's quantity x the norm's coefficient, in the item's base unit, without the permissible wastage (the
    norm's wastage_pct is the allowance on top). A norm pinned to the BOQ line wins over one for its work-item code."""
    boq = db.get(models.DBBoqLine, boq_item_id) if boq_item_id else None
    if boq is None or not item_id:
        return None
    norm = _norm_for_boq(db, boq, item_id)
    if norm is None:
        return None
    return q(D(str(boq.quantity or 0)) * D(norm.coefficient), _QTY)


# --- reconciliation ------------------------------------------------------------------------------------------------

def executed_quantities(db, client_id, scope, scope_id, codes, upto, project_id=None) -> dict:
    """{work_item_code: quantity executed} from the measurement books, read only: the client work orders' book for a
    project or work order, the subcontract orders' book for a subcontractor."""
    out = defaultdict(lambda: ZERO)
    if not codes:
        return out
    stamp = upto.isoformat() if upto else "9999-12-31"
    if scope == "subcontractor":
        query = (db.query(models.DBSubcontractItem.item_code, models.DBSubMeasurement.quantity, models.DBSubMeasurement.multiplier,
                          models.DBSubMeasurement.measured_on)
                 .join(models.DBSubMeasurement, models.DBSubMeasurement.item_id == models.DBSubcontractItem.id)
                 .join(models.DBSubcontractOrder, models.DBSubcontractOrder.id == models.DBSubMeasurement.order_id)
                 .filter(models.DBSubcontractOrder.client_id == client_id, models.DBSubcontractOrder.contractor_id == scope_id,
                         models.DBSubcontractItem.item_code.in_(list(codes)),
                         (models.DBSubMeasurement.kind == "") | models.DBSubMeasurement.kind.is_(None)))
        if project_id:
            query = query.filter(models.DBSubcontractOrder.job_id == project_id)
        for code, qty, mult, on in query.all():
            if (on or "")[:10] <= stamp:
                out[code] += D(str(qty or 0)) * D(str(mult or 1))
        return out
    query = (db.query(models.DBMeasurement.fg_code, models.DBMeasurement.quantity, models.DBMeasurement.measured_on)
             .join(models.DBWorkOrder, models.DBWorkOrder.id == models.DBMeasurement.work_order_id)
             .filter(models.DBWorkOrder.client_id == client_id, models.DBMeasurement.fg_code.in_(list(codes))))
    if scope == "work_order":
        query = query.filter(models.DBMeasurement.work_order_id == scope_id)
    else:
        query = query.filter(models.DBWorkOrder.job_id == scope_id)
    for code, qty, on in query.all():
        if (on or "")[:10] <= stamp:
            out[code] += D(str(qty or 0))
    return out


def net_issued(db, client_id, scope, scope_id, item_ids_, upto, project_id=None) -> dict:
    """{item_id: (qty, value)} issued net of returns (and reversals) to the project / work order / subcontractor."""
    store_ids = [x for (x,) in db.query(DBStore.id).filter(DBStore.client_id == client_id).all()]
    out = defaultdict(lambda: [ZERO, ZERO])
    if not store_ids or not item_ids_:
        return out
    query = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(store_ids), DBStoreStockLedger.item_id.in_(list(item_ids_)),
                                                DBStoreStockLedger.movement_type.in_(list(ISSUES | RETURNS)))
    col = {"project": DBStoreStockLedger.project_id, "work_order": DBStoreStockLedger.work_order_id,
           "subcontractor": DBStoreStockLedger.subcontractor_id}[scope]
    query = query.filter(col == scope_id)
    if project_id and scope != "project":
        query = query.filter(DBStoreStockLedger.project_id == project_id)
    if upto:
        query = query.filter(DBStoreStockLedger.txn_date <= upto)
    for e in query.all():
        qty, value = consumed(e)
        out[e.item_id][0] += qty
        out[e.item_id][1] += value
    return out


def reconciliation(db, client_id, scope, scope_id, upto=None, project_id=None, item_ids_=None, category="") -> dict:
    """Theoretical (executed work x norm) against actual (issued net of returns), per material, with the permissible
    wastage. For a subcontractor, what is used beyond the allowance is recoverable at the norm's penal rate (or the
    average issue rate when the norm has none)."""
    if scope not in ("project", "work_order", "subcontractor"):
        raise ValueError("scope is project, work_order or subcontractor")
    norms = norms_for(db, client_id)
    if item_ids_:
        norms = [n for n in norms if n.item_id in item_ids_]
    if category:
        cat = {r for (r,) in db.query(DBStoreItemSettings.item_id).filter(DBStoreItemSettings.category == category.upper())}
        norms = [n for n in norms if n.item_id in cat]
    executed = executed_quantities(db, client_id, scope, scope_id, {n.work_item_code for n in norms}, upto, project_id)
    names = Names(db, client_id)
    per_item = defaultdict(lambda: {"theoretical": ZERO, "allowance": ZERO, "penal": None, "work": []})
    for n in norms:
        done = executed.get(n.work_item_code, ZERO)
        theo = done * D(n.coefficient)
        a = per_item[n.item_id]
        a["theoretical"] += theo
        a["allowance"] += theo * D(n.wastage_pct) / 100
        if n.penal_rate is not None:
            a["penal"] = max(a["penal"] or ZERO, D(n.penal_rate))
        if done:
            a["work"].append("%s: %s %s x %s" % (n.work_item_code, plain(done), n.work_uom or "", plain(n.coefficient)))
    actual = net_issued(db, client_id, scope, scope_id, set(per_item), upto, project_id)
    rows, tot = [], defaultdict(lambda: ZERO)
    for iid, a in sorted(per_item.items(), key=lambda kv: names.item(kv[0])["item_name"]):
        aq, av = actual.get(iid, [ZERO, ZERO])
        permitted = a["theoretical"] + a["allowance"]
        variance = aq - a["theoretical"]
        excess = max(aq - permitted, ZERO)
        avg = (av / aq) if aq else ZERO
        rate = a["penal"] if a["penal"] is not None else avg
        recoverable = q(excess * rate, _VALUE) if scope == "subcontractor" else ZERO
        rows.append(dict(**names.item(iid), executed="; ".join(a["work"]), theoretical=s(a["theoretical"], _QTY), allowance=s(a["allowance"], _QTY),
                         permitted=s(permitted, _QTY), actual=s(aq, _QTY), variance=s(variance, _QTY),
                         variance_pct=s(variance / a["theoretical"] * 100, D("0.01")) if a["theoretical"] else "",
                         excess=s(excess, _QTY), excess_value=s(excess * avg, _VALUE), penal_rate=s(rate, _RATE),
                         recoverable=s(recoverable, _VALUE), status="Over allowance" if excess > 0 else ("Within" if aq else "Not issued")))
        tot["recoverable"] += recoverable
        tot["excess_value"] += excess * avg
    title = {"project": "project %s" % names.project(scope_id), "work_order": "work order %s" % names.work_order(scope_id),
             "subcontractor": "subcontractor %s" % names.subcontractor(scope_id)}[scope]
    return report("reconciliation", "Material reconciliation - %s" % title, ITEM_COLS + [
        ("executed", "Work executed", "L"), ("theoretical", "Theoretical", "R"), ("allowance", "Wastage allowed", "R"), ("permitted", "Permitted", "R"),
        ("actual", "Actual (net issued)", "R"), ("variance", "Variance", "R"), ("variance_pct", "Variance %", "R"), ("excess", "Beyond allowance", "R"),
        ("penal_rate", "Penal rate", "R"), ("recoverable", "Recoverable", "R"), ("status", "Status", "L")],
        rows, {k: s(v, _VALUE) for k, v in tot.items()},
        notes=["Theoretical = quantity executed in the measurement book x the norm's coefficient; actual = issued less returns."])


def client_supply_reconciliation(db, client_id, project_id=0, work_order_id=0, upto=None) -> dict:
    """Material the client supplied: received, issued into the work (net), the theoretical consumption by the norms,
    and what is left at site - with the value to recover in the client's RA bill at the receipt's agreed rate."""
    names = Names(db, client_id)
    store_ids = [x for (x,) in db.query(DBStore.id).filter(DBStore.client_id == client_id).all()]
    rec = defaultdict(lambda: [ZERO, ZERO])
    if store_ids:
        query = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(store_ids),
                                                    DBStoreStockLedger.movement_type == M.CLIENT_SUPPLY_IN.value)
        if work_order_id:
            query = query.filter(DBStoreStockLedger.work_order_id == work_order_id)
        elif project_id:
            query = query.filter(DBStoreStockLedger.project_id == project_id)
        if upto:
            query = query.filter(DBStoreStockLedger.txn_date <= upto)
        for e in query.all():
            rec[e.item_id][0] += net_qty(e)
            rec[e.item_id][1] += net_value(e)
    scope, sid = ("work_order", work_order_id) if work_order_id else ("project", project_id)
    issued = net_issued(db, client_id, scope, sid, set(rec), upto)
    theo = {}
    norms = [n for n in norms_for(db, client_id) if n.item_id in rec]
    if norms and sid:
        done = executed_quantities(db, client_id, scope, sid, {n.work_item_code for n in norms}, upto)
        for n in norms:
            theo[n.item_id] = theo.get(n.item_id, ZERO) + done.get(n.work_item_code, ZERO) * D(n.coefficient)
    rows, tot = [], defaultdict(lambda: ZERO)
    for iid, (rq, rv) in sorted(rec.items(), key=lambda kv: names.item(kv[0])["item_name"]):
        rate = rv / rq if rq else ZERO
        iq = min(issued.get(iid, [ZERO, ZERO])[0], rq)        # issues beyond what the client sent came from bought stock
        balance = rq - iq
        rows.append(dict(**names.item(iid), received=s(rq, _QTY), agreed_rate=s(rate, _RATE), consumed=s(iq, _QTY),
                         theoretical=s(theo.get(iid, ZERO), _QTY) if iid in theo else "", balance_at_site=s(balance, _QTY),
                         balance_value=s(balance * rate, _VALUE), recovery_value=s(iq * rate, _VALUE)))
        tot["recovery_value"] += iq * rate
        tot["balance_value"] += balance * rate
    return report("client-supply", "Client-supplied material", ITEM_COLS + [
        ("received", "Received", "R"), ("agreed_rate", "Agreed rate", "R"), ("consumed", "Consumed (net issued)", "R"), ("theoretical", "By norms", "R"),
        ("balance_at_site", "Balance at site", "R"), ("balance_value", "Balance value", "R"), ("recovery_value", "To recover", "R")],
        rows, {k: s(v, _VALUE) for k, v in tot.items()},
        notes=["Consumed is issues net of returns, never more than was received; the rest of an issue came from bought stock."])


# --- dashboard -----------------------------------------------------------------------------------------------------

def dashboard(db, client_id, store_ids=None) -> dict:
    """The figures the Store front page shows. Each comes from where it lives; one a slice does not publish yet is None."""
    from app.services import store_control, store_outward
    sts = {st.id: st for st in db.query(DBStore).filter(DBStore.client_id == client_id, DBStore.is_active.is_(True)).all()
           if store_ids is None or st.id in store_ids}
    by_store = []
    below = 0
    for st in sorted(sts.values(), key=lambda x: x.code):
        bal = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == st.id).all()
        by_store.append({"store_id": st.id, "code": st.code, "name": st.name, "value": s(sum((D(b.value) for b in bal), ZERO), _VALUE),
                         "items": sum(1 for b in bal if D(b.qty) > 0)})
        settings = {c.item_id: c for c in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_([b.item_id for b in bal]))} if bal else {}
        below += sum(1 for b in bal if b.item_id in settings and D(settings[b.item_id].reorder_level or 0) > 0
                     and D(b.qty) < D(settings[b.item_id].reorder_level))
    in_transit = [t for t in (store_control.get_in_transit(db, None) or []) if t.from_store_id in sts or t.to_store_id in sts]
    overdue = [r for sid in sts for r in (store_outward.get_outstanding_returnables(db, store_id=sid) or []) if r.overdue_days > 0]
    frozen = [{"store_id": f.store_id, "code": sts[f.store_id].code, "reason": f.reason or "", "since": f.frozen_at.isoformat(timespec="minutes")}
              for f in db.query(DBStoreFreeze).filter(DBStoreFreeze.store_id.in_(list(sts) or [-1]), DBStoreFreeze.unfrozen_at.is_(None)).all()]
    from app.services import store_integration
    return {"stock_value": s(sum((D(x["value"]) for x in by_store), ZERO), _VALUE), "by_store": by_store,
            "pending_indents": store_integration.pending_indents(db, client_id),
            "grns_pending_qc": store_integration.grns_pending_qc(db, client_id),
            "in_transit": {"lines": len(in_transit), "value": s(sum((D(t.value) for t in in_transit), ZERO), _VALUE)},
            "below_reorder": below, "overdue_returnables": len(overdue), "frozen_stores": frozen}
