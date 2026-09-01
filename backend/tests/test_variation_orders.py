"""Variations - the step that turns over-measured work into money.

The measurement book already prints "5 over the order" against a line the site
built past its ordered quantity. Until variations existed that was where it
stopped, and the extra work stayed done, measured and unpaid.

A variation drafts itself from that flag. What is tested here is mostly that
the app fills the thing in correctly on its own, because a variation somebody
has to retype is one nobody raises.
"""
import uuid

from conftest import make_employee
from test_measurement_and_ra_bills import placed_order, book, measure


PASSWORD = "Crew1234"


def over_measure(tenant, qty=1200):
    """An order for 1000 with 1200 actually built."""
    wo = placed_order(tenant, qty=1000, rate=60)
    line = book(tenant, wo["id"])["lines"][0]
    measure(tenant, wo["id"], line["line_id"], qty)
    return wo, line


# --- What the app proposes on its own ---------------------------------------

def test_suggests_nothing_when_the_order_is_not_over_run(tenant):
    wo = placed_order(tenant)
    line = book(tenant, wo["id"])["lines"][0]
    measure(tenant, wo["id"], line["line_id"], 400)
    out = tenant.get("/api/variations/suggest/%d" % wo["id"]).json()
    assert out["count"] == 0 and out["value"] == 0


def test_suggests_the_over_run_without_raising_anything(tenant):
    wo, line = over_measure(tenant)
    out = tenant.get("/api/variations/suggest/%d" % wo["id"]).json()
    assert out["count"] == 1
    assert out["lines"][0]["extra_qty"] == 200
    assert out["value"] == 200 * 60
    # Asking must not create one.
    assert tenant.get("/api/variations").json()["variations"] == []


def test_draws_itself_up_from_the_book(tenant):
    wo, line = over_measure(tenant)
    res = tenant.post("/api/variations", json={"work_order_id": wo["id"]})
    assert res.status_code == 200, res.text
    vo = res.json()["variation"]
    assert vo["origin"] == "measured"
    assert vo["number"].endswith("/VO-01")
    assert vo["value"] == 12000
    assert len(vo["lines"]) == 1
    got = vo["lines"][0]
    assert (got["ordered_qty"], got["measured_qty"], got["extra_qty"]) == (1000, 1200, 200)


def test_refuses_when_there_is_nothing_to_vary(tenant):
    wo = placed_order(tenant)
    res = tenant.post("/api/variations", json={"work_order_id": wo["id"]})
    assert res.status_code == 409
    assert "nothing to vary" in res.json()["detail"].lower()


def test_a_draft_order_cannot_be_varied(tenant):
    job = tenant.post("/api/jobs", json={"name": "J", "customer_name": "C"}).json()
    # An FG code is one deliverable on one contract, so a repeat is refused
    # rather than skipped - this needs a name of its own.
    code = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "DRAFT ITEM %s" % uuid.uuid4().hex[:6],
         "units_of_measure": "Nos"}]})
    assert code.status_code == 200, code.text
    code = code.json()["codes"][0]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "lines": [{"code": code, "qty": 1, "rate": 1}]
    }).json()["work_order"]          # left as a draft on purpose
    res = tenant.post("/api/variations", json={"work_order_id": wo["id"]})
    assert res.status_code == 409
    assert "after it has been placed" in res.json()["detail"]


# --- Approving it raises the order ------------------------------------------

def test_approval_lifts_the_ordered_quantity_and_clears_the_over_run(tenant):
    wo, line = over_measure(tenant)
    vo = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    tenant.post("/api/variations/%d/submit" % vo["id"])
    tenant.post("/api/variations/%d/approve" % vo["id"])

    after = book(tenant, wo["id"])["lines"][0]
    assert after["ordered_qty"] == 1200          # raised to what was built
    assert after["over_measured"] == 0           # the flag is gone
    assert after["balance_to_measure"] == 0
    assert book(tenant, wo["id"])["summary"]["lines_over_measured"] == 0


def test_approval_raises_the_order_value(tenant):
    wo, _ = over_measure(tenant)
    vo = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    assert vo["order_value_before"] == 60000
    assert vo["order_value_after"] == 72000
    tenant.post("/api/variations/%d/submit" % vo["id"])
    tenant.post("/api/variations/%d/approve" % vo["id"])
    got = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    assert got["total_value"] == 72000


def test_the_extra_work_becomes_billable(tenant):
    """The point of the whole thing: unbilled value the order now covers."""
    wo, _ = over_measure(tenant)
    vo = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    tenant.post("/api/variations/%d/submit" % vo["id"])
    tenant.post("/api/variations/%d/approve" % vo["id"])
    bill = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()
    assert bill["bill"]["this_bill"] == 1200 * 60


