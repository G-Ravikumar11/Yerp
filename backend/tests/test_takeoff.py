"""Quantity take-off: exact from a DXF, an estimate from a traced picture, and a DWG sends the person to Save As DXF."""
import io

import ezdxf
import pytest
from fastapi import HTTPException

from app.services import takeoff


def plan(units=4):
    """A 10 m x 8 m room in millimetres: walls drawn as two faces, a floor outline, one door, two windows."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = units
    for name in ("A-WALL", "A-WALL-DIMS", "A-FLOOR", "A-DOOR", "A-WINDOW"):
        doc.layers.add(name)
    doc.blocks.new("D1")
    doc.blocks.new("W1")
    msp = doc.modelspace()
    outer = [(0, 0), (10000, 0), (10000, 8000), (0, 8000)]
    inner = [(230, 230), (9770, 230), (9770, 7770), (230, 7770)]
    msp.add_lwpolyline(outer, close=True, dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline(inner, close=True, dxfattribs={"layer": "A-WALL"})
    msp.add_line((0, 0), (5000, 0), dxfattribs={"layer": "A-WALL-DIMS"})
    msp.add_lwpolyline(inner, close=True, dxfattribs={"layer": "A-FLOOR"})
    msp.add_blockref("D1", (1000, 0), dxfattribs={"layer": "A-DOOR"})
    msp.add_blockref("W1", (3000, 0), dxfattribs={"layer": "A-WINDOW"})
    msp.add_blockref("W1", (6000, 0), dxfattribs={"layer": "A-WINDOW"})
    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode("utf-8")


def layers():
    return {r["name"]: r for r in takeoff.read_dxf(plan())["layers"]}


def test_a_dxf_gives_real_lengths_areas_and_counts_by_layer():
    got = layers()
    assert got["A-WALL"]["length_m"] == pytest.approx(36 + 34.16, abs=0.01)
    assert got["A-FLOOR"]["area_sqm"] == pytest.approx(9.54 * 7.54, abs=0.01)
    assert got["A-DOOR"]["blocks"] == 1 and got["A-WINDOW"]["blocks"] == 2


def test_layers_are_guessed_from_their_names_and_dimensions_are_not_walls():
    got = layers()
    assert got["A-WALL"]["kind"] == "wall" and got["A-FLOOR"]["kind"] == "slab" and got["A-DOOR"]["kind"] == "door"
    assert got["A-WALL-DIMS"]["kind"] == "ignore"


def test_a_wall_drawn_as_two_faces_is_counted_once():
    a = takeoff.clean_assumptions({})
    q = takeoff.cad_quantities(takeoff.read_dxf(plan())["layers"], {}, a)
    assert q["wall_m"] == pytest.approx(35.08, abs=0.01) and q["doors"] == 1 and q["windows"] == 2


def test_a_person_can_correct_a_layer():
    a = takeoff.clean_assumptions({})
    q = takeoff.cad_quantities(takeoff.read_dxf(plan())["layers"], {"A-FLOOR": "ignore"}, a)
    assert q["floor_sqm"] == 0


def test_the_units_in_the_file_are_used():
    metres = takeoff.read_dxf(plan(units=6))
    assert metres["units"] == "metres" and metres["units_stated"]
    assert {r["name"]: r for r in metres["layers"]}["A-WALL"]["length_m"] > 60000
    assert not takeoff.read_dxf(plan(units=0))["units_stated"]


def test_the_materials_follow_from_the_quantities():
    a = takeoff.clean_assumptions({"wastage_percent": 0})
    rows = {(m["group"], m["item"]): m for m in takeoff.materials({"wall_m": 10, "floor_sqm": 100, "doors": 1, "windows": 0}, a)}
    # 10 m x 3 m less a 2.1 sqm door = 27.9 sqm; x 0.23 = 6.417 cum; x 500 bricks.
    assert rows[("Quantities", "Wall area, openings taken off")]["quantity"] == 27.9
    assert rows[("Masonry", "Bricks")]["quantity"] == pytest.approx(3208.5, abs=0.1)
    assert rows[("Slab", "Concrete")]["quantity"] == 15
    assert rows[("Slab", "Cement")]["quantity"] == 112.5


def test_wastage_and_floors_scale_what_is_bought():
    one = {m["item"]: m for m in takeoff.materials({"wall_m": 0, "floor_sqm": 100, "doors": 0, "windows": 0}, takeoff.clean_assumptions({"wastage_percent": 0}))}
    two = {m["item"]: m for m in takeoff.materials({"wall_m": 0, "floor_sqm": 100, "doors": 0, "windows": 0}, takeoff.clean_assumptions({"wastage_percent": 10, "storeys": 2}))}
    assert two["Floor tiles"]["quantity"] == pytest.approx(one["Floor tiles"]["quantity"] * 2.2)


def test_a_traced_plan_is_scaled_by_its_width_and_shape():
    trace = {"walls": [{"x1": 0, "y1": 0, "x2": 100, "y2": 0}, {"x1": 0, "y1": 0, "x2": 0, "y2": 100}],
             "rooms": [{"name": "Hall", "x": 0, "y": 0, "w": 100, "h": 100}], "openings": [{"type": "door", "x": 1, "y": 1}]}
    q = takeoff.plan_quantities(trace, 20.0, 0.5)     # a sheet half as tall as it is wide: a 20 m x 10 m plan
    assert q["wall_m"] == pytest.approx(30) and q["floor_sqm"] == pytest.approx(200) and q["doors"] == 1


def test_a_bad_figure_is_refused():
    with pytest.raises(HTTPException):
        takeoff.clean_assumptions({"wall_height_m": "tall"})


def _drawing(tenant, name, data, media):
    job = tenant.post("/api/jobs", json={"name": "Takeoff site", "customer_name": "Kokapet LLP"}).json()
    jid = job.get("id") or job["job"]["id"]
    d = tenant.post("/api/jobs/%d/drawings" % jid, json={"number": "A-101", "title": "Ground floor", "discipline": "Architectural"})
    assert d.status_code == 200, d.text
    did = (d.json().get("drawing") or d.json())["id"]
    r = tenant.post("/api/drawings/%d/revisions" % did, files={"file": (name, data, media)}, data={"revision": "R0"})
    assert r.status_code == 200, r.text
    return did


def test_the_whole_way_from_an_uploaded_dxf(tenant):
    did = _drawing(tenant, "plan.dxf", plan(), "application/dxf")
    got = tenant.post("/api/drawings/%d/takeoff" % did, json={"assumptions": {"storeys": 2}}).json()
    assert got["exact"] and got["source"] == "cad" and got["quantities"]["doors"] == 1
    assert any(m["item"] == "Bricks" for m in got["materials"])
    fixed = tenant.post("/api/drawings/%d/takeoff" % did, json={"kinds": {"A-FLOOR": "ignore"}}).json()
    assert fixed["quantities"]["floor_sqm"] == 0


def test_a_dwg_says_how_to_get_a_dxf(tenant):
    did = _drawing(tenant, "plan.dwg", b"AC1032" + b"\0" * 64, "application/acad")
    res = tenant.post("/api/drawings/%d/takeoff" % did, json={})
    assert res.status_code == 400 and "Save As" in res.json()["detail"]


def test_another_company_cannot_read_it(tenant, second_tenant):
    did = _drawing(tenant, "plan.dxf", plan(), "application/dxf")
    assert second_tenant.post("/api/drawings/%d/takeoff" % did, json={}).status_code == 404
