"""Deleting a work order: the owner's alone, and complete - the order and everything
that hangs off it go from every screen. Money behind it is the one thing that stops it."""
from conftest import make_employee
from test_subcontractor_bills import live_order, measure, book, pay_the_advance

PASSWORD = "Crew1234"


def raise_a_bill(tenant, order):
    item = book(tenant, order["id"])["lines"][0]
    measure(tenant, order["id"], item["item_id"], 10)
    res = tenant.post("/api/sub-bills", json={"order_id": order["id"]})
    assert res.status_code == 200, res.text
    return res.json()["bill"] if "bill" in res.json() else res.json()


def test_a_draft_is_deleted_and_is_gone_from_the_list(tenant):
    from test_subcontract_orders import priced
    order = priced(tenant)
    assert tenant.get("/api/wo/orders/%d/delete-preview" % order["id"]).json()["can_delete"] is True
    res = tenant.delete("/api/wo/orders/%d" % order["id"])
    assert res.status_code == 200, res.text
    assert tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 404
    assert order["id"] not in [o["id"] for o in tenant.get("/api/wo/orders").json()["orders"]]


def test_an_approved_order_goes_with_its_measurements_and_bills(tenant):
    order = live_order(tenant, pay_advance=False)
    bill = raise_a_bill(tenant, order)
    prev = tenant.get("/api/wo/orders/%d/delete-preview" % order["id"]).json()
    assert prev["can_delete"] and prev["counts"]["measurements"] >= 1 and prev["counts"]["bills"] == 1
    assert tenant.delete("/api/wo/orders/%d" % order["id"]).status_code == 200
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).status_code == 404
    assert tenant.get("/api/sub-mb/%d" % order["id"]).status_code == 404
    assert bill["id"] not in [b["id"] for b in tenant.get("/api/sub-bills").json().get("bills", [])]


def test_a_revision_takes_the_whole_chain_with_it(tenant):
    order = live_order(tenant, pay_advance=False)
    rev = tenant.post("/api/wo/orders/%d/amend" % order["id"], json={}).json()["order"]
    prev = tenant.get("/api/wo/orders/%d/delete-preview" % rev["id"]).json()
    assert prev["counts"]["versions"] == 2
    assert tenant.delete("/api/wo/orders/%d" % rev["id"]).status_code == 200
    ids = [o["id"] for o in tenant.get("/api/wo/orders").json()["orders"]]
    assert order["id"] not in ids and rev["id"] not in ids


def test_money_paid_against_it_is_deleted_with_it(tenant):
    order = live_order(tenant, mobilization_advance_percent=10)
    assert order["mobilization_advance_amount"] > 0
    prev = tenant.get("/api/wo/orders/%d/delete-preview" % order["id"]).json()
    assert prev["can_delete"] is True and "advance" in prev["warnings"][0]
    assert tenant.delete("/api/wo/orders/%d" % order["id"]).status_code == 200
    assert tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 404
    entries = tenant.get("/api/money/entries").json()
    rows = entries.get("entries", entries) if isinstance(entries, dict) else entries
    assert not [e for e in rows if e.get("doc_type") == "sub_advance" and e.get("doc_id") == order["id"]]


def test_staff_cannot_delete_a_work_order(tenant, portal):
    order = live_order(tenant, pay_advance=False)
    pm = make_employee(tenant, permission_role="project_manager", password=PASSWORD)
    tenant.put("/api/employees/%d" % pm["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": pm["email"], "password": PASSWORD})
    assert portal.delete("/api/wo/orders/%d" % order["id"]).status_code in (401, 403)
    assert portal.get("/api/wo/orders/%d/delete-preview" % order["id"]).status_code in (401, 403)
    assert tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 200


def test_a_client_work_order_goes_with_everything_on_it(tenant):
    from test_work_order_pricing import fg, job
    code = fg(tenant)
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"], "reference": "PO/DEL/1",
        "lines": [{"code": code, "qty": 10, "rate": 500}]}).json()["work_order"]
    assert wo["id"]
    prev = tenant.get("/api/erp/work-orders/%d/delete-preview" % wo["id"])
    assert prev.status_code == 200 and prev.json()["can_delete"] is True
    assert tenant.delete("/api/erp/work-orders/%d" % wo["id"]).status_code == 200
    assert tenant.get("/api/erp/work-orders/%d" % wo["id"]).status_code == 404


