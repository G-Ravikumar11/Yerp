"""Free-issue material to a subcontractor is held to an allowance - the store's norm x the quantity of the work ordered - and goes past it only
with the Master's approval, the way steel goes past its BBS allowance. The allowance is worked out from posted issues, so cancelling or returning
gives it back; nothing is kept as a counter."""
from decimal import Decimal

from app import db as database, models
from app.models.store_outward import DBStoreFreeIssueRequest, DBStoreIssue, DBStoreOutwardLog
from app.models.store_reports import DBStoreMaterialNorm
from store.test_p3_outward import API, TODAY, _leave_no_stock_behind, issue_body, make_issue, move, staff, world  # noqa: F401

ALLOWANCE = API + "/free-issue/allowance"
RIGHTS = ["store.outward.view", "store.outward.create", "store.outward.approve", "store.outward.post", "store.outward.direct_issue"]


def with_norm(account, norm="5", ordered=20):
    """The test company with a subcontract order for 20 cum of BOQ item 1, and a norm of 5 kg of cement per cum on it: 100 kg may be drawn free."""
    w = world(account)
    with database.SessionLocal() as s:
        s.add(models.DBSubcontractItem(order_id=w.sub_order, activity_no="1", item_code="RCC", item_description="RCC M25 in columns", uom="cum", quantity=ordered, boq_key="k1"))
        s.add(DBStoreMaterialNorm(client_id=w.client_id, boq_item_id=w.boq[0], item_id=w.item["cement"], qty_per_unit=Decimal(norm), wastage_pct=Decimal("10")))
        s.commit()
    return w


def sub(w, kg, item="cement", uom="kg", **line):
    lines = [{"item_id": w.item[item], "qty": str(kg), "uom": uom, **line}]
    return issue_body(w, issue_type="SUBCONTRACTOR", subcontractor_id=w.contractor, subcontract_order_id=w.sub_order, lines=lines)


def row(client, w, item="cement"):
    got = client.get(ALLOWANCE, params={"subcontract_order_id": w.sub_order, "item_id": w.item[item]}).json()["items"]
    return got[0] if got else None


def requests(w):
    with database.SessionLocal() as s:
        return s.query(DBStoreFreeIssueRequest).filter(DBStoreFreeIssueRequest.client_id == w.client_id).order_by(DBStoreFreeIssueRequest.id).all()


def inbox(client):
    got = client.get("/api/approvals/inbox").json()
    return got["items"] if isinstance(got, dict) else got


# --- within the allowance ---------------------------------------------------------------------------------------------------

def test_inside_the_allowance_free_issue_goes_out_as_usual_and_the_allowance_is_tracked(account):
    tenant = account["client"]
    w = with_norm(account)
    got = row(tenant, w)
    assert (got["permitted"], got["issued"], got["remaining"], got["order_qty"]) == ("100.000", "0.000", "100.000", 20)
    assert got["basis"][0]["norm"] == "5.000000" and got["basis"][0]["allowed"] == "100.000" and got["subcontractor"] == "Sai Steel Fixers"
    res = tenant.post(API + "/issue/direct", json=sub(w, 60))
    assert res.status_code == 200 and res.json()["status"] == "POSTED" and "held_for_allowance" not in res.json()
    assert res.json()["free_issue"]["requests"] == []
    got = row(tenant, w)
    assert (got["issued"], got["remaining"]) == ("60.000", "40.000")
    assert tenant.post(API + "/issue/direct", json=sub(w, 40)).json()["status"] == "POSTED"           # exactly what is left
    assert row(tenant, w)["remaining"] == "0.000" and requests(w) == []


def test_only_free_material_on_an_order_with_a_norm_is_held(account):
    tenant = account["client"]
    w = with_norm(account)
    # Charged to the contractor, a SITE issue and a material with no norm are none of the allowance's business.
    charged = sub(w, 500, chargeable=True, recovery_basis="AVERAGE_COST")
    assert tenant.post(API + "/issue/direct", json=charged).json()["status"] == "POSTED"
    assert tenant.post(API + "/issue/direct", json=issue_body(w, lines=[{"item_id": w.item["cement"], "qty": "500", "uom": "kg", "boq_item_id": w.boq[0]}])).json()["status"] == "POSTED"
    assert tenant.post(API + "/issue/direct", json=sub(w, 30, item="helmet", uom="nos")).json()["status"] == "POSTED"
    assert row(tenant, w)["issued"] == "0.000" and row(tenant, w, "helmet") is None and requests(w) == []


