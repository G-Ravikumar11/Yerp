"""A bank transfer on an expense voucher keeps where the money went, and the voucher is in the ledgers of its project."""
from test_finance_ledger import money_in


def bank(tenant):
    res = tenant.post("/api/bank-accounts", json={"name": "HDFC current", "kind": "Bank", "opening_balance": 500000})
    assert res.status_code == 200, res.text
    return res.json()["id"] if "id" in res.json() else res.json()["account"]["id"]


def job(tenant, name="Alpha Towers"):
    return tenant.post("/api/jobs", json={"name": name, "customer_name": "L&T"}).json()["id"]


def spend(tenant, account, **kw):
    body = dict(doc_type="expense", head="Rent", party_name="Landlord", amount=25000, mode="Bank transfer", reference="UTR123", account_id=account)
    body.update(kw)
    return money_in(tenant, **body)


def test_a_bank_transfer_keeps_the_payees_bank_details(tenant):
    acct = bank(tenant)
    res = spend(tenant, acct, payee_bank="State Bank of India", payee_account="30123456789", payee_ifsc="sbin0001234")
    assert res.status_code == 200, res.text
    e = res.json()["entry"]
    assert (e["payee_bank"], e["payee_account"], e["payee_ifsc"], e["reference"]) == ("State Bank of India", "30123456789", "SBIN0001234", "UTR123")
    listed = [x for x in tenant.get("/api/money/entries").json()["entries"] if x["id"] == e["id"]][0]
    assert listed["payee_ifsc"] == "SBIN0001234"


def test_the_details_are_checked(tenant):
    acct = bank(tenant)
    assert spend(tenant, acct, payee_account="12AB").status_code == 400
    assert spend(tenant, acct, payee_ifsc="SBI123").status_code == 400


def test_only_a_bank_transfer_keeps_them(tenant):
    acct = bank(tenant)
    e = spend(tenant, acct, mode="Cash", reference="", payee_bank="SBI", payee_account="30123456789", payee_ifsc="SBIN0001234").json()["entry"]
    assert (e["payee_bank"], e["payee_account"], e["payee_ifsc"]) == ("", "", "")


def test_tally_narrates_where_the_money_went(tenant):
    acct = bank(tenant)
    spend(tenant, acct, payee_bank="State Bank of India", payee_account="30123456789", payee_ifsc="SBIN0001234")
    vouchers = tenant.get("/api/tally/vouchers").json()
    rows = vouchers["vouchers"] if isinstance(vouchers, dict) else vouchers
    text = " ".join(v.get("narration", "") for v in rows)
    assert "State Bank of India" in text and "30123456789" in text and "SBIN0001234" in text


def test_the_party_ledgers_can_be_narrowed_to_one_project(tenant):
    acct = bank(tenant)
    mine, other = job(tenant, "Alpha Towers"), job(tenant, "Beta Homes")
    for who, jid in (("Landlord A", mine), ("Landlord B", other)):
        assert money_in(tenant, doc_type="on_account", direction="OUT", party_type="supplier", party_name=who, amount=1000, mode="Cash", job_id=jid).status_code == 200
    everyone = {p["party"] for p in tenant.get("/api/ledger/parties").json()["parties"]}
    only = {p["party"] for p in tenant.get("/api/ledger/parties?job_id=%d" % mine).json()["parties"]}
    assert {"Landlord A", "Landlord B"} <= everyone and only == {"Landlord A"}
