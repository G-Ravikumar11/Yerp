"""What accounts take from the stores: stock value, goods received and not billed, scrap sales to collect (receiving the money into the bank book),
and the cost to charge across when stock moves between two projects."""
import uuid
from datetime import date

from app import db as database, models
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()


def _receive(t, central, w, bags, project=None):
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "lines": [{"po_line_id": po_line, "qty": str(bags), "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    return grn


def _bill(w, amount, status="Approved for payment"):
    with database.SessionLocal() as s:
        s.add(models.DBBill(client_id=w["client_id"], number="B-" + uuid.uuid4().hex[:6], amount=amount, tax_amount=0, total=amount, status=status, purchase_order_id=w["pos"][0][0], job_id=w["job"]))
        s.commit()


def test_goods_received_and_not_billed(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    assert ok(t.get("/api/store/accounts/not-billed"))["items"] == []
    _receive(t, central, w, 100)                                      # 100 bags at 350 = 35,000
    [row] = ok(t.get("/api/store/accounts/not-billed"))["items"]
    assert row["po_number"] == "PO-%s-0" % tag and row["received_value"] == "35000.00" and row["billed_value"] == "0.00" and row["difference"] == "35000.00" and row["status"] == "NOT_BILLED"

    _bill(w, 20000, "Draft")                                          # a draft is not billed
    assert ok(t.get("/api/store/accounts/not-billed"))["items"][0]["difference"] == "35000.00"
    _bill(w, 20000)
    assert ok(t.get("/api/store/accounts/not-billed"))["items"][0]["difference"] == "15000.00"
    _bill(w, 15000, "Paid")
    assert ok(t.get("/api/store/accounts/not-billed"))["items"] == []                              # square
    _bill(w, 1000)
    [over] = ok(t.get("/api/store/accounts/not-billed"))["items"]
    assert over["status"] == "OVER_BILLED" and over["difference"] == "-1000.00"

    s = ok(t.get("/api/store/accounts/summary"))
    assert s["stock_value"] == "35000.00" and s["not_billed"] == "0.00" and s["over_billed"] == "1000.00" and s["over_billed_orders"] == 1


def _scrap(t, central, w, realised="4000"):
    doc = ok(t.post("/api/store/control/scrap", json={"store_id": central["id"], "scrap_date": TODAY, "project_id": w["job"], "buyer": "Gupta Scrap Traders", "reference": "GP-12",
                                                      "lines": [{"item_id": w["item"], "qty": "100", "uom": "kg", "disposal": "SCRAP", "reason": "cut-offs", "realised_value": realised}]}))
    walk(t, "control", "scrap", doc["id"], "submit", "approve", "post")
    return doc


def test_a_scrap_sale_is_collected_into_the_bank_book(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 100)
    doc = _scrap(t, central, w)
    [sale] = ok(t.get("/api/store/accounts/scrap"))["items"]
    assert sale["number"] == doc["number"] and sale["realised"] == "4000.00" and sale["outstanding"] == "4000.00" and sale["buyer"] == "Gupta Scrap Traders" and not sale["settled"]
    assert ok(t.get("/api/store/accounts/summary"))["scrap_to_collect"] == "4000.00"

    url = "/api/store/accounts/scrap/%d/receive" % doc["id"]
    assert t.post(url, json={"amount": "0"}).status_code == 400
    assert t.post(url, json={"amount": "5000"}).status_code == 400                                   # more than is owed
    assert t.post(url, json={"amount": "100", "mode": "Cheque"}).status_code == 400                  # a cheque needs its number
    first = ok(t.post(url, json={"amount": "1500", "reference": "UTR123"}))
    assert first["receipt_number"].startswith("RCT-")
    [sale] = ok(t.get("/api/store/accounts/scrap"))["items"]
    assert sale["received"] == "1500.00" and sale["outstanding"] == "2500.00"
    ok(t.post(url, json={"amount": "2500", "mode": "Cash"}))
    [sale] = ok(t.get("/api/store/accounts/scrap"))["items"]
    assert sale["settled"] is True and sale["outstanding"] == "0.00"
    assert t.post(url, json={"amount": "1"}).status_code == 400

    with database.SessionLocal() as s:                                                               # the receipts are in the bank book, under the scrap head and the project
        rows = s.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.client_id == w["client_id"], models.DBMoneyEntry.head == "Scrap sale").all()
        assert sorted(r.amount for r in rows) == [1500.0, 2500.0] and all(r.direction == "IN" and r.doc_type == "income" and r.job_id == w["job"] for r in rows)


def test_a_scrap_sale_needs_a_posted_document(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 100)
    doc = ok(t.post("/api/store/control/scrap", json={"store_id": central["id"], "scrap_date": TODAY, "project_id": w["job"], "buyer": "X", "lines": [
        {"item_id": w["item"], "qty": "100", "uom": "kg", "disposal": "SCRAP", "reason": "cut-offs", "realised_value": "4000"}]}))
    assert ok(t.get("/api/store/accounts/scrap"))["items"] == []
    assert t.post("/api/store/accounts/scrap/%d/receive" % doc["id"], json={"amount": "10"}).status_code == 409


def test_an_inter_project_transfer_is_charged_across_once(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    with database.SessionLocal() as s:
        other = models.DBJob(client_id=w["client_id"], number="Q-" + tag, name="Tower B")
        s.add(other)
        s.commit()
        other_id = other.id
    a = ok(t.post("/api/store/masters/stores", json={"code": "SA" + tag[:3].upper(), "name": "Site A", "type": "SITE", "project_id": w["job"]}))
    b = ok(t.post("/api/store/masters/stores", json={"code": "SB" + tag[:3].upper(), "name": "Site B", "type": "SITE", "project_id": other_id}))
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": a["id"], "grn_date": TODAY, "po_id": po_id, "project_id": w["job"], "lines": [{"po_line_id": po_line, "qty": "40", "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    doc = ok(t.post("/api/store/control/transfer", json={"store_id": a["id"], "to_store_id": b["id"], "transfer_date": TODAY, "lines": [{"item_id": w["item"], "qty": "10", "uom": "bag"}]}))
    walk(t, "control", "transfer", doc["id"], "submit", "approve", "post")
    assert ok(t.get("/api/store/accounts/cross-charges"))["items"] == []                            # not until it is received
    ok(t.post("/api/store/control/transfer/%d/receive" % doc["id"]))

    [c] = ok(t.get("/api/store/accounts/cross-charges"))["items"]
    assert c["status"] == "PENDING" and c["amount"] == "3500.00" and c["from_project"] == "Tower A" and c["to_project"] == "Tower B" and c["transfer_number"] == doc["number"]
    assert len(ok(t.get("/api/store/accounts/cross-charges"))["items"]) == 1                         # listing again adds nothing
    s = ok(t.get("/api/store/accounts/summary"))
    assert s["cross_charges_pending"] == "3500.00" and s["cross_charges_open"] == 1

    url = "/api/store/accounts/cross-charges/%d/adjust" % c["id"]
    assert ok(t.post(url, json={"note": "JV 12"}))["status"] == "ADJUSTED"
    assert t.post(url, json={}).status_code == 409
    assert ok(t.get("/api/store/accounts/summary"))["cross_charges_open"] == 0

    # Cancelling the transfer afterwards asks accounts to put the adjustment back.
    ok(t.post("/api/store/control/transfer/%d/cancel" % doc["id"], json={"reason": "Sent in error"}))
    [c] = ok(t.get("/api/store/accounts/cross-charges"))["items"]
    assert c["status"] == "REVERSE"
    assert ok(t.post(url, json={}))["status"] == "VOID"


def test_suppliers_billing_and_cross_charges_are_for_accounts_only(account):
    from fastapi.testclient import TestClient
    import main
    from conftest import make_employee
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 10)
    people = {}
    for role in ("stores", "accounts"):
        email = "%s-%s@example.com" % (role, tag)
        emp = make_employee(t, email=email, password="Crew1234", permission_role=role, status="active")
        ok(t.post("/api/store/masters/stores/%d/assignments" % central["id"], json={"employee_id": emp["id"], "role": "STOREKEEPER"}))
        c = TestClient(main.app)
        c.__enter__()
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        people[role] = c
    try:
        keeper, accounts = people["stores"], people["accounts"]
        s = ok(keeper.get("/api/store/accounts/summary"))
        assert s["accounts_view"] is False and s["not_billed"] is None and s["cross_charges_pending"] is None and s["stock_value"] == "3500.00"
        for path in ("/api/store/accounts/not-billed", "/api/store/accounts/cross-charges", "/api/store/accounts/price-variances"):
            assert keeper.get(path).status_code == 403, path
        assert ok(keeper.get("/api/store/accounts/scrap"))["items"] == []                         # their own stores' scrap sales they see

        s = ok(accounts.get("/api/store/accounts/summary"))
        assert s["accounts_view"] is True and s["not_billed"] == "3500.00"
        assert len(ok(accounts.get("/api/store/accounts/not-billed"))["items"]) == 1
        assert keeper.post("/api/store/accounts/cross-charges/1/adjust", json={}).status_code == 403
    finally:
        for c in people.values():
            c.__exit__(None, None, None)
