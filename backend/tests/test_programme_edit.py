"""Changing the programme through the grid's endpoints: rows and sub-items, typed dates, predecessors, moving, copying
units, deleting, the working week and holidays, and undo."""
from datetime import date, timedelta

from test_schedule import job


def _monday():
    t = date.today() + timedelta(days=21)
    return t - timedelta(days=t.weekday())


def url(j, tail=""):
    return "/api/jobs/%d/programme%s" % (j["id"], tail)


def ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def add(tenant, j, name, anchor=None, position="end", **values):
    v = ok(tenant.post(url(j, "/rows"), json={"anchor_id": anchor, "position": position, "rows": [{"name": name, **values}]}))
    return v["made"][0], v


def edit(tenant, j, rid, **values):
    return tenant.patch(url(j, "/rows"), json={"changes": [{"id": rid, **values}]})


def rows(view):
    return {r["name"]: r for r in view["rows"]}


def unit_with_painting(tenant, j, start):
    """A-16 > Internal Painting > Putty, Primer, Paint, each waiting on the one before."""
    unit, _ = add(tenant, j, "A-16")
    paint, _ = add(tenant, j, "Internal Painting", unit, "child")
    putty, _ = add(tenant, j, "Putty", paint, "child", start=start.isoformat(), days=3)
    primer, _ = add(tenant, j, "Primer", putty, "after", days=1)
    final, _ = add(tenant, j, "Paint", primer, "after", days=2)
    ok(edit(tenant, j, primer, predecessors="1.1.1"))
    v = ok(edit(tenant, j, final, predecessors="1.1.2"))
    return {"unit": unit, "painting": paint, "putty": putty, "primer": primer, "paint": final}, v


def test_rows_and_sub_items_are_numbered_and_their_heading_spans_them(tenant):
    mon = _monday()
    j = job(tenant)
    ids, v = unit_with_painting(tenant, j, mon)
    assert [r["wbs"] for r in v["rows"]] == ["1", "1.1", "1.1.1", "1.1.2", "1.1.3"]
    r = rows(v)
    assert r["Primer"]["start"] == (mon + timedelta(days=3)).isoformat() and r["Primer"]["predecessors"] == "1.1.1"
    assert r["Paint"]["end"] == (mon + timedelta(days=5)).isoformat()             # Thu-Fri... Paint: Fri, Sat
    assert r["A-16"]["summary"] and r["A-16"]["start"] == mon.isoformat() and r["A-16"]["end"] == r["Paint"]["end"]


def test_end_gives_days_and_days_give_end_skipping_sunday(tenant):
    mon = _monday()
    j = job(tenant)
    rid, _ = add(tenant, j, "Cupboard work", start=mon.isoformat(), days=10)
    r = rows(ok(edit(tenant, j, rid)))["Cupboard work"]
    assert r["end"] == (mon + timedelta(days=10)).isoformat()                     # 10 working days pass one Sunday
    r = rows(ok(edit(tenant, j, rid, end=(mon + timedelta(days=4)).isoformat())))["Cupboard work"]
    assert r["days"] == 5 and r["typed"]["days"] == 5
    assert edit(tenant, j, rid, end=(mon - timedelta(days=1)).isoformat()).status_code == 400


def test_a_headings_dates_cannot_be_typed(tenant):
    mon = _monday()
    j = job(tenant)
    ids, _ = unit_with_painting(tenant, j, mon)
    res = edit(tenant, j, ids["unit"], start=mon.isoformat())
    assert res.status_code == 400 and "sub-items" in res.json()["detail"]


def test_predecessors_with_type_and_lag_and_a_loop_is_refused(tenant):
    mon = _monday()
    j = job(tenant)
    ids, _ = unit_with_painting(tenant, j, mon)
    r = rows(ok(edit(tenant, j, ids["paint"], predecessors="1.1.2SS+1")))["Paint"]
    assert r["predecessors"] == "1.1.2SS+1"
    assert edit(tenant, j, ids["paint"], predecessors="9.9").status_code == 400
    res = edit(tenant, j, ids["putty"], predecessors="1.1.3")                     # Putty after Paint: a loop
    assert res.status_code == 400 and "Circular dependency" in res.json()["detail"]
    assert rows(ok(tenant.get(url(j))))["Putty"]["predecessors"] == "", "nothing of the refused change is kept"


