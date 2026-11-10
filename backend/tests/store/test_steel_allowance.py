"""Steel wastage: a project draws its approved BBS steel plus 2%; past that, an issue waits for the Master or an engineer
who signs off the BBS, and the reconciliation shows the wastage diameter by diameter."""
from datetime import date, timedelta
from decimal import Decimal

from app import db as database, models
from app.models.store_core import DBStoreItemSettings, MovementType
from app.models.store_outward import DBStoreIssue
from app.services.stock_ledger import post_movement
from store.test_p3_outward import API, TODAY, _leave_no_stock_behind, issue_body, move, staff, world  # noqa: F401

D = Decimal
# 100 bars of 12 mm cut to 12 m: 1,200 m x 0.889 kg/m = 1,066.7 kg; with 2%, 1,088 kg may be drawn.
BBS_KG = 100 * 12.0 * 144 / 162.0


def with_steel(account, bbs=True):
    w = world(account)
    with database.SessionLocal() as s:
        it = models.DBItem(client_id=w.client_id, kind="RM", item_code="TMT12-%d" % w.project, item_name="TMT Fe500D 12 mm", units_of_measure="kg")
        s.add(it)
        s.flush()
        s.add(DBStoreItemSettings(item_id=it.id, category="CONSUMABLE", base_uom="kg"))
        post_movement(s, movement_type=MovementType.OPENING_IN, store_id=w.central, item_id=it.id, qty=D("5000"), rate=D("62"),
                      txn_date=date.today() - timedelta(days=30), project_id=None, ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        if bbs:
            s.add(models.DBBbsEntry(client_id=w.client_id, job_id=w.project, entry_key="k-%d" % w.project, element="Column", bar_mark="C1",
                                    diameter_mm=12, num_bars=100, cutting_length_mm=12000, status="Approved"))
        s.commit()
        w.steel = it.id
    return w


def steel_body(w, kg):
    return issue_body(w, lines=[{"item_id": w.steel, "qty": str(kg), "uom": "kg", "boq_item_id": w.boq[0]}])


def test_inside_the_allowance_steel_goes_out_as_usual(account):
    tenant = account["client"]
    w = with_steel(account)
    res = tenant.post(API + "/issue/direct", json=steel_body(w, 1080))
    assert res.status_code == 200, res.text


def test_past_two_percent_a_direct_issue_goes_for_approval_instead(account, portal):
    tenant = account["client"]
    w = with_steel(account)
    assert tenant.post(API + "/issue/direct", json=steel_body(w, 1000)).status_code == 200
    staff(account, portal, ["store.outward.direct_issue"], [w.central])
    res = portal.post(API + "/issue/direct", json=steel_body(w, 100))
    assert res.status_code == 200, res.text
    got = res.json()
    assert got["held_for_steel"] is True and got["status"] == "SUBMITTED" and "2%" in got["message"]
    assert got["steel_over"] and "12 mm" in got["steel_over"][0]
    # Not issued: the stock is still in the store.
    issued = tenant.get("/api/bbs/steel?job_id=%d" % w.project).json()
    assert next(r for r in issued["rows"] if r["diameter_mm"] == 12)["issued_kg"] == 1000
    # It is on the issue's history as waiting for the steel, and it waits in the approvals inbox.
    from app.models.store_outward import DBStoreOutwardLog
    with database.SessionLocal() as s:
        assert s.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_id == got["id"], DBStoreOutwardLog.action == "steel_needs_approval").count() == 1
    inbox = tenant.get("/api/approvals/inbox").json()
    inbox = inbox["items"] if isinstance(inbox, dict) else inbox
    row = next(i for i in inbox if i["kind"] == "steel_issue" and i["id"] == got["id"])
    assert "12 mm" in row["what"]
    done = tenant.post("/api/approvals/decide", json={"kind": "steel_issue", "id": got["id"], "decision": "approve", "note": "Lap lengths revised"})
    assert done.status_code == 200, done.text
    assert move(tenant, "issue", got["id"], "post")["status"] == "POSTED"
    with database.SessionLocal() as s:
        assert s.get(DBStoreIssue, got["id"]).steel_override_by


