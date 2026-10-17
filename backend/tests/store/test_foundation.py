"""P1 foundation: the ledger engine under pressure (valuation over mixed rates, reversals in the middle of a sequence,
rounding, back-dating, count freezes, two posters at once) and document numbering (concurrency, financial year)."""
import random
import threading
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import db as database
from app.models.store_core import (
    DBStoreStockLedger, InsufficientStockError, InvalidMovementError, MovementType, StoreFrozenError,
)
from app.services.stock_ledger import (
    freeze_store, freeze_store_for_count, get_balance, ledger_position, post_movement, reverse_document, unfreeze_store,
)
from app.services.store_numbering import financial_year, next_doc_number
from store.fixtures import db, store_world  # noqa: F401  (fixtures)

D = Decimal
TODAY = date.today()


def post(db, w, mtype, qty, rate=None, store=None, item="sand", doc=("GRN", 10), day=TODAY, **kw):
    return post_movement(db, movement_type=mtype, store_id=store or w.central_id, item_id=w.item[item], qty=D(str(qty)),
                         rate=None if rate is None else D(str(rate)), txn_date=day, project_id=kw.pop("project_id", None),
                         ref_doc_type=doc[0], ref_doc_id=doc[1], ref_line_id=kw.pop("ref_line_id", 1),
                         user_id=kw.pop("user_id", None), **kw)


def position(db, w, item="sand", store=None):
    b = get_balance(db, store or w.central_id, w.item[item])
    return b.qty, b.value, b.avg_rate


def assert_ledger_agrees(db, w, item="sand", store=None):
    bal = get_balance(db, store or w.central_id, w.item[item])
    led = ledger_position(db, store or w.central_id, w.item[item])
    assert (led.qty, led.value) == (bal.qty, bal.value)


# --- valuation -----------------------------------------------------------------------------------------------------

def test_mixed_rates_issues_and_a_reversal_in_the_middle(db, store_world):
    """Sand: 100 cum @ 1800 opening. Every figure below was worked out by hand (Decimal, half-up)."""
    w = store_world
    post(db, w, MovementType.GRN_IN, 50, 2000, doc=("GRN", 1))
    assert position(db, w) == (D("150.000"), D("280000.00"), D("1866.6667"))

    issue = post(db, w, MovementType.ISSUE_OUT, 40, doc=("ISSUE", 1), project_id=w.project_id)
    assert (issue.value, issue.rate) == (D("74666.67"), D("1866.6668"))      # 40 x 1866.6667, the entry's own rate
    assert position(db, w) == (D("110.000"), D("205333.33"), D("1866.6667"))  # an issue does not move the average

    post(db, w, MovementType.GRN_IN, 30, "1750.5", doc=("GRN", 2))
    assert position(db, w) == (D("140.000"), D("257848.33"), D("1841.7738"))

    back = reverse_document(db, ref_doc_type="ISSUE", ref_doc_id=1, user_id=None, reason="returned unused")
    assert len(back) == 1 and back[0].reversal_of_id == issue.id
    assert back[0].qty_in == D("40") and back[0].value == D("74666.67")         # back in at what it went out at
    assert back[0].movement_type == "ISSUE_OUT"                                 # same type, opposite column
    assert position(db, w) == (D("180.000"), D("332515.00"), D("1847.3056"))

    later = post(db, w, MovementType.ISSUE_OUT, 25, doc=("ISSUE", 2))
    assert later.value == D("46182.64")
    assert position(db, w) == (D("155.000"), D("286332.36"), D("1847.3056"))
    assert_ledger_agrees(db, w)


def test_reversing_a_receipt_takes_it_out_at_its_own_rate_and_re_averages(db, store_world):
    w = store_world
    grn = post(db, w, MovementType.GRN_IN, 50, 2000, doc=("GRN", 3))
    post(db, w, MovementType.ISSUE_OUT, 30, doc=("ISSUE", 3))                 # 30 x 1866.6667 = 56000.00
    assert position(db, w) == (D("120.000"), D("224000.00"), D("1866.6667"))
    out = reverse_document(db, ref_doc_type="GRN", ref_doc_id=3, user_id=None, reason="wrong supplier")[0]
    assert (out.qty_out, out.value, out.rate, out.reversal_of_id) == (D("50"), grn.value, D("2000.0000"), grn.id)
    # 70 left worth 124000.00: the average is what is left, not the old blend that included the receipt.
    assert position(db, w) == (D("70.000"), D("124000.00"), D("1771.4286"))
    assert_ledger_agrees(db, w)


