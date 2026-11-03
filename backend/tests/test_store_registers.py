"""The four store registers: stock with when it last came in, posted receipts and posted issues line by line, and what is low."""
import uuid
from datetime import date, timedelta

from store.test_batches import TODAY, _issue, _receive
from store.test_cutover import _company, _hub, ok  # noqa: F401


def test_the_registers_show_what_came_in_went_out_and_is_left(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    grn = _receive(t, central, w["item"], "R-1", TODAY - timedelta(days=5))
    issued = ok(_issue(t, central, w, "R-1", qty="20"))

    stock = ok(t.get("/api/store/enquiry/balances?store_id=%d" % central["id"]))["items"]
    row = [r for r in stock if r["item_id"] == w["item"]][0]
    assert row["last_received"] == date.today().isoformat() and row["store_name"]

    rec = ok(t.get("/api/store/enquiry/receipts?store_id=%d" % central["id"]))["items"]
    line = [r for r in rec if r["grn_id"] == grn["id"]][0]
    assert line["number"] == grn["number"] and line["supplier"] == "Shree Traders" and float(line["qty"]) > 0 and line["uom"] and line["date"] == TODAY.isoformat()

    out = ok(t.get("/api/store/enquiry/issues?store_id=%d" % central["id"]))["items"]
    line = [r for r in out if r["issue_id"] == issued["id"]][0]
    assert line["number"] == issued["number"] and line["project"] and line["used_for"] == "Overhead" and line["received_by"] == "Suresh"

    assert ok(t.get("/api/store/enquiry/receipts?q=nothing-like-this"))["items"] == []


def test_a_draft_is_listed_with_its_status_and_a_cancelled_one_is_not(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    draft = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY.isoformat(), "supplier_name": "Draft Traders",
                                                     "lines": [{"item_id": w["item"], "qty": "5", "uom": "bag", "rate": "350"}]}))
    assert [r["status"] for r in ok(t.get("/api/store/enquiry/receipts"))["items"] if r["grn_id"] == draft["id"]] == ["DRAFT"]
    ok(t.post("/api/store/inward/grn/%d/cancel" % draft["id"], json={"reason": "Entered twice"}))
    assert not [r for r in ok(t.get("/api/store/enquiry/receipts"))["items"] if r["grn_id"] == draft["id"]]
