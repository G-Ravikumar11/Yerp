"""Bank reconciliation and the cheque register.

The bank's statement comes in as the bank's site gives it - Excel with a title block, CSV, debit and credit columns or
one amount with Dr/Cr - and each line is matched to the entry it is. What is left over is the reconciliation: cheques
written and not yet presented, deposits not yet credited, and what the bank booked on its own.
"""
import io
from datetime import date, timedelta

import openpyxl

from app.services import bank_reco
from test_finance_ledger import money_in, supplier_bill


def day(n):
    return (date.today() - timedelta(days=n)).isoformat()


def dmy(iso):
    y, m, d = iso.split("-")
    return "%s/%s/%s" % (d, m, y)


def hdfc_xlsx(rows):
    """As HDFC's net banking gives it: the bank's name and the account above, then the headings."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["HDFC BANK Ltd."])
    ws.append(["Statement of account", "", "A/c 50100123456789"])
    ws.append([])
    ws.append(["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"])
    for r in rows:
        ws.append(r)
    ws.append([])
    ws.append(["", "STATEMENT SUMMARY"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def setup(tenant):
    bank = tenant.post("/api/bank-accounts", json={"name": "HDFC current", "kind": "Bank", "account_no": "50100123456789",
                                                   "opening_balance": 100000, "opening_date": day(40)}).json()
    receipt = money_in(tenant, doc_type="income", head="Deposit refunded", party_name="APCPDCL", amount=50000,
                       account_id=bank["id"], paid_on=day(10), reference="UTR998877").json()["entry"]
    b1 = supplier_bill(tenant, amount=20000, tax=0)
    b2 = supplier_bill(tenant, vendor="Sai Steels", amount=15000, tax=0)
    chq1 = money_in(tenant, doc_type="supplier_bill", doc_id=b1["id"], amount=20000, account_id=bank["id"],
                    paid_on=day(9), mode="Cheque", reference="000451").json()["entry"]
    chq2 = money_in(tenant, doc_type="supplier_bill", doc_id=b2["id"], amount=15000, account_id=bank["id"],
                    paid_on=day(8), mode="Cheque", reference="000452").json()["entry"]
    return bank, receipt, chq1, chq2


def statement(tenant, bank, rows, name="statement.xlsx"):
    res = tenant.post("/api/bank-reco/%d/statement" % bank["id"], files={"file": (name, hdfc_xlsx(rows), "application/octet-stream")})
    assert res.status_code == 200, res.text
    return res.json()


ROWS = [
    [dmy(day(10)), "NEFT CR-HDFC0000001-APCPDCL-UTR998877", "UTR998877", dmy(day(10)), "", "50,000.00", "1,50,000.00"],
    [dmy(day(4)), "CHQ PAID-MICR CLG-SRI SAI TRADERS", "000451", dmy(day(4)), "20,000.00", "", "1,30,000.00"],
    [dmy(day(3)), "CHRG: NEFT/IMPS CHARGES + GST", "", dmy(day(3)), "590.00", "", "1,29,410.00"],
]


def test_a_statement_is_read_whatever_the_bank_calls_its_columns():
    lines = bank_reco.read_statement(hdfc_xlsx(ROWS), "Acct_Statement.xlsx")
    assert [(l["txn_date"], l["debit"], l["credit"], l["balance"]) for l in lines] == [
        (day(10), 0, 50000, 150000), (day(4), 20000, 0, 130000), (day(3), 590, 0, 129410)]
    sbi = ("Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance\n"
           "%s,%s,BY TRANSFER-NEFT,UTR1,,1000.00,11000.00\n%s,%s,TO CLG,000451,500.00,,10500.00\n"
           % (day(2), day(2), day(1), day(1))).encode()
    got = bank_reco.read_statement(sbi, "sbi.csv")
    assert [(l["credit"], l["debit"], l["reference"]) for l in got] == [(1000, 0, "UTR1"), (0, 500, "000451")]
    one_amount = ("Date,Particulars,Amount,Dr/Cr\n%s,Interest,25.00,CR\n%s,Charges,10.00,DR\n" % (dmy(day(2)), dmy(day(1)))).encode()
    got = bank_reco.read_statement(one_amount, "x.csv")
    assert [(l["credit"], l["debit"]) for l in got] == [(25, 0), (0, 10)]


def test_the_statement_is_matched_and_what_is_left_is_the_reconciliation(tenant):
    bank, receipt, chq1, chq2 = setup(tenant)
    out = statement(tenant, bank, ROWS)
    assert (out["added"], out["matched"]) == (3, 2)
    v = tenant.get("/api/bank-reco/%d?as_of=%s" % (bank["id"], day(0))).json()
    assert [l["narration"] for l in v["lines"]] == ["CHRG: NEFT/IMPS CHARGES + GST"]
    entries = {e["id"]: e for e in tenant.get("/api/money/entries").json()["entries"]}
    assert entries[receipt["id"]]["cleared_on"] == day(10) and entries[chq1["id"]]["cleared_on"] == day(4)
    assert entries[chq2["id"]]["cleared_on"] == ""
    # The charges the bank took, booked from the line in one go.
    booked = tenant.post("/api/bank-reco/lines/%d/book" % v["lines"][0]["id"], json={"head": "Bank charges"})
    assert booked.status_code == 200, booked.text
    b = tenant.get("/api/bank-reco/%d?as_of=%s" % (bank["id"], day(0))).json()["brs"]
    assert b["books"] == 100000 + 50000 - 20000 - 15000 - 590
    assert [r["reference"] for r in b["not_presented"]] == ["000452"] and b["not_presented_total"] == 15000
    assert b["bank_should_show"] == 129410 and b["statement_balance"] == 129410 and b["difference"] == 0
    pdf = tenant.get("/api/bank-reco/%d/brs.pdf?as_of=%s" % (bank["id"], day(0)))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    # The same statement downloaded again stores nothing twice.
    again = statement(tenant, bank, ROWS)
    assert (again["added"], again["already_in"]) == (0, 3)


def test_a_line_is_matched_by_hand_only_to_what_it_can_be(tenant):
    bank, receipt, chq1, chq2 = setup(tenant)
    statement(tenant, bank, [[dmy(day(2)), "CLG 000452 SAI STEELS", "", dmy(day(2)), "15,000.00", "", ""]])
    v = tenant.get("/api/bank-reco/%d" % bank["id"]).json()
    assert v["counts"]["matched"] == 1                                    # the cheque number settled it
    line = tenant.post("/api/bank-reco/%d/statement" % bank["id"],
                       files={"file": ("s.xlsx", hdfc_xlsx([[dmy(day(1)), "SOMETHING", "", "", "", "9,999.00", ""]]), "x")})
    lid = tenant.get("/api/bank-reco/%d" % bank["id"]).json()["lines"][0]["id"]
    wrong = tenant.post("/api/bank-reco/lines/%d/match" % lid, json={"entry_id": chq1["id"]})
    assert wrong.status_code == 400                                       # out of the bank is not 9,999 in
    assert tenant.post("/api/bank-reco/lines/%d/ignore" % lid).status_code == 200
    assert tenant.get("/api/bank-reco/%d" % bank["id"]).json()["counts"]["ignored"] == 1


def test_voiding_a_matched_entry_puts_its_line_back(tenant):
    bank, receipt, *_ = setup(tenant)
    statement(tenant, bank, ROWS[:1])
    tenant.post("/api/money/entries/%d/void" % receipt["id"], json={"reason": "entered twice"})
    lines = tenant.get("/api/bank-reco/%d" % bank["id"]).json()["lines"]
    assert len(lines) == 1 and lines[0]["status"] == "UNMATCHED"


def test_voiding_a_transfer_puts_both_banks_lines_back(tenant):
    """Voided from either side, both legs go - and so the line on the other bank's statement is unmatched too."""
    hdfc = tenant.post("/api/bank-accounts", json={"name": "HDFC current", "kind": "Bank", "opening_balance": 100000,
                                                   "opening_date": day(40)}).json()
    sbi = tenant.post("/api/bank-accounts", json={"name": "SBI current", "kind": "Bank", "opening_balance": 0,
                                                  "opening_date": day(40)}).json()
    moved = tenant.post("/api/money/transfer", json={"from_account_id": hdfc["id"], "to_account_id": sbi["id"],
                                                     "amount": 25000, "paid_on": day(5), "reference": "UTR445566"})
    assert moved.status_code == 200, moved.text
    statement(tenant, hdfc, [[dmy(day(5)), "NEFT DR-SBI-UTR445566", "UTR445566", dmy(day(5)), "25,000.00", "", "75,000.00"]])
    statement(tenant, sbi, [[dmy(day(5)), "NEFT CR-HDFC-UTR445566", "UTR445566", dmy(day(5)), "", "25,000.00", "25,000.00"]])
    assert [tenant.get("/api/bank-reco/%d" % b["id"]).json()["counts"]["matched"] for b in (hdfc, sbi)] == [1, 1]
    voided = tenant.post("/api/money/entries/%d/void" % moved.json()["entry"]["id"], json={"reason": "wrong account"})
    assert voided.status_code == 200, voided.text
    for b in (hdfc, sbi):
        v = tenant.get("/api/bank-reco/%d" % b["id"]).json()
        assert v["counts"]["matched"] == 0 and [l["status"] for l in v["lines"]] == ["UNMATCHED"]


