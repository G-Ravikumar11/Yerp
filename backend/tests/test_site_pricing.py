"""The BOQ item master and site-wise pricing: the item is shared, the price is each site's own."""
import main
from app import models
from conftest import make_employee
from test_boq import make_boq, saved
from test_boq_variations import ready, variation


def make_item(tenant, code="PCC-M15", name="PCC M15 in foundation", **extra):
    body = {"item_code": code, "item_name": name, "units_of_measure": "cum", "item_category": "Concrete (PCC / RCC)",
            "item_type": "Work", "specification": "M15"}
    body.update(extra)
    res = tenant.post("/api/items", json=body)
    assert res.status_code == 200, res.text
    return res.json()["item"]


def site_with(tenant, name, items):
    """A site whose BOQ lines are (item_code, qty, rate), under one section."""
    jid, boq = make_boq(tenant, name)
    lines = [{"kind": "section", "description": "SUBSTRUCTURE"}] + [
        {"kind": "item", "description": "Supply and lay %s" % code, "uom": "cum", "quantity": qty, "rate": rate, "item_code": code}
        for code, qty, rate in items]
    res = tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines})
    assert res.status_code == 200, res.text
    return jid, boq


def rows(tenant, site):
    return tenant.get("/api/sites/%d/boq-items" % site).json()["rows"]


def put(tenant, site, item_id, rate, **extra):
    return tenant.put("/api/sites/%d/item-prices/%d" % (site, item_id), json={"rate": rate, **extra})


# --- the item master ------------------------------------------------------------------------------------------------

def test_codes_are_trimmed_upper_cased_unique_and_generated_when_blank(tenant):
    item = make_item(tenant, code="  pcc/m15.a ")
    assert item["item_code"] == "PCC/M15.A"
    dup = tenant.post("/api/items", json={"item_code": "pcc/m15.a", "item_name": "Again", "units_of_measure": "cum"})
    assert dup.status_code == 409 and "already used by" in dup.json()["detail"] and "Again" not in dup.json()["detail"]
    for bad in ("HAS SPACE", "bad#code", "X" * 31):
        assert tenant.post("/api/items", json={"item_code": bad, "item_name": "n", "units_of_measure": "cum"}).status_code == 400
    auto = tenant.post("/api/items", json={"item_name": "Cement OPC 53", "units_of_measure": "Bags"})
    assert auto.status_code == 200 and auto.json()["item"]["item_code"]
    with main.SessionLocal() as db:
        assert db.query(models.DBItem).filter(models.DBItem.item_code == "PCC/M15.A").count() == 1


def test_editing_keeps_the_code_and_validates_unit_type_and_category(tenant):
    item = make_item(tenant)
    body = {"item_name": "PCC M15 (revised)", "units_of_measure": "cum", "item_code": "SOMETHING-ELSE", "item_type": "Work",
            "item_category": "Concrete (PCC / RCC)", "selling_rate": 6000}
    res = tenant.put("/api/items/%d" % item["id"], json=body)
    assert res.status_code == 200 and res.json()["item"]["item_code"] == "PCC-M15" and res.json()["item"]["selling_rate"] == 6000
    assert tenant.put("/api/items/%d" % item["id"], json={**body, "units_of_measure": "furlong"}).status_code == 400
    assert tenant.put("/api/items/%d" % item["id"], json={**body, "item_type": "Nonsense"}).status_code == 400
    assert tenant.put("/api/items/%d" % item["id"], json={**body, "item_category": "Not set up"}).status_code == 422
    assert tenant.put("/api/items/%d" % item["id"], json={**body, "selling_rate": -1}).status_code == 422


def test_categories_are_configurable(tenant):
    cats = tenant.get("/api/item-categories").json()["categories"]
    assert "Cement" in [c["name"] for c in cats]
    added = tenant.post("/api/item-categories", json={"name": "Glazing"}).json()["categories"]
    parent = next(c for c in added if c["name"] == "Glazing")
    assert tenant.post("/api/item-categories", json={"name": "glazing"}).status_code == 409
    tenant.post("/api/item-categories", json={"name": "Toughened", "parent_id": parent["id"]})
    item = make_item(tenant, "GLZ-1", "Toughened glass", item_category="Glazing", item_subcategory="Toughened")
    assert item["item_subcategory"] == "Toughened"
    renamed = tenant.patch("/api/item-categories/%d" % parent["id"], json={"name": "Glass & Glazing"})
    assert renamed.status_code == 200
    assert tenant.get("/api/items/%d" % item["id"]).json()["item"]["item_category"] == "Glass & Glazing"