# --- past the allowance --------------------------------------------------------------------------------------------------------

def test_past_the_allowance_a_storekeepers_direct_issue_waits_for_the_master_who_approves_it(account, portal):
    tenant = account["client"]
    w = with_norm(account)
    assert tenant.post(API + "/issue/direct", json=sub(w, 60)).status_code == 200
    staff(account, portal, RIGHTS, [w.central])
    res = portal.post(API + "/issue/direct", json=sub(w, 70, remarks="Extra shuttering oil"))
    assert res.status_code == 200, res.text
    got = res.json()
    assert got["held_for_allowance"] is True and got["status"] == "SUBMITTED" and "30.000 kg over" in got["allowance_over"][0]
    assert row(tenant, w)["issued"] == "60.000"                                         # nothing went out
    [req] = requests(w)
    assert (req.status, req.permitted_qty, req.issued_qty, req.requested_qty, req.excess_qty) == ("PENDING", Decimal("100"), Decimal("60"), Decimal("70"), Decimal("30"))
    assert req.reason == "Column casting" and req.requested_by and req.subcontract_order_id == w.sub_order and req.subcontractor_id == w.contractor
    detail = tenant.get("%s/issue/%d" % (API, got["id"])).json()["free_issue"]
    assert detail["rows"][0]["excess"] == "30.000" and detail["requests"][0]["status"] == "PENDING" and detail["requests"][0]["subcontractor"] == "Sai Steel Fixers"
    # It waits in the Master's inbox, and is in the history as waiting.
    waiting = next(i for i in inbox(tenant) if i["kind"] == "free_issue" and i["id"] == got["id"])
    assert "30.000 over" in waiting["what"]
    with database.SessionLocal() as s:
        assert s.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_id == got["id"], DBStoreOutwardLog.action == "free_issue_requested").count() == 1
    # The storekeeper cannot approve it, nor push it through.
    refused = portal.post("%s/issue/%d/approve" % (API, got["id"]))
    assert refused.status_code == 403                                                  # it is their own issue, and past the allowance besides
    assert portal.post("%s/issue/%d/post" % (API, got["id"])).status_code == 409                 # it is not approved
    done = tenant.post("/api/approvals/decide", json={"kind": "free_issue", "id": got["id"], "decision": "approve", "note": "Rain damage, re-cast"})
    assert done.status_code == 200, done.text
    assert move(tenant, "issue", got["id"], "post")["status"] == "POSTED"
    [req] = requests(w)
    assert (req.status, req.approved_excess, req.decision_note) == ("APPROVED", Decimal("30"), "Rain damage, re-cast") and req.decided_by and req.decided_at
    assert (row(tenant, w)["issued"], row(tenant, w)["remaining"]) == ("130.000", "-30.000")
    with database.SessionLocal() as s:
        assert s.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_id == got["id"], DBStoreOutwardLog.action == "free_issue_approved").count() == 1


def test_the_master_issuing_past_the_allowance_directly_is_recorded_as_approved(account):
    tenant = account["client"]
    w = with_norm(account)
    res = tenant.post(API + "/issue/direct", json=sub(w, 150))
    assert res.status_code == 200 and res.json()["status"] == "POSTED"
    [req] = requests(w)
    assert (req.status, req.excess_qty, req.approved_excess) == ("APPROVED", Decimal("50"), Decimal("50")) and "directly by the Master" in req.decision_note


def test_a_storekeepers_own_approval_is_not_enough_even_with_the_store_rights(account, portal):
    tenant = account["client"]
    w = with_norm(account)
    draft = tenant.post(API + "/issue", json=sub(w, 130)).json()
    assert tenant.post("%s/issue/%d/submit" % (API, draft["id"])).status_code == 200
    staff(account, portal, RIGHTS, [w.central])
    assert portal.post("%s/issue/%d/approve" % (API, draft["id"])).status_code == 403
    assert portal.post("/api/approvals/decide", json={"kind": "free_issue", "id": draft["id"], "decision": "approve", "note": "x"}).status_code in (403, 404)
    assert tenant.get("%s/issue/%d" % (API, draft["id"])).json()["status"] == "SUBMITTED"
    assert not [i for i in inbox(portal) if i["kind"] == "free_issue"]                    # the inbox is the Master's


