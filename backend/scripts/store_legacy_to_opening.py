"""Carry what the old stock screens hold into the Store module, as opening stock.

The old ledger (stock_movements, summed in stock_balances) keeps stock by item code and a free-typed store name. This
replays it per store name, finds the Store module's store and the item master's item for each balance, and posts one
opening per store - an OPENING_STOCK document (source LEGACY), posted straight away, its lines as OPENING_IN at the old
weighted-average rate. See docs/store/legacy_audit.md.

    python scripts/store_legacy_to_opening.py --client 12                      # dry run: what it would do
    python scripts/store_legacy_to_opening.py --client 12 --map "Main store=CS01" --map "Tower A=ST01" --commit
    python scripts/store_legacy_to_opening.py --all --create-stores --as-of 2026-10-01 --commit

Safe to run again: an item that already has stock history in its new store is skipped, so a second run only picks up
what the first could not. Nothing is written without --commit. Negative or zero balances, FG items, codes not in the item
master and units with no conversion are reported and left out - put them right in the old screens (or enter them as
opening stock by hand) and run again.
"""
import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import models  # noqa: E402
from app.models.store_core import (  # noqa: E402
    DBStore, DBStoreDocStatusLog, DBStoreOpening, DBStoreOpeningLine, DBStoreStockLedger, DocStatus, InvalidMovementError,
    MovementType, OpeningSource, StoreType,
)
from app.services.stock_ledger import convert_to_base, post_movement  # noqa: E402
from app.services.store_numbering import next_doc_number  # noqa: E402
from app.services.stores import replay_stock_ledger  # noqa: E402

D = Decimal
OPENING_DOC, WHO = "OPENING_STOCK", "Legacy stock migration"


def _q(x, step):
    return D(str(x)).quantize(D(step), rounding=ROUND_HALF_UP)


@dataclass
class StoreReport:
    legacy_name: str
    store_code: str = ""
    opening_number: str = ""
    lines: list = field(default_factory=list)       # (item_code, qty, uom, rate, value)
    skipped: list = field(default_factory=list)     # (item_code, why)
    value: Decimal = D(0)


def _has_history(db, store_id, item_id):
    reversed_ids = db.query(DBStoreStockLedger.reversal_of_id).filter(
        DBStoreStockLedger.store_id == store_id, DBStoreStockLedger.item_id == item_id,
        DBStoreStockLedger.reversal_of_id.isnot(None))
    return db.query(DBStoreStockLedger.id).filter(
        DBStoreStockLedger.store_id == store_id, DBStoreStockLedger.item_id == item_id,
        DBStoreStockLedger.reversal_of_id.is_(None), DBStoreStockLedger.id.notin_(reversed_ids)).first() is not None


def _free_code(db, client_id, name):
    """A store code for a store the old screens knew only by name: its initials, then a number (MS01 for Main store)."""
    stem = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", name.upper()))[:4] or "LG"
    taken = {c for (c,) in db.query(DBStore.code).filter(DBStore.client_id == client_id).all()}
    for n in range(1, 100):
        code = "%s%02d" % (stem, n)
        if code not in taken:
            return code
    raise RuntimeError("No free store code for %s" % name)


def _find_store(db, client_id, legacy_name, store_map, create):
    wanted = store_map.get(legacy_name.lower())
    stores = db.query(DBStore).filter(DBStore.client_id == client_id, DBStore.is_active.is_(True)).all()
    for st in stores:
        if wanted and st.code.upper() == wanted.upper():
            return st
    if wanted:
        return None
    for st in stores:
        if st.name.strip().lower() == legacy_name.strip().lower() or st.code.upper() == legacy_name.strip().upper():
            return st
    if not create:
        return None
    st = DBStore(client_id=client_id, code=_free_code(db, client_id, legacy_name), name=legacy_name.strip(),
                 type=StoreType.CENTRAL.value, address="Carried over from the old stock screens", is_active=True)
    db.add(st)
    db.flush()
    return st


