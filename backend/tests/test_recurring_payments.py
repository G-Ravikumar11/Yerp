"""Recurring payments: rent, internet, hire and insurance raised for approval every month without being typed in.

Each template carries its own next due date; a daily job raises an expense payment request for whatever has fallen due
(catching up after downtime, never twice for one month), and the request is approved and paid like any other.
"""
from datetime import date, datetime, timedelta

import pytest
from conftest import make_employee

from app import models
from app.core.scheduler import run_due_jobs
from app.db import SessionLocal
from app.models.recurring_payments import DBRecurringPayment, DBRecurringPaymentRun
from app.services.recurring_payments import first_due, following, occurrence

TODAY = date.today()


@pytest.fixture(autouse=True)
def _fresh_claims():
    """A day's job is claimed once for everybody, so an earlier test's run would otherwise stand in the way of this one's."""
    with SessionLocal() as db:
        db.query(models.DBJobRun).delete()
        db.commit()


def add(tenant, **kw):
    # A day that is not today, so nothing is raised the moment it is set up unless a test asks for that.
    body = {"payee": "Sri Lakshmi Estates", "head": "Rent", "amount": 25000, "day_of_month": 5 if TODAY.day != 5 else 6, **kw}
    return tenant.post("/api/recurring-payments", json=body)


def made(tenant, **kw):
    res = add(tenant, **kw)
    assert res.status_code == 200, res.text
    return res.json()["payment"]


def listing(tenant):
    return tenant.get("/api/recurring-payments").json()


def requests_of(tenant):
    return tenant.get("/api/payment-requests").json()["requests"]


def set_row(rid, **fields):
    with SessionLocal() as db:
        t = db.get(DBRecurringPayment, rid)
        for k, v in fields.items():
            setattr(t, k, v)
        db.commit()


def job(on=None):
    return run_due_jobs(now=datetime.combine(on or TODAY, datetime.min.time()).replace(hour=7), only="recurring_payments")[0]


# --- the dates ---------------------------------------------------------------------------------------------------------------

def test_a_day_that_a_short_month_does_not_have_falls_on_its_last():
    assert occurrence(2026, 2, 31) == date(2026, 2, 28)
    assert occurrence(2028, 2, 30) == date(2028, 2, 29)                      # a leap year
    assert occurrence(2026, 4, 31) == date(2026, 4, 30)
    # The month after is built from the day asked for, so the 31st stays the 31st after a February that had to use the 28th.
    assert following(date(2026, 2, 28), 31) == date(2026, 3, 31)
    assert following(date(2026, 12, 15), 15) == date(2027, 1, 15)


def test_the_first_due_date_is_never_before_the_day_it_is_asked_from():
    assert first_due(16, date(2026, 11, 16)) == date(2026, 11, 16)           # today counts
    assert first_due(5, date(2026, 11, 16)) == date(2026, 12, 5)             # this month's has gone: next month's
    assert first_due(5, date(2026, 12, 20)) == date(2027, 1, 5)


# --- setting one up --------------------------------------------------------------------------------------------------------

def test_a_payment_is_set_up_and_waits_for_its_day(tenant):
    p = made(tenant, payee="Airtel Business", head="Telephone & internet", amount=4200, note="Leased line, head office")
    assert p["status"] == "Active" and p["raised_count"] == 0 and p["last_request"] is None
    assert date.fromisoformat(p["next_due"]) >= TODAY and date.fromisoformat(p["next_due"]).day == p["day_of_month"]
    assert requests_of(tenant) == []                                         # nothing raised before its day
    s = listing(tenant)["summary"]
    assert s["active"] == 1 and s["monthly"] == 4200 and s["next_due"] == p["next_due"] and s["failing"] == 0


def test_one_due_today_is_raised_at_once_not_a_day_late(tenant):
    res = add(tenant, day_of_month=TODAY.day, note="Site office, Vizag")
    assert res.status_code == 200, res.text
    p = res.json()["payment"]
    assert "raised now" in res.json()["message"] and p["raised_count"] == 1 and p["last_raised_on"] == TODAY.isoformat()
    [r] = requests_of(tenant)
    assert (r["doc_type"], r["head"], r["party_name"], r["amount"], r["status"]) == ("expense", "Rent", "Sri Lakshmi Estates", 25000, "PENDING")
    assert "Recurring" in r["note"] and "Site office, Vizag" in r["note"] and r["requested_by_name"] == "Recurring payment"
    assert p["last_request"]["number"] == r["number"]
    # And it has moved on to next month.
    assert date.fromisoformat(p["next_due"]) == following(TODAY, TODAY.day)


