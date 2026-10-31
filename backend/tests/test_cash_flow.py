"""The dashboard's cash chart, totalled on the server: every entry (not the last thousand), a transfer between our own
banks neither in nor out, a voided entry nothing, and the balance starting from the accounts' opening balances - the
same figure the all-accounts cash book closes on."""
from datetime import date

from test_accounts_vouchers import account


def month():
    return date.today().strftime("%Y-%m")


def entry(tenant, direction, amount, account_id, paid_on=None, **extra):
    res = tenant.post("/api/money/entries", json={"doc_type": "on_account", "direction": direction, "party_type": "other",
                                                  "party_name": "Walk-in", "amount": amount, "account_id": account_id,
                                                  "paid_on": paid_on or date.today().isoformat(), **extra})
    assert res.status_code == 200, res.text
    return res.json()["entry"]


def flow(tenant, months=12):
    res = tenant.get("/api/money/cash-flow", params={"months": months})
    assert res.status_code == 200, res.text
    return res.json()


def test_a_transfer_between_our_banks_is_neither_in_nor_out(tenant):
    sbi = account(tenant, "SBI current", "Bank", 500000)
    hdfc = account(tenant, "HDFC current", "Bank", 100000)
    assert tenant.post("/api/money/transfer", json={"from_account_id": sbi["id"], "to_account_id": hdfc["id"], "amount": 200000}).status_code == 200
    entry(tenant, "IN", 50000, sbi["id"])
    entry(tenant, "OUT", 20000, hdfc["id"])
    now = flow(tenant)["months"][-1]
    assert (now["month"], now["received"], now["paid"], now["net"]) == (month(), 50000, 20000, 30000)
    assert now["running"] == 630000                                          # 600000 opening + 30000


def test_the_balance_starts_from_the_opening_balances_and_agrees_with_the_cash_book(tenant):
    a = account(tenant, "SBI current", "Bank", 250000)
    entry(tenant, "IN", 1000, a["id"])
    out = flow(tenant)
    assert out["opening"] == 250000 and out["months"][0]["running"] == 250000
    assert out["months"][-1]["running"] == tenant.get("/api/money/book").json()["closing"] == 251000


def test_a_voided_entry_is_nothing(tenant):
    a = account(tenant, "SBI current", "Bank", 0)
    e = entry(tenant, "IN", 9999, a["id"])
    assert tenant.post("/api/money/entries/%d/void" % e["id"], json={"reason": "Keyed twice"}).status_code == 200
    now = flow(tenant)["months"][-1]
    assert (now["received"], now["running"]) == (0, 0)


def test_every_entry_counts_not_only_the_last_thousand(tenant):
    a = account(tenant, "SBI current", "Bank", 0)
    from app import db as database, models
    with database.SessionLocal() as db:
        client_id = db.get(models.DBBankAccount, a["id"]).client_id
        today = date.today().isoformat()
        db.add_all([models.DBMoneyEntry(client_id=client_id, number="RCT-%05d" % i, direction="IN", party_type="other", party_name="x",
                                        doc_type="on_account", account_id=a["id"], amount=10.0, paid_on=today, mode="Cash", voided=False)
                    for i in range(1200)])
        db.commit()
    now = flow(tenant)["months"][-1]
    assert (now["received"], now["running"]) == (12000, 12000)


def test_months_before_the_window_are_in_the_opening_balance(tenant):
    res = tenant.post("/api/bank-accounts", json={"name": "SBI current", "kind": "Bank", "opening_balance": 0, "opening_date": "2019-04-01"})
    assert res.status_code == 200, res.text
    a = res.json()
    entry(tenant, "IN", 700, a["id"], paid_on="2020-01-15")
    out = flow(tenant, months=3)
    assert len(out["months"]) == 3 and out["opening"] == 700 and out["months"][0]["received"] == 0 and out["months"][-1]["running"] == 700
