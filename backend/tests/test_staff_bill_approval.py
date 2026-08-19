"""A cost raised on site, signed off up the reporting line, then paid.

The whole point of the chain is that money does not move because somebody
clicked approve: approval only clears a bill for payment, and finance still
has to release it. These tests pin that separation down, along with who is
allowed to decide what.
"""
import uuid

import pytest

from conftest import make_employee


PASSWORD = "Crew1234"


def staff(tenant, permission_role="staff", reports_to=None, **overrides):
    """An employee who can sign into the portal."""
    emp = make_employee(
        tenant,
        permission_role=permission_role,
        reports_to=reports_to,
        password=PASSWORD,
        status="active",
        **overrides,
    )
    # make_employee creates people as "onboarding"; a real signing-in employee
    # is active, and status is not settable on create.
    tenant.put(f"/api/employees/{emp['id']}", json={"status": "active"})
    return emp


def sign_in(client, emp):
    res = client.post("/api/employee/auth/login",
                      json={"email": emp["email"], "password": PASSWORD})
    assert res.status_code == 200, res.text
    return client


def sign_out(client):
    client.post("/api/employee/auth/logout")


def raise_bill(client, **overrides):
    payload = {"vendor_name": "Travis Perkins", "amount": 250.0, "tax_amount": 50.0,
               "notes": "Timber for the Fairview job"}
    payload.update(overrides)
    res = client.post("/api/employee/bills", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def test_a_bill_goes_to_the_persons_manager(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])

    sign_in(tenant, hand)
    result = raise_bill(tenant)

    assert result["status"] == "pending"
    assert result["bill"]["approval_status"] == "pending"
    assert result["bill"]["status"] == "Awaiting Approval"
    assert result["chain_length"] == 1
    sign_out(tenant)

    sign_in(tenant, boss)
    queue = tenant.get("/api/employee/approvals").json()
    assert [b["number"] for b in queue["pending"]] == [result["bill"]["number"]]


def test_approval_clears_for_payment_without_paying(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])

    sign_in(tenant, hand)
    bill = raise_bill(tenant)["bill"]
    sign_out(tenant)

    sign_in(tenant, boss)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    res = tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                      json={"action": "approve", "notes": "Seen the delivery note"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"
    sign_out(tenant)

    after = tenant.get(f"/api/bills/{bill['id']}").json()
    assert after["approval_status"] == "approved"
    assert after["status"] == "Approved for payment"
    # The money has not moved.
    assert after["amount_paid"] == 0.0


def test_only_finance_can_release_the_money(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])

    sign_in(tenant, hand)
    bill = raise_bill(tenant)["bill"]
    sign_out(tenant)

    sign_in(tenant, boss)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                json={"action": "approve", "notes": "Fine"})
    # A manager approves, but does not pay.
    assert tenant.post(f"/api/employee/bills/{bill['id']}/pay").status_code == 403
    sign_out(tenant)

    purse = staff(tenant, permission_role="finance")
    sign_in(tenant, purse)
    res = tenant.post(f"/api/employee/bills/{bill['id']}/pay")
    assert res.status_code == 200, res.text
    sign_out(tenant)

    after = tenant.get(f"/api/bills/{bill['id']}").json()
    assert after["status"] == "Paid"
    assert after["amount_paid"] == 300.0


def test_an_unapproved_bill_cannot_be_paid(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    sign_in(tenant, hand)
    bill = raise_bill(tenant)["bill"]
    sign_out(tenant)

    purse = staff(tenant, permission_role="finance")
    sign_in(tenant, purse)
    res = tenant.post(f"/api/employee/bills/{bill['id']}/pay")
    assert res.status_code == 403, res.text
    sign_out(tenant)

    # And the owner's own screen refuses it for the same reason.
    assert tenant.post(f"/api/bills/{bill['id']}/pay").status_code == 403


def test_rejection_sends_it_back_with_the_reason(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])

    sign_in(tenant, hand)
    bill = raise_bill(tenant)["bill"]
    sign_out(tenant)

    sign_in(tenant, boss)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                json={"action": "reject", "notes": "No purchase order on this"})
    sign_out(tenant)

    sign_in(tenant, hand)
    mine = tenant.get("/api/employee/bills").json()["bills"]
    sent_back = next(b for b in mine if b["id"] == bill["id"])
    assert sent_back["approval_status"] == "rejected"
    assert sent_back["status"] == "Rejected"
    assert sent_back["rejection_reason"] == "No purchase order on this"


def test_a_sent_back_bill_can_be_fixed_and_sent_again(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])

    sign_in(tenant, hand)
    bill = raise_bill(tenant)["bill"]
    sign_out(tenant)

    sign_in(tenant, boss)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                json={"action": "reject", "notes": "Wrong amount"})
    sign_out(tenant)

    sign_in(tenant, hand)
    fixed = tenant.put(f"/api/employee/bills/{bill['id']}",
                       json={"amount": 180.0, "reference": "PO-4471"})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["total"] == 230.0

    again = tenant.post(f"/api/employee/bills/{bill['id']}/submit")
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "pending"
    sign_out(tenant)

    sign_in(tenant, boss)
    queue = tenant.get("/api/employee/approvals").json()["pending"]
    assert len(queue) == 1, "the second round should be a single fresh step"
    assert queue[0]["total"] == 230.0