def test_list_filters_sorts_paginates_and_exports(tenant):
    make_item(tenant, "A-1", "Alpha"), make_item(tenant, "B-1", "Beta", item_category="Cement", units_of_measure="Bags")
    make_item(tenant, "C-1", "Gamma")
    res = tenant.get("/api/items", params={"category": "Cement"}).json()
    assert [i["item_code"] for i in res["items"]] == ["B-1"] and res["total"] == 1
    page = tenant.get("/api/items", params={"sort": "name", "direction": "desc", "page_size": 2, "page": 1}).json()
    assert [i["item_code"] for i in page["items"]] == ["C-1", "B-1"] and page["total"] == 3
    assert tenant.get("/api/items", params={"q": "alph"}).json()["total"] == 1
    assert tenant.get("/api/items/export.xlsx").status_code == 200


def test_deactivating_keeps_history_and_blocks_new_mapping(tenant):
    item = make_item(tenant)
    site, _ = site_with(tenant, "Site A", [("PCC-M15", 10, 100)])
    off = tenant.patch("/api/items/%d/status" % item["id"], json={"is_active": False})
    assert off.status_code == 200 and off.json()["item"]["is_active"] is False
    assert [r["item_code"] for r in rows(tenant, site)] == ["PCC-M15"], "existing BOQ lines keep their item"
    other = make_item(tenant, "PCC-M20", "PCC M20")
    tenant.patch("/api/items/%d/status" % other["id"], json={"is_active": False})
    _, boq2 = make_boq(tenant, "Site B")
    j2 = boq2["job_id"]
    tenant.put("/api/boqs/%d/lines" % boq2["id"], json={"lines": [{"kind": "item", "description": "Blank line", "uom": "cum", "quantity": 1}]})
    key = rows(tenant, j2)[0]["line_key"]
    assert tenant.post("/api/sites/%d/boq-items/%s/map-item" % (j2, key), json={"item_id": other["id"]}).status_code == 409


# --- site pricing ---------------------------------------------------------------------------------------------------

def test_one_item_three_sites_three_rates_and_the_default_does_not_overwrite_them(tenant):
    item = make_item(tenant, selling_rate=6000)
    a, _ = site_with(tenant, "Site A", [("PCC-M15", 10, 1)])
    b, _ = site_with(tenant, "Site B", [("PCC-M15", 20, 1)])
    c, _ = site_with(tenant, "Site C", [("PCC-M15", 30, 1)])
    for site, rate in ((a, 6000), (b, 6400), (c, 5850)):
        assert put(tenant, site, item["id"], rate).status_code == 200
        assert tenant.post("/api/sites/%d/item-prices/%d/finalize" % (site, item["id"]), json={}).status_code == 200
    assert [rows(tenant, s)[0]["site_rate"] for s in (a, b, c)] == [6000, 6400, 5850]
    assert tenant.get("/api/items/%d/sites" % item["id"]).json()["item"]["sites"] == 3
    # The master's default moves: the finalised site rates stay as they were, and are flagged.
    moved = tenant.put("/api/items/%d" % item["id"], json={"item_name": item["item_name"], "units_of_measure": "cum", "selling_rate": 7000,
                                                           "item_category": "Concrete (PCC / RCC)", "item_type": "Work"})
    assert moved.status_code == 200
    got = [rows(tenant, s)[0] for s in (a, b, c)]
    assert [g["site_rate"] for g in got] == [6000, 6400, 5850] and {g["status"] for g in got} == {"Changed"}
    assert got[0]["default_rate"] == 7000


