"""Receipts, payments, party ledgers and the bank book.

A bill was paid or it was not, so a part-payment lived in a notebook, what a
party owed across all their bills lived in Tally, and what was in the bank
lived there too. These are those three books, kept from the documents
already here.
"""
from test_measurement_and_ra_bills import placed_order, book, measure
from test_subcontractor_bills import (live_order, book as sub_book,
                                      measure as sub_measure, raise_bill)


def certified_ra(tenant, qty=100):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], qty)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    return tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]


def certified_sub(tenant, qty=100):
    order = live_order(tenant)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, qty)
    b = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % b["id"], json={})
    return tenant.get("/api/sub-bills/%d" % b["id"]).json()


def money_in(tenant, **body):
    return tenant.post("/api/money/entries", json=body)


_n = [0]


def supplier_bill(tenant, vendor="ACC Ltd", amount=100000, tax=18000):
    _n[0] += 1
    res = tenant.post("/api/bills", json={"number": "SB-%04d" % _n[0],
                                          "vendor_name": vendor, "amount": amount,
                                          "tax_amount": tax, "total": amount + tax,
                                          "status": "Awaiting Payment"})
    assert res.status_code == 200, res.text
    return res.json()


# --- Part-payments ---------------------------------------------------------------

def test_a_bill_can_be_received_in_parts(tenant):
    b = certified_ra(tenant)
    half = round(b["net_payable"] / 2, 2)
    r = money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=half,
                 mode="Bank transfer", reference="UTR123")
    assert r.status_code == 200, r.text
    assert r.json()["left"] == round(b["net_payable"] - half, 2)
    assert tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]["status"] == "CERTIFIED"
    owed = tenant.get("/api/money/receivables").json()
    row = [x for x in owed["invoices"] if x.get("doc_type") == "ra_bill"][0]
    assert row["paid"] == half and row["outstanding"] == round(b["net_payable"] - half, 2)


def test_the_last_rupee_marks_it_paid(tenant):
    b = certified_ra(tenant)
    half = round(b["net_payable"] / 2, 2)
    money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=half)
    r = money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=round(b["net_payable"] - half, 2))
    assert r.json()["left"] == 0
    assert tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]["status"] == "PAID"
    assert not [x for x in tenant.get("/api/money/receivables").json()["invoices"]
                if x.get("doc_type") == "ra_bill"]


def test_more_than_is_owed_is_refused(tenant):
    b = certified_ra(tenant)
    r = money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=b["net_payable"] + 1)
    assert r.status_code == 400 and "left to settle" in r.json()["detail"]


def test_a_draft_bill_cannot_be_received_against(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 10)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    r = money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=10)
    assert r.status_code == 409


def test_a_cheque_needs_its_number(tenant):
    b = certified_ra(tenant)
    r = money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=10, mode="Cheque")
    assert r.status_code == 400 and "cheque number" in r.json()["detail"]


def test_a_gang_is_paid_in_parts_too(tenant):
    b = certified_sub(tenant)
    r = money_in(tenant, doc_type="sub_bill", doc_id=b["id"], amount=1000)
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["direction"] == "OUT"
    pay = tenant.get("/api/money/payables").json()
    row = [x for x in pay["bills"] if x.get("doc_type") == "sub_bill"][0]
    assert row["outstanding"] == round(b["net_payable"] - 1000, 2)


def test_a_supplier_bill_moves_through_partly_paid(tenant):
    bill = supplier_bill(tenant)
    r = money_in(tenant, doc_type="supplier_bill", doc_id=bill["id"], amount=50000)
    assert r.status_code == 200, r.text
    got = tenant.get("/api/money/outstanding/supplier_bill/%d" % bill["id"]).json()
    assert got["outstanding"] == 68000
    money_in(tenant, doc_type="supplier_bill", doc_id=bill["id"], amount=68000)
    assert tenant.get("/api/money/outstanding/supplier_bill/%d" % bill["id"]).json()["outstanding"] == 0


# --- Voiding -----------------------------------------------------------------------

def test_a_void_puts_the_bill_back_to_owing(tenant):
    b = certified_ra(tenant)
    e = money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=b["net_payable"]).json()["entry"]
    assert tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]["status"] == "PAID"
    r = tenant.post("/api/money/entries/%d/void" % e["id"], json={"reason": "bounced"})
    assert r.status_code == 200
    assert tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]["status"] == "CERTIFIED"
    entries = tenant.get("/api/money/entries").json()["entries"]
    assert entries[0]["voided"] is True and entries[0]["void_reason"] == "bounced"


def test_a_void_needs_a_reason(tenant):
    b = certified_ra(tenant)
    e = money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=10).json()["entry"]
    assert tenant.post("/api/money/entries/%d/void" % e["id"], json={}).status_code == 400


# --- On account ---------------------------------------------------------------------

def test_an_advance_on_account_sits_in_the_ledger(tenant):
    r = money_in(tenant, doc_type="on_account", direction="OUT", party_type="supplier",
                 party_name="Tata Steel", amount=200000, note="Advance against PO")
    assert r.status_code == 200, r.text
    parties = tenant.get("/api/ledger/parties?party_type=supplier").json()
    tata = [p for p in parties["parties"] if p["party"] == "Tata Steel"][0]
    assert tata["balance"] == -200000          # they owe us goods
    assert parties["summary"]["advances_out"] == 200000