def test_a_bill_with_an_approver_waiting_cannot_be_edited(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    sign_in(tenant, hand)
    bill = raise_bill(tenant)["bill"]
    res = tenant.put(f"/api/employee/bills/{bill['id']}", json={"amount": 5.0})
    assert res.status_code == 409, res.text


def test_it_climbs_every_rung_in_order(tenant):
    director = staff(tenant, permission_role="manager")
    boss = staff(tenant, permission_role="supervisor", reports_to=director["id"])
    hand = staff(tenant, reports_to=boss["id"])

    sign_in(tenant, hand)
    bill = raise_bill(tenant)
    assert bill["chain_length"] == 2
    sign_out(tenant)

    # The director is on the chain but it is not their turn.
    sign_in(tenant, director)
    queue = tenant.get("/api/employee/approvals").json()
    assert queue["pending"] == []
    assert len(queue["upcoming"]) == 1
    not_yet = queue["upcoming"][0]
    res = tenant.post(f"/api/employee/approvals/{not_yet['step_id']}/action",
                      json={"action": "approve", "notes": "Jumping the queue"})
    assert res.status_code == 409, res.text
    sign_out(tenant)

    sign_in(tenant, boss)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                json={"action": "approve", "notes": "Crew confirms it arrived"})
    sign_out(tenant)

    # Still not paid: it has only reached the director.
    mid = tenant.get(f"/api/bills/{bill['bill']['id']}").json()
    assert mid["approval_status"] == "pending"

    sign_in(tenant, director)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                json={"action": "approve", "notes": "Approved"})
    sign_out(tenant)

    done = tenant.get(f"/api/bills/{bill['bill']['id']}").json()
    assert done["status"] == "Approved for payment"


def test_nobody_can_decide_a_step_addressed_to_someone_else(tenant):
    boss = staff(tenant, permission_role="manager")
    other = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])

    sign_in(tenant, hand)
    raise_bill(tenant)
    sign_out(tenant)

    sign_in(tenant, boss)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    sign_out(tenant)

    sign_in(tenant, other)
    res = tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                      json={"action": "approve", "notes": "Not mine to sign"})
    assert res.status_code == 403, res.text


def test_staff_cannot_approve_or_see_everyone_elses_costs(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    mate = staff(tenant, reports_to=boss["id"])

    sign_in(tenant, hand)
    mine = raise_bill(tenant)["bill"]
    sign_out(tenant)

    sign_in(tenant, mate)
    # No approval rights at all.
    assert tenant.get("/api/employee/approvals").status_code == 403
    # And somebody else's cost is not in their list.
    listing = tenant.get("/api/employee/bills").json()
    assert listing["can_view_all"] is False
    assert [b["id"] for b in listing["bills"]] == []
    assert tenant.get(f"/api/employee/bills/{mine['id']}").status_code == 403


def test_a_manager_with_view_all_sees_the_lot(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])

    sign_in(tenant, hand)
    raise_bill(tenant)
    sign_out(tenant)

    sign_in(tenant, boss)
    listing = tenant.get("/api/employee/bills").json()
    assert listing["can_view_all"] is True
    assert len(listing["bills"]) == 1


def test_somebody_with_no_manager_needs_no_signoff(tenant):
    top = staff(tenant, permission_role="manager")
    sign_in(tenant, top)
    result = raise_bill(tenant)
    assert result["status"] == "approved"
    assert result["bill"]["status"] == "Approved for payment"


def test_a_decision_must_carry_a_reason(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    sign_in(tenant, hand)
    raise_bill(tenant)
    sign_out(tenant)

    sign_in(tenant, boss)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    res = tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                      json={"action": "approve", "notes": "   "})
    assert res.status_code == 400, res.text


def test_a_signed_out_visitor_gets_no_costs(client):
    assert client.get("/api/employee/bills").status_code == 401
    assert client.get("/api/employee/approvals").status_code == 401
    assert client.post("/api/employee/bills", json={"vendor_name": "X", "amount": 5}).status_code == 401


def test_a_bill_needs_a_supplier_and_an_amount(tenant):
    hand = staff(tenant)
    sign_in(tenant, hand)
    assert tenant.post("/api/employee/bills", json={"amount": 10}).status_code == 400
    assert tenant.post("/api/employee/bills", json={"vendor_name": "Jewson"}).status_code == 400
    assert tenant.post("/api/employee/bills",
                       json={"vendor_name": "Jewson", "amount": -5}).status_code == 400


def test_the_total_is_recomputed_not_trusted(tenant):
    hand = staff(tenant)
    sign_in(tenant, hand)
    result = raise_bill(tenant, amount=100.0, tax_amount=20.0, total=999999.0)
    assert result["bill"]["total"] == 120.0


def test_hr_can_change_what_somebody_may_do(tenant):
    hand = staff(tenant)
    res = tenant.put(f"/api/employees/{hand['id']}/permissions",
                     json={"permission_role": "finance"})
    assert res.status_code == 200, res.text
    assert "bills.pay" in res.json()["permissions"]

    sign_in(tenant, hand)
    me = tenant.get("/api/employee/auth/me").json()
    assert me["permission_role"] == "finance"
    assert "bills.pay" in me["permissions"]


def test_an_unknown_access_level_is_refused(tenant):
    hand = staff(tenant)
    res = tenant.put(f"/api/employees/{hand['id']}/permissions",
                     json={"permission_role": "director_of_everything"})
    assert res.status_code == 400, res.text