def test_amount_is_quantity_times_site_rate_and_rate_only_stays_out(tenant):
    item = make_item(tenant)
    site, boq = site_with(tenant, "Site A", [("PCC-M15", 10, 1)])
    other = make_item(tenant, "RO-1", "Rate-only item")
    lines = [{"kind": "item", "description": "Supply and lay PCC-M15", "uom": "cum", "quantity": 10, "rate": 1, "item_code": "PCC-M15"},
             {"kind": "item", "description": "Provisional", "uom": "cum", "quantity": 99, "rate": 5, "item_code": "RO-1", "rate_only": True}]
    assert tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines}).status_code == 200
    put(tenant, site, item["id"], 6400.5)
    put(tenant, site, other["id"], 50)
    got = {r["item_code"]: r for r in rows(tenant, site)}
    assert got["PCC-M15"]["amount"] == 64005.0
    assert got["RO-1"]["amount"] == 0 and got["RO-1"]["rate_only"] and got["RO-1"]["site_rate"] == 50
    assert tenant.get("/api/sites/%d/boq-items" % site).json()["summary"]["amount"] == 64005.0


def test_sections_and_notes_are_not_priced_items(tenant):
    make_item(tenant)
    site, boq = site_with(tenant, "Site A", [("PCC-M15", 1, 1)])
    lines = [{"kind": "section", "description": "SUBSTRUCTURE"}, {"kind": "note", "description": "All rates include royalty"},
             {"kind": "item", "description": "Supply and lay PCC-M15", "uom": "cum", "quantity": 1, "rate": 1, "item_code": "PCC-M15"}]
    tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines})
    got = rows(tenant, site)
    assert len(got) == 1 and got[0]["section"] == "SUBSTRUCTURE"
    with main.SessionLocal() as db:
        assert db.query(models.DBItem).filter(models.DBItem.item_name.in_(["SUBSTRUCTURE", "All rates include royalty"])).count() == 0


def test_a_line_is_mapped_by_code_and_the_stable_id_is_kept(tenant):
    item = make_item(tenant)
    site, _ = site_with(tenant, "Site A", [("PCC-M15", 5, 10)])
    got = rows(tenant, site)[0]
    assert got["mapped"] and got["item_id"] == item["id"] and got["item_name"] == "PCC M15 in foundation"
    with main.SessionLocal() as db:
        assert db.query(models.DBBoqLine).filter_by(item_code="PCC-M15").first().item_id == item["id"]


def test_an_unmapped_line_can_be_mapped_or_made_into_a_new_item(tenant):
    item = make_item(tenant)
    _, boq = make_boq(tenant, "Site A")
    site = boq["job_id"]
    lines = [{"kind": "item", "description": "Excavation in all types of soil", "uom": "cum", "quantity": 5, "rate": 10},
             {"kind": "item", "description": "Brick masonry in CM 1:6", "uom": "cum", "quantity": 7, "rate": 20}]
    tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines})
    un = tenant.get("/api/sites/%d/boq-items/unmapped" % site).json()["rows"]
    assert len(un) == 2 and not any(r["mapped"] for r in un)
    k1, k2 = un[0]["line_key"], un[1]["line_key"]
    res = tenant.post("/api/sites/%d/boq-items/%s/map-item" % (site, k1), json={"item_id": item["id"]})
    assert res.status_code == 200 and res.json()["rows"][0]["item_code"] == "PCC-M15"
    again = tenant.post("/api/sites/%d/boq-items/%s/map-item" % (site, k2), json={"item_id": item["id"]})
    assert again.status_code == 409, "a code is for one line only"
    made = tenant.post("/api/sites/%d/boq-items/%s/create-item" % (site, k2), json={"item_code": "MAS-CM16", "item_category": "Masonry"})
    assert made.status_code == 200 and made.json()["item"]["item_name"] == "Brick masonry in CM 1:6"
    dup = tenant.post("/api/sites/%d/boq-items/%s/create-item" % (site, k2), json={})
    assert dup.status_code == 409, "repeating it does not make a second item"
    with main.SessionLocal() as db:
        assert db.query(models.DBItem).filter(models.DBItem.item_name == "Brick masonry in CM 1:6").count() == 1
    assert not tenant.get("/api/sites/%d/boq-items/unmapped" % site).json()["rows"]