def test_rounding_never_leaves_value_behind_an_empty_heap(db, store_world):
    """Diesel: 1000 litre @ 92. Three thirds and the crumb that is left."""
    w = store_world
    for n in (1, 2, 3):
        e = post(db, w, MovementType.ISSUE_OUT, "333.333", item="diesel", doc=("ISSUE", 10 + n))
        assert e.value == D("30666.64")                                        # 333.333 x 92 = 30666.636
    assert position(db, w, "diesel") == (D("0.001"), D("0.08"), D("92.0000"))
    last = post(db, w, MovementType.ISSUE_OUT, "0.001", item="diesel", doc=("ISSUE", 14))
    assert last.value == D("0.08")                                             # the whole heap takes the whole value
    assert position(db, w, "diesel")[:2] == (0, 0)
    assert_ledger_agrees(db, w, "diesel")


def test_a_random_day_in_the_store_always_adds_up(db, store_world):
    """Two hundred receipts, issues and reversals at awkward rates: the balance and the ledger never part, value
    never goes negative, and the average is always what is held divided by how much."""
    w, rnd = store_world, random.Random(20261017)
    docs = []
    for n in range(200):
        bal = get_balance(db, w.central_id, w.item["bricks"])
        roll = rnd.random()
        try:
            if roll < 0.4:
                post(db, w, MovementType.GRN_IN, rnd.randint(1, 900), D(rnd.randint(100, 1500)) / 97, item="bricks",
                     doc=("GRN", 1000 + n))
                docs.append(("GRN", 1000 + n))
            elif roll < 0.8 and bal.qty > 0:
                post(db, w, MovementType.ISSUE_OUT, min(bal.qty, rnd.randint(1, 1200)), item="bricks", doc=("ISSUE", 1000 + n))
                docs.append(("ISSUE", 1000 + n))
            elif docs:
                kind, ref = docs.pop(rnd.randrange(len(docs)))
                with db.begin_nested():
                    reverse_document(db, ref_doc_type=kind, ref_doc_id=ref, user_id=None, reason="test")
        except (InsufficientStockError, InvalidMovementError):
            pass                                                               # refused whole; nothing half-done
        b = get_balance(db, w.central_id, w.item["bricks"])
        assert b.qty >= 0 and b.value >= 0
        if b.qty:
            assert abs(b.value / b.qty - b.avg_rate) < D("0.01")
        else:
            assert b.value == 0
    assert_ledger_agrees(db, w, "bricks")


# --- reversals -----------------------------------------------------------------------------------------------------

def test_a_reversal_that_would_go_negative_is_refused_and_says_what_is_there(db, store_world):
    w = store_world
    post(db, w, MovementType.GRN_IN, 20, 1900, doc=("GRN", 20))
    post(db, w, MovementType.ISSUE_OUT, 110, doc=("ISSUE", 20))                # 10 cum left
    with pytest.raises(InsufficientStockError) as err:
        reverse_document(db, ref_doc_type="GRN", ref_doc_id=20, user_id=None, reason="wrong")
    msg = str(err.value)
    assert "River Sand" in msg and "only 10 cum" in msg and "CS01" in msg and "20 cum is needed" in msg
    assert (err.value.available, err.value.requested) == (D("10.000"), D("20.000"))
    assert position(db, w)[0] == D("10.000")


