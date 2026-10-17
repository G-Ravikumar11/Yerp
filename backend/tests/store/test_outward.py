"""P3 - outward: requisitions, issues (site / subcontractor / direct), returns with losses, outstanding returnables, rights."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import make_employee

from app import db as database, models
from app.models.store_core import (
    DBStore, DBStoreBin, DBStoreDocSequence, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger,
    DBStoreUomConversion, DBStoreUserAssignment, MovementType,
)
from app.models.store_outward import (
    DBStoreIssue, DBStoreIssueLine, DBStoreIssueReturn, DBStoreIssueReturnLine, DBStoreOutwardLog, DBStoreRequisition,
    DBStoreRequisitionLine, DBStoreWriteoffRequest,
)
from app.services.stock_ledger import get_balance, post_movement
from app.services.store_outward import (
    close_writeoff_request, get_outstanding_returnables, get_subcon_issues, list_writeoff_requests,
)

D = Decimal
O = "/api/store/outward"
VIEW = ["store.%s.view" % s for s in ("masters", "enquiry", "outward")]


@pytest.fixture(autouse=True)
def _clean(account):
    yield
    with database.SessionLocal() as s:
        cid = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id
        stores = [i for (i,) in s.query(DBStore.id).filter(DBStore.client_id == cid).all()]
        items = [i for (i,) in s.query(models.DBItem.id).filter(models.DBItem.client_id == cid).all()]
        reqs = [i for (i,) in s.query(DBStoreRequisition.id).filter(DBStoreRequisition.client_id == cid).all()]
        issues = [i for (i,) in s.query(DBStoreIssue.id).filter(DBStoreIssue.client_id == cid).all()]
        rtns = [i for (i,) in s.query(DBStoreIssueReturn.id).filter(DBStoreIssueReturn.client_id == cid).all()]
        for t, ids in (("MRQ", reqs), ("ISSUE", issues), ("RTN", rtns)):
            s.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_type == t, DBStoreOutwardLog.doc_id.in_(ids)).delete(synchronize_session=False)
        s.query(DBStoreWriteoffRequest).filter(DBStoreWriteoffRequest.client_id == cid).delete(synchronize_session=False)
        s.query(DBStoreIssueReturnLine).filter(DBStoreIssueReturnLine.return_id.in_(rtns)).delete(synchronize_session=False)
        s.query(DBStoreIssueReturn).filter(DBStoreIssueReturn.id.in_(rtns)).delete(synchronize_session=False)
        s.query(DBStoreIssueLine).filter(DBStoreIssueLine.issue_id.in_(issues)).delete(synchronize_session=False)
        s.query(DBStoreIssue).filter(DBStoreIssue.id.in_(issues)).delete(synchronize_session=False)
        s.query(DBStoreRequisitionLine).filter(DBStoreRequisitionLine.requisition_id.in_(reqs)).delete(synchronize_session=False)
        s.query(DBStoreRequisition).filter(DBStoreRequisition.id.in_(reqs)).delete(synchronize_session=False)
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreStockBalance, DBStoreFreeze, DBStoreUserAssignment, DBStoreBin, DBStoreDocSequence):
            s.query(model).filter(model.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreUomConversion, DBStoreItemSettings):
            s.query(model).filter(model.item_id.in_(items)).delete(synchronize_session=False)
        s.query(DBStore).filter(DBStore.id.in_(stores)).delete(synchronize_session=False)
        for m, col in ((models.DBContractor, models.DBContractor.client_id),):
            s.query(m).filter(col == cid).delete(synchronize_session=False)
        wos = [i for (i,) in s.query(models.DBWorkOrder.id).filter(models.DBWorkOrder.client_id == cid).all()]
        boqs = [i for (i,) in s.query(models.DBBoq.id).filter(models.DBBoq.client_id == cid).all()]
        s.query(models.DBWorkOrder).filter(models.DBWorkOrder.id.in_(wos)).delete(synchronize_session=False)
        s.query(models.DBBoqLine).filter(models.DBBoqLine.boq_id.in_(boqs)).delete(synchronize_session=False)
        s.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id.in_(boqs)).delete(synchronize_session=False)
        s.query(models.DBBoq).filter(models.DBBoq.id.in_(boqs)).delete(synchronize_session=False)
        s.query(models.DBJob).filter(models.DBJob.client_id == cid).delete(synchronize_session=False)
        s.commit()


class W:
    pass


def seed(account, cement_qty="1000", shutter_qty="50"):
    """A project with a work order and two BOQ items, a store holding cement (kg) and returnable shuttering, a subcontractor."""
    o = account["client"]
    w = W()
    tag = uuid.uuid4().hex[:6]
    with database.SessionLocal() as s:
        w.cid = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id
        job = models.DBJob(client_id=w.cid, number="P-" + tag, name="Tower A")
        s.add(job)
        s.flush()
        boq = models.DBBoq(client_id=w.cid, job_id=job.id, number="B-" + tag, title="Tower A")
        s.add(boq)
        s.flush()
        rev = models.DBBoqRevision(boq_id=boq.id, rev_no=0, label="R0")
        s.add(rev)
        s.flush()
        lines = [models.DBBoqLine(boq_id=boq.id, revision_id=rev.id, key="k%d" % i, kind="item", item_no=str(i), description="Work %d" % i, uom="cum", quantity=10, rate=100, amount=1000) for i in (1, 2)]
        job2 = models.DBJob(client_id=w.cid, number="P2-" + tag, name="Tower B")
        s.add(job2)
        s.flush()
        other_boq = models.DBBoq(client_id=w.cid, job_id=job2.id, number="B2-" + tag, title="Other")
        s.add_all(lines + [other_boq])
        s.flush()
        rev2 = models.DBBoqRevision(boq_id=other_boq.id, rev_no=0, label="R0")
        s.add(rev2)
        s.flush()
        foreign = models.DBBoqLine(boq_id=other_boq.id, revision_id=rev2.id, key="z", kind="item", item_no="9", description="Other work", uom="cum", quantity=1, rate=1, amount=1)
        wo = models.DBWorkOrder(client_id=w.cid, job_id=job.id, number="WO-" + tag, status="Approved", boq_id=boq.id)
        sub = models.DBContractor(client_id=w.cid, vendor_code="V-" + tag, company_name="Sai Steel Fixers")
        cement = models.DBItem(client_id=w.cid, kind="RM", item_code="CEM-" + tag, item_name="Cement", units_of_measure="kg")
        shutter = models.DBItem(client_id=w.cid, kind="RM", item_code="SHT-" + tag, item_name="Shuttering Plate", units_of_measure="nos")
        emp = models.DBEmployee(client_id=w.cid, first_name="Mason", last_name="Gang", email="m-%s@example.com" % tag, permission_role="staff")
        s.add_all([foreign, wo, sub, cement, shutter, emp])
        s.flush()
        s.add_all([DBStoreItemSettings(item_id=cement.id, base_uom="kg", category="CONSUMABLE"), DBStoreItemSettings(item_id=shutter.id, base_uom="nos", category="RETURNABLE"),
                   DBStoreUomConversion(item_id=cement.id, from_uom="bag", to_base_factor=50)])
        s.commit()
        w.project, w.wo, w.boq1, w.boq2, w.foreign_boq, w.sub, w.cement, w.shutter, w.emp = job.id, wo.id, lines[0].id, lines[1].id, foreign.id, sub.id, cement.id, shutter.id, emp.id
    w.store = o.post("/api/store/masters/stores", json={"code": "S" + uuid.uuid4().hex[:4].upper(), "name": "Site Store", "type": "SITE", "project_id": w.project}).json()["id"]
    with database.SessionLocal() as s:
        for item, qty, rate in ((w.cement, cement_qty, "7"), (w.shutter, shutter_qty, "450")):
            post_movement(s, movement_type=MovementType.OPENING_IN, store_id=w.store, item_id=item, qty=D(qty), rate=D(rate), txn_date=date.today() - timedelta(days=5),
                          project_id=None, ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        s.commit()
    return w


def bal(store, item):
    with database.SessionLocal() as s:
        b = get_balance(s, store, item)
        return b.qty, b.value


def go(o, kind, doc_id, *actions):
    res = None
    for a in actions:
        res = o.post("%s/%s/%d/%s" % (O, kind, doc_id, a), json={"reason": "because"} if a == "cancel" else {})
        assert res.status_code == 200, (a, res.text)
    return res.json()


def mrq(o, w, lines=None, **kw):
    res = o.post(O + "/requisitions", json={"store_id": w.store, "work_order_id": w.wo, "boq_item_id": w.boq1, "purpose": "Slab pour",
                                           "lines": lines or [{"item_id": w.cement, "qty": "10", "uom": "bag"}], **kw})
    assert res.status_code == 201, res.text
    return res.json()


def issue(o, w, lines=None, status=201, **kw):
    body = {"store_id": w.store, "project_id": w.project, "lines": lines or [{"item_id": w.cement, "qty": "100"}], **kw}
    res = o.post(O + "/issues", json=body)
    assert res.status_code == status, res.text
    return res.json()


def test_requisition_then_issue_posts_with_costing(account):
    o = account["client"]
    w = seed(account)
    r = mrq(o, w)
    assert r["number"].startswith("MRQ/") and r["lines"][0]["qty"] == "500.000" and r["status"] == "DRAFT"           # 10 bags = 500 kg
    assert o.post(O + "/issues", json={"store_id": w.store, "requisition_id": r["id"], "lines": [{"item_id": w.cement, "qty": "10"}]}).status_code == 409   # not approved yet
    assert go(o, "requisitions", r["id"], "submit", "approve")["status"] == "APPROVED"
    assert o.post("%s/requisitions/%d/post" % (O, r["id"])).status_code == 409                                      # moves no stock

    i = o.post(O + "/issues", json={"store_id": w.store, "requisition_id": r["id"], "lines": [{"item_id": w.cement, "qty": "6", "uom": "bag"}]}).json()
    assert i["work_order_id"] == w.wo and i["boq_item_id"] == w.boq1 and i["project_id"] == w.project and not i["direct"]     # costing comes from the requisition
    assert bal(w.store, w.cement) == (D("1000"), D("7000"))                                                         # nothing yet
    done = go(o, "issues", i["id"], "submit", "approve", "post")
    assert done["status"] == "POSTED" and done["total_value"] == "2100.00" and done["lines"][0]["rate"] == "7.0000"   # 300 kg @ 7
    assert bal(w.store, w.cement) == (D("700"), D("4900"))
    with database.SessionLocal() as s:
        e = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "ISSUE", DBStoreStockLedger.ref_doc_id == i["id"]).one()
        assert (e.movement_type, e.project_id, e.work_order_id, e.boq_item_id) == ("ISSUE_OUT", w.project, w.wo, w.boq1)
    assert o.get("%s/requisitions/%d" % (O, r["id"])).json()["lines"][0]["issued_qty"] == "300.000"
    over = o.post(O + "/issues", json={"store_id": w.store, "requisition_id": r["id"], "lines": [{"item_id": w.cement, "qty": "5", "uom": "bag"}]})
    assert over.status_code == 409                                                                                  # only 4 bags left on the requisition
    assert o.post("%s/requisitions/%d/cancel" % (O, r["id"]), json={"reason": "x"}).status_code == 409             # an issue stands against it
    for kind, pk in (("issues", i["id"]), ("requisitions", r["id"])):
        pdf = o.get("%s/%s/%d/pdf" % (O, kind, pk))
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_insufficient_stock_stops_the_post(account):
    o = account["client"]
    w = seed(account, cement_qty="100")
    i = issue(o, w, [{"item_id": w.cement, "qty": "101"}])
    go(o, "issues", i["id"], "submit", "approve")
    res = o.post("%s/issues/%d/post" % (O, i["id"]))
    assert res.status_code == 409
    assert bal(w.store, w.cement)[0] == D("100") and o.get("%s/issues/%d" % (O, i["id"])).json()["status"] == "APPROVED"


def test_two_lines_post_all_or_nothing(account):
    o = account["client"]
    w = seed(account, shutter_qty="5")
    i = issue(o, w, [{"item_id": w.cement, "qty": "100"}, {"item_id": w.shutter, "qty": "10"}], holder_type="GANG", holder_name="Gang A")
    go(o, "issues", i["id"], "submit", "approve")
    assert o.post("%s/issues/%d/post" % (O, i["id"])).status_code == 409
    assert bal(w.store, w.cement)[0] == D("1000")                                                                   # the cement line was rolled back too


def test_costing_rules(account):
    o = account["client"]
    w = seed(account)
    body = {"store_id": w.store, "lines": [{"item_id": w.cement, "qty": "1"}]}
    assert o.post(O + "/issues", json={**body, "project_id": None}).status_code in (201, 400)
    plain = o.post("/api/store/masters/stores", json={"code": "NP" + uuid.uuid4().hex[:3].upper(), "name": "No project"}).json()["id"]
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.OPENING_IN, store_id=plain, item_id=w.cement, qty=D(10), rate=D(7), txn_date=date.today(), project_id=None,
                      ref_doc_type="OPENING", ref_doc_id=2, ref_line_id=None, user_id=None)
        s.commit()
    assert o.post(O + "/issues", json={"store_id": plain, "lines": [{"item_id": w.cement, "qty": "1"}]}).status_code == 400          # charged to nothing
    ok = o.post(O + "/issues", json={"store_id": plain, "cost_head": "SAFETY", "lines": [{"item_id": w.cement, "qty": "1"}]})
    assert ok.status_code == 201 and ok.json()["cost_head"] == "SAFETY"
    assert o.post(O + "/issues", json={"store_id": plain, "cost_head": "NOPE", "lines": [{"item_id": w.cement, "qty": "1"}]}).status_code == 400
    assert issue(o, w, work_order_id=w.wo, boq_item_id=w.foreign_boq, status=400)                                   # BOQ item of another BOQ
    assert o.post(O + "/issues", json={**body, "project_id": w.project, "boq_item_id": w.boq1}).status_code == 400  # BOQ item without a work order
    assert o.post(O + "/issues", json={**body, "project_id": w.project, "lines": [{"item_id": w.cement, "qty": "1", "uom": "bale"}]}).status_code == 400   # unknown unit
    assert o.post(O + "/issues", json={**body, "project_id": w.project, "lines": [{"item_id": w.cement, "qty": "0"}]}).status_code == 400


def test_cancelling_a_posted_issue_puts_stock_back(account):
    o = account["client"]
    w = seed(account)
    i = issue(o, w)
    go(o, "issues", i["id"], "submit", "approve", "post")
    assert bal(w.store, w.cement)[0] == D("900")
    assert o.put("%s/issues/%d" % (O, i["id"]), json={"purpose": "late"}).status_code == 409                       # posted is immutable
    assert o.post("%s/issues/%d/cancel" % (O, i["id"]), json={}).status_code == 400                                 # a reason
    assert go(o, "issues", i["id"], "cancel")["status"] == "CANCELLED"
    assert bal(w.store, w.cement) == (D("1000"), D("7000"))
    assert o.post("%s/issues/%d/post" % (O, i["id"])).status_code == 409


def test_returnable_items_holder_return_and_loss(account):
    o = account["client"]
    w = seed(account)
    lines = [{"item_id": w.shutter, "qty": "20"}]
    issue(o, w, lines, status=400)                                                                                  # returnable needs a holder
    i = issue(o, w, lines, holder_type="EMPLOYEE", holder_id=w.emp, expected_return_date=str(date.today() - timedelta(days=3)))
    assert i["holder_name"] == "Mason Gang" and i["lines"][0]["returnable"]
    go(o, "issues", i["id"], "submit", "approve", "post")
    assert bal(w.store, w.shutter) == (D("30"), D("13500"))
    out = o.get(O + "/outstanding").json()["rows"]
    assert len(out) == 1 and out[0]["qty_outstanding"] == "20.000" and out[0]["overdue_days"] == 3 and out[0]["holder_name"] == "Mason Gang"
    with database.SessionLocal() as s:
        r = get_outstanding_returnables(s, project_id=w.project)[0]
        assert (r.holder_type, r.holder_id, r.qty_outstanding) == ("EMPLOYEE", w.emp, D("20"))

    line = i["lines"][0]["id"]
    assert o.post(O + "/returns", json={"store_id": w.store, "issue_id": i["id"], "lines": [{"issue_line_id": line, "qty": "21"}]}).status_code == 409          # more than is out
    assert o.post(O + "/returns", json={"store_id": w.store, "issue_id": i["id"], "lines": [{"issue_line_id": line, "qty": "15", "lost_qty": "2"}]}).status_code == 400   # loss needs a reason
    rt = o.post(O + "/returns", json={"store_id": w.store, "issue_id": i["id"], "lines": [{"issue_line_id": line, "qty": "15", "lost_qty": "2", "remarks": "bent beyond use"}]}).json()
    assert rt["number"].startswith("RTN/")
    done = go(o, "returns", rt["id"], "submit", "approve", "post")
    assert done["status"] == "POSTED" and done["lines"][0]["value"] == "6750.00"                                    # 15 back at the 450 it left at
    assert bal(w.store, w.shutter) == (D("45"), D("20250"))
    out = o.get(O + "/outstanding").json()["rows"]
    assert out[0]["qty_outstanding"] == "3.000"                                                                     # 20 - 15 back - 2 lost
    w_off = o.get(O + "/writeoffs").json()["rows"]
    assert len(w_off) == 1 and w_off[0]["qty"] == "2.000" and w_off[0]["reason"] == "bent beyond use"
    assert o.post("%s/issues/%d/cancel" % (O, i["id"]), json={"reason": "x"}).status_code == 409                   # a return stands against it
    assert o.get("%s/issues/%d/returnable" % (O, i["id"])).json()["lines"][0]["still_out_qty"] == "3.000"

    with database.SessionLocal() as s:                                                                              # the control slice's side
        req = list_writeoff_requests(s)
        assert len(req) == 1 and req[0].qty == D("2") and req[0].status == "OPEN"
        close_writeoff_request(s, req[0].request_id, "SCRAP", 9, None)
        s.commit()
        assert list_writeoff_requests(s) == [] and list_writeoff_requests(s, "CLOSED")[0].status == "CLOSED"
    assert o.post("%s/returns/%d/cancel" % (O, rt["id"]), json={"reason": "x"}).status_code == 409                 # loss already written off

    pdf = o.get("%s/returns/%d/pdf" % (O, rt["id"]))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_cancelling_a_return_takes_the_stock_out_and_reopens_the_issue(account):
    o = account["client"]
    w = seed(account)
    i = issue(o, w, [{"item_id": w.shutter, "qty": "10"}], holder_type="GANG", holder_name="Carpenters")
    go(o, "issues", i["id"], "submit", "approve", "post")
    rt = o.post(O + "/returns", json={"store_id": w.store, "issue_id": i["id"], "lines": [{"issue_line_id": i["lines"][0]["id"], "qty": "4", "lost_qty": "1", "remarks": "lost"}]}).json()
    go(o, "returns", rt["id"], "submit", "approve", "post")
    assert bal(w.store, w.shutter)[0] == D("44")
    go(o, "returns", rt["id"], "cancel")
    assert bal(w.store, w.shutter)[0] == D("40")
    assert o.get(O + "/writeoffs").json()["rows"] == []                                                             # the open request was withdrawn
    assert o.get(O + "/outstanding").json()["rows"][0]["qty_outstanding"] == "10.000"
    assert go(o, "issues", i["id"], "cancel")["status"] == "CANCELLED"
    assert bal(w.store, w.shutter)[0] == D("50")


def test_subcontractor_issue_and_recovery(account):
    o = account["client"]
    w = seed(account)
    assert o.post(O + "/issues", json={"store_id": w.store, "project_id": w.project, "issue_type": "SUBCONTRACTOR", "lines": [{"item_id": w.cement, "qty": "1"}]}).status_code == 400
    i = issue(o, w, [{"item_id": w.cement, "qty": "200", "chargeable": True, "recovery_rate": "8"}], issue_type="SUBCONTRACTOR", subcontractor_id=w.sub)
    assert i["holder_type"] == "SUBCONTRACTOR" and i["subcontractor_name"] == "Sai Steel Fixers"
    go(o, "issues", i["id"], "submit", "approve", "post")
    with database.SessionLocal() as s:
        e = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "ISSUE", DBStoreStockLedger.ref_doc_id == i["id"]).one()
        assert (e.movement_type, e.subcontractor_id) == ("SUBCON_ISSUE_OUT", w.sub)
        rows = get_subcon_issues(s, w.sub, date.today())
        assert len(rows) == 1 and (rows[0].qty_issued, rows[0].qty_returned, rows[0].chargeable, rows[0].recovery_value) == (D("200"), D("0"), True, D("1600.00"))
        assert get_subcon_issues(s, w.sub, date.today() - timedelta(days=1)) == []
    rt = o.post(O + "/returns", json={"store_id": w.store, "issue_id": i["id"], "lines": [{"issue_line_id": i["lines"][0]["id"], "qty": "50"}]}).json()
    go(o, "returns", rt["id"], "submit", "approve", "post")
    with database.SessionLocal() as s:
        r = get_subcon_issues(s, w.sub, date.today())[0]
        assert (r.qty_returned, r.recovery_value) == (D("50"), D("1200.00"))                                        # only the 150 kg kept is recovered
        e = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "RTN", DBStoreStockLedger.ref_doc_id == rt["id"]).one()
        assert (e.movement_type, e.rate) == ("SUBCON_RETURN_IN", D("7.0000"))


def test_lifecycle_and_draft_editing(account):
    o = account["client"]
    w = seed(account)
    i = issue(o, w)
    for step in ("approve", "post"):
        assert o.post("%s/issues/%d/%s" % (O, i["id"], step)).status_code == 409
    assert o.put("%s/issues/%d" % (O, i["id"]), json={"purpose": "Columns", "lines": [{"item_id": w.cement, "qty": "5"}]}).json()["lines"][0]["qty"] == "5.000"
    go(o, "issues", i["id"], "submit")
    assert o.put("%s/issues/%d" % (O, i["id"]), json={"purpose": "x"}).status_code == 409
    assert [x["to"] for x in o.get("%s/issues/%d" % (O, i["id"])).json()["log"]] == ["DRAFT", "SUBMITTED"]
    assert o.get(O + "/issues", params={"status": "SUBMITTED"}).json()["total"] == 1
    assert o.get(O + "/issues", params={"status": "BOGUS"}).status_code == 400
    assert o.post(O + "/issues", json={"store_id": w.store, "project_id": w.project, "lines": []}).status_code == 400


def _login(account, portal, rights, stores):
    email = "staff-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = ",".join(rights)
        s.add_all([DBStoreUserAssignment(store_id=i, employee_id=row.id) for i in stores])
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200


def test_rights_direct_issue_and_store_access(account, portal):
    o = account["client"]
    w = seed(account)
    other = o.post("/api/store/masters/stores", json={"code": "OT" + uuid.uuid4().hex[:3].upper(), "name": "Other"}).json()["id"]
    r = mrq(o, w)
    go(o, "requisitions", r["id"], "submit", "approve")
    i = issue(o, w)
    go(o, "issues", i["id"], "submit")
    body = {"store_id": w.store, "project_id": w.project, "lines": [{"item_id": w.cement, "qty": "1"}]}

    _login(account, portal, VIEW + ["store.outward.create"], [w.store])                                             # can draft, cannot issue direct
    assert portal.post(O + "/issues", json=body).status_code == 403
    assert portal.post(O + "/issues", json={**body, "requisition_id": r["id"]}).status_code == 201                  # against a requisition is fine
    assert portal.post(O + "/requisitions", json={"store_id": other, "project_id": w.project, "lines": [{"item_id": w.cement, "qty": "1"}]}).status_code == 403   # wrong store
    assert portal.post("%s/issues/%d/approve" % (O, i["id"])).status_code == 403
    assert portal.post("%s/issues/%d/post" % (O, i["id"])).status_code == 403
    assert portal.post("%s/issues/%d/cancel" % (O, i["id"]), json={"reason": "x"}).status_code == 403

    _login(account, portal, VIEW + ["store.outward.create", "store.outward.direct_issue"], [w.store])
    assert portal.post(O + "/issues", json=body).status_code == 201

    _login(account, portal, VIEW, [w.store])                                                                         # view only
    assert portal.post(O + "/requisitions", json={"store_id": w.store, "lines": []}).status_code == 403
    assert portal.get("%s/issues/%d" % (O, i["id"])).status_code == 200

    _login(account, portal, VIEW + ["store.outward.approve", "store.outward.post"], [other])                         # right rights, wrong store
    assert portal.get("%s/issues/%d" % (O, i["id"])).status_code == 403
    assert portal.post("%s/issues/%d/approve" % (O, i["id"])).status_code == 403
    assert portal.get(O + "/issues").json()["total"] == 0
    assert portal.get(O + "/outstanding", params={"store_id": w.store}).status_code == 403

    _login(account, portal, ["store.inward.view"], [w.store])
    assert portal.get(O + "/issues").status_code == 403

    _login(account, portal, VIEW + ["store.outward.approve", "store.outward.post"], [w.store])
    assert portal.post("%s/issues/%d/approve" % (O, i["id"])).status_code == 200
    assert portal.post("%s/issues/%d/post" % (O, i["id"])).status_code == 200
