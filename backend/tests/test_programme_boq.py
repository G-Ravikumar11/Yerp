"""Draw from BOQ: the client's sheet keeps its item numbers and its tree, is picked from, and lands on the programme as
headings and activities with their unit, quantity, rate, amount and BOQ Ref; a line can be split across units."""
from test_boq import make_boq, sheet
from test_programme_edit import add, ok, rows, url

# The APNRT sheet's shape, cut down: parts I and II, items 1, 2, sub-items 2.1, 2.1.1; a numbered heading with a long
# description (2.1), an item with a quantity and sub-items of its own (3.1), a priced line with no number under its
# heading (6.02), and a line of text under a heading that belongs to it (6.05).
APNRT = [
    ["BILL OF QUANTITIES"], ["Project", ": NRT Iconic Tower"], [],
    ["ITEM \nNO.", "DESCRIPTION OF ITEM", "UNIT", "QTY", "RATE", "AMOUNT", "REMARK"],
    [None, "Kindly refer general notes, preambles, technical specifications before quoting the rates for all items."],
    ["I", "CIVIL & STRUCTURE ( B2 TO GROUND FLOOR)"],
    ["1", "Dewatering"],
    ["1.1", "Pumping the collected water with adequate capacity pumps", "Hour", 1000, 650, 650000],
    ["2", "Excavation"],
    ["2.1", "Excavation in all kinds of soil other than rock for foundations, including dressing of sides and ramming of "
            "bottoms, lift upto 1.5 m"],
    ["2.1.1", " 0.0 mt. to EL -12.15 mt. ", "Cum.", 500, 1293, 646500, "Varies as per soil strata"],
    ["2.1.2", "-11.00 mt. to EL -14.00 mt. ", "Cum.", 500, 1293, 646500],
    ["2.2", "Disposal of Surplus/Unsuitable earth available in above excavation, as directed by the engineer in charge"],
    ["2.2.1", "Lead from site upto 1 km", "Cum.", 500, 44, 22000],
    ["2.2.2", "Same as above 2.2.1 but extra over lead from 1 km to 3 km", "Cum.", 500, 83, 41500],
    ["3", "Backfill"],
    ["3.1", "Providing and Filling in plinth, above Stiched Raft with approved soil", "cum", 1000, 62, 62000],
    ["3.1.1", "Providing and Filling in plinth, above Stiched Raft with sand", "cum", 1000, 970, 970000],
    ["6", "WATERPROOFING WORKS"],
    ["6.02", "Tanks (STP, UG, Lift Pit,Sump)"],
    [None, "Providing and applying two coats of Acrylic Cementitious coating", "sqm", 5493, 1020, 5602860],
    ["6.05", "Supplying and filling with broken pieces of AAC blocks in sunken portions"],
    [None, "\"Cost to include for proper compaction of the laid material.\""],
    ["6.05.1", "Sunken at all level (Location as per drawing)", "cum", 153, 7532, 1152396],
    ["II", "FINISHES"],
    ["1", "Flooring"],
    ["1.1", "Vitrified tiles 600x600 in floors", "sqm", 2000, 1450, 2900000],
]


def apnrt_boq(tenant):
    jid, boq = make_boq(tenant, "NRT Iconic Tower")
    read = tenant.post("/api/boqs/%d/import" % boq["id"], files={"file": ("boq.xlsx", sheet(APNRT))})
    assert read.status_code == 200, read.text
    lines = read.json()["lines"]
    ok(tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines}))
    return {"id": jid}, boq, lines


def tree(tenant, j):
    v = ok(tenant.get(url(j, "/boq")))
    by_ref = {}
    for n in v["items"]:                     # a heading first; an unnumbered line under it shares its ref
        by_ref.setdefault(n["ref"] + ("#own" if n["id"].endswith("#own") else ""), n)
    return v, by_ref


def draw(tenant, j, picks, **where):
    return tenant.post(url(j, "/from-boq"), json={"picks": picks, **where})