def test_a_reversal_that_would_leave_a_negative_value_is_refused(db, store_world):
    """Cheap stock, then a dear receipt, then an issue at the blend: the dear receipt is worth more than what is left."""
    w = store_world
    post(db, w, MovementType.ISSUE_OUT, 100, doc=("ISSUE", 30))                # empty the opening
    post(db, w, MovementType.GRN_IN, 100, 1, doc=("GRN", 31))
    post(db, w, MovementType.GRN_IN, 100, 10, doc=("GRN", 32))
    post(db, w, MovementType.ISSUE_OUT, 50, doc=("ISSUE", 33))                 # 150 left worth 825.00
    with pytest.raises(InvalidMovementError, match="negative value"):
        reverse_document(db, ref_doc_type="GRN", ref_doc_id=32, user_id=None, reason="wrong")
    assert position(db, w)[:2] == (D("150.000"), D("825.00"))


def test_reversed_once_only_and_never_a_reversal_of_a_reversal(db, store_world):
    w = store_world
    post(db, w, MovementType.GRN_IN, 5, 1800, doc=("GRN", 40))
    post(db, w, MovementType.GRN_IN, 5, 1800, item="aggregate", doc=("GRN", 40), ref_line_id=2)
    first = reverse_document(db, ref_doc_type="GRN", ref_doc_id=40, user_id=None, reason="duplicate")
    assert len(first) == 2 and all(r.reversal_of_id for r in first)
    with pytest.raises(InvalidMovementError, match="already been reversed"):
        reverse_document(db, ref_doc_type="GRN", ref_doc_id=40, user_id=None, reason="again")
    with pytest.raises(InvalidMovementError, match="nothing to reverse"):
        reverse_document(db, ref_doc_type="GRN", ref_doc_id=41, user_id=None, reason="never posted")
    with pytest.raises(InvalidMovementError, match="reason"):
        reverse_document(db, ref_doc_type="GRN", ref_doc_id=40, user_id=None, reason="  ")


def test_the_database_itself_refuses_a_second_reversal_of_one_row(db, store_world):
    w = store_world
    grn = post(db, w, MovementType.GRN_IN, 5, 1800, doc=("GRN", 50))
    reverse_document(db, ref_doc_type="GRN", ref_doc_id=50, user_id=None, reason="once")
    db.add(DBStoreStockLedger(txn_date=TODAY, store_id=w.central_id, item_id=w.item["sand"], movement_type="GRN_IN",
                              qty_in=0, qty_out=5, rate=1800, value=9000, running_qty=0, running_value=0, avg_rate=0,
                              ref_doc_type="GRN", ref_doc_id=50, reversal_of_id=grn.id))
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# --- dates ---------------------------------------------------------------------------------------------------------

def test_a_movement_cannot_be_dated_before_the_last_one_of_its_item(db, store_world):
    w = store_world
    yesterday = TODAY - timedelta(days=1)
    post(db, w, MovementType.GRN_IN, 5, 1800, doc=("GRN", 60), day=yesterday)
    with pytest.raises(InvalidMovementError, match="dated %s" % yesterday.isoformat()):
        post(db, w, MovementType.ISSUE_OUT, 1, doc=("ISSUE", 60), day=TODAY - timedelta(days=2))
    post(db, w, MovementType.ISSUE_OUT, 1, doc=("ISSUE", 61), day=yesterday)    # the same day is fine
    post(db, w, MovementType.ISSUE_OUT, 1, doc=("ISSUE", 62))
    post(db, w, MovementType.ISSUE_OUT, 1, item="aggregate", doc=("ISSUE", 63), day=TODAY - timedelta(days=5))  # another item
    post(db, w, MovementType.TRANSFER_IN, 1, 1800, store=w.site_id, doc=("TRANSFER", 64), day=TODAY - timedelta(days=9))  # another store
    with pytest.raises(InvalidMovementError, match="future"):
        post(db, w, MovementType.ISSUE_OUT, 1, doc=("ISSUE", 65), day=TODAY + timedelta(days=1))


# --- freezes -------------------------------------------------------------------------------------------------------

