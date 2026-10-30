"""A work order built from the project BOQ reads like the BOQ sheet: main headings and the sub-headings under them, the
text written under a heading, each line's grade, contractor rates filled in from the budget (or the last order), lines
added up per heading with the grades kept apart, and the schedule numbered."""
from types import SimpleNamespace

import main
from test_boq import job_of_key, make_boq
from test_subcontract_orders import draft

PCC_TEXT = "Plain Cement Concrete corresponding to Mix (1:3:6) or M10 grade"
RCC_TEXT = "Vibrated Reinforced Cement Concrete: providing and laying"

SHEET = [
    {"kind": "section", "description": "PLAIN CEMENT CONCRETE"},
    {"kind": "note", "group_code": "SUBSTR-CW", "description": PCC_TEXT},
    {"kind": "item", "description": "Footings", "uom": "Cum.", "quantity": 277, "rate": 5230},
    {"kind": "item", "description": "Flooring", "uom": "Cum.", "quantity": 764, "rate": 5230},
    {"kind": "item", "description": "Retaining wall", "uom": "Cum.", "quantity": 23, "rate": 5230},
    {"kind": "section", "description": "REINFORCED CEMENT CONCRETE"},
    {"kind": "note", "group_code": "SUBSTR-CW", "description": RCC_TEXT},
    {"kind": "section", "description": "Basement-02(Grade Slab Lvl)"},
    {"kind": "item", "description": "Tower Columns(Found to Plinth)", "material": "M60", "uom": "Cum", "quantity": 61, "rate": 7800},
    {"kind": "item", "description": "Podium Columns(Found to Plinth)", "material": "M60", "uom": "Cum", "quantity": 4, "rate": 7800},
    {"kind": "item", "description": "Podium beams", "material": "M40", "uom": "Cum", "quantity": 10, "rate": 7500},
    {"kind": "section", "description": "Basement-01(1st slab Lvl)"},
    {"kind": "item", "description": "Tower Columns(Above Plinth to 1st Slab)", "material": "M60", "uom": "Cum", "quantity": 71, "rate": 8190},
    {"kind": "item", "description": "Podim Columns(Above Plinth to 1st Slab)", "material": "M60", "uom": "Cum", "quantity": 94, "rate": 8190},
    {"kind": "section", "description": "SHUTTERING"},
    {"kind": "item", "description": "Shuttering to columns", "uom": "sqm", "quantity": 500, "rate": 450},
]


def sheet_boq(tenant):
    jid, boq = make_boq(tenant, job_name="Vision Arsha")
    res = tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": SHEET, "issue_codes": True})
    assert res.status_code == 200, res.text
    lines = tenant.get("/api/boqs/%d/available" % boq["id"]).json()["lines"]
    return jid, boq, {l["description"]: l for l in lines}


def pull(tenant, order, current=(), lines=(), groups=()):
    res = tenant.post("/api/wo/orders/%d/boq-lines" % order["id"],
                      json={"lines": list(lines), "groups": list(groups), "current": list(current)})
    assert res.status_code == 200, res.text
    return res.json()


# --- the picker sees the sheet as it is -------------------------------------------------------------------------------

def test_main_headings_sub_headings_their_text_and_grades_reach_the_picker(tenant):
    _, _, by = sheet_boq(tenant)
    pcc, rcc, b02, b01, sh = (by[k] for k in ("PLAIN CEMENT CONCRETE", "REINFORCED CEMENT CONCRETE",
                                             "Basement-02(Grade Slab Lvl)", "Basement-01(1st slab Lvl)", "SHUTTERING"))
    assert [pcc["level"], rcc["level"], b02["level"], b01["level"], sh["level"]] == [0, 0, 1, 1, 0]
    assert b02["path"] == [rcc["key"]] and b01["path"] == [rcc["key"]]
    assert pcc["notes"] == PCC_TEXT and rcc["notes"] == RCC_TEXT
    tower = by["Tower Columns(Found to Plinth)"]
    assert tower["path"] == [rcc["key"], b02["key"]] and tower["material"] == "M60"
    assert by["Footings"]["path"] == [pcc["key"]] and by["Shuttering to columns"]["path"] == [sh["key"]]


