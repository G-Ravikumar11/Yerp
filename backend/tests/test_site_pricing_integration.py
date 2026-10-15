"""Site pricing alongside the documents drawn from a BOQ, and the migration that adds its columns to an existing database."""
from sqlalchemy import create_engine, text

import main
from app.db import migrations
from test_boq import contractor_order, make_boq, saved
from test_site_pricing import put, rows


def lines_of(tenant, boq):
    return {l["group_code"]: l for l in saved(tenant, boq)["lines"]}


def test_pricing_a_site_leaves_the_clients_work_order_and_the_contractors_rate_alone(tenant):
    _, boq = make_boq(tenant)
    lines = lines_of(tenant, boq)
    wo = tenant.post("/api/boqs/%d/client-order" % boq["id"], json={}).json()["work_order"]
    before = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    order, _, res = contractor_order(tenant, lines, [(lines["EXC"], 300, 150)])
    site = boq["job_id"]
    exc = next(r for r in rows(tenant, site) if r["description"] == "Excavation in all types of soil")
    assert exc["mapped"] and exc["quantity"] == 500
    assert put(tenant, site, exc["item_id"], 999).status_code == 200
    assert tenant.post("/api/sites/%d/item-prices/%d/finalize" % (site, exc["item_id"]), json={}).status_code == 200
    done = tenant.post("/api/sites/%d/item-prices/apply-to-boq" % site, json={})
    assert done.status_code == 200 and done.json()["applied"] == 1
    # The BOQ line now carries the site rate...
    assert next(l for l in tenant.get("/api/boqs/%d" % boq["id"]).json()["lines"] if l["group_code"] == "EXC")["rate"] == 999
    # ...but the client's work order is exactly as it was drawn,
    after = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    assert [(l["fg_code"], l["qty"], l["rate"], l["amount"]) for l in after["lines"]] == [
        (l["fg_code"], l["qty"], l["rate"], l["amount"]) for l in before["lines"]]
    assert after["total_value"] == before["total_value"] == 1472800
    # ...and the contractor keeps his own rate: the site's selling rate is never substituted for it.
    full = tenant.get("/api/wo/orders/%d" % order["id"]).json()
    item = (full.get("order") or full)["items"][0]
    assert item["boq_key"] == lines["EXC"]["key"] and float(item["unit_rate"]) == 150
    tracker = {r["group_code"]: r for r in tenant.get("/api/boqs/%d/tracker" % boq["id"]).json()["rows"] if r["kind"] != "section"}
    assert tracker["EXC"]["contractor_rate"] == 150 and tracker["EXC"]["given"] == 300


def test_deactivating_an_item_keeps_every_document_that_uses_it(tenant):
    _, boq = make_boq(tenant)
    lines = lines_of(tenant, boq)
    wo = tenant.post("/api/boqs/%d/client-order" % boq["id"], json={}).json()["work_order"]
    contractor_order(tenant, lines, [(lines["RCC"], 10, 100)])
    rcc = next(r for r in rows(tenant, boq["job_id"]) if r["description"].startswith("M25 grade RCC"))
    assert tenant.patch("/api/items/%d/status" % rcc["item_id"], json={"is_active": False}).status_code == 200
    assert tenant.get("/api/boqs/%d" % boq["id"]).status_code == 200
    again = {l["fg_code"] for l in tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["lines"]}
    assert rcc["item_code"] in again
    t = {r["group_code"]: r for r in tenant.get("/api/boqs/%d/tracker" % boq["id"]).json()["rows"] if r["kind"] != "section"}
    assert t["RCC"]["given"] == 10


def test_a_database_made_before_this_gets_the_new_columns_and_keeps_its_rows(tmp_path, monkeypatch):
    old = create_engine("sqlite:///%s" % (tmp_path / "old.db"))
    with old.begin() as c:
        c.execute(text("CREATE TABLE erp_items (id INTEGER PRIMARY KEY, client_id INTEGER, kind VARCHAR, item_code VARCHAR, item_name VARCHAR, "
                       "description VARCHAR, units_of_measure VARCHAR, is_active BOOLEAN)"))
        c.execute(text("CREATE TABLE boq_lines (id INTEGER PRIMARY KEY, boq_id INTEGER, revision_id INTEGER, key VARCHAR, kind VARCHAR, "
                       "description TEXT, item_code VARCHAR, quantity FLOAT, rate FLOAT, amount FLOAT)"))
        c.execute(text("INSERT INTO erp_items VALUES (1, 7, 'FG', 'OLD-1', 'Old item', 'Old description', 'cum', 1)"))
        c.execute(text("INSERT INTO boq_lines VALUES (1, 1, 1, 'k1', 'item', 'Old line', 'OLD-1', 5, 10, 50)"))
    monkeypatch.setattr(migrations, "engine", old)
    migrations.migrate_sqlite()
    migrations.migrate_sqlite()                                   # and again: running it twice changes nothing
    with old.connect() as c:
        items = {r[1] for r in c.execute(text("PRAGMA table_info(erp_items)"))}
        lines = {r[1] for r in c.execute(text("PRAGMA table_info(boq_lines)"))}
        assert {"item_category", "item_subcategory", "specification", "purchase_rate", "selling_rate", "preferred_supplier",
                "remarks", "created_by_name", "updated_by_name", "updated_at"} <= items
        assert "item_id" in lines
        item = c.execute(text("SELECT item_code, item_name, description, units_of_measure, item_category, selling_rate FROM erp_items")).one()
        assert tuple(item)[:4] == ("OLD-1", "Old item", "Old description", "cum") and item[4] == "" and item[5] == 0
        line = c.execute(text("SELECT key, item_code, quantity, rate, amount, item_id FROM boq_lines")).one()
        assert tuple(line) == ("k1", "OLD-1", 5, 10, 50, None)
    assert not [e for e in migrations.MIGRATION_ERRORS if "item master" in e]
    assert main  # the app module still imports with the patched engine restored by monkeypatch
