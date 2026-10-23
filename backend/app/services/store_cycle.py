"""Store module - cycle counting: items ranked A, B or C by what they are worth to the company, the items now due for counting at each class's
own interval, and a blind second count for any line whose first count was far from the books. Nothing here moves stock; a recount only decides
what number the count document adjusts the books to."""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import case, func

from app import models
from app.models.store_core import DBStore, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DocStatus, MovementType
from app.models.store_control import DBStoreCount, DBStoreCountLine
from app.models.store_extras import DBStoreCountRecount, DBStoreCycleSetting
from app.services.stock_ledger import convert_to_base

ZERO = Decimal("0")
USE_MOVEMENTS = (MovementType.ISSUE_OUT.value, MovementType.SUBCON_ISSUE_OUT.value, MovementType.WASTAGE_OUT.value, MovementType.SCRAP_OUT.value)
A_SHARE, B_SHARE = Decimal("80"), Decimal("95")        # cumulative percent of value: the top 80 is A, the next 15 is B, the rest C


def _q(x, step="0.001"):
    return Decimal(str(x)).quantize(Decimal(step), rounding=ROUND_HALF_UP)


def _num(raw, what, *, high=Decimal("999999999")):
    try:
        d = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "%s is not a number." % what) from None
    if not d.is_finite() or d < 0 or d > high:
        raise HTTPException(400, "%s must be zero or more." % what)
    return d


def settings_of(db, client_id) -> DBStoreCycleSetting:
    row = db.query(DBStoreCycleSetting).filter(DBStoreCycleSetting.client_id == client_id).first()
    if row is None:
        row = DBStoreCycleSetting(client_id=client_id, days_a=30, days_b=90, days_c=180, recount_value=25000, recount_pct=20, recount_min_value=1000)
        db.add(row)
        db.flush()
    return row


def settings_dict(row):
    return {"days_a": row.days_a, "days_b": row.days_b, "days_c": row.days_c, "recount_value": str(_q(row.recount_value, "0.01")), "recount_pct": str(_q(row.recount_pct, "0.01")),
            "recount_min_value": str(_q(row.recount_min_value, "0.01"))}


def save_settings(db, client_id, body):
    row = settings_of(db, client_id)
    for name in ("days_a", "days_b", "days_c"):
        raw = getattr(body, name)
        if raw is not None:
            d = _num(raw, name.replace("_", " "), high=Decimal("3650"))
            if d < 1 or d != d.to_integral_value():
                raise HTTPException(400, "A counting interval is a whole number of days, at least 1.")
            setattr(row, name, int(d))
    if not (row.days_a <= row.days_b <= row.days_c):
        raise HTTPException(400, "Class A is counted at least as often as B, and B as often as C.")
    if body.recount_value is not None:
        row.recount_value = _num(body.recount_value, "Recount value")
    if body.recount_pct is not None:
        row.recount_pct = _num(body.recount_pct, "Recount percent", high=Decimal("100000"))
    if body.recount_min_value is not None:
        row.recount_min_value = _num(body.recount_min_value, "Smallest value for a percent recount")
    db.flush()
    return row


# --- ABC and what is due -------------------------------------------------------------------------------------------------