def test_a_numbered_sheet_nests_by_its_numbers():
    from app.services.boq_outline import boq_outline
    line = lambda key, kind, no, text: SimpleNamespace(key=key, kind=kind, item_no=no, description=text, group_code="")
    heads, path, _ = boq_outline([line("a", "section", "I", "PART A"), line("b", "section", "1", "Earthwork"),
                                  line("c", "item", "1.1", "Excavation"), line("d", "section", "2", "Concrete"),
                                  line("e", "section", "2.1", "Footings"), line("f", "item", "2.1.1", "M20")])
    assert [heads[k]["level"] for k in "abde"] == [0, 1, 1, 2]
    assert path["f"] == ["a", "d", "e"] and path["c"] == ["a", "b"]


# --- adding lines: under their headings, in the sheet's order, numbered ------------------------------------------------

def test_lines_come_under_their_headings_in_the_sheets_order_and_numbered(tenant):
    _, _, by = sheet_boq(tenant)
    order = draft(tenant, job_id=job_of_key(by["Footings"]["key"]))
    out = pull(tenant, order, lines=[{"key": by["Tower Columns(Above Plinth to 1st Slab)"]["key"], "quantity": 71, "rate": 950},
                                     {"key": by["Footings"]["key"], "quantity": 277, "rate": 900}])
    rows = [(r["activity_no"], r["item_description"], r["is_header"], r["heading_level"]) for r in out["rows"]]
    assert rows == [("1", "PLAIN CEMENT CONCRETE", True, 1), ("1.1", "Footings", False, 0),
                    ("2", "REINFORCED CEMENT CONCRETE", True, 1), ("2.1", "Basement-01(1st slab Lvl)", True, 2),
                    ("2.1.1", "Tower Columns(Above Plinth to 1st Slab)", False, 0)]
    head = out["rows"][2]
    assert head["technical_spec"] == RCC_TEXT and head["boq_key"] == by["REINFORCED CEMENT CONCRETE"]["key"]
    assert out["rows"][4]["material"] == "M60" and out["rows"][4]["unit_rate"] == 950
    # The headings are not given twice when more lines under them are added.
    again = pull(tenant, order, current=out["rows"], lines=[{"key": by["Flooring"]["key"], "quantity": 764, "rate": 900}])
    names = [r["item_description"] for r in again["rows"]]
    assert names.count("PLAIN CEMENT CONCRETE") == 1 and names.index("Flooring") == names.index("Footings") + 1


def test_a_line_typed_by_hand_stays_under_the_line_it_was_typed_below(tenant):
    _, _, by = sheet_boq(tenant)
    order = draft(tenant, job_id=job_of_key(by["Footings"]["key"]))
    first = pull(tenant, order, lines=[{"key": by["Footings"]["key"], "quantity": 10, "rate": 900}])["rows"]
    typed = first + [{"item_description": "Curing extra", "uom": "LS", "quantity": 1, "unit_rate": 5000}]
    rows = pull(tenant, order, current=typed, lines=[{"key": by["Shuttering to columns"]["key"], "quantity": 5, "rate": 400}])["rows"]
    names = [r["item_description"] for r in rows]
    assert names == ["PLAIN CEMENT CONCRETE", "Footings", "Curing extra", "SHUTTERING", "Shuttering to columns"]


# --- the rate filled in: the budget first, then the last order ---------------------------------------------------------

