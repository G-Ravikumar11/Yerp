"""The trial balance and the day book: accounts checks the books here before sending them to Tally.

Both are read from the same balanced vouchers the Tally export is made of, so the trial balance agrees with the export to the
rupee, a voucher voided before it was exported is in neither, and a staff member with no right to the books reads neither.
"""
import io
from datetime import date

from openpyxl import load_workbook

from conftest import make_employee
from test_tally import period

TODAY = date.today().isoformat()
ALL = "date_from=2020-01-01&date_to=2030-12-31"


def tb(tenant, query=ALL):
    res = tenant.get("/api/reports/trial-balance?" + query)
    assert res.status_code == 200, res.text
    return res.json()


def ledger(report, name):
    return next(r for r in report["ledgers"] if r["ledger"] == name)


def sheet_cells(res):
    assert res.status_code == 200, res.text
    ws = load_workbook(io.BytesIO(res.content)).active
    return [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]


def test_the_trial_balance_balances_and_agrees_with_the_tally_export(tenant):
    period(tenant)
    report = tb(tenant)
    t = report["totals"]
    assert report["balanced"] is True and report["difference"] == 0
    assert t["debit"] == t["credit"] > 0 and t["closing_dr"] == t["closing_cr"]
    assert report["vouchers"] > 0 and report["warnings"] == []

    # The same ledgers and the same amounts as the vouchers the export carries, line by line.
    vouchers = tenant.get("/api/tally/vouchers?" + ALL).json()["vouchers"]
    debits, credits = {}, {}
    for v in vouchers:
        for l in v["lines"]:
            debits[l["ledger"]] = debits.get(l["ledger"], 0) + l["debit"]
            credits[l["ledger"]] = credits.get(l["ledger"], 0) + l["credit"]
    assert {r["ledger"] for r in report["ledgers"]} == set(debits) | set(credits)
    for r in report["ledgers"]:
        assert round(r["debit"], 2) == round(debits.get(r["ledger"], 0), 2)
        assert round(r["credit"], 2) == round(credits.get(r["ledger"], 0), 2)
        # With no opening, a ledger closes where its debits less its credits leave it - on one side only.
        assert r["closing_dr"] == max(0, round(r["debit"] - r["credit"], 2)) and r["closing_cr"] == max(0, round(r["credit"] - r["debit"], 2))
        assert not (r["closing_dr"] and r["closing_cr"])


def test_each_ledger_is_under_its_tally_group_and_the_groups_add_up(tenant):
    period(tenant)
    report = tb(tenant)
    assert ledger(report, "Diesel & fuel")["group"] == "Direct Expenses"
    assert ledger(report, "Sales - Works Contract")["group"] == "Sales Accounts"
    assert ledger(report, "HDFC current")["group"] == "Bank Accounts"
    by = {g["group"]: g for g in report["groups"]}
    assert by["Bank Accounts"]["ledgers"] == 1
    assert round(sum(g["debit"] for g in report["groups"]), 2) == report["totals"]["debit"]
    assert round(sum(g["closing_dr"] for g in report["groups"]), 2) == report["totals"]["closing_dr"]


def test_what_was_booked_before_the_period_is_the_opening(tenant):
    period(tenant)
    everything = tb(tenant)
    # Every voucher in the fixture is dated today, so a period that starts tomorrow has all of it as opening.
    later = tb(tenant, "date_from=2999-01-01&date_to=2999-12-31")
    assert later["vouchers"] == 0 and later["totals"]["debit"] == 0 and later["totals"]["credit"] == 0
    assert later["totals"]["opening_dr"] == everything["totals"]["closing_dr"] and later["balanced"] is True
    for r in everything["ledgers"]:
        l = ledger(later, r["ledger"])
        assert (l["opening_dr"], l["opening_cr"]) == (r["closing_dr"], r["closing_cr"])
        assert (l["closing_dr"], l["closing_cr"]) == (r["closing_dr"], r["closing_cr"])
    # And a period that ends before any of it has nothing.
    earlier = tb(tenant, "date_from=2000-01-01&date_to=2000-12-31")
    assert earlier["ledgers"] == [] and earlier["totals"]["debit"] == 0 and earlier["balanced"] is True