def test_create_item_refuses_a_duplicate_code(tenant):
    make_item(tenant)
    _, boq = make_boq(tenant, "Site A")
    tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": [{"kind": "item", "description": "Something new", "uom": "cum", "quantity": 1}]})
    key = rows(tenant, boq["job_id"])[0]["line_key"]
    res = tenant.post("/api/sites/%d/boq-items/%s/create-item" % (boq["job_id"], key), json={"item_code": "pcc-m15"})
    assert res.status_code == 409 and "already used by" in res.json()["detail"]


def test_ownership_a_rate_cannot_go_on_an_item_or_site_that_is_not_theirs(tenant, second_tenant):
    x, y = make_item(tenant), make_item(tenant, "OTHER-1", "Other")
    a, _ = site_with(tenant, "Site A", [("PCC-M15", 1, 1)])
    assert put(tenant, a, y["id"], 5).status_code == 404, "an item not in this site's BOQ"
    assert put(tenant, 999999, x["id"], 5).status_code == 404
    assert second_tenant.get("/api/sites/%d/boq-items" % a).status_code == 404
    assert second_tenant.put("/api/sites/%d/item-prices/%d" % (a, x["id"]), json={"rate": 1}).status_code == 404
    assert second_tenant.get("/api/items/%d" % x["id"]).status_code == 404


def test_finalise_lock_reopen_and_the_audit_trail_with_reasons(tenant):
    x = make_item(tenant)
    site, _ = site_with(tenant, "Site A", [("PCC-M15", 2, 5)])
    base = "/api/sites/%d/item-prices/%d" % (site, x["id"])
    assert tenant.post(base + "/finalize", json={}).status_code == 422
    assert put(tenant, site, x["id"], 40).status_code == 200
    assert put(tenant, site, x["id"], 42).status_code == 422, "changing an existing rate needs a reason"
    assert put(tenant, site, x["id"], 42, remarks="Quote revised").status_code == 200
    assert tenant.post(base + "/finalize", json={}).status_code == 200
    assert put(tenant, site, x["id"], 43, remarks="x").status_code == 409
    assert tenant.post(base + "/reopen", json={}).status_code == 422
    assert tenant.post(base + "/reopen", json={"remarks": "Client renegotiated"}).status_code == 200
    trail = tenant.get("/api/sites/%d/item-prices/audit" % site).json()["audit"]
    assert [a["action"] for a in reversed(trail)] == ["created", "edited", "finalized", "reopened"]
    edited = next(a for a in trail if a["action"] == "edited")
    assert (edited["previous_rate"], edited["new_rate"], edited["reason"]) == (40, 42, "Quote revised")


def test_bulk_save_is_all_or_nothing_and_repeating_it_makes_no_second_row(tenant):
    a, b = make_item(tenant), make_item(tenant, "PCC-M20", "PCC M20")
    site, _ = site_with(tenant, "Site A", [("PCC-M15", 1, 1), ("PCC-M20", 1, 1)])
    url = "/api/sites/%d/item-prices/bulk" % site
    assert tenant.post(url, json={"rates": [{"item_id": a["id"], "rate": 10}, {"item_id": b["id"], "rate": -5}]}).status_code == 422
    with main.SessionLocal() as db:
        assert db.query(models.DBSiteItemRate).filter_by(job_id=site).count() == 0
        assert db.query(models.DBRateAuditLog).filter_by(job_id=site).count() == 0
    good = {"rates": [{"item_id": a["id"], "rate": 10}, {"item_id": b["id"], "rate": 20}]}
    assert tenant.post(url, json=good).status_code == 200
    assert tenant.post(url, json=good).status_code == 200
    with main.SessionLocal() as db:
        assert db.query(models.DBSiteItemRate).filter_by(job_id=site).count() == 2


