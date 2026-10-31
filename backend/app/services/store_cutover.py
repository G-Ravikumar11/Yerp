"""Moving a company's old store into the Store Hub, once.

The old store (Stock & Issues, Goods Receipt & Match) kept stock by item code in named stores - "Main store", a site.
The Hub keeps it by stock item in a store it knows. At the cut-over each old store that still holds anything is given a
Hub store; its closing stock becomes one posted Opening stock document there, as on the cut-over day, at the old
weighted-average rate. From then on the old store is a record: nothing more is received, issued or moved in it.

Its history is not copied. It stays readable, and its issues keep counting in project costs: Hub issues start from the
opening stock and never repeat what the old store already charged to a job.
"""
import json
import os
from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException

from app import models
from app.core.currency import money, unit_rate
from app.models.store_core import DBStore, DocStatus, InvalidMovementError
from app.models.store_inward import OPENING, DBStoreOpening


def cutover_of(db, client_id):
    """The company's cut-over, or None while the old store is still in use. Asked once per request: a fifty-line
    receipt checks it for every line."""
    seen = db.info.setdefault("store_cutover", {})
    if client_id not in seen:
        seen[client_id] = db.query(models.DBStoreCutover).filter(models.DBStoreCutover.client_id == client_id).first()
    return seen[client_id]


def old_store_closed():
    """The old store takes no new entries, for any company. OLD_STORE_OPEN=1 opens it for one purpose: a company that has
    not moved yet and has to put its figures right before it can."""
    return (os.getenv("OLD_STORE_OPEN") or "").strip() not in ("1", "true")


def refuse_if_moved(db, client_id):
    """409: the old store is a record, and stock changes only in the Hub."""
    if old_store_closed():
        raise HTTPException(409, "This is a legacy store module. Transactions are available in read-only mode. Record this in the Store Hub.")
    c = cutover_of(db, client_id)
    if c is not None:
        raise HTTPException(409, "The old store moved into the Store Hub on %s and is kept as a record only. "
                                 "Record this in the Store Hub." % c.cutover_date)


def cutover_dict(c):
    if c is None:
        return None
    try:
        summary = json.loads(c.summary or "[]")
    except ValueError:
        summary = []
    return {"cutover_date": c.cutover_date, "done_by_name": c.done_by_name or "", "done_at": c.done_at or "", "carried": summary}


def _hub_item(db, client_id, code):
    return db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.item_code == code).first()


def preview(db, client_id):
    """What the cut-over would carry: each old store's closing stock, item by item, with whatever stops it moving, and
    the Hub stores it could go to."""
    from app.services.stock_ledger import convert_to_base
    from app.services.store_inward import base_uom_of
    from app.services.stores import replay_stock_ledger

    done = cutover_of(db, client_id)
    hub = [{"id": s.id, "code": s.code, "name": s.name, "type": s.type, "project_id": s.project_id}
           for s in db.query(DBStore).filter(DBStore.client_id == client_id, DBStore.is_active.is_(True)).order_by(DBStore.code).all()]
    names = sorted({n or "Main store" for (n,) in db.query(models.DBStockMovement.store).filter(
        models.DBStockMovement.client_id == client_id).distinct()})
    stores, problems = [], []
    for name in names:
        rows = []
        for code, a in sorted(replay_stock_ledger(db, client_id, store=name).items()):
            if not a["on_hand"]:
                continue
            item = _hub_item(db, client_id, code)
            row = {"item_code": code, "item_name": a["item_name"] or (item.item_name if item else ""), "uom": a["uom"] or "",
                   "on_hand": money(a["on_hand"]), "rate": unit_rate(a["rate"]), "value": money(a["value"]),
                   "item_id": item.id if item else None, "problem": ""}
            if a["on_hand"] < 0:
                row["problem"] = "Shows %s %s: count it and correct it with an adjustment first." % (money(a["on_hand"]), row["uom"])
            elif item is None:
                row["problem"] = "Not in the Item Master. Add item %s there first." % code
            elif item.kind != "RM":
                row["problem"] = "In the Item Master as %s, not as a stock material (RM)." % item.kind
            else:
                try:
                    convert_to_base(db, item.id, Decimal(str(row["on_hand"])), row["uom"] or base_uom_of(db, item))
                except InvalidMovementError:
                    row["problem"] = "Counted in %s, but the Hub keeps it in %s and has no conversion. Set one under Masters." % (
                        row["uom"] or "no unit", base_uom_of(db, item) or "no unit")
            rows.append(row)
        if not rows:
            continue
        match = next((s["id"] for s in hub if name.strip().lower() in (s["name"].strip().lower(), s["code"].strip().lower())), None)
        stores.append({"name": name, "items": rows, "value": money(sum(r["value"] for r in rows if r["on_hand"] > 0)),
                       "problems": sum(1 for r in rows if r["problem"]), "suggested_store_id": match})
        problems += ["%s, %s: %s" % (name, r["item_code"], r["problem"]) for r in rows if r["problem"]]
    drafts = {
        "goods_receipts": db.query(models.DBGoodsReceipt.id).filter(
            models.DBGoodsReceipt.client_id == client_id, models.DBGoodsReceipt.status == "DRAFT").count(),
        "issues": db.query(models.DBStockIssue.id).filter(
            models.DBStockIssue.client_id == client_id, models.DBStockIssue.status == "DRAFT").count(),
    }
    if drafts["goods_receipts"]:
        problems.append("%d goods receipt%s in the old store still in draft: post or cancel them first."
                        % (drafts["goods_receipts"], "" if drafts["goods_receipts"] == 1 else "s"))
    if drafts["issues"]:
        problems.append("%d issue%s in the old store still in draft: post or cancel them first."
                        % (drafts["issues"], "" if drafts["issues"] == 1 else "s"))
    return {"done": cutover_dict(done), "stores": stores, "hub_stores": hub, "drafts": drafts, "problems": problems}


