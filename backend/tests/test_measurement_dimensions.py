"""The measurement book as a book of dimensions.

Until now an entry was a total and a page reference - which meant the real
book, the one with No x L x B x D on it, lived on paper or in a spreadsheet
and the app only ever saw its answer. Now the dimensions are the entry, the
total is what they come to, and the app is the book.
"""
from test_measurement_and_ra_bills import placed_order, book, measure
from test_subcontractor_bills import live_order, book as sub_book


def entry(tenant, wo_id, line_id, dims, **extra):
    body = {"line_id": line_id, "dimensions": dims}
    body.update(extra)
    return tenant.post("/api/mb/%d/entries" % wo_id, json=body)


def first_line(tenant, wo_id):
    return book(tenant, wo_id)["lines"][0]["line_id"]


# --- The arithmetic --------------------------------------------------------------

def test_no_by_l_by_b_by_d(tenant):
    """Twelve footings, 4.5 x 0.3 x 0.3: what the engineer writes."""
    wo = placed_order(tenant)
    res = entry(tenant, wo["id"], first_line(tenant, wo["id"]),
                [{"particulars": "Footings F1", "nos": 12, "length": 4.5,
                  "breadth": 0.3, "depth": 0.3}])
    assert res.status_code == 200, res.text
    assert res.json()["measured_to_date"] == 4.86


def test_a_blank_dimension_does_not_apply(tenant):
    """An area has no depth; a count has no length. Blank is not zero."""
    wo = placed_order(tenant)
    line = first_line(tenant, wo["id"])
    entry(tenant, wo["id"], line, [{"nos": 2, "length": 10, "breadth": 3}])      # area
    entry(tenant, wo["id"], line, [{"nos": 5}])                                   # count
    entry(tenant, wo["id"], line, [{"length": 7.25}])                             # a run
    assert book(tenant, wo["id"])["lines"][0]["measured_to_date"] == 60 + 5 + 7.25


def test_lines_add_and_deductions_take_away(tenant):
    """A wall less its door: the way every plastering measurement is written."""
    wo = placed_order(tenant)
    res = entry(tenant, wo["id"], first_line(tenant, wo["id"]), [
        {"particulars": "Wall, grid 3", "nos": 1, "length": 6, "breadth": 3},
        {"particulars": "Deduct door D1", "nos": 1, "length": 1.2, "breadth": 2.1,
         "deduct": True},
    ])
    assert res.status_code == 200, res.text
    assert res.json()["measured_to_date"] == round(18 - 2.52, 2)


def test_the_total_is_the_dimensions_not_the_typed_figure(tenant):
    """If both are sent, the dimensions win: they are what was checked."""
    wo = placed_order(tenant)
    res = entry(tenant, wo["id"], first_line(tenant, wo["id"]),
                [{"nos": 2, "length": 5}], quantity=999)
    assert res.json()["measured_to_date"] == 10


def test_a_bare_total_is_still_a_measurement(tenant):
    """A count of manholes has no dimensions to write."""
    wo = placed_order(tenant)
    res = measure(tenant, wo["id"], first_line(tenant, wo["id"]), 40)
    assert res.status_code == 200 and res.json()["measured_to_date"] == 40


def test_the_book_gives_the_dimensions_back(tenant):
    wo = placed_order(tenant)
    entry(tenant, wo["id"], first_line(tenant, wo["id"]), [
        {"particulars": "Beam B2", "nos": 3, "length": 4, "breadth": 0.23, "depth": 0.45},
        {"particulars": "Deduct column", "nos": 3, "length": 0.23, "breadth": 0.23,
         "depth": 0.45, "deduct": True},
    ])
    e = book(tenant, wo["id"])["entries"][0]
    assert len(e["dimensions"]) == 2
    assert e["dimensions"][0]["particulars"] == "Beam B2"
    assert e["dimensions"][0]["quantity"] == 1.242
    assert e["dimensions"][1]["deduct"] is True
    assert e["dimensions"][1]["quantity"] < 0
    assert e["quantity"] == round(1.242 - 0.071, 2)


