"""Alerts: a bill waiting on a signature, money in, a gang to pay - on the
bell for the office, and by email or WhatsApp to whoever is named for it."""
from datetime import datetime

import pytest

import database
import main
from test_measurement_and_ra_bills import placed_order, book, measure


@pytest.fixture
def sent(monkeypatch):
    """What would have gone out, without anything going out."""
    out = {"email": [], "whatsapp": []}
    monkeypatch.setattr(main, "NOTIFY_SYNC", True)
    monkeypatch.setattr(main, "send_email_background",
                        lambda to, subject, body, frm, **k: out["email"].append((to, subject)) or (True, ""))
    monkeypatch.setattr(main, "_send_whatsapp_for",
                        lambda pid, tok, number, text: out["whatsapp"].append((number, text)) or True)
    return out


def certified_bill(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 100)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    return b


def kinds(tenant):
    return [a["kind"] for a in tenant.get("/api/alerts").json()["alerts"]]


def test_a_bill_announces_itself_on_the_bell(tenant, sent):
    certified_bill(tenant)
    feed = tenant.get("/api/alerts").json()
    assert "ra_bill_submitted" in [a["kind"] for a in feed["alerts"]]
    top = feed["alerts"][0]
    assert top["kind"] == "ra_bill_certified" and "to receive" in top["body"]
    assert feed["unread"] == 2


def test_marking_read(tenant, sent):
    certified_bill(tenant)
    ids = [a["id"] for a in tenant.get("/api/alerts").json()["alerts"]]
    tenant.post("/api/alerts/read", json={"ids": ids[:1]})
    assert tenant.get("/api/alerts").json()["unread"] == 1
    tenant.post("/api/alerts/read", json={"all": True})
    assert tenant.get("/api/alerts").json()["unread"] == 0


def test_money_in_is_announced_and_emailed_to_whoever_is_named(tenant, sent):
    b = certified_bill(tenant)
    tenant.put("/api/alerts/settings", json={"emails": ["accounts@yprojects.co.in"]})
    tenant.post("/api/money/entries", json={"doc_type": "ra_bill", "doc_id": b["id"], "amount": 5000,
                                            "mode": "NEFT", "reference": "UTR1"})
    assert kinds(tenant)[0] == "money_in"
    assert sent["email"] and sent["email"][-1][0] == "accounts@yprojects.co.in"
    assert "received" in sent["email"][-1][1]


def test_whatsapp_only_once_the_business_number_is_set_up(tenant, sent):
    tenant.put("/api/alerts/settings", json={
        "whatsapp": ["98480 12345"], "channels": {"ra_bill_certified": ["whatsapp"]}})
    certified_bill(tenant)
    assert sent["whatsapp"] == [], "no Business number yet, nothing is sent"
    tenant.put("/api/alerts/settings", json={"wa_phone_id": "1234567890", "wa_token": "EAAG-test"})
    certified_bill(tenant)
    assert sent["whatsapp"] and sent["whatsapp"][-1][0] == "919848012345"


def test_the_settings_check_what_they_are_given(tenant):
    assert tenant.put("/api/alerts/settings", json={"emails": ["not-an-email"]}).status_code == 400
    assert tenant.put("/api/alerts/settings", json={"whatsapp": ["123"]}).status_code == 400
    s = tenant.put("/api/alerts/settings", json={"channels": {"money_in": ["email", "fax"], "bogus": ["email"]}}).json()
    assert s["channels"]["money_in"] == ["email"] and "bogus" not in s["channels"]
    assert s["whatsapp_ready"] is False


def test_the_morning_digest_waits_for_seven_and_goes_once(tenant, sent):
    wo = placed_order(tenant, qty=10, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 20)   # built past the order
    assert main.digest_key(datetime(2026, 9, 26, 6, 30)) != main.digest_key(datetime(2026, 9, 26, 8))
    s = database.SessionLocal()
    try:
        assert main.job_morning_digest(s, datetime(2026, 9, 26, 6, 30)) == "too early"
        main.job_morning_digest(s, datetime(2026, 9, 26, 8, 0))
    finally:
        s.close()
    digest = [a for a in tenant.get("/api/alerts").json()["alerts"] if a["kind"] == "daily_digest"]
    assert digest and "Built past the order" in digest[0]["body"]


def test_a_test_message_says_where_it_went(tenant, sent):
    out = tenant.post("/api/alerts/test").json()
    assert "bell" in out["message"]
    tenant.put("/api/alerts/settings", json={"emails": ["site@yprojects.co.in"]})
    out = tenant.post("/api/alerts/test").json()
    assert out["sent_to"] == "site@yprojects.co.in"


def test_another_company_sees_none_of_it(tenant, second_tenant, sent):
    certified_bill(tenant)
    assert second_tenant.get("/api/alerts").json()["alerts"] == []
