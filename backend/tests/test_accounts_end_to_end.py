"""Accounts, end to end, the way the office runs a month.

A supplier's bill is asked for, approved, put in the bank's payment file, paid, found on the bank statement and sent to
Tally. A contractor's RA bill is certified with retention and TDS held back and paid. Then the month's GST and TDS
reports are read back and must carry what happened.
"""
from datetime import date

from app.services.files import fy_quarter

from test_bank_reco import dmy, statement
from test_payment_approval import office
from test_payouts import bank, supplier
from test_subcontract_controls import certified_bill
from test_subcontractor_bills import live_order

TODAY = date.today().isoformat()
MONTH_START = TODAY[:8] + "01"

__all__ = ["office"]


def ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def test_a_supplier_bill_from_approval_to_tally(tenant, office):
    clerk, head = office
    acc = bank(tenant)
    supplier(tenant, name="Ramco Steel")
    bill = ok(tenant.post("/api/bills", json={"number": "RS/2611", "vendor_name": "Ramco Steel", "amount": 100000, "tax_amount": 18000,
                                              "total": 118000, "issue_date": TODAY, "status": "Awaiting Payment"}))

    # With approvals on, the bill may not go in a bank file before it is approved.
    assert all(c["doc_id"] != bill["id"] for c in ok(tenant.get("/api/payment-batches/candidates"))["items"])
    sneak = {"doc_type": "supplier_bill", "doc_id": bill["id"], "request_id": None, "doc_number": "RS/2611"}
    early = clerk.post("/api/payment-batches", json={"account_id": acc["id"], "bank_format": "icici", "pay_on": TODAY, "items": [sneak]})
    assert early.status_code == 409, early.text

    r = ok(clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 118000}))["request"]
    ok(head.post("/api/approvals/decide", json={"kind": "payment_request", "id": r["id"], "decision": "approve"}))
    ok(tenant.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}))      # over the MD's limit: the MD releases it

    cand = next(c for c in ok(tenant.get("/api/payment-batches/candidates"))["items"] if c["doc_id"] == bill["id"])
    assert not cand.get("problem"), cand
    batch = ok(clerk.post("/api/payment-batches", json={"account_id": acc["id"], "bank_format": "icici", "pay_on": TODAY, "items": [cand]}))
    assert batch["total"] == 118000
    f = tenant.get("/api/payment-batches/%d/file" % batch["id"])
    assert f.status_code == 200 and "001105012345" in f.text
    paid = ok(tenant.post("/api/payment-batches/%d/paid" % batch["id"], json={"paid_on": TODAY, "reference": "UTR26110001"}))
    assert paid["status"] == "PAID"
    assert ok(tenant.get("/api/bills/%d" % bill["id"]))["status"] == "Paid"
    # The request is settled by the file, not left open to be paid twice.
    req = next(x for x in ok(tenant.get("/api/payment-requests"))["requests"] if x["id"] == r["id"])
    assert req["status"] == "PAID", req

    # The bank's statement shows the debit; it matches the payment.
    st = statement(tenant, acc, [[dmy(TODAY), "NEFT DR-ICIC0004321-RAMCO STEEL-UTR26110001", "UTR26110001", dmy(TODAY), "1,18,000.00", "", "8,82,000.00"]])
    assert st["matched"] == 1, st
    reco = ok(tenant.get("/api/bank-reco/%d" % acc["id"]))
    assert reco["counts"]["unmatched"] == 0 and reco["brs"]["difference"] == 0, reco["brs"]

    # Tally: the purchase with its GST and the payment from the bank, both balanced.
    vs = ok(tenant.get("/api/tally/vouchers", params={"date_from": MONTH_START, "date_to": TODAY}))
    mine = [v for v in vs["vouchers"] if "RS/2611" in str(v) or "Ramco Steel" in str(v)]
    kinds = {v.get("type") or v.get("voucher_type") for v in mine}
    assert {"Purchase", "Payment"} <= kinds, (kinds, mine)
    for v in mine:
        lines = v.get("lines") or v.get("entries")
        assert abs(sum(l.get("amount", 0) for l in lines)) < 0.01 or abs(sum(l.get("debit", 0) - l.get("credit", 0) for l in lines)) < 0.01, v
    xml = tenant.get("/api/tally/vouchers.xml", params={"date_from": MONTH_START, "date_to": TODAY})
    assert xml.status_code == 200 and "Ramco Steel" in xml.text and "UTR26110001" in xml.text


def test_a_contractor_ra_bill_with_retention_and_tds_then_the_month_s_gst_and_tds(tenant):
    order = live_order(tenant, pay_advance=False, retention_percent=5)
    bill = certified_bill(tenant, order)
    assert bill["retention_amount"] > 0 and bill["tds_amount"] > 0 and bill["gst_amount"] > 0, bill
    net = round(bill["this_bill"] + bill["gst_amount"] - bill["tds_amount"] - bill["retention_amount"], 2)
    out = ok(tenant.get("/api/money/outstanding/sub_bill/%d" % bill["id"]))
    assert abs(out["outstanding"] - net) < 1, (out, net, bill)
    paid = ok(tenant.post("/api/sub-bills/%d/pay" % bill["id"], json={"reference": "NEFT RA1"}))["bill"]
    assert paid["status"] == "PAID"
    held = ok(tenant.get("/api/retention"))["summary"]["contractor_held"]
    assert abs(held - bill["retention_amount"]) < 0.01, held

    gst = ok(tenant.get("/api/gst/inward", params={"date_from": MONTH_START, "date_to": TODAY}))
    row = next(r for r in gst["supplies"] if r["number"] == bill["number"])
    assert row["taxable"] == bill["this_bill"] and abs(row["tax"] - bill["gst_amount"]) < 0.01
    assert tenant.get("/api/gst/inward.xlsx", params={"date_from": MONTH_START, "date_to": TODAY}).status_code == 200

    tds = ok(tenant.get("/api/registers/tds", params=dict(zip(("year", "quarter"), fy_quarter(TODAY)))))
    got = [d for d in tds["deducted"] if d.get("number") == bill["number"] or d.get("bill") == bill["number"]]
    assert got and abs(got[0].get("tds", got[0].get("tds_amount", 0)) - bill["tds_amount"]) < 0.01, tds["deducted"]
    assert tenant.get("/api/registers/tds.xlsx").status_code == 200

    vs = ok(tenant.get("/api/tally/vouchers", params={"date_from": MONTH_START, "date_to": TODAY}))
    text = str([v for v in vs["vouchers"] if bill["number"] in str(v)])
    assert "TDS" in text and "Retention" in text, text