# --- Ledgers --------------------------------------------------------------------------

def test_a_statement_of_account_runs_a_balance(tenant):
    b = certified_ra(tenant)
    money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=1000, reference="UTR1")
    st = tenant.get("/api/ledger/statement", params={
        "party_type": "client", "party": "L&T"}).json()
    assert [r["kind"] for r in st["rows"]][0] == "RA bill"
    assert st["rows"][0]["balance"] == b["net_payable"]
    assert st["rows"][-1]["balance"] == round(b["net_payable"] - 1000, 2)
    assert st["closing"] == round(b["net_payable"] - 1000, 2)
    assert st["closing_words"].startswith("Rupees")


def test_names_that_differ_only_in_spelling_are_one_party(tenant):
    supplier_bill(tenant, vendor="ACC Ltd", amount=1000, tax=0)
    supplier_bill(tenant, vendor="acc ltd.", amount=500, tax=0)
    parties = tenant.get("/api/ledger/parties?party_type=supplier").json()["parties"]
    acc = [p for p in parties if p["party"].lower().startswith("acc")]
    assert len(acc) == 1 and acc[0]["billed"] == 1500


def test_a_bill_marked_paid_before_the_ledger_is_settled_in_it(tenant):
    """Old bills paid with the one-click button must not show as owing."""
    b = certified_ra(tenant)
    tenant.post("/api/ra-bills/%d/pay" % b["id"], json={})
    parties = tenant.get("/api/ledger/parties?party_type=client").json()["parties"]
    assert parties[0]["balance"] == 0


# --- The bank book ----------------------------------------------------------------------

def test_the_bank_book_runs_from_the_opening_balance(tenant):
    acc = tenant.post("/api/bank-accounts", json={"name": "SBI current",
                                                  "opening_balance": 500000}).json()
    b = certified_ra(tenant)
    money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=10000, account_id=acc["id"])
    s = certified_sub(tenant)
    money_in(tenant, doc_type="sub_bill", doc_id=s["id"], amount=3000, account_id=acc["id"])
    bk = tenant.get("/api/money/book?account_id=%d" % acc["id"]).json()
    assert bk["opening"] == 500000
    assert bk["closing"] == 500000 + 10000 - 3000
    assert [r["balance"] for r in bk["rows"]] == [510000, 507000]
    listed = tenant.get("/api/bank-accounts").json()["accounts"][0]
    assert listed["balance"] == 507000


def test_a_cash_box_takes_cash(tenant):
    box = tenant.post("/api/bank-accounts", json={"name": "Site cash", "kind": "Cash"}).json()
    r = money_in(tenant, doc_type="on_account", direction="OUT", party_type="other",
                 party_name="Tea and water", amount=450, account_id=box["id"], mode="Bank transfer")
    assert r.json()["entry"]["mode"] == "Cash"


# --- Suppliers ----------------------------------------------------------------------------

def test_a_supplier_takes_its_state_and_pan_from_the_gstin(tenant):
    s = tenant.post("/api/suppliers", json={"name": "ACC Ltd", "gstin": "36AAACA1234C1Z5"}).json()
    assert s["code"] == "SUP-0001"
    assert s["state"] == "Telangana" and s["pan"] == "AAACA1234C"


def test_the_same_supplier_is_not_added_twice(tenant):
    tenant.post("/api/suppliers", json={"name": "ACC Ltd"})
    assert tenant.post("/api/suppliers", json={"name": "acc  ltd."}).status_code == 409


def test_names_already_on_orders_can_be_adopted(tenant):
    tenant.post("/api/purchase-orders", json={"supplier_name": "UltraTech", "amount": 100})
    supplier_bill(tenant, vendor="Jindal Steel")
    listed = tenant.get("/api/suppliers").json()
    assert set(listed["unregistered"]) == {"UltraTech", "Jindal Steel"}
    out = tenant.post("/api/suppliers/adopt", json={}).json()
    assert len(out["added"]) == 2
    assert tenant.get("/api/suppliers").json()["unregistered"] == []


def test_a_bad_gstin_is_refused(tenant):
    assert tenant.post("/api/suppliers", json={"name": "X", "gstin": "99ABC"}).status_code == 400


def test_another_tenant_sees_none_of_it(tenant, second_tenant):
    b = certified_ra(tenant)
    money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=10)
    assert second_tenant.get("/api/money/entries").json()["entries"] == []
    assert second_tenant.get("/api/ledger/parties").json()["parties"] == []
    assert money_in(second_tenant, doc_type="ra_bill", doc_id=b["id"], amount=1).status_code == 404


def test_a_draft_supplier_bill_cannot_be_paid(tenant):
    """Drafts are not in the ledger, so money against one would land against
    nothing."""
    res = tenant.post("/api/bills", json={"number": "DRAFT-1", "vendor_name": "X",
                                          "amount": 100, "total": 100, "status": "Draft"})
    r = money_in(tenant, doc_type="supplier_bill", doc_id=res.json()["id"], amount=50)
    assert r.status_code == 409 and "Accept the bill" in r.json()["detail"]
