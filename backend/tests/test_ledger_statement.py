"""A statement of account is available for every kind of party, with or without a record of its own."""
from test_finance_ledger import money_in


def test_a_client_has_a_statement_with_an_empty_master_and_a_pdf(tenant):
    # A client has no supplier or contractor record: its statement still comes whole, with an empty master and not none.
    assert money_in(tenant, doc_type="on_account", direction="IN", party_type="client", party_name="Kokapet LLP", amount=5000, mode="Cash").status_code == 200
    d = tenant.get("/api/ledger/statement", params={"party_type": "client", "party": "Kokapet LLP"})
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["master"] == {} and body["party"] == "Kokapet LLP" and len(body["rows"]) == 1
    pdf = tenant.get("/api/ledger/statement.pdf", params={"party_type": "client", "party": "Kokapet LLP"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"


def test_a_supplier_not_on_the_master_has_an_empty_one(tenant):
    assert money_in(tenant, doc_type="on_account", direction="OUT", party_type="supplier", party_name="Roadside Traders", amount=900, mode="Cash").status_code == 200
    body = tenant.get("/api/ledger/statement", params={"party_type": "supplier", "party": "Roadside Traders"}).json()
    assert body["master"] == {}
    assert tenant.get("/api/ledger/statement.pdf", params={"party_type": "supplier", "party": "Roadside Traders"}).status_code == 200


def test_the_entries_and_the_reconciliation_download(tenant):
    acct = tenant.post("/api/bank-accounts", json={"name": "HDFC current", "kind": "Bank", "opening_balance": 1000}).json()["id"]
    xlsx = tenant.get("/api/money/entries.xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    brs = tenant.get("/api/bank-reco/%d/brs.pdf" % acct)
    assert brs.status_code == 200 and brs.content[:4] == b"%PDF"
