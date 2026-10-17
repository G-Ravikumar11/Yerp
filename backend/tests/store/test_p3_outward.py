"""P3: outward - issues to a project or a subcontractor, returns, returnables, write-off requests, subcontractor recovery."""
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
import pytest

from app import db as database, models
from app.models.store_core import (
    DBStore, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion, DBStoreUserAssignment, MovementType,
)
from app.models.store_outward import DBStoreIssue
from app.services import store_outward
from app.services.stock_ledger import freeze_store, get_balance, post_movement, unfreeze_store

from conftest import make_employee

D = Decimal
API = "/api/store/outward"
TODAY = date.today().isoformat()


@pytest.fixture(autouse=True)
def _leave_no_stock_behind():
    """The suite empties the item master between tests, freeing item ids for reuse: clear what points at them."""
    yield
    with database.SessionLocal() as s:
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreItemSettings, DBStoreUomConversion):
            s.query(model).delete(synchronize_session=False)
        s.commit()


class W:
    pass


def world(account):
    """A company with a project (BOQ of two items, a work order), a second project, a store holding stock, a subcontractor."""
    w = W()
    with database.SessionLocal() as s:
        client = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first()
        tag = uuid.uuid4().hex[:6]
        w.client_id = client.id
        job = models.DBJob(client_id=client.id, number="P-" + tag, name="Tower A")
        other = models.DBJob(client_id=client.id, number="Q-" + tag, name="Tower B")
        s.add_all([job, other])
        s.flush()
        w.project, w.other_project = job.id, other.id
        boq = models.DBBoq(client_id=client.id, job_id=job.id, number="B-" + tag, title="Tower A")
        s.add(boq)
        s.flush()
        rev = models.DBBoqRevision(boq_id=boq.id, rev_no=boq.current_rev or 0, label="R0")
        s.add(rev)
        s.flush()
        w.boq = []
        for i, (d, u) in enumerate((("RCC M25 in columns", "cum"), ("Brick masonry", "cum")), 1):
            line = models.DBBoqLine(boq_id=boq.id, revision_id=rev.id, key="k%d" % i, kind="item", item_no=str(i), description=d, uom=u, quantity=10, rate=100.0, amount=1000.0, display_order=i)
            s.add(line)
            s.flush()
            w.boq.append(line.id)
        oboq = models.DBBoq(client_id=client.id, job_id=other.id, number="C-" + tag, title="Tower B")
        s.add(oboq)
        s.flush()
        orev = models.DBBoqRevision(boq_id=oboq.id, rev_no=0, label="R0")
        s.add(orev)
        s.flush()
        oline = models.DBBoqLine(boq_id=oboq.id, revision_id=orev.id, key="o1", kind="item", item_no="1", description="Elsewhere", uom="cum", quantity=1, rate=1.0, amount=1.0)
        s.add(oline)
        s.flush()
        w.other_boq = oline.id
        wo = models.DBWorkOrder(client_id=client.id, job_id=job.id, number="WO-" + tag, status="Approved", boq_id=boq.id)
        s.add(wo)
        con = models.DBContractor(client_id=client.id, vendor_code="V-" + tag, company_name="Sai Steel Fixers")
        s.add(con)
        s.flush()
        order = models.DBSubcontractOrder(client_id=client.id, wo_number="SWO-" + tag, status="ACTIVE", contractor_id=con.id, job_id=job.id, subject="Shuttering and steel fixing")
        s.add(order)
        cs = DBStore(client_id=client.id, code="C" + tag[:3].upper(), name="Central", type="CENTRAL")
        st = DBStore(client_id=client.id, code="S" + tag[:3].upper(), name="Site", type="SITE", project_id=job.id)
        s.add_all([cs, st])
        s.flush()
        w.wo, w.contractor, w.central, w.site, w.sub_order = wo.id, con.id, cs.id, st.id, order.id
        w.item = {}
        for key, name, uom, cat, qty, rate, conv in (("cement", "Cement OPC", "kg", "CONSUMABLE", 5000, "7", {"bag": 50}), ("plate", "Shuttering Plate", "nos", "RETURNABLE", 100, "450", {}),
                                                      ("helmet", "Safety Helmet", "nos", "CONSUMABLE", 60, "180", {})):
            it = models.DBItem(client_id=client.id, kind="RM", item_code="OU-%s-%s" % (key.upper(), tag), item_name=name, units_of_measure=uom)
            s.add(it)
            s.flush()
            w.item[key] = it.id
            s.add(DBStoreItemSettings(item_id=it.id, category=cat, base_uom=uom))
            s.add_all([DBStoreUomConversion(item_id=it.id, from_uom=u, to_base_factor=f) for u, f in conv.items()])
            post_movement(s, movement_type=MovementType.OPENING_IN, store_id=cs.id, item_id=it.id, qty=D(qty), rate=D(rate), txn_date=date.today() - timedelta(days=30), project_id=None,
                          ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        emp = models.DBEmployee(client_id=client.id, first_name="Ravi", last_name="Kumar", email="ravi-%s@example.com" % tag)
        s.add(emp)
        s.flush()
        w.employee = emp.id
        w.closed_wo = None
        s.commit()
    return w


def staff(account, portal, rights, store_ids=()):
    email = "p3-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = ",".join(rights)
        s.add_all([DBStoreUserAssignment(store_id=i, employee_id=row.id) for i in store_ids])
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
    return emp


def issue_body(w, lines=None, **over):
    lines = lines if lines is not None else [{"item_id": w.item["cement"], "qty": "10", "uom": "bag", "boq_item_id": w.boq[0]}]
    return {"store_id": w.central, "issue_date": TODAY, "issue_type": "SITE", "project_id": w.project, "work_order_id": w.wo, "purpose": "Column casting", "received_by_type": "FOREMAN",
            "received_by_name": "Suresh (foreman)", "lines": lines, **over}


def make_issue(tenant, w, **kw):
    res = tenant.post(API + "/issue", json=issue_body(w, **kw))
    assert res.status_code == 200, res.text
    return res.json()


def move(tenant, kind, doc_id, *steps):
    last = None
    for step in steps:
        res = tenant.post("%s/%s/%d/%s" % (API, kind, doc_id, step), json={"reason": "wrong site"} if step == "cancel" else None)
        assert res.status_code == 200, (step, res.text)
        last = res.json()
    return last


def balance(w, store, key):
    with database.SessionLocal() as s:
        b = get_balance(s, store, w.item[key])
        return b.qty, b.value


def posted_issue(tenant, w, **kw):
    i = make_issue(tenant, w, **kw)
    return move(tenant, "issue", i["id"], "submit", "approve", "post")


# --- the happy path ---------------------------------------------------------------------------------------------------

def test_an_issue_runs_draft_to_posted_and_stock_leaves_only_at_the_end(account):
    tenant = account["client"]
    w = world(account)
    i = make_issue(tenant, w)
    assert i["status"] == "DRAFT" and i["number"].startswith("ISSUE/") and i["issue_type"] == "SITE"
    assert i["lines"][0]["qty"] == "500.000" and i["lines"][0]["entry_qty"] == "10.000" and i["lines"][0]["entry_uom"] == "bag"
    assert i["lines"][0]["boq_item"].startswith("1 RCC M25")
    for step, status in (("submit", "SUBMITTED"), ("approve", "APPROVED")):
        assert move(tenant, "issue", i["id"], step)["status"] == status
        assert balance(w, w.central, "cement")[0] == D("5000.000")                    # nothing moves before posting
    posted = move(tenant, "issue", i["id"], "post")
    assert posted["status"] == "POSTED" and posted["posted_at"]
    assert balance(w, w.central, "cement") == (D("4500.000"), D("31500.00"))          # 500 kg at the average of 7
    with database.SessionLocal() as s:
        row = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "ISSUE", DBStoreStockLedger.ref_doc_id == i["id"]).one()
        assert (row.movement_type, row.qty_out, row.rate, row.value) == ("ISSUE_OUT", D("500.000"), D("7.0000"), D("3500.00"))
        assert (row.project_id, row.work_order_id, row.boq_item_id, row.cost_head) == (w.project, w.wo, w.boq[0], None)
    assert [h["action"] for h in posted["history"]] == ["create", "submit", "approve", "post"] and all(h["by"] for h in posted["history"])
    assert tenant.get(API + "/issue", params={"status": "POSTED", "project_id": w.project}).json()["total"] == 1
    assert tenant.get(API).json()["slice"] == "outward"


def test_an_issue_can_be_charged_to_a_cost_head_instead_of_a_boq_item(account):
    tenant = account["client"]
    w = world(account)
    posted_issue(tenant, w, lines=[{"item_id": w.item["helmet"], "qty": "5", "cost_head": "safety"}])
    with database.SessionLocal() as s:
        row = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "ISSUE").one()
        assert (row.cost_head, row.boq_item_id, row.qty_out, row.value) == ("SAFETY", None, D("5.000"), D("900.00"))


