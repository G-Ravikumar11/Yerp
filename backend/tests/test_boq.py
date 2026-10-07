"""The project BOQ: read as the client sends it, coded from the item master, revised, and tracked against the gangs."""
import io

import openpyxl

import main
from test_subcontract_orders import masters, draft, fund_order


def sheet(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Off a client's desk: a title block above the headings, section rows, items, sub-items and its own grand total.
CLIENT_SHEET = [
    ["M/s Kokapet Towers LLP"], ["BILL OF QUANTITIES - TOWER C"], [],
    ["Sl.No", "Description of work", "Unit", "Qty", "Rate (Rs)", "Amount (Rs)"],
    ["A", "SUBSTRUCTURE", None, None, None, None],
    ["1.1", "Excavation in all types of soil", "cum", 500, 180, 90000],
    ["1.2", "M25 grade RCC in raft", "cum", 120, 8200, 984000],
    ["a", "Shuttering to raft edges", "sqm", 80, 410, 32800],
    ["B", "SUPERSTRUCTURE", None, None, None, None],
    ["2.1", "Brick masonry in CM 1:6", "cum", 60, 6100, 366000],
    ["", "Grand Total", None, None, None, 1472800],
]


def make_boq(tenant, job_name="Kokapet Towers"):
    job = tenant.post("/api/jobs", json={"name": job_name, "customer_name": "Kokapet LLP"}).json()
    jid = job.get("id") or job["job"]["id"]
    res = tenant.post("/api/boqs", json={"job_id": jid})
    assert res.status_code == 200, res.text
    return jid, res.json()["boq"]


def import_lines(tenant, boq):
    res = tenant.post("/api/boqs/%d/import" % boq["id"], files={"file": ("boq.xlsx", sheet(CLIENT_SHEET))})
    assert res.status_code == 200, res.text
    return res.json()


def saved(tenant, boq, issue_codes=True):
    lines = import_lines(tenant, boq)["lines"]
    res = tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines, "issue_codes": issue_codes})
    assert res.status_code == 200, res.text
    return res.json()


# --- reading the client's sheet --------------------------------------------------------------------------------------

def test_a_clients_sheet_is_read_as_it_comes(tenant):
    _, boq = make_boq(tenant)
    out = import_lines(tenant, boq)
    kinds = [(l["kind"], l["sno"]) for l in out["lines"]]
    assert kinds == [("section", "A"), ("item", "1.1"), ("item", "1.2"), ("sub", "a"), ("section", "B"), ("item", "2.1")]
    assert out["total"] == 1472800 and not out["warnings"]
    assert out["skipped_rows"] == 1                       # the sheet's own grand total, checked and left out


def test_a_sheets_wrong_total_or_amount_is_called_out(tenant):
    _, boq = make_boq(tenant)
    rows = [list(r) for r in CLIENT_SHEET]
    rows[-1][5] = 999999                                   # the grand total
    rows[5][5] = 95000                                     # an amount that is not qty x rate
    res = tenant.post("/api/boqs/%d/import" % boq["id"], files={"file": ("b.xlsx", sheet(rows))}).json()
    text = " ".join(res["warnings"])
    assert "grand total is" in text and "180" in text


def test_a_sheet_that_is_not_a_boq_is_refused_in_words(tenant):
    _, boq = make_boq(tenant)
    res = tenant.post("/api/boqs/%d/import" % boq["id"], files={"file": ("b.xlsx", sheet([["Name", "Phone"], ["A", "1"]]))})
    assert res.status_code == 400 and "description and quantity" in res.json()["detail"]


# --- saving, totals and item codes ---------------------------------------------------------------------------------------

def test_saved_lines_add_up_by_section_and_get_item_codes_from_the_master(tenant):
    _, boq = make_boq(tenant)
    out = saved(tenant, boq)
    assert out["total"] == 1472800
    sections = [l for l in out["lines"] if l["kind"] == "section"]
    assert [s["subtotal"] for s in sections] == [1106800, 366000]
    priced = [l for l in out["lines"] if l["kind"] in ("item", "sub")]
    codes = [l["item_code"] for l in priced]
    assert all(codes) and len(set(codes)) == len(codes)
    assert "4 item codes given" in out["message"]
    items = tenant.get("/api/erp/items", params={"kind": "FG"}).json()
    names = {i["item_code"]: i["item_name"] for i in (items["items"] if isinstance(items, dict) else items)}
    assert names[codes[0]] == "Excavation in all types of soil"


def test_saving_again_keeps_each_lines_key_and_code_and_issues_nothing_twice(tenant):
    _, boq = make_boq(tenant)
    first = saved(tenant, boq)
    again = tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": first["lines"], "issue_codes": True}).json()
    assert [l["key"] for l in again["lines"]] == [l["key"] for l in first["lines"]]
    assert [l["item_code"] for l in again["lines"]] == [l["item_code"] for l in first["lines"]]
    assert "code" not in again["message"].split("saved,")[-1]