def test_a_new_item_becomes_a_real_order_line(tenant):
    """Work nobody priced has to be measurable afterwards, so it joins the order."""
    wo, _ = over_measure(tenant)
    vo = tenant.post("/api/variations", json={
        "work_order_id": wo["id"], "reason": "Extra chamber at CH 240",
        "lines": [{"fg_code": "EXTRA-01", "description": "RCC chamber",
                   "uom": "Nos", "extra_qty": 4, "rate": 2500}]}).json()["variation"]
    assert vo["origin"] == "manual"
    assert vo["lines"][0]["is_new_item"] is True
    tenant.post("/api/variations/%d/submit" % vo["id"])
    tenant.post("/api/variations/%d/approve" % vo["id"])

    codes = [l["fg_code"] for l in book(tenant, wo["id"])["lines"]]
    assert "EXTRA-01" in codes
    got = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    assert got["total_value"] == 60000 + 10000


def test_approving_twice_does_not_raise_the_order_twice(tenant):
    wo, _ = over_measure(tenant)
    vo = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    tenant.post("/api/variations/%d/submit" % vo["id"])
    tenant.post("/api/variations/%d/approve" % vo["id"])
    again = tenant.post("/api/variations/%d/approve" % vo["id"])
    assert again.status_code == 409
    got = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    assert got["total_value"] == 72000


# --- The state machine -------------------------------------------------------

def test_a_draft_cannot_be_approved_without_being_submitted(tenant):
    wo, _ = over_measure(tenant)
    vo = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    res = tenant.post("/api/variations/%d/approve" % vo["id"])
    assert res.status_code == 409


def test_rejection_needs_a_reason_and_sends_it_back_to_draft(tenant):
    wo, _ = over_measure(tenant)
    vo = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    tenant.post("/api/variations/%d/submit" % vo["id"])
    assert tenant.post("/api/variations/%d/reject" % vo["id"], json={}).status_code == 400
    out = tenant.post("/api/variations/%d/reject" % vo["id"],
                      json={"comments": "Get the client to agree the rate first"}).json()
    assert out["variation"]["status"] == "DRAFT"
    assert "rate" in out["variation"]["rejection_reason"]


def test_a_rejected_variation_does_not_raise_the_order(tenant):
    wo, _ = over_measure(tenant)
    vo = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    tenant.post("/api/variations/%d/submit" % vo["id"])
    tenant.post("/api/variations/%d/reject" % vo["id"], json={"comments": "no"})
    got = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    assert got["total_value"] == 60000
    assert book(tenant, wo["id"])["lines"][0]["over_measured"] == 200


def test_only_a_draft_can_be_deleted(tenant):
    wo, _ = over_measure(tenant)
    vo = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    tenant.post("/api/variations/%d/submit" % vo["id"])
    assert tenant.delete("/api/variations/%d" % vo["id"]).status_code == 409


def test_numbering_runs_per_order(tenant):
    wo, _ = over_measure(tenant)
    first = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    second = tenant.post("/api/variations", json={
        "work_order_id": wo["id"],
        "lines": [{"fg_code": "X", "extra_qty": 1, "rate": 10}]}).json()["variation"]
    assert first["number"].endswith("/VO-01")
    assert second["number"].endswith("/VO-02")


# --- Who may do it -----------------------------------------------------------

def test_someone_denied_approval_may_raise_one_but_not_approve_it(tenant):
    """The person who measured the extra work must not also agree to pay for it."""
    wo, _ = over_measure(tenant)
    # No preset role manages work orders without also being able to approve
    # them, so the separation is made the way the owner actually makes it:
    # by withholding that one right from this person.
    engineer = make_employee(tenant, permission_role="manager", password=PASSWORD)
    tenant.put("/api/employees/%d" % engineer["id"], json={
        "status": "active", "denied_permissions": "subcontracts.approve"})
    tenant.post("/api/employee/auth/login",
                json={"email": engineer["email"], "password": PASSWORD})

    raised = tenant.post("/api/variations", json={"work_order_id": wo["id"]})
    assert raised.status_code == 200, raised.text
    vo = raised.json()["variation"]
    tenant.post("/api/variations/%d/submit" % vo["id"])
    assert tenant.post("/api/variations/%d/approve" % vo["id"]).status_code == 403
    tenant.post("/api/employee/auth/logout")


def test_the_summary_separates_agreed_money_from_asked_for_money(tenant):
    wo, _ = over_measure(tenant)
    approved = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    tenant.post("/api/variations/%d/submit" % approved["id"])
    tenant.post("/api/variations/%d/approve" % approved["id"])
    tenant.post("/api/variations", json={
        "work_order_id": wo["id"],
        "lines": [{"fg_code": "Y", "extra_qty": 2, "rate": 500}]})

    s = tenant.get("/api/variations").json()["summary"]
    assert s["approved_value"] == 12000
    assert s["pending_value"] == 1000
    assert s["raised"] == 2