def test_the_lifecycle_cannot_be_skipped_and_only_drafts_change(account):
    tenant = account["client"]
    w = world(account)
    i = make_issue(tenant, w)
    for step in ("approve", "post"):
        assert tenant.post("%s/issue/%d/%s" % (API, i["id"], step)).status_code == 409
    assert tenant.post("%s/issue/%d/nonsense" % (API, i["id"])).status_code == 404
    edited = tenant.put("%s/issue/%d" % (API, i["id"]), json=issue_body(w, lines=[{"item_id": w.item["cement"], "qty": "4", "uom": "bag", "boq_item_id": w.boq[1]}], purpose="Masonry"))
    assert edited.status_code == 200 and edited.json()["lines"][0]["qty"] == "200.000" and edited.json()["purpose"] == "Masonry"
    assert tenant.put("%s/issue/%d" % (API, i["id"]), json=issue_body(w, store_id=w.site)).status_code == 400
    move(tenant, "issue", i["id"], "submit")
    assert tenant.put("%s/issue/%d" % (API, i["id"]), json=issue_body(w)).status_code == 409
    assert tenant.delete("%s/issue/%d" % (API, i["id"])).status_code == 409
    again = make_issue(tenant, w)
    assert tenant.delete("%s/issue/%d" % (API, again["id"])).status_code == 200
    assert tenant.get("%s/issue/%d" % (API, again["id"])).status_code == 404


# --- stock ---------------------------------------------------------------------------------------------------------------

def test_an_issue_cannot_take_more_than_is_on_hand(account):
    tenant = account["client"]
    w = world(account)
    big = make_issue(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "101", "uom": "bag", "boq_item_id": w.boq[0]}])          # 5050 kg, 5000 on hand
    res = tenant.post("%s/issue/%d/submit" % (API, big["id"]))
    assert res.status_code == 409 and "Only 5000.000 kg of Cement OPC on hand" in res.json()["detail"]
    assert tenant.get("%s/issue/%d" % (API, big["id"])).json()["status"] == "DRAFT"
    # two lines of the same item add up
    two = make_issue(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "60", "uom": "bag", "boq_item_id": w.boq[0]}, {"item_id": w.item["cement"], "qty": "60", "uom": "bag", "boq_item_id": w.boq[1]}])
    assert tenant.post("%s/issue/%d/submit" % (API, two["id"])).status_code == 409


def test_stock_used_between_submit_and_post_stops_the_post_and_changes_nothing(account):
    tenant = account["client"]
    w = world(account)
    i = make_issue(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "90", "uom": "bag", "boq_item_id": w.boq[0]}])        # 4500 kg
    move(tenant, "issue", i["id"], "submit", "approve")
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.central, item_id=w.item["cement"], qty=D("1000"), rate=None, txn_date=date.today(), project_id=None,
                      ref_doc_type="ISSUE", ref_doc_id=999, ref_line_id=1, user_id=None)
        s.commit()
    res = tenant.post("%s/issue/%d/post" % (API, i["id"]))
    assert res.status_code == 409 and "4000.000 on hand" in res.json()["detail"]
    assert tenant.get("%s/issue/%d" % (API, i["id"])).json()["status"] == "APPROVED"
    assert balance(w, w.central, "cement")[0] == D("4000.000")


def test_a_frozen_store_refuses_the_post(account):
    tenant = account["client"]
    w = world(account)
    i = make_issue(tenant, w)
    move(tenant, "issue", i["id"], "submit", "approve")
    with database.SessionLocal() as s:
        freeze_store(s, w.central, "annual count", None)
        s.commit()
    res = tenant.post("%s/issue/%d/post" % (API, i["id"]))
    assert res.status_code == 423 and tenant.get("%s/issue/%d" % (API, i["id"])).json()["status"] == "APPROVED"
    with database.SessionLocal() as s:
        unfreeze_store(s, w.central, None)
        s.commit()
    assert move(tenant, "issue", i["id"], "post")["status"] == "POSTED"


# --- what is typed ------------------------------------------------------------------------------------------------------

def test_bad_issues_are_refused_in_words(account):
    tenant = account["client"]
    w = world(account)
    c, p = w.item["cement"], w.item["plate"]
    bad = [
        ({"lines": []}, "at least one line"),
        ({"lines": [{"item_id": c, "qty": "5", "uom": "bag"}]}, "where the cost goes"),
        ({"lines": [{"item_id": c, "qty": "5", "uom": "bag", "boq_item_id": w.boq[0], "cost_head": "SAFETY"}]}, "not both"),
        ({"lines": [{"item_id": c, "qty": "5", "uom": "bag", "cost_head": "LUNCH"}]}, "cost head must be"),
        ({"lines": [{"item_id": c, "qty": "5", "uom": "bag", "boq_item_id": w.other_boq}]}, "not one of this project"),
        ({"lines": [{"item_id": c, "qty": "0", "uom": "bag", "boq_item_id": w.boq[0]}]}, "more than zero"),
        ({"lines": [{"item_id": c, "qty": "5", "uom": "furlong", "boq_item_id": w.boq[0]}]}, "No conversion"),
        ({"lines": [{"item_id": 999999, "qty": "5", "boq_item_id": w.boq[0]}]}, "not a stock item"),
        ({"lines": [{"item_id": c, "qty": "5", "uom": "bag", "boq_item_id": w.boq[0]}] * 2}, "twice"),
        ({"lines": [{"item_id": c, "qty": "5", "uom": "bag", "cost_head": "SAFETY", "expected_return_date": "2030-01-01"}]}, "only returnable"),
        ({"lines": [{"item_id": c, "qty": "5", "uom": "bag", "cost_head": "SAFETY", "chargeable": True, "recovery_basis": "CONTRACT_RATE", "recovery_rate": "7"}]}, "subcontractor"),
        ({"project_id": 999999}, "project"),
        ({"project_id": w.other_project}, "work order is not one of this project"),
        ({"work_order_id": 999999}, "work order"),
        ({"issue_type": "GIFT"}, "SITE use"),
        ({"issue_type": "SUBCONTRACTOR"}, "subcontractor the material"),
        ({"issue_type": "SUBCONTRACTOR", "subcontractor_id": w.contractor}, "subcontract work order"),
        ({"issue_date": "2999-01-01"}, "future"),
        ({"issue_date": "nope"}, "not a date"),
        ({"store_id": 999999}, "store does not exist"),
        ({"received_by_type": "ALIEN"}, "who received the material"),
        ({"received_by_name": " "}, "name of who received the material"),
        ({"received_by_employee_id": 999999}, "employee does not exist"),
    ]
    for over, word in bad:
        res = tenant.post(API + "/issue", json=issue_body(w, **over))
        assert res.status_code in (400, 409) and word.lower() in res.json()["detail"].lower(), (over, res.text)
    assert tenant.get(API + "/issue").json()["total"] == 0


# --- cancel -------------------------------------------------------------------------------------------------------------

def test_cancelling_needs_a_reason_and_a_posted_issue_goes_back_into_stock(account):
    tenant = account["client"]
    w = world(account)
    i = make_issue(tenant, w)
    assert tenant.post("%s/issue/%d/cancel" % (API, i["id"]), json={"reason": " "}).status_code == 400
    done = move(tenant, "issue", i["id"], "cancel")
    assert done["status"] == "CANCELLED" and done["cancel_reason"] == "wrong site" and balance(w, w.central, "cement")[0] == D("5000.000")
    assert tenant.post("%s/issue/%d/cancel" % (API, i["id"]), json={"reason": "again"}).status_code == 409
    j = posted_issue(tenant, w)
    assert balance(w, w.central, "cement")[0] == D("4500.000")
    assert move(tenant, "issue", j["id"], "cancel")["status"] == "CANCELLED"
    assert balance(w, w.central, "cement") == (D("5000.000"), D("35000.00"))
    with database.SessionLocal() as s:
        rows = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "ISSUE", DBStoreStockLedger.ref_doc_id == j["id"]).order_by(DBStoreStockLedger.id).all()
        assert len(rows) == 2 and rows[1].reversal_of_id == rows[0].id and rows[1].qty_in == D("500.000")


# --- returns, returnables and write-offs --------------------------------------------------------------------------------

def returnable_issue(tenant, w, qty="40", due=None, holder=None, issued=None):
    return posted_issue(tenant, w, lines=[{"item_id": w.item["plate"], "qty": qty, "boq_item_id": w.boq[0], "expected_return_date": due or ""}],
                        **(holder or {"received_by_type": "PERSON", "received_by_employee_id": w.employee}), **({"issue_date": issued} if issued else {}))