def test_the_rate_comes_from_the_budget_then_the_last_rate_given(tenant):
    jid, _, by = sheet_boq(tenant)
    tenant.put("/api/jobs/%d/budget/lines/%s" % (jid, by["Footings"]["key"]), json={"items": [
        {"kind": "MATERIAL", "description": "Cement", "uom": "Bag", "coefficient": 6, "rate": 400},
        {"kind": "LABOUR", "description": "Mason", "uom": "day", "coefficient": 0.5, "rate": 1000},
        {"kind": "OTHER", "description": "Mixer hire", "uom": "hr", "coefficient": 1, "rate": 150}]})
    order = draft(tenant, job_id=jid)
    out = pull(tenant, order, lines=[{"key": by["Footings"]["key"], "quantity": 10}])
    assert (out["lines"][0]["unit_rate"], out["lines"][0]["rate_from"]) == (650, "budget")        # labour + plant, not our cement
    # A line with no budget takes the rate it was last given at, from an order whose rates were agreed.
    given = pull(tenant, order, lines=[{"key": by["Flooring"]["key"], "quantity": 5, "rate": 720}])["lines"]
    assert tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": given}).status_code == 200
    with main.SessionLocal() as db:
        db.get(main.models.DBSubcontractOrder, order["id"]).status = "APPROVED"
        db.commit()
    later = pull(tenant, draft(tenant, job_id=jid), lines=[{"key": by["Flooring"]["key"], "quantity": 5}])["lines"][0]
    assert (later["unit_rate"], later["rate_from"]) == (720, "last given")
    nothing = pull(tenant, draft(tenant, job_id=jid), lines=[{"key": by["Retaining wall"]["key"], "quantity": 5}])["lines"][0]
    assert nothing["unit_rate"] == 0 and nothing["rate_from"] == ""


# --- cumulative: a heading as one line, the grades apart ---------------------------------------------------------------

def test_a_sub_heading_added_up_sits_under_its_main_heading(tenant):
    _, boq, by = sheet_boq(tenant)
    order = draft(tenant, job_id=job_of_key(by["Footings"]["key"]))
    b02 = by["Basement-02(Grade Slab Lvl)"]
    m60 = [{"key": by[n]["key"], "quantity": by[n]["left"]} for n in ("Tower Columns(Found to Plinth)", "Podium Columns(Found to Plinth)")]
    out = pull(tenant, order, groups=[{"heading_key": b02["key"], "description": "Basement-02(Grade Slab Lvl) - M60", "rate": 1100, "parts": m60},
                                      {"heading_key": b02["key"], "description": "Basement-02(Grade Slab Lvl) - M40", "rate": 1050,
                                       "parts": [{"key": by["Podium beams"]["key"], "quantity": 10}]}])
    rows = [(r["activity_no"], r["item_description"], r["quantity"], r["material"]) for r in out["rows"]]
    assert rows == [("1", "REINFORCED CEMENT CONCRETE", 0, ""), ("1.1", "Basement-02(Grade Slab Lvl) - M60", 65, "M60"),
                    ("1.2", "Basement-02(Grade Slab Lvl) - M40", 10, "M40")]
    total = out["rows"][1]
    assert total["boq_key"] == b02["key"] and len(total["boq_parts"]) == 2
    assert out["rows"][0]["technical_spec"] == RCC_TEXT and total["technical_spec"] == ""      # the text once, on its heading
    # Saved, it keeps the heading it stands for, and each BOQ line still counts what was given against it.
    res = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": out["rows"]})
    assert res.status_code == 200, res.text
    items = res.json()["order"]["items"]
    assert [i["is_header"] for i in items] == [True, False, False] and items[0]["heading_level"] == 1
    assert items[1]["boq_key"] == b02["key"] and items[1]["material"] == "M60"
    left = {l["description"]: l["left"] for l in tenant.get("/api/boqs/%d/available" % boq["id"]).json()["lines"] if l["kind"] != "section"}
    assert left["Tower Columns(Found to Plinth)"] == 0 and left["Podium beams"] == 0 and left["Footings"] == 277


def test_without_a_rate_a_total_takes_the_suggested_rates_weighted_by_quantity(tenant):
    jid, _, by = sheet_boq(tenant)
    for name, labour in (("Tower Columns(Found to Plinth)", 1000), ("Podium Columns(Found to Plinth)", 2000)):
        tenant.put("/api/jobs/%d/budget/lines/%s" % (jid, by[name]["key"]),
                   json={"items": [{"kind": "LABOUR", "description": "Gang", "uom": "cum", "coefficient": 1, "rate": labour}]})
    order = draft(tenant, job_id=jid)
    parts = [{"key": by["Tower Columns(Found to Plinth)"]["key"], "quantity": 60}, {"key": by["Podium Columns(Found to Plinth)"]["key"], "quantity": 4}]
    line = pull(tenant, order, groups=[{"heading_key": by["Basement-02(Grade Slab Lvl)"]["key"], "parts": parts}])["lines"][0]
    assert line["unit_rate"] == round((60 * 1000 + 4 * 2000) / 64, 2) and line["rate_from"] == "budget"


