"""The controls a set of books needs before an auditor will sign them.

1. A closed period: nothing dated in it is entered, moved or voided; a cleared entry is voided by the Master alone.
2. A payment date is a real day, and not next month.
3. The reconciliation is audit-logged, a matched line is not re-matched in passing, and only a bank clears an entry.
4. A cheque is paid once.
5. Bank accounts are added by whoever pays, and can be corrected.
6. An account's opening balance stands on its opening date.
7. The profit and loss is on the accrual basis and the balance sheet balances.
8. Aged receivables list every kind of claim on a customer, aged as the Owed page ages them.
9. An approval not paid in time expires.
"""
from datetime import date, datetime, timedelta

from app import db as database
from app import models

from test_bank_reco import day, dmy, statement
from test_finance_ledger import certified_ra, certified_sub, money_in, supplier_bill
from test_payment_approval import office, person  # noqa: F401  (the fixture)


def ahead(n):
    return (date.today() + timedelta(days=n)).isoformat()


def bank(tenant, name="HDFC current", opening=100000, opened=None, kind="Bank"):
    res = tenant.post("/api/bank-accounts", json={"name": name, "kind": kind, "opening_balance": opening,
                                                  "opening_date": opened or day(60)})
    assert res.status_code == 200, res.text
    return res.json()


def income(tenant, acc, amount=1000, on=None, **kw):
    return money_in(tenant, doc_type="income", head="Scrap sale", party_name="Scrap dealer", amount=amount,
                    account_id=acc["id"], paid_on=on or day(1), **kw)


def audited(action, account_id):
    with database.SessionLocal() as db:
        return db.query(models.DBAuditLog).filter(models.DBAuditLog.action == action,
                                                  models.DBAuditLog.entity_id == account_id).count()


# --- 1. the closed period ---------------------------------------------------------------------------------------------

def test_the_master_closes_the_books_and_nothing_dated_in_them_moves(tenant):
    acc = bank(tenant)
    other = bank(tenant, "SBI current", 0)
    early = income(tenant, acc, on=day(20)).json()["entry"]
    assert tenant.put("/api/money/lock", json={"locked_upto": ahead(0)}).status_code == 400     # yesterday at the latest
    res = tenant.put("/api/money/lock", json={"locked_upto": day(10)})
    assert res.status_code == 200, res.text
    assert tenant.get("/api/money/lock").json()["locked_upto"] == day(10)
    refused = income(tenant, acc, on=day(10))
    assert refused.status_code == 409 and "closed" in refused.json()["detail"]
    assert income(tenant, acc, on=day(9)).status_code == 200
    moved = tenant.post("/api/money/transfer", json={"from_account_id": acc["id"], "to_account_id": other["id"],
                                                     "amount": 10, "paid_on": day(15)})
    assert moved.status_code == 409
    assert tenant.post("/api/money/entries/%d/void" % early["id"], json={"reason": "wrong"}).status_code == 409
    # Reopened, it can be corrected.
    assert tenant.put("/api/money/lock", json={"locked_upto": ""}).status_code == 200
    assert tenant.post("/api/money/entries/%d/void" % early["id"], json={"reason": "wrong"}).status_code == 200


def test_only_the_master_closes_the_books(tenant):
    clerk = person(tenant, extra="bills.pay")
    try:
        assert clerk.put("/api/money/lock", json={"locked_upto": day(10)}).status_code == 403
    finally:
        clerk.__exit__(None, None, None)


def test_an_entry_the_bank_has_cleared_is_voided_by_the_master_alone(tenant):
    acc = bank(tenant)
    e = income(tenant, acc, on=day(5), mode="Cheque", reference="778812").json()["entry"]
    assert tenant.post("/api/money/entries/%d/clear" % e["id"], json={"cleared_on": day(3)}).status_code == 200
    clerk = person(tenant, extra="bills.pay")
    try:
        res = clerk.post("/api/money/entries/%d/void" % e["id"], json={"reason": "bounced"})
        assert res.status_code == 409 and "Master" in res.json()["detail"]
    finally:
        clerk.__exit__(None, None, None)
    assert tenant.post("/api/money/entries/%d/void" % e["id"], json={"reason": "bounced"}).status_code == 200


# --- 2. dates ------------------------------------------------------------------------------------------------------------

def test_a_payment_date_is_a_real_day_and_not_next_month(tenant):
    acc = bank(tenant)
    assert income(tenant, acc, on="31/10/2026").status_code == 400
    assert income(tenant, acc, on="2026-02-30").status_code == 400
    assert income(tenant, acc, on=ahead(30)).status_code == 400
    assert income(tenant, acc, on=ahead(1)).status_code == 200
    other = bank(tenant, "SBI current", 0)
    res = tenant.post("/api/money/transfer", json={"from_account_id": acc["id"], "to_account_id": other["id"],
                                                   "amount": 10, "paid_on": "yesterday"})
    assert res.status_code == 400


# --- 3. the reconciliation --------------------------------------------------------------------------------------------