def test_returned_material_goes_back_at_the_rate_it_left_at(account):
    tenant = account["client"]
    w = world(account)
    i = posted_issue(tenant, w)                                                           # 500 kg cement at 7
    il = i["lines"][0]
    assert tenant.get(API + "/issue-lines/%d" % i["id"]).json()["lines"][0]["outstanding"] == "500.000"
    ret = tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": il["id"], "qty_returned": "2", "uom": "bag"}]})
    assert ret.status_code == 200, ret.text
    r = ret.json()
    assert r["number"].startswith("ISSRET/") and r["issue_number"] == i["number"] and r["lines"][0]["qty_returned"] == "100.000"
    move(tenant, "returns", r["id"], "submit", "approve", "post")
    assert balance(w, w.central, "cement") == (D("4600.000"), D("32200.00"))
    with database.SessionLocal() as s:
        row = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "ISSRET").one()
        assert (row.movement_type, row.qty_in, row.rate, row.boq_item_id, row.project_id) == ("ISSUE_RETURN_IN", D("100.000"), D("7.0000"), w.boq[0], w.project)
    assert tenant.get(API + "/issue-lines/%d" % i["id"]).json()["lines"][0]["outstanding"] == "400.000"
    # the issue cannot be cancelled while a live return stands on it
    res = tenant.post("%s/issue/%d/cancel" % (API, i["id"]), json={"reason": "no longer needed"})
    assert res.status_code == 409 and r["number"] in res.json()["detail"]
    move(tenant, "returns", r["id"], "cancel")
    assert balance(w, w.central, "cement")[0] == D("4500.000")
    assert move(tenant, "issue", i["id"], "cancel")["status"] == "CANCELLED"


def test_a_return_cannot_exceed_what_is_still_out(account):
    tenant = account["client"]
    w = world(account)
    i = posted_issue(tenant, w)                                                           # 10 bags
    il = i["lines"][0]["id"]
    body = lambda qty, **k: {"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": il, "qty_returned": qty, "uom": "bag", **k}]}     # noqa: E731
    assert tenant.post(API + "/returns", json=body("11")).status_code == 409
    assert tenant.post(API + "/returns", json=body("0")).status_code == 400
    assert tenant.post(API + "/returns", json=body("abc")).status_code == 400
    assert tenant.post(API + "/returns", json=body("1", qty_lost="1", reason="gone")).status_code == 400        # consumables are used up, not written off
    first = tenant.post(API + "/returns", json=body("6")).json()
    move(tenant, "returns", first["id"], "submit")
    second = tenant.post(API + "/returns", json=body("5"))
    assert second.status_code == 409 and "already on a return" in second.json()["detail"]
    assert tenant.post(API + "/returns", json=body("4")).status_code == 200
    draft = make_issue(tenant, w)
    res = tenant.post(API + "/returns", json={"issue_id": draft["id"], "return_date": TODAY, "lines": [{"issue_line_id": draft["lines"][0]["id"], "qty_returned": "1", "uom": "bag"}]})
    assert res.status_code == 409 and "posted issue" in res.json()["detail"]


def test_lost_tools_raise_write_off_requests_and_stop_counting_as_out(account):
    tenant = account["client"]
    w = world(account)
    due = (date.today() - timedelta(days=5)).isoformat()
    i = returnable_issue(tenant, w, "40", due=due, issued=(date.today() - timedelta(days=20)).isoformat())
    il = i["lines"][0]["id"]
    out = tenant.get(API + "/returnables").json()
    assert out["total"] == 1 and out["overdue"] == 1 and out["items"][0]["qty_outstanding"] == "40.000" and out["items"][0]["overdue_days"] == 5
    assert out["items"][0]["holder_name"] == "Ravi Kumar" and out["items"][0]["holder_type"] == "EMPLOYEE" and out["items"][0]["expected_return_date"] == due
    assert tenant.get(API + "/returnables", params={"overdue_only": True}).json()["total"] == 1
    assert tenant.get(API + "/returnables", params={"project_id": w.other_project}).json()["total"] == 0
    r = tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": il, "qty_returned": "30", "qty_lost": "6", "reason": "fell from scaffold"}]})
    assert r.status_code == 200, r.text
    assert tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": il, "qty_lost": "6"}]}).status_code == 400     # lost needs a reason
    rid = r.json()["id"]
    move(tenant, "returns", rid, "submit", "approve", "post")
    assert balance(w, w.central, "plate")[0] == D("90.000")                                # 100 - 40 + 30: the lost 6 are not back
    assert tenant.get(API + "/returnables").json()["items"][0]["qty_outstanding"] == "4.000"
    wo = tenant.get(API + "/writeoffs").json()["items"]
    assert len(wo) == 1 and (wo[0]["qty"], wo[0]["status"], wo[0]["item_name"], wo[0]["reason"]) == ("6.000", "OPEN", "Shuttering Plate", "fell from scaffold")
    with database.SessionLocal() as s:
        assert [(x.request_id, x.qty, x.status) for x in store_outward.list_writeoff_requests(s)][-1][1:] == (D("6.000"), "OPEN")
    # cancelling the return withdraws its request and brings the tools back out
    move(tenant, "returns", rid, "cancel")
    assert tenant.get(API + "/writeoffs").json()["items"] == [] and balance(w, w.central, "plate")[0] == D("60.000")
    assert tenant.get(API + "/writeoffs", params={"status": "WITHDRAWN"}).json()["items"][0]["status"] == "WITHDRAWN"


def test_a_return_whose_write_off_was_dealt_with_cannot_be_cancelled(account):
    tenant = account["client"]
    w = world(account)
    i = returnable_issue(tenant, w, "10")
    r = tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": i["lines"][0]["id"], "qty_lost": "3", "reason": "stolen"}]}).json()
    move(tenant, "returns", r["id"], "submit", "approve", "post")
    request_id = tenant.get(API + "/writeoffs").json()["items"][0]["id"]
    with database.SessionLocal() as s:
        store_outward.close_writeoff_request(s, request_id, "SCRAP", 5, None)
        s.commit()
        with pytest.raises(Exception):
            store_outward.close_writeoff_request(s, request_id, "SCRAP", 6, None)          # only once
    res = tenant.post("%s/returns/%d/cancel" % (API, r["id"]), json={"reason": "my mistake"})
    assert res.status_code == 409 and "already been dealt with" in res.json()["detail"]
    closed = tenant.get(API + "/writeoffs", params={"status": "CLOSED"}).json()["items"][0]
    assert closed["closed_ref"] == "SCRAP #5"


def test_outstanding_returnables_for_the_contract(account):
    tenant = account["client"]
    w = world(account)
    returnable_issue(tenant, w, "20", due=(date.today() + timedelta(days=10)).isoformat(), holder={"received_by_type": "GANG", "received_by_name": "Mason gang 2"})
    posted_issue(tenant, w)                                                               # cement: a consumable, never "returnable"
    with database.SessionLocal() as s:
        rows = store_outward.get_outstanding_returnables(s, project_id=w.project)
        assert len(rows) == 1 and rows[0].qty_outstanding == D("20.000") and (rows[0].holder_type, rows[0].holder_id, rows[0].overdue_days) == ("GANG", 0, 0)
        assert store_outward.get_outstanding_returnables(s, project_id=w.other_project) == []
        assert len(store_outward.get_outstanding_returnables(s, store_id=w.central)) == 1


# --- subcontractors -----------------------------------------------------------------------------------------------------------

def test_material_issued_to_a_subcontractor_is_recovered_net_of_what_comes_back(account):
    tenant = account["client"]
    w = world(account)
    line = {"item_id": w.item["cement"], "qty": "20", "uom": "bag", "chargeable": True, "recovery_basis": "CONTRACT_RATE", "recovery_rate": "8"}      # 1000 kg at Rs 8
    sub = dict(issue_type="SUBCONTRACTOR", subcontractor_id=w.contractor, subcontract_order_id=w.sub_order)
    bad = tenant.post(API + "/issue", json=issue_body(w, **sub, lines=[{**line, "recovery_rate": ""}]))
    assert bad.status_code == 400 and "contract rate" in bad.json()["detail"]
    i = posted_issue(tenant, w, **sub, lines=[line])
    assert i["issue_type"] == "SUBCONTRACTOR" and i["holder_type"] == "SUBCONTRACTOR" and i["holder_name"] == "Sai Steel Fixers" and i["subcontract_order"].startswith("SWO-")
    assert i["lines"][0]["resolved_rate"] == "8.000" and i["received_by_name"] == "Suresh (foreman)"
    with database.SessionLocal() as s:
        assert s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "ISSUE").one().movement_type == "SUBCON_ISSUE_OUT"
        got = store_outward.get_subcon_issues(s, w.contractor, date.today())
        assert len(got) == 1 and (got[0].qty_issued, got[0].qty_returned, got[0].chargeable, got[0].recovery_rate, got[0].recovery_value) == (D("1000.000"), D("0.000"), True, D("8.000"), D("8000.00"))
        assert store_outward.get_subcon_issues(s, w.contractor, date.today() - timedelta(days=1)) == []
        assert store_outward.get_subcon_issues(s, w.contractor + 1000, date.today()) == []
    r = tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": i["lines"][0]["id"], "qty_returned": "5", "uom": "bag"}]}).json()
    move(tenant, "returns", r["id"], "submit", "approve", "post")
    with database.SessionLocal() as s:
        assert s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "ISSRET").one().movement_type == "SUBCON_RETURN_IN"
    stmt = tenant.get(API + "/subcontractors/%d/recovery" % w.contractor).json()
    assert stmt["total_recovery"] == "6000.00" and stmt["items"][0]["qty_returned"] == "250.000" and stmt["items"][0]["recovery_value"] == "6000.00"
    assert tenant.get(API + "/subcontractors/999999/recovery").status_code == 404


