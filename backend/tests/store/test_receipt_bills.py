"""A draft supplier bill drawn from a Store Hub receipt: from the Invoice Tracker or the receipt itself, never twice."""
import uuid

from app import db as database, models
from store.test_cutover import TODAY, _company, _hub, ok, walk  # noqa: F401


def _received(t, w, central, bags="10", rejected=""):
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={
        "store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "project_id": w["job"], "supplier_name": "Shree Traders",
        "challan_no": "CH-77", "lines": [{"po_line_id": po_line, "qty": bags, "uom": "bag", "rate": "350", "rejected_qty": rejected,
                                          "reject_reason": "Wet" if rejected else ""}]}))
    return grn


def test_a_hub_receipt_becomes_a_draft_bill_once(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    grn = _received(t, w, central)
    assert t.post("/api/invoice-tracker/invoices/%d/bill" % -grn["id"]).status_code == 409, "a draft receipt is not billed"
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    assert ok(t.get("/api/invoice-tracker/invoices/%d/bill" % -grn["id"]))["billable"] is True

    res = ok(t.post("/api/invoice-tracker/invoices/%d/bill" % -grn["id"]))
    bill = res["bill"]
    assert bill["status"] == "Draft" and bill["vendor_name"] == "Shree Traders" and bill["grn_id"] == -grn["id"]
    assert bill["purchase_order_id"] == w["pos"][0][0] and bill["job_id"] == w["job"]
    with database.SessionLocal() as s:
        lines = s.query(models.DBBillLineItem).filter(models.DBBillLineItem.bill_id == bill["id"]).all()
        assert [(l.po_line_id, l.grn_line_id) for l in lines] == [(w["pos"][0][1], -grn["lines"][0]["id"])]
        assert round(lines[0].qty * lines[0].price, 2) == 3500, "10 bags at 350, billed per kg"
        assert s.get(models.DBBill, bill["id"]).amount == 3500

    again = t.post("/api/invoice-tracker/invoices/%d/bill" % -grn["id"])
    assert again.status_code == 409 and bill["number"] in again.json()["detail"]
    state = ok(t.get("/api/invoice-tracker/invoices/%d/bill" % -grn["id"]))
    assert state["billable"] is False and [b["number"] for b in state["bills"]] == [bill["number"]]
    inv = [i for i in ok(t.get("/api/invoice-tracker"))["invoices"] if i["grn_id"] == -grn["id"]][0]
    assert inv["billable"] is False and inv["bills"][0]["id"] == bill["id"]


def test_what_a_cut_down_or_rejected_bill_left_can_be_billed(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    grn = _received(t, w, central)
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    first = ok(t.post("/api/invoice-tracker/invoices/%d/bill" % -grn["id"]))["bill"]
    with database.SessionLocal() as s:
        line = s.query(models.DBBillLineItem).filter(models.DBBillLineItem.bill_id == first["id"]).one()
        line.qty = line.qty * 0.6                       # accounts billed six bags of the ten on this bill
        s.commit()
    second = ok(t.post("/api/invoice-tracker/invoices/%d/bill" % -grn["id"]))["bill"]
    assert second["total"] == 1400 and second["reference"].endswith("/2"), "the other four bags"
    assert t.post("/api/invoice-tracker/invoices/%d/bill" % -grn["id"]).status_code == 409

    with database.SessionLocal() as s:
        s.get(models.DBBill, second["id"]).status = "Rejected"
        s.commit()
    assert ok(t.post("/api/invoice-tracker/invoices/%d/bill" % -grn["id"]))["bill"]["total"] == 1400


def test_only_the_accepted_quantity_is_billed(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    grn = _received(t, w, central, bags="10", rejected="2")      # two bags came wet
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    assert ok(t.post("/api/invoice-tracker/invoices/%d/bill" % -grn["id"]))["bill"]["total"] == 2800
