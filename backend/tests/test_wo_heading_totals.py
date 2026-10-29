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


def test_a_total_line_naming_a_line_from_another_project_is_refused(tenant):
    _, lines = lines_of(tenant)
    order, pulled = total_order(tenant, lines, [(lines["EXC"], 10)])
    row = dict(pulled["lines"][0], boq_parts=[{"key": "nonsense", "qty": 10}])
    assert tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": [row]}).status_code == 400