# --- direct issue --------------------------------------------------------------------------------------------------------------

def test_a_direct_issue_does_everything_in_one_step_and_needs_its_own_right(account, portal):
    tenant = account["client"]
    w = world(account)
    staff(account, portal, ["store.outward.view", "store.outward.create", "store.outward.post"], [w.central])
    assert portal.post(API + "/issue/direct", json=issue_body(w)).status_code == 403          # create and post are not enough
    res = portal.post(API + "/issue", json=issue_body(w))
    assert res.status_code == 403 and "indent" in res.json()["detail"]                        # ... nor to issue without an indent
    owner = tenant.post(API + "/issue/direct", json=issue_body(w))
    assert owner.status_code == 200, owner.text
    d = owner.json()
    assert d["status"] == "POSTED" and d["direct"] is True and [h["action"] for h in d["history"]] == ["create", "submit", "approve", "post", "direct"]
    assert balance(w, w.central, "cement")[0] == D("4500.000")


def test_a_member_of_staff_with_the_direct_issue_right_can_issue_in_one_step(account, portal):
    w = world(account)
    staff(account, portal, ["store.outward.direct_issue"], [w.central])                       # that one right alone: no view, create or post
    res = portal.post(API + "/issue/direct", json=issue_body(w))
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["status"] == "POSTED" and d["direct"] is True and d["history"][0]["by"]
    assert balance(w, w.central, "cement")[0] == D("4500.000")
    assert portal.get(API + "/issue").status_code == 403                                      # it does not let them read the lists
    other = staff(account, portal, ["store.outward.direct_issue"], [])                         # no store assigned: wrong-store access
    assert portal.post(API + "/issue/direct", json=issue_body(w)).status_code == 403 and other["id"]


def test_a_direct_issue_that_cannot_move_stock_leaves_nothing_behind(account):
    tenant = account["client"]
    w = world(account)
    res = tenant.post(API + "/issue/direct", json=issue_body(w, lines=[{"item_id": w.item["cement"], "qty": "101", "uom": "bag", "boq_item_id": w.boq[0]}]))
    assert res.status_code == 409 and "on hand" in res.json()["detail"]
    assert tenant.get(API + "/issue").json()["total"] == 0 and balance(w, w.central, "cement")[0] == D("5000.000")
    with database.SessionLocal() as s:
        assert s.query(DBStoreIssue).filter(DBStoreIssue.client_id == w.client_id).count() == 0


# --- rights and tenancy -----------------------------------------------------------------------------------------------------------

def test_each_step_needs_its_own_right(account, portal):
    tenant = account["client"]
    w = world(account)
    i = make_issue(tenant, w)
    staff(account, portal, ["store.outward.view", "store.outward.create"], [w.central])
    assert portal.post("%s/issue/%d/submit" % (API, i["id"])).status_code == 200
    for step in ("approve", "post"):
        assert portal.post("%s/issue/%d/%s" % (API, i["id"], step)).status_code == 403
    assert portal.post("%s/issue/%d/cancel" % (API, i["id"]), json={"reason": "no"}).status_code == 403


def test_a_viewer_can_look_but_not_make(account, portal):
    tenant = account["client"]
    w = world(account)
    i = make_issue(tenant, w)
    staff(account, portal, ["store.outward.view"], [w.central])
    assert portal.get(API + "/issue").json()["total"] == 1 and portal.get("%s/issue/%d" % (API, i["id"])).status_code == 200
    assert portal.get(API + "/returnables").status_code == 200 and portal.get(API + "/writeoffs").status_code == 200
    assert portal.post(API + "/issue", json=issue_body(w)).status_code == 403
    assert portal.put("%s/issue/%d" % (API, i["id"]), json=issue_body(w)).status_code == 403
    assert portal.delete("%s/issue/%d" % (API, i["id"])).status_code == 403
    assert portal.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": []}).status_code == 403


def test_staff_work_only_in_their_own_stores(account, portal):
    tenant = account["client"]
    w = world(account)
    at_central = make_issue(tenant, w)
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.OPENING_IN, store_id=w.site, item_id=w.item["cement"], qty=D("1000"), rate=D("7"), txn_date=date.today() - timedelta(days=2), project_id=None,
                      ref_doc_type="OPENING", ref_doc_id=2, ref_line_id=None, user_id=None)
        s.commit()
    at_site = make_issue(tenant, w, store_id=w.site)
    staff(account, portal, ["store.outward.view", "store.outward.create", "store.outward.post", "store.outward.direct_issue"], [w.site])
    assert [d["number"] for d in portal.get(API + "/issue").json()["items"]] == [at_site["number"]]
    assert portal.get("%s/issue/%d" % (API, at_central["id"])).status_code == 403
    assert portal.post("%s/issue/%d/submit" % (API, at_central["id"])).status_code == 403
    assert portal.post(API + "/issue", json=issue_body(w)).status_code == 403                  # wrong-store access
    assert portal.get(API + "/issue", params={"store_id": w.central}).status_code == 403
    assert portal.get("%s/issue/%d/print" % (API, at_central["id"])).status_code == 403
    assert portal.post(API + "/issue", json=issue_body(w, store_id=w.site)).status_code == 200


def test_one_company_cannot_reach_anothers_documents(account, second_tenant):
    tenant = account["client"]
    w = world(account)
    i = make_issue(tenant, w)
    assert second_tenant.get("%s/issue/%d" % (API, i["id"])).status_code == 404
    assert second_tenant.post("%s/issue/%d/submit" % (API, i["id"])).status_code == 404
    assert second_tenant.get("%s/issue/%d/print" % (API, i["id"])).status_code == 404
    assert second_tenant.get(API + "/issue").json()["total"] == 0
    assert second_tenant.post(API + "/issue", json=issue_body(w)).status_code == 400
    assert second_tenant.get(API + "/returnables").json()["total"] == 0 and second_tenant.get(API + "/writeoffs").json()["items"] == []
    assert second_tenant.get(API + "/pick/boq-items", params={"project_id": w.project}).json()["items"] == []
    assert second_tenant.get(API + "/subcontractors/%d/recovery" % w.contractor).status_code == 404
    assert second_tenant.get(API + "/nonsense").status_code == 404


# --- pickers, printing and exports ---------------------------------------------------------------------------------------------

def test_the_pickers_offer_the_projects_own_things(account):
    tenant = account["client"]
    w = world(account)
    boq = tenant.get(API + "/pick/boq-items", params={"project_id": w.project}).json()["items"]
    assert [b["id"] for b in boq] == w.boq and boq[0]["description"] == "RCC M25 in columns"
    assert [b["id"] for b in tenant.get(API + "/pick/boq-items", params={"project_id": w.project, "q": "brick"}).json()["items"]] == [w.boq[1]]
    assert [x["id"] for x in tenant.get(API + "/pick/work-orders", params={"project_id": w.project}).json()["items"]] == [w.wo]
    assert tenant.get(API + "/pick/work-orders", params={"project_id": w.other_project}).json()["items"] == []
    assert [x["id"] for x in tenant.get(API + "/pick/subcontractors", params={"q": "sai"}).json()["items"]] == [w.contractor]
    assert w.employee in [x["id"] for x in tenant.get(API + "/pick/employees").json()["items"]]


def test_every_document_prints_and_the_lists_export(account):
    tenant = account["client"]
    w = world(account)
    i = posted_issue(tenant, w)
    draft = make_issue(tenant, w)
    sub = posted_issue(tenant, w, issue_type="SUBCONTRACTOR", subcontractor_id=w.contractor, subcontract_order_id=w.sub_order, lines=[{"item_id": w.item["cement"], "qty": "1", "uom": "bag", "chargeable": True, "recovery_basis": "CONTRACT_RATE", "recovery_rate": "8"}])
    ret = tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": i["lines"][0]["id"], "qty_returned": "1", "uom": "bag"}]}).json()
    for kind, doc in (("issue", i), ("issue", draft), ("issue", sub), ("returns", ret)):
        res = tenant.get("%s/%s/%d/print" % (API, kind, doc["id"]))
        assert res.status_code == 200 and res.content[:4] == b"%PDF", (kind, res.text[:200])
    for path in ("/issue/export", "/returns/export", "/returnables/export"):
        xl = tenant.get(API + path)
        assert xl.status_code == 200 and "spreadsheetml" in xl.headers["content-type"] and openpyxl.load_workbook(io.BytesIO(xl.content)).active.max_row >= 1


# =====================================================================================================================================
# The fuller outward spec: indents, closed work orders, recovery rates, damaged returns, closing returnables, gate passes, norm warnings
# =====================================================================================================================================