def abc(db, client_id, store_ids, today=None):
    """Items ranked by the value they were used for over the last year (issues, wastage and scrap, net of reversals), or by the stock held when
    nothing was used. A is the top 80 percent of the value, B the next 15, C the rest - and anything unused is C."""
    today = today or date.today()
    stores = [s for s in store_ids] if store_ids is not None else [i for (i,) in db.query(DBStore.id).filter(DBStore.client_id == client_id).all()]
    if not stores:
        return []
    signed = case((DBStoreStockLedger.qty_out > 0, DBStoreStockLedger.value), else_=-DBStoreStockLedger.value)
    used = {i: Decimal(str(v or 0)) for i, v in db.query(DBStoreStockLedger.item_id, func.sum(signed)).filter(
        DBStoreStockLedger.store_id.in_(stores), DBStoreStockLedger.movement_type.in_(USE_MOVEMENTS), DBStoreStockLedger.txn_date > today - timedelta(days=365)).group_by(DBStoreStockLedger.item_id).all()}
    held = {i: (Decimal(str(q or 0)), Decimal(str(v or 0))) for i, q, v in db.query(DBStoreStockBalance.item_id, func.sum(DBStoreStockBalance.qty), func.sum(DBStoreStockBalance.value)).filter(
        DBStoreStockBalance.store_id.in_(stores)).group_by(DBStoreStockBalance.item_id).all()}
    ids = set(held) | set(used)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(ids) or [0])).all()}
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(list(ids) or [0])).all()}
    basis = "use" if sum((v for v in used.values() if v > 0), ZERO) > 0 else "stock"
    rank = {i: (used.get(i, ZERO) if basis == "use" else held.get(i, (ZERO, ZERO))[1]) for i in ids}
    total = sum((v for v in rank.values() if v > 0), ZERO)
    rows, running = [], ZERO
    for i in sorted(ids, key=lambda k: (-rank[k], items[k].item_name if k in items else "")):
        if i not in items:
            continue
        v = max(ZERO, rank[i])
        before = (running * 100 / total) if total > 0 else Decimal(100)      # the share of the value ranked above this item
        running += v
        after = (running * 100 / total) if total > 0 else Decimal(100)
        cls = "C" if v <= 0 else ("A" if before < A_SHARE else ("B" if before < B_SHARE else "C"))
        rows.append({"item_id": i, "item_code": items[i].item_code, "item_name": items[i].item_name, "base_uom": (sets[i].base_uom if i in sets else items[i].units_of_measure) or "",
                     "class": cls, "basis": basis, "annual_use_value": format(_q(used.get(i, ZERO), "0.01"), "f"), "stock_qty": format(_q(held.get(i, (ZERO, ZERO))[0]), "f"),
                     "stock_value": format(_q(held.get(i, (ZERO, ZERO))[1], "0.01"), "f"), "cumulative_pct": format(_q(min(after, Decimal(100)), "0.1"), "f")})
    return rows


def due_for_counting(db, client_id, store_ids, today=None):
    """Every item held in the stores with its class, when it was last counted there, and whether its class's interval has run out (never counted is due)."""
    today = today or date.today()
    cfg = settings_of(db, client_id)
    days = {"A": cfg.days_a, "B": cfg.days_b, "C": cfg.days_c}
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.client_id == client_id, DBStore.is_active.is_(True)).all() if store_ids is None or s.id in store_ids}
    if not stores:
        return []
    cls = {r["item_id"]: r["class"] for r in abc(db, client_id, list(stores), today)}
    last = {(s, i): d for s, i, d in db.query(DBStoreCount.store_id, DBStoreCountLine.item_id, func.max(DBStoreCount.count_date)).join(DBStoreCountLine, DBStoreCountLine.count_id == DBStoreCount.id).filter(
        DBStoreCount.store_id.in_(list(stores)), DBStoreCount.status == DocStatus.POSTED.value, DBStoreCountLine.counted_qty.isnot(None)).group_by(DBStoreCount.store_id, DBStoreCountLine.item_id).all()}
    bals = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id.in_(list(stores)), DBStoreStockBalance.qty > 0).all()
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([b.item_id for b in bals] or [0])).all()}
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_([b.item_id for b in bals] or [0])).all()}
    out = []
    for b in bals:
        c = cls.get(b.item_id, "C")
        when = last.get((b.store_id, b.item_id))
        since = (today - when).days if when else None
        due = when is None or since >= days[c]
        out.append({"store_id": b.store_id, "store_code": stores[b.store_id].code, "item_id": b.item_id, "item_code": items[b.item_id].item_code, "item_name": items[b.item_id].item_name,
                    "base_uom": (sets[b.item_id].base_uom if b.item_id in sets else items[b.item_id].units_of_measure) or "", "class": c, "every_days": days[c],
                    "last_counted": when.isoformat() if when else "", "days_since": since, "due": due, "overdue_days": (0 if when is None else max(0, since - days[c])) if due else 0,
                    "stock_value": format(_q(b.value, "0.01"), "f")})
    out.sort(key=lambda r: (not r["due"], r["class"], -(r["overdue_days"] if r["last_counted"] else 10 ** 6), r["store_code"], r["item_name"]))
    return out


# --- recount -------------------------------------------------------------------------------------------------------------------

