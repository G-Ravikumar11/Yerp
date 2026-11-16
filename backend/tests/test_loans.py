"""Loans and EMIs: what was borrowed, and the instalments that repay it.

A loan is a liability on its own ledger. An instalment leaves the bank as one payment (the EMI) and is split in the books: the
principal repays the loan, the interest is an expense. Paying one is the ordinary payment, so approval, the books lock, the
account, the void and the voucher all behave as they do for a bill.
"""
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pytest
from conftest import make_employee

from app import models
from app.db import SessionLocal
from app.models.loans import DBLoan
from app.services.accounts_watch import accounts_items
from app.services.loans import build_schedule
from app.services.recurring_payments import following

TODAY = date.today()
NEXT_MONTH = following(TODAY, TODAY.day)
P = 1_200_000


def bank(tenant, name="HDFC current", balance=5_000_000):
    res = tenant.post("/api/bank-accounts", json={"name": name, "kind": "Bank", "opening_balance": balance})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def new_loan(tenant, account, **kw):
    body = {"lender": "HDFC Bank", "name": "Excavator", "kind": "secured", "principal": P, "annual_rate": 9, "months": 12,
            "taken_on": TODAY.isoformat(), "first_due": NEXT_MONTH.isoformat(), "account_id": account, **kw}
    return tenant.post("/api/loans", json=body)


def made(tenant, account=None, **kw):
    res = new_loan(tenant, account if account is not None else bank(tenant), **kw)
    assert res.status_code == 200, res.text
    return res.json()["loan"]


def running(tenant, **kw):
    """A loan already running before these books began: what was left of it on a past day."""
    body = {"lender": "SBI", "name": "Term loan", "kind": "secured", "principal": 800_000, "annual_rate": 10, "months": 10, "existing": True,
            "taken_on": (TODAY - timedelta(days=45)).isoformat(), "first_due": (TODAY + timedelta(days=5)).isoformat(), **kw}
    res = tenant.post("/api/loans", json=body)
    assert res.status_code == 200, res.text
    return res.json()["loan"]


def pay(tenant, instalment, account, **kw):
    body = {"doc_type": "loan_instalment", "doc_id": instalment["id"], "amount": instalment["total"], "account_id": account,
            "mode": "Bank transfer", "reference": "UTR-%d" % instalment["id"], "paid_on": TODAY.isoformat(), **kw}
    return tenant.post("/api/money/entries", json=body)


def get(tenant, loan):
    return tenant.get("/api/loans/%d" % loan["id"]).json()


def vouchers(tenant):
    return tenant.get("/api/tally/vouchers?date_from=2020-01-01&date_to=2030-12-31").json()["vouchers"]


# --- the schedule ------------------------------------------------------------------------------------------------------------

def test_the_schedule_is_a_reducing_balance_loan_that_clears_to_the_paisa():
    rows, emi = build_schedule(P, 9, 12, date(2026, 12, 5))
    r = 0.09 / 12
    assert emi == pytest.approx(P * r * (1 + r) ** 12 / ((1 + r) ** 12 - 1), abs=0.01)
    assert round(sum(p for _, p, _ in rows), 2) == P                                  # the principal repaid is exactly what was borrowed
    assert rows[0][2] == 9000.00                                                       # the first month's interest: 1,200,000 x 0.75%
    assert [i for _, _, i in rows] == sorted((i for _, _, i in rows), reverse=True)   # interest falls as the balance does
    for _, p, i in rows[:-1]:
        assert p + i == pytest.approx(emi, abs=0.01)
    assert rows[-1][1] + rows[-1][2] == pytest.approx(emi, abs=1.0)                    # the last one absorbs the rounding
    assert [d for d, _, _ in rows][:3] == [date(2026, 12, 5), date(2027, 1, 5), date(2027, 2, 5)]


def test_a_day_a_short_month_lacks_falls_on_its_last_and_the_31st_stays_the_31st():
    rows, _ = build_schedule(100000, 12, 4, date(2027, 1, 31))
    assert [d for d, _, _ in rows] == [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)]


