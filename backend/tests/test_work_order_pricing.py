"""Pricing a work order, and the order that is worth nothing.

The modal promises the order "prices itself as you go" and it did not: every
line opened at zero, nothing remembered what a code had ever been sold for,
and an order where every rate was left at zero was created quite happily. It
then sat in the list at zero, measured at zero and billed at zero.
"""
import uuid


def fg(tenant, name=None):
    res = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": name or ("SUPPLY %s" % uuid.uuid4().hex[:6]),
         "units_of_measure": "Meters"}]})
    assert res.status_code == 200, res.text
    return res.json()["codes"][0]


def job(tenant):
    return tenant.post("/api/jobs", json={
        "name": "Vizag STP", "customer_name": "L&T"}).json()


def item_named(tenant, code):
    return [i for i in tenant.get("/api/erp/items").json()["items"]
            if i["item_code"] == code][0]


# --- An order worth nothing ---------------------------------------------------

def test_an_order_priced_entirely_at_zero_is_refused(tenant):
    """It would measure at zero and bill at zero for ever."""
    res = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"],
        "lines": [{"code": fg(tenant), "qty": 100, "rate": 0}]})
    assert res.status_code == 400
    assert "worth nothing" in res.json()["detail"].lower()


def test_one_priced_line_is_enough_to_carry_a_free_one(tenant):
    """A free issue line is normal; every line free is not."""
    paid, free = fg(tenant), fg(tenant)
    res = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"],
        "lines": [{"code": paid, "qty": 10, "rate": 500},
                  {"code": free, "qty": 1, "rate": 0}]})
    assert res.status_code == 200, res.text
    assert res.json()["work_order"]["total_value"] == 5000


def test_a_negative_rate_is_still_refused(tenant):
    res = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"],
        "lines": [{"code": fg(tenant), "qty": 10, "rate": -5}]})
    assert res.status_code == 400


# --- Remembering what a code was sold at --------------------------------------

def test_a_new_code_has_no_price_yet(tenant):
    assert item_named(tenant, fg(tenant))["last_rate"] == 0


def test_selling_something_remembers_what_it_went_for(tenant):
    code = fg(tenant)
    tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"],
        "lines": [{"code": code, "qty": 100, "rate": 62.5}]})
    assert item_named(tenant, code)["last_rate"] == 62.5


def test_the_newest_price_wins(tenant):
    """An offer, not a rule - prices move, and the latest is the useful one."""
    code = fg(tenant)
    for rate in (50, 75):
        tenant.post("/api/erp/work-orders/build", json={
            "job_id": job(tenant)["id"],
            "lines": [{"code": code, "qty": 10, "rate": rate}]})
    assert item_named(tenant, code)["last_rate"] == 75


def test_a_free_line_does_not_wipe_a_remembered_price(tenant):
    """Giving one away once must not forget what it is normally worth."""
    code, other = fg(tenant), fg(tenant)
    tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"],
        "lines": [{"code": code, "qty": 10, "rate": 400}]})
    tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"],
        "lines": [{"code": other, "qty": 1, "rate": 900},
                  {"code": code, "qty": 1, "rate": 0}]})
    assert item_named(tenant, code)["last_rate"] == 400


def test_a_rate_carries_four_decimals(tenant):
    """Rates are priced finer than money is rounded."""
    code = fg(tenant)
    tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"],
        "lines": [{"code": code, "qty": 1000, "rate": 12.3456}]})
    assert item_named(tenant, code)["last_rate"] == 12.3456


def test_a_reorder_level_survives_an_edit_that_omits_it(tenant):
    """None means leave it alone, so a form that does not send it is safe."""
    code = fg(tenant)
    item = item_named(tenant, code)
    tenant.put("/api/erp/items/%d" % item["id"], json={
        "kind": "FG", "item_name": item["item_name"],
        "units_of_measure": "Meters", "reorder_level": 25})
    assert item_named(tenant, code)["reorder_level"] == 25
    tenant.put("/api/erp/items/%d" % item["id"], json={
        "kind": "FG", "item_name": "Renamed", "units_of_measure": "Meters"})
    assert item_named(tenant, code)["reorder_level"] == 25