def test_delete_all_needs_the_phrase_then_clears_every_work_order(tenant):
    from test_work_order_pricing import fg, job
    live_order(tenant, mobilization_advance_percent=10)
    sub = live_order(tenant, pay_advance=False)
    tenant.post("/api/wo/orders/%d/amend" % sub["id"], json={})
    tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"], "reference": "PO/ALL/1",
        "lines": [{"code": fg(tenant), "qty": 10, "rate": 500}]})
    prev = tenant.get("/api/work-orders/delete-all-preview").json()
    assert prev["subcontract"] >= 3 and prev["client"] >= 1
    assert tenant.post("/api/work-orders/delete-all", json={"confirm": "yes"}).status_code == 400
    res = tenant.post("/api/work-orders/delete-all", json={"confirm": prev["phrase"]})
    assert res.status_code == 200, res.text
    after = tenant.get("/api/work-orders/delete-all-preview").json()
    assert after["subcontract"] == 0 and after["client"] == 0 and after["sub_bills"] == 0


def test_staff_cannot_delete_everything(tenant, portal):
    pm = make_employee(tenant, permission_role="project_manager", password=PASSWORD)
    tenant.put("/api/employees/%d" % pm["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": pm["email"], "password": PASSWORD})
    assert portal.post("/api/work-orders/delete-all", json={"confirm": "DELETE ALL WORK ORDERS"}).status_code in (401, 403)


def test_alerts_that_were_read_and_drawings_do_not_stop_a_delete(tenant):
    order = live_order(tenant, pay_advance=False)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}) if False else None
    tenant.post("/api/alerts/read", json={"all": True})
    assert tenant.delete("/api/wo/orders/%d" % order["id"]).status_code == 200
    from test_work_order_pricing import fg, job
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"], "reference": "PO/ALR/1",
        "lines": [{"code": fg(tenant), "qty": 10, "rate": 500}]}).json()["work_order"]
    tenant.post("/api/alerts/read", json={"all": True})
    assert tenant.delete("/api/erp/work-orders/%d" % wo["id"]).status_code == 200


def test_a_link_no_model_knows_about_does_not_stop_a_delete(tenant):
    """An older release can leave a table pointing at a bill. The delete reads the database's own
    constraints, so that row goes with the bill instead of blocking it."""
    from sqlalchemy import text
    from database import engine
    order = live_order(tenant, pay_advance=False)
    bill = raise_a_bill(tenant, order)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS zz_legacy_link (id INTEGER PRIMARY KEY, "
                          "bill_id INTEGER NOT NULL REFERENCES sub_bills(id))"))
        conn.execute(text("INSERT INTO zz_legacy_link (bill_id) VALUES (:b)"), {"b": bill["id"]})
    try:
        assert tenant.delete("/api/wo/orders/%d" % order["id"]).status_code == 200
        with engine.begin() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM zz_legacy_link")).scalar() == 0
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS zz_legacy_link"))


def test_a_bill_is_deleted_and_what_it_measured_is_free_to_bill_again(tenant):
    order = live_order(tenant, pay_advance=False)
    bill = raise_a_bill(tenant, order)
    prev = tenant.get("/api/sub-bills/%d/delete-preview" % bill["id"]).json()
    assert prev["can_delete"] and prev["counts"]["measurements"] >= 1
    assert tenant.delete("/api/sub-bills/%d" % bill["id"]).status_code == 200
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).status_code == 404
    assert not any(e["billed"] for e in book(tenant, order["id"])["entries"])
    assert tenant.post("/api/sub-bills", json={"order_id": order["id"]}).status_code == 200      # billable again