def test_a_loan_with_no_interest_repays_in_equal_parts():
    rows, emi = build_schedule(100000, 0, 10, date(2027, 1, 5))
    assert emi == 10000 and all((p, i) == (10000, 0) for _, p, i in rows)


def test_the_banks_own_emi_is_used_and_the_last_instalment_clears_the_rest():
    rows, emi = build_schedule(P, 9, 12, date(2026, 12, 5), emi=200000)
    assert emi == 200000 and len(rows) < 12                                           # a bigger EMI repays it sooner
    assert round(sum(p for _, p, _ in rows), 2) == P
    with pytest.raises(Exception) as err:
        build_schedule(P, 9, 12, date(2026, 12, 5), emi=9000)                          # no more than the first month's interest
    assert "never be repaid" in str(err.value.detail)


# --- a new loan, and one already running --------------------------------------------------------------------------------

def test_a_new_loan_has_its_schedule_and_its_money_in_the_bank_book(tenant):
    acct = bank(tenant)
    before = next(a for a in tenant.get("/api/bank-accounts").json()["accounts"] if a["id"] == acct)["balance"]
    res = new_loan(tenant, acct, note="Sanctioned 3 Nov")
    assert res.status_code == 200, res.text
    loan = res.json()["loan"]
    assert loan["number"] == "LN-0001" and loan["instalments"] == 12 and loan["status"] == "ACTIVE" and loan["received"] is True
    assert loan["outstanding"] == P and loan["paid"] == 0 and loan["next"]["due_on"] == NEXT_MONTH.isoformat() and loan["next"]["interest"] == 9000.0
    assert len(loan["schedule"]) == 12 and sum(i["principal"] for i in loan["schedule"]) == pytest.approx(P)
    assert "The money received is in the bank book" in res.json()["message"]
    # The money received is a receipt against the loan, in the bank book.
    [e] = [e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "loan_disbursal"]
    assert (e["direction"], e["amount"], e["party_name"], e["doc_id"], e["paid_on"]) == ("IN", P, "HDFC Bank", loan["id"], TODAY.isoformat())
    after = next(a for a in tenant.get("/api/bank-accounts").json()["accounts"] if a["id"] == acct)["balance"]
    assert round(after - before, 2) == P
    # And the lender is not a party with an advance: a loan is not a supplier's ledger.
    assert [p for p in tenant.get("/api/ledger/parties").json()["parties"] if p["party"] == "HDFC Bank"] == []


def test_a_loan_already_running_is_entered_with_what_was_left_and_no_money_moves(tenant):
    loan = running(tenant)
    assert loan["existing"] is True and loan["received"] is True and loan["outstanding"] == 800_000
    assert [e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "loan_disbursal"] == []
    # The books carry it as an opening balance: against the one offset ledger, to the loan's own ledger.
    [j] = [v for v in vouchers(tenant) if v["number"] == "LN-0001/OPEN"]
    assert {l["ledger"]: (l["debit"], l["credit"]) for l in j["lines"]} == {"Opening Balance Adjustment": (800_000, 0), "Loan - SBI - Term loan": (0, 800_000)}
    assert tenant.get("/api/reports/balance-sheet").json()["liabilities"]["loans"] == 800_000


def test_what_is_refused(tenant):
    acct = bank(tenant)
    assert new_loan(tenant, acct, lender="  ").status_code == 400
    assert new_loan(tenant, acct, kind="mortgage").status_code == 400
    assert new_loan(tenant, acct, principal=0).status_code == 400
    assert new_loan(tenant, acct, principal=10 ** 12).status_code == 400
    assert new_loan(tenant, acct, annual_rate=101).status_code == 400
    assert new_loan(tenant, acct, annual_rate=-1).status_code == 400
    assert new_loan(tenant, acct, months=0).status_code == 400
    assert new_loan(tenant, acct, months=601).status_code == 400
    assert new_loan(tenant, acct, taken_on="3 November").status_code == 400
    assert new_loan(tenant, acct, taken_on=(TODAY + timedelta(days=3)).isoformat()).status_code == 400       # money not yet received
    assert new_loan(tenant, acct, first_due=TODAY.isoformat()).status_code == 400                              # the first falls after receipt
    assert new_loan(tenant, acct, account_id=None).status_code == 400                                           # a new loan says where the money went
    assert new_loan(tenant, 999999).status_code == 404
    assert new_loan(tenant, acct, emi=100).status_code == 400
    assert tenant.get("/api/loans").json()["loans"] == []
    assert [e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "loan_disbursal"] == []     # nothing half-done