def test_what_is_refused(tenant):
    assert add(tenant, payee="  ").status_code == 400
    assert add(tenant, head="Entertainment").status_code == 400
    assert add(tenant, amount=0).status_code == 400
    assert add(tenant, amount=-10).status_code == 400
    assert add(tenant, amount=10 ** 12).status_code == 400
    assert add(tenant, day_of_month=0).status_code == 400
    assert add(tenant, day_of_month=32).status_code == 400
    assert add(tenant, start_date="next month").status_code == 400
    assert add(tenant, end_date="whenever").status_code == 400
    assert add(tenant, start_date="2030-06-01", end_date="2030-05-01").status_code == 400          # ends before it starts
    assert add(tenant, end_date=(TODAY - timedelta(days=60)).isoformat(), start_date=(TODAY - timedelta(days=90)).isoformat()).status_code == 400   # over before it begins
    assert add(tenant, job_id=999999).status_code == 404
    assert add(tenant, account_id=999999).status_code == 404
    assert listing(tenant)["payments"] == []


def test_the_same_rent_is_not_set_up_twice(tenant):
    made(tenant)
    again = add(tenant, payee="sri lakshmi estates.", amount=30000)
    assert again.status_code == 409 and "already set up" in again.json()["detail"]
    assert add(tenant, head="Insurance").status_code == 200                      # another head is another payment
    assert add(tenant, payee="Someone Else").status_code == 200                  # another payee is another payment
    j = tenant.post("/api/jobs", json={"name": "Vizag site", "customer_name": "X"}).json()
    assert add(tenant, job_id=j.get("id") or j["job"]["id"]).status_code == 200  # the same rent on another project is another payment


# --- the daily job -----------------------------------------------------------------------------------------------------------

def test_the_job_raises_what_has_fallen_due_once_and_moves_it_on(tenant):
    p = made(tenant)
    set_row(p["id"], next_due=TODAY.isoformat())
    first = job()
    assert first["status"] == "done" and "1 request(s) raised" in first["detail"]
    [r] = requests_of(tenant)
    assert r["status"] == "PENDING" and r["amount"] == 25000 and "Recurring" in r["note"]
    after = listing(tenant)["payments"][0]
    assert after["raised_count"] == 1 and after["last_request"]["number"] == r["number"] and date.fromisoformat(after["next_due"]) > TODAY
    # The same day again claims nothing; and the run log refuses the same month even if the job were forced.
    assert job()["status"] == "already_done"
    set_row(p["id"], next_due=TODAY.isoformat())
    with SessionLocal() as db:
        assert db.query(DBRecurringPaymentRun).filter(DBRecurringPaymentRun.recurring_id == p["id"]).count() == 1
    from app.services.recurring_payments import job_recurring_payments
    with SessionLocal() as db:
        assert job_recurring_payments(db, datetime.combine(TODAY, datetime.min.time())).startswith("0 request(s)")
    assert len(requests_of(tenant)) == 1


def test_a_month_missed_while_the_app_was_down_is_raised_when_it_is_back(tenant):
    p = made(tenant, day_of_month=5)
    y, m = TODAY.year, TODAY.month - 3
    while m < 1:
        y, m = y - 1, m + 12
    set_row(p["id"], next_due=date(y, m, 5).isoformat())
    # Independently: the 5ths from three months back up to today.
    expected, (cy, cm) = 0, (y, m)
    while (cy, cm) <= (TODAY.year, TODAY.month):
        expected += date(cy, cm, 5) <= TODAY
        cy, cm = (cy + 1, 1) if cm == 12 else (cy, cm + 1)
    job()
    got = requests_of(tenant)
    assert len(got) == expected >= 3
    assert len({r["note"] for r in got}) == expected                           # each names the month it is for
    assert date.fromisoformat(listing(tenant)["payments"][0]["next_due"]) > TODAY


def test_it_stops_at_its_last_date(tenant):
    # Due today, and again next month, which is inside the 45 days; the month after is not.
    p = made(tenant, end_date=(TODAY + timedelta(days=45)).isoformat(), day_of_month=TODAY.day)
    assert len(requests_of(tenant)) == 1 and p["status"] == "Active"
    second = date.fromisoformat(p["next_due"])
    job(second)
    assert len(requests_of(tenant)) == 2
    after = listing(tenant)["payments"][0]
    assert after["status"] == "Ended" and after["next_due"] == ""              # the next one would be after the end
    # A long time later nothing more is raised.
    job(second + timedelta(days=90))
    assert len(requests_of(tenant)) == 2
    assert listing(tenant)["summary"]["ended"] == 1 and listing(tenant)["summary"]["monthly"] == 0
    # An ended one cannot be paused; and one whose last date has really passed cannot be resumed until the date is moved.
    assert tenant.post("/api/recurring-payments/%d/pause" % p["id"]).status_code == 409
    set_row(p["id"], end_date=(TODAY - timedelta(days=1)).isoformat())
    gone = tenant.post("/api/recurring-payments/%d/resume" % p["id"])
    assert gone.status_code == 409 and "nothing left to raise" in gone.json()["detail"]
    assert tenant.put("/api/recurring-payments/%d" % p["id"], json={"end_date": ""}).status_code == 200
    assert tenant.post("/api/recurring-payments/%d/resume" % p["id"]).json()["payment"]["status"] == "Active"     # no end: it carries on


