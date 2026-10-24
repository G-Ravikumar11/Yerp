"""The books, for Tally: an XML of masters and an XML of vouchers, as Tally Prime imports them.

Every voucher balances to the rupee, every ledger a voucher names is in the masters, each line of income or cost carries
its project as a cost centre, and the company's own ledger names are used where it has set them.
"""
import xml.etree.ElementTree as ET
from datetime import date

from test_finance_ledger import certified_ra, certified_sub, money_in, supplier_bill

TODAY = date.today().isoformat()
TALLY_STANDARD = {"Subcontract Charges", "Input CGST", "Input SGST", "Input IGST", "TDS Payable - Contractors",
                  "Labour Cess Payable", "Retention Money Payable", "Mobilisation Advance to Contractors",
                  "Recoveries from Contractors"}


def period(tenant):
    bank = tenant.post("/api/bank-accounts", json={"name": "HDFC current", "kind": "Bank", "opening_balance": 500000}).json()
    box = tenant.post("/api/bank-accounts", json={"name": "Site cash - Vizag", "kind": "Cash"}).json()
    ra = certified_ra(tenant)
    money_in(tenant, doc_type="ra_bill", doc_id=ra["id"], amount=1000, account_id=bank["id"], reference="UTR1")
    sb = supplier_bill(tenant, amount=10000, tax=1800)
    money_in(tenant, doc_type="supplier_bill", doc_id=sb["id"], amount=11800, account_id=bank["id"], mode="Cheque", reference="000451")
    sub = certified_sub(tenant)
    money_in(tenant, doc_type="sub_bill", doc_id=sub["id"], amount=500, account_id=bank["id"])
    tenant.post("/api/money/transfer", json={"from_account_id": bank["id"], "to_account_id": box["id"], "amount": 20000})
    money_in(tenant, doc_type="expense", head="Diesel & fuel", party_name="HP pump", amount=4500, account_id=box["id"],
             job_id=ra["job_id"])
    gone = money_in(tenant, doc_type="expense", head="Rent", party_name="Landlord", amount=999, account_id=bank["id"]).json()["entry"]
    tenant.post("/api/money/entries/%d/void" % gone["id"], json={"reason": "wrong"})
    return ra, sub


def xml(tenant, what, **q):
    res = tenant.get("/api/tally/%s.xml" % what, params=q)
    assert res.status_code == 200, res.text
    assert "attachment" in res.headers["content-disposition"]
    return ET.fromstring(res.content)


def amounts(v):
    return [float(e.findtext("AMOUNT")) for e in v.findall("ALLLEDGERENTRIES.LIST")]


def test_every_voucher_balances_and_names_only_ledgers_in_the_masters(tenant):
    ra, sub = period(tenant)
    vouchers = xml(tenant, "vouchers").findall(".//VOUCHER")
    types = sorted(v.get("VCHTYPE") for v in vouchers)
    assert types == ["Contra", "Journal", "Payment", "Payment", "Payment", "Purchase", "Receipt", "Sales"]
    for v in vouchers:
        assert abs(sum(amounts(v))) < 0.005, ET.tostring(v)
        for e in v.findall("ALLLEDGERENTRIES.LIST"):           # Tally: a debit is negative and deemed positive
            assert (float(e.findtext("AMOUNT")) < 0) == (e.findtext("ISDEEMEDPOSITIVE") == "Yes")
    assert len({v.get("REMOTEID") for v in vouchers}) == len(vouchers)
    masters = xml(tenant, "masters")
    ledgers = {l.get("NAME"): l.findtext("PARENT") for l in masters.findall(".//LEDGER")}
    named = {e.findtext("LEDGERNAME") for v in vouchers for e in v.findall("ALLLEDGERENTRIES.LIST")}
    assert named <= set(ledgers), named - set(ledgers)
    assert ledgers["HDFC current"] == "Bank Accounts" and ledgers["Site cash - Vizag"] == "Cash-in-Hand"
    assert ledgers["Diesel & fuel"] == "Direct Expenses" and ledgers["Sales - Works Contract"] == "Sales Accounts"
    assert "Rent" not in ledgers                                                   # a voided entry is not exported


