"""Document control: transmittals, RFIs and submittals - numbered per kind, answered, chased by a due date, and in
"What needs you" when overdue. Nothing really goes out: the sender is replaced."""
import io
from datetime import date, datetime, timedelta

import pytest

import main
from app import db as database, models
from _patching import patch_app
from test_project_files import PDF, job


@pytest.fixture
def sent(monkeypatch):
    out = []
    patch_app(monkeypatch, "send_email_background", lambda to, subject, body, frm, **k: out.append((to, subject, body)) or (True, "ok"))
    return out


def raise_(tenant, **body):
    body.setdefault("subject", "Raft levels")
    body.setdefault("to_party", "Arcadis (PMC)")
    res = tenant.post("/api/doc-control", json=body)
    assert res.status_code == 200, res.text
    return res.json()["item"]


def run(day):
    with database.SessionLocal() as db:
        db.query(models.DBJobRun).filter(models.DBJobRun.job_name == "doc_control_reminders").delete()
        db.commit()
    return main.run_due_jobs(now=datetime.combine(day, datetime.min.time()).replace(hour=9), only="doc_control_reminders")


def test_each_kind_has_its_own_series(tenant):
    assert raise_(tenant, kind="TRANSMITTAL")["number"] == "TR-0001"
    assert raise_(tenant, kind="RFI", details="Which grade at the pile caps?")["number"] == "RFI-0001"
    assert raise_(tenant, kind="SUBMITTAL", subject="Waterproofing membrane")["number"] == "SUB-0001"
    assert raise_(tenant, kind="RFI", details="Second question")["number"] == "RFI-0002"


def test_a_transmittal_records_each_drawing_at_the_revision_sent(tenant):
    j = job(tenant)
    d = tenant.post("/api/jobs/%d/drawings" % j["id"], json={"number": "STR-301", "title": "Pile caps"}).json()["drawing"]
    tenant.post("/api/drawings/%d/revisions" % d["id"], files={"file": ("r1.pdf", io.BytesIO(PDF), "application/pdf")}, data={"revision": "R1"})
    t = raise_(tenant, kind="TRANSMITTAL", job_id=j["id"], purpose="For construction",
               items=[{"drawing_id": d["id"]}, {"description": "Bar bending schedule, 4 sheets"}])
    assert [(i["number"], i["revision"]) for i in t["items"]] == [("STR-301", "R1"), ("", "")]
    # A later revision does not change what was sent.
    tenant.post("/api/drawings/%d/revisions" % d["id"], files={"file": ("r2.pdf", io.BytesIO(PDF + b"2"), "application/pdf")}, data={"revision": "R2"})
    assert tenant.get("/api/doc-control/%d" % t["id"]).json()["item"]["items"][0]["revision"] == "R1"
    ack = tenant.post("/api/doc-control/%d/reply" % t["id"], json={"reply": "ACKNOWLEDGED"})
    assert ack.status_code == 200 and ack.json()["item"]["status"] == "ACKNOWLEDGED"


def test_an_rfi_needs_a_question_and_an_answer(tenant):
    assert tenant.post("/api/doc-control", json={"kind": "RFI", "subject": "Grade", "to_party": "PMC"}).status_code == 400
    r = raise_(tenant, kind="RFI", details="M30 or M35 at the pile caps?")
    assert tenant.post("/api/doc-control/%d/reply" % r["id"], json={"reply": "ANSWERED"}).status_code == 400
    out = tenant.post("/api/doc-control/%d/reply" % r["id"], json={"reply": "ANSWERED", "response": "M35, per revised spec"}).json()["item"]
    assert (out["status"], out["response"]) == ("ANSWERED", "M35, per revised spec")
    assert tenant.post("/api/doc-control/%d/reply" % r["id"], json={"reply": "ANSWERED", "response": "again"}).status_code == 409


def test_a_rejected_submittal_goes_up_again_as_its_next_revision(tenant):
    s = raise_(tenant, kind="SUBMITTAL", subject="Waterproofing membrane")
    assert s["revision"] == "R0"
    assert tenant.post("/api/doc-control/%d/reply" % s["id"], json={"reply": "REJECTED"}).status_code == 400      # comments needed
    tenant.post("/api/doc-control/%d/reply" % s["id"], json={"reply": "REJECTED", "response": "Thickness below spec"})
    n = tenant.post("/api/doc-control/%d/resubmit" % s["id"]).json()["item"]
    assert (n["number"], n["revision"], n["status"]) == (s["number"], "R1", "OPEN")
    assert tenant.get("/api/doc-control/%d" % s["id"]).json()["item"]["status"] == "CLOSED"


def test_the_party_is_reminded_before_the_due_date_and_while_overdue_and_the_raiser_is_told(tenant, sent):
    due = date.today() + timedelta(days=1)
    r = raise_(tenant, kind="RFI", details="M30 or M35?", to_email="pmc@example.com", due_date=due.isoformat())
    run(date.today())                                                   # the day before
    assert [m[0] for m in sent] == ["pmc@example.com"] and "RFI-0001" in sent[0][1]
    sent.clear()
    run(due)                                                            # on the day: nothing
    assert sent == []
    run(due + timedelta(days=3))                                        # three days late: reminded, and the raiser told
    assert [m[0] for m in sent] == ["pmc@example.com"] and "was due" in sent[0][2]
    with database.SessionLocal() as db:
        cid = db.get(models.DBDocControl, r["id"]).client_id
        alerts = db.query(models.DBAlert).filter(models.DBAlert.client_id == cid, models.DBAlert.kind == "doc_control_overdue").all()
        assert len(alerts) == 1 and "RFI-0001" in alerts[0].title


def test_what_is_overdue_needs_you(tenant):
    r = raise_(tenant, kind="RFI", details="Q", due_date=date.today().isoformat())
    with database.SessionLocal() as db:
        db.get(models.DBDocControl, r["id"]).due_date = (date.today() - timedelta(days=2)).isoformat()
        db.commit()
    items = {i["kind"]: i for i in tenant.get("/api/attention").json()["items"]}
    assert "RFI-0001" in items["doc_control_overdue"]["detail"]
    lst = tenant.get("/api/doc-control", params={"kind": "RFI"}).json()
    assert lst["summary"]["RFI"] == {"open": 1, "overdue": 1} and lst["items"][0]["overdue"] is True


def test_a_due_date_cannot_have_gone_and_another_company_sees_nothing(tenant, second_tenant):
    assert tenant.post("/api/doc-control", json={"kind": "TRANSMITTAL", "subject": "x", "to_party": "y",
                                                 "due_date": (date.today() - timedelta(days=1)).isoformat()}).status_code == 400
    t = raise_(tenant, kind="TRANSMITTAL")
    assert second_tenant.get("/api/doc-control/%d" % t["id"]).status_code == 404
    assert second_tenant.get("/api/doc-control").json()["items"] == []
