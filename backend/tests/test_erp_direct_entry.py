"""Entering this data without a spreadsheet.

The upload path spends its effort detecting mistakes after they are made:
a code that already exists, a unit that is not a unit, an FG code on a job
that never sold it. Entered here those have nowhere to occur - the code is
issued, and every picker is built from the same list the server validates
against. These tests hold that line.
"""


def make_job(tenant, **over):
    payload = {"name": "Plot 7", "customer_name": "Acme", "status": "in_progress"}
    payload.update(over)
    return tenant.post("/api/jobs", json=payload).json()


def add(tenant, **over):
    payload = {"kind": "RM", "item_name": "20MM CONDUIT"}
    payload.update(over)
    return tenant.post("/api/erp/items", json=payload)


# --- Codes are issued, not typed -------------------------------------------

def test_a_code_is_issued_when_none_is_given(tenant):
    assert add(tenant).json()["item_code"] == "RM0001"
    assert add(tenant, item_name="25MM").json()["item_code"] == "RM0002"


def test_the_two_series_are_independent(tenant):
    assert add(tenant, kind="RM").json()["item_code"] == "RM0001"
    assert add(tenant, kind="FG", item_name="SUPPLY").json()["item_code"] == "FG0001"


def test_the_next_code_can_be_asked_for_before_saving(tenant):
    add(tenant)
    assert tenant.get("/api/erp/items/next-code?kind=RM").json()["item_code"] == "RM0002"


def test_a_batch_does_not_issue_one_code_twice(tenant):
    """Each row must claim its own number even though none are committed yet."""
    r = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "RM", "item_name": "A"},
        {"kind": "RM", "item_name": "B"},
        {"kind": "RM", "item_name": "C"}]}).json()
    assert r["codes"] == ["RM0001", "RM0002", "RM0003"]
    assert len(set(r["codes"])) == 3


def test_an_existing_scheme_can_still_be_typed(tenant):
    assert add(tenant, item_code="LEGACY-77").json()["item_code"] == "LEGACY-77"


def test_a_typed_code_that_clashes_is_refused(tenant):
    add(tenant, item_code="LEGACY-77")
    res = add(tenant, item_code="LEGACY-77", item_name="OTHER")
    assert res.status_code == 409
    assert "already in use" in res.json()["detail"]


def test_a_code_issued_around_a_gap_stays_free(tenant):
    add(tenant, item_code="RM0005")
    # Highest is 5, so the next issued is 6 - it does not reuse 1.
    assert add(tenant, item_name="NEXT").json()["item_code"] == "RM0006"


# --- Only valid values are accepted, from the same list the pickers use -----

def test_the_pickers_and_the_validator_share_one_list(tenant):
    vocab = tenant.get("/api/erp/vocabulary").json()
    for unit in vocab["units"]:
        assert add(tenant, item_name="X", units_of_measure=unit).status_code == 200
    for itype in vocab["item_types"]:
        assert add(tenant, item_name="X", item_type=itype).status_code == 200


def test_a_unit_that_is_not_a_unit_is_refused(tenant):
    res = add(tenant, units_of_measure="furlongs")
    assert res.status_code == 400 and "Unit must be" in res.json()["detail"]


def test_an_item_needs_a_name(tenant):
    assert add(tenant, item_name="   ").status_code == 400


def test_the_description_defaults_to_the_name(tenant):
    assert add(tenant, item_name="20MM CONDUIT").json()["description"] == "20MM CONDUIT"


def test_a_batch_is_all_or_nothing(tenant):
    """A half-saved batch leaves somebody working out which half."""
    res = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "RM", "item_name": "GOOD"},
        {"kind": "RM", "item_name": "BAD", "units_of_measure": "furlongs"}]})
    assert res.status_code == 400
    assert tenant.get("/api/erp/items").json()["counts"]["RM"] == 0


# --- Editing and removing ---------------------------------------------------

def test_an_item_can_be_corrected(tenant):
    item = add(tenant).json()
    res = tenant.put("/api/erp/items/%d" % item["id"],
                     json={"kind": "RM", "item_name": "20MM CONDUIT HEAVY",
                           "units_of_measure": "Meters"})
    assert res.status_code == 200
    listed = tenant.get("/api/erp/items").json()["items"][0]
    assert listed["item_name"] == "20MM CONDUIT HEAVY"
    assert listed["item_code"] == item["item_code"], "the code must not move"


def test_an_unused_item_can_be_removed(tenant):
    item = add(tenant).json()
    assert tenant.delete("/api/erp/items/%d" % item["id"]).status_code == 200


def test_an_item_in_use_cannot_be_removed(tenant):
    job = make_job(tenant)
    fg = add(tenant, kind="FG", item_name="SUPPLY").json()
    tenant.post("/api/erp/work-orders/build", json={"job_id": job["id"],
                "lines": [{"code": fg["item_code"], "qty": 10, "rate": 5}]})
    res = tenant.delete("/api/erp/items/%d" % fg["id"])
    assert res.status_code == 409 and "cannot be removed" in res.json()["detail"]


# --- Work orders built on screen -------------------------------------------