def test_identical_lines_in_one_statement_are_all_kept_and_still_not_stored_twice(tenant):
    """Two equal charges on one day, on a statement with no balance column, are two transactions."""
    bank = tenant.post("/api/bank-accounts", json={"name": "HDFC current", "kind": "Bank", "opening_balance": 0,
                                                   "opening_date": day(40)}).json()
    charge = [dmy(day(3)), "SMS ALERT CHARGES", "", dmy(day(3)), "17.70", "", ""]
    first = statement(tenant, bank, [charge, charge])
    assert (first["added"], first["already_in"]) == (2, 0)
    # The same statement again stores nothing; a later one with a third such charge stores just that one.
    assert (statement(tenant, bank, [charge, charge])["added"]) == 0
    third = statement(tenant, bank, [charge, charge, charge])
    assert (third["added"], third["already_in"]) == (1, 2)
    assert tenant.get("/api/bank-reco/%d" % bank["id"]).json()["counts"]["unmatched"] == 3


def test_the_cheque_register(tenant):
    bank, receipt, chq1, chq2 = setup(tenant)
    old = supplier_bill(tenant, vendor="Old Vendor", amount=5000, tax=0)
    stale = money_in(tenant, doc_type="supplier_bill", doc_id=old["id"], amount=5000, account_id=bank["id"],
                     paid_on=day(120), mode="Cheque", reference="000300").json()["entry"]
    got = money_in(tenant, doc_type="income", head="Scrap sale", party_name="Scrap dealer", amount=8000,
                   account_id=bank["id"], paid_on=day(5), mode="Cheque", reference="778812").json()["entry"]
    # Cleared by hand, from the passbook - not before it was written, not in the future.
    assert tenant.post("/api/money/entries/%d/clear" % chq1["id"], json={"cleared_on": day(20)}).status_code == 400
    assert tenant.post("/api/money/entries/%d/clear" % chq1["id"], json={"cleared_on": day(3)}).status_code == 200
    # A cheque received and returned unpaid.
    tenant.post("/api/money/entries/%d/void" % got["id"], json={"reason": "Cheque bounced: insufficient funds"})
    reg = tenant.get("/api/cheques").json()
    status = {c["id"]: c["status"] for c in reg["cheques"]}
    assert status[chq1["id"]] == "CLEARED" and status[chq2["id"]] == "PENDING"
    assert status[stale["id"]] == "STALE" and status[got["id"]] == "BOUNCED"
    assert reg["summary"]["issued_pending"] == 20000 and reg["summary"]["stale"] == 1 and reg["summary"]["bounced"] == 1
    assert [c["id"] for c in tenant.get("/api/cheques?status=stale").json()["cheques"]] == [stale["id"]]


def test_another_company_cannot_reach_it(tenant, second_tenant):
    bank, *_ = setup(tenant)
    assert second_tenant.get("/api/bank-reco/%d" % bank["id"]).status_code == 404
    assert second_tenant.get("/api/bank-reco/%d/brs.pdf" % bank["id"]).status_code == 404
