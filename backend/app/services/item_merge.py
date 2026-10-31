"""Finding items entered twice, and folding them into one.

A merge moves what points at the duplicates onto the item kept: stock, batches, BOQ lines, orders, the ledger. The
duplicate is never deleted: it stays, switched off, saying where it went, and the merge record lists what moved.
Everything happens in the caller's one transaction, so a merge is all or nothing.
"""
import json
import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from app import models
from app.core.units import canonical_unit
from app.db.session import Base
from app.services import item_usage
from app.services.hr import serialise
from app.services.item_master import stock_of

# Printed once and never reissued: the record keeps the code it was written with.
HISTORY_ONLY = {("rate_audit_logs", "item_code"), ("eway_bill_lines", "item_code")}
# Quantities: when both items have a row for the same key, the two rows add up.
ADD_UP = {"store_stock_balance", "store_batch_balance", "stock_balances"}
# Two different things under one key: a person has to decide, so the merge stops.
REFUSE_CLASH = {"store_batch": "batch number", "store_tool": "tool serial number"}
PLAIN_ITEM_IDS = (("purchase_order_line_items", "item_id"),)     # item ids held without a foreign key


def _clean(text):
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _unit(text):
    return _clean(canonical_unit(text, "") or text)


def _words(text):
    return " ".join(sorted(re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split()))


def _references():
    """(table, column, unique key or None) for everything that points at an item."""
    out = []
    for t in Base.metadata.sorted_tables:
        if t.name == "erp_items":
            continue
        columns = [c for c in t.columns if any(fk.target_fullname == "erp_items.id" for fk in c.foreign_keys)]
        columns += [t.c[c] for tb, c in PLAIN_ITEM_IDS if tb == t.name]
        columns += [c for c in t.columns if c.name == "item_code" and (t.name, c.name) not in HISTORY_ONLY]
        for c in columns:
            key = None
            for con in list(t.constraints) + list(t.indexes):
                names = [x.name for x in con.columns] if hasattr(con, "columns") else []
                unique = con.__class__.__name__ == "UniqueConstraint" or getattr(con, "unique", False)
                if unique and c.name in names:
                    key = names
            out.append((t, c, key))
    return out


def _repoint(db, table, column, key, old, new):
    """Move one table's rows from the duplicate to the item kept. Returns how many moved."""
    rows = db.execute(select(table).where(column == old)).mappings().all()
    moved = 0
    pk = table.c.id if "id" in table.c else None
    for row in rows:
        clash = None
        if key:
            same = [table.c[k] == (new if k == column.name else row[k]) for k in key]
            clash = db.execute(select(table).where(*same)).mappings().first()
        if clash is None:
            db.execute(table.update().where(pk == row["id"]).values({column.name: new}))
            moved += 1
        elif table.name in ADD_UP:
            sums = {}
            for c in table.columns:
                if c.name in ("qty", "value", "quantity", "on_hand", "received", "issued"):
                    sums[c.name] = (clash[c.name] or 0) + (row[c.name] or 0)
            if "avg_rate" in table.c and "qty" in sums:
                sums["avg_rate"] = (sums.get("value", 0) / sums["qty"]) if sums["qty"] else 0
            db.execute(table.update().where(pk == clash["id"]).values(sums))
            db.execute(table.delete().where(pk == row["id"]))
            moved += 1
        # Anything else (a rate, a level, a count line) has one on the item kept already: the duplicate's stays as its record.
    return moved


def _items(db, client_id, ids):
    rows = db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.id.in_(ids)).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "Item not found")
    return {r.id: r for r in rows}


def _settings(db, ids):
    return {s.item_id: s for s in db.query(models.DBStoreItemSettings).filter(models.DBStoreItemSettings.item_id.in_(ids)).all()}


def merge_problems(db, primary, others):
    """Why these cannot be one item as they stand. A different unit needs a conversion agreed first, not a merge."""
    problems = []
    settings = _settings(db, [primary.id] + [o.id for o in others])
    mine = settings.get(primary.id)
    if primary.merged_into_id:
        problems.append("%s has already been merged into another item." % primary.item_code)
    for o in others:
        if o.merged_into_id:
            problems.append("%s has already been merged." % o.item_code)
        if o.kind != primary.kind:
            problems.append("%s is a %s and %s a %s." % (o.item_code, "material" if o.kind == "RM" else "work item", primary.item_code, "material" if primary.kind == "RM" else "work item"))
        if _unit(o.units_of_measure) != _unit(primary.units_of_measure):
            problems.append("%s is in %s and %s in %s: the quantities would not mean the same. Reconcile the units first." % (o.item_code, o.units_of_measure, primary.item_code, primary.units_of_measure))
        theirs = settings.get(o.id)
        if mine and theirs:
            if _unit(mine.base_uom) != _unit(theirs.base_uom):
                problems.append("%s keeps stock in %s and %s in %s." % (o.item_code, theirs.base_uom, primary.item_code, mine.base_uom))
            if mine.category != theirs.category:
                problems.append("%s is %s in the store and %s %s." % (o.item_code, theirs.category, primary.item_code, mine.category))
            if bool(mine.is_batch_tracked) != bool(theirs.is_batch_tracked):
                problems.append("One of %s and %s is tracked by batch and the other is not." % (o.item_code, primary.item_code))
    for name, what in REFUSE_CLASH.items():
        t = Base.metadata.tables[name]
        field = "batch_no" if name == "store_batch" else "serial_no"
        kept = {r[0] for r in db.execute(select(t.c[field]).where(t.c.item_id == primary.id)).all()}
        for o in others:
            for (value,) in db.execute(select(t.c[field]).where(t.c.item_id == o.id)).all():
                if value in kept:
                    problems.append("%s %s is on both %s and %s." % (what.capitalize(), value, o.item_code, primary.item_code))
    return problems


