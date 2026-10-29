"""The Store skeleton end to end: posting IN / OUT / reversal and checking balances, the guards, numbering, access and
that every store route answers."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app import models
from app.models.store_core import (
    DBStoreStockLedger, InsufficientStockError, InvalidMovementError, MovementType, StoreFrozenError,
)
from app.services.stock_ledger import (
    assert_store_access, convert_to_base, freeze_store, get_balance, post_movement, reverse_document, unfreeze_store,
)
from app.services.store_numbering import next_doc_number
from store.fixtures import db, store_world  # noqa: F401  (fixtures)

D = Decimal
TODAY = date.today()


def post(db, w, mtype, qty, rate=None, store=None, item="cement", doc=("GRN", 10), **kw):
    return post_movement(db, movement_type=mtype, store_id=store or w.central_id, item_id=w.item[item], qty=qty, rate=rate,
                         txn_date=TODAY, project_id=kw.pop("project_id", None), ref_doc_type=doc[0], ref_doc_id=doc[1],
                         ref_line_id=kw.pop("ref_line_id", 1), user_id=kw.pop("user_id", None), **kw)


def test_opening_stock_was_posted_through_the_ledger(db, store_world):
    w = store_world
    bal = get_balance(db, w.central_id, w.item["cement"])
    assert (bal.qty, bal.value, bal.avg_rate) == (D("5000.000"), D("35000.00"), D("7.0000"))
    assert get_balance(db, w.site_id, w.item["cement"]).qty == 0
    assert len(w.item) == 10 and len(w.po_line_ids) == 3 and len(w.boq_item_ids) == 2


def test_in_out_and_reversal_keep_the_balance_right(db, store_world):
    w = store_world
    e = post(db, w, MovementType.GRN_IN, D("1000"), D("8"))                      # 5000 @ 7 + 1000 @ 8
    assert (e.qty_in, e.value, e.running_qty, e.avg_rate) == (D("1000"), D("8000.00"), D("6000"), D("7.1667"))
    out = post(db, w, MovementType.ISSUE_OUT, D("600"), None, doc=("ISSUE", 5), project_id=w.project_id,
               work_order_id=w.work_order_id, boq_item_id=w.boq_item_ids[0], cost_head="SAFETY")
    assert out.qty_out == D("600") and out.rate == D("7.1667") and out.value == D("4300.02")      # valued at the average
    assert out.cost_head == "SAFETY" and out.project_id == w.project_id
    bal = get_balance(db, w.central_id, w.item["cement"])
    assert (bal.qty, bal.value) == (D("5400.000"), D("38699.98"))

    undone = reverse_document(db, ref_doc_type="ISSUE", ref_doc_id=5, user_id=None, reason="issued to wrong site")
    assert len(undone) == 1 and undone[0].reversal_of_id == out.id and undone[0].qty_in == D("600")
    assert get_balance(db, w.central_id, w.item["cement"]).qty == D("6000.000")
    assert get_balance(db, w.central_id, w.item["cement"]).value == D("43000.00")
    with pytest.raises(InvalidMovementError):                                    # not twice
        reverse_document(db, ref_doc_type="ISSUE", ref_doc_id=5, user_id=None, reason="again")

    reverse_document(db, ref_doc_type="GRN", ref_doc_id=10, user_id=None, reason="wrong supplier")
    bal = get_balance(db, w.central_id, w.item["cement"])
    assert (bal.qty, bal.value) == (D("5000.000"), D("35000.00"))
    assert bal.avg_rate == D("7.0000")             # the dearer receipt undone, the average is back where it was
    ledger = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.item_id == w.item["cement"]).all()
    assert sum(r.qty_in - r.qty_out for r in ledger) == bal.qty
    assert sum(r.value if r.qty_in else -r.value for r in ledger) == bal.value       # the ledger always adds up to the balance


def test_taking_everything_out_leaves_no_residue(db, store_world):
    w = store_world
    post(db, w, MovementType.GRN_IN, D("3"), D("33.3333"), item="diesel")
    post(db, w, MovementType.ISSUE_OUT, D("1003"), None, item="diesel", doc=("ISSUE", 6))
    bal = get_balance(db, w.central_id, w.item["diesel"])
    assert (bal.qty, bal.value) == (0, 0)


def test_stock_cannot_go_negative_and_a_rate_is_needed_on_in_only(db, store_world):
    w = store_world
    with pytest.raises(InsufficientStockError):
        post(db, w, MovementType.ISSUE_OUT, D("5000.001"), None)
    with pytest.raises(InvalidMovementError):
        post(db, w, MovementType.GRN_IN, D("5"), None)                           # IN without a rate
    with pytest.raises(InvalidMovementError):
        post(db, w, MovementType.ISSUE_OUT, D("5"), D("7"))                      # OUT with a rate
    with pytest.raises(InvalidMovementError):
        post(db, w, MovementType.GRN_IN, D("0"), D("7"))
    assert get_balance(db, w.central_id, w.item["cement"]).qty == D("5000.000")


def test_a_frozen_store_takes_deliveries_but_nothing_leaves(db, store_world):
    w = store_world
    freeze_store(db, w.central_id, "annual count", user_id=None)
    post(db, w, MovementType.GRN_IN, D("1"), D("7"), doc=("GRN", 77))                 # the lorry is not turned away
    for mtype, rate in ((MovementType.ISSUE_OUT, None), (MovementType.ADJUST_IN, D("7")), (MovementType.TRANSFER_OUT, None)):
        with pytest.raises(StoreFrozenError):
            post(db, w, mtype, D("1"), rate)
    with pytest.raises(StoreFrozenError):
        reverse_document(db, ref_doc_type="GRN", ref_doc_id=77, user_id=None, reason="no")
    with pytest.raises(InvalidMovementError):
        freeze_store(db, w.central_id, "twice", user_id=None)
    unfreeze_store(db, w.central_id, user_id=None)
    post(db, w, MovementType.ISSUE_OUT, D("1"), None)


def test_a_transfer_pair_reverses_together_or_not_at_all(db, store_world):
    w = store_world
    out = post(db, w, MovementType.TRANSFER_OUT, D("100"), None, doc=("TRANSFER", 3))
    post(db, w, MovementType.TRANSFER_IN, D("100"), out.rate, store=w.site_id, doc=("TRANSFER", 3))
    post(db, w, MovementType.ISSUE_OUT, D("60"), None, store=w.site_id, doc=("ISSUE", 9))      # the site used some
    with pytest.raises(InsufficientStockError):
        reverse_document(db, ref_doc_type="TRANSFER", ref_doc_id=3, user_id=None, reason="oops")
    assert get_balance(db, w.central_id, w.item["cement"]).qty == D("4900.000")                 # nothing half-done
    assert get_balance(db, w.site_id, w.item["cement"]).qty == D("40.000")


def test_unit_conversion(db, store_world):
    w = store_world
    assert convert_to_base(db, w.item["cement"], 3, "bag") == D("150.000")
    assert convert_to_base(db, w.item["cement"], 2, "MT") == D("2000.000")
    assert convert_to_base(db, w.item["cement"], 7, "kg") == D("7.000")
    assert convert_to_base(db, w.item["tmt12"], 10, "nos") == D("106.667")                      # 12 x 12 / 162 x 12 m
    assert convert_to_base(db, w.item["tmt16"], 10, "nos") == D("189.630")
    with pytest.raises(InvalidMovementError):
        convert_to_base(db, w.item["sand"], 1, "bag")


def test_document_numbers_follow_the_indian_financial_year(db, store_world):
    w = store_world
    assert next_doc_number(db, "GRN", w.central_id, on_date="2026-10-17") == "GRN/CS01/26-27/00001"
    assert next_doc_number(db, "GRN", w.central_id, on_date="2026-10-18") == "GRN/CS01/26-27/00002"
    assert next_doc_number(db, "GRN", w.central_id, on_date="2027-03-31") == "GRN/CS01/26-27/00003"
    assert next_doc_number(db, "GRN", w.central_id, on_date="2027-04-01") == "GRN/CS01/27-28/00001"
    assert next_doc_number(db, "ISSUE", w.central_id, on_date="2026-10-17") == "ISSUE/CS01/26-27/00001"
    assert next_doc_number(db, "GRN", w.site_id, on_date="2026-10-17") == "GRN/ST01/26-27/00001"
    with pytest.raises(InvalidMovementError):
        next_doc_number(db, "grn", w.central_id)


def test_store_access(db, store_world):
    w = store_world
    emp = lambda k: db.get(models.DBEmployee, w.staff[k])           # noqa: E731
    assert_store_access(emp("central_keeper"), w.central_id)
    assert_store_access(emp("admin"), w.site_id)                    # store.admin reaches every store
    assert_store_access(db.get(models.DBClient, w.client_id), w.site_id)
    for who, store in (("central_keeper", w.site_id), ("unassigned", w.central_id), ("site_keeper", w.central_id)):
        with pytest.raises(HTTPException) as err:
            assert_store_access(emp(who), store)
        assert err.value.status_code == 403


def test_every_store_route_answers(account, db):
    tenant = account["client"]
    for slice_ in ("masters", "enquiry", "inward", "outward", "control", "reports"):
        res = tenant.get("/api/store/%s" % slice_)
        assert res.status_code == 200, (slice_, res.text)
        assert res.json() == {"slice": slice_, "items": []}
    assert tenant.get("/api/store/lookup/stores").json() == {"stores": []}
    assert tenant.get("/api/store/lookup/items").json() == {"items": []}
    assert "GRN_IN" in tenant.get("/api/store/lookup/meta").json()["movement_types"]


def test_staff_routes_follow_the_store_rights_and_assignments(account, portal):
    """A member of staff with one right opens that slice only, and the pickers list only the stores they are assigned to."""
    import uuid
    from conftest import make_employee
    from app import db as database
    from app.models.store_core import DBStore, DBStoreUserAssignment
    email = "keeper-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = "store.inward.view"
        mine = DBStore(client_id=row.client_id, code="XA1", name="Assigned", type="SITE")
        other = DBStore(client_id=row.client_id, code="XB1", name="Not assigned", type="SITE")
        s.add_all([mine, other])
        s.flush()
        s.add(DBStoreUserAssignment(store_id=mine.id, employee_id=row.id))
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
    assert portal.get("/api/store/inward").status_code == 200
    assert portal.get("/api/store/outward").status_code == 403
    assert [x["code"] for x in portal.get("/api/store/lookup/stores").json()["stores"]] == ["XA1"]
