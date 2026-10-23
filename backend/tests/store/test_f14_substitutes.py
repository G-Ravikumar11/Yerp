"""An indent line the approver cuts back says why, and may be replaced by another item. The substitute is a line of the indent in its own right: it is
reserved, issued against and closed like any other."""
import uuid
from datetime import date

from app import db as database, models
from app.models.store_core import DBStoreItemSettings, MovementType
from app.services.stock_ledger import post_movement
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401
from decimal import Decimal

TODAY = date.today().isoformat()


def _setup(account, tag):
    t = account["client"]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    with database.SessionLocal() as s:                                    # a second cement grade, 3000 kg in the store
        sub = models.DBItem(client_id=w["client_id"], kind="RM", item_code="SUB-" + tag, item_name="Cement PPC", units_of_measure="kg")
        s.add(sub)
        s.flush()
        s.add(DBStoreItemSettings(item_id=sub.id, category="CONSUMABLE", base_uom="kg"))
        post_movement(s, movement_type=MovementType.OPENING_IN, store_id=central["id"], item_id=sub.id, qty=Decimal("3000"), rate=Decimal("6.5"), txn_date=date.today(), project_id=None,
                      ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        s.commit()
        w["sub"] = sub.id
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "lines": [{"po_line_id": po_line, "qty": "100", "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    ind = ok(t.post("/api/store/outward/indent", json={"store_id": central["id"], "project_id": w["job"], "activity": "Slab", "lines": [{"item_id": w["item"], "qty": "40", "uom": "bag"}]}))
    ok(t.post("/api/store/outward/indent/%d/submit" % ind["id"]))
    return t, w, central, ind


def test_a_cut_needs_a_reason(account):
    t, w, central, ind = _setup(account, uuid.uuid4().hex[:6])
    line = ind["lines"][0]
    url = "/api/store/outward/indent/%d/approve" % ind["id"]
    res = t.post(url, json={"lines": [{"line_id": line["id"], "approved_qty": "25", "uom": "bag"}]})
    assert res.status_code == 400 and "say why" in res.json()["detail"]
    done = ok(t.post(url, json={"lines": [{"line_id": line["id"], "approved_qty": "25", "uom": "bag", "reason": "Budget for this week"}]}))
    assert done["lines"][0]["reason"] == "Budget for this week" and done["lines"][0]["approved_qty"] == "1250.000"


def test_the_approvals_remarks_serve_as_the_reason(account):
    t, w, central, ind = _setup(account, uuid.uuid4().hex[:6])
    line = ind["lines"][0]
    done = ok(t.post("/api/store/outward/indent/%d/approve" % ind["id"], json={"remarks": "Only 25 bags this week", "lines": [{"line_id": line["id"], "approved_qty": "25", "uom": "bag"}]}))
    assert done["lines"][0]["reason"] == "Only 25 bags this week"


def test_a_substitute_is_a_line_of_the_indent_and_is_issued_against(account):
    t, w, central, ind = _setup(account, uuid.uuid4().hex[:6])
    line = ind["lines"][0]
    url = "/api/store/outward/indent/%d/approve" % ind["id"]
    sub_row = {"line_id": line["id"], "approved_qty": "0", "uom": "bag", "reason": "OPC out of stock at the factory", "substitute_item_id": w["sub"], "substitute_qty": "2000", "substitute_uom": "kg"}
    assert t.post(url, json={"lines": [dict(sub_row, substitute_item_id=w["item"])]}).status_code == 400          # not the same item
    assert t.post(url, json={"lines": [dict(sub_row, approved_qty="40")]}).status_code == 400                      # the original is not cut
    assert t.post(url, json={"lines": [dict(sub_row, substitute_qty="")]}).status_code == 400
    assert t.post(url, json={"lines": [dict(sub_row, reason="")]}).status_code == 400
    done = ok(t.post(url, json={"lines": [sub_row]}))
    assert len(done["lines"]) == 2
    orig, sub = done["lines"]
    assert orig["approved_qty"] == "0.000" and sub["item_name"] == "Cement PPC" and sub["approved_qty"] == "2000.000" and sub["substitute_for_line_id"] == orig["id"]
    assert sub["reason"] == "OPC out of stock at the factory" and sub["purpose"] == "Substitute for Cement OPC"

    # Its 2000 kg is reserved: others cannot take it, the indent's own issue can.
    [pos] = [r for r in ok(t.get("/api/store/enquiry/balances", params={"store_id": central["id"]}))["items"] if r["item_name"] == "Cement PPC"]
    assert pos["reserved"] == "2000.000" and pos["available"] == "1000.000"
    body = {"store_id": central["id"], "issue_date": TODAY, "project_id": w["job"], "indent_id": ind["id"], "received_by_type": "FOREMAN", "received_by_name": "Suresh",
            "lines": [{"item_id": w["sub"], "qty": "2000", "uom": "kg", "cost_head": "OVERHEAD", "indent_line_id": sub["id"]}]}
    issue = ok(t.post("/api/store/outward/issue", json=body))
    walk(t, "outward", "issue", issue["id"], "submit", "approve", "post")
    closed = ok(t.get("/api/store/outward/indent/%d" % ind["id"]))
    assert closed["status"] == "CLOSED"                                                                           # the cut-to-nothing original does not hold it open
