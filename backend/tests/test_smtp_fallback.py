"""Reset mail goes out through the server's SMTP account when no Gmail is connected, and says so when it cannot."""
import smtplib

import pytest

from app.core import notifications

# These test the SMTP sender itself, so they run it - against FakeSMTP below, never a real server.
pytestmark = pytest.mark.fake_smtp


class FakeSMTP:
    sent, fail = [], False

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, context=None): pass

    def login(self, user, password):
        if FakeSMTP.fail:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def sendmail(self, frm, to, msg):
        FakeSMTP.sent.append((frm, to, msg))


def send(monkeypatch, host="smtp.example.com"):
    FakeSMTP.sent, FakeSMTP.fail = [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(notifications, "get_stored_refresh_token", lambda db, client_id=None: "")
    monkeypatch.setenv("SMTP_HOST", host)
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")


def test_sends_through_smtp_when_no_gmail(monkeypatch):
    send(monkeypatch)
    ok, _ = notifications.send_email_background("to@example.com", "Reset", "text", "Y ERP <a@b.c>", "<p>hi</p>")
    assert ok and FakeSMTP.sent[0][1] == ["to@example.com"]


def test_a_provider_refusal_is_reported_without_secrets(monkeypatch):
    send(monkeypatch)
    FakeSMTP.fail = True
    ok, msg = notifications.send_email_background("to@example.com", "Reset", "text", "Y ERP <a@b.c>", "<p>hi</p>")
    assert not ok and "SMTPAuthenticationError" in msg and "app-password" not in msg


def test_an_expired_gmail_connection_says_so(monkeypatch):
    send(monkeypatch)
    monkeypatch.delenv("SMTP_HOST")
    monkeypatch.setattr(notifications, "get_stored_refresh_token", lambda db, client_id=None: "an-old-token")
    monkeypatch.setattr(notifications, "get_gmail_credentials", lambda **k: None)
    ok, msg = notifications.send_email_background("to@example.com", "Alert", "text", "Y ERP <a@b.c>")
    assert not ok and "expired" in msg and FakeSMTP.sent == []


def test_without_any_mail_account_it_says_so(monkeypatch):
    send(monkeypatch)
    monkeypatch.delenv("SMTP_HOST")
    ok, msg = notifications.send_email_background("to@example.com", "Reset", "text", "Y ERP <a@b.c>", "<p>hi</p>")
    assert not ok and "not configured" in msg


# --- Zoho Mail over SMTP --------------------------------------------------------------------------------------------

class FakeSSL(FakeSMTP):
    used = False

    def __init__(self, host, port, context=None, timeout=None):
        FakeSSL.used = True
        super().__init__(host, port, timeout)


def zoho(monkeypatch, sender="smtp"):
    send(monkeypatch, host="smtp.zoho.in")
    FakeSSL.used = False
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSSL)
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "erp@yalavarti.example")
    monkeypatch.setenv("SMTP_FROM", "Yalavarti Infra Projects <erp@yalavarti.example>")
    monkeypatch.setenv("EMAIL_SENDER", sender)


def headers(raw):
    import email
    return email.message_from_string(raw.decode() if isinstance(raw, bytes) else raw)


def test_smtp_chosen_sends_everything_from_the_mailbox_with_replies_to_the_writer(monkeypatch):
    """Zoho refuses mail "from" any address but the signed-in mailbox: the name stays, the address is the mailbox's,
    and Reply-To keeps the original writer. Chosen as the sender, it is used even with a Gmail connected."""
    zoho(monkeypatch)
    monkeypatch.setattr(notifications, "get_stored_refresh_token", lambda db, client_id=None: "a-gmail-token")
    ok, _ = notifications.send_email_background("to@example.com", "Work order", "text", "Site Office <site@company.example>")
    assert ok and FakeSSL.used                                     # port 465: SSL from the start
    frm, to, raw = FakeSMTP.sent[0]
    msg = headers(raw)
    assert frm == "erp@yalavarti.example" and to == ["to@example.com"]
    assert "erp@yalavarti.example" in msg["From"] and "Site Office" in msg["From"]
    assert "site@company.example" in msg["Reply-To"] and msg["Message-ID"]


def test_auto_falls_back_to_smtp_when_gmail_fails(monkeypatch):
    zoho(monkeypatch, sender="auto")
    monkeypatch.setattr(notifications, "get_stored_refresh_token", lambda db, client_id=None: "a-gmail-token")

    def broken(**k):
        raise RuntimeError("Google is down")
    monkeypatch.setattr(notifications, "get_gmail_credentials", broken)
    ok, msg = notifications.send_email_background("to@example.com", "Alert", "text", "Y ERP <a@b.c>")
    assert ok and "SMTP" in msg and FakeSMTP.sent


def test_smtp_chosen_but_not_set_up_says_so(monkeypatch):
    zoho(monkeypatch)
    monkeypatch.delenv("SMTP_HOST")
    ok, msg = notifications.send_email_background("to@example.com", "Alert", "text", "Y ERP <a@b.c>")
    assert not ok and "SMTP_HOST" in msg and FakeSMTP.sent == []


def test_settings_shows_the_smtp_mailbox_never_its_password_and_sends_a_test_by_it(monkeypatch, tenant):
    zoho(monkeypatch)
    monkeypatch.setenv("SMTP_PASSWORD", "zoho-app-password-123")
    status = tenant.get("/api/gmail/status").json()
    assert status["sender"] == "smtp" and status["smtp_ready"] and "erp@yalavarti.example" in status["smtp_from"]
    assert "zoho-app-password-123" not in str(status)
    res = tenant.post("/api/gmail/test", json={"to": "someone@example.com"})
    assert res.status_code == 200 and "by SMTP" in res.json()["message"], res.text
    assert FakeSMTP.sent and FakeSMTP.sent[-1][1] == ["someone@example.com"]
