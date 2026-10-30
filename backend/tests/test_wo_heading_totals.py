"""A heading of the BOQ taken into a work order as one line: its quantities added up, each BOQ line still counted."""
from test_boq import contractor_order, job_of_key, make_boq, saved
from test_subcontract_orders import draft


def lines_of(tenant):
    _, boq = make_boq(tenant)
    return boq, {l["group_code"]: l for l in saved(tenant, boq)["lines"]}


def total_order(tenant, lines, picks, rate=100):
    """A draft order with one line standing for the BOQ lines picked: [(boq line, quantity)]."""
    order = draft(tenant, job_id=job_of_key(picks[0][0]["key"]))
    pulled = tenant.post("/api/wo/orders/%d/boq-lines" % order["id"], json={"groups": [
        {"description": "Concrete works", "group_code": "A", "rate": rate,
         "parts": [{"key": l["key"], "quantity": q} for l, q in picks]}]}).json()
    return order, pulled


def test_a_heading_comes_back_as_one_line_with_the_quantities_added(tenant):
    _, lines = lines_of(tenant)
    order, pulled = total_order(tenant, lines, [(lines["EXC"], 100), (lines["EXC"], 50)])
    one = pulled["lines"]
    assert len(one) == 1 and one[0]["quantity"] == 150 and one[0]["unit_rate"] == 100
    assert one[0]["item_description"] == "Concrete works" and one[0]["boq_key"] == "" and len(one[0]["boq_parts"]) == 2


def test_each_boq_line_still_shows_what_was_given(tenant):
    boq, lines = lines_of(tenant)
    order, pulled = total_order(tenant, lines, [(lines["EXC"], 300), (lines["RCC"], 120)])
    res = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": pulled["lines"]})
    assert res.status_code == 200, res.text
    rows = {r["group_code"]: r for r in tenant.get("/api/boqs/%d/tracker" % boq["id"]).json()["rows"] if r["kind"] != "section"}
    assert rows["EXC"]["given"] == 300 and rows["RCC"]["given"] == 120 and rows["EXC"]["left_to_give"] == 200
    assert "not on the project BOQ" not in res.json()["message"], "a total line is not a loose line"
    assert res.json()["order"]["items"][0]["boq_parts"]


def test_changing_the_total_in_the_schedule_shares_the_change_out(tenant):
    boq, lines = lines_of(tenant)
    order, pulled = total_order(tenant, lines, [(lines["EXC"], 300), (lines["RCC"], 100)])
    row = dict(pulled["lines"][0], quantity=200)          # 400 -> 200: half of each
    tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": [row]})
    rows = {r["group_code"]: r for r in tenant.get("/api/boqs/%d/tracker" % boq["id"]).json()["rows"] if r["kind"] != "section"}
    assert rows["EXC"]["given"] == 150 and rows["RCC"]["given"] == 50


def test_lines_in_different_units_are_never_added_together(tenant):
    _, lines = lines_of(tenant)
    other = next(l for l in lines.values() if l["uom"] != lines["EXC"]["uom"] and l.get("kind") != "section")
    _, pulled = total_order(tenant, lines, [(lines["EXC"], 10), (other, 20)])
    assert sorted(l["uom"] for l in pulled["lines"]) == sorted([lines["EXC"]["uom"], other["uom"]])
    assert sorted(l["quantity"] for l in pulled["lines"]) == [10, 20]


def test_a_part_no_longer_on_the_boq_is_let_go_with_a_warning_not_a_refusal(tenant):
    boq, lines = lines_of(tenant)
    order, pulled = total_order(tenant, lines, [(lines["EXC"], 10), (lines["RCC"], 10)])
    row = dict(pulled["lines"][0], boq_parts=pulled["lines"][0]["boq_parts"] + [{"key": "gone-in-a-revision", "qty": 5}])
    res = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": [row]})
    assert res.status_code == 200, res.text
    assert any("no longer on the project BOQ" in w for w in res.json()["warnings"])
    assert {p["key"] for p in res.json()["order"]["items"][0]["boq_parts"]} == {lines["EXC"]["key"], lines["RCC"]["key"]}


def test_clearing_the_quantity_keeps_the_boq_lines_it_adds_up(tenant):
    boq, lines = lines_of(tenant)
    order, pulled = total_order(tenant, lines, [(lines["EXC"], 300), (lines["RCC"], 100)])
    url = "/api/wo/orders/%d/boq" % order["id"]
    cleared = tenant.put(url, json={"lines": [dict(pulled["lines"][0], quantity=0)]}).json()["order"]["items"][0]
    assert len(cleared["boq_parts"]) == 2
    back = tenant.put(url, json={"lines": [dict(cleared, quantity=400)]}).json()["order"]["items"][0]
    assert sorted(p["qty"] for p in back["boq_parts"]) == [100, 300]
    rows = {r["group_code"]: r for r in tenant.get("/api/boqs/%d/tracker" % boq["id"]).json()["rows"] if r["kind"] != "section"}
    assert rows["EXC"]["given"] == 300 and rows["RCC"]["given"] == 100


def test_the_approver_is_told_when_a_heading_total_is_at_a_loss(tenant):
    from app.services.subcontract_rules import boq_breaches
    import main
    _, lines = lines_of(tenant)
    # well above the client's rate on both lines
    order, pulled = total_order(tenant, lines, [(lines["EXC"], 100), (lines["RCC"], 10)], rate=99999)
    tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": pulled["lines"]})
    with main.SessionLocal() as db:
        found = boq_breaches(db, db.get(main.models.DBSubcontractOrder, order["id"]))
    assert len([f for f in found if "loss on every unit" in f]) == 2
