"""People are on sites, and only the sites they are on.

Every member of staff could see every live project in the business: the job
picker on a timesheet, on a cost, on an order, listed all of them. On a site
that is somebody else's customer at somebody else's rates, that is not a
detail - it is the whole commercial position of another job, visible to anyone
with a login.

Assignment is opt-in so nothing changes under a business that has not used it
yet, and these hold both halves of that: unassigned sees everything, assigned
sees exactly its own.
"""

from test_jobs_and_orders import staff, sign_in, sign_out


def make_job(tenant, name):
    return tenant.post("/api/jobs", json={
        "name": name, "customer_name": "Someone", "status": "in_progress"}).json()


def sites_of(tenant, emp_id):
    return tenant.get("/api/employees/%d" % emp_id).json()


# --- assignment -------------------------------------------------------------

def test_somebody_with_no_site_still_sees_them_all(tenant, portal):
    """The existing behaviour, kept deliberately: shipping this must not lock
    an entire workforce out of every job overnight."""
    a, b = make_job(tenant, "Fairview"), make_job(tenant, "Riverside")
    hand = staff(tenant)
    sign_in(portal, hand)
    seen = portal.get("/api/employee/jobs").json()["jobs"]
    assert {j["id"] for j in seen} == {a["id"], b["id"]}
    assert sites_of(tenant, hand["id"])["all_sites"] is True


def test_a_site_can_be_assigned_and_it_is_the_only_one_they_see(tenant, portal):
    a, b = make_job(tenant, "Fairview"), make_job(tenant, "Riverside")
    hand = staff(tenant)
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": [a["id"]]})

    sign_in(portal, hand)
    seen = portal.get("/api/employee/jobs").json()["jobs"]
    assert [j["id"] for j in seen] == [a["id"]]
    assert b["id"] not in [j["id"] for j in seen]


def test_the_profile_says_which_sites(tenant):
    a = make_job(tenant, "Fairview")
    hand = staff(tenant)
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": [a["id"]]})
    row = sites_of(tenant, hand["id"])
    assert row["site_ids"] == [a["id"]]
    assert row["all_sites"] is False
    assert row["site_names"][0].endswith("Fairview")


def test_sites_can_be_handed_over(tenant):
    a, b = make_job(tenant, "Fairview"), make_job(tenant, "Riverside")
    hand = staff(tenant)
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": [a["id"]]})
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": [b["id"]]})
    assert sites_of(tenant, hand["id"])["site_ids"] == [b["id"]]


def test_clearing_the_list_gives_them_everything_again(tenant):
    a = make_job(tenant, "Fairview")
    hand = staff(tenant)
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": [a["id"]]})
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": []})
    assert sites_of(tenant, hand["id"])["all_sites"] is True


def test_a_site_from_another_business_cannot_be_assigned(tenant, second_tenant):
    theirs = second_tenant.post("/api/jobs", json={
        "name": "Not yours", "status": "in_progress"}).json()
    hand = staff(tenant)
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": [theirs["id"]]})
    assert sites_of(tenant, hand["id"])["site_ids"] == []


# --- enforcement, not just the picker ---------------------------------------

def test_a_cost_cannot_be_booked_to_a_site_they_are_not_on(tenant, portal):
    """The picker would never offer it. The API has to refuse it anyway, or
    the restriction is decoration."""
    mine, theirs = make_job(tenant, "Fairview"), make_job(tenant, "Riverside")
    hand = staff(tenant)
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": [mine["id"]]})

    sign_in(portal, hand)
    ok = portal.post("/api/employee/bills", json={
        "vendor_name": "Jewson", "amount": 500.0, "job_id": mine["id"]})
    assert ok.status_code == 200, ok.text

    blocked = portal.post("/api/employee/bills", json={
        "vendor_name": "Jewson", "amount": 500.0, "job_id": theirs["id"]})
    assert blocked.status_code == 403
    assert "not assigned to that site" in blocked.json()["detail"].lower()


def test_hours_cannot_be_booked_to_a_site_they_are_not_on(tenant, portal):
    mine, theirs = make_job(tenant, "Fairview"), make_job(tenant, "Riverside")
    hand = staff(tenant)
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": [mine["id"]]})

    sign_in(portal, hand)
    blocked = portal.post("/api/employee/attendance/job", json={"job_id": theirs["id"]})
    assert blocked.status_code == 403


def test_a_cost_with_no_site_is_still_allowed(tenant, portal):
    """Not everything a business buys belongs to a job, and an overhead must
    not become impossible to record just because sites are in use."""
    mine = make_job(tenant, "Fairview")
    hand = staff(tenant)
    tenant.put("/api/employees/%d" % hand["id"], json={"site_ids": [mine["id"]]})
    sign_in(portal, hand)
    res = portal.post("/api/employee/bills", json={"vendor_name": "BT", "amount": 90.0})
    assert res.status_code == 200, res.text