def test_the_same_loan_is_not_entered_twice(tenant):
    acct = bank(tenant)
    made(tenant, acct)
    again = new_loan(tenant, acct)
    assert again.status_code == 409 and "already entered" in again.json()["detail"]
    assert new_loan(tenant, acct, principal=P + 1).status_code == 200


def test_a_closed_books_period_refuses_the_money_received(tenant):
    acct = bank(tenant)
    assert tenant.put("/api/money/lock", json={"locked_upto": (TODAY - timedelta(days=1)).isoformat()}).status_code == 200
    shut = new_loan(tenant, acct, taken_on=(TODAY - timedelta(days=5)).isoformat(), first_due=TODAY.isoformat())
    assert shut.status_code == 409 and "closed" in shut.json()["detail"]
    assert tenant.get("/api/loans").json()["loans"] == []


# --- paying an instalment -------------------------------------------------------------------------------------------------------

def test_an_instalment_is_paid_whole_and_settles_it(tenant):
    acct = bank(tenant)
    loan = made(tenant, acct)
    first = loan["schedule"][0]
    res = pay(tenant, first, acct)
    assert res.status_code == 200, res.text
    assert res.json()["settled"] == first["total"] and res.json()["left"] in (0, 0.0, None)
    after = get(tenant, loan)
    assert after["schedule"][0]["status"] == "PAID" and after["schedule"][0]["paid_on"] == TODAY.isoformat()
    assert after["paid"] == 1 and after["repaid"] == first["principal"] and after["outstanding"] == pytest.approx(P - first["principal"])
    assert after["interest_paid"] == first["interest"] and after["next"]["seq"] == 2
    entry = next(e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "loan_instalment")
    assert (entry["direction"], entry["amount"], entry["party_name"], entry["doc_number"]) == ("OUT", first["total"], "HDFC Bank", "LN-0001 EMI 1/12")
    # It leaves the lender out of the party ledgers, and the bank is down by the whole EMI.
    assert [p for p in tenant.get("/api/ledger/parties").json()["parties"] if p["party"] == "HDFC Bank"] == []
    # Paid once, it cannot be paid again; and only in full.
    assert pay(tenant, first, acct).status_code == 409
    second = loan["schedule"][1]
    part = pay(tenant, second, acct, amount=second["total"] - 1)
    assert part.status_code == 400 and "paid in full" in part.json()["detail"]
    assert pay(tenant, second, acct, amount=second["total"] + 1).status_code == 400


def test_voiding_the_payment_puts_the_instalment_back_to_owing(tenant):
    acct = bank(tenant)
    loan = made(tenant, acct)
    first = loan["schedule"][0]
    entry = pay(tenant, first, acct).json()["entry"]
    assert tenant.post("/api/money/entries/%d/void" % entry["id"], json={"reason": "Wrong account"}).status_code == 200
    after = get(tenant, loan)
    assert after["schedule"][0]["status"] == "DUE" and after["schedule"][0]["paid_on"] == "" and after["outstanding"] == P and after["paid"] == 0
    assert pay(tenant, first, acct).status_code == 200                                       # and it can be paid again


def test_the_instalments_voucher_prints(tenant):
    acct = bank(tenant)
    first = made(tenant, acct)["schedule"][0]
    entry = pay(tenant, first, acct).json()["entry"]
    res = tenant.get("/api/money/entries/%d/voucher.pdf" % entry["id"])
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"