def test_indent_outdent_and_moving_under_itself(tenant):
    j = job(tenant)
    a, _ = add(tenant, j, "Reinforcement")
    b, _ = add(tenant, j, "Shuttering")
    v = ok(tenant.post(url(j, "/move"), json={"id": b, "parent_id": a}))       # indent under the row above
    assert [r["wbs"] for r in v["rows"]] == ["1", "1.1"] and rows(v)["Shuttering"]["parent_id"] == a
    assert tenant.post(url(j, "/move"), json={"id": a, "parent_id": b}).status_code == 400
    v = ok(tenant.post(url(j, "/move"), json={"id": b, "parent_id": None, "before_id": a}))   # out, and to the top
    assert [r["name"] for r in v["rows"]] == ["Shuttering", "Reinforcement"]


def test_duplicate_copies_the_rows_under_it_and_their_links(tenant):
    mon = _monday()
    j = job(tenant)
    ids, _ = unit_with_painting(tenant, j, mon)
    v = ok(tenant.post(url(j, "/rows/%d/duplicate" % ids["painting"])))
    names = [r["name"] for r in v["rows"]]
    assert names == ["A-16", "Internal Painting", "Putty", "Primer", "Paint", "Internal Painting (copy)", "Putty", "Primer", "Paint"]
    copy = [r for r in v["rows"] if r["wbs"].startswith("1.2.")]
    assert [r["predecessors"] for r in copy] == ["", "1.2.1", "1.2.2"], "the copy's links point within the copy"


def test_copy_to_other_units_with_a_start_date_or_an_offset(tenant):
    mon = _monday()
    j = job(tenant)
    ids, _ = unit_with_painting(tenant, j, mon)
    outside, _ = add(tenant, j, "Shuttering material shifting", start=mon.isoformat(), days=1)
    ok(edit(tenant, j, ids["putty"], predecessors="2"))                       # A-16's putty waits on the shifting
    v = ok(tenant.post(url(j, "/copy"), json={"source_id": ids["unit"], "targets": [
        {"name": "A-18", "start": (mon + timedelta(days=14)).isoformat()}, {"name": "B-23", "offset": 7}]}))
    tops = [r for r in v["rows"] if r["level"] == 0]
    assert [t["name"] for t in tops] == ["A-16", "A-18", "B-23", "Shuttering material shifting"]
    a18 = next(t for t in tops if t["name"] == "A-18")
    assert a18["start"] == (mon + timedelta(days=14)).isoformat()
    a18_rows = [r for r in v["rows"] if r["wbs"].startswith(a18["wbs"] + ".")]
    assert [r["name"] for r in a18_rows] == ["Internal Painting", "Putty", "Primer", "Paint"]
    assert a18_rows[2]["predecessors"] == a18["wbs"] + ".1.1", "links inside the unit come with it"
    assert a18_rows[1]["predecessors"] == "", "the link to a row outside the unit does not"
    assert "Shuttering material shifting" in v["message"]


def test_deleting_a_row_takes_its_sub_items_and_renumbers(tenant):
    mon = _monday()
    j = job(tenant)
    ids, _ = unit_with_painting(tenant, j, mon)
    add(tenant, j, "FFL marking")
    v = ok(tenant.delete(url(j, "/rows/%d" % ids["unit"])))
    assert [r["name"] for r in v["rows"]] == ["FFL marking"] and v["rows"][0]["wbs"] == "1"
    assert v["message"] == "5 rows deleted." and v["links"] == []