def migrate_client(db, client_id, *, as_of=None, store_map=None, create_stores=False):
    """Post the client's old balances as one opening per store. Flushes, never commits: the caller commits (or rolls
    back for a dry run). Returns a StoreReport per old store name."""
    as_of = as_of or date.today()
    store_map = {k.strip().lower(): v.strip() for k, v in (store_map or {}).items()}
    names = sorted({s for (s,) in db.query(models.DBStockMovement.store).filter(
        models.DBStockMovement.client_id == client_id).distinct().all() if s})
    reports = []
    for legacy_name in names:
        rep = StoreReport(legacy_name)
        reports.append(rep)
        store = _find_store(db, client_id, legacy_name, store_map, create_stores)
        if store is None:
            rep.skipped.append(("*", "no store in the Store module for %r - map it with --map or use --create-stores" % legacy_name))
            continue
        rep.store_code = store.code
        held = replay_stock_ledger(db, client_id, store=legacy_name)
        planned = []
        for code, a in sorted(held.items()):
            qty_old = _q(a["on_hand"], "0.001")
            if qty_old <= 0:
                if qty_old < 0:
                    rep.skipped.append((code, "negative balance %s in the old ledger" % qty_old))
                continue
            item = db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.item_code == code).first()
            if item is None:
                rep.skipped.append((code, "not in the item master"))
                continue
            if item.kind != "RM":
                rep.skipped.append((code, "a %s item, not stock" % item.kind))
                continue
            if _has_history(db, store.id, item.id):
                rep.skipped.append((code, "already has stock history in %s" % store.code))
                continue
            uom = (a.get("uom") or item.units_of_measure or "").strip()
            try:
                qty = convert_to_base(db, item.id, qty_old, uom)
            except InvalidMovementError as exc:
                rep.skipped.append((code, str(exc)))
                continue
            value_old = _q(a["value"], "0.01")
            if qty <= 0 or value_old < 0:
                rep.skipped.append((code, "nothing to carry (%s %s worth %s)" % (qty_old, uom, value_old)))
                continue
            rate = _q(value_old / qty, "0.0001")
            planned.append((item, qty_old, uom, _q(value_old / qty_old, "0.0001"), qty, rate))
        if not planned:
            continue
        number = next_doc_number(db, "OPEN", store.id, on_date=as_of)
        doc = DBStoreOpening(client_id=client_id, store_id=store.id, number=number, opening_date=as_of,
                             status=DocStatus.DRAFT.value, source=OpeningSource.LEGACY.value,
                             remarks="Carried over from the old stock screens (%s)" % legacy_name, created_by_name=WHO)
        db.add(doc)
        db.flush()
        for n, (item, qty_old, uom, rate_old, qty, rate) in enumerate(planned, 1):
            value = _q(qty * rate, "0.01")
            line = DBStoreOpeningLine(opening_id=doc.id, line_no=n, item_id=item.id, entered_qty=qty_old, entered_uom=uom,
                                      entered_rate=rate_old, qty=qty, rate=rate, value=value, remarks="Legacy balance")
            db.add(line)
            db.flush()
            post_movement(db, movement_type=MovementType.OPENING_IN, store_id=store.id, item_id=item.id, qty=qty, rate=rate,
                          txn_date=as_of, project_id=store.project_id, ref_doc_type=OPENING_DOC, ref_doc_id=doc.id,
                          ref_line_id=line.id, user_id=None, remarks="Opening %s: legacy balance" % number)
            rep.lines.append((item.item_code, qty, uom, rate, value))
            rep.value += value
        doc.status, doc.posted_at = DocStatus.POSTED.value, datetime.now()
        now = datetime.now()
        db.add_all([DBStoreDocStatusLog(client_id=client_id, doc_type=OPENING_DOC, doc_id=doc.id, from_status=None,
                                        to_status=DocStatus.DRAFT.value, user_name=WHO, note="Carried over", at=now),
                    DBStoreDocStatusLog(client_id=client_id, doc_type=OPENING_DOC, doc_id=doc.id, from_status=DocStatus.DRAFT.value,
                                        to_status=DocStatus.POSTED.value, user_name=WHO,
                                        note="Posted by the legacy migration script", at=now)])
        rep.opening_number = number
        db.flush()
    return reports


def _print(client, reports):
    print("== %s (client %s)" % (client.company_name or client.email, client.id))
    if not reports:
        print("   the old stock screens hold nothing")
    for r in reports:
        print("   %s -> %s %s  %d lines, value %s" % (r.legacy_name, r.store_code or "?", r.opening_number or "(nothing posted)",
                                                   len(r.lines), r.value))
        for code, why in r.skipped:
            print("      skipped %s: %s" % (code, why))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--client", type=int, help="the company (clients.id) to migrate")
    who.add_argument("--all", action="store_true", help="every company with old stock movements")
    p.add_argument("--map", action="append", default=[], metavar="OLD NAME=CODE",
                   help="post the old store name into this Store module store (repeatable)")
    p.add_argument("--create-stores", action="store_true", help="make a central store for an old name with no match")
    p.add_argument("--as-of", default=None, help="the opening date, YYYY-MM-DD (default today)")
    p.add_argument("--commit", action="store_true", help="write it; without this nothing is saved")
    args = p.parse_args(argv)
    store_map = dict(m.split("=", 1) for m in args.map if "=" in m)
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else date.today()

    from app import db as database
    db = database.SessionLocal()
    try:
        if args.client:
            ids = [args.client]
        else:
            ids = sorted({c for (c,) in db.query(models.DBStockMovement.client_id).distinct().all()})
        for cid in ids:
            client = db.get(models.DBClient, cid)
            if client is None:
                print("No client %s" % cid)
                continue
            reports = migrate_client(db, cid, as_of=as_of, store_map=store_map, create_stores=args.create_stores)
            _print(client, reports)
        if args.commit:
            db.commit()
            print("Committed.")
        else:
            db.rollback()
            print("Dry run - nothing saved. Run again with --commit to write it.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