def test_payments_needing_approval_are_requested_and_paid_like_any_other(tenant):
    acct = bank(tenant)
    loan = made(tenant, acct)
    first = loan["schedule"][0]
    assert tenant.put("/api/payment-requests/rules", json={"on": True, "free_below": 0, "md_above": 10_000_000}).status_code == 200
    asked = tenant.post("/api/payment-requests", json={"doc_type": "loan_instalment", "doc_id": first["id"], "amount": first["total"], "account_id": acct})
    assert asked.status_code == 200, asked.text
    req = asked.json()["request"]
    assert req["doc_number"] == "LN-0001 EMI 1/12" and req["party_name"] == "HDFC Bank" and req["amount"] == first["total"]
    assert tenant.post("/api/payment-requests/%d/decide" % req["id"], json={"decision": "approve"}).status_code == 200
    paid = tenant.post("/api/payment-requests/%d/pay" % req["id"], json={"mode": "Bank transfer", "reference": "UTR9"})
    assert paid.status_code == 200, paid.text
    assert get(tenant, loan)["schedule"][0]["status"] == "PAID"
    # An instalment paid, or already asked for, is not asked for twice.
    assert tenant.post("/api/payment-requests", json={"doc_type": "loan_instalment", "doc_id": first["id"], "amount": first["total"]}).status_code == 400
    second = loan["schedule"][1]
    assert tenant.post("/api/payment-requests", json={"doc_type": "loan_instalment", "doc_id": second["id"], "amount": second["total"]}).status_code == 200
    assert tenant.post("/api/payment-requests", json={"doc_type": "loan_instalment", "doc_id": second["id"], "amount": second["total"]}).status_code == 400


# --- the books -------------------------------------------------------------------------------------------------------------------

def test_tally_gets_the_money_received_and_each_emi_split_into_principal_and_interest(tenant):
    acct = bank(tenant)
    loan = made(tenant, acct)
    first = loan["schedule"][0]
    entry = pay(tenant, first, acct).json()["entry"]
    got = {v["number"]: {l["ledger"]: (l["debit"], l["credit"]) for l in v["lines"]} for v in vouchers(tenant)}
    received = next(v for v in vouchers(tenant) if v["type"] == "Receipt" and "Loan received" in v["narration"])
    assert {l["ledger"]: (l["debit"], l["credit"]) for l in received["lines"]} == {"HDFC current": (P, 0), "Loan - HDFC Bank - Excavator": (0, P)}
    # The EMI: principal to the loan ledger, the rest to interest, the whole of it out of the bank - one payment, three lines.
    assert got[entry["number"]] == {"Loan - HDFC Bank - Excavator": (first["principal"], 0), "Interest on loans": (first["interest"], 0),
                                    "HDFC current": (0, first["total"])}
    voucher = next(v for v in vouchers(tenant) if v["number"] == entry["number"])
    assert voucher["type"] == "Payment" and "EMI LN-0001 EMI 1/12" in voucher["narration"]
    # The masters put the loan under Secured Loans and the interest among the indirect expenses.
    root = ET.fromstring(tenant.get("/api/tally/masters.xml?date_from=2020-01-01&date_to=2030-12-31").content)
    groups = {l.get("NAME"): l.findtext("PARENT") for l in root.iter("LEDGER")}
    assert groups["Loan - HDFC Bank - Excavator"] == "Secured Loans" and groups["Interest on loans"] == "Indirect Expenses"
    # An unsecured one goes under its own group.
    other = made(tenant, acct, lender="Director Rao", name="Bridge", kind="unsecured", principal=500_000)
    pay(tenant, other["schedule"][0], acct)
    root = ET.fromstring(tenant.get("/api/tally/masters.xml?date_from=2020-01-01&date_to=2030-12-31").content)
    assert {l.get("NAME"): l.findtext("PARENT") for l in root.iter("LEDGER")}["Loan - Director Rao - Bridge"] == "Unsecured Loans"


def test_the_trial_balance_balances_with_loans_and_shows_the_loan_ledger(tenant):
    acct = bank(tenant)
    loan = made(tenant, acct)
    pay(tenant, loan["schedule"][0], acct)
    running(tenant)
    tb = tenant.get("/api/reports/trial-balance?date_from=2020-01-01&date_to=2030-12-31").json()
    rows = {r["ledger"]: r for r in tb["ledgers"]}
    first = loan["schedule"][0]
    assert tb["balanced"] is True and tb["warnings"] == []
    assert rows["Loan - HDFC Bank - Excavator"]["closing_cr"] == pytest.approx(P - first["principal"], abs=0.01)
    assert rows["Interest on loans"]["closing_dr"] == first["interest"]
    assert rows["Loan - SBI - Term loan"]["closing_cr"] == 800_000