def test_the_master_refuses_it_and_the_refusal_is_on_the_record(account, portal):
    tenant = account["client"]
    w = with_norm(account)
    over = tenant.post(API + "/issue", json=sub(w, 130)).json()
    assert tenant.post("%s/issue/%d/submit" % (API, over["id"]), json={"reason": "Need it for the slab"}).status_code == 200
    assert requests(w)[0].reason == "Need it for the slab"
    staff(account, portal, RIGHTS, [w.central])
    assert portal.post("%s/issue/%d/free-issue/reject" % (API, over["id"]), json={"reason": "no"}).status_code == 403
    assert tenant.post("%s/issue/%d/free-issue/reject" % (API, over["id"]), json={"reason": ""}).status_code == 400          # a reason is needed
    done = tenant.post("%s/issue/%d/free-issue/reject" % (API, over["id"]), json={"reason": "Use what is on site first"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "CANCELLED" and "Use what is on site first" in done.json()["cancel_reason"]
    [req] = requests(w)
    assert (req.status, req.decision_note, req.approved_excess) == ("REJECTED", "Use what is on site first", None) and req.decided_by
    assert row(tenant, w)["issued"] == "0.000"
    with database.SessionLocal() as s:
        assert s.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_id == over["id"], DBStoreOutwardLog.action == "free_issue_rejected").count() == 1
    shown = tenant.get(API + "/free-issue/requests", params={"status": "REJECTED"}).json()["items"]
    assert [x["issue_id"] for x in shown] == [over["id"]] and shown[0]["decision_note"] == "Use what is on site first"
    assert tenant.post("%s/issue/%d/free-issue/reject" % (API, over["id"]), json={"reason": "again"}).status_code == 409           # already cancelled


# --- giving the allowance back ---------------------------------------------------------------------------------------------------

def test_cancelling_or_returning_gives_the_allowance_back(account):
    tenant = account["client"]
    w = with_norm(account)
    posted = tenant.post(API + "/issue/direct", json=sub(w, 90)).json()
    assert row(tenant, w)["remaining"] == "10.000"
    ret = tenant.post(API + "/returns", json={"issue_id": posted["id"], "return_date": TODAY, "lines": [{"issue_line_id": posted["lines"][0]["id"], "qty_returned": "40", "uom": "kg"}]})
    assert ret.status_code == 200, ret.text
    assert row(tenant, w)["issued"] == "90.000"                                         # a return that has not posted gives nothing back
    move(tenant, "returns", ret.json()["id"], "submit", "approve", "post")
    assert (row(tenant, w)["issued"], row(tenant, w)["remaining"]) == ("50.000", "50.000")
    move(tenant, "returns", ret.json()["id"], "cancel")                                   # the return is undone: the 40 kg is out again
    assert row(tenant, w)["issued"] == "90.000"
    move(tenant, "issue", posted["id"], "cancel")                                         # and the issue itself
    assert (row(tenant, w)["issued"], row(tenant, w)["remaining"]) == ("0.000", "100.000")
    again = tenant.post(API + "/issue/direct", json=sub(w, 100))                          # the whole allowance is there to use again
    assert again.json()["status"] == "POSTED" and requests(w) == []


def test_cancelling_an_issue_that_waits_withdraws_its_request(account):
    tenant = account["client"]
    w = with_norm(account)
    over = tenant.post(API + "/issue", json=sub(w, 130)).json()
    tenant.post("%s/issue/%d/submit" % (API, over["id"]))
    assert requests(w)[0].status == "PENDING"
    move(tenant, "issue", over["id"], "cancel")
    assert requests(w)[0].status == "WITHDRAWN"
    assert not [i for i in inbox(tenant) if i["kind"] == "free_issue"]


# --- two issues, one allowance -----------------------------------------------------------------------------------------------------

def test_two_issues_each_inside_the_allowance_cannot_both_go_out_past_it(account):
    """Both were approved while the whole allowance was free. Posting works it out again with the other's posting counted, so the second is stopped."""
    tenant = account["client"]
    w = with_norm(account)
    first, second = (tenant.post(API + "/issue", json=sub(w, 60)).json() for _ in range(2))
    for d in (first, second):
        move(tenant, "issue", d["id"], "submit", "approve")                               # 60 against 100: inside it, both ways
    assert requests(w) == []
    assert move(tenant, "issue", first["id"], "post")["status"] == "POSTED"
    stopped = tenant.post("%s/issue/%d/post" % (API, second["id"]))
    assert stopped.status_code == 409 and "Since it was approved" in stopped.json()["detail"] and "20.000 kg over" in stopped.json()["detail"]
    assert row(tenant, w)["issued"] == "60.000"
    # Sent back and approved by the Master for the 20 kg over, it goes.
    move(tenant, "issue", second["id"], "cancel")
    third = tenant.post(API + "/issue", json=sub(w, 60)).json()
    move(tenant, "issue", third["id"], "submit", "approve", "post")
    assert row(tenant, w)["issued"] == "120.000" and requests(w)[0].status == "APPROVED"


def test_an_approval_covers_only_the_excess_that_was_approved(account):
    tenant = account["client"]
    w = with_norm(account)
    a, b = (tenant.post(API + "/issue", json=sub(w, 120)).json() for _ in range(2))
    for d in (a, b):
        tenant.post("%s/issue/%d/submit" % (API, d["id"]))
    assert {r.excess_qty for r in requests(w)} == {Decimal("20")}                          # each, on its own, is 20 over
    for d in (a, b):
        tenant.post("%s/issue/%d/approve" % (API, d["id"]))
    assert move(tenant, "issue", a["id"], "post")["status"] == "POSTED"                    # 120 against 100: the 20 approved
    stopped = tenant.post("%s/issue/%d/post" % (API, b["id"]))                             # now 240 against 100: 120 of it past, 20 approved
    assert stopped.status_code == 409 and "Since it was approved" in stopped.json()["detail"]
    assert row(tenant, w)["issued"] == "120.000"


def test_a_released_lock_leaves_other_orders_untouched(account):
    """The allowance is per work order: material free under one order is not counted against another's."""
    tenant = account["client"]
    w = with_norm(account)
    with database.SessionLocal() as s:
        other = models.DBSubcontractOrder(client_id=w.client_id, wo_number="SWO-2", status="ACTIVE", contractor_id=w.contractor, job_id=w.project)
        s.add(other)
        s.flush()
        s.add(models.DBSubcontractItem(order_id=other.id, activity_no="1", item_description="RCC", uom="cum", quantity=10, boq_key="k1"))
        s.commit()
        other_id = other.id
    assert tenant.post(API + "/issue/direct", json=sub(w, 100)).json()["status"] == "POSTED"
    body = sub(w, 50)
    body["subcontract_order_id"] = other_id
    got = tenant.post(API + "/issue/direct", json=body)                                    # 10 cum x 5 = 50 on its own order: inside it
    assert got.status_code == 200 and got.json()["status"] == "POSTED" and requests(w) == []
    assert tenant.get(ALLOWANCE, params={"subcontract_order_id": w.sub_order}).json()["items"][0]["issued"] == "100.000"
    assert tenant.get(ALLOWANCE, params={"subcontract_order_id": 999999}).status_code == 404


def test_steel_the_bbs_governs_is_left_to_the_bbs(account):
    """Steel keeps its own allowance; the norm check does not hold it a second time."""
    from store.test_steel_allowance import BBS_KG, with_steel
    tenant = account["client"]
    w = with_steel(account)
    with database.SessionLocal() as s:
        s.add(models.DBSubcontractItem(order_id=w.sub_order, activity_no="1", item_description="Steel fixing", uom="kg", quantity=10, boq_key="k1"))
        s.add(DBStoreMaterialNorm(client_id=w.client_id, boq_item_id=w.boq[0], item_id=w.steel, qty_per_unit=Decimal("1"), wastage_pct=Decimal("0")))
        s.commit()
    body = issue_body(w, issue_type="SUBCONTRACTOR", subcontractor_id=w.contractor, subcontract_order_id=w.sub_order, lines=[{"item_id": w.steel, "qty": "500", "uom": "kg"}])
    got = tenant.post(API + "/issue/direct", json=body)               # 500 kg against a norm of 10 kg, but inside the BBS (1,088 kg)
    assert got.status_code == 200 and got.json()["status"] == "POSTED" and BBS_KG > 500 and requests(w) == []