def build_order(tenant, lines=None):
    job = make_job(tenant)
    fg1 = add(tenant, kind="FG", item_name="SUPPLY", units_of_measure="Meters").json()
    fg2 = add(tenant, kind="FG", item_name="INSTALL", item_type="Service",
              units_of_measure="Meters").json()
    res = tenant.post("/api/erp/work-orders/build", json={"job_id": job["id"],
        "lines": lines or [{"code": fg1["item_code"], "qty": 800, "rate": 78},
                           {"code": fg2["item_code"], "qty": 800, "rate": 22}]})
    return job, fg1, fg2, res


def test_a_work_order_prices_itself(tenant):
    job, fg1, fg2, res = build_order(tenant)
    wo = res.json()["work_order"]
    assert wo["total_value"] == 80000.0
    assert wo["line_count"] == 2
    # The unit comes from the master, so it cannot disagree with the item.
    assert wo["lines"][0]["uom"] == "Meters"


def test_the_same_code_cannot_be_sold_twice_on_one_order(tenant):
    job = make_job(tenant)
    fg = add(tenant, kind="FG", item_name="SUPPLY").json()
    res = tenant.post("/api/erp/work-orders/build", json={"job_id": job["id"],
        "lines": [{"code": fg["item_code"], "qty": 1, "rate": 1},
                  {"code": fg["item_code"], "qty": 1, "rate": 1}]})
    assert res.status_code == 400 and "already on this order" in res.json()["detail"]


def test_raw_material_cannot_be_sold(tenant):
    job = make_job(tenant)
    rm = add(tenant).json()
    res = tenant.post("/api/erp/work-orders/build", json={"job_id": job["id"],
        "lines": [{"code": rm["item_code"], "qty": 1, "rate": 1}]})
    assert res.status_code == 400 and "not a finished goods code" in res.json()["detail"]


def test_a_line_needs_a_quantity(tenant):
    job = make_job(tenant)
    fg = add(tenant, kind="FG", item_name="SUPPLY").json()
    res = tenant.post("/api/erp/work-orders/build", json={"job_id": job["id"],
        "lines": [{"code": fg["item_code"], "qty": 0, "rate": 5}]})
    assert res.status_code == 400 and "more than zero" in res.json()["detail"]


def test_an_order_needs_at_least_one_line(tenant):
    job = make_job(tenant)
    assert tenant.post("/api/erp/work-orders/build",
                       json={"job_id": job["id"], "lines": []}).status_code == 400


# --- Budgets built on screen ------------------------------------------------

def budgeted(tenant):
    job, fg1, fg2, res = build_order(tenant)
    wo = res.json()["work_order"]
    rm1 = add(tenant, item_name="CONDUIT", units_of_measure="Meters").json()
    rm2 = add(tenant, item_name="COUPLER", units_of_measure="Nos").json()
    out = tenant.post("/api/erp/bom/build", json={"work_order_id": wo["id"], "lines": [
        {"fg_code": fg1["item_code"], "rm_code": rm1["item_code"], "qty": 820, "rate": 54},
        {"fg_code": fg2["item_code"], "rm_code": rm2["item_code"], "qty": 90, "rate": 33}]})
    return job, wo, fg1, fg2, rm1, rm2, out


def test_the_budget_gives_the_order_its_margin(tenant):
    job, wo, fg1, fg2, rm1, rm2, out = budgeted(tenant)
    after = out.json()["work_order"]
    assert after["budget_cost"] == 47250.0
    assert after["margin"] == 32750.0
    assert after["margin_percent"] == 40.9


def test_a_line_that_was_never_sold_cannot_be_budgeted(tenant):
    job, wo, fg1, fg2, rm1, rm2, out = budgeted(tenant)
    res = tenant.post("/api/erp/bom/build", json={"work_order_id": wo["id"],
        "lines": [{"fg_code": "FG9999", "rm_code": rm1["item_code"], "qty": 1, "rate": 1}]})
    assert res.status_code == 400 and "is not on" in res.json()["detail"]


def test_a_finished_good_cannot_be_its_own_material(tenant):
    job, wo, fg1, fg2, rm1, rm2, out = budgeted(tenant)
    res = tenant.post("/api/erp/bom/build", json={"work_order_id": wo["id"],
        "lines": [{"fg_code": fg1["item_code"], "rm_code": fg2["item_code"],
                   "qty": 1, "rate": 1}]})
    assert res.status_code == 400 and "not a raw material code" in res.json()["detail"]


def test_budgeting_twice_replaces_rather_than_doubles(tenant):
    job, wo, fg1, fg2, rm1, rm2, out = budgeted(tenant)
    again = tenant.post("/api/erp/bom/build", json={"work_order_id": wo["id"],
        "lines": [{"fg_code": fg1["item_code"], "rm_code": rm1["item_code"],
                   "qty": 10, "rate": 10}]}).json()
    assert again["total_cost"] == 100.0


def test_the_job_carries_what_was_sold_and_budgeted(tenant):
    job, wo, fg1, fg2, rm1, rm2, out = budgeted(tenant)
    costing = tenant.get("/api/jobs/%d" % job["id"]).json()["costing"]
    assert costing["ordered"] == 80000.0
    assert costing["budgeted"] == 47250.0
    assert costing["expected_margin"] == 32750.0


def test_a_stranger_can_do_none_of_this(client):
    assert client.get("/api/erp/vocabulary").status_code == 401
    assert client.post("/api/erp/items", json={"kind": "RM", "item_name": "X"}).status_code == 401
    assert client.post("/api/erp/work-orders/build",
                       json={"job_id": 1, "lines": []}).status_code == 401