def test_the_interest_is_an_expense_and_the_principal_is_not(tenant):
    acct = bank(tenant)
    loan = made(tenant, acct)
    before = tenant.get("/api/reports/profit-loss").json()
    first = loan["schedule"][0]
    pay(tenant, first, acct)
    after = tenant.get("/api/reports/profit-loss").json()
    assert after["expenses_by_source"]["loan_interest"] == first["interest"]
    assert round(after["total_expenses"] - before["total_expenses"], 2) == first["interest"]            # not the whole EMI
    assert after["total_revenue"] == before["total_revenue"]


def test_the_balance_sheet_owes_what_is_left_of_the_principal(tenant):
    acct = bank(tenant)
    sheet = lambda: tenant.get("/api/reports/balance-sheet").json()
    base = sheet()["liabilities"]["loans"]
    loan = made(tenant, acct)
    assert sheet()["liabilities"]["loans"] - base == P
    assets_before = sheet()["assets"]["bank_and_cash"]
    first = loan["schedule"][0]
    entry = pay(tenant, first, acct).json()["entry"]
    assert round(sheet()["liabilities"]["loans"] - base, 2) == pytest.approx(P - first["principal"], abs=0.01)
    assert round(assets_before - sheet()["assets"]["bank_and_cash"], 2) == first["total"]               # the bank is down by the whole EMI
    tenant.post("/api/money/entries/%d/void" % entry["id"], json={"reason": "x"})
    assert sheet()["liabilities"]["loans"] - base == P


def test_interest_is_a_head_a_voucher_may_use_too(tenant):
    res = tenant.post("/api/money/entries", json={"doc_type": "expense", "head": "Interest on loans", "party_name": "Overdraft, ICICI", "amount": 1500, "mode": "Cash"})
    assert res.status_code == 200, res.text
    assert "Interest on loans" in tenant.get("/api/money/heads").json()["expense"]


# --- what is due -----------------------------------------------------------------------------------------------------------------

def _items(loan_id, today):
    with SessionLocal() as db:
        client = db.get(models.DBClient, db.get(DBLoan, loan_id).client_id)
        return {i["kind"]: i for i in accounts_items(db, client, today=today)}


def test_emi_due_this_week_is_on_the_accounts_list_until_it_is_paid(tenant):
    acct = bank(tenant)
    loan = made(tenant, acct, first_due=(TODAY + timedelta(days=3)).isoformat())
    got = _items(loan["id"], TODAY)
    item = got["emi_due_week"]
    assert item["title"] == "EMI due this week" and item["count"] == 1 and item["view"] == "loans-view" and item["severity"] == "action"
    assert item["value"] == loan["schedule"][0]["total"] and "HDFC Bank - Excavator" in item["detail"]
    assert "emi_overdue" not in got
    assert "emi_due_week" not in _items(loan["id"], TODAY - timedelta(days=10))                        # not yet within the week
    pay(tenant, loan["schedule"][0], acct)
    assert "emi_due_week" not in _items(loan["id"], TODAY)                                             # paid: no longer waiting
    # And it reaches the dashboard's list.
    other = made(tenant, acct, lender="ICICI", name="Truck", first_due=(TODAY + timedelta(days=2)).isoformat())
    kinds = {i["kind"] for i in (tenant.get("/api/attention").json()["items"])}
    assert "emi_due_week" in kinds and other["id"]


def test_an_emi_past_its_day_is_overdue_and_says_how_late(tenant):
    loan = running(tenant, first_due=(TODAY - timedelta(days=12)).isoformat(), taken_on=(TODAY - timedelta(days=40)).isoformat())
    got = _items(loan["id"], TODAY)
    item = got["emi_overdue"]
    assert item["severity"] == "wrong" and item["count"] >= 1 and "12 days late" in item["detail"] and item["view"] == "loans-view"


# --- changing and taking away -----------------------------------------------------------------------------------------------------