def test_a_matched_line_is_unmatched_before_it_is_matched_again_and_it_is_all_logged(tenant):
    acc = bank(tenant)
    a = income(tenant, acc, amount=5000, on=day(6), reference="UTR111").json()["entry"]
    b = income(tenant, acc, amount=5000, on=day(5), reference="UTR222").json()["entry"]
    statement(tenant, acc, [[dmy(day(5)), "NEFT CR UTR111", "UTR111", "", "", "5,000.00", ""]])
    with database.SessionLocal() as db:
        line = db.query(models.DBBankStatementLine).filter(models.DBBankStatementLine.account_id == acc["id"]).first()
        lid, matched_to = line.id, line.entry_id
    assert matched_to == a["id"]
    again = tenant.post("/api/bank-reco/lines/%d/match" % lid, json={"entry_id": b["id"]})
    assert again.status_code == 409 and "Unmatch" in again.json()["detail"]
    assert tenant.post("/api/bank-reco/lines/%d/unmatch" % lid).status_code == 200
    assert tenant.post("/api/bank-reco/lines/%d/match" % lid, json={"entry_id": b["id"]}).status_code == 200
    assert tenant.post("/api/bank-reco/lines/%d/ignore" % lid).status_code == 200
    assert [audited(a, acc["id"]) for a in ("bank_line_unmatched", "bank_line_matched", "bank_line_ignored")] == [1, 1, 1]


def test_only_a_bank_clears_an_entry_and_a_void_one_never(tenant):
    box = bank(tenant, "Site cash", 5000, kind="Cash")
    cash = money_in(tenant, doc_type="expense", head="Site expenses", party_name="Tea stall", amount=100,
                    account_id=box["id"], paid_on=day(2)).json()["entry"]
    assert tenant.post("/api/money/entries/%d/clear" % cash["id"], json={"cleared_on": day(1)}).status_code == 409
    acc = bank(tenant)
    e = income(tenant, acc, on=day(3)).json()["entry"]
    tenant.post("/api/money/entries/%d/void" % e["id"], json={"reason": "wrong"})
    assert tenant.post("/api/money/entries/%d/clear" % e["id"], json={"cleared_on": day(1)}).status_code == 409


# --- 4. cheques -------------------------------------------------------------------------------------------------------

def test_a_cheque_is_paid_once_from_an_account(tenant):
    acc = bank(tenant, opening=500000)
    b1, b2 = supplier_bill(tenant, amount=1000, tax=0), supplier_bill(tenant, vendor="Sai Steels", amount=1000, tax=0)
    first = money_in(tenant, doc_type="supplier_bill", doc_id=b1["id"], amount=1000, account_id=acc["id"],
                     mode="Cheque", reference="000451", paid_on=day(2))
    assert first.status_code == 200, first.text
    twice = money_in(tenant, doc_type="supplier_bill", doc_id=b2["id"], amount=1000, account_id=acc["id"],
                     mode="Cheque", reference="451", paid_on=day(1))
    assert twice.status_code == 409 and "already entered" in twice.json()["detail"]
    other = bank(tenant, "SBI current", 0)
    moved = tenant.post("/api/money/transfer", json={"from_account_id": acc["id"], "to_account_id": other["id"],
                                                     "amount": 10, "mode": "Cheque", "reference": "000451"})
    assert moved.status_code == 409
    # Voided (bounced, torn up), the number is free again.
    tenant.post("/api/money/entries/%d/void" % first.json()["entry"]["id"], json={"reason": "cancelled cheque"})
    assert money_in(tenant, doc_type="supplier_bill", doc_id=b2["id"], amount=1000, account_id=acc["id"],
                    mode="Cheque", reference="000451", paid_on=day(1)).status_code == 200


# --- 5. bank accounts -------------------------------------------------------------------------------------------------

def test_whoever_pays_adds_an_account_and_it_can_be_corrected(tenant):
    clerk = person(tenant, extra="bills.pay")
    try:
        res = clerk.post("/api/bank-accounts", json={"name": "Axis current", "opening_balance": 1000, "opening_date": day(30)})
        assert res.status_code == 200, res.text
        acc = res.json()
    finally:
        clerk.__exit__(None, None, None)
    fixed = tenant.put("/api/bank-accounts/%d" % acc["id"], json={"name": "Axis current - HO", "opening_balance": 2500,
                                                                 "ifsc": "utib0000123"})
    assert fixed.status_code == 200, fixed.text
    got = fixed.json()
    assert got["name"] == "Axis current - HO" and got["opening_balance"] == 2500 and got["ifsc"] == "UTIB0000123"
    assert audited("bank_account_opening_changed", acc["id"]) == 1
    tenant.put("/api/money/lock", json={"locked_upto": day(10)})
    res = tenant.put("/api/bank-accounts/%d" % acc["id"], json={"opening_balance": 9999})
    assert res.status_code == 409
    assert tenant.put("/api/bank-accounts/%d" % acc["id"], json={"is_active": False}).json()["is_active"] is False


# --- 6. the opening date ----------------------------------------------------------------------------------------------