def indent_body(w, lines=None, **over):
    lines = lines if lines is not None else [{"item_id": w.item["cement"], "qty": "20", "uom": "bag", "purpose": "Column casting"}]
    return {"store_id": w.central, "required_by": (date.today() + timedelta(days=3)).isoformat(), "project_id": w.project, "work_order_id": w.wo, "boq_item_id": w.boq[0],
            "activity": "Columns, block 2", "lines": lines, **over}


def make_indent(tenant, w, **kw):
    res = tenant.post(API + "/indent", json=indent_body(w, **kw))
    assert res.status_code == 200, res.text
    return res.json()


def approved_indent(tenant, w, approve=None, **kw):
    i = make_indent(tenant, w, **kw)
    assert tenant.post("%s/indent/%d/submit" % (API, i["id"])).status_code == 200
    res = tenant.post("%s/indent/%d/approve" % (API, i["id"]), json=approve or {})
    assert res.status_code == 200, res.text
    return res.json()


def against(w, indent, qty="10", **over):
    line = indent["lines"][0]
    return issue_body(w, indent_id=indent["id"], lines=[{"item_id": w.item["cement"], "qty": qty, "uom": "bag", "indent_line_id": line["id"]}], **over)


def test_an_indent_is_raised_submitted_and_approved_with_quantities_the_approver_may_cut(account):
    tenant = account["client"]
    w = world(account)
    i = make_indent(tenant, w)
    assert i["status"] == "DRAFT" and i["number"].startswith("INDENT/") and i["lines"][0]["qty"] == "1000.000" and i["lines"][0]["approved_qty"] is None and i["activity"] == "Columns, block 2"
    assert i["boq_item"].startswith("1 RCC") and i["work_order"].startswith("WO-") and i["requested_by"]
    assert tenant.post("%s/indent/%d/approve" % (API, i["id"])).status_code == 409                    # not before it is submitted
    sub = tenant.post("%s/indent/%d/submit" % (API, i["id"])).json()
    assert sub["status"] == "SUBMITTED"
    line = sub["lines"][0]
    assert tenant.post("%s/indent/%d/approve" % (API, i["id"]), json={"lines": [{"line_id": line["id"], "approved_qty": "25", "uom": "bag"}]}).status_code == 409       # cannot be raised
    assert tenant.post("%s/indent/%d/approve" % (API, i["id"]), json={"lines": [{"line_id": line["id"], "approved_qty": "0"}]}).status_code == 400                    # not cut to nothing
    assert tenant.post("%s/indent/%d/approve" % (API, i["id"]), json={"lines": [{"line_id": 999999, "approved_qty": "1"}]}).status_code == 400
    ok_ = tenant.post("%s/indent/%d/approve" % (API, i["id"]), json={"lines": [{"line_id": line["id"], "approved_qty": "15", "uom": "bag"}], "remarks": "only 15 bags this week"})
    assert ok_.status_code == 200, ok_.text
    d = ok_.json()
    assert d["status"] == "OPEN" and d["approved_by"] and d["approver_remarks"] == "only 15 bags this week"
    assert (d["lines"][0]["qty"], d["lines"][0]["approved_qty"], d["lines"][0]["fulfilled"], d["lines"][0]["pending"]) == ("1000.000", "750.000", "0.000", "750.000")
    assert [h["action"] for h in d["history"]] == ["create", "submit", "approve"]
    assert tenant.put("%s/indent/%d" % (API, i["id"]), json=indent_body(w)).status_code == 409             # no longer a draft
    pend = tenant.get(API + "/indent-lines/%d" % i["id"]).json()
    assert pend["lines"][0]["pending"] == "750.000" and pend["indent"]["boq_item_id"] == w.boq[0]


def test_bad_indents_are_refused_in_words(account):
    tenant = account["client"]
    w = world(account)
    c = w.item["cement"]
    bad = [
        ({"lines": []}, "at least one line"),
        ({"lines": [{"item_id": c, "qty": "0", "uom": "bag"}]}, "more than zero"),
        ({"lines": [{"item_id": c, "qty": "1", "uom": "bag"}, {"item_id": c, "qty": "2", "uom": "bag"}]}, "twice"),
        ({"lines": [{"item_id": c, "qty": "1", "uom": "furlong"}]}, "No conversion"),
        ({"lines": [{"item_id": 999999, "qty": "1"}]}, "not a stock item"),
        ({"project_id": 999999}, "project"),
        ({"project_id": w.other_project}, "work order is not one of this project"),
        ({"boq_item_id": w.other_boq}, "not one of this project"),
        ({"work_order_id": None, "boq_item_id": None, "activity": ""}, "what the material is for"),
        ({"required_by": "2000-01-01"}, "before the indent date"),
        ({"required_by": "nope"}, "not a date"),
        ({"store_id": 999999}, "store does not exist"),
    ]
    for over, word in bad:
        res = tenant.post(API + "/indent", json=indent_body(w, **over))
        assert res.status_code in (400, 409) and word.lower() in res.json()["detail"].lower(), (over, res.text)
    assert tenant.get(API + "/indent").json()["total"] == 0


def test_issues_are_made_against_an_indent_and_fill_it_up(account):
    tenant = account["client"]
    w = world(account)
    ind = approved_indent(tenant, w, approve={"lines": []})                         # 20 bags approved as asked
    over = tenant.post(API + "/issue", json=against(w, ind, "21"))
    assert over.status_code == 409 and "still to be issued" in over.json()["detail"]
    no_line = tenant.post(API + "/issue", json=issue_body(w, indent_id=ind["id"], lines=[{"item_id": w.item["cement"], "qty": "5", "uom": "bag"}]))
    assert no_line.status_code == 400 and "choose the line of indent" in no_line.json()["detail"]
    assert tenant.post(API + "/issue", json=issue_body(w, lines=[{"item_id": w.item["cement"], "qty": "5", "uom": "bag", "boq_item_id": w.boq[0], "indent_line_id": ind["lines"][0]["id"]}])).status_code == 400
    first = tenant.post(API + "/issue", json=against(w, ind, "12")).json()
    assert first["indent_number"] == ind["number"] and first["direct"] is False and first["lines"][0]["boq_item"].startswith("1 RCC")          # the cost goes where the indent said
    second = tenant.post(API + "/issue", json=against(w, ind, "9"))
    assert second.status_code == 200                                                  # a draft reserves nothing ...
    move(tenant, "issue", first["id"], "submit", "approve", "post")
    res = tenant.post("%s/issue/%d/submit" % (API, second.json()["id"]))              # ... but 12 + 9 is more than the 20 approved, and it is checked again when it is submitted
    assert res.status_code == 409 and "Only 8.000 kg" not in res.json()["detail"] and "still to be issued on indent" in res.json()["detail"]
    assert tenant.delete("%s/issue/%d" % (API, second.json()["id"])).status_code == 200
    after = tenant.get("%s/indent/%d" % (API, ind["id"])).json()
    assert after["status"] == "PARTIAL" and after["lines"][0]["fulfilled"] == "600.000" and after["lines"][0]["pending"] == "400.000" and after["fulfilled_pct"] == 60.0
    last = tenant.post(API + "/issue", json=against(w, ind, "8")).json()
    move(tenant, "issue", last["id"], "submit", "approve", "post")
    done = tenant.get("%s/indent/%d" % (API, ind["id"])).json()
    assert done["status"] == "CLOSED" and done["lines"][0]["pending"] == "0.000" and [x["number"] for x in done["issues"]] == [first["number"], last["number"]]
    assert tenant.post(API + "/issue", json=against(w, ind, "1")).status_code == 409                    # a closed indent takes no more
    # cancelling a posted issue opens the indent again
    move(tenant, "issue", last["id"], "cancel")
    assert tenant.get("%s/indent/%d" % (API, ind["id"])).json()["status"] == "PARTIAL"
    assert tenant.post("%s/indent/%d/cancel" % (API, ind["id"]), json={"reason": "no longer needed"}).status_code == 409        # material has been issued against it


def test_an_issue_against_an_indent_needs_only_the_create_right_but_one_without_needs_direct_issue(account, portal):
    tenant = account["client"]
    w = world(account)
    ind = approved_indent(tenant, w, approve={})
    staff(account, portal, ["store.outward.view", "store.outward.create"], [w.central])
    assert portal.post(API + "/issue", json=issue_body(w)).status_code == 403
    mine = portal.post(API + "/issue", json=against(w, ind, "5"))
    assert mine.status_code == 200, mine.text
    staff(account, portal, ["store.outward.view", "store.outward.create", "store.outward.direct_issue"], [w.central])
    free = portal.post(API + "/issue", json=issue_body(w))
    assert free.status_code == 200 and free.json()["direct"] is True and free.json()["indent_number"] == ""


