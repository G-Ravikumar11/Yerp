"""Tracebacks are the platform admin's: a company sees that one is kept, the super-admin reads every company's; and
the super-admin is told when server faults spike."""
from datetime import datetime, timedelta

import pytest

import main
from app import db as database, models
from _patching import patch_app


@pytest.fixture
def superadmin(client):
    main.rate_limiter._hits.clear()
    res = client.post("/api/superadmin/login", json={"identifier": "hello@billing.com", "password": "TestSuper123"})
    assert res.status_code == 200, res.text
    return client


def fault(client_id, at=None, path="/api/boom", trace="Traceback (most recent call last):\n  ValueError: boom"):
    with database.SessionLocal() as db:
        db.add(models.DBErrorLog(client_id=client_id, at=(at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), code="YE-SRV-01",
                                 ref="ABCD1234", status=500, method="GET", path=path, detail="Something went wrong", who="owner", trace=trace))
        db.commit()


def client_id_of(account):
    with database.SessionLocal() as db:
        return db.query(models.DBClient).filter(models.DBClient.email == account["email"]).one().id


def test_the_company_sees_the_fault_but_not_its_traceback(account):
    fault(client_id_of(account))
    [e] = [e for e in account["client"].get("/api/errors").json()["errors"] if e["code"] == "YE-SRV-01"]
    assert e["trace"] == "" and e["has_trace"] is True and e["ref"] == "ABCD1234"


def test_the_platform_admin_reads_every_companys_tracebacks(account, superadmin):
    fault(client_id_of(account))
    out = superadmin.get("/api/superadmin/errors").json()
    mine = [e for e in out["errors"] if e["ref"] == "ABCD1234"]
    assert mine and "ValueError: boom" in mine[0]["trace"] and mine[0]["company"]
    assert set(out["spike"]) == {"last_hour", "usual_per_hour", "threshold", "spiking"}


def test_a_company_cannot_read_the_platforms_error_route(account):
    assert account["client"].get("/api/superadmin/errors").status_code == 401


def test_a_spike_in_server_faults_alerts_the_platform_admin_once_an_hour(account, monkeypatch):
    cid = client_id_of(account)
    now = datetime.now()
    for _ in range(12):
        fault(cid, at=now - timedelta(minutes=5), path="/api/jobs")
    mails = []
    monkeypatch.setenv("PLATFORM_ALERT_EMAIL", "ops@example.com")
    patch_app(monkeypatch, "send_email_background", lambda to, subject, body, frm, **k: mails.append((to, subject, body)) or (True, "ok"))
    with database.SessionLocal() as db:
        db.query(models.DBJobRun).filter(models.DBJobRun.job_name == "error_spike_alert").delete()
        db.commit()
    [run] = main.run_due_jobs(now=now, only="error_spike_alert")
    assert run["status"] == "done" and "spike" in run["detail"]
    assert mails and mails[0][0] == "ops@example.com" and "/api/jobs" in mails[0][2]
    assert main.run_due_jobs(now=now, only="error_spike_alert")[0]["status"] == "already_done"     # once an hour