def test_the_import_keeps_item_numbers_and_numbered_headings(tenant):
    j, boq, lines = apnrt_boq(tenant)
    by_no = {l["item_no"]: l for l in lines if l["item_no"]}
    assert by_no["2.1"]["kind"] == "section", "a numbered line with no quantity is a heading, however long"
    assert by_no["2.1.1"]["kind"] == "item" and by_no["2.1.1"]["quantity"] == 500
    assert by_no["I"]["kind"] == "section"
    saved = ok(tenant.get("/api/boqs/%d" % boq["id"]))["lines"]
    assert [l["item_no"] for l in saved if l["item_no"]][:5] == ["I", "1", "1.1", "2", "2.1"], "kept through a save"


def test_the_boq_reads_as_a_tree_with_refs_and_short_names(tenant):
    j, _, _ = apnrt_boq(tenant)
    v, n = tree(tenant, j)
    assert v["numbered"] is True
    assert n["I"]["heading"] and n["I"]["parent"] is None and n["II"]["parent"] is None
    assert n["I-2.1"]["heading"] and n["I-2.1"]["parent"] == n["I-2"]["id"] and n["I-2.1"]["name"] == "Excavation in all kinds of soil other than rock"
    leaf = n["I-2.1.1"]
    assert not leaf["heading"] and leaf["parent"] == n["I-2.1"]["id"] and leaf["level"] == 3
    assert (leaf["uom"], leaf["quantity"], leaf["rate"], leaf["amount"]) == ("Cum.", 500, 1293, 646500)
    assert n["I-1.1"]["name"] == "Pumping the collected water"
    assert n["I-6.02"]["heading"] and n["I-6.02"]["name"] == "Tanks (STP, UG, Lift Pit,Sump)"
    tanks = [x for x in v["items"] if x["parent"] == n["I-6.02"]["id"]]
    assert len(tanks) == 1 and tanks[0]["ref"] == "I-6.02" and tanks[0]["quantity"] == 5493, "the unnumbered priced line is its work"
    assert "proper compaction" in n["I-6.05"]["description"], "a line of text under a heading is part of its description"
    # 3.1 has a quantity and a sub-item of its own: a heading, with its own work as its first sub-item
    assert n["I-3.1"]["heading"] and n["I-3.1#own"]["quantity"] == 1000 and n["I-3.1#own"]["parent"] == n["I-3.1"]["id"]
    assert n["II-1.1"]["parent"] == n["II-1"]["id"], "the numbering starts again under part II"


def test_picked_lines_come_with_their_headings_and_everything_from_the_boq(tenant):
    j, _, _ = apnrt_boq(tenant)
    _, n = tree(tenant, j)
    v = ok(draw(tenant, j, [{"id": n["I-2.1.1"]["id"]}, {"id": n["I-2.2.1"]["id"], "name": "Disposal within 1 km"},
                            {"id": n["I-2"]["id"], "name": "Earthwork"}]))
    got = [(r["wbs"], r["name"], r["boq_ref"]) for r in v["rows"]]
    assert got == [("1", "CIVIL & STRUCTURE", "I"), ("1.1", "Earthwork", "I-2"), ("1.1.1", "Excavation in all kinds of soil other than rock", "I-2.1"),
                   ("1.1.1.1", "0.0 mt. to EL -12.15 mt", "I-2.1.1"), ("1.1.2", "Disposal of Surplus/Unsuitable earth available in above", "I-2.2"),
                   ("1.1.2.1", "Disposal within 1 km", "I-2.2.1")], got
    r = rows(v)["0.0 mt. to EL -12.15 mt"]
    assert (r["uom"], r["quantity"], r["rate"], r["amount"]) == ("Cum.", 500, 1293, 646500)
    assert r["description"].startswith("0.0 mt. to EL -12.15 mt") and r["boq_key"]
    exc = rows(v)["Excavation in all kinds of soil other than rock"]
    assert exc["summary"] and "ramming of bottoms" in exc["description"]
    assert "2 BOQ lines" in v["message"]

    # drawn again later: the headings already there are used, not made twice
    v = ok(draw(tenant, j, [{"id": n["I-2.1.2"]["id"]}]))
    assert sum(1 for r in v["rows"] if r["boq_ref"] == "I-2.1") == 1
    assert [r["wbs"] for r in v["rows"] if r["boq_ref"] == "I-2.1.2"] == ["1.1.1.2"]
    _, n2 = tree(tenant, j)
    assert n2["I-2.1.1"]["drawn_rows"] == 1 and n2["I-1.1"]["drawn_rows"] == 0