# --- What is refused -------------------------------------------------------------

def test_a_line_with_no_figures_is_refused(tenant):
    wo = placed_order(tenant)
    res = entry(tenant, wo["id"], first_line(tenant, wo["id"]),
                [{"particulars": "forgot to fill it in"}])
    assert res.status_code == 400
    assert "no figures" in res.json()["detail"]


def test_a_zero_that_was_typed_is_refused(tenant):
    """A blank does not apply; a typed nought measures nothing."""
    wo = placed_order(tenant)
    res = entry(tenant, wo["id"], first_line(tenant, wo["id"]),
                [{"nos": 4, "length": 0, "breadth": 2}])
    assert res.status_code == 400
    assert "comes to nothing" in res.json()["detail"]


def test_a_negative_dimension_is_a_deduction_written_wrongly(tenant):
    wo = placed_order(tenant)
    res = entry(tenant, wo["id"], first_line(tenant, wo["id"]),
                [{"nos": 1, "length": -6, "breadth": 3}])
    assert res.status_code == 400
    assert "deduction" in res.json()["detail"]


def test_deductions_alone_are_a_negative_entry(tenant):
    """A correction can be written as dimensions too."""
    wo = placed_order(tenant)
    line = first_line(tenant, wo["id"])
    entry(tenant, wo["id"], line, [{"nos": 1, "length": 10, "breadth": 10}])
    res = entry(tenant, wo["id"], line, [{"particulars": "measured twice", "nos": 1,
                                          "length": 2, "breadth": 2, "deduct": True}])
    assert res.status_code == 200
    assert book(tenant, wo["id"])["lines"][0]["measured_to_date"] == 96


def test_removing_an_entry_removes_its_dimensions(tenant):
    wo = placed_order(tenant)
    entry(tenant, wo["id"], first_line(tenant, wo["id"]), [{"nos": 2, "length": 3}])
    e = book(tenant, wo["id"])["entries"][0]
    assert tenant.delete("/api/mb/entries/%d" % e["id"]).status_code == 200
    assert book(tenant, wo["id"])["entries"] == []
    import main
    from database import SessionLocal
    db = SessionLocal()
    try:
        assert db.query(main.models.DBMeasurementDimension).filter(
            main.models.DBMeasurementDimension.measurement_id == e["id"]).count() == 0
    finally:
        db.close()


# --- The gang's book, the same way ---------------------------------------------

def test_the_subcontractors_book_takes_dimensions_too(tenant):
    order = live_order(tenant)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]          # 250 cum ordered
    res = tenant.post("/api/sub-mb/%d/entries" % order["id"], json={
        "item_id": item, "dimensions": [
            {"particulars": "Raft, zone A", "nos": 1, "length": 20, "breadth": 10, "depth": 0.6},
            {"particulars": "Deduct lift pit", "nos": 1, "length": 2, "breadth": 2,
             "depth": 0.6, "deduct": True},
        ]})
    assert res.status_code == 200, res.text
    assert res.json()["measured_to_date"] == round(120 - 2.4, 2)
    e = sub_book(tenant, order["id"])["entries"][0]
    assert len(e["dimensions"]) == 2 and e["dimensions"][1]["deduct"] is True


def test_the_ceiling_is_checked_on_what_the_dimensions_come_to(tenant):
    order = live_order(tenant)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]          # 250 cum, no tolerance
    res = tenant.post("/api/sub-mb/%d/entries" % order["id"], json={
        "item_id": item, "dimensions": [{"nos": 1, "length": 30, "breadth": 10, "depth": 1}]})
    assert res.status_code == 409
    assert "300" in res.json()["detail"]


def test_another_tenant_cannot_read_the_dimensions(tenant, second_tenant):
    wo = placed_order(tenant)
    entry(tenant, wo["id"], first_line(tenant, wo["id"]), [{"nos": 2, "length": 3}])
    assert second_tenant.get("/api/mb/%d" % wo["id"]).status_code == 404