def test_only_the_project_manager_approves_an_indent_and_other_cancellations_follow_their_rights(account, portal):
    tenant = account["client"]
    w = world(account)
    i = make_indent(tenant, w)
    tenant.post("%s/indent/%d/submit" % (API, i["id"]))
    staff(account, portal, ["store.outward.view", "store.outward.approve"], [w.central])
    manager = make_employee(tenant, email="pm-%s@example.com" % uuid.uuid4().hex[:6], first_name="Priya", last_name="Rao", password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        s.get(models.DBJob, w.project).manager_id = manager["id"]
        s.get(models.DBEmployee, manager["id"]).extra_permissions = "store.outward.view,store.outward.approve"
        s.add(DBStoreUserAssignment(store_id=w.central, employee_id=manager["id"]))
        s.commit()
    res = portal.post("%s/indent/%d/approve" % (API, i["id"]))                                 # somebody else with the approve right
    assert res.status_code == 403 and "Priya Rao" in res.json()["detail"]
    assert portal.post("/api/employee/auth/login", json={"email": manager["email"], "password": "Crew1234"}).status_code == 200
    assert portal.post("%s/indent/%d/approve" % (API, i["id"])).status_code == 200
    # an approved indent is cancelled by a holder of the cancel right, not by the person who raised it
    assert portal.post("%s/indent/%d/cancel" % (API, i["id"]), json={"reason": "plan changed"}).status_code == 403
    assert tenant.post("%s/indent/%d/cancel" % (API, i["id"]), json={"reason": "plan changed"}).json()["status"] == "CANCELLED"
    assert tenant.post("%s/indent/%d/cancel" % (API, i["id"]), json={"reason": "again"}).status_code == 409


def test_an_indent_can_be_closed_short_cancelled_or_thrown_away(account):
    tenant = account["client"]
    w = world(account)
    ind = approved_indent(tenant, w, approve={})
    first = tenant.post(API + "/issue", json=against(w, ind, "5")).json()
    move(tenant, "issue", first["id"], "submit", "approve", "post")
    assert tenant.post("%s/indent/%d/close" % (API, ind["id"]), json={"reason": " "}).status_code == 400
    closed = tenant.post("%s/indent/%d/close" % (API, ind["id"]), json={"reason": "the rest is not needed"}).json()
    assert closed["status"] == "CLOSED" and closed["short_closed"] is True and closed["cancel_reason"] == "the rest is not needed"
    move(tenant, "issue", first["id"], "cancel")
    assert tenant.get("%s/indent/%d" % (API, ind["id"])).json()["status"] == "CLOSED"           # a short closure stays closed
    draft = make_indent(tenant, w)
    assert tenant.post("%s/indent/%d/cancel" % (API, draft["id"]), json={"reason": " "}).status_code == 400
    assert tenant.delete("%s/indent/%d" % (API, draft["id"])).status_code == 200 and tenant.get("%s/indent/%d" % (API, draft["id"])).status_code == 404
    sent = make_indent(tenant, w)
    tenant.post("%s/indent/%d/submit" % (API, sent["id"]))
    assert tenant.delete("%s/indent/%d" % (API, sent["id"])).status_code == 409
    assert tenant.post("%s/indent/%d/cancel" % (API, sent["id"]), json={"reason": "raised twice"}).json()["status"] == "CANCELLED"


def test_indent_lists_print_export_and_stay_in_their_stores(account, portal, second_tenant):
    tenant = account["client"]
    w = world(account)
    i = make_indent(tenant, w, required_by=(date.today() - timedelta(days=0)).isoformat())
    tenant.post("%s/indent/%d/submit" % (API, i["id"]))
    tenant.post("%s/indent/%d/approve" % (API, i["id"]))
    assert tenant.get(API + "/indent", params={"status": "OPEN", "project_id": w.project, "q": "columns"}).json()["total"] == 1
    assert tenant.get(API + "/indent", params={"status": "CLOSED"}).json()["total"] == 0
    for kind in ("indent", ):
        assert tenant.get("%s/%s/%d/print" % (API, kind, i["id"])).content[:4] == b"%PDF"
    assert openpyxl.load_workbook(io.BytesIO(tenant.get(API + "/indent/export").content)).active.max_row >= 2
    staff(account, portal, ["store.outward.view", "store.outward.create"], [w.site])
    assert portal.get(API + "/indent").json()["total"] == 0 and portal.get("%s/indent/%d" % (API, i["id"])).status_code == 403
    assert portal.post(API + "/indent", json=indent_body(w)).status_code == 403                  # wrong-store access
    assert second_tenant.get("%s/indent/%d" % (API, i["id"])).status_code == 404 and second_tenant.get(API + "/indent").json()["total"] == 0


def test_nothing_is_issued_or_asked_for_against_a_closed_work_order(account):
    tenant = account["client"]
    w = world(account)
    i = make_issue(tenant, w)
    move(tenant, "issue", i["id"], "submit", "approve")
    with database.SessionLocal() as s:
        s.get(models.DBWorkOrder, w.wo).status = "Closed"
        s.commit()
    res = tenant.post("%s/issue/%d/post" % (API, i["id"]))
    assert res.status_code == 409 and "is closed" in res.json()["detail"] and tenant.get("%s/issue/%d" % (API, i["id"])).json()["status"] == "APPROVED"
    assert tenant.post(API + "/issue", json=issue_body(w)).status_code == 409
    assert tenant.post(API + "/issue/direct", json=issue_body(w)).status_code == 409
    assert tenant.post(API + "/indent", json=indent_body(w)).status_code == 409
    assert tenant.post(API + "/issue", json=issue_body(w, work_order_id=None, lines=[{"item_id": w.item["cement"], "qty": "1", "uom": "bag", "cost_head": "SAFETY"}])).status_code == 200      # a cost head needs no work order


def test_an_issue_beyond_what_the_norms_allow_is_warned_about_never_blocked(account, monkeypatch):
    tenant = account["client"]
    w = world(account)
    from app.services import store_reports
    i = make_issue(tenant, w)                                                           # 500 kg to BOQ item 1
    assert i["warnings"] == []                                                          # no norm set: silent
    monkeypatch.setattr(store_reports, "get_theoretical_requirement", lambda db, boq, item: D("400") if boq == w.boq[0] else None)
    warned = tenant.get("%s/issue/%d" % (API, i["id"])).json()
    assert len(warned["warnings"]) == 1 and "500.000 kg issued in all" in warned["warnings"][0] and "400.000 kg by its norms" in warned["warnings"][0]
    assert move(tenant, "issue", i["id"], "submit", "approve", "post")["status"] == "POSTED"          # it is only a warning
    more = make_issue(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "2", "uom": "bag", "boq_item_id": w.boq[0]}])
    assert "600.000 kg issued in all" in more["warnings"][0]                            # cumulative with what was already issued
    other = make_issue(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "1", "uom": "bag", "boq_item_id": w.boq[1]}])
    assert other["warnings"] == []                                                      # another BOQ item has no norm


# --- recovery from subcontractors ---------------------------------------------------------------------------------------------------------

def sub_head(w):
    return dict(issue_type="SUBCONTRACTOR", subcontractor_id=w.contractor, subcontract_order_id=w.sub_order)


def test_the_recovery_rate_is_the_contract_rate_or_the_average_cost_plus_handling(account):
    tenant = account["client"]
    w = world(account)
    assert tenant.get(API + "/settings").json() == {"subcon_handling_pct": "0.000", "default_recovery_basis": "AVERAGE_COST"}
    cfg = tenant.put(API + "/settings", json={"subcon_handling_pct": "5", "default_recovery_basis": "average_cost"})
    assert cfg.status_code == 200 and cfg.json()["subcon_handling_pct"] == "5.000"
    lines = [{"item_id": w.item["cement"], "qty": "10", "uom": "bag", "chargeable": True},                                                      # the company's usual: average cost + its 5%
             {"item_id": w.item["steel"] if "steel" in w.item else w.item["helmet"], "qty": "2", "chargeable": True, "recovery_basis": "CONTRACT_RATE", "recovery_rate": "200", "handling_pct": "10"},
             {"item_id": w.item["plate"], "qty": "1"}]                                                                                          # free of cost
    i = posted_issue(tenant, w, lines=lines, **sub_head(w))
    by = {l["item_name"]: l for l in i["lines"]}
    assert (by["Cement OPC"]["recovery_basis"], by["Cement OPC"]["handling_pct"], by["Cement OPC"]["resolved_rate"]) == ("AVERAGE_COST", "5.000", "7.350")             # 7 x 1.05
    assert (by["Safety Helmet"]["recovery_basis"], by["Safety Helmet"]["resolved_rate"]) == ("CONTRACT_RATE", "220.000")                                             # 200 x 1.10
    assert by["Shuttering Plate"]["chargeable"] is False and by["Shuttering Plate"]["resolved_rate"] is None
    rec = tenant.get(API + "/recoveries", params={"subcontractor_id": w.contractor}).json()
    assert len(rec["items"]) == 2 and rec["total_amount"] == str((D("500") * D("7.35") + D("2") * D("220")).quantize(D("0.01")))                  # 3675.00 + 440.00
    cement = [x for x in rec["items"] if x["item_name"] == "Cement OPC"][0]
    assert (cement["source"], cement["basis"], cement["base_rate"], cement["recovery_rate"], cement["amount"]) == ("ISSUE", "AVERAGE_COST", "7.000", "7.350", "3675.00")
    with database.SessionLocal() as s:
        got = {g.item_id: g for g in store_outward.get_subcon_issues(s, w.contractor, date.today())}
        assert got[w.item["cement"]].recovery_value == D("3675.00") and got[w.item["plate"]].chargeable is False and got[w.item["plate"]].recovery_value == 0
    # a return takes off what is recovered, and cancelling it puts it back
    ret = tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": by["Cement OPC"]["id"], "qty_returned": "2", "uom": "bag"}]}).json()
    move(tenant, "returns", ret["id"], "submit", "approve", "post")
    assert [x["amount"] for x in tenant.get(API + "/recoveries").json()["items"] if x["item_name"] == "Cement OPC"] == ["2940.00"]                  # 400 kg left at 7.35
    move(tenant, "returns", ret["id"], "cancel")
    assert [x["amount"] for x in tenant.get(API + "/recoveries").json()["items"] if x["item_name"] == "Cement OPC"] == ["3675.00"]
    # cancelling the issue cancels what it was going to recover
    move(tenant, "issue", i["id"], "cancel")
    assert tenant.get(API + "/recoveries").json()["items"] == [] and tenant.get(API + "/recoveries", params={"status": "CANCELLED"}).json()["total_amount"] == "0"