def run(db, actor, cutover_date, mapping):
    """Carry every old store's closing stock into its Hub store as posted opening stock, and close the old store.
    `mapping` is {old store name: Hub store id}. All or nothing; the caller commits."""
    from app.services import store_inward as inward

    client_id = actor.client.id
    if cutover_of(db, client_id) is not None:
        raise HTTPException(409, "The old store has already moved into the Store Hub.")
    try:
        on = date.fromisoformat((cutover_date or "")[:10])
    except ValueError:
        raise HTTPException(400, "Give the cut-over date.")
    if on > date.today():
        raise HTTPException(400, "The cut-over date cannot be in the future: the stock carried is what is held now.")
    p = preview(db, client_id)
    if p["problems"]:
        raise HTTPException(409, "Put these right first: " + "; ".join(p["problems"][:5])
                            + (" (and %d more)" % (len(p["problems"]) - 5) if len(p["problems"]) > 5 else ""))
    hub = {s["id"]: s for s in p["hub_stores"]}
    into = OrderedDict()                       # Hub store id -> {item id: [qty, value, uom]}
    for s in p["stores"]:
        sid = mapping.get(s["name"])
        try:
            sid = int(sid) if sid not in (None, "") else None
        except (TypeError, ValueError):
            sid = None
        if sid not in hub:
            raise HTTPException(400, "Choose the Hub store that %s's stock goes to." % s["name"])
        slot = into.setdefault(sid, OrderedDict())
        for r in s["items"]:
            # Two old stores carried into one Hub store become one line per item, valued at what they held together.
            got = slot.setdefault(r["item_id"], [0.0, 0.0, r["uom"]])
            if (got[2] or "").strip().lower() != (r["uom"] or "").strip().lower():
                raise HTTPException(409, "%s is counted in %s in one old store and %s in another; carry them into different "
                                         "Hub stores or correct the unit first." % (r["item_code"], got[2], r["uom"]))
            got[0], got[1] = got[0] + r["on_hand"], got[1] + r["value"]
    carried = []
    for sid, items in into.items():
        rows = [SimpleNamespace(item_id=iid, uom=uom, qty=Decimal(str(money(qty))),
                                rate=Decimal(str(unit_rate(value / qty))) if qty else Decimal("0"))
                for iid, (qty, value, uom) in items.items() if qty > 0]
        if not rows:
            continue
        lines = inward.build_opening_lines(db, client_id, rows)
        doc = DBStoreOpening(client_id=client_id, store_id=sid, number=inward.numbered(db, OPENING, sid, on), status=DocStatus.DRAFT.value,
                             as_on_date=on, remarks="Carried from the old store on cut-over")
        doc.created_by_id, doc.created_by_name = actor.user_id, actor.name
        db.add(doc)
        db.flush()
        inward.write_opening_lines(db, doc, lines)
        inward.log(db, actor, OPENING, doc.id, "create", "", doc.status, "cut-over from the old store")
        for step in ("submit", "approve", "post"):
            inward.advance(db, actor, inward.KINDS["opening"], doc, step)
        carried.append({"store_id": sid, "store": hub[sid]["name"], "opening": doc.number, "opening_id": doc.id, "lines": len(rows),
                        "value": money(sum(v for _q, v, _u in items.values()))})
    c = models.DBStoreCutover(client_id=client_id, cutover_date=on.isoformat(), done_by_name=actor.name,
                              done_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), summary=json.dumps(carried))
    db.add(c)
    db.flush()
    db.info.setdefault("store_cutover", {})[client_id] = c
    return carried
