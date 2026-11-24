"""The project's Item sheet in the store: lines under the BOQ's group codes, items from the item master with their HSN, made
in the app or uploaded from the template, approved by the Master - and then an indent may ask only for what is on it."""
import io
import uuid

import openpyxl

from app import db as database, models
from store.test_cutover import _leave_no_stock_behind, ok  # noqa: F401
from test_budgeting import keyed

BASE = "/api/store/item-sheet"


def _items(jid, *names):
    """Stock items in the master of the project's company, with an HSN: {name: code}."""
    out = {}
    with database.SessionLocal() as s:
        client_id = s.get(models.DBJob, jid).client_id
        for name in names:
            it = models.DBItem(client_id=client_id, kind="RM", item_code="IS-%s" % uuid.uuid4().hex[:8].upper(), item_name=name,
                               units_of_measure="kg", hsn_code="2523")
            s.add(it)
            s.flush()
            out[name] = (it.id, it.item_code)
        s.commit()
    return out


def _upload(t, jid, rows):
    wb = openpyxl.Workbook()
    wb.active.title = "Item sheet"
    wb.active.append(["Group code", "Item code", "Item name", "HSN", "Unit", "Quantity", "Remarks"])
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return t.post("%s/%d/upload" % (BASE, jid), files={"file": ("sheet.xlsx", buf.getvalue())})


def test_a_sheet_is_made_under_the_boqs_group_codes_with_hsn_from_the_master(tenant):
    jid, _k = keyed(tenant)
    it = _items(jid, "Cement OPC", "TMT 12 mm")
    s = ok(tenant.get("%s/%d" % (BASE, jid)))
    assert not s["exists"] and {"RCC", "MAS"} <= set(s["groups"])
    s = ok(tenant.put("%s/%d" % (BASE, jid), json={"lines": [
        {"group_code": "rcc", "item_code": it["Cement OPC"][1], "qty": 500},
        {"group_code": "MAS", "item_code": it["Cement OPC"][1], "qty": 120, "remarks": "CM 1:6"},
        {"group_code": "RCC", "item_code": it["TMT 12 mm"][1], "qty": 9000}]}))
    assert s["status"] == "DRAFT" and len(s["lines"]) == 3
    first = s["lines"][0]
    assert (first["group_code"], first["item_name"], first["hsn"], first["unit"], first["qty"]) == ("RCC", "Cement OPC", "2523", "kg", 500.0)


def test_a_wrong_group_or_item_saves_nothing_and_says_what_is_wrong(tenant):
    jid, _k = keyed(tenant)
    it = _items(jid, "Cement OPC")
    res = tenant.put("%s/%d" % (BASE, jid), json={"lines": [
        {"group_code": "XYZ", "item_code": it["Cement OPC"][1], "qty": 5},
        {"group_code": "RCC", "item_code": "NO-SUCH", "qty": 5},
        {"group_code": "RCC", "item_code": it["Cement OPC"][1], "qty": 0}]})
    assert res.status_code == 400
    d = res.json()["detail"]
    assert "'XYZ' is not on the project's BOQ" in d and "'NO-SUCH' is not in the item master" in d and "above 0" in d
    assert not ok(tenant.get("%s/%d" % (BASE, jid)))["exists"]


def test_the_template_downloads_with_the_boq_group_codes_and_uploads_back(tenant):
    jid, _k = keyed(tenant)
    it = _items(jid, "Cement OPC")
    res = tenant.get("%s/%d/template.xlsx" % (BASE, jid))
    assert res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    assert [c.value for c in wb["Item sheet"][1]] == ["Group code", "Item code", "Item name", "HSN", "Unit", "Quantity", "Remarks"]
    assert "RCC" in [r[0].value for r in wb["BOQ group codes"].iter_rows(min_row=2)]

    bad = _upload(tenant, jid, [["RCC", it["Cement OPC"][1], "", "", "", 300, ""], ["PQR", it["Cement OPC"][1], "", "", "", 3, ""]])
    assert bad.status_code == 400 and "Row 3" in bad.json()["detail"]
    s = ok(_upload(tenant, jid, [["RCC", it["Cement OPC"][1], "typed name is not read", "", "", 300, "raft"]]))
    assert [(l["group_code"], l["item_name"], l["qty"], l["remarks"]) for l in s["lines"]] == [("RCC", "Cement OPC", 300.0, "raft")]

    again = openpyxl.load_workbook(io.BytesIO(tenant.get("%s/%d/template.xlsx" % (BASE, jid)).content))["Item sheet"]
    assert [c.value for c in again[2]][:3] == ["RCC", it["Cement OPC"][1], "Cement OPC"]