def needs_recount(cfg, system_qty, counted_qty, avg_rate) -> bool:
    """Whether a first count is far enough from the books to be counted again: worth the configured amount, or the configured share of the books
    once it is worth at least the smallest amount."""
    var = Decimal(str(counted_qty)) - Decimal(str(system_qty))
    if var == 0:
        return False
    worth = abs(var * Decimal(str(avg_rate)))
    if Decimal(str(cfg.recount_value)) > 0 and worth >= Decimal(str(cfg.recount_value)):
        return True
    system = Decimal(str(system_qty))
    pct = Decimal(str(cfg.recount_pct))
    return pct > 0 and system > 0 and worth >= Decimal(str(cfg.recount_min_value)) and abs(var) * 100 / system >= pct


def _lines(db, doc):
    return db.query(DBStoreCountLine).filter(DBStoreCountLine.count_id == doc.id).order_by(DBStoreCountLine.id).all()


def _recounts(db, lines):
    return {r.count_line_id: r for r in db.query(DBStoreCountRecount).filter(DBStoreCountRecount.count_line_id.in_([l.id for l in lines] or [0])).all()}


def lines_to_recount(db, doc):
    """The counted lines that must still be counted again: far from the books on the first count, and no second count yet."""
    cfg = settings_of(db, doc.client_id)
    lines = _lines(db, doc)
    done = _recounts(db, lines)
    return [l for l in lines if l.counted_qty is not None and l.id not in done and needs_recount(cfg, l.system_qty, l.counted_qty, l.avg_rate)]


def assert_recounted(db, doc):
    pending = lines_to_recount(db, doc)
    if pending:
        names = ", ".join(db.get(models.DBItem, l.item_id).item_name for l in pending[:3])
        raise HTTPException(409, "%d item%s differ a lot from the books and must be counted again, without sight of the books (%s%s)." % (
            len(pending), "" if len(pending) == 1 else "s", names, ", ..." if len(pending) > 3 else ""))


def clear_recount(db, line):
    """The first count of a line was entered again: any second count of the old number no longer stands."""
    db.query(DBStoreCountRecount).filter(DBStoreCountRecount.count_line_id == line.id).delete(synchronize_session=False)


def recount_list(db, doc):
    """What is still to be counted again - names and units only. The books and the first count are not shown."""
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines_to_recount(db, doc)] or [0])).all()}
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(list(items) or [0])).all()}
    return [{"item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name,
             "base_uom": (sets[l.item_id].base_uom if l.item_id in sets else items[l.item_id].units_of_measure) or ""} for l in lines_to_recount(db, doc)]


def save_recounts(db, actor, doc, rows):
    if doc.status != DocStatus.DRAFT.value or doc.started_at is None:
        raise HTTPException(409, "Recounts can only be entered while the count is open.")
    if not rows:
        raise HTTPException(400, "Enter at least one count.")
    cfg = settings_of(db, doc.client_id)
    by_item = {l.item_id: l for l in _lines(db, doc)}
    existing = _recounts(db, list(by_item.values()))
    seen = set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        line = by_item.get(r.item_id)
        if line is None or line.counted_qty is None:
            raise HTTPException(400, "%s: that item has not been counted yet." % label)
        if r.item_id in seen:
            raise HTTPException(400, "%s: the item is on the sheet twice." % label)
        seen.add(r.item_id)
        have = existing.get(line.id)
        first = Decimal(str(have.first_qty if have else line.counted_qty))
        if not needs_recount(cfg, line.system_qty, first, line.avg_rate):
            raise HTTPException(409, "%s: that item does not need counting again." % label)
        entry = _num(r.qty, label + " quantity")
        item = db.get(models.DBItem, line.item_id)
        st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == line.item_id).first()
        uom = " ".join((r.uom or "").split()) or ((st.base_uom if st else item.units_of_measure) or "")
        try:
            base = convert_to_base(db, line.item_id, entry, uom)
        except Exception as exc:
            raise HTTPException(400, "%s: %s" % (label, exc)) from None
        if have is None:
            have = DBStoreCountRecount(count_line_id=line.id, first_qty=first)
            db.add(have)
        have.recount_qty, have.by_name, have.at = base, actor.name, datetime.now()
        line.counted_qty = base
    db.flush()
