"""Material norms on work items, and the Item sheet using them: which work a BOQ line is (from the BOQ, chosen on the sheet, or
matched on its description), its materials filled from the norms - or from the same work on another sheet - as a proposal, a
line's worked-out materials saved back as a norm, and what the work done so far should have used against what was issued."""
import io
import uuid

import openpyxl

from app import db as database, models
from store.test_cutover import _leave_no_stock_behind, ok  # noqa: F401
from test_budgeting import keyed

BASE = "/api/store/item-sheet"


def _item(jid, name, kind="RM", unit="Bags", **extra):
    with database.SessionLocal() as s:
        client_id = s.get(models.DBJob, jid).client_id
        it = models.DBItem(client_id=client_id, kind=kind, item_code="N-%s" % uuid.uuid4().hex[:8].upper(), item_name=name,
                           units_of_measure=unit, hsn_code="2523" if kind == "RM" else "", **extra)
        s.add(it)
        s.commit()
        return it.id, it.item_code


def _sheet(t, jid):
    return ok(t.get("%s/%d" % (BASE, jid)))


def _line(sheet, key):
    return next(l for g in sheet["groups"] for l in g["lines"] if l["key"] == key)


def _norms(t, work_id, *rows):
    return t.put("/api/items/%d/norms" % work_id, json={"rows": [dict(zip(("material_id", "qty_per_unit", "wastage_pct"), r)) for r in rows]})


def test_a_work_item_keeps_what_one_unit_of_it_uses(tenant):
    jid, _k = keyed(tenant)
    work = _item(jid, "RCC M25", kind="FG", unit="cum")
    cement, sand = _item(jid, "Cement OPC 53"), _item(jid, "River sand", unit="cum")
    got = ok(_norms(tenant, work[0], (cement[0], 8.2, 2), (sand[0], 0.45, None)))
    assert got["is_work"] and [(n["item_name"], n["qty_per_unit"], n["wastage_pct"], n["unit"]) for n in got["norms"]] == [
        ("Cement OPC 53", 8.2, 2.0, "Bags"), ("River sand", 0.45, 0.0, "cum")]
    again = ok(tenant.get("/api/items/%d/norms" % work[0]))
    assert len(again["norms"]) == 2


def test_norms_go_on_work_items_and_name_store_materials_in_proper_quantities(tenant):
    jid, _k = keyed(tenant)
    work = _item(jid, "PCC M15", kind="FG", unit="cum")
    other_work = _item(jid, "Plastering", kind="FG", unit="sqm")
    cement = _item(jid, "Cement OPC 43")
    res = _norms(tenant, cement[0], (cement[0], 1, 0))
    assert res.status_code == 400 and "store material" in res.json()["detail"]
    res = _norms(tenant, work[0], (other_work[0], 1, 0), (cement[0], 0, 0), (cement[0], 2, 150))
    assert res.status_code == 400
    d = res.json()["detail"]
    assert "Row 1: %s Plastering is a work item" % other_work[1] in d and "Row 2: The quantity must be above 0" in d and "Row 3: The wastage % must be from 0 to 100" in d
    assert ok(tenant.get("/api/items/%d/norms" % work[0]))["norms"] == []


def test_norms_round_trip_through_the_excel_sheet_all_or_nothing(tenant):
    jid, _k = keyed(tenant)
    work = _item(jid, "Brick masonry 1:6", kind="FG", unit="cum")
    bricks, cement = _item(jid, "Red bricks", unit="Nos"), _item(jid, "Cement PPC")
    res = tenant.get("/api/items/norms.xlsx")
    assert res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    ws = wb["Norms"]
    head = [c.value for c in ws[1]]
    assert head[:3] == ["Work item code", "Work item name", "Work unit"]
    row = next(r for r in ws.iter_rows(min_row=2) if r[0].value == work[1])
    assert row[3].value in (None, ""), "a work item with no norms is listed once, to fill"
    row[3].value, row[6].value, row[7].value = bricks[1], 500, 3
    ws.append([work[1], "", "", cement[1], "", "", 1.25, None, "CM 1:6"])
    ws.append(["NO-SUCH-WORK", "", "", cement[1], "", "", 1, None, ""])
    buf = io.BytesIO()
    wb.save(buf)
    bad = tenant.post("/api/items/norms/upload", files={"file": ("n.xlsx", buf.getvalue())})
    assert bad.status_code == 400 and "NO-SUCH-WORK is not in the Item Master" in bad.json()["detail"]
    assert ok(tenant.get("/api/items/%d/norms" % work[0]))["norms"] == [], "nothing saved while any row is wrong"
    ws.delete_rows(ws.max_row)
    buf = io.BytesIO()
    wb.save(buf)
    done = ok(tenant.post("/api/items/norms/upload", files={"file": ("n.xlsx", buf.getvalue())}))
    assert done["work_items"] >= 1 and done["materials"] >= 2
    got = ok(tenant.get("/api/items/%d/norms" % work[0]))["norms"]
    assert [(n["item_name"], n["qty_per_unit"], n["wastage_pct"], n["remarks"]) for n in got] == [("Red bricks", 500, 3, ""), ("Cement PPC", 1.25, 0, "CM 1:6")]