def test_subcontractor_issue_rules_and_the_settings(account, portal):
    tenant = account["client"]
    w = world(account)
    line = {"item_id": w.item["cement"], "qty": "1", "uom": "bag", "chargeable": True, "recovery_basis": "CONTRACT_RATE", "recovery_rate": "8"}
    with database.SessionLocal() as s:
        other = models.DBContractor(client_id=w.client_id, vendor_code="V-X" + uuid.uuid4().hex[:4], company_name="Another Contractor")
        s.add(other)
        s.flush()
        w.other_con = other.id
        s.commit()
    for over, word in (({"subcontract_order_id": 999999}, "subcontract work order"), ({"subcontractor_id": w.other_con}, "not another contractor"[:0] or "order on this project"),
                       ({"lines": [{**line, "recovery_basis": "GUESS"}]}, "CONTRACT_RATE or the AVERAGE_COST"), ({"lines": [{**line, "handling_pct": "101"}]}, "handling percentage"),
                       ({"lines": [{**line, "handling_pct": "x"}]}, "not a number")):
        res = tenant.post(API + "/issue", json=issue_body(w, **{**sub_head(w), "lines": [line], **over}))
        assert res.status_code in (400, 409) and word.lower() in res.json()["detail"].lower(), (over, res.text)
    with database.SessionLocal() as s:
        s.get(models.DBSubcontractOrder, w.sub_order).status = "CANCELLED"
        s.commit()
    assert tenant.post(API + "/issue", json=issue_body(w, **sub_head(w), lines=[line])).status_code == 409
    assert tenant.put(API + "/settings", json={"subcon_handling_pct": "150"}).status_code == 400
    assert tenant.put(API + "/settings", json={"default_recovery_basis": "GUESS"}).status_code == 400
    staff(account, portal, ["store.outward.view", "store.outward.create"], [w.central])
    assert portal.get(API + "/settings").status_code == 200 and portal.put(API + "/settings", json={"subcon_handling_pct": "1"}).status_code == 403


# --- damaged returns ------------------------------------------------------------------------------------------------------------------------

def test_damaged_goods_come_back_into_a_bin_kept_for_them(account):
    tenant = account["client"]
    w = world(account)
    with database.SessionLocal() as s:
        from app.models.store_core import DBStoreBin
        good_bin = DBStoreBin(store_id=w.central, code="DAMAGED", description="Damaged goods")
        far_bin = DBStoreBin(store_id=w.site, code="ELSEWHERE")
        s.add_all([good_bin, far_bin])
        s.commit()
        w.bin, w.far_bin = good_bin.id, far_bin.id
    i = posted_issue(tenant, w, lines=[{"item_id": w.item["plate"], "qty": "10", "boq_item_id": w.boq[0]}], received_by_type="GANG", received_by_name="Gang 3")
    il = i["lines"][0]["id"]
    body = lambda **k: {"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": il, "qty_returned": "4", **k}]}     # noqa: E731
    assert tenant.get(API + "/pick/bins", params={"store_id": w.central}).json()["items"][0]["code"] == "DAMAGED"
    for k, word in (({"condition": "BROKEN"}, "GOOD or DAMAGED"), ({"condition": "DAMAGED", "reason": "bent"}, "bin kept for them"), ({"condition": "DAMAGED", "reason": "bent", "bin_id": w.far_bin}, "bin kept for them"),
                    ({"condition": "DAMAGED", "bin_id": w.bin}, "what is wrong"), ({"condition": "DAMAGED", "bin_id": 999999, "reason": "bent"}, "bin kept for them")):
        res = tenant.post(API + "/returns", json=body(**k))
        assert res.status_code == 400 and word.lower() in res.json()["detail"].lower(), (k, res.text)
    assert tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": il, "qty_lost": "1", "reason": "gone", "condition": "DAMAGED", "bin_id": w.bin}]}).status_code == 400   # nothing came back to be damaged
    ret = tenant.post(API + "/returns", json=body(condition="DAMAGED", bin_id=w.bin, reason="bent on one side"))
    assert ret.status_code == 200, ret.text
    r = ret.json()
    assert r["lines"][0]["condition"] == "DAMAGED" and r["lines"][0]["bin"] == "DAMAGED" and r["lines"][0]["qty_returned"] == "4.000"
    move(tenant, "returns", r["id"], "submit", "approve", "post")
    assert balance(w, w.central, "plate")[0] == D("94.000")                                  # they are stock again, valued at the rate they left at
    assert tenant.get("%s/returns/%d/print" % (API, r["id"])).content[:4] == b"%PDF"
    good = tenant.post(API + "/returns", json=body(bin_id=w.far_bin)).json()                 # a bin on a good return is ignored
    assert good["lines"][0]["condition"] == "GOOD" and good["lines"][0]["bin_id"] is None


# --- closing a returnable other than by returning it -------------------------------------------------------------------------------

def test_a_returnable_can_be_converted_to_a_recovery_or_handed_to_a_write_off_request(account, portal):
    tenant = account["client"]
    w = world(account)
    i = returnable_issue(tenant, w, "20")                                                   # to Ravi Kumar
    il = i["lines"][0]["id"]
    convert = lambda **k: tenant.post("%s/returnables/%d/convert" % (API, il), json={"qty": "5", "rate": "300", "reason": "not returned by the gang", **k})     # noqa: E731
    assert convert().status_code == 200 and tenant.get(API + "/returnables").json()["items"][0]["qty_outstanding"] == "15.000"
    res = convert(qty="3", handling_pct="10")
    assert res.status_code == 200 and res.json()["recovery_rate"] == "330.000" and res.json()["amount"] == "990.00"
    rec = [x for x in tenant.get(API + "/recoveries").json()["items"] if x["source"] == "CONVERSION"]
    assert len(rec) == 2 and rec[0]["holder_name"] == "Ravi Kumar" and rec[0]["holder_type"] == "EMPLOYEE" and rec[0]["basis"] == "CONVERSION"
    for bad, word in (({"qty": "50"}, "still out"), ({"qty": "0"}, "more than zero"), ({"rate": "0"}, "more than zero"), ({"rate": "x"}, "not a number"), ({"reason": " "}, "give the reason"), ({"handling_pct": "101"}, "handling")):
        r = convert(**bad)
        assert r.status_code in (400, 409) and word.lower() in r.json()["detail"].lower(), (bad, r.text)
    wr = tenant.post("%s/returnables/%d/writeoff" % (API, il), json={"qty": "4", "reason": "lost on site"})
    assert wr.status_code == 200 and wr.json()["request_id"]
    req = tenant.get(API + "/writeoffs").json()["items"]
    assert len(req) == 1 and (req[0]["qty"], req[0]["status"], req[0]["reason"]) == ("4.000", "OPEN", "lost on site")
    assert tenant.get(API + "/returnables").json()["items"][0]["qty_outstanding"] == "8.000"                    # 20 - 5 - 3 - 4
    assert tenant.post("%s/returnables/%d/writeoff" % (API, il), json={"qty": "9", "reason": "x"}).status_code == 409
    back = tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": il, "qty_returned": "9"}]})
    assert back.status_code == 409 and "still out" in back.json()["detail"]
    ret = tenant.post(API + "/returns", json={"issue_id": i["id"], "return_date": TODAY, "lines": [{"issue_line_id": il, "qty_returned": "8"}]}).json()
    move(tenant, "returns", ret["id"], "submit", "approve", "post")
    assert tenant.get(API + "/returnables").json()["items"] == []                                                # everything accounted for
    res = tenant.post("%s/issue/%d/cancel" % (API, i["id"]), json={"reason": "no way"})
    assert res.status_code == 409                                                                               # a return and the closures stand on it
    # rights: converting needs approve (it is a charge); asking for a write-off needs only create
    staff(account, portal, ["store.outward.view", "store.outward.create"], [w.central])
    j = returnable_issue(tenant, w, "5")
    jl = j["lines"][0]["id"]
    assert portal.post("%s/returnables/%d/convert" % (API, jl), json={"qty": "1", "rate": "10", "reason": "x"}).status_code == 403
    assert portal.post("%s/returnables/%d/writeoff" % (API, jl), json={"qty": "1", "reason": "lost"}).status_code == 200


