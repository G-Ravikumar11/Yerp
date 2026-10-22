"""The accounts office's vouchers: expenses with no bill behind them, sundry receipts, money moved between our own bank
and cash, and every receipt and payment printed as a voucher on the letterhead.

A site office pays the diesel at the pump, the lorry and the gang's tea without a supplier's bill; draws cash from the
bank for the site's cash box; sells scrap. Each needs a voucher, a place in the bank book and - for an expense - a
place in the project's cost, without being taken for somebody's account in the ledger.
"""
from test_finance_ledger import certified_ra, money_in


def account(tenant, name="SBI current", kind="Bank", opening=0):
    res = tenant.post("/api/bank-accounts", json={"name": name, "kind": kind, "opening_balance": opening})
    assert res.status_code == 200, res.text
    return res.json()


def project(tenant, name="Vizag site"):
    res = tenant.post("/api/jobs", json={"name": name, "customer_name": "Aniprotech", "status": "in_progress"})
    assert res.status_code == 200, res.text
    return res.json()


def test_an_expense_voucher_is_booked_under_a_head_and_charged_to_the_project(tenant):
    box = account(tenant, "Site cash - Vizag", "Cash", 20000)
    job = project(tenant)
    res = money_in(tenant, doc_type="expense", head="Diesel & fuel", party_name="HP pump, Gajuwaka", amount=4500,
                   account_id=box["id"], job_id=job["id"], note="JCB 3DX, 50 litres")
    assert res.status_code == 200, res.text
    e = res.json()["entry"]
    assert e["number"] == "PMT-0001" and e["direction"] == "OUT" and e["head"] == "Diesel & fuel" and e["mode"] == "Cash"
    # In the cash book, out of the box.
    assert tenant.get("/api/money/book?account_id=%d" % box["id"]).json()["closing"] == 15500
    # In the project's cost, on every screen that costs it.
    one = tenant.get("/api/jobs/%d" % job["id"]).json()["costing"]
    assert one["site_expenses"] == 4500 and one["total_cost"] == 4500
    listed = next(j for j in tenant.get("/api/jobs").json()["jobs"] if j["id"] == job["id"])["costing"]
    assert listed["site_expenses"] == 4500 and listed["total_cost"] == 4500
    pnl = tenant.get("/api/jobs/%d/pnl" % job["id"]).json()
    assert pnl["cost"]["site_expenses"] == 4500 and pnl["cost"]["incurred"] == 4500
    # Nobody's account: the pump is not a party owed or owing anything.
    assert all(p["party"] != "HP pump, Gajuwaka" for p in tenant.get("/api/ledger/parties").json()["parties"])
    # Voided, it costs the project nothing.
    tenant.post("/api/money/entries/%d/void" % e["id"], json={"reason": "entered twice"})
    assert tenant.get("/api/jobs/%d" % job["id"]).json()["costing"]["site_expenses"] == 0


def test_an_expense_needs_a_known_head_and_a_payee(tenant):
    heads = tenant.get("/api/money/heads").json()
    assert "Diesel & fuel" in heads["expense"] and "Scrap sale" in heads["income"]
    # Labour gangs are paid on their RA bills and staff on the payroll; neither is an expense head.
    assert not any("wage" in h.lower() or "salar" in h.lower() for h in heads["expense"])
    assert money_in(tenant, doc_type="expense", head="Party", party_name="X", amount=10).status_code == 400
    assert money_in(tenant, doc_type="expense", head="Rent", party_name=" ", amount=10).status_code == 400
    ok = money_in(tenant, doc_type="expense", head="rent", party_name="Landlord", amount=10)
    assert ok.status_code == 200 and ok.json()["entry"]["head"] == "Rent"          # matched whatever the case


def test_scrap_sold_is_a_sundry_receipt(tenant):
    res = money_in(tenant, doc_type="income", head="Scrap sale", party_name="Sri Sai Scrap", amount=12000)
    assert res.status_code == 200, res.text
    e = res.json()["entry"]
    assert e["number"] == "RCT-0001" and e["direction"] == "IN"
    s = tenant.get("/api/money/entries").json()["summary"]
    assert s["received"] == 12000


def test_cash_drawn_for_a_site_is_one_contra_voucher_in_both_books(tenant):
    bank = account(tenant, "SBI current", "Bank", 500000)
    box = account(tenant, "Site cash - Vizag", "Cash")
    res = tenant.post("/api/money/transfer", json={"from_account_id": bank["id"], "to_account_id": box["id"],
                                                   "amount": 50000, "mode": "Cheque", "reference": "000123"})
    assert res.status_code == 200, res.text
    assert res.json()["entry"]["number"] == "CON-0001"
    assert tenant.get("/api/money/book?account_id=%d" % bank["id"]).json()["closing"] == 450000
    assert tenant.get("/api/money/book?account_id=%d" % box["id"]).json()["closing"] == 50000
    # Neither received nor paid: it only moved. And the receipts and payments keep their own numbers.
    s = tenant.get("/api/money/entries").json()["summary"]
    assert s["received"] == 0 and s["paid"] == 0 and s["transferred"] == 50000
    assert money_in(tenant, doc_type="expense", head="Site expenses", party_name="Tea stall", amount=300,
                    account_id=box["id"]).json()["entry"]["number"] == "PMT-0001"
    assert not tenant.get("/api/ledger/parties").json()["parties"]
    # Voided, both legs go together.
    out_leg = next(e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "contra")
    tenant.post("/api/money/entries/%d/void" % out_leg["id"], json={"reason": "wrong box"})
    assert tenant.get("/api/money/book?account_id=%d" % bank["id"]).json()["closing"] == 500000
    assert tenant.get("/api/money/book?account_id=%d" % box["id"]).json()["closing"] == -300


def test_a_transfer_needs_two_different_accounts_of_ours(tenant, second_tenant):
    bank = account(tenant)
    assert tenant.post("/api/money/transfer", json={"from_account_id": bank["id"], "to_account_id": bank["id"],
                                                    "amount": 10}).status_code == 400
    theirs = second_tenant.post("/api/bank-accounts", json={"name": "Theirs"}).json()
    assert tenant.post("/api/money/transfer", json={"from_account_id": bank["id"], "to_account_id": theirs["id"],
                                                    "amount": 10}).status_code == 404


def test_every_entry_prints_as_a_voucher(tenant, second_tenant):
    bank = account(tenant, "SBI current", "Bank", 100000)
    box = account(tenant, "Site cash", "Cash")
    b = certified_ra(tenant)
    receipt = money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=1000, account_id=bank["id"],
                       reference="UTR998877").json()["entry"]
    expense = money_in(tenant, doc_type="expense", head="Transport & freight", party_name="Lorry, AP31 TX 4455",
                       amount=2500, account_id=bank["id"]).json()["entry"]
    contra = tenant.post("/api/money/transfer", json={"from_account_id": bank["id"], "to_account_id": box["id"],
                                                      "amount": 5000}).json()["entry"]
    for e in (receipt, expense, contra):
        res = tenant.get("/api/money/entries/%d/voucher.pdf" % e["id"])
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "application/pdf" and res.content[:4] == b"%PDF"
        assert e["number"].replace("-", "_") in res.headers["content-disposition"]
    # A voided one still prints, marked void.
    tenant.post("/api/money/entries/%d/void" % expense["id"], json={"reason": "wrong lorry"})
    assert tenant.get("/api/money/entries/%d/voucher.pdf" % expense["id"]).status_code == 200
    # Nobody else's.
    assert second_tenant.get("/api/money/entries/%d/voucher.pdf" % receipt["id"]).status_code == 404