def merge_preview(db, client_id, primary_id, ids):
    """Each item side by side, with everything linked to it, and what would stop the merge."""
    all_ids = list(dict.fromkeys([primary_id] + list(ids)))
    if len(all_ids) < 2:
        raise HTTPException(400, "Choose at least two items.")
    items = _items(db, client_id, all_ids)
    primary = items[primary_id]
    others = [items[i] for i in all_ids if i != primary_id]
    stock = stock_of(db, client_id, [i.item_code for i in items.values()])
    cards = []
    for i in all_ids:
        it = items[i]
        usage = item_usage.where_used(db, client_id, it)
        cards.append({"id": it.id, "item_code": it.item_code, "item_name": it.item_name, "kind": it.kind, "units_of_measure": it.units_of_measure or "",
                      "item_category": it.item_category or "", "specification": it.specification or "", "make": it.make or "", "hsn_code": it.hsn_code or "",
                      "is_active": it.is_active is not False, "is_primary": i == primary_id, "stock": float(stock.get(it.item_code) or 0),
                      "linked_total": usage["total"], "linked": [{"label": g["label"], "count": g["count"]} for g in usage["groups"] if g["count"]]})
    return {"items": cards, "problems": merge_problems(db, primary, others)}


def merge_items(db, client_id, primary_id, ids, reason, who):
    """Fold `ids` into the primary. Does not commit: the caller's one transaction is the whole merge."""
    serialise(db, "item-merge:%d" % client_id)
    others_ids = [i for i in dict.fromkeys(ids) if i != primary_id]
    if not others_ids:
        raise HTTPException(400, "Choose at least one duplicate to merge into the item kept.")
    items = _items(db, client_id, [primary_id] + others_ids)
    primary = items[primary_id]
    others = [items[i] for i in others_ids]
    problems = merge_problems(db, primary, others)
    if problems:
        raise HTTPException(409, " ".join(problems))
    refs = _references()
    records = []
    for o in others:
        moved = {}
        for table, column, key in refs:
            old, new = (o.item_code, primary.item_code) if column.name == "item_code" else (o.id, primary.id)
            n = _repoint(db, table, column, key, old, new)
            if n:
                moved["%s.%s" % (table.name, column.name)] = n
        db.query(models.DBItem).filter(models.DBItem.merged_into_id == o.id).update({"merged_into_id": primary.id}, synchronize_session=False)
        o.is_active, o.merged_into_id, o.dup_key = False, primary.id, None
        o.merged_at, o.merged_by = datetime.now().strftime("%Y-%m-%d %H:%M:%S"), who
        record = models.DBItemMerge(client_id=client_id, primary_item_id=primary.id, primary_code=primary.item_code, merged_item_id=o.id, merged_code=o.item_code,
                                    merged_name=o.item_name, moved=json.dumps(moved), reason=(reason or "").strip()[:500], merged_by=who)
        db.add(record)
        records.append(record)
    db.flush()
    return primary, others, records


def find_duplicates(db, client_id, kind="", q="", which=""):
    """Groups that may be the same item. Exact: one kind, name and unit, once case and spacing are set aside. Possible:
    the same words in another order or punctuation, or the same name in another unit. Nothing here is ever merged by itself."""
    rows = [i for i in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.merged_into_id.is_(None)).all() if not kind or i.kind == kind]
    exact, loose = {}, {}
    for i in rows:
        exact.setdefault((i.kind, _clean(i.item_name), _unit(i.units_of_measure)), []).append(i)
        loose.setdefault((i.kind, _words(i.item_name)), []).append(i)
    groups, placed = [], set()
    for key, members in exact.items():
        if len(members) > 1:
            groups.append({"type": "exact", "reason": "Same name and unit", "members": members})
            placed.add(_words(members[0].item_name))
    for key, members in loose.items():
        if len(members) > 1 and key[1] and len({(_clean(m.item_name), _unit(m.units_of_measure)) for m in members}) > 1:
            groups.append({"type": "possible", "reason": "Same words, or the same name in another unit", "members": members})
    if which:
        groups = [g for g in groups if g["type"] == which]
    term = _clean(q)
    if term:
        groups = [g for g in groups if any(term in _clean(m.item_name) or term in _clean(m.item_code) for m in g["members"])]
    groups.sort(key=lambda g: (g["type"] != "exact", _clean(g["members"][0].item_name)))
    return groups


def group_dict(group, stock):
    return {"type": group["type"], "reason": group["reason"], "name": group["members"][0].item_name,
            "items": [{"id": m.id, "item_code": m.item_code, "item_name": m.item_name, "kind": m.kind, "item_category": m.item_category or "", "units_of_measure": m.units_of_measure or "",
                       "stock": float(stock.get(m.item_code) or 0), "is_active": m.is_active is not False} for m in group["members"]]}