def test_closing_a_returnable_for_a_subcontractor_reaches_the_bill_and_consumables_cannot_be_closed_this_way(account, second_tenant):
    tenant = account["client"]
    w = world(account)
    i = posted_issue(tenant, w, lines=[{"item_id": w.item["plate"], "qty": "10"}], **sub_head(w))
    il = i["lines"][0]["id"]
    assert tenant.post("%s/returnables/%d/convert" % (API, il), json={"qty": "2", "rate": "450", "handling_pct": "5", "reason": "props not returned"}).status_code == 200
    with database.SessionLocal() as s:
        got = store_outward.get_subcon_issues(s, w.contractor, date.today())
        conv = [g for g in got if g.chargeable]
        assert len(conv) == 1 and (conv[0].qty_issued, conv[0].recovery_rate, conv[0].recovery_value, conv[0].issue_line_id) == (D("2.000"), D("472.500"), D("945.00"), il)
    c = posted_issue(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "1", "uom": "bag", "boq_item_id": w.boq[0]}])
    for path in ("convert", "writeoff"):
        res = tenant.post("%s/returnables/%d/%s" % (API, c["lines"][0]["id"], path), json={"qty": "1", "rate": "5", "reason": "x"})
        assert res.status_code == 409 and "consumable" in res.json()["detail"]
    assert second_tenant.post("%s/returnables/%d/writeoff" % (API, il), json={"qty": "1", "reason": "x"}).status_code == 404
    assert tenant.post("%s/returnables/999999/writeoff" % API, json={"qty": "1", "reason": "x"}).status_code == 404


# --- gate passes ------------------------------------------------------------------------------------------------------------------------------

def test_a_gate_pass_is_made_for_issued_material_leaving_the_premises(account, portal):
    tenant = account["client"]
    w = world(account)
    draft = make_issue(tenant, w)
    body = lambda issue, **k: {"issue_id": issue["id"], "gate_date": TODAY, "vehicle_no": "TS09AB1234", "driver_name": "Raju", "destination": "Tower A site", **k}     # noqa: E731
    res = tenant.post(API + "/gate-pass", json=body(draft))
    assert res.status_code == 409 and "post the issue first" in res.json()["detail"]
    i = posted_issue(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "10", "uom": "bag", "boq_item_id": w.boq[0]}, {"item_id": w.item["plate"], "qty": "8", "boq_item_id": w.boq[0],
                                                                                                                  "expected_return_date": (date.today() + timedelta(days=12)).isoformat()}],
                     received_by_type="GANG", received_by_name="Gang 3")
    cement, plate = i["lines"]
    for bad, word in (({"destination": " "}, "destination"), ({"lines": [{"issue_line_id": cement["id"], "qty": "11", "uom": "bag"}]}, "was issued"), ({"lines": [{"issue_line_id": 999999, "qty": "1"}]}, "not on issue"),
                      ({"lines": [{"issue_line_id": plate["id"], "qty": "0"}]}, "more than zero"), ({"gate_date": "2999-01-01"}, "future")):
        r = tenant.post(API + "/gate-pass", json=body(i, **bad))
        assert r.status_code in (400, 409) and word.lower() in r.json()["detail"].lower(), (bad, r.text)
    gp = tenant.post(API + "/gate-pass", json=body(i, lines=[{"issue_line_id": plate["id"], "qty": "5"}]))
    assert gp.status_code == 200, gp.text
    g = gp.json()
    assert g["number"].startswith("GATE/") and g["status"] == "ISSUED" and g["returnable"] is True and g["expected_return_date"] == plate["expected_return_date"]       # the date from the issue line
    assert (g["lines"][0]["qty"], g["received_by"], g["authorised_by"] != "") == ("5.000", "Gang 3", True) and g["overdue_days"] == 0
    assert tenant.post(API + "/gate-pass", json=body(i, lines=[{"issue_line_id": plate["id"], "qty": "4"}])).status_code == 409                # 5 + 4 is more than the 8 issued
    whole = tenant.post(API + "/gate-pass", json=body(i, lines=[{"issue_line_id": cement["id"], "qty": "10", "uom": "bag"}]))
    assert whole.status_code == 200 and whole.json()["returnable"] is False and whole.json()["expected_return_date"] == ""
    both = tenant.post(API + "/gate-pass", json=body(i, lines=[{"issue_line_id": plate["id"], "qty": "3"}], expected_return_date=(date.today() + timedelta(days=5)).isoformat()))
    assert both.status_code == 200 and both.json()["expected_return_date"] == (date.today() + timedelta(days=5)).isoformat()
    assert [x["status"] for x in tenant.get("%s/issue/%d" % (API, i["id"])).json()["gate_passes"]] == ["ISSUED", "ISSUED", "ISSUED"]
    res = tenant.post("%s/issue/%d/cancel" % (API, i["id"]), json={"reason": "wrong"})
    assert res.status_code == 409 and "gate pass" in res.json()["detail"].lower()
    assert tenant.post("%s/gate-pass/%d/close" % (API, whole.json()["id"])).status_code == 409                                              # only a returnable pass is closed
    assert tenant.post("%s/gate-pass/%d/close" % (API, g["id"])).json()["status"] == "CLOSED"
    assert tenant.post("%s/gate-pass/%d/close" % (API, g["id"])).status_code == 409
    assert tenant.post("%s/gate-pass/%d/cancel" % (API, whole.json()["id"]), json={"reason": " "}).status_code == 400
    assert tenant.post("%s/gate-pass/%d/cancel" % (API, whole.json()["id"]), json={"reason": "load not sent"}).json()["status"] == "CANCELLED"
    assert tenant.post("%s/gate-pass/%d/cancel" % (API, whole.json()["id"]), json={"reason": "again"}).status_code == 409
    assert tenant.get(API + "/gate-pass", params={"status": "ISSUED"}).json()["total"] == 1 and tenant.get(API + "/gate-pass", params={"q": "TS09"}).json()["total"] == 3
    for gid in (g["id"], whole.json()["id"]):
        assert tenant.get("%s/gate-pass/%d/print" % (API, gid)).content[:4] == b"%PDF"
    assert openpyxl.load_workbook(io.BytesIO(tenant.get(API + "/gate-pass/export").content)).active.max_row >= 2
    # rights and stores
    staff(account, portal, ["store.outward.view", "store.outward.create"], [w.central])
    assert portal.get(API + "/gate-pass").json()["total"] == 3
    assert portal.post(API + "/gate-pass/%d/cancel" % both.json()["id"], json={"reason": "no"}).status_code == 403          # cancelling needs the cancel right
    staff(account, portal, ["store.outward.view", "store.outward.create"], [w.site])
    assert portal.get(API + "/gate-pass").json()["total"] == 0 and portal.get("%s/gate-pass/%d" % (API, g["id"])).status_code == 403
    assert portal.post(API + "/gate-pass", json=body(i)).status_code == 403
    pass_ = tenant.get("%s/gate-pass/%d" % (API, both.json()["id"])).json()
    assert pass_["history"][0]["action"] == "create"


def test_a_gate_pass_is_not_reachable_across_companies(account, second_tenant):
    tenant = account["client"]
    w = world(account)
    i = posted_issue(tenant, w)
    g = tenant.post(API + "/gate-pass", json={"issue_id": i["id"], "gate_date": TODAY, "destination": "Site"}).json()
    assert second_tenant.get("%s/gate-pass/%d" % (API, g["id"])).status_code == 404 and second_tenant.get(API + "/gate-pass").json()["total"] == 0
    assert second_tenant.post("%s/gate-pass/%d/close" % (API, g["id"])).status_code == 404
    assert second_tenant.post(API + "/gate-pass", json={"issue_id": i["id"], "gate_date": TODAY, "destination": "x"}).status_code == 404
    assert second_tenant.get("%s/gate-pass/%d/print" % (API, g["id"])).status_code == 404


def test_the_insufficient_stock_message_says_what_is_available(account):
    tenant = account["client"]
    w = world(account)
    big = make_issue(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "101", "uom": "bag", "boq_item_id": w.boq[0]}])
    res = tenant.post("%s/issue/%d/submit" % (API, big["id"]))
    assert res.status_code == 409 and "Only 5000.000 kg of Cement OPC on hand in this store; 5050.000 was asked for" in res.json()["detail"]
    direct = tenant.post(API + "/issue/direct", json=issue_body(w, lines=[{"item_id": w.item["cement"], "qty": "101", "uom": "bag", "boq_item_id": w.boq[0]}]))
    assert direct.status_code == 409 and "5000.000" in direct.json()["detail"]