def test_what_moved_before_the_opening_date_is_inside_the_opening_balance(tenant):
    acc = bank(tenant, opening=100000, opened=day(10))
    income(tenant, acc, amount=7000, on=day(20))                  # before the account's books start
    income(tenant, acc, amount=3000, on=day(5))
    listed = next(a for a in tenant.get("/api/bank-accounts").json()["accounts"] if a["id"] == acc["id"])
    assert listed["balance"] == 103000
    book = tenant.get("/api/money/book?account_id=%d" % acc["id"]).json()
    assert book["opening"] == 100000 and book["closing"] == 103000 and len(book["rows"]) == 1
    assert tenant.get("/api/bank-reco/%d?as_of=%s" % (acc["id"], day(0))).json()["brs"]["books"] == 103000
    bank(tenant, "SBI current", 50000, opened=day(10))
    everything = tenant.get("/api/money/book").json()
    assert everything["opening"] == 150000 and everything["closing"] == 153000


# --- 7. the profit and loss and the balance sheet ---------------------------------------------------------------------

def test_the_profit_and_loss_is_on_the_accrual_basis(tenant):
    ra = certified_ra(tenant)
    sub = certified_sub(tenant)
    supplier_bill(tenant, amount=10000, tax=1800)
    tenant.post("/api/bills", json={"number": "DRAFT-9", "vendor_name": "X", "amount": 500, "total": 500, "status": "Draft"})
    acc = bank(tenant)
    money_in(tenant, doc_type="expense", head="Diesel & fuel", party_name="HP pump", amount=4500, account_id=acc["id"])
    income(tenant, acc, amount=800, on=day(0))
    pl = tenant.get("/api/reports/profit-loss").json()
    assert pl["basis"] == "accrual"
    assert pl["revenue_by_source"]["client_bills"] == ra["this_bill"] and pl["revenue_by_source"]["other_income"] == 800
    assert pl["expenses_by_source"] == {"supplier_bills": 10000, "subcontractor_bills": sub["this_bill"],
                                        "expense_vouchers": 4500}
    assert pl["net_profit"] == round(pl["total_revenue"] - pl["total_expenses"], 2)
    assert tenant.get("/api/reports/profit-loss?date_to=2000-01-01").json()["total_revenue"] == 0
    assert tenant.get("/api/reports/profit-loss?date_from=bad").status_code == 400


def test_the_balance_sheet_balances(tenant):
    ra = certified_ra(tenant)
    acc = bank(tenant, opening=200000)
    money_in(tenant, doc_type="ra_bill", doc_id=ra["id"], amount=1000, account_id=acc["id"], paid_on=day(1))
    bill = supplier_bill(tenant, amount=10000, tax=1800)
    money_in(tenant, doc_type="supplier_bill", doc_id=bill["id"], amount=1800, account_id=acc["id"], paid_on=day(1))
    money_in(tenant, doc_type="on_account", direction="OUT", party_type="supplier", party_name="Sai Steels",
             amount=5000, account_id=acc["id"], paid_on=day(1))
    bs = tenant.get("/api/reports/balance-sheet").json()
    a, li = bs["assets"], bs["liabilities"]
    assert a["bank_and_cash"] == 200000 + 1000 - 1800 - 5000
    assert a["accounts_receivable"] == round(ra["net_payable"] - 1000, 2)
    assert a["advances_paid"] == 5000 and li["accounts_payable"] == 10000
    assert a["retention_receivable"] == ra["retention_amount"]
    assert bs["total_assets"] == round(bs["total_liabilities"] + bs["total_equity"], 2)
    assert bs["balances"] is True


# --- 8. aged receivables ----------------------------------------------------------------------------------------------

def test_aged_receivables_include_certified_bills_and_age_as_the_owed_page(tenant):
    ra = certified_ra(tenant)
    aged = tenant.get("/api/reports/aged-receivables").json()
    row = next(r for r in aged["invoices"] if r["number"] == ra["number"])
    assert row["kind"] == "RA bill" and row["bucket"] == "current"
    owed = tenant.get("/api/money/receivables").json()
    assert aged["total_outstanding"] == owed["summary"]["owed"]


# --- 9. approvals expire ----------------------------------------------------------------------------------------------

def test_an_approval_not_paid_in_time_expires(tenant, office):  # noqa: F811
    clerk, head = office
    bill = supplier_bill(tenant, amount=50000, tax=0)
    r = clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 50000}).json()["request"]
    assert head.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).status_code == 200
    with database.SessionLocal() as db:
        row = db.query(models.DBPaymentRequest).filter(models.DBPaymentRequest.id == r["id"]).first()
        row.approved_at = (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
    listed = tenant.get("/api/payment-requests").json()
    mine = next(x for x in listed["requests"] if x["id"] == r["id"])
    assert mine["expired"] is True and listed["summary"]["to_pay"] == 0
    res = clerk.post("/api/payment-requests/%d/pay" % r["id"], json={})
    assert res.status_code == 409 and "expired" in res.json()["detail"]
    # The bill can be asked for again.
    again = clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 50000})
    assert again.status_code == 200, again.text