def test_the_sheet_fills_a_lines_materials_from_its_work_items_norms_without_saving(tenant):
    jid, k = keyed(tenant)
    s = _sheet(tenant, jid)
    rcc = _line(s, k["RCC"])
    assert rcc["work"]["from"] == "boq", "a saved BOQ names its lines' work items"
    work = _item(jid, "RCC M25 raft", kind="FG", unit=rcc["unit"])
    cement, steel = _item(jid, "Cement OPC 53"), _item(jid, "TMT 12 mm", unit="Kgs")
    ok(_norms(tenant, work[0], (cement[0], 8.2, 2), (steel[0], 95, 0)))
    s = ok(tenant.put("%s/%d/works" % (BASE, jid), json={"links": [{"boq_key": k["RCC"], "work_item_id": work[0]}]}))
    line = _line(s, k["RCC"])
    assert line["work"]["id"] == work[0] and line["work"]["from"] == "sheet" and line["work"]["norms"] == 2
    filled = ok(tenant.post("%s/%d/fill" % (BASE, jid), json={"keys": [k["RCC"], k["MAS"]]}))
    got = {m["item_name"]: m for m in filled["proposals"][k["RCC"]]}
    assert got["Cement OPC 53"]["qty"] == round(120 * 8.2 * 1.02, 3) and "+ 2% wastage" in got["Cement OPC 53"]["remarks"]
    assert got["TMT 12 mm"]["qty"] == 120 * 95 and got["TMT 12 mm"]["hsn"] == "2523"
    assert [x["key"] for x in filled["skipped"]] == [k["MAS"]] and "has no norms yet" in filled["skipped"][0]["why"]
    assert _sheet(tenant, jid)["material_count"] == 0, "a proposal is not saved"


def test_a_work_item_counted_in_another_unit_is_not_used_to_fill(tenant):
    jid, k = keyed(tenant)
    work = _item(jid, "RCC M25 by the tonne", kind="FG", unit="MT")
    cement = _item(jid, "Cement OPC 53")
    ok(_norms(tenant, work[0], (cement[0], 3, 0)))
    ok(tenant.put("%s/%d/works" % (BASE, jid), json={"links": [{"boq_key": k["RCC"], "work_item_id": work[0]}]}))
    filled = ok(tenant.post("%s/%d/fill" % (BASE, jid), json={"keys": [k["RCC"]]}))
    assert filled["proposals"] == {} and "norms of %s are per MT" % work[1] in filled["skipped"][0]["why"]


def test_the_same_work_on_another_projects_sheet_fills_a_line_scaled_to_its_quantity(tenant):
    a, ka = keyed(tenant)
    b, kb = keyed(tenant)
    cement = _item(a, "Cement OPC 53 shared")
    ok(tenant.put("%s/%d" % (BASE, a), json={"materials": [{"boq_key": ka["RCC"], "item_code": cement[1], "qty": 1200, "remarks": ""}]}))
    filled = ok(tenant.post("%s/%d/fill" % (BASE, b), json={"keys": [kb["RCC"]]}))
    row = filled["proposals"][kb["RCC"]][0]
    qty_b = _line(_sheet(tenant, b), kb["RCC"])["qty"]
    assert row["item_id"] == cement[0] and row["qty"] == round(1200 / 120 * qty_b, 3) and row["remarks"].startswith("As on ")


def test_a_lines_worked_out_materials_are_saved_as_its_work_items_norm(tenant):
    jid, k = keyed(tenant)
    rcc = _line(_sheet(tenant, jid), k["RCC"])
    work = _item(jid, "RCC M25 learnt", kind="FG", unit=rcc["unit"])
    cement = _item(jid, "Cement learnt")
    res = tenant.post("%s/%d/lines/%s/save-norm" % (BASE, jid, k["RCC"]))
    assert res.status_code == 400 and "Save the line's materials" in res.json()["detail"]
    ok(tenant.put("%s/%d/works" % (BASE, jid), json={"links": [{"boq_key": k["RCC"], "work_item_id": work[0]}]}))
    ok(tenant.put("%s/%d" % (BASE, jid), json={"materials": [{"boq_key": k["RCC"], "item_code": cement[1], "qty": 984, "remarks": ""}]}))
    done = ok(tenant.post("%s/%d/lines/%s/save-norm" % (BASE, jid, k["RCC"])))
    assert "Saved as the norm of %s" % work[1] in done["message"]
    assert ok(tenant.get("/api/items/%d/norms" % work[0]))["norms"][0]["qty_per_unit"] == round(984 / 120, 6)


