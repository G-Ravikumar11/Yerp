"""Clearing many at once: each goes through the same delete as the single one, and one that is refused does not stop the rest."""
from test_delete_work_order import book, live_order, measure, raise_a_bill


def test_many_work_orders_go_in_one_request_and_what_hung_off_them_with_them(tenant):
    made = [live_order(tenant, pay_advance=False) for _ in range(3)]
    bill = raise_a_bill(tenant, made[0])
    res = tenant.post("/api/wo/orders/bulk-delete", json={"ids": [o["id"] for o in made]})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["deleted"] == 3 and not out["failed"], out
    for o in made:
        assert tenant.get("/api/wo/orders/%d" % o["id"]).status_code == 404
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).status_code == 404


def test_an_id_that_is_gone_or_never_was_does_not_stop_the_others(tenant):
    a, b = live_order(tenant, pay_advance=False), live_order(tenant, pay_advance=False)
    out = tenant.post("/api/wo/orders/bulk-delete", json={"ids": [a["id"], 987654, a["id"], b["id"], "x"]}).json()
    assert out["deleted"] == 2 and out["gone"] == 1 and not out["failed"], out


def test_bills_entries_and_vendors_can_be_cleared_in_bulk(tenant):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    for q in (5, 6, 7):
        measure(tenant, order["id"], item, q)
    ids = [e["id"] for e in book(tenant, order["id"])["entries"]]
    out = tenant.post("/api/sub-mb/entries/bulk-delete", json={"ids": ids}).json()
    assert out["deleted"] == 3 and not book(tenant, order["id"])["entries"], out
    bill = raise_a_bill(tenant, order)
    out = tenant.post("/api/sub-bills/bulk-delete", json={"ids": [bill["id"]]}).json()
    assert out["deleted"] == 1
    out = tenant.post("/api/wo/contractors/bulk-delete", json={"ids": [order["contractor_id"]]}).json()
    assert out["deleted"] == 1
    assert tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 404


def test_a_refused_one_is_named_and_the_rest_still_go(tenant):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 10)
    measure(tenant, order["id"], item, 5)
    bill = raise_a_bill(tenant, order)            # draws both entries onto a draft bill
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})     # a sent bill: its entries cannot be removed
    ids = [e["id"] for e in book(tenant, order["id"])["entries"]]
    extra = measure(tenant, order["id"], item, 1)
    fresh = [e["id"] for e in book(tenant, order["id"])["entries"] if e["id"] not in ids]
    out = tenant.post("/api/sub-mb/entries/bulk-delete", json={"ids": ids + fresh}).json()
    assert len(out["failed"]) == len(ids) and out["deleted"] == len(fresh), out
    assert all(f["reason"] for f in out["failed"]) and extra


def test_only_the_owner_clears_orders_and_bills_in_bulk(tenant, portal):
    from test_sub_contractor_certificate import staff, sign_in
    order = live_order(tenant, pay_advance=False)
    emp = staff(tenant, "project_manager")
    sign_in(portal, emp)
    out = portal.post("/api/wo/orders/bulk-delete", json={"ids": [order["id"]]})
    assert out.status_code in (200, 401, 403)
    if out.status_code == 200:
        assert out.json()["deleted"] == 0 and out.json()["failed"]
    assert tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 200
