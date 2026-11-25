"""The project's Item sheet in the store: the BOQ's lines grouped by group code, and under each line the store materials it
needs (item code, HSN and unit from the item master). Made in the app or uploaded from the template, approved by the Master
- and then purchase orders and indents for the project go by it, and the sheet follows each material through ordering,
receiving, indenting and issuing."""
import io
import json
import uuid
from datetime import date

import openpyxl

from app import db as database, models
from app.models.item_sheet import DBItemSheet, DBItemSheetLine
from store.test_cutover import _leave_no_stock_behind, ok  # noqa: F401
from test_budgeting import keyed

BASE = "/api/store/item-sheet"
TODAY = date.today().isoformat()


def _items(jid, *names, kind="RM"):
    """Items in the master of the project's company, kept in kg, with an HSN: {name: (id, code)}."""
    out = {}
    with database.SessionLocal() as s:
        client_id = s.get(models.DBJob, jid).client_id
        for name in names:
            it = models.DBItem(client_id=client_id, kind=kind, item_code="IS-%s" % uuid.uuid4().hex[:8].upper(), item_name=name,
                               units_of_measure="kg", hsn_code="2523")
            s.add(it)
            s.flush()
            out[name] = (it.id, it.item_code)
        s.commit()
    return out


def _line(sheet, group, n=0):
    """The n-th BOQ line of a group on the sheet."""
    return next(g for g in sheet["groups"] if g["code"] == group)["lines"][n]


def _save(t, jid, *mats, **extra):
    return t.put("%s/%d" % (BASE, jid), json=dict({"materials": [dict(zip(("boq_key", "item_code", "qty", "remarks"), m)) for m in mats]}, **extra))


def _upload(t, jid, rows):
    wb = openpyxl.Workbook()
    wb.active.title = "Item sheet"
    wb.active.append(["Group code", "BOQ item no", "BOQ work", "BOQ unit", "BOQ qty", "Item code", "Item name", "HSN", "Unit", "Quantity", "Remarks", "Line ref"])
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return t.post("%s/%d/upload" % (BASE, jid), files={"file": ("sheet.xlsx", buf.getvalue())})


def test_the_sheet_lists_the_boqs_lines_under_their_group_codes(tenant):
    jid, k = keyed(tenant)
    s = ok(tenant.get("%s/%d" % (BASE, jid)))
    assert not s["exists"] and s["has_boq"]
    assert {"RCC", "MAS", "EXC"} <= set(s["group_codes"])
    rcc = _line(s, "RCC")
    assert rcc["key"] == k["RCC"] and rcc["qty"] == 120.0 and rcc["unit"] and rcc["description"] and rcc["materials"] == []


def test_each_boq_line_gets_its_own_materials_with_hsn_from_the_master(tenant):
    jid, k = keyed(tenant)
    it = _items(jid, "Cement OPC", "TMT 12 mm")
    s = ok(_save(tenant, jid, (k["RCC"], it["Cement OPC"][1], 500, ""), (k["RCC"], it["TMT 12 mm"][1], 9000, "Fe550"),
                 (k["MAS"], it["Cement OPC"][1], 120, "CM 1:6")))
    assert s["status"] == "DRAFT" and s["material_count"] == 3 and s["item_count"] == 2
    rcc = _line(s, "RCC")
    assert [(m["item_name"], m["hsn"], m["unit"], m["qty"]) for m in rcc["materials"]] == [("Cement OPC", "2523", "kg", 500.0), ("TMT 12 mm", "2523", "kg", 9000.0)]
    assert _line(s, "MAS")["materials"][0]["remarks"] == "CM 1:6"
    cement = next(t for t in s["totals"] if t["item_name"] == "Cement OPC")
    assert cement["required"] == 620.0 and cement["to_order"] == 620.0