def test_a_line_with_no_work_item_is_matched_to_the_one_its_description_reads_like(tenant):
    jid, k = keyed(tenant)
    with database.SessionLocal() as db:                       # a BOQ brought in without item codes
        for l in db.query(models.DBBoqLine).filter(models.DBBoqLine.key == k["RCC"]).all():
            l.item_id, l.item_code = None, ""
        db.commit()
    rcc = _line(_sheet(tenant, jid), k["RCC"])
    assert rcc["work"] is None
    good = _item(jid, rcc["description"] + " (sheet)", kind="FG", unit=rcc["unit"])
    _item(jid, "Painting of walls with two coats", kind="FG", unit="sqm")
    got = ok(tenant.get("%s/%d/work-suggestions" % (BASE, jid)))["items"]
    match = next(x for x in got if x["key"] == k["RCC"])
    # The BOQ's own work item of that name is in the master too: either reads like the line.
    assert match["work"]["name"].startswith(rcc["description"]) and match["score"] >= 0.6
    assert all(x["work"]["name"] != "Painting of walls with two coats" for x in got)
    found = ok(tenant.get("%s/%d/work-items" % (BASE, jid), params={"q": rcc["description"][:6]}))["items"]
    assert any(w["id"] == good[0] for w in found)


def test_the_work_done_says_what_should_have_been_used_against_what_was_issued(tenant):
    jid, k = keyed(tenant)
    cement = _item(jid, "Cement for checking")
    ok(tenant.put("%s/%d" % (BASE, jid), json={"materials": [{"boq_key": k["RCC"], "item_code": cement[1], "qty": 1200, "remarks": ""}]}))
    rcc = _line(_sheet(tenant, jid), k["RCC"])
    assert rcc["done_qty"] is None and rcc["materials"][0]["should_use"] is None
    with database.SessionLocal() as db:
        job = db.get(models.DBJob, jid)
        o = models.DBSubcontractOrder(client_id=job.client_id, job_id=jid, status="APPROVED")
        db.add(o)
        db.flush()
        i = models.DBSubcontractItem(order_id=o.id, item_description="RCC", uom=rcc["unit"], quantity=120, unit_rate=100, boq_key=k["RCC"])
        odd = models.DBSubcontractItem(order_id=o.id, item_description="RCC by weight", uom="MT", quantity=10, unit_rate=100, boq_key=k["RCC"])
        db.add_all([i, odd])
        db.flush()
        db.add_all([models.DBSubMeasurement(client_id=job.client_id, order_id=o.id, item_id=i.id, quantity=30),
                    models.DBSubMeasurement(client_id=job.client_id, order_id=o.id, item_id=odd.id, quantity=999)])
        db.commit()
    rcc = _line(_sheet(tenant, jid), k["RCC"])
    assert rcc["done_qty"] == 30 and rcc["done_from"] == "measured", "work measured in another unit is not added in"
    assert rcc["materials"][0]["should_use"] == 300.0                        # a quarter of the line done: a quarter of 1,200


def test_the_sheet_offers_the_rate_last_paid_and_the_rate_contracts_in_force(tenant):
    from datetime import date, timedelta
    jid, k = keyed(tenant)
    cement = _item(jid, "Cement priced", item_tax_type="28%")
    ok(tenant.put("%s/%d" % (BASE, jid), json={"materials": [{"boq_key": k["RCC"], "item_code": cement[1], "qty": 100, "remarks": ""}]}))
    day = lambda n: (date.today() + timedelta(days=n)).isoformat()
    with database.SessionLocal() as db:
        cid = db.get(models.DBJob, jid).client_id
        for n, (status, price, uom, when) in enumerate([("Approved", 390, "Bags", day(-30)), ("Approved", 410, "Bags", day(-2)),
                                                        ("Draft", 999, "Bags", day(-1)), ("Approved", 8, "Kgs", day(-1))]):
            po = models.DBPurchaseOrder(client_id=cid, job_id=jid, supplier_name="Supplier %d" % n, status=status, issue_date=when, number="PO-T%d" % n)
            db.add(po)
            db.flush()
            db.add(models.DBPurchaseOrderLineItem(order_id=po.id, description="Cement", item_code=cement[1], item_id=cement[0], uom=uom, qty=10, price=price))
        db.add_all([models.DBRateContract(client_id=cid, supplier_name="Shree Traders", item_code=cement[1], rate=395, valid_from=day(-10), valid_to=day(20)),
                    models.DBRateContract(client_id=cid, supplier_name="Old Contract", item_code=cement[1], rate=300, valid_from=day(-90), valid_to=day(-1))])
        db.commit()
    p = _sheet(tenant, jid)["prices"][str(cement[0])]
    assert (p["last_rate"], p["last_supplier"], p["gst"]) == (410, "Supplier 1", "28"), "the newest approved order in the item's own unit"
    assert p["contracts"] == [{"supplier": "Shree Traders", "rate": 395, "valid_to": day(20)}]


