"""Suppliers chased for their quotes: the link emailed when a supplier is invited, a reminder to those who have not
quoted as the due date nears, and the L1 summary for the buyer on the day. Nothing really goes out: the sender is
replaced."""
from datetime import date, datetime, timedelta

import pytest

import main
from _patching import patch_app
from test_comparative_statement import quote, rfq


@pytest.fixture
def sent(monkeypatch):
    out = []
    patch_app(monkeypatch, "send_email_background", lambda to, subject, body, frm, **k: out.append((to, subject, body)) or (True, "ok"))
    return out


def invite(tenant, r, name, email=""):
    res = tenant.post("/api/rfqs/%d/invites" % r["rfq"]["id"], json={"supplier_name": name, "email": email})
    assert res.status_code == 200, res.text
    return res.json()


def run(day):
    """The job, as the scheduler runs it on `day`. It runs once a day for everybody: the day's claim from an earlier test
    is cleared, as each test is its own day."""
    from app import db as database, models
    with database.SessionLocal() as db:
        db.query(models.DBJobRun).filter(models.DBJobRun.job_name == "rfq_chasers").delete()
        db.commit()
    return main.run_due_jobs(now=datetime.combine(day, datetime.min.time()).replace(hour=9), only="rfq_chasers")


def l1_alerts(r):
    from app import db as database, models
    with database.SessionLocal() as db:
        rfq_row = db.get(models.DBRfq, r["rfq"]["id"])
        return [a.title for a in db.query(models.DBAlert).filter(models.DBAlert.kind == "rfq_l1", models.DBAlert.client_id == rfq_row.client_id).all()]


def test_a_supplier_invited_with_an_email_is_sent_the_link(tenant, sent):
    r = rfq(tenant, quotes_due=(date.today() + timedelta(days=5)).isoformat())
    out = invite(tenant, r, "ACC Cement", "sales@acc.example.com")
    assert out["emailed"] is True and "emailed" in out["message"]
    to, subject, body = sent[0]
    assert to == "sales@acc.example.com" and r["rfq"]["number"] in subject and "/next/quote?token=" in body and "due by" in body
    assert out["invite"]["emailed_at"]
    # Without an email there is only the link to forward.
    assert "emailed" not in invite(tenant, r, "Local Traders")["message"]


def test_the_link_can_be_emailed_again(tenant, sent):
    r = rfq(tenant)
    inv = invite(tenant, r, "ACC Cement", "sales@acc.example.com")["invite"]
    res = tenant.post("/api/rfqs/%d/invites/%d/email" % (r["rfq"]["id"], inv["id"]))
    assert res.status_code == 200 and len(sent) == 2


def test_suppliers_who_have_not_quoted_are_reminded_two_days_before_and_on_the_day(tenant, sent):
    due = date.today() + timedelta(days=2)
    r = rfq(tenant, quotes_due=due.isoformat())
    invite(tenant, r, "ACC Cement", "sales@acc.example.com")
    invite(tenant, r, "UltraTech", "ut@example.com")
    quote(tenant, r, "UltraTech", 380, 61000)                      # this one has answered
    from app import db as database, models
    with database.SessionLocal() as db:                             # the quote typed in by the buyer marks his link answered
        inv = db.query(models.DBRfqInvite).filter(models.DBRfqInvite.supplier_name == "UltraTech").one()
        inv.submitted_at = "2026-01-01 10:00:00"
        db.commit()
    sent.clear()
    run(date.today())
    assert [s[0] for s in sent] == ["sales@acc.example.com"] and sent[0][1].startswith("Reminder:")
    sent.clear()
    run(date.today() + timedelta(days=1))                          # nothing the day between
    assert sent == []
    run(due)                                                        # and again on the day
    assert [s[0] for s in sent] == ["sales@acc.example.com"]


def test_on_the_due_date_the_buyer_gets_the_l1_summary_once(tenant, sent):
    r = rfq(tenant, quotes_due=date.today().isoformat())
    quote(tenant, r, "ACC Cement", 390, 62000)
    quote(tenant, r, "UltraTech", 380, 61000)
    run(date.today())
    [title] = l1_alerts(r)
    assert "2 of 2 quoted" in title and "L1 is UltraTech" in title and "less than L2" in title
    run(date.today() + timedelta(days=1))
    assert len(l1_alerts(r)) == 1


def test_an_enquiry_without_a_due_date_is_never_chased(tenant, sent):
    r = rfq(tenant)
    invite(tenant, r, "ACC Cement", "sales@acc.example.com")
    sent.clear()
    run(date.today())
    assert sent == []


def test_quotes_cannot_be_due_on_a_day_gone(tenant):
    res = tenant.post("/api/rfqs", json={"title": "Late", "quotes_due": (date.today() - timedelta(days=1)).isoformat(),
                                         "lines": [{"description": "Cement", "qty": 1}]})
    assert res.status_code == 400
