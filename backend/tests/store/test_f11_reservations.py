"""Stock promised to an approved indent is held back: others cannot issue, transfer or scrap it, the indent's own issue can, and the stock
position shows reserved and available."""
import uuid
from datetime import date

from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()


def _receive(t, central, w, bags):
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "lines": [{"po_line_id": po_line, "qty": str(bags), "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")


def _indent(t, central, w, bags):
    i = ok(t.post("/api/store/outward/indent", json={"store_id": central["id"], "project_id": w["job"], "activity": "Slab casting", "lines": [{"item_id": w["item"], "qty": str(bags), "uom": "bag"}]}))
    ok(t.post("/api/store/outward/indent/%d/submit" % i["id"]))
    return ok(t.post("/api/store/outward/indent/%d/approve" % i["id"], json={}))


def _issue_body(central, w, bags, **over):
    body = {"store_id": central["id"], "issue_date": TODAY, "project_id": w["job"], "received_by_type": "FOREMAN", "received_by_name": "Suresh",
            "lines": [{"item_id": w["item"], "qty": str(bags), "uom": "bag", "cost_head": "OVERHEAD"}]}
    body.update(over)
    return body


def _position(t, central):
    [row] = ok(t.get("/api/store/enquiry/balances", params={"store_id": central["id"]}))["items"]
    return row


def test_an_approved_indent_holds_its_stock_back(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 100)                                       # 100 bags = 5000 kg
    indent = _indent(t, central, w, 60)                                # 3000 kg reserved
    row = _position(t, central)
    assert row["qty"] == "5000.000" and row["reserved"] == "3000.000" and row["available"] == "2000.000"

    # Someone else's issue may take the free 40 bags, not more.
    too_much = ok(t.post("/api/store/outward/issue", json=_issue_body(central, w, 50)))
    res = t.post("/api/store/outward/issue/%d/submit" % too_much["id"])
    assert res.status_code == 409 and "promised to approved indents" in res.json()["detail"]
    fine = ok(t.post("/api/store/outward/issue", json=_issue_body(central, w, 40)))
    walk(t, "outward", "issue", fine["id"], "submit", "approve", "post")
    assert _position(t, central)["available"] == "0.000"

    # The indent's own issue uses its reservation.
    line = indent["lines"][0]
    own = ok(t.post("/api/store/outward/issue", json=_issue_body(central, w, 60, indent_id=indent["id"], lines=[{"item_id": w["item"], "qty": "60", "uom": "bag", "cost_head": "OVERHEAD", "indent_line_id": line["id"]}])))
    walk(t, "outward", "issue", own["id"], "submit", "approve", "post")
    [row] = ok(t.get("/api/store/enquiry/balances", params={"store_id": central["id"], "include_zero": True}))["items"]
    assert row["qty"] == "0.000" and row["reserved"] == "0.000"                                 # the indent is filled: nothing is promised any more


def test_a_transfer_cannot_take_reserved_stock(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    site = ok(t.post("/api/store/masters/stores", json={"code": "ST" + tag[:3].upper(), "name": "Site", "type": "SITE"}))
    _receive(t, central, w, 100)
    _indent(t, central, w, 80)                                         # 4000 kg reserved, 1000 free
    doc = ok(t.post("/api/store/control/transfer", json={"store_id": central["id"], "to_store_id": site["id"], "transfer_date": TODAY, "lines": [{"item_id": w["item"], "qty": "30", "uom": "bag"}]}))
    res = t.post("/api/store/control/transfer/%d/submit" % doc["id"])
    assert res.status_code == 409 and "promised to approved indents" in res.json()["detail"]


def test_a_cancelled_indent_frees_its_stock(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 100)
    indent = _indent(t, central, w, 80)
    assert _position(t, central)["available"] == "1000.000"
    ok(t.post("/api/store/outward/indent/%d/cancel" % indent["id"], json={"reason": "Not needed"}))
    assert _position(t, central)["reserved"] == "0.000"


def test_an_indent_shows_what_the_store_can_spare_and_what_must_be_bought(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 100)                                       # 5000 kg on hand
    _indent(t, central, w, 70)                                         # another indent holds 3500 kg
    mine = _indent(t, central, w, 50)                                  # this one wants 2500 kg: 1500 can be spared, 1000 is short
    [line] = ok(t.get("/api/store/outward/indent/%d" % mine["id"]))["lines"]
    assert (line["pending"], line["available"], line["short"]) == ("2500.000", "1500.000", "1000.000")
    # A draft has nothing approved yet, so nothing is short.
    draft = ok(t.post("/api/store/outward/indent", json={"store_id": central["id"], "project_id": w["job"], "activity": "Plaster", "lines": [{"item_id": w["item"], "qty": "1", "uom": "bag"}]}))
    [d] = ok(t.get("/api/store/outward/indent/%d" % draft["id"]))["lines"]
    assert d["available"] is None and d["short"] is None


def test_an_indent_enquiry_and_order_stay_linked_and_nothing_is_bought_twice(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 40)                                        # 2000 kg on hand
    indent = _indent(t, central, w, 60)                                # wants 3000 kg: 1000 short
    [line] = ok(t.get("/api/store/outward/indent/%d" % indent["id"]))["lines"]
    assert (line["short"], line["on_order"], line["bought_on"]) == ("1000.000", "0.000", [])

    # "Buy the short items": an enquiry line that names the indent line.
    body = {"title": "Short for %s" % indent["number"], "job_id": w["job"],
            "lines": [{"item_code": w["code"], "description": "Cement OPC", "uom": "kg", "qty": 1000, "indent_line_id": line["id"]}]}
    first = ok(t.post("/api/rfqs", json=body))
    number = first["rfq"]["number"]
    [line] = ok(t.get("/api/store/outward/indent/%d" % indent["id"]))["lines"]
    assert (line["short"], line["on_order"], line["bought_on"]) == ("0.000", "1000.000", [number])

    # Pressed again: nothing new is raised.
    again = t.post("/api/rfqs", json=body)
    assert again.status_code == 409 and number in again.json()["detail"]

    # Awarded: the order line carries the enquiry line and the indent line, and the indent shows the order.
    r = t.get("/api/rfqs/%d" % first["rfq"]["id"]).json()
    rfq_line = r["lines"][0]
    assert rfq_line["indent_line_id"] == line["id"]
    ok(t.post("/api/rfqs/%d/quotes" % first["rfq"]["id"], json={"supplier_name": "Shree Traders", "freight": 0,
                                                                "lines": [{"rfq_line_id": rfq_line["rfq_line_id"], "rate": 7, "tax_percent": 18}]}))
    award = ok(t.post("/api/rfqs/%d/award" % first["rfq"]["id"], json={"mode": "lowest_per_line"}))
    po_number = award["orders"][0]["number"]
    from app import db as database, models
    with database.SessionLocal() as s:
        [pl] = s.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == award["orders"][0]["id"]).all()
        assert (pl.rfq_line_id, pl.indent_line_id) == (rfq_line["rfq_line_id"], line["id"])
    [line] = ok(t.get("/api/store/outward/indent/%d" % indent["id"]))["lines"]
    assert (line["short"], line["bought_on"]) == ("0.000", [po_number])
    assert t.post("/api/rfqs", json=body).status_code == 409


def test_an_enquiry_cannot_name_another_companys_indent_line(account, second_tenant):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 10)
    indent = _indent(t, central, w, 5)
    [line] = ok(t.get("/api/store/outward/indent/%d" % indent["id"]))["lines"]
    res = second_tenant.post("/api/rfqs", json={"title": "Not mine", "lines": [{"description": "Cement", "qty": 1, "indent_line_id": line["id"]}]})
    assert res.status_code == 404


def test_an_indent_nobody_is_buying_for_needs_you_until_it_is_bought(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 10)                                        # 500 kg
    indent = _indent(t, central, w, 30)                                # wants 1500 kg: 1000 short
    kinds = lambda: {i["kind"]: i for i in ok(t.get("/api/attention"))["items"]}
    assert indent["number"] in kinds()["indents_unbought"]["detail"]
    [line] = ok(t.get("/api/store/outward/indent/%d" % indent["id"]))["lines"]
    ok(t.post("/api/rfqs", json={"title": "Short", "lines": [{"item_code": w["code"], "description": "Cement", "uom": "kg", "qty": 1000, "indent_line_id": line["id"]}]}))
    assert "indents_unbought" not in kinds()