def test_permissions_view_edit_and_finalise_are_separate(tenant, portal):
    x = make_item(tenant)
    site, _ = site_with(tenant, "Mine", [("PCC-M15", 1, 1)])
    other, _ = site_with(tenant, "Other", [("PCC-M15", 1, 1)])
    emp = make_employee(tenant, password="EmpPass123")

    def grant(perms):
        res = tenant.put("/api/employees/%d/permissions" % emp["id"], json={"permission_role": "staff", "permissions": perms, "site_ids": [site]})
        assert res.status_code == 200, res.text

    def sign_in():
        assert portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"}).status_code == 200

    grant(["self.service"])
    sign_in()
    assert portal.get("/api/sites/%d/boq-items" % site).status_code == 403, "no right to see site prices"
    grant(["siteprices.view"])
    assert portal.get("/api/sites/%d/boq-items" % site).status_code == 200
    assert portal.get("/api/sites/%d/boq-items" % other).status_code == 404, "and only their own sites"
    assert portal.put("/api/sites/%d/item-prices/%d" % (site, x["id"]), json={"rate": 9}).status_code == 403
    grant(["siteprices.view", "siteprices.edit"])
    assert portal.put("/api/sites/%d/item-prices/%d" % (site, x["id"]), json={"rate": 9}).status_code == 200
    assert portal.post("/api/sites/%d/item-prices/%d/finalize" % (site, x["id"]), json={}).status_code == 403
    grant(["siteprices.view", "siteprices.edit", "siteprices.finalize"])
    assert portal.post("/api/sites/%d/item-prices/%d/finalize" % (site, x["id"]), json={}).status_code == 200
    assert portal.put("/api/sites/%d/item-prices/%d" % (site, x["id"]), json={"rate": 10, "remarks": "r"}).status_code == 409


def test_applying_finalised_rates_updates_the_open_revision_only(tenant):
    x = make_item(tenant)
    site, boq = site_with(tenant, "Site A", [("PCC-M15", 10, 1)])
    put(tenant, site, x["id"], 6400)
    done = tenant.post("/api/sites/%d/item-prices/apply-to-boq" % site, json={})
    assert done.status_code == 200 and done.json()["applied"] == 0, "a draft rate is not applied"
    tenant.post("/api/sites/%d/item-prices/%d/finalize" % (site, x["id"]), json={})
    done = tenant.post("/api/sites/%d/item-prices/apply-to-boq" % site, json={})
    assert done.json()["applied"] == 1 and done.json()["boq_total"] == 64000
    book = tenant.get("/api/boqs/%d" % boq["id"]).json()
    assert [l["rate"] for l in book["lines"] if l["kind"] == "item"] == [6400]
    issued = tenant.post("/api/boqs/%d/revisions" % boq["id"], json={})
    assert issued.status_code == 200, issued.text                 # R0 is issued and R1 opened as a copy
    tenant.post("/api/boqs/%d/revisions" % boq["id"], json={})    # R1 issued too: the working revision is now R2
    assert tenant.get("/api/boqs/%d" % boq["id"]).json()["editable"] is True


# --- BOQ integration -------------------------------------------------------------------------------------------------

def test_a_variation_keeps_mappings_and_finalised_rates_and_new_items_are_mapped(tenant):
    boq, lines, sections = ready(tenant)
    site = boq["job_id"]
    got = {r["description"]: r for r in rows(tenant, site)}
    exc = got["Excavation in all types of soil"]
    assert exc["mapped"] and exc["item_id"]
    assert put(tenant, site, exc["item_id"], 190).status_code == 200
    assert tenant.post("/api/sites/%d/item-prices/%d/finalize" % (site, exc["item_id"]), json={}).status_code == 200
    v = variation(tenant, boq, [{"kind": "quantity", "boq_key": lines["EXC"]["key"], "change_qty": 80},
                                {"kind": "extra", "description": "Dewatering during excavation", "uom": "day", "change_qty": 20, "rate": 4500,
                                 "section_key": sections[0]["key"]}]).json()["variation"]
    tenant.post("/api/boq-variations/%d/submit" % v["id"])
    assert tenant.post("/api/boq-variations/%d/approve" % v["id"], json={}).status_code == 200
    after = {r["description"]: r for r in rows(tenant, site)}
    assert after["Excavation in all types of soil"]["site_rate"] == 190 and after["Excavation in all types of soil"]["status"] == "Finalized"
    assert after["Excavation in all types of soil"]["quantity"] == 580
    new = after["Dewatering during excavation"]
    assert new["mapped"] and new["item_id"] and new["status"] == "Pending", "the extra item is mapped and awaits its site rate"


def test_the_existing_boq_still_saves_and_totals(tenant):
    _, boq = make_boq(tenant)
    out = saved(tenant, boq)
    assert out["lines"] and all(l["item_code"] for l in out["lines"] if l["kind"] == "item")