def test_paused_ones_are_left_alone_and_resuming_does_not_raise_the_months_missed(tenant):
    p = made(tenant)
    set_row(p["id"], next_due=(TODAY - timedelta(days=65)).isoformat())
    paused = tenant.post("/api/recurring-payments/%d/pause" % p["id"])
    assert paused.status_code == 200 and paused.json()["payment"]["status"] == "Paused"
    job()
    assert requests_of(tenant) == []
    res = tenant.post("/api/recurring-payments/%d/resume" % p["id"])
    assert res.status_code == 200 and res.json()["payment"]["status"] == "Active"
    assert date.fromisoformat(res.json()["payment"]["next_due"]) >= TODAY
    assert requests_of(tenant) == []                                           # the two missed months are not raised


def test_one_that_cannot_be_raised_says_why_and_does_not_stop_the_rest(tenant):
    bad = made(tenant, payee="Old Landlord")
    good = made(tenant, payee="Airtel", head="Telephone & internet")
    set_row(bad["id"], next_due=TODAY.isoformat(), head="A head that no longer exists")
    set_row(good["id"], next_due=TODAY.isoformat())
    res = job()
    assert "1 request(s) raised" in res["detail"] and "1 could not be raised" in res["detail"]
    rows = {r["payee"]: r for r in listing(tenant)["payments"]}
    assert rows["Airtel"]["raised_count"] == 1 and rows["Airtel"]["last_error"] == ""
    assert rows["Old Landlord"]["raised_count"] == 0 and rows["Old Landlord"]["last_error"] and rows["Old Landlord"]["status"] == "Active"
    assert rows["Old Landlord"]["next_due"] == TODAY.isoformat()               # left for tomorrow, not lost
    assert listing(tenant)["summary"]["failing"] == 1
    assert [r["party_name"] for r in requests_of(tenant)] == ["Airtel"]


def test_the_accounts_people_are_told_what_is_waiting(tenant):
    p = made(tenant, payee="Landlord A")
    q = made(tenant, payee="Landlord B", head="Insurance", amount=9000)
    for x in (p, q):
        set_row(x["id"], next_due=TODAY.isoformat())
    job()
    with SessionLocal() as db:
        ours = [a for a in db.query(models.DBAlert).filter(models.DBAlert.kind == "approval").all() if "Landlord A" in (a.body or "")]
        assert len(ours) == 1 and "2 recurring payments waiting for approval" in ours[0].title
        assert "Landlord B" in ours[0].body and ours[0].view == "payments-view"


# --- the request it raises is a real one ---------------------------------------------------------------------------------------

def test_the_request_is_approved_and_paid_like_any_other_and_lands_on_its_project(tenant):
    j = tenant.post("/api/jobs", json={"name": "Vizag site", "customer_name": "X"}).json()
    jid = j.get("id") or j["job"]["id"]
    p = made(tenant, job_id=jid, head="Machinery hire", payee="Gulf Heavy Equipment", amount=62000, day_of_month=TODAY.day)
    assert p["project"].endswith("Vizag site")
    [r] = requests_of(tenant)
    assert r["job_id"] == jid and r["status"] == "PENDING"
    assert tenant.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).status_code == 200
    paid = tenant.post("/api/payment-requests/%d/pay" % r["id"], json={"mode": "Bank transfer"})
    assert paid.status_code == 200, paid.text
    entry = next(e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "expense")
    assert (entry["head"], entry["party_name"], entry["amount"], entry["job_id"], entry["direction"]) == ("Machinery hire", "Gulf Heavy Equipment", 62000, jid, "OUT")
    assert listing(tenant)["payments"][0]["last_request"]["status"] == "Paid"


# --- changing and removing -----------------------------------------------------------------------------------------------------