def test_a_voided_entry_is_in_neither_report(tenant):
    period(tenant)
    assert "Rent" not in {r["ledger"] for r in tb(tenant)["ledgers"]}          # the fixture's 999 rent voucher was voided
    assert all("Rent" not in " ".join(l["ledger"] for l in v["lines"]) for v in tenant.get("/api/reports/day-book?date=" + TODAY).json()["vouchers"])


def test_the_day_book_lists_the_days_vouchers_with_their_lines(tenant):
    period(tenant)
    day = tenant.get("/api/reports/day-book?date=" + TODAY).json()
    s = day["summary"]
    assert s["count"] == len(day["vouchers"]) > 0 and s["debit"] == s["credit"] > 0
    assert {t["type"] for t in s["types"]} >= {"Payment", "Receipt", "Contra"}
    assert sum(t["count"] for t in s["types"]) == s["count"]
    for v in day["vouchers"]:
        assert v["date"] == TODAY
        assert sum(l["debit"] for l in v["lines"]) == sum(l["credit"] for l in v["lines"])
    diesel = next(v for v in day["vouchers"] if "HP pump" in v["narration"])
    assert {l["ledger"] for l in diesel["lines"]} == {"Diesel & fuel", "Site cash - Vizag"}
    # A day with nothing booked says so, and defaults to today when no day is given.
    assert tenant.get("/api/reports/day-book?date=2000-01-01").json()["vouchers"] == []
    assert tenant.get("/api/reports/day-book").json()["summary"]["count"] == s["count"]
    # A run of days reads the same as the one day when everything is on one.
    ranged = tenant.get("/api/reports/day-book?date_from=2000-01-01&date_to=%s" % TODAY).json()
    assert ranged["summary"]["count"] == s["count"]


def test_a_voucher_that_does_not_balance_is_reported_not_swallowed(tenant, monkeypatch):
    from app.services import tally
    real = tally.Books._money

    def lopsided(self):
        real(self)
        self.add("Payment", "BAD-1", TODAY, "Half a voucher", [("Diesel & fuel", 100), ("Cash", -90)], "yerp-test")

    monkeypatch.setattr(tally.Books, "_money", lopsided)
    period(tenant)
    report = tb(tenant)
    assert any("BAD-1" in w and "did not balance" in w for w in report["warnings"])
    assert report["balanced"] is True                       # it was left out, so what is shown still agrees with itself
    day = tenant.get("/api/reports/day-book?date=" + TODAY).json()
    assert any("BAD-1" in w for w in day["warnings"]) and all(v["number"] != "BAD-1" for v in day["vouchers"])


def test_dates_must_be_real_and_in_order(tenant):
    assert tenant.get("/api/reports/trial-balance?date_from=yesterday").status_code == 400
    assert tenant.get("/api/reports/trial-balance?date_from=2026-05-01&date_to=2026-04-01").status_code == 400
    assert tenant.get("/api/reports/day-book?date=31-10-2026").status_code == 400
    assert tenant.get("/api/reports/trial-balance").status_code == 200       # no period: from the first voucher to the last


def test_an_empty_company_has_an_empty_balanced_book(tenant):
    report = tb(tenant, "")
    assert report["ledgers"] == [] and report["balanced"] is True and report["totals"]["debit"] == 0
    assert tenant.get("/api/reports/day-book").json()["vouchers"] == []


def test_the_workbooks(tenant):
    period(tenant)
    cells = sheet_cells(tenant.get("/api/reports/trial-balance.xlsx?" + ALL))
    assert "TRIAL BALANCE" in cells and "Opening Dr" in cells and "Diesel & fuel" in cells and "Balanced" in cells
    cells = sheet_cells(tenant.get("/api/reports/day-book.xlsx?date=" + TODAY))
    assert "DAY BOOK" in cells and "Diesel & fuel" in cells and "Payment" in cells


def test_staff_without_the_right_to_the_books_cannot_read_them(tenant, portal):
    period(tenant)
    e = make_employee(tenant, password="Crew1234", permission_role="staff", emergency_contact="Asha", emergency_phone="9999999999")
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    assert portal.post("/api/employee/auth/login", json={"email": e["email"], "password": "Crew1234"}).status_code == 200
    for url in ("/api/reports/trial-balance", "/api/reports/trial-balance.xlsx", "/api/reports/day-book", "/api/reports/day-book.xlsx"):
        assert portal.get(url).status_code in (401, 403), url