def test_a_line_pasted_with_the_name_of_an_existing_item_takes_that_items_code(tenant):
    _, boq = make_boq(tenant)
    first = saved(tenant, boq)
    code = first["lines"][1]["item_code"]
    line = {"kind": "item", "sno": "9.9", "description": "Excavation in all types of soil", "uom": "cum", "quantity": 10, "rate": 200}
    # the first line holding that code is removed, so the code is free for the pasted line to take
    rest = [l for l in first["lines"] if l["item_code"] != code]
    res = tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": rest + [line], "issue_codes": True}).json()
    assert [l for l in res["lines"] if l["sno"] == "9.9"][0]["item_code"] == code


def test_one_boq_to_a_project_and_negative_figures_are_refused(tenant):
    jid, boq = make_boq(tenant)
    assert tenant.post("/api/boqs", json={"job_id": jid}).status_code == 409
    bad = {"lines": [{"kind": "item", "description": "x", "quantity": -1, "rate": 5}]}
    assert tenant.put("/api/boqs/%d/lines" % boq["id"], json=bad).status_code == 400


# --- revisions ---------------------------------------------------------------------------------------------------------

def test_a_new_revision_locks_the_old_one_and_the_changes_are_listed(tenant):
    _, boq = make_boq(tenant)
    first = saved(tenant, boq)
    rev = tenant.post("/api/boqs/%d/revisions" % boq["id"], json={"label": "R1 - Award", "note": "after negotiation"})
    assert rev.status_code == 200, rev.text
    r1 = tenant.get("/api/boqs/%d" % boq["id"]).json()
    assert r1["boq"]["current_rev"] == 1 and r1["editable"] and [r["status"] for r in r1["revisions"]] == ["ISSUED", "OPEN"]
    assert tenant.get("/api/boqs/%d" % boq["id"], params={"rev": 0}).json()["editable"] is False
    lines = r1["lines"]
    lines[1]["quantity"] = 650                                     # excavation 500 -> 650
    lines = [l for l in lines if l["sno"] != "2.1"]                # masonry removed
    lines.append({"kind": "item", "sno": "3.1", "description": "Plastering", "uom": "sqm", "quantity": 100, "rate": 90})
    assert tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines}).status_code == 200
    ch = tenant.get("/api/boqs/%d/changes" % boq["id"], params={"frm": 0}).json()
    by = {c["change"]: c for c in ch["changes"]}
    assert set(by) == {"added", "removed", "changed"} and "quantity 500.0 -> 650.0" in by["changed"]["detail"]
    assert ch["difference"] == by["added"]["amount"] + by["removed"]["amount"] + by["changed"]["amount"]


def test_an_issued_revision_cannot_be_edited_by_saving(tenant):
    _, boq = make_boq(tenant)
    saved(tenant, boq)
    tenant.post("/api/boqs/%d/revisions" % boq["id"], json={})
    # revision 0 is closed; saving goes to the open one, and the old one is untouched
    assert tenant.get("/api/boqs/%d" % boq["id"], params={"rev": 0}).json()["total"] == 1472800


# --- gang orders against the BOQ ---------------------------------------------------------------------------------------

def gang_order(tenant, boq_lines, picks, order=None):
    """A draft gang order whose schedule is the BOQ lines picked: [(boq line, quantity, gang rate)]."""
    order = order or draft(tenant)
    pulled = tenant.post("/api/wo/orders/%d/boq-lines" % order["id"],
                         json={"lines": [{"key": l["key"], "quantity": q, "rate": r} for l, q, r in picks]}).json()
    res = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": pulled["lines"]})
    assert res.status_code == 200, res.text
    return order, pulled, res.json()


def test_lines_are_pulled_from_the_boq_into_a_gang_order_and_keep_their_link(tenant):
    _, boq = make_boq(tenant)
    lines = {l["sno"]: l for l in saved(tenant, boq)["lines"]}
    order, pulled, res = gang_order(tenant, lines, [(lines["1.1"], 300, 150)])
    assert pulled["lines"][0]["item_description"] == "Excavation in all types of soil" and pulled["warnings"] == []
    assert res["order"]["items"][0]["boq_key"] == lines["1.1"]["key"] and res["warnings"] == []


def test_giving_more_than_the_boq_allows_is_warned_not_refused(tenant):
    _, boq = make_boq(tenant)
    lines = {l["sno"]: l for l in saved(tenant, boq)["lines"]}
    gang_order(tenant, lines, [(lines["1.1"], 300, 150)])
    pulled = tenant.post("/api/wo/orders/%d/boq-lines" % draft(tenant)["id"],
                         json={"lines": [{"key": lines["1.1"]["key"], "quantity": 300, "rate": 150}]}).json()
    assert "600" in pulled["warnings"][0] and "500" in pulled["warnings"][0]
    _, _, res = gang_order(tenant, lines, [(lines["1.1"], 300, 150)])
    assert res["warnings"] and "Over the BOQ" in res["message"]