def test_a_line_split_across_units_and_a_split_that_does_not_add_up_is_said(tenant):
    j, _, _ = apnrt_boq(tenant)
    _, n = tree(tenant, j)
    v = ok(draw(tenant, j, [{"id": n["II-1.1"]["id"], "name": "Vitrified tiles",
                             "splits": [{"label": "A-16", "quantity": 1200}, {"label": "A-18", "quantity": 600}]}]))
    tiles = [r for r in v["rows"] if r["boq_ref"] == "II-1.1"]
    assert [(r["name"], r["quantity"], r["amount"]) for r in tiles] == [("Vitrified tiles - A-16", 1200, 1740000), ("Vitrified tiles - A-18", 600, 870000)]
    assert v["warnings"] and "1800" in v["warnings"][0] and "2000" in v["warnings"][0]
    assert "Check:" in v["message"]
    _, n2 = tree(tenant, j)
    assert n2["II-1.1"]["drawn_rows"] == 2 and n2["II-1.1"]["drawn_quantity"] == 1800


def test_placed_under_a_row_of_our_own_and_started_on_a_date(tenant):
    j, _, _ = apnrt_boq(tenant)
    block, _ = add(tenant, j, "300 SFT Block Type - A")
    shifting, _ = add(tenant, j, "Shuttering material shifting", block, "child", start="2026-11-02", days=1)
    _, n = tree(tenant, j)
    v = ok(draw(tenant, j, [{"id": n["I-1.1"]["id"]}], anchor_id=block, position="child", start="2026-11-03"))
    got = [(r["wbs"], r["name"]) for r in v["rows"]]
    assert got == [("1", "300 SFT Block Type - A"), ("1.1", "Shuttering material shifting"), ("1.2", "CIVIL & STRUCTURE"),
                   ("1.2.1", "Dewatering"), ("1.2.1.1", "Pumping the collected water")], got
    assert rows(v)["Pumping the collected water"]["start"] == "2026-11-03"
    assert rows(v)["Shuttering material shifting"]["boq_ref"] == "", "a row of our own stays beside the BOQ's"


def test_an_item_with_its_own_quantity_and_sub_items(tenant):
    j, _, _ = apnrt_boq(tenant)
    _, n = tree(tenant, j)
    v = ok(draw(tenant, j, [{"id": n["I-3.1#own"]["id"]}, {"id": n["I-3.1.1"]["id"]}]))
    plinth = [r for r in v["rows"] if r["boq_ref"].startswith("I-3.1")]
    assert [(r["wbs"], r["summary"], r["quantity"]) for r in plinth] == [("1.1.1", True, 0), ("1.1.1.1", False, 1000), ("1.1.1.2", False, 1000)]
    assert plinth[1]["amount"] == 62000 and plinth[2]["amount"] == 970000


def test_nothing_ticked_or_no_boq_is_refused_in_words(tenant):
    j, _, _ = apnrt_boq(tenant)
    _, n = tree(tenant, j)
    res = draw(tenant, j, [{"id": n["I-2"]["id"]}])
    assert res.status_code == 400 and "line with a quantity" in res.json()["detail"]
    other = tenant.post("/api/jobs", json={"name": "No BOQ here", "customer_name": "X"}).json()
    other = {"id": other.get("id") or other["job"]["id"]}
    assert ok(tenant.get(url(other, "/boq")))["boq"] is None
    assert draw(tenant, other, [{"id": "x"}]).status_code == 409


def test_a_boq_saved_without_numbers_is_shown_by_section(tenant):
    from test_boq import CLIENT_SHEET
    jid, boq = make_boq(tenant, "Kokapet")
    lines = tenant.post("/api/boqs/%d/import" % boq["id"], files={"file": ("b.xlsx", sheet(CLIENT_SHEET))}).json()["lines"]
    ok(tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines}))
    v = ok(tenant.get(url({"id": jid}, "/boq")))
    assert v["numbered"] is False
    heads = [x["name"] for x in v["items"] if x["heading"]]
    assert heads == ["SUBSTRUCTURE", "SUPERSTRUCTURE"]
    assert [x["name"] for x in v["items"] if x["parent"] == v["items"][0]["id"]][:2] == ["Excavation in all types of soil", "M25 grade RCC in raft"]