def test_a_main_heading_added_up_takes_its_own_number_beside_the_headings(tenant):
    _, _, by = sheet_boq(tenant)
    order = draft(tenant, job_id=job_of_key(by["Footings"]["key"]))
    pcc = by["PLAIN CEMENT CONCRETE"]
    rows = pull(tenant, order, groups=[
        {"heading_key": pcc["key"], "description": "PLAIN CEMENT CONCRETE", "rate": 650,
         "parts": [{"key": by[n]["key"], "quantity": by[n]["left"]} for n in ("Footings", "Flooring", "Retaining wall")]},
        {"heading_key": by["Basement-01(1st slab Lvl)"]["key"], "description": "Basement-01(1st slab Lvl) - M60", "rate": 980,
         "parts": [{"key": by["Tower Columns(Above Plinth to 1st Slab)"]["key"], "quantity": 71}]},
        {"heading_key": by["SHUTTERING"]["key"], "description": "SHUTTERING", "rate": 400,
         "parts": [{"key": by["Shuttering to columns"]["key"], "quantity": 500}]}])["rows"]
    assert [(r["activity_no"], r["item_description"]) for r in rows] == [
        ("1", "PLAIN CEMENT CONCRETE"), ("2", "REINFORCED CEMENT CONCRETE"), ("2.1", "Basement-01(1st slab Lvl) - M60"),
        ("3", "SHUTTERING")]
    assert rows[0]["technical_spec"] == PCC_TEXT and not rows[0]["is_header"]           # its own text, as its own line


# --- the schedule kept like the sheet ----------------------------------------------------------------------------------

def test_arranging_puts_in_missing_headings_and_numbers_again_on_request(tenant):
    _, _, by = sheet_boq(tenant)
    order = draft(tenant, job_id=job_of_key(by["Footings"]["key"]))
    loose = [{"item_description": "Shuttering to columns", "boq_key": by["Shuttering to columns"]["key"], "activity_no": "9", "quantity": 1, "unit_rate": 1},
             {"item_description": "Footings", "boq_key": by["Footings"]["key"], "activity_no": "", "quantity": 1, "unit_rate": 1}]
    res = tenant.post("/api/wo/orders/%d/schedule/arrange" % order["id"], json={"rows": loose})
    rows = [(r["activity_no"], r["item_description"]) for r in res.json()["rows"]]
    assert rows == [("1", "PLAIN CEMENT CONCRETE"), ("1.1", "Footings"), ("2", "SHUTTERING"), ("9", "Shuttering to columns")]
    again = tenant.post("/api/wo/orders/%d/schedule/arrange" % order["id"], json={"rows": res.json()["rows"], "renumber": True}).json()["rows"]
    assert [r["activity_no"] for r in again] == ["1", "1.1", "2", "2.1"]


def test_the_printed_order_and_its_workbook_carry_the_headings_and_grades(tenant):
    _, _, by = sheet_boq(tenant)
    order = draft(tenant, job_id=job_of_key(by["Footings"]["key"]))
    rows = pull(tenant, order, lines=[{"key": by["Tower Columns(Found to Plinth)"]["key"], "quantity": 61, "rate": 950}])["rows"]
    assert tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": rows}).status_code == 200
    assert tenant.get("/api/wo/orders/%d/document.pdf" % order["id"]).status_code in (200, 503)
    book = tenant.get("/api/wo/orders/%d/boq.xlsx" % order["id"])
    assert book.status_code == 200
    import io
    import openpyxl
    sheet = openpyxl.load_workbook(io.BytesIO(book.content)).active
    cells = [[c for c in row] for row in sheet.iter_rows(values_only=True)]
    header = next(r for r in cells if r and r[0] == "Activity")
    assert "Material" in header
    tower = next(r for r in cells if r and r[2] == "Tower Columns(Found to Plinth)")
    assert tower[header.index("Material")] == "M60"
    heading = next(r for r in cells if r and r[2] == "REINFORCED CEMENT CONCRETE")
    assert heading[header.index("Amount")] in ("", None)


# --- the grade read off the heading, and the schedule made cumulative where it stands ------------------------------------

