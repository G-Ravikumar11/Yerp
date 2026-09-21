"""Every bill and order carries what its printed page needs.

The RA bill is the document the business lives on, and until now the only
way to see one was to download a workbook. The page needs the parties, the
figure in words, and an up-to-date value per line beside this bill's - so
the API hands them over, and the page is drawn from that, never assembled
by hand.
"""
from test_measurement_and_ra_bills import placed_order, book, measure
from test_subcontractor_bills import live_order, book as sub_book, measure as sub_measure, raise_bill
from test_goods_receipt import order as po_order, receipt


def certified(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 250)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    return tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]


def test_the_ra_bill_names_both_parties_and_states_the_figure_twice(tenant):
    tenant.put("/api/gst/settings", json={"gstin": "36AABCY1234H1ZX"})
    b = certified(tenant)
    assert b["our"]["gstin"] == "36AABCY1234H1ZX"
    assert b["our"]["name"]
    assert b["client_party"]["name"]
    assert b["amount_in_words"].startswith("Rupees")
    assert b["work_order_detail"]["number"] == b["work_order"]


def test_each_line_carries_its_up_to_date_value(tenant):
    """The abstract shows this bill's amount beside the value to date."""
    b = certified(tenant)
    line = b["lines"][0]
    assert line["upto_date_amount"] == round(line["measured_to_date"] * line["rate"], 2)
    assert line["amount"] == round(line["this_bill_qty"] * line["rate"], 2)


def test_the_gangs_bill_names_the_contractor_and_the_order(tenant):
    order = live_order(tenant, retention_percent=5)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 100)
    b = raise_bill(tenant, order["id"]).json()["bill"]
    b = tenant.get("/api/sub-bills/%d" % b["id"]).json()
    assert b["contractor_detail"]["name"].startswith("Sri Balaji")
    assert b["contractor_detail"]["gstin"].startswith("36")
    assert b["order_detail"]["number"] == order["wo_number"]
    assert b["order_detail"]["retention_percent"] == 5
    assert b["amount_in_words"].startswith("Rupees")
    assert b["lines"][0]["upto_date_amount"] == round(100 * b["lines"][0]["rate"], 2)


def test_the_purchase_order_page_has_its_header_and_words(tenant):
    po = po_order(tenant)
    d = tenant.get("/api/purchase-orders/%d" % po["id"]).json()
    assert "our" in d and d["our"]["name"]
    assert d["amount_in_words"].startswith("Rupees")
    assert "deliver_to" in d


def test_a_goods_receipt_prints_from_its_own_payload(tenant):
    grn = receipt(tenant, po_order(tenant))
    d = tenant.get("/api/grn/%d" % grn["id"]).json()
    assert d["number"] == grn["number"]
    assert "lines" in d and "accepted_value" in d