def test_the_working_week_and_holidays(tenant):
    mon = _monday()
    j = job(tenant)
    rid, _ = add(tenant, j, "Flooring", start=mon.isoformat(), days=6)
    assert rows(ok(tenant.get(url(j))))["Flooring"]["end"] == (mon + timedelta(days=5)).isoformat()      # Mon..Sat
    v = ok(tenant.put(url(j, "/calendar"), json={"calendar_days": False, "weekly_off": [6, 7]}))
    assert rows(v)["Flooring"]["end"] == (mon + timedelta(days=7)).isoformat()                           # Sat off too
    v = ok(tenant.post(url(j, "/holidays"), json={"date": (mon + timedelta(days=1)).isoformat(), "name": "Site closed"}))
    assert rows(v)["Flooring"]["end"] == (mon + timedelta(days=8)).isoformat()
    hid = v["calendar"]["holidays"][0]["id"]
    v = ok(tenant.delete(url(j, "/holidays/%d" % hid)))
    assert v["calendar"]["holidays"] == []
    v = ok(tenant.post(url(j, "/holidays/public"), json={"year": 2026}))
    assert len(v["calendar"]["holidays"]) >= 10 and "public holiday" in v["message"]
    assert tenant.put(url(j, "/calendar"), json={"weekly_off": [1, 2, 3, 4, 5, 6, 7]}).status_code == 400


def test_undo_puts_the_programme_back_exactly(tenant):
    mon = _monday()
    j = job(tenant)
    ids, before = unit_with_painting(tenant, j, mon)
    snapshot = {"rows": [{"id": r["id"], "parent_id": r["parent_id"], "order": r["order"], "name": r["name"],
                          "typed_start": r["typed"]["start"], "typed_end": r["typed"]["end"], "typed_days": r["typed"]["days"],
                          "uom": r["uom"], "quantity": r["quantity"]} for r in before["rows"]],
                "links": before["links"]}
    ok(edit(tenant, j, ids["putty"], days=9, name="Wall putty"))
    add(tenant, j, "Something added")
    ok(tenant.delete(url(j, "/rows/%d" % ids["paint"])))
    after = ok(tenant.post(url(j, "/restore"), json=snapshot))
    strip = lambda v: [(r["id"], r["wbs"], r["name"], r["start"], r["end"], r["predecessors"]) for r in v["rows"]]
    assert strip(after) == strip(before)


def test_who_may_change_it(tenant, portal, second_tenant):
    from test_contracts_flow import staff_session
    j = job(tenant)
    rid, _ = add(tenant, j, "Brick masonry")
    crew = staff_session(tenant, portal, "staff")
    assert crew.patch(url(j, "/rows"), json={"changes": [{"id": rid, "name": "Mine"}]}).status_code == 403
    assert second_tenant.patch(url(j, "/rows"), json={"changes": [{"id": rid, "name": "Mine"}]}).status_code == 404
    assert second_tenant.post(url(j, "/restore"), json={"rows": [], "links": []}).status_code == 404


def test_the_first_sub_item_takes_over_the_rows_plan(tenant):
    """Broken into steps, a row keeps its dates: its first step starts where it started, for as long, after what it
    waited on; the steps after it are planned on their own."""
    mon = _monday()
    j = job(tenant)
    first, _ = add(tenant, j, "Shuttering", start=mon.isoformat(), days=2)
    works, _ = add(tenant, j, "General works", days=10)
    ok(edit(tenant, j, works, predecessors="1"))
    before = rows(ok(tenant.get(url(j))))["General works"]
    step, v = add(tenant, j, "Putty", works, "child")
    r = rows(v)
    assert r["Putty"]["start"] == before["start"] and r["Putty"]["days"] == 10 and r["Putty"]["predecessors"] == "1"
    assert r["General works"]["summary"] and (r["General works"]["start"], r["General works"]["end"]) == (before["start"], before["end"])
    # a second step is the user's to plan
    _, v = add(tenant, j, "Primer", step, "after")
    assert rows(v)["Primer"]["start"] is None and rows(v)["General works"]["end"] == before["end"]
    # a row with no plan gives its first step nothing
    empty, _ = add(tenant, j, "Snags")
    _, v = add(tenant, j, "Doors", empty, "child")
    assert rows(v)["Doors"]["start"] is None