def test_a_line_with_no_grade_takes_the_one_its_heading_names(tenant):
    _, _, by = sheet_boq(tenant)
    assert by["Footings"]["material"] == "M10"                                  # "... Mix (1:3:6) or M10 grade" over it
    assert by["Tower Columns(Found to Plinth)"]["material"] == "M60"            # its own grade wins
    assert by["Shuttering to columns"]["material"] == ""                        # nothing names one
    order = draft(tenant, job_id=job_of_key(by["Footings"]["key"]))
    rows = pull(tenant, order, lines=[{"key": by["Footings"]["key"], "quantity": 10, "rate": 1}])["rows"]
    assert rows[1]["material"] == "M10"
    # A line already on a schedule without its grade gets it when the schedule is arranged.
    bare = [dict(rows[1], material="")]
    arranged = tenant.post("/api/wo/orders/%d/schedule/arrange" % order["id"], json={"rows": bare}).json()["rows"]
    assert arranged[1]["material"] == "M10"


def test_lines_already_on_the_schedule_are_made_cumulative_and_split_back(tenant):
    _, boq, by = sheet_boq(tenant)
    order = draft(tenant, job_id=job_of_key(by["Footings"]["key"]))
    picks = [("Footings", 277, 600), ("Flooring", 764, 650), ("Retaining wall", 23, 700),
             ("Tower Columns(Found to Plinth)", 61, 950), ("Podium Columns(Found to Plinth)", 4, 1000), ("Podium beams", 10, 900),
             ("Tower Columns(Above Plinth to 1st Slab)", 71, 980)]
    rows = pull(tenant, order, lines=[{"key": by[n]["key"], "quantity": q, "rate": r} for n, q, r in picks])["rows"]
    value = round(sum(q * r for _, q, r in picks), 2)
    url = "/api/wo/orders/%d/schedule/cumulative" % order["id"]

    main_level = tenant.post(url, json={"rows": rows, "level": 0, "keep_grades": True}).json()["rows"]
    got = [(r["activity_no"], r["item_description"], r["material"], r["quantity"]) for r in main_level]
    assert got == [("1", "PLAIN CEMENT CONCRETE - M10", "M10", 1064), ("2", "REINFORCED CEMENT CONCRETE - M60", "M60", 136),
                   ("3", "REINFORCED CEMENT CONCRETE - M40", "M40", 10)]
    assert round(sum(r["quantity"] * r["unit_rate"] for r in main_level), 0) == round(value, 0)     # the order's value holds
    assert len(main_level[1]["boq_parts"]) == 3

    sub_level = tenant.post(url, json={"rows": rows, "level": 1, "keep_grades": True}).json()["rows"]
    assert [(r["activity_no"], r["item_description"]) for r in sub_level] == [
        ("1", "PLAIN CEMENT CONCRETE - M10"), ("2", "REINFORCED CEMENT CONCRETE"),
        ("2.1", "Basement-02(Grade Slab Lvl) - M60"), ("2.2", "Basement-02(Grade Slab Lvl) - M40"),
        ("2.3", "Basement-01(1st slab Lvl) - M60")]

    together = tenant.post(url, json={"rows": rows, "level": 0, "keep_grades": False}).json()["rows"]
    assert [r["item_description"] for r in together] == ["PLAIN CEMENT CONCRETE", "REINFORCED CEMENT CONCRETE"]

    saved = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": main_level})
    assert saved.status_code == 200, saved.text
    left = {l["description"]: l["left"] for l in tenant.get("/api/boqs/%d/available" % boq["id"]).json()["lines"] if l["kind"] != "section"}
    assert left["Flooring"] == 0 and left["Podium beams"] == 0                  # every BOQ line still counted

    back = tenant.post(url, json={"rows": main_level, "split": True}).json()["rows"]
    lines = [r for r in back if not r["is_header"]]
    assert sorted(r["item_description"] for r in lines) == sorted(n for n, _, _ in picks)
    assert {r["item_description"]: r["quantity"] for r in lines}["Flooring"] == 764
    assert [r["item_description"] for r in back if r["is_header"]] == ["PLAIN CEMENT CONCRETE", "REINFORCED CEMENT CONCRETE",
                                                                         "Basement-02(Grade Slab Lvl)", "Basement-01(1st slab Lvl)"]
