"""No payment before the goods are received.

A bill that claims more than has come in on its order - nothing received at all, or more billed than arrived - is
never approved on the nod: it goes to whoever may release payment. Paying it needs a reason, which is kept. And a
cancelled bill, like a rejected one, is no claim on its order.
"""
from test_goods_receipt import match, order, post, receipt, set_lines
from test_jobs_and_orders import approved_order, set_rules, sign_in, sign_out, staff


def bill(tenant, po, number, amount, **extra):
    res = tenant.post("/api/bills", json={"number": number, "vendor_name": "Steel Co", "total": amount, "amount": amount,
                                          "purchase_order_id": po["id"], **extra})
    assert res.status_code == 200, res.text
    return res.json()


# --- the three-way match ------------------------------------------------------------------------------------------

def test_a_cancelled_bill_stops_counting_as_billed(tenant):
    po = order(tenant)
    post(tenant, receipt(tenant, po))
    bill(tenant, po, "SUP-C1", 600000, status="Cancelled")
    row = match(tenant, po)
    assert row["verdict"] == "AWAITING_BILL" and row["billed_value"] == 0 and row["bill_count"] == 0


# --- approval ----------------------------------------------------------------------------------------------------

def _staff_bill(portal, tenant, amount, received, auto_below=5000.0):
    """A bill raised by a member of staff against an order of 1,000, with `received` of it delivered, under a
    sign-off limit of `auto_below` (set once the order is approved, so the order itself is not waved through)."""
    po = approved_order(portal, tenant, supplier_name="Jewson", amount=1000.0,
                        line_items=[{"description": "Cement", "uom": "bag", "qty": 10, "price": 100}])
    set_rules(tenant, auto_below=auto_below)
    if received:
        grn = receipt(tenant, po)
        set_lines(tenant, grn, [{"received_qty": received / 100, "accepted_qty": received / 100}])
        post(tenant, grn)
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    sign_in(portal, hand)
    out = portal.post("/api/employee/bills", json={"vendor_name": "Jewson", "amount": amount, "purchase_order_id": po["id"]}).json()
    sign_out(portal)
    return out


def test_a_bill_for_goods_not_received_is_never_auto_approved_and_goes_to_finance(portal, tenant):
    purse = staff(tenant, permission_role="finance")
    out = _staff_bill(portal, tenant, 300.0, received=0)
    assert out["status"] == "pending", out
    assert out.get("held_for_goods") is True
    history = tenant.get("/api/approvals/history/bill/%d" % out["bill"]["id"]).json()["history"]
    # Finance is on the chain, last, whoever else is.
    assert history[-1]["approver_name"] == "%s %s" % (purse["first_name"], purse["last_name"])


def test_a_bill_for_more_than_arrived_is_held_too(portal, tenant):
    staff(tenant, permission_role="finance")
    out = _staff_bill(portal, tenant, 600.0, received=400)
    assert out["status"] == "pending" and out.get("held_for_goods") is True


def test_a_bill_within_what_arrived_still_goes_through_on_the_limit(portal, tenant):
    out = _staff_bill(portal, tenant, 400.0, received=400)
    assert out["status"] == "approved", out


# --- payment ------------------------------------------------------------------------------------------------------

def test_paying_a_bill_ahead_of_the_goods_needs_a_reason_and_keeps_it(tenant):
    po = order(tenant)
    b = bill(tenant, po, "SUP-P1", 600000, status="Awaiting Payment")
    res = tenant.post("/api/bills/%d/pay" % b["id"], json={})
    assert res.status_code == 409, res.text
    assert "override reason" in res.json()["detail"]
    res = tenant.post("/api/bills/%d/pay" % b["id"], json={"override_reason": "ok"})
    assert res.status_code == 409                                     # too short to be a reason
    res = tenant.post("/api/bills/%d/pay" % b["id"], json={"override_reason": "Advance agreed in the PO terms"})
    assert res.status_code == 200, res.text
    mine = [e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "supplier_bill" and e["doc_id"] == b["id"]]
    assert mine and "Advance agreed in the PO terms" in mine[0]["note"] and mine[0]["note"].startswith("Override")


def test_a_bill_for_goods_received_is_paid_without_a_reason(tenant):
    po = order(tenant)
    post(tenant, receipt(tenant, po))
    b = bill(tenant, po, "SUP-P2", 600000, status="Awaiting Payment")
    res = tenant.post("/api/bills/%d/pay" % b["id"], json={})
    assert res.status_code == 200, res.text


def test_the_same_rule_holds_on_a_payment_from_the_ledger(tenant):
    po = order(tenant)
    b = bill(tenant, po, "SUP-P3", 600000, status="Awaiting Payment")
    res = tenant.post("/api/money/entries", json={"doc_type": "supplier_bill", "doc_id": b["id"], "amount": 1000})
    assert res.status_code == 409 and "override reason" in res.json()["detail"]
    res = tenant.post("/api/money/entries", json={"doc_type": "supplier_bill", "doc_id": b["id"], "amount": 1000,
                                          "override_reason": "Part advance agreed with the supplier"})
    assert res.status_code == 200, res.text
