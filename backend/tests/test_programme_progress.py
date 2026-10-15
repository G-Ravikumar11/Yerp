"""Progress on the programme: recorded per leaf as a quantity done (or a %), rolled up by amount, and read the same by
the programme, the cards, the day plan and the activity page; planned % measured against a saved baseline."""
from datetime import date, timedelta

from app.services.programme_engine import Calendar, Row, leaf_weights, project_percent, schedule
from test_programme_edit import add, edit, ok, rows, url
from test_schedule import job, put_act


def _monday(weeks=-1):
    t = date.today() + timedelta(weeks=weeks)
    return t - timedelta(days=t.weekday())


def block(tenant, j, start):
    """A-16 > Flooring (500 sqm at 100 = 50,000) then Skirting (100 rmt at 100 = 10,000), skirting after flooring."""
    unit, _ = add(tenant, j, "A-16")
    floor, _ = add(tenant, j, "Flooring", unit, "child", start=start.isoformat(), days=5, uom="sqm", quantity=500, rate=100, amount=50000)
    skirt, v = add(tenant, j, "Skirting", floor, "after", days=3, uom="rmt", quantity=100, rate=100, amount=10000)
    v = ok(edit(tenant, j, skirt, predecessors="1.1"))
    return {"unit": unit, "floor": floor, "skirt": skirt}, v