def test_a_wrong_line_item_or_quantity_saves_nothing_and_says_what_is_wrong(tenant):
    jid, k = keyed(tenant)
    it = _items(jid, "Cement OPC")
    work = _items(jid, "RCC M25 work", kind="FG")
    res = _save(tenant, jid, ("no-such-line", it["Cement OPC"][1], 5, ""), (k["RCC"], "NO-SUCH", 5, ""), (k["RCC"], it["Cement OPC"][1], 0, ""),
                (k["MAS"], work["RCC M25 work"][1], 3, ""), (k["EXC"], it["Cement OPC"][1], 1, ""), (k["EXC"], it["Cement OPC"][1], 2, ""))
    assert res.status_code == 400
    d = res.json()["detail"]
    for part in ("Row 1: that BOQ line is not on the project's BOQ", "'NO-SUCH' is not in the item master", "Row 3: give a quantity above 0",
                 "is a BOQ work item, not a store material", "Row 6:"):
        assert part in d, (part, d)
    assert not ok(tenant.get("%s/%d" % (BASE, jid)))["exists"]


def test_the_template_lists_every_boq_line_and_uploads_back(tenant):
    jid, k = keyed(tenant)
    it = _items(jid, "Cement OPC", "River sand")
    res = tenant.get("%s/%d/template.xlsx" % (BASE, jid))
    assert res.status_code == 200
    ws = openpyxl.load_workbook(io.BytesIO(res.content))["Item sheet"]
    rows = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
    refs = {r[11]: r for r in rows}
    assert k["RCC"] in refs and refs[k["RCC"]][0] == "RCC" and refs[k["RCC"]][4] == 120.0 and refs[k["RCC"]][5] in (None, "")

    rcc = refs[k["RCC"]]
    bad = _upload(tenant, jid, [rcc[:5] + [it["Cement OPC"][1], "", "", "", 300, "", k["RCC"]], rcc[:5] + ["NOPE", "", "", "", 3, "", k["RCC"]]])
    assert bad.status_code == 400 and "Row 3" in bad.json()["detail"]
    s = ok(_upload(tenant, jid, [rcc[:5] + [it["Cement OPC"][1], "typed name is not read", "", "", 300, "raft", k["RCC"]],
                                 rcc[:5] + [it["River sand"][1], "", "", "", 45, "", k["RCC"]],
                                 refs[k["MAS"]][:5] + [None, None, None, None, None, None, k["MAS"]]]))      # a line left with no material
    assert [(m["item_name"], m["qty"], m["remarks"]) for m in _line(s, "RCC")["materials"]] == [("Cement OPC", 300.0, "raft"), ("River sand", 45.0, "")]

    again = openpyxl.load_workbook(io.BytesIO(tenant.get("%s/%d/template.xlsx" % (BASE, jid)).content))["Item sheet"]
    mine = [[c.value for c in r] for r in again.iter_rows(min_row=2) if r[11].value == k["RCC"]]
    assert [(r[5], r[6], r[9]) for r in mine] == [(it["Cement OPC"][1], "Cement OPC", 300.0), (it["River sand"][1], "River sand", 45.0)]


def test_a_new_material_is_added_to_the_item_master_from_the_sheet(tenant):
    jid, k = keyed(tenant)
    res = ok(tenant.post("%s/%d/items" % (BASE, jid), json={"item_name": "Waterproofing compound %s" % uuid.uuid4().hex[:4], "units_of_measure": "kg", "hsn_code": "3824"}))
    code = res["item"]["code"]
    with database.SessionLocal() as s:
        it = s.query(models.DBItem).filter(models.DBItem.item_code == code).one()
        assert it.kind == "RM" and it.hsn_code == "3824" and it.units_of_measure == "Kgs"
    s = ok(_save(tenant, jid, (k["RCC"], code, 12, "")))
    assert _line(s, "RCC")["materials"][0]["hsn"] == "3824"
    bad = tenant.post("%s/%d/items" % (BASE, jid), json={"item_name": "Something", "units_of_measure": "furlongs"})
    assert bad.status_code == 400