def test_the_tracker_adds_up_what_the_gangs_have_and_flags_what_is_wrong(tenant):
    _, boq = make_boq(tenant)
    lines = {l["sno"]: l for l in saved(tenant, boq)["lines"]}
    gang_order(tenant, lines, [(lines["1.1"], 300, 150), (lines["1.2"], 120, 9000)])      # the second is at a loss
    t = tenant.get("/api/boqs/%d/tracker" % boq["id"]).json()
    rows = {r["sno"]: r for r in t["rows"] if r["kind"] != "section"}
    assert rows["1.1"]["given"] == 300 and rows["1.1"]["gang_rate"] == 150 and rows["1.1"]["left_to_give"] == 200
    assert rows["1.1"]["margin_percent"] == round((180 - 150) / 180 * 100, 1) and rows["1.1"]["flags"] == []
    assert "loss" in rows["1.2"]["flags"] and "no_gang" in rows["2.1"]["flags"] and "no_gang" in rows["a"]["flags"]
    assert t["flags"]["loss"] == 1 and t["flags"]["no_gang"] == 2


def test_a_cancelled_gang_order_no_longer_counts_against_the_boq(tenant):
    _, boq = make_boq(tenant)
    lines = {l["sno"]: l for l in saved(tenant, boq)["lines"]}
    order, _, _ = gang_order(tenant, lines, [(lines["1.1"], 300, 150)])
    tenant.post("/api/wo/orders/%d/cancel" % order["id"], json={"comments": "x"})
    rows = {r["sno"]: r for r in tenant.get("/api/boqs/%d/tracker" % boq["id"]).json()["rows"] if r["kind"] != "section"}
    assert rows["1.1"]["given"] == 0


# --- the client's order, export, tender -------------------------------------------------------------------------------

def test_the_clients_work_order_is_drawn_from_the_boq_once(tenant):
    jid, boq = make_boq(tenant)
    saved(tenant, boq, issue_codes=False)
    refused = tenant.post("/api/boqs/%d/client-order" % boq["id"], json={})
    assert refused.status_code == 409 and "item code" in refused.json()["detail"]
    saved(tenant, boq, issue_codes=True)
    made = tenant.post("/api/boqs/%d/client-order" % boq["id"], json={"reference": "PO-77"})
    assert made.status_code == 200, made.text
    wo = made.json()["work_order"]
    assert len(wo["lines"]) == 4 and wo["total_value"] == 1472800
    assert tenant.post("/api/boqs/%d/client-order" % boq["id"], json={}).status_code == 409


def test_the_boq_goes_to_excel_and_to_paper(tenant):
    _, boq = make_boq(tenant)
    saved(tenant, boq)
    x = tenant.get("/api/boqs/%d/export.xlsx" % boq["id"])
    assert x.status_code == 200
    cells = [c.value for ws in openpyxl.load_workbook(io.BytesIO(x.content)).worksheets for row in ws.iter_rows() for c in row if c.value is not None]
    assert "SUBSTRUCTURE" in cells and 1472800 in cells
    assert tenant.get("/api/boqs/%d/export.pdf" % boq["id"]).status_code == 200


def test_a_won_tender_becomes_the_boq(tenant):
    job = tenant.post("/api/jobs", json={"name": "Tendered job"}).json()
    jid = job.get("id") or job["job"]["id"]
    est = tenant.post("/api/estimates", json={"title": "Tender", "job_id": jid}).json()
    eid = est.get("id") or est["estimate"]["id"]
    with main.SessionLocal() as db:
        db.add(main.models.DBEstimateItem(estimate_id=eid, item_no="1.1", description="Piling", uom="m", quantity=100, quoted_rate=900, display_order=0))
        db.commit()
    res = tenant.post("/api/boqs/from-estimate/%d" % eid)
    assert res.status_code == 200, res.text
    got = tenant.get("/api/boqs/%d" % res.json()["boq"]["id"]).json()
    assert got["total"] == 90000 and got["lines"][0]["description"] == "Piling"


def test_the_kinds_of_row_are_told_apart():
    kind = main.boq_kind_of
    assert kind("1.1", "Excavation", 5, 10) == "item" and kind("a", "Edges", 5, 10) == "sub"
    assert kind("1.2.b", "Edges", 5, 10) == "sub" and kind("(ii)", "Edges", 5, 10) == "sub"
    assert kind("A", "SUBSTRUCTURE", 0, 0) == "section" and kind("", "FINISHING WORKS", 0, 0) == "section"
    assert kind("", "All rates include supply, fixing and curing unless stated otherwise in the specification.", 0, 0) == "note"
