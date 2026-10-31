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


def test_the_server_mailbox_sends_everything_even_with_gmail_connected_and_says_it_is_from_itself(monkeypatch):
    send(monkeypatch)
    monkeypatch.setattr(notifications, "get_stored_refresh_token", lambda db, client_id=None: "a-connected-gmail")
    monkeypatch.setattr(notifications, "get_gmail_credentials", lambda **k: pytest.fail("Gmail is not used when the server has a mailbox"))
    ok, _ = notifications.send_email_background("to@example.com", "Alert", "text", "Acme Builders <noreply@acme.example>", client_id=7)
    frm, to, msg = FakeSMTP.sent[0]
    assert ok and to == ["to@example.com"] and frm == "sender@example.com"
    assert b"From: Acme Builders <sender@example.com>" in msg
    assert notifications.server_mailbox() == "sender@example.com" and notifications.mail_ready(None, 7)


def test_an_expired_gmail_connection_says_so(monkeypatch):
    send(monkeypatch)
    monkeypatch.delenv("SMTP_HOST")
    monkeypatch.setattr(notifications, "get_stored_refresh_token", lambda db, client_id=None: "an-old-token")
    monkeypatch.setattr(notifications, "get_gmail_credentials", lambda **k: None)
    ok, msg = notifications.send_email_background("to@example.com", "Alert", "text", "Y ERP <a@b.c>")
    assert not ok and "expired" in msg


def test_without_any_mail_account_it_says_so(monkeypatch):
    send(monkeypatch)
    monkeypatch.delenv("SMTP_HOST")
    ok, msg = notifications.send_email_background("to@example.com", "Reset", "text", "Y ERP <a@b.c>", "<p>hi</p>")
    assert not ok and "not configured" in msg