def test_the_master_approves_and_a_change_waits_for_approval_again(tenant):
    jid, k = keyed(tenant)
    code = _items(jid, "Cement OPC")["Cement OPC"][1]
    ok(_save(tenant, jid, (k["RCC"], code, 100, "")))
    s = ok(tenant.post("%s/%d/approve" % (BASE, jid)))                               # the Master may approve a draft straight away
    assert s["status"] == "APPROVED" and s["approved"] and not s["changed_since_approval"]
    s = ok(_save(tenant, jid, (k["RCC"], code, 150, "")))
    assert s["status"] == "DRAFT" and s["approved"] and s["changed_since_approval"]
    assert s["totals"][0]["approved_qty"] == 100.0                                    # the approved copy is still the one in force
    assert ok(tenant.post("%s/%d/submit" % (BASE, jid)))["status"] == "SUBMITTED"
    assert tenant.post("%s/%d/send-back" % (BASE, jid), json={"note": ""}).status_code == 400
    s = ok(tenant.post("%s/%d/send-back" % (BASE, jid), json={"note": "Check the steel"}))
    assert s["status"] == "DRAFT" and s["returned_note"] == "Check the steel"
    ok(tenant.post("%s/%d/submit" % (BASE, jid)))
    s = ok(tenant.post("%s/%d/approve" % (BASE, jid)))
    assert s["status"] == "APPROVED" and s["totals"][0]["approved_qty"] == 150.0


def test_a_sheet_saved_under_group_codes_moves_under_the_boq_lines(tenant):
    jid, k = keyed(tenant)
    cement = _items(jid, "Cement OPC")["Cement OPC"][0]
    with database.SessionLocal() as s:
        sheet = DBItemSheet(client_id=s.get(models.DBJob, jid).client_id, job_id=jid, status="APPROVED", approved_by_name="Master",
                            approved_lines=json.dumps([{"group_code": "RCC", "item_id": cement, "qty": 40}, {"group_code": "GONE", "item_id": cement, "qty": 5}]))
        s.add(sheet)
        s.flush()
        s.add_all([DBItemSheetLine(sheet_id=sheet.id, line_no=1, group_code="RCC", item_id=cement, qty=40, remarks="old"),
                   DBItemSheetLine(sheet_id=sheet.id, line_no=2, group_code="GONE", item_id=cement, qty=5)])
        s.commit()
        sid = sheet.id
    s = ok(tenant.get("%s/%d" % (BASE, jid)))
    assert [(m["qty"], m["remarks"]) for m in _line(s, "RCC")["materials"]] == [(40.0, "old")]
    assert s["approved"] and not s["changed_since_approval"]                            # the same cement, now under BOQ lines: no change
    first = s["groups"][0]["lines"][0]["materials"]                                     # a group the BOQ no longer has: its first line, saying so
    assert any(m["qty"] == 5.0 and "was under group GONE" in m["remarks"] for m in first)
    with database.SessionLocal() as db:
        assert db.query(DBItemSheetLine).filter(DBItemSheetLine.sheet_id == sid).count() == 0


def test_an_indent_asks_only_for_items_on_the_approved_sheet(tenant):
    jid, k = keyed(tenant)
    it = _items(jid, "Cement OPC", "Red brick")
    (cement, ccode), (brick, _b) = it["Cement OPC"], it["Red brick"]
    store = ok(tenant.post("/api/store/masters/stores", json={"code": "IS" + uuid.uuid4().hex[:4].upper(), "name": "Central", "type": "CENTRAL"}))
    body = lambda item, qty: {"store_id": store["id"], "project_id": jid, "activity": "Raft", "lines": [{"item_id": item, "qty": str(qty), "uom": "kg"}]}

    early = ok(tenant.post("/api/store/outward/indent", json=body(brick, 10)))          # no sheet yet: anything may be asked for
    ok(_save(tenant, jid, (k["RCC"], ccode, 60, ""), (k["MAS"], ccode, 40, "")))
    ok(tenant.post("/api/store/outward/indent", json=body(brick, 10)))                   # a sheet not yet approved holds nothing
    ok(tenant.post("%s/%d/approve" % (BASE, jid)))

    res = tenant.post("/api/store/outward/indent", json=body(brick, 10))
    assert res.status_code == 400 and "not on the project's approved Item sheet" in res.json()["detail"]
    assert tenant.post("/api/store/outward/indent/%d/submit" % early["id"]).status_code == 400     # a draft from before is held to it too

    fine = ok(tenant.post("/api/store/outward/indent", json=body(cement, 80)))           # the two lines' 60 + 40
    assert fine["sheet_warnings"] == []
    ok(tenant.post("/api/store/outward/indent/%d/submit" % fine["id"]))
    (w,) = ok(tenant.post("/api/store/outward/indent", json=body(cement, 40)))["sheet_warnings"]
    assert "Cement OPC" in w and "120" in w and "100" in w


