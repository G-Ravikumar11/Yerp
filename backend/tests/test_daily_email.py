"""The daily summary email: the Master's in plain business terms, and each employee's own pending work, sent to the address
the organisation gave them or, when they have none, to their personal email - and to nobody with nothing pending."""
from datetime import date, datetime, timedelta

import main
from app import db as database, models
from app.services import daily_email
from conftest import make_employee
from _patching import patch_app


def _capture(monkeypatch):
    out = []
    patch_app(monkeypatch, "NOTIFY_SYNC", True)
    monkeypatch.setattr(daily_email, "SYNC", True)
    patch_app(monkeypatch, "send_email_background",
              lambda to, subject, body, frm, **k: out.append({"to": to, "subject": subject, "text": body, "html": k.get("html_body") or ""}) or (True, ""))
    return out


def _job(tenant):
    res = tenant.post("/api/jobs", json={"name": "Sunrise Residency", "number": "SR-%s" % datetime.now().strftime("%H%M%S%f")})
    assert res.status_code == 200, res.text
    return res.json()["id"] if "id" in res.json() else res.json()["job"]["id"]


def _task(jid, emp_id, title, due):
    with database.SessionLocal() as db:
        cid = db.get(models.DBJob, jid).client_id
        t = models.DBProjectThread(client_id=cid, job_id=jid, title="Site")
        db.add(t)
        db.flush()
        db.add(models.DBChatTask(client_id=cid, job_id=jid, thread_id=t.id, title=title, assignee="employee:%d" % emp_id, due_date=due, status="Open"))
        db.commit()


def _po_waiting_on(jid, emp_id, number):
    with database.SessionLocal() as db:
        cid = db.get(models.DBJob, jid).client_id
        po = models.DBPurchaseOrder(client_id=cid, job_id=jid, number=number, supplier_name="Shree Traders", status="Awaiting Approval",
                                    approval_status="pending", current_approval_step=1)
        db.add(po)
        db.flush()
        db.add(models.DBApprovalChain(client_id=cid, entity_type="purchase_order", entity_id=po.id, approver_id=emp_id, step=1, status="pending"))
        db.commit()


def _run(day):
    with database.SessionLocal() as s:
        return main.job_morning_digest(s, day)


def test_each_employee_gets_their_own_work_at_their_org_email_or_else_their_personal_one(tenant, monkeypatch):
    out = _capture(monkeypatch)
    jid = _job(tenant)
    ravi = make_employee(tenant, first_name="Ravi", email="ravi.personal@example.com", org_email="ravi@yalavarti.example")
    meena = make_employee(tenant, first_name="Meena", email="meena.personal@example.com")
    idle = make_employee(tenant, first_name="Idle", email="idle.personal@example.com", org_email="idle@yalavarti.example")
    today = date(2026, 11, 27)
    _task(jid, ravi["id"], "Send the raft pour sequence", (today - timedelta(days=2)).isoformat())
    _po_waiting_on(jid, meena["id"], "PO-0777")
    _run(datetime(2026, 11, 27, 8, 0))
    to = {m["to"]: m for m in out}
    assert "ravi@yalavarti.example" in to and "ravi.personal@example.com" not in to, "the organisation's address when there is one"
    assert "meena.personal@example.com" in to, "else the personal one"
    assert not any(a in to for a in ("idle@yalavarti.example", "idle.personal@example.com")), "nothing pending, no email"
    r = to["ravi@yalavarti.example"]
    assert r["subject"].endswith("Daily summary - 27 Nov 2026") and "Good morning Ravi," in r["text"]
    assert "Task: Send the raft pour sequence" in r["text"] and "overdue since 2026-11-25" in r["text"]
    assert "PO-0777" not in r["text"], "only their own work"
    m = to["meena.personal@example.com"]
    assert "Approvals pending with you" in m["text"] and "PO PO-0777" in m["text"]
    assert "<table" in m["html"] and "Approvals pending with you" in m["html"]


def test_the_masters_summary_uses_plain_business_terms(tenant, monkeypatch):
    out = _capture(monkeypatch)
    tenant.post("/api/bank-accounts", json={"name": "SBI current", "kind": "Bank", "opening_balance": 250000})
    jid = _job(tenant)
    with database.SessionLocal() as db:
        cid = db.get(models.DBJob, jid).client_id
        db.add(models.DBSiteDiary(client_id=cid, job_id=jid, diary_date="2026-11-20", status="DRAFT"))
        db.commit()
    _run(datetime(2026, 11, 27, 8, 0))
    digest = [a for a in tenant.get("/api/alerts").json()["alerts"] if a["kind"] == "daily_digest"]
    assert digest and digest[0]["title"] == "Daily summary - 27 Nov 2026"
    body = digest[0]["body"]
    for words in ("MONEY POSITION", "Receivables", "Payables", "Bank balance", "PENDING WITH YOU", "Site diaries not signed off", "Sign off each day's diary."):
        assert words in body, words
    for old in ("Owed to us", "We owe", "worth a look", "worth nothing in a claim"):
        assert old not in body, old
    master = [m for m in out if m["subject"].endswith("Daily summary - 27 Nov 2026") and "MONEY POSITION" in m["text"]]
    assert master and "<table" in master[0]["html"]


def test_links_point_at_the_page_where_the_work_is_done(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://erp.example.com/")
    assert daily_email.link("/approvals") == "https://erp.example.com/next/approvals"
    monkeypatch.delenv("APP_BASE_URL")
    assert daily_email.link("/approvals") == ""
    assert daily_email.first_sentence("2 days still in draft. An unsigned day is worth nothing.") == "2 days still in draft."