def test_the_client_bill_and_the_contractor_bill_split_as_the_books_need(tenant):
    ra, sub = period(tenant)
    vouchers = {v.get("VCHTYPE"): v for v in xml(tenant, "vouchers").findall(".//VOUCHER")}
    lines = lambda v: {e.findtext("LEDGERNAME"): float(e.findtext("AMOUNT")) for e in v.findall("ALLLEDGERENTRIES.LIST")}
    sales = lines(vouchers["Sales"])
    assert sales["Sales - Works Contract"] == ra["this_bill"]                    # a credit, positive in Tally
    assert -sum(a for a in sales.values() if a < 0) == round(ra["this_bill"] + ra["cgst_amount"] + ra["sgst_amount"] + ra["igst_amount"], 2)
    journal = lines(vouchers["Journal"])
    bill = sub.get("bill", sub)
    assert bill["this_bill"] > 0 and journal["Subcontract Charges"] == -bill["this_bill"]       # their work, a debit
    assert journal[next(k for k in journal if k not in TALLY_STANDARD)] == bill["net_payable"]   # owed to them, a credit
    # The party line of a bill opens a bill reference in Tally, and a payment against it settles that reference.
    party = [e for e in vouchers["Sales"].findall("ALLLEDGERENTRIES.LIST") if e.find("BILLALLOCATIONS.LIST") is not None]
    assert len(party) == 1 and party[0].findtext("BILLALLOCATIONS.LIST/BILLTYPE") == "New Ref"


def test_a_project_s_costs_carry_it_as_a_cost_centre(tenant):
    ra, _ = period(tenant)
    masters = xml(tenant, "masters")
    centres = [c.get("NAME") for c in masters.findall(".//COSTCENTRE")]
    assert len(centres) >= 1
    diesel = next(v for v in xml(tenant, "vouchers").findall(".//VOUCHER") if "Diesel" in (v.findtext("NARRATION") or ""))
    entry = next(e for e in diesel.findall("ALLLEDGERENTRIES.LIST") if e.findtext("LEDGERNAME") == "Diesel & fuel")
    assert entry.findtext("CATEGORYALLOCATIONS.LIST/COSTCENTREALLOCATIONS.LIST/NAME") in centres
    # The bank's side of the same voucher is not a cost, so it has no cost centre.
    bank = next(e for e in diesel.findall("ALLLEDGERENTRIES.LIST") if e.findtext("LEDGERNAME") == "Site cash - Vizag")
    assert bank.find("CATEGORYALLOCATIONS.LIST") is None


def test_the_company_s_own_ledger_names_and_the_period(tenant):
    period(tenant)
    res = tenant.put("/api/tally/settings", json={"ledgers": {"sales": "Contract Receipts", "nonsense": "x"}, "company": "Yalavarti Projects 2026-27"})
    assert res.status_code == 200, res.text
    s = tenant.get("/api/tally/settings").json()
    assert s["company"] == "Yalavarti Projects 2026-27"
    assert next(l for l in s["ledgers"] if l["key"] == "sales")["name"] == "Contract Receipts"
    root = xml(tenant, "masters")
    assert root.findtext(".//SVCURRENTCOMPANY") == "Yalavarti Projects 2026-27"
    assert "Contract Receipts" in {l.get("NAME") for l in root.findall(".//LEDGER")}
    # A period with nothing in it exports nothing; a period ending before it starts is refused.
    assert xml(tenant, "vouchers", date_from="2001-04-01", date_to="2002-03-31").findall(".//VOUCHER") == []
    assert tenant.get("/api/tally/summary", params={"date_from": TODAY, "date_to": "2001-01-01"}).status_code == 400
    summary = tenant.get("/api/tally/summary").json()
    assert sum(v["count"] for v in summary["vouchers"]) == 8 and not summary["warnings"]


def test_another_company_gets_its_own_books_only(tenant, second_tenant):
    period(tenant)
    assert second_tenant.get("/api/tally/summary").json()["vouchers"] == []