def _order(t, jid, lines, supplier="Shree Traders"):
    return t.post("/api/purchase-orders", json={"supplier_name": supplier, "job_id": jid, "category": "materials", "line_items": lines})


def test_a_purchase_order_buys_only_what_is_on_the_approved_sheet(tenant):
    jid, k = keyed(tenant)
    it = _items(jid, "Cement OPC", "Red brick")
    ccode, bcode = it["Cement OPC"][1], it["Red brick"][1]
    assert _order(tenant, jid, [{"description": "Brick", "item_code": bcode, "uom": "kg", "qty": 5, "price": 8}]).status_code == 200   # no sheet yet
    ok(_save(tenant, jid, (k["RCC"], ccode, 100, "")))
    ok(tenant.post("%s/%d/approve" % (BASE, jid)))

    res = _order(tenant, jid, [{"description": "Brick", "item_code": bcode, "uom": "kg", "qty": 5, "price": 8}])
    assert res.status_code == 400 and bcode in res.json()["detail"] and "not on the project's approved Item sheet" in res.json()["detail"]
    po = ok(_order(tenant, jid, [{"description": "Cement", "item_code": ccode, "uom": "kg", "qty": 60, "price": 8, "boq_key": k["RCC"]},
                                 {"description": "Freight to site", "item_code": "", "uom": "Lot", "qty": 1, "price": 500}]))
    assert not any(f.get("kind") == "sheet" for f in po.get("rate_flags") or [])
    more = ok(_order(tenant, jid, [{"description": "Cement", "item_code": ccode, "uom": "kg", "qty": 50, "price": 8, "boq_key": k["RCC"]}]))
    (flag,) = [f for f in more["rate_flags"] if f.get("kind") == "sheet"]
    assert "110" in flag["why"] and "100" in flag["why"]
    other = tenant.post("/api/jobs", json={"name": "Elsewhere", "customer_name": "X"}).json()
    assert _order(tenant, other.get("id") or other["job"]["id"], [{"description": "Brick", "item_code": bcode, "uom": "kg", "qty": 5, "price": 8}]).status_code == 200