def test_a_count_freeze_lets_its_own_adjustments_through_and_nothing_else(db, store_world):
    w = store_world
    freeze = freeze_store_for_count(db, w.central_id, "count 77", user_id=None, count_doc_id=77)
    assert (freeze.ref_doc_type, freeze.ref_doc_id) == ("COUNT", 77)
    adj = post(db, w, MovementType.ADJUST_IN, 2, 1800, doc=("COUNT", 77))
    post(db, w, MovementType.ADJUST_OUT, 1, item="aggregate", doc=("COUNT", 77))
    for mtype, rate, doc in ((MovementType.ADJUST_IN, 1800, ("COUNT", 78)),      # another count
                             (MovementType.ADJUST_OUT, None, ("ADJUST", 77)),    # another kind of document
                             (MovementType.GRN_IN, 1800, ("COUNT", 77)),         # the count, but not an adjustment
                             (MovementType.ISSUE_OUT, None, ("ISSUE", 77))):
        with pytest.raises(StoreFrozenError):
            post(db, w, mtype, 1, rate, doc=doc)
    undone = reverse_document(db, ref_doc_type="COUNT", ref_doc_id=77, user_id=None, reason="recount")
    assert {u.reversal_of_id for u in undone} >= {adj.id}
    post(db, w, MovementType.GRN_IN, 1, 1800, store=w.site_id, doc=("GRN", 77))   # the other store is not frozen
    unfreeze_store(db, w.central_id, user_id=None)
    post(db, w, MovementType.ISSUE_OUT, 1, doc=("ISSUE", 79))


def test_a_plain_freeze_holds_adjustments_too(db, store_world):
    w = store_world
    freeze_store(db, w.central_id, "audit", user_id=None)
    with pytest.raises(StoreFrozenError):
        post(db, w, MovementType.ADJUST_IN, 1, 1800, doc=("COUNT", 1))
    with pytest.raises(InvalidMovementError):
        freeze_store_for_count(db, w.central_id, "again", user_id=None, count_doc_id=2)   # one freeze at a time


# --- two at once ---------------------------------------------------------------------------------------------------