def test_an_engineer_approves_the_steel_without_the_store_s_right_but_nothing_else(account, portal):
    tenant = account["client"]
    w = with_steel(account)
    over = tenant.post(API + "/issue", json=steel_body(w, 1200)).json()
    plain = tenant.post(API + "/issue", json=issue_body(w)).json()
    for d in (over, plain):
        assert tenant.post("%s/issue/%d/submit" % (API, d["id"])).status_code == 200
    engineer = staff(account, portal, ["site.signoff"], [w.central])
    over2 = tenant.post(API + "/issue", json=steel_body(w, 1150)).json()          # sent after the engineer is on the books
    assert tenant.post("%s/issue/%d/submit" % (API, over2["id"])).status_code == 200
    with database.SessionLocal() as s:                                            # the engineer was told on their bell
        told = s.query(models.DBNotification).filter(models.DBNotification.employee_id == engineer["id"]).all()
        assert any(over2["number"] in (n.title or "") for n in told)
    assert portal.post("%s/issue/%d/approve" % (API, plain["id"])).status_code == 403
    inbox = portal.get("/api/approvals/inbox").json()
    inbox = inbox["items"] if isinstance(inbox, dict) else inbox
    assert sorted(i["id"] for i in inbox if i["kind"] == "steel_issue") == sorted([over["id"], over2["id"]])
    refused = portal.post("/api/approvals/decide", json={"kind": "steel_issue", "id": over["id"], "decision": "reject", "note": "Use the 10 mm offcuts"})
    assert refused.status_code == 200, refused.text
    d = tenant.get("%s/issue/%d" % (API, over["id"])).json()
    assert d["status"] == "CANCELLED" and "offcuts" in d["cancel_reason"]


def test_the_storekeeper_cannot_approve_it_but_the_master_can(account, portal):
    tenant = account["client"]
    w = with_steel(account)
    staff(account, portal, ["store.outward.view", "store.outward.create", "store.outward.approve", "store.outward.post", "store.outward.direct_issue"], [w.central])
    made = portal.post(API + "/issue/direct", json=steel_body(w, 1000))
    assert made.status_code == 200, made.text
    draft = tenant.post(API + "/issue", json=steel_body(w, 200))
    assert draft.status_code == 200, draft.text
    doc = draft.json()["id"]
    assert tenant.post("%s/issue/%d/submit" % (API, doc)).status_code == 200
    refused = portal.post("%s/issue/%d/approve" % (API, doc))            # the storekeeper, who did not raise it
    assert refused.status_code == 403 and "Only the Master or an engineer" in refused.json()["detail"]
    engineer = staff(account, portal, ["store.outward.view", "store.outward.approve", "site.signoff"], [w.central])
    done = move(portal, "issue", doc, "approve")
    assert done["status"] == "APPROVED" and engineer["id"]
    done = move(tenant, "issue", doc, "post")
    assert done["status"] == "POSTED"
    with database.SessionLocal() as s:
        assert s.get(DBStoreIssue, doc).steel_override_by


def test_the_reconciliation_shows_the_wastage_by_diameter(account):
    tenant = account["client"]
    w = with_steel(account)
    assert tenant.post(API + "/issue/direct", json=steel_body(w, 1080)).status_code == 200
    got = tenant.get("/api/bbs/steel?job_id=%d" % w.project).json()
    row = next(r for r in got["rows"] if r["diameter_mm"] == 12)
    assert row["bbs_kg"] == round(BBS_KG, 1) and row["issued_kg"] == 1080 and row["status"] == "OK"
    assert row["wastage_pct"] == round((1080 - BBS_KG) / BBS_KG * 100, 2) and got["allowance_pct"] == 2


def test_a_project_with_no_approved_bbs_is_not_held_up(account):
    tenant = account["client"]
    w = with_steel(account, bbs=False)
    assert tenant.post(API + "/issue/direct", json=steel_body(w, 3000)).status_code == 200
    assert tenant.get("/api/bbs/steel?job_id=%d" % w.project).json()["checked"] is False


def test_steel_items_are_known_by_name_and_weighed_by_unit():
    from app.services.steel_allowance import diameter_of, kg_per

    class I:
        def __init__(self, name):
            self.item_name, self.description, self.segment, self.category = name, "", "", ""
    assert diameter_of(I("TMT Fe500D 12 mm")) == 12 and diameter_of(I("Reinforcement steel 16mm")) == 16
    assert diameter_of(I("Cement OPC 53")) == 0 and diameter_of(I("Binding wire 18 gauge")) == 0
    assert kg_per("MT") == 1000 and kg_per("Kg") == 1 and kg_per("Nos") == 0
