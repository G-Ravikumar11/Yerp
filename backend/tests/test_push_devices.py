"""Registering a phone for push, and the sender doing nothing until Firebase is set up."""
from app import models
from app.core import push


def test_push_is_off_without_firebase(monkeypatch):
    monkeypatch.delenv("FCM_PROJECT_ID", raising=False)
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_JSON", raising=False)
    assert push.push_ready() is False
    push.push_to(None, 1, "Title")  # no database touched, no error


def test_status_endpoint(client):
    assert client.get("/api/devices/status").json() == {"enabled": push.push_ready()}


def test_registering_needs_sign_in(client):
    r = client.post("/api/devices", json={"token": "x" * 20, "platform": "ios"})
    assert r.status_code in (401, 403)