def _together(*jobs):
    """Run each job on its own thread and session; return what each returned or raised."""
    results = [None] * len(jobs)

    def run(i, job):
        s = database.SessionLocal()
        try:
            results[i] = job(s)
            s.commit()
        except Exception as exc:          # noqa: BLE001 - the test looks at what was raised
            s.rollback()
            results[i] = exc
        finally:
            s.close()
    threads = [threading.Thread(target=run, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results


def test_two_issues_at_once_cannot_spend_the_same_stock(db, store_world):
    """100 cum held; two people issue 60 each at the same moment. One gets it, the other is told there is not enough."""
    w = store_world

    def issue(ref):
        def job(s):
            e = post(s, w, MovementType.ISSUE_OUT, 60, doc=("ISSUE", ref))
            time.sleep(0.3)               # hold the lock a while, so the other really does arrive meanwhile
            return e.id
        return job
    results = _together(issue(90), issue(91))
    assert sum(isinstance(r, int) for r in results) == 1, results
    assert sum(isinstance(r, InsufficientStockError) for r in results) == 1, results
    db.expire_all()
    assert position(db, w)[:2] == (D("40.000"), D("72000.00"))
    assert_ledger_agrees(db, w)


def test_two_receipts_at_once_both_count(db, store_world):
    w = store_world

    def receive(ref):
        def job(s):
            post(s, w, MovementType.GRN_IN, 10, 1900, doc=("GRN", ref))
            time.sleep(0.2)
        return job
    results = _together(receive(92), receive(93), receive(94))
    assert results == [None, None, None], results
    db.expire_all()
    assert position(db, w)[:2] == (D("130.000"), D("237000.00"))
    assert_ledger_agrees(db, w)


def test_two_cancels_of_one_document_reverse_it_once(db, store_world):
    w = store_world
    post(db, w, MovementType.GRN_IN, 10, 1900, doc=("GRN", 95))
    db.commit()

    def cancel(s):
        out = reverse_document(s, ref_doc_type="GRN", ref_doc_id=95, user_id=None, reason="twice at once")
        time.sleep(0.2)
        return len(out)
    results = _together(cancel, cancel)
    assert sorted(map(type, results), key=str) == sorted([int, InvalidMovementError], key=str), results
    db.expire_all()
    assert position(db, w)[:2] == (D("100.000"), D("180000.00"))


def test_numbers_taken_at_once_are_all_different(db, store_world):
    w = store_world

    def take(s):
        got = []
        for _ in range(8):
            got.append(next_doc_number(s, "ISSUE", w.central_id, on_date="2026-10-17"))
            s.commit()
        return got
    results = _together(take, take, take)
    numbers = [n for r in results for n in r]
    assert len(numbers) == 24 and len(set(numbers)) == 24, results
    assert max(numbers) == "ISSUE/CS01/26-27/00024"


# --- numbering -----------------------------------------------------------------------------------------------------

def test_numbering_rolls_over_on_the_first_of_april(db, store_world):
    w = store_world
    assert next_doc_number(db, "TRF", w.central_id, on_date=date(2027, 3, 31)) == "TRF/CS01/26-27/00001"
    assert next_doc_number(db, "TRF", w.central_id, on_date="2027-04-01") == "TRF/CS01/27-28/00001"
    assert next_doc_number(db, "TRF", w.central_id, on_date="2027-03-15") == "TRF/CS01/26-27/00002"   # back in the old year
    assert financial_year(date(2099, 4, 1)) == "99-00" and financial_year("2000-01-05") == "99-00"


def test_a_rolled_back_document_gives_its_number_back(db, store_world):
    w = store_world
    assert next_doc_number(db, "SCRAP", w.site_id, on_date="2026-10-17") == "SCRAP/ST01/26-27/00001"
    db.rollback()
    assert next_doc_number(db, "SCRAP", w.site_id, on_date="2026-10-17") == "SCRAP/ST01/26-27/00001"


def test_numbering_refuses_what_it_cannot_number(db, store_world):
    w = store_world
    for bad in ("grn", "G", "GRN-1", ""):
        with pytest.raises(InvalidMovementError):
            next_doc_number(db, bad, w.central_id)
    with pytest.raises(InvalidMovementError):
        next_doc_number(db, "GRN", 999999)
    with pytest.raises(InvalidMovementError, match="Not a date"):
        next_doc_number(db, "GRN", w.central_id, on_date="17/10/2026")


# --- the old stock screens, carried over -------------------------------------------------------------------------

def test_legacy_balances_become_opening_stock_once(db, store_world):
    from app import models
    from app.models.store_core import (
        DBStore, DBStoreDocSequence, DBStoreDocStatusLog, DBStoreOpening, DBStoreOpeningLine, DBStoreStockBalance,
    )
    from app.services.stores import stock_movement
    from scripts.store_legacy_to_opening import migrate_client
    w = store_world
    code = {k: db.get(models.DBItem, v).item_code for k, v in w.item.items()}
    cid = w.client_id
    stock_movement(db, cid, code["cement"], "RECEIPT", 1000, 7.5, store="Main store")
    stock_movement(db, cid, code["cement"], "ISSUE", -200, 7.5, store="Main store")
    stock_movement(db, cid, code["tmt12"], "RECEIPT", 50, 700, store="Main store", uom="nos")       # counted in bars
    stock_movement(db, cid, code["helmet"], "ISSUE", -5, 180, store="Main store")                   # went negative
    stock_movement(db, cid, "OLD-CODE-1", "RECEIPT", 5, 10, store="Main store", uom="kg")            # not an item any more
    stock_movement(db, cid, code["sand"], "RECEIPT", 12, 1700, store="Lost shed")
    db.commit()
    made = []
    try:
        reports = {r.legacy_name: r for r in migrate_client(db, cid, as_of=TODAY, store_map={"Main store": "ST01"})}
        main_, lost = reports["Main store"], reports["Lost shed"]
        assert main_.store_code == "ST01" and main_.opening_number.startswith("OPEN/ST01/")
        assert [(c, q, u, r) for c, q, u, r, _ in main_.lines] == [
            (code["cement"], D("800.000"), "kg", D("7.5000")), (code["tmt12"], D("533.333"), "nos", D("65.6250"))]
        why = dict(main_.skipped)
        assert "negative" in why[code["helmet"]] and "not in the item master" in why["OLD-CODE-1"]
        assert lost.store_code == "" and "--map" in lost.skipped[0][1]
        assert get_balance(db, w.site_id, w.item["cement"]).value == D("6000.00")
        assert get_balance(db, w.site_id, w.item["tmt12"]).value == D("34999.98")                    # 533.333 kg x 65.625
        doc = db.query(DBStoreOpening).filter(DBStoreOpening.number == main_.opening_number).one()
        assert (doc.status, doc.source) == ("POSTED", "LEGACY")
        assert [t.to_status for t in db.query(DBStoreDocStatusLog).filter(DBStoreDocStatusLog.doc_id == doc.id,
                                                                         DBStoreDocStatusLog.doc_type == "OPENING_STOCK")] == ["DRAFT", "POSTED"]

        again = {r.legacy_name: r for r in migrate_client(db, cid, as_of=TODAY, store_map={"Main store": "ST01"}, create_stores=True)}
        assert again["Main store"].lines == [] and again["Main store"].opening_number == ""        # nothing twice
        assert "already has stock history" in dict(again["Main store"].skipped)[code["cement"]]
        created = db.query(DBStore).filter(DBStore.client_id == cid, DBStore.code == "LS01").one()
        made.append(created.id)
        assert created.name == "Lost shed" and again["Lost shed"].lines[0][1] == D("12.000")
        db.commit()
    finally:
        db.rollback()
        docs = [d.id for d in db.query(DBStoreOpening).filter(DBStoreOpening.client_id == cid)]
        if docs:
            db.query(DBStoreOpeningLine).filter(DBStoreOpeningLine.opening_id.in_(docs)).delete(synchronize_session=False)
        db.query(DBStoreOpening).filter(DBStoreOpening.client_id == cid).delete(synchronize_session=False)
        db.query(DBStoreDocStatusLog).filter(DBStoreDocStatusLog.client_id == cid).delete(synchronize_session=False)
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreDocSequence):
            db.query(model).filter(model.store_id.in_(made)).delete(synchronize_session=False)
        db.query(DBStore).filter(DBStore.id.in_(made)).delete(synchronize_session=False)
        db.query(models.DBStockMovement).filter(models.DBStockMovement.client_id == cid).delete(synchronize_session=False)
        db.query(models.DBStockBalance).filter(models.DBStockBalance.client_id == cid).delete(synchronize_session=False)
        db.commit()


def test_the_foundation_upgrade_brings_an_older_database_up_to_it(tmp_path):
    """A database made at store_001_core: the freeze has no count link and the ledger lacks the new indexes."""
    from sqlalchemy import create_engine, inspect, text
    from app.models.store_core import upgrade_store_002_foundation
    engine = create_engine("sqlite:///%s" % (tmp_path / "old.db"))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE store_freeze (id INTEGER PRIMARY KEY, store_id INTEGER, reason VARCHAR)"))
        c.execute(text("CREATE TABLE store_stock_ledger (id INTEGER PRIMARY KEY, store_id INTEGER, item_id INTEGER, txn_date DATE, "
                       "project_id INTEGER, ref_doc_type VARCHAR, ref_doc_id INTEGER, reversal_of_id INTEGER)"))
    done = upgrade_store_002_foundation(engine)
    assert "store_freeze.ref_doc_type" in done and "store_freeze.ref_doc_id" in done
    insp = inspect(engine)
    assert {"ref_doc_type", "ref_doc_id"} <= {c["name"] for c in insp.get_columns("store_freeze")}
    indexes = {i["name"]: i for i in insp.get_indexes("store_stock_ledger")}
    assert indexes["ix_store_ledger_store_item_date"]["column_names"] == ["store_id", "item_id", "txn_date"]
    assert indexes["uq_store_ledger_reversal_of"]["unique"]
    assert upgrade_store_002_foundation(engine) == ["ledger indexes"]          # a second run changes nothing
    engine.dispose()
