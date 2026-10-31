"""Document control: transmittals, RFIs and submittals - numbered per kind, answered, followed by a due date, and in
"What needs you" when overdue. The other party is emailed only when Remind is pressed; the sender is replaced."""
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
    assert raise_(tenant, kind="SUBMITTAL", subject="Waterproofing membrane", submittal_type="Material approval")["number"] == "SUB-0001"
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
    assert tenant.post("/api/doc-control/%d/reply" % t["id"], json={"reply": "ACKNOWLEDGED"}).status_code == 400   # by whom?
    ack = tenant.post("/api/doc-control/%d/reply" % t["id"], json={"reply": "ACKNOWLEDGED", "received_by": "R. Menon (PMC)",
                                                                  "received_on": date.today().isoformat()})
    got = ack.json()["item"]
    assert ack.status_code == 200 and (got["status"], got["received_by"], got["received_on"]) == ("ACKNOWLEDGED", "R. Menon (PMC)", date.today().isoformat())


def test_an_rfi_needs_a_question_and_an_answer(tenant):
    assert tenant.post("/api/doc-control", json={"kind": "RFI", "subject": "Grade", "to_party": "PMC"}).status_code == 400
    r = raise_(tenant, kind="RFI", details="M30 or M35 at the pile caps?")
    assert tenant.post("/api/doc-control/%d/reply" % r["id"], json={"reply": "ANSWERED"}).status_code == 400
    out = tenant.post("/api/doc-control/%d/reply" % r["id"], json={"reply": "ANSWERED", "response": "M35, per revised spec"}).json()["item"]
    assert (out["status"], out["response"]) == ("ANSWERED", "M35, per revised spec")
    assert tenant.post("/api/doc-control/%d/reply" % r["id"], json={"reply": "ANSWERED", "response": "again"}).status_code == 409


def test_a_rejected_submittal_goes_up_again_as_its_next_revision(tenant):
    assert tenant.post("/api/doc-control", json={"kind": "SUBMITTAL", "subject": "x", "to_party": "PMC"}).status_code == 400   # which kind?
    s = raise_(tenant, kind="SUBMITTAL", subject="Waterproofing membrane", submittal_type="Shop drawing")
    assert (s["revision"], s["submittal_type"]) == ("R0", "Shop drawing")
    assert tenant.post("/api/doc-control/%d/reply" % s["id"], json={"reply": "REJECTED"}).status_code == 400      # comments needed
    tenant.post("/api/doc-control/%d/reply" % s["id"], json={"reply": "REJECTED", "response": "Thickness below spec"})
    n = tenant.post("/api/doc-control/%d/resubmit" % s["id"]).json()["item"]
    assert (n["number"], n["revision"], n["status"], n["submittal_type"]) == (s["number"], "R1", "OPEN", "Shop drawing")
    assert tenant.get("/api/doc-control/%d" % s["id"]).json()["item"]["status"] == "CLOSED"


def test_the_raiser_is_told_before_the_due_date_and_when_overdue_and_only_remind_emails_the_party(tenant, sent):
    due = date.today() + timedelta(days=1)
    r = raise_(tenant, kind="RFI", details="M30 or M35?", to_email="pmc@example.com", due_date=due.isoformat())
    with database.SessionLocal() as db:
        cid = db.get(models.DBDocControl, r["id"]).client_id
    kinds = lambda k: [a.title for a in database.SessionLocal().query(models.DBAlert).filter(models.DBAlert.client_id == cid, models.DBAlert.kind == k).all()]
    run(date.today())                                                   # the day before: the raiser is told, nobody emailed
    assert sent == [] and any("RFI-0001" in t and "due tomorrow" in t for t in kinds("doc_control_due"))
    run(due + timedelta(days=1))                                        # late: told once that it is overdue
    assert sent == [] and len(kinds("doc_control_overdue")) == 1
    run(due + timedelta(days=2))
    assert len(kinds("doc_control_overdue")) == 1
    res = tenant.post("/api/doc-control/%d/remind" % r["id"])          # a person presses Remind: now the party is emailed
    assert res.status_code == 200 and [m[0] for m in sent] == ["pmc@example.com"]


def test_an_rfi_can_name_its_drawing(tenant):
    j = job(tenant)
    d = tenant.post("/api/jobs/%d/drawings" % j["id"], json={"number": "STR-401", "title": "Pile caps"}).json()["drawing"]
    tenant.post("/api/drawings/%d/revisions" % d["id"], files={"file": ("r0.pdf", io.BytesIO(PDF), "application/pdf")}, data={"revision": "R0"})
    r = raise_(tenant, kind="RFI", details="Cover to the caps?", drawing_id=d["id"])
    assert (r["drawing_id"], r["drawing"]) == (d["id"], "STR-401 rev R0")


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