def progress(tenant, aid, **body):
    res = tenant.post("/api/schedule/activities/%d/progress" % aid, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_quantity_done_so_far_is_the_percent_and_the_heading_rolls_up_by_amount(tenant):
    j = job(tenant)
    ids, _ = block(tenant, j, _monday())
    progress(tenant, ids["floor"], qty_done=320)                     # 320 of 500 sqm
    v = ok(tenant.get(url(j)))
    r = rows(v)
    assert r["Flooring"]["percent"] == 64 and r["Flooring"]["qty_done"] == 320
    assert round(r["A-16"]["percent"], 2) == round(64 * 50000 / 60000, 2), "weighted by what each is worth"
    assert round(v["percent"], 2) == round(r["A-16"]["percent"], 2)
    # a later report is the total so far, not today's share
    progress(tenant, ids["floor"], qty_done=500)
    assert rows(ok(tenant.get(url(j))))["Flooring"]["percent"] == 100
    # a percentage still works, and stands for its quantity
    progress(tenant, ids["skirt"], percent=50)
    assert rows(ok(tenant.get(url(j))))["Skirting"]["qty_done"] == 50


def test_the_cards_the_day_plan_and_the_activity_page_read_the_programme(tenant):
    mon = _monday()
    j = job(tenant)
    ids, v = block(tenant, j, mon)
    progress(tenant, ids["floor"], qty_done=250)
    v = ok(tenant.get(url(j)))
    s = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()
    acts = {a["name"]: a for a in s["activities"]}
    assert set(acts) == {"Flooring", "Skirting"}, "headings add up their rows; they are not work of their own"
    sk = acts["Skirting"]
    assert sk["planned_start"] == rows(v)["Skirting"]["start"], "dates are the programme's, not what was typed"
    assert sk["wbs"] == "1.2" and sk["path"] == "A-16" and sk["uom"] == "rmt" and sk["quantity"] == 100
    assert abs(s["summary"]["actual_percent"] - round(v["percent"], 1)) < 0.11
    assert abs(s["summary"]["planned_percent"] - round(v["planned_percent"], 1)) < 0.11
    assert acts["Flooring"]["share_percent"] == round(50000 / 60000 * 100, 1)

    day = tenant.get("/api/jobs/%d/schedule/day" % j["id"]).json()
    every = day["today"] + day["overdue"] + day["soon"] + day["others"]
    assert sorted(r["name"] for r in every) == ["Flooring", "Skirting"]
    f = next(r for r in every if r["name"] == "Flooring")
    assert f["path"] == "A-16" and f["wbs"] == "1.1" and f["quantity"] == 500 and f["qty_done"] == 250
    assert abs(day["summary"]["done_percent"] - s["summary"]["actual_percent"]) < 0.11

    page = tenant.get("/api/schedule/activities/%d" % ids["skirt"]).json()["activity"]
    assert page["planned_start"] == sk["planned_start"] and page["path"] == "A-16"


def test_planned_percent_is_measured_against_the_saved_baseline(tenant):
    mon = _monday(weeks=-1)
    j = job(tenant)
    ids, _ = block(tenant, j, mon)
    before = ok(tenant.get(url(j)))
    saved = ok(tenant.post(url(j, "/baseline"), json={"label": "As agreed"}))
    assert saved["baseline"]["label"] == "As agreed" and "As agreed" in saved["message"]
    assert all(r["baseline"]["slip_days"] == 0 for r in saved["rows"] if r["start"])
    # the flooring takes three days longer: skirting moves, the baseline does not
    v = ok(edit(tenant, j, ids["floor"], days=8))
    r = rows(v)
    assert r["Skirting"]["baseline"]["start"] == rows(before)["Skirting"]["start"]
    assert r["Skirting"]["baseline"]["slip_days"] > 0 and r["A-16"]["baseline"]["slip_days"] > 0
    assert v["planned_percent"] == before["planned_percent"], "planned % follows the baseline, not today's dates"
    # a second baseline is used from then on; the first stays on record
    v = ok(tenant.post(url(j, "/baseline"), json={}))
    assert v["baseline"]["label"] == "Baseline 2" and rows(v)["Skirting"]["baseline"]["slip_days"] == 0


def test_a_baseline_needs_dates(tenant):
    j = job(tenant)
    add(tenant, j, "Not scheduled yet")
    res = tenant.post(url(j, "/baseline"), json={})
    assert res.status_code == 409 and "no" in res.json()["detail"].lower()


def test_a_typed_start_holds_a_linked_row_back_and_a_first_predecessor_takes_over_from_it(tenant):
    mon = _monday(weeks=2)
    j = job(tenant)
    a, _ = add(tenant, j, "Tiling", start=mon.isoformat(), days=2)
    b, _ = add(tenant, j, "Grouting", start=(mon + timedelta(days=7)).isoformat(), end=(mon + timedelta(days=8)).isoformat())
    # the first predecessor: it now follows Tiling and keeps its two days
    r = rows(ok(edit(tenant, j, b, predecessors="1")))["Grouting"]
    assert r["start"] == (mon + timedelta(days=2)).isoformat() and r["days"] == 2 and r["typed"]["start"] == ""
    # a Start typed afterwards holds it back: not earlier than
    r = rows(ok(edit(tenant, j, b, start=(mon + timedelta(days=9)).isoformat())))["Grouting"]
    assert r["start"] == (mon + timedelta(days=9)).isoformat() and r["predecessors"] == "1"


def test_the_old_activity_form_types_both_dates(tenant):
    """Saved from the old form, the two dates are its length again, not a Days kept from the grid."""
    mon = _monday(weeks=2)
    j = job(tenant)
    a, _ = add(tenant, j, "Plaster", start=mon.isoformat(), days=10)
    s = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["activities"][0]
    res = put_act(tenant, s, planned_start=mon.isoformat(), planned_finish=(mon + timedelta(days=2)).isoformat())
    assert res.status_code == 200, res.text
    assert rows(ok(tenant.get(url(j))))["Plaster"]["end"] == (mon + timedelta(days=2)).isoformat()


def test_leaf_weights_give_the_same_figure_as_rolling_up_a_level_at_a_time():
    cal = Calendar()
    mon = date(2026, 11, 2)
    tree = [Row(id=1, name="Block"), Row(id=2, parent_id=1, name="A-16"), Row(id=3, parent_id=1, name="A-18", order=2),
            Row(id=4, parent_id=2, name="Floor", start=mon, days=5, quantity=10, rate=50, qty_done=4),
            Row(id=5, parent_id=2, name="Skirt", start=mon, days=3, quantity=10, rate=10, qty_done=10, order=2),
            Row(id=6, parent_id=3, name="Paint", start=mon, days=4, percent=30),       # no amount: A-18 goes by days
            Row(id=7, parent_id=3, name="Polish", start=mon, days=6, percent=80, order=2),
            Row(id=8, name="Handover", start=mon + timedelta(days=14), days=1, percent=0, order=2)]
    prog = schedule(tree, [], cal)
    w = leaf_weights(prog)
    assert abs(sum(w.values()) - 1) < 1e-9 and set(w) == {4, 5, 6, 7, 8}
    assert abs(sum(w[i] * prog.rows[i].percent for i in w) - project_percent(prog)) < 1e-9