def test_the_sheet_follows_each_material_through_order_receipt_indent_and_issue(tenant):
    jid, k = keyed(tenant)
    cement, ccode = _items(jid, "Cement OPC")["Cement OPC"]
    tag = uuid.uuid4().hex[:4].upper()
    site = ok(tenant.post("/api/store/masters/stores", json={"code": "SS" + tag, "name": "Site store", "type": "SITE", "project_id": jid}))
    ok(tenant.put("/api/store/masters/items/%d/settings" % cement, json={"category": "CONSUMABLE", "base_uom": "kg"}))
    ok(_save(tenant, jid, (k["RCC"], ccode, 300, ""), (k["MAS"], ccode, 100, "")))
    ok(tenant.post("%s/%d/approve" % (BASE, jid)))

    po = ok(_order(tenant, jid, [{"description": "Cement", "item_code": ccode, "uom": "kg", "qty": 250, "price": 8, "boq_key": k["RCC"]}]))
    s = ok(tenant.get("%s/%d" % (BASE, jid)))
    assert s["totals"][0]["awaiting"] == 250.0 and s["totals"][0]["ordered"] == 0.0
    with database.SessionLocal() as db:                                                  # approved in Approvals - not what this test is about
        db.get(models.DBPurchaseOrder, po["id"]).status = "Approved"
        db.commit()
    s = ok(tenant.get("%s/%d" % (BASE, jid)))
    (order,) = [o for o in s["orders"] if o["id"] == po["id"]]
    assert order["receivable"] and order["lines"][0]["pending"] == 250.0 and order["lines"][0]["boq_key"] == k["RCC"]

    grn = ok(tenant.post("/api/store/inward/grn", json={"store_id": site["id"], "grn_date": TODAY, "po_id": po["id"], "project_id": jid,
                                                       "lines": [{"po_line_id": order["lines"][0]["po_line_id"], "qty": "200", "uom": "kg"}]}))
    for step in ("submit", "approve", "post"):
        ok(tenant.post("/api/store/inward/grn/%d/%s" % (grn["id"], step)))

    rcc_line = _line(s, "RCC")["line_id"]
    ind = ok(tenant.post("/api/store/outward/indent", json={"store_id": site["id"], "project_id": jid, "boq_item_id": rcc_line, "activity": "Raft",
                                                         "lines": [{"item_id": cement, "qty": "120", "uom": "kg"}]}))
    ok(tenant.post("/api/store/outward/indent/%d/submit" % ind["id"]))
    ind = ok(tenant.post("/api/store/outward/indent/%d/approve" % ind["id"], json={}))
    iss = ok(tenant.post("/api/store/outward/issue", json={"store_id": site["id"], "issue_date": TODAY, "project_id": jid, "indent_id": ind["id"],
                                                        "received_by_type": "FOREMAN", "received_by_name": "Suresh",
                                                        "lines": [{"item_id": cement, "qty": "90", "uom": "kg", "indent_line_id": ind["lines"][0]["id"]}]}))
    for step in ("submit", "approve", "post"):
        ok(tenant.post("/api/store/outward/issue/%d/%s" % (iss["id"], step)))

    s = ok(tenant.get("%s/%d" % (BASE, jid)))
    t = s["totals"][0]
    assert (t["required"], t["ordered"], t["received"], t["indented"], t["issued"], t["at_site"], t["to_order"], t["to_receive"]) == \
        (400.0, 250.0, 200.0, 120.0, 90.0, 110.0, 150.0, 50.0)
    m = _line(s, "RCC")["materials"][0]
    assert (m["ordered"], m["received"], m["indented"], m["issued"]) == (250.0, 200.0, 120.0, 90.0)
    assert _line(s, "MAS")["materials"][0]["issued"] == 0.0
    assert [r["number"] for r in s["receipts"]] == [grn["number"]] and s["receipts"][0]["status"] == "POSTED"
    assert s["indents"][0]["boq_key"] == k["RCC"] and s["issues"][0]["indent_number"] == ind["number"]
    assert s["stores"][0]["id"] == site["id"] and s["stores"][0]["this_project"]


def test_another_business_cannot_see_or_change_the_sheet(tenant, second_tenant):
    jid, _k = keyed(tenant)
    assert second_tenant.get("%s/%d" % (BASE, jid)).status_code == 404
    assert second_tenant.put("%s/%d" % (BASE, jid), json={"materials": []}).status_code == 404
    assert second_tenant.post("%s/%d/items" % (BASE, jid), json={"item_name": "X", "units_of_measure": "kg"}).status_code == 404


def test_a_new_order_is_numbered_past_an_order_numbered_another_way(tenant):
    jid, _k = keyed(tenant)
    first = ok(_order(tenant, jid, [{"description": "Sand", "item_code": "", "uom": "cum", "qty": 1, "price": 100}]))
    with database.SessionLocal() as s:                                                # the newest order carries an imported number
        s.add(models.DBPurchaseOrder(client_id=s.get(models.DBJob, jid).client_id, job_id=jid, number="OLD-ERP/77", status="Draft", supplier_name="X"))
        s.commit()
    nxt = ok(_order(tenant, jid, [{"description": "Sand", "item_code": "", "uom": "cum", "qty": 1, "price": 100}]))
    assert int(nxt["number"].split("-")[1]) == int(first["number"].split("-")[1]) + 1
