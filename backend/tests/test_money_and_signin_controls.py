"""Three holes closed: a colleague of the Master's treated as the Master for payment approval, the Master locked out by
anybody who knew their email, and the bank reconciliation losing track of a voided transfer's other leg and of genuinely
repeated statement lines. (An approved payment paid to someone else is closed on its own branch, with its tests.)"""
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from app import models
from app.core import login_guard
from test_bank_reco import day, dmy, statement

PASSWORD = "Passw0rdTest"


@pytest.fixture(autouse=True)
def _calm():
    main.rate_limiter._hits.clear()
    login_guard.failures.reset()
    yield
    login_guard.failures.reset()


# --- 2. a colleague is not the Master ---------------------------------------------------------------------------------------

def _colleague(tenant):
    email = "mate-%s@example.com" % uuid.uuid4().hex[:8]
    assert tenant.post("/api/team/invite", json={"email": email, "role": "admin", "name": "Colleague", "password": "Colleague123"}).status_code == 200
    c = TestClient(main.app)
    c.__enter__()
    assert c.post("/api/client/login", json={"email": email, "password": "Colleague123"}).status_code == 200
    return c


def test_a_colleague_waits_for_approval_and_cannot_turn_it_off(tenant):
    assert tenant.put("/api/payment-requests/rules", json={"on": True, "free_below": 1000, "md_above": 100000}).status_code == 200
    mate = _colleague(tenant)
    try:
        assert mate.get("/api/payment-requests/rules").json()["master"] is False
        assert mate.put("/api/payment-requests/rules", json={"on": False}).status_code == 403
        res = mate.post("/api/money/entries", json={"doc_type": "on_account", "direction": "OUT", "party_name": "Sai Steel Fixers", "amount": 25000})
        assert res.status_code == 409 and "approv" in res.json()["detail"]
        # Their own request is approved by somebody else - the Master, here.
        r = mate.post("/api/payment-requests", json={"doc_type": "on_account", "party_name": "Sai Steel Fixers", "amount": 25000}).json()["request"]
        assert mate.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).status_code == 403
        assert tenant.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).status_code == 200
    finally:
        mate.__exit__(None, None, None)
    assert tenant.get("/api/payment-requests/rules").json()["on"] is True      # still on: nobody but the Master turns it off


# --- 3. a lock that keeps the guesser out, not the Master -------------------------------------------------------------------

def test_wrong_passwords_from_one_address_do_not_lock_the_master_out_elsewhere(account, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    c, email = account["client"], account["email"]
    at = lambda ip, password: c.post("/api/client/login", json={"email": email, "password": password}, headers={"X-Forwarded-For": ip})
    for _ in range(10):
        assert at("203.0.113.9", "wrong").status_code == 401
        main.rate_limiter._hits.clear()
    # The Master is never locked out, from the guesser's address or any other: what stands in front of the account is
    # the CAPTCHA and the limit on how fast one address may try (test_login_guard.py).
    assert at("203.0.113.9", PASSWORD).status_code == 200
    assert at("198.51.100.20", PASSWORD).status_code == 200


def test_a_new_password_through_forgot_password_clears_what_was_counted(account):
    from app.core import login_guard
    c, email = account["client"], account["email"]
    for _ in range(10):
        c.post("/api/client/login", json={"email": email, "password": "wrong"})
        main.rate_limiter._hits.clear()
    assert login_guard.failures.count("acct:" + email.lower()) == 10                 # counted, though never locked
    assert c.post("/api/client/login", json={"email": email, "password": PASSWORD}).status_code == 200
    raw = uuid.uuid4().hex
    with main.SessionLocal() as db:
        owner = db.query(models.DBClient).filter(models.DBClient.email == email).first()
        db.add(models.DBPasswordReset(user_type="client", client_id=owner.id, token_hash=main.hash_reset_token(raw),
                                      expires_at=(datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()
    assert c.post("/api/client/reset-password", json={"token": raw, "password": "NewPassw0rd!x"}).status_code == 200
    assert login_guard.failures.count("acct:" + email.lower()) == 0                  # the reset wiped it
    assert c.post("/api/client/login", json={"email": email, "password": "NewPassw0rd!x"}).status_code == 200


# --- 4. the reconciliation ----------------------------------------------------------------------------------------------------

def test_voiding_a_transfer_reopens_both_banks_statement_lines(tenant):
    a = tenant.post("/api/bank-accounts", json={"name": "HDFC current", "kind": "Bank", "opening_balance": 100000, "opening_date": day(40)}).json()
    b = tenant.post("/api/bank-accounts", json={"name": "SBI current", "kind": "Bank", "opening_balance": 0, "opening_date": day(40)}).json()
    res = tenant.post("/api/money/transfer", json={"from_account_id": a["id"], "to_account_id": b["id"], "amount": 30000, "paid_on": day(5)})
    assert res.status_code == 200, res.text
    out = res.json()["entry"]
    assert statement(tenant, a, [[dmy(day(5)), "TRF TO SBI", "", "", "30,000.00", "", "70,000.00"]])["matched"] == 1
    assert statement(tenant, b, [[dmy(day(5)), "TRF FROM HDFC", "", "", "", "30,000.00", "30,000.00"]])["matched"] == 1
    assert tenant.post("/api/money/entries/%d/void" % out["id"], json={"reason": "wrong accounts"}).status_code == 200
    for acc in (a, b):                                 # both legs voided, so both banks' lines are open again
        got = tenant.get("/api/bank-reco/%d" % acc["id"]).json()
        assert got["counts"]["matched"] == 0 and [l["status"] for l in got["lines"]] == ["UNMATCHED"], got["counts"]


def test_two_genuine_identical_lines_are_both_kept_and_a_second_import_adds_nothing(tenant):
    bank = tenant.post("/api/bank-accounts", json={"name": "ICICI current", "kind": "Bank", "opening_balance": 10000, "opening_date": day(40)}).json()
    on = day(3).split("-")
    row = ["%s/%s/%s" % (on[2], on[1], on[0]), "SMS CHARGES", "", "", 500, "", ""]          # no running balance on this statement
    first = statement(tenant, bank, [row, row])
    assert len(tenant.get("/api/bank-reco/%d" % bank["id"]).json()["lines"]) == 2, first
    statement(tenant, bank, [row, row], name="again.xlsx")                                  # the same statement, downloaded again
    assert len(tenant.get("/api/bank-reco/%d" % bank["id"]).json()["lines"]) == 2
    statement(tenant, bank, [row, row, row], name="later.xlsx")                             # a third charge since
    assert len(tenant.get("/api/bank-reco/%d" % bank["id"]).json()["lines"]) == 3