def _project_norms(jid):
    from app.models.store_reports import DBStoreMaterialNorm
    with database.SessionLocal() as db:
        lines = {l.id: l.key for l in db.query(models.DBBoqLine).join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id).filter(models.DBBoq.job_id == jid).all()}
        return {(lines[n.boq_item_id], n.item_id): (float(n.qty_per_unit), float(n.wastage_pct or 0), n.notes)
                for n in db.query(DBStoreMaterialNorm).filter(DBStoreMaterialNorm.boq_item_id.in_(list(lines))).all()}


def test_a_projects_norms_are_brought_in_from_its_work_items_norms(tenant):
    jid, k = keyed(tenant)
    rcc = _line(_sheet(tenant, jid), k["RCC"])
    cement, sand = _item(jid, "Cement for project norms"), _item(jid, "Sand for project norms", unit="cum")
    ok(_norms(tenant, rcc["work"]["id"], (cement[0], 8.2, 2), (sand[0], 0.42, 5)))
    odd = _item(jid, "RCC by the tonne", kind="FG", unit="MT")
    ok(_norms(tenant, odd[0], (cement[0], 3, 0)))
    ok(tenant.put("%s/%d/works" % (BASE, jid), json={"links": [{"boq_key": k["MAS"], "work_item_id": odd[0]}]}))
    view = ok(tenant.get("/api/store/reports/norms/from-work/preview", params={"project_id": jid, "mode": "add"}))
    assert view["summary"]["insert"] == 2 and view["summary"]["unit"] == 1, view["summary"]
    assert {r["status"] for r in view["rows"] if r["work_item_id"] == odd[0]} == {"unit"}, "masonry counted in cum is not filled from a per-MT norm"
    assert _project_norms(jid) == {}, "a preview writes nothing"
    done = ok(tenant.post("/api/store/reports/norms/from-work", json={"project_id": jid, "mode": "add"}))
    assert (done["inserted"], done["updated"]) == (2, 0)
    got = _project_norms(jid)
    assert got[(k["RCC"], cement[0])][:2] == (8.2, 2.0) and "From the norms of work item" in got[(k["RCC"], cement[0])][2]
    # A changed work norm: "add" keeps what the project has, "replace" takes the new figure.
    ok(_norms(tenant, rcc["work"]["id"], (cement[0], 8.5, 2), (sand[0], 0.42, 5)))
    again = tenant.post("/api/store/reports/norms/from-work", json={"project_id": jid, "mode": "add"})
    assert again.status_code == 400 and "nothing to bring in" in again.json()["detail"]
    done = ok(tenant.post("/api/store/reports/norms/from-work", json={"project_id": jid, "mode": "replace"}))
    assert (done["inserted"], done["updated"], done["unchanged"]) == (0, 1, 1)
    assert _project_norms(jid)[(k["RCC"], cement[0])][0] == 8.5


def test_the_sheet_fills_from_the_projects_own_norms_before_the_work_items(tenant):
    from app.models.store_reports import DBStoreMaterialNorm
    jid, k = keyed(tenant)
    rcc = _line(_sheet(tenant, jid), k["RCC"])
    cement = _item(jid, "Cement own norm")
    ok(_norms(tenant, rcc["work"]["id"], (cement[0], 8.2, 2)))
    with database.SessionLocal() as db:
        cid = db.get(models.DBJob, jid).client_id
        db.add(DBStoreMaterialNorm(client_id=cid, boq_item_id=rcc["line_id"], item_id=cement[0], qty_per_unit=7.5, wastage_pct=0))
        db.commit()
    row = ok(tenant.post("%s/%d/fill" % (BASE, jid), json={"keys": [k["RCC"]]}))["proposals"][k["RCC"]][0]
    assert row["qty"] == 120 * 7.5 and row["remarks"].startswith("Project norm: 7.5 per")