def test_the_master_approves_and_a_change_waits_for_approval_again(tenant):
    jid, _k = keyed(tenant)
    it = _items(jid, "Cement OPC")
    code = it["Cement OPC"][1]
    ok(tenant.put("%s/%d" % (BASE, jid), json={"lines": [{"group_code": "RCC", "item_code": code, "qty": 100}]}))
    s = ok(tenant.post("%s/%d/approve" % (BASE, jid)))                              # the Master may approve a draft straight away
    assert s["status"] == "APPROVED" and s["approved"]
    s = ok(tenant.put("%s/%d" % (BASE, jid), json={"lines": [{"group_code": "RCC", "item_code": code, "qty": 150}]}))
    assert s["status"] == "DRAFT" and s["approved"] and s["changed_since_approval"]
    assert s["usage"][0]["sheet_qty"] == 100.0                                       # the approved copy is still the one in force
    s = ok(tenant.post("%s/%d/submit" % (BASE, jid)))
    assert s["status"] == "SUBMITTED"
    assert tenant.post("%s/%d/send-back" % (BASE, jid), json={"note": ""}).status_code == 400
    s = ok(tenant.post("%s/%d/send-back" % (BASE, jid), json={"note": "Check the steel"}))
    assert s["status"] == "DRAFT" and s["returned_note"] == "Check the steel"
    ok(tenant.post("%s/%d/submit" % (BASE, jid)))
    s = ok(tenant.post("%s/%d/approve" % (BASE, jid)))
    assert s["status"] == "APPROVED" and not s["changed_since_approval"] and s["usage"][0]["sheet_qty"] == 150.0


def test_an_indent_asks_only_for_items_on_the_approved_sheet(tenant):
    jid, _k = keyed(tenant)
    it = _items(jid, "Cement OPC", "Red brick")
    (cement, ccode), (brick, _b) = it["Cement OPC"], it["Red brick"]
    store = ok(tenant.post("/api/store/masters/stores", json={"code": "IS" + uuid.uuid4().hex[:4].upper(), "name": "Central", "type": "CENTRAL"}))
    body = lambda item, qty: {"store_id": store["id"], "project_id": jid, "activity": "Raft", "lines": [{"item_id": item, "qty": str(qty), "uom": "kg"}]}

    early = ok(tenant.post("/api/store/outward/indent", json=body(brick, 10)))          # no sheet yet: anything may be asked for
    ok(tenant.put("%s/%d" % (BASE, jid), json={"lines": [{"group_code": "RCC", "item_code": ccode, "qty": 100}]}))
    ok(tenant.post("/api/store/outward/indent", json=body(brick, 10)))                   # a sheet not yet approved holds nothing
    ok(tenant.post("%s/%d/approve" % (BASE, jid)))

    res = tenant.post("/api/store/outward/indent", json=body(brick, 10))
    assert res.status_code == 400 and "not on the project's approved Item sheet" in res.json()["detail"]
    res = tenant.post("/api/store/outward/indent/%d/submit" % early["id"])                 # a draft from before is held to it too
    assert res.status_code == 400

    fine = ok(tenant.post("/api/store/outward/indent", json=body(cement, 80)))
    assert fine["sheet_warnings"] == []
    ok(tenant.post("/api/store/outward/indent/%d/submit" % fine["id"]))
    more = ok(tenant.post("/api/store/outward/indent", json=body(cement, 40)))             # 80 + 40 past the sheet's 100: warned, not stopped
    (w,) = more["sheet_warnings"]
    assert "Cement OPC" in w and "120" in w and "100" in w


def test_another_business_cannot_see_or_change_the_sheet(tenant, second_tenant):
    jid, _k = keyed(tenant)
    assert second_tenant.get("%s/%d" % (BASE, jid)).status_code == 404
    assert second_tenant.put("%s/%d" % (BASE, jid), json={"lines": []}).status_code == 404