def test_a_change_applies_from_the_next_request_and_a_new_day_moves_the_date(tenant):
    p = made(tenant, day_of_month=TODAY.day)                                  # raised at once at 25,000
    res = tenant.put("/api/recurring-payments/%d" % p["id"], json={"amount": 27500, "note": "Rent revised"})
    assert res.status_code == 200 and res.json()["payment"]["amount"] == 27500
    assert [r["amount"] for r in requests_of(tenant)] == [25000]              # what was raised is not rewritten
    other = 20 if TODAY.day != 20 else 21
    moved = tenant.put("/api/recurring-payments/%d" % p["id"], json={"day_of_month": other}).json()["payment"]
    assert moved["day_of_month"] == other and date.fromisoformat(moved["next_due"]).day == other and date.fromisoformat(moved["next_due"]) >= TODAY
    assert tenant.put("/api/recurring-payments/%d" % p["id"], json={"amount": 0}).status_code == 400
    assert tenant.put("/api/recurring-payments/999999", json={"amount": 1}).status_code == 404


def test_taking_one_away_keeps_the_requests_it_raised(tenant):
    p = made(tenant, day_of_month=TODAY.day)
    assert tenant.delete("/api/recurring-payments/%d" % p["id"]).status_code == 200
    assert listing(tenant)["payments"] == []
    assert len(requests_of(tenant)) == 1
    with SessionLocal() as db:
        assert db.query(DBRecurringPaymentRun).filter(DBRecurringPaymentRun.recurring_id == p["id"]).count() == 0
    assert tenant.delete("/api/recurring-payments/%d" % p["id"]).status_code == 404


def test_only_accounts_may_set_them_up_and_only_those_who_see_the_books_may_read(tenant, portal):
    made(tenant)
    e = make_employee(tenant, password="Crew1234", permission_role="staff", emergency_contact="Asha", emergency_phone="9999999999")
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    assert portal.post("/api/employee/auth/login", json={"email": e["email"], "password": "Crew1234"}).status_code == 200
    assert portal.post("/api/recurring-payments", json={"payee": "X", "head": "Rent", "amount": 1, "day_of_month": 1}).status_code in (401, 403)
    assert portal.get("/api/recurring-payments").status_code in (401, 403)
    assert portal.delete("/api/recurring-payments/1").status_code in (401, 403)


def test_the_tax_selection_and_bank_details_are_kept_and_go_with_each_months_request(tenant):
    # Due today, so the job raises it at once.
    p = made(tenant, day_of_month=TODAY.day, start_date=TODAY.isoformat(), amount=11800, mode="Bank transfer", tax="taxable", supply="non_local",
             supply_state="29", gst_rate=18, payee_bank="State Bank of India", payee_account="30123456789", payee_ifsc="sbin0001234")
    assert (p["tax"], p["supply"], p["supply_state"], p["gst_rate"]) == ("taxable", "non_local", "29", 18.0)
    assert (p["payee_bank"], p["payee_account"], p["payee_ifsc"]) == ("State Bank of India", "30123456789", "SBIN0001234")
    job()
    req = [r for r in requests_of(tenant) if r["doc_type"] == "expense"][0]
    # The month's request carries the tax selection and where the money goes.
    assert (req["tax"], req["supply"], req["supply_state"], req["gst_rate"]) == ("taxable", "non_local", "29", 18.0)
    assert (req["payee_bank"], req["payee_account"], req["payee_ifsc"]) == ("State Bank of India", "30123456789", "SBIN0001234")


def test_non_taxable_needs_no_supply_and_a_cash_mode_keeps_no_bank_details(tenant):
    p = tenant.post("/api/recurring-payments", json={"payee": "Airtel", "head": "Telephone & internet", "amount": 4200, "day_of_month": 22, "start_date": "2026-01-01",
                                                   "mode": "Cash", "tax": "non_taxable", "supply": "local", "payee_bank": "SBI", "payee_account": "30123456789"}).json()["payment"]
    assert (p["tax"], p["supply"], p["supply_state"], p["gst_rate"]) == ("non_taxable", "", "", 0.0)
    assert (p["payee_bank"], p["payee_account"], p["payee_ifsc"]) == ("", "", "")


def test_a_taxable_payment_needs_local_or_a_state_for_non_local(tenant):
    base = {"payee": "Hire Co", "head": "Machinery hire", "amount": 5000, "day_of_month": 1, "start_date": "2026-01-01", "tax": "taxable"}
    assert tenant.post("/api/recurring-payments", json=base).status_code == 400                                   # neither local nor non local
    assert tenant.post("/api/recurring-payments", json={**base, "supply": "non_local"}).status_code == 400       # no state
    assert tenant.post("/api/recurring-payments", json={**base, "supply": "non_local", "supply_state": "29", "gst_rate": 17}).status_code == 400
    assert tenant.post("/api/recurring-payments", json={**base, "supply": "local", "gst_rate": 18}).status_code == 200