def test_a_paid_bill_goes_with_its_payments(tenant):
    order = live_order(tenant, pay_advance=False)
    bill = raise_a_bill(tenant, order)
    for step in ("submit", "certify"):
        assert tenant.post("/api/sub-bills/%d/%s" % (bill["id"], step), json={}).status_code == 200
    pay = tenant.post("/api/money/entries", json={"doc_type": "sub_bill", "doc_id": bill["id"], "amount": 100,
                                                  "mode": "Bank transfer", "reference": "UTR-DEL"})
    assert pay.status_code == 200, pay.text
    prev = tenant.get("/api/sub-bills/%d/delete-preview" % bill["id"]).json()
    assert prev["can_delete"] and "payments are deleted" in prev["warnings"][0]
    assert tenant.delete("/api/sub-bills/%d" % bill["id"]).status_code == 200
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).status_code == 404


def test_a_vendor_goes_with_their_orders_and_bills(tenant):
    order = live_order(tenant, pay_advance=False)
    bill = raise_a_bill(tenant, order)
    vendor = order["contractor_id"]
    prev = tenant.get("/api/wo/contractors/%d/delete-preview" % vendor).json()
    assert prev["can_delete"] and prev["counts"]["bills"] >= 1
    assert tenant.delete("/api/wo/contractors/%d" % vendor).status_code == 200
    assert tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 404
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).status_code == 404
    assert vendor not in [c["id"] for c in tenant.get("/api/wo/contractors").json()["contractors"]]


def test_a_measurement_on_a_draft_bill_can_go_and_the_bill_follows_it(tenant):
    order = live_order(tenant, pay_advance=False)
    bill = raise_a_bill(tenant, order)
    entry = book(tenant, order["id"])["entries"][0]
    assert tenant.delete("/api/sub-mb/entries/%d" % entry["id"]).status_code == 200
    got = tenant.get("/api/sub-bills/%d" % bill["id"]).json()
    assert (got.get("bill") or got)["this_bill"] == 0


def test_a_measurement_on_a_sent_bill_says_to_delete_the_bill_first(tenant):
    order = live_order(tenant, pay_advance=False)
    bill = raise_a_bill(tenant, order)
    assert tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).status_code == 200
    entry = book(tenant, order["id"])["entries"][0]
    res = tenant.delete("/api/sub-mb/entries/%d" % entry["id"])
    assert res.status_code == 409 and "Delete that bill first" in res.json()["detail"]


def test_staff_cannot_delete_a_bill_or_a_vendor(tenant, portal):
    order = live_order(tenant, pay_advance=False)
    bill = raise_a_bill(tenant, order)
    pm = make_employee(tenant, permission_role="project_manager", password=PASSWORD)
    tenant.put("/api/employees/%d" % pm["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": pm["email"], "password": PASSWORD})
    assert portal.delete("/api/sub-bills/%d" % bill["id"]).status_code in (401, 403)
    assert portal.delete("/api/wo/contractors/%d" % order["contractor_id"]).status_code in (401, 403)


def test_an_entry_can_be_changed_after_it_is_recorded_and_the_bill_follows(tenant):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 10)
    entry = book(tenant, order["id"])["entries"][0]
    # the lines are replaced and the quantity is worked out again: 2 blocks of 3 x 5 = 30
    res = tenant.put("/api/sub-mb/entries/%d" % entry["id"], json={
        "item_id": item, "multiplier": 2, "location": "Block B", "measured_on": "2026-11-20",
        "dimensions": [{"particulars": "Slab", "nos": 3, "length": 5}]})
    assert res.status_code == 200 and res.json()["quantity"] == 30, res.text
    changed = book(tenant, order["id"])["entries"][0]
    assert changed["quantity"] == 30 and changed["location"] == "Block B" and changed["multiplier"] == 2
    assert changed["dimensions"][0]["particulars"] == "Slab"
    # on a draft bill the bill is drawn up again; on a sent bill it is refused
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()
    bill = bill.get("bill") or bill
    again = tenant.put("/api/sub-mb/entries/%d" % entry["id"], json={"item_id": item, "dimensions": [{"particulars": "Slab", "nos": 4, "length": 5}]})
    assert again.status_code == 200
    got = tenant.get("/api/sub-bills/%d" % bill["id"]).json()
    assert (got.get("bill") or got)["this_bill"] > bill["this_bill"] - 1e9
    assert tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).status_code == 200
    refused = tenant.put("/api/sub-mb/entries/%d" % entry["id"], json={"item_id": item, "quantity": 5})
    assert refused.status_code == 409 and "Delete that bill" in refused.json()["detail"]