def test_an_instalment_is_put_right_before_it_is_paid_and_not_after(tenant):
    acct = bank(tenant)
    loan = made(tenant, acct)
    first = loan["schedule"][0]
    url = "/api/loans/%d/instalments/%d" % (loan["id"], first["id"])
    res = tenant.put(url, json={"principal": 95000, "interest": 9400, "due_on": (NEXT_MONTH + timedelta(days=2)).isoformat()})
    assert res.status_code == 200, res.text
    fixed = res.json()["instalment"]
    assert (fixed["principal"], fixed["interest"], fixed["total"]) == (95000, 9400, 104400)
    assert fixed["due_on"] == (NEXT_MONTH + timedelta(days=2)).isoformat()
    assert pay(tenant, fixed, acct).json()["entry"]["amount"] == 104400                                  # what is paid is what was corrected
    assert tenant.put(url, json={"interest": 1}).status_code == 409                                      # a paid one is never rewritten
    second = "/api/loans/%d/instalments/%d" % (loan["id"], loan["schedule"][1]["id"])
    assert tenant.put(second, json={"principal": 0, "interest": 0}).status_code == 400
    assert tenant.put(second, json={"principal": -5}).status_code == 400
    assert tenant.put(second, json={"due_on": "soon"}).status_code == 400
    assert tenant.put("/api/loans/%d/instalments/%d" % (loan["id"], 999999), json={"interest": 1}).status_code == 404


def test_only_the_note_of_a_loan_changes(tenant):
    loan = made(tenant)
    res = tenant.put("/api/loans/%d" % loan["id"], json={"note": "Renewed in March", "principal": 1, "lender": "Someone else"})
    assert res.status_code == 200 and res.json()["loan"]["note"] == "Renewed in March"
    assert res.json()["loan"]["principal"] == P and res.json()["loan"]["lender"] == "HDFC Bank"


def test_a_loan_is_taken_away_only_while_the_books_hold_nothing_against_it(tenant):
    acct = bank(tenant)
    loan = made(tenant, acct)
    held = tenant.delete("/api/loans/%d" % loan["id"])
    assert held.status_code == 409 and "Void that entry first" in held.json()["detail"]                 # the money received is on the books
    entry = next(e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "loan_disbursal")
    pay(tenant, loan["schedule"][0], acct)
    assert tenant.post("/api/money/entries/%d/void" % entry["id"], json={"reason": "Entered in error"}).status_code == 200
    assert tenant.delete("/api/loans/%d" % loan["id"]).status_code == 409                                # an instalment is still paid on it
    paid = next(e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "loan_instalment" and not e["voided"])
    tenant.post("/api/money/entries/%d/void" % paid["id"], json={"reason": "Entered in error"})
    assert tenant.delete("/api/loans/%d" % loan["id"]).status_code == 200
    assert tenant.get("/api/loans").json()["loans"] == [] and tenant.get("/api/loans/%d" % loan["id"]).status_code == 404
    assert tenant.delete("/api/loans/%d" % loan["id"]).status_code == 404


def test_the_list_says_what_is_owed_and_what_is_coming(tenant):
    acct = bank(tenant)
    made(tenant, acct, first_due=(TODAY + timedelta(days=3)).isoformat())
    running(tenant)
    s = tenant.get("/api/loans").json()["summary"]
    assert s["active"] == 2 and s["outstanding"] == P + 800_000 and s["due_week"] >= 1 and s["emi_a_month"] > 0
    assert s["interest_to_come"] > 0 and s["interest_paid"] == 0 and s["next_due"] != ""


def test_only_accounts_may_enter_them_and_only_those_who_see_the_books_may_read(tenant, portal):
    made(tenant)
    e = make_employee(tenant, password="Crew1234", permission_role="staff", emergency_contact="Asha", emergency_phone="9999999999")
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    assert portal.post("/api/employee/auth/login", json={"email": e["email"], "password": "Crew1234"}).status_code == 200
    assert portal.post("/api/loans", json={"lender": "X", "principal": 1, "months": 1, "annual_rate": 0, "taken_on": TODAY.isoformat(), "first_due": NEXT_MONTH.isoformat(), "existing": True}).status_code in (401, 403)
    assert portal.get("/api/loans").status_code in (401, 403)
    assert portal.delete("/api/loans/1").status_code in (401, 403)
