"""The Finance Dashboard for one project: what it was sold for, billed, received, owed and spent - only that project's."""
from test_finance_ledger import certified_ra, money_in


def job(tenant, name):
    return tenant.post("/api/jobs", json={"name": name, "customer_name": "L&T"}).json()["id"]


def bill(tenant, number, job_id, total):
    res = tenant.post("/api/bills", json={"number": number, "vendor_name": "ACC Ltd", "amount": total, "tax_amount": 0, "total": total,
                                          "status": "Awaiting Payment", "job_id": job_id})
    assert res.status_code == 200, res.text
    return res.json()


def test_a_project_shows_only_its_own_bills_and_payments(tenant):
    mine, other = job(tenant, "Alpha Towers"), job(tenant, "Beta Homes")
    b = bill(tenant, "SB-A1", mine, 40000)
    bill(tenant, "SB-B1", other, 99000)
    assert tenant.post("/api/approvals/submit", json={"entity_type": "bill", "entity_id": b["id"]}).status_code == 200
    got = tenant.get("/api/money/project-accounts/%d" % mine)
    assert got.status_code == 200, got.text
    d = got.json()
    assert d["project"]["job_id"] == mine and d["project"]["name"] == "Alpha Towers"
    assert [r["number"] for r in d["to_pay"]] == ["SB-A1"] and d["pay_total"] == 40000
    assert d["to_receive"] == [] and d["received"] == 0
    # Paid in part: the payment is in this project's list and the balance is what is left.
    assert money_in(tenant, doc_type="supplier_bill", doc_id=b["id"], amount=15000, mode="Bank transfer").status_code == 200
    d = tenant.get("/api/money/project-accounts/%d" % mine).json()
    assert d["pay_total"] == 25000 and d["paid"] == 15000 and len(d["entries"]) == 1
    # The other project has none of it.
    o = tenant.get("/api/money/project-accounts/%d" % other).json()
    assert o["paid"] == 0 and [r["number"] for r in o["to_pay"]] == ["SB-B1"] and o["pay_total"] == 99000


def test_a_project_shows_what_its_client_owes_and_has_paid(tenant):
    ra = certified_ra(tenant)
    d = tenant.get("/api/money/project-accounts/%d" % ra["job_id"]).json()
    assert [r["number"] for r in d["to_receive"]] == [ra["number"]] and d["receive_total"] == ra["net_payable"]
    half = round(ra["net_payable"] / 2, 2)
    assert money_in(tenant, doc_type="ra_bill", doc_id=ra["id"], amount=half, mode="Bank transfer").status_code == 200
    d = tenant.get("/api/money/project-accounts/%d" % ra["job_id"]).json()
    assert d["received"] == half and d["receive_total"] == round(ra["net_payable"] - half, 2)


def test_an_unknown_project_is_not_found(tenant):
    assert tenant.get("/api/money/project-accounts/999999").status_code == 404


def test_a_project_shows_its_payment_requests_and_the_months_money_moved(tenant):
    mine, other = job(tenant, "Alpha Towers"), job(tenant, "Beta Homes")
    b, o = bill(tenant, "SB-A2", mine, 60000), bill(tenant, "SB-B2", other, 5000)
    for x in (b, o):
        assert tenant.post("/api/approvals/submit", json={"entity_type": "bill", "entity_id": x["id"]}).status_code == 200
    assert tenant.put("/api/payment-requests/rules", json={"on": True, "free_below": 100, "md_above": 1000000}).status_code == 200
    req = tenant.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": b["id"], "amount": 60000}).json()["request"]
    assert tenant.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": o["id"], "amount": 5000}).status_code == 200
    d = tenant.get("/api/money/project-accounts/%d" % mine).json()
    assert [r["number"] for r in d["payment_requests"]] == [req["number"]] and d["payment_requests"][0]["status"] == "PENDING"
    assert d["request_summary"] == {"with_accounts": 60000, "with_md": 0, "to_pay": 0, "open": 1}
    # Approved in Payment Approvals, it is approved here; paid under it, the month shows the money out.
    assert tenant.post("/api/payment-requests/%d/decide" % req["id"], json={"decision": "approve"}).status_code == 200
    assert tenant.get("/api/money/project-accounts/%d" % mine).json()["request_summary"]["to_pay"] == 60000
    assert tenant.post("/api/payment-requests/%d/pay" % req["id"], json={"mode": "Bank transfer"}).status_code == 200
    d = tenant.get("/api/money/project-accounts/%d" % mine).json()
    assert d["payment_requests"][0]["status"] == "PAID" and d["request_summary"]["open"] == 0
    assert len(d["monthly"]) == 1 and d["monthly"][0]["paid"] == 60000 and d["monthly"][0]["received"] == 0


def test_the_projects_figures_are_set_beside_the_ledgers_with_what_explains_a_difference(tenant):
    mine = job(tenant, "Alpha Towers")
    b = bill(tenant, "SB-L1", mine, 40000)
    assert tenant.post("/api/approvals/submit", json={"entity_type": "bill", "entity_id": b["id"]}).status_code == 200
    # A journal credits the supplier 3,000 on this project: the ledger owes it, the bill does not.
    jid = tenant.post("/api/journals", json={"narration": "Hire owed", "lines": [
        {"kind": "head", "head": "Machinery hire", "debit": 3000, "job_id": mine},
        {"kind": "party", "party_type": "supplier", "party_name": "ACC Ltd", "credit": 3000, "job_id": mine}]}).json()["id"]
    assert tenant.post("/api/journals/%d/approve" % jid, json={}).status_code == 200
    check = {c["label"]: c for c in tenant.get("/api/money/project-accounts/%d" % mine).json()["ledger_check"]}
    pay = check["Still to pay"]
    assert pay["dashboard"] == 40000 and pay["ledger"] == 43000 and pay["difference"] == -3000
    assert pay["explained"][0]["amount"] == -3000 and pay["unexplained"] == 0
    # With nothing else on the project, the other figures agree outright.
    for label in ("Still to receive", "Received", "Paid out"):
        assert check[label]["difference"] == 0 and check[label]["unexplained"] == 0
