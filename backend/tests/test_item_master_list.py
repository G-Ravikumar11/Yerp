"""The item master list: stock, bulk actions, export of what is ticked, who may change what, and speed on a long list."""
import time

from sqlalchemy import event

import main
from app import models
from conftest import make_employee
from test_site_pricing import make_item


def client_id_of(item_id):
    with main.SessionLocal() as db:
        return db.get(models.DBItem, item_id).client_id


def test_the_list_carries_each_items_stock_in_one_pass(tenant):
    material = make_item(tenant, "STK-1", "Cement OPC 53", kind="RM", units_of_measure="Bags", item_type="Purchased")
    work = make_item(tenant, "WRK-1", "PCC M15")
    with main.SessionLocal() as db:
        db.add(models.DBStockBalance(client_id=client_id_of(material["id"]), item_code="STK-1", on_hand=120.5, uom="Bags"))
        db.commit()
    got = {i["item_code"]: i for i in tenant.get("/api/items").json()["items"]}
    assert got["STK-1"]["stock"] == 120.5 and got["WRK-1"]["stock"] is None, "no record in the store is not the same as none left"
    assert work["id"] != material["id"]


def test_bulk_deactivate_and_activate_are_all_or_nothing(tenant):
    a, b = make_item(tenant, "BLK-1", "One"), make_item(tenant, "BLK-2", "Two")
    off = tenant.post("/api/items/bulk-status", json={"ids": [a["id"], b["id"]], "is_active": False})
    assert off.status_code == 200 and off.json()["changed"] == 2
    assert tenant.get("/api/items", params={"status": "inactive"}).json()["total"] == 2
    bad = tenant.post("/api/items/bulk-status", json={"ids": [a["id"], 999999], "is_active": True})
    assert bad.status_code == 404
    assert tenant.get("/api/items", params={"status": "inactive"}).json()["total"] == 2, "nothing changed"
    assert tenant.post("/api/items/bulk-status", json={"ids": [], "is_active": True}).status_code == 422


def test_bulk_change_category_checks_the_category_and_moves_them_together(tenant):
    a, b = make_item(tenant, "CAT-1", "One"), make_item(tenant, "CAT-2", "Two")
    ok = tenant.post("/api/items/bulk-category", json={"ids": [a["id"], b["id"]], "item_category": "Cement"})
    assert ok.status_code == 200
    assert {i["item_category"] for i in tenant.get("/api/items").json()["items"]} == {"Cement"}
    assert tenant.post("/api/items/bulk-category", json={"ids": [a["id"]], "item_category": "Not set up"}).status_code == 422
    assert tenant.get("/api/items/%d" % a["id"]).json()["item"]["item_category"] == "Cement"


def test_export_can_be_limited_to_the_rows_ticked(tenant):
    a = make_item(tenant, "EXP-1", "One")
    make_item(tenant, "EXP-2", "Two")
    every = tenant.get("/api/items/export.xlsx")
    ticked = tenant.get("/api/items/export.xlsx", params={"ids": str(a["id"])})
    assert every.status_code == ticked.status_code == 200
    assert len(ticked.content) < len(every.content)


def test_one_company_cannot_change_anothers_items(tenant, second_tenant):
    a = make_item(tenant, "OWN-1", "Mine")
    assert second_tenant.post("/api/items/bulk-status", json={"ids": [a["id"]], "is_active": False}).status_code == 404
    assert tenant.get("/api/items/%d" % a["id"]).json()["item"]["is_active"] is True


def test_staff_without_the_item_right_can_read_but_not_change(tenant, portal):
    a = make_item(tenant, "PRM-1", "Item")
    emp = make_employee(tenant, password="EmpPass123")
    tenant.put("/api/employees/%d/permissions" % emp["id"], json={"permission_role": "staff", "permissions": ["self.service"]})
    assert portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"}).status_code == 200
    assert portal.get("/api/items").status_code == 200
    assert portal.post("/api/items/bulk-status", json={"ids": [a["id"]], "is_active": False}).status_code == 403
    assert portal.post("/api/items/bulk-category", json={"ids": [a["id"]], "item_category": "Cement"}).status_code == 403
    assert portal.patch("/api/items/%d/status" % a["id"], json={"is_active": False}).status_code == 403
    assert portal.post("/api/items", json={"item_name": "x", "units_of_measure": "Nos"}).status_code == 403


def test_a_long_list_is_paged_and_costs_a_handful_of_queries(tenant):
    first = make_item(tenant, "LONG-0", "Seed")
    cid = client_id_of(first["id"])
    with main.SessionLocal() as db:
        db.add_all([models.DBItem(client_id=cid, kind="FG", item_code="LONG-%05d" % n, item_name="Item number %d" % n, units_of_measure="Nos",
                                  item_category="Cement", is_active=True) for n in range(1, 5001)])
        db.commit()
    seen = []

    def count(conn, cursor, statement, *rest):
        seen.append(statement)

    event.listen(main.engine, "before_cursor_execute", count)
    try:
        started = time.time()
        res = tenant.get("/api/items", params={"page": 3, "page_size": 50, "q": "Item number", "category": "Cement"})
        took = time.time() - started
    finally:
        event.remove(main.engine, "before_cursor_execute", count)
    body = res.json()
    assert res.status_code == 200 and body["total"] == 5000 and len(body["items"]) == 50
    selects = [s for s in seen if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 12, "the page must not cost a query per row: %d" % len(selects)
    assert took < 3


def test_items_with_no_category_can_be_found_and_filed_together(tenant):
    a, b = make_item(tenant, "NOC-1", "Uncategorised one", item_category=""), make_item(tenant, "NOC-2", "Uncategorised two", item_category="")
    make_item(tenant, "HAS-1", "Has one", item_category="Cement")
    found = tenant.get("/api/items", params={"category": "__none__"}).json()
    assert {i["item_code"] for i in found["items"]} == {"NOC-1", "NOC-2"} and found["total"] == 2
    assert tenant.post("/api/items/bulk-category", json={"ids": [a["id"], b["id"]], "item_category": "Masonry"}).status_code == 200
    assert tenant.get("/api/items", params={"category": "__none__"}).json()["total"] == 0


def test_the_last_rate_from_before_is_offered_where_no_purchase_rate_is_kept(tenant):
    item = make_item(tenant, "LST-1", "Old rate")
    with main.SessionLocal() as db:
        db.get(models.DBItem, item["id"]).last_rate = 250.0
        db.commit()
    got = tenant.get("/api/items/%d" % item["id"]).json()["item"]
    assert got["purchase_rate"] == 0 and got["last_rate"] == 250.0
