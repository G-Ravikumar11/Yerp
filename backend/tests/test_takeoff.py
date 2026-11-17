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


def test_a_dwg_says_how_to_get_a_dxf_when_no_converter_is_installed(tenant, monkeypatch):
    monkeypatch.setattr(takeoff, "dwg_converter", lambda: None)
    did = _drawing(tenant, "plan.dwg", b"AC1032" + b"\0" * 64, "application/acad")
    res = tenant.post("/api/drawings/%d/takeoff" % did, json={})
    assert res.status_code == 400 and "Save As" in res.json()["detail"]


def test_a_dwg_is_turned_into_a_dxf_when_a_converter_is_installed(tenant, monkeypatch):
    """LibreDWG's dwg2dxf, stood in for: it is given the DWG's path and writes the DXF where -o says."""
    calls = []

    def dwg2dxf(cmd, **kw):
        calls.append(cmd)
        assert kw.get("timeout") and "shell" not in kw
        with open(cmd[cmd.index("-o") + 1], "wb") as fh:
            fh.write(plan())
    monkeypatch.setattr(takeoff, "dwg_converter", lambda: ("libredwg", "/usr/bin/dwg2dxf"))
    monkeypatch.setattr(takeoff.subprocess, "run", dwg2dxf)
    did = _drawing(tenant, "plan.dwg", b"AC1032" + b"\0" * 64, "application/acad")
    got = tenant.post("/api/drawings/%d/takeoff" % did, json={}).json()
    assert got["exact"] and got["converted_from"] == "DWG" and got["quantities"]["doors"] == 1
    tenant.post("/api/drawings/%d/takeoff" % did, json={"assumptions": {"storeys": 2}})
    assert len(calls) == 1, "converted once, then kept"


def test_a_converter_that_writes_nothing_is_reported(tenant, monkeypatch):
    monkeypatch.setattr(takeoff, "dwg_converter", lambda: ("libredwg", "/usr/bin/dwg2dxf"))
    monkeypatch.setattr(takeoff.subprocess, "run", lambda cmd, **kw: None)
    did = _drawing(tenant, "broken.dwg", b"not a dwg", "application/acad")
    res = tenant.post("/api/drawings/%d/takeoff" % did, json={})
    assert res.status_code == 400 and "could not be turned into a DXF" in res.json()["detail"]


# --- sending the quantities on ---------------------------------------------------------------------------------------

def _drawing_on_job(tenant):
    job = tenant.post("/api/jobs", json={"name": "Takeoff tower", "customer_name": "Kokapet LLP"}).json()
    jid = job.get("id") or job["job"]["id"]
    d = tenant.post("/api/jobs/%d/drawings" % jid, json={"number": "A-201", "title": "First floor", "discipline": "Architectural"})
    did = (d.json().get("drawing") or d.json())["id"]
    assert tenant.post("/api/drawings/%d/revisions" % did, files={"file": ("plan.dxf", plan(), "application/dxf")},
                       data={"revision": "R1"}).status_code == 200
    return jid, did


SENT = [{"description": "Masonry", "uom": "cum", "quantity": 16.1}, {"description": "Plaster area", "uom": "sqm", "quantity": 140},
        {"description": "Nothing", "uom": "nos", "quantity": 0}]


def test_quantities_go_to_the_end_of_the_projects_boq_once(tenant):
    jid, did = _drawing_on_job(tenant)
    none = tenant.post("/api/drawings/%d/takeoff/boq" % did, json={"lines": SENT})
    assert none.status_code == 409 and "no BOQ" in none.json()["detail"]
    boq = tenant.post("/api/boqs", json={"job_id": jid}).json()["boq"]
    tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": [{"kind": "item", "description": "Excavation", "uom": "cum", "quantity": 50, "rate": 300}]})
    res = tenant.post("/api/drawings/%d/takeoff/boq" % did, json={"lines": SENT})
    assert res.status_code == 200, res.text
    lines = tenant.get("/api/boqs/%d" % boq["id"]).json()["lines"]
    got = [(l["kind"], l["description"], l.get("quantity"), l.get("rate")) for l in lines if l["kind"] in ("section", "item")]
    assert got[0][1] == "Excavation", "what was there stays, first"
    assert ("section", "Take-off from drawing A-201 rev R1") == got[1][:2]
    assert [(g[1], g[2], g[3]) for g in got[2:]] == [("Masonry", 16.1, 0), ("Plaster area", 140, 0)]
    again = tenant.post("/api/drawings/%d/takeoff/boq" % did, json={"lines": SENT})
    assert again.status_code == 409 and "already" in again.json()["detail"]


def test_materials_go_to_a_new_enquiry_with_the_same_material_asked_for_once(tenant):
    jid, did = _drawing_on_job(tenant)
    res = tenant.post("/api/drawings/%d/takeoff/enquiry" % did, json={"lines": [
        {"description": "Cement", "uom": "bags", "quantity": 60.5}, {"description": "Sand", "uom": "cum", "quantity": 4},
        {"description": "cement", "uom": "Bags", "quantity": 39.5}]})
    assert res.status_code == 200, res.text
    r = tenant.get("/api/rfqs/%d" % res.json()["rfq"]["id"]).json()
    assert r["rfq"]["job_id"] == jid and "A-201 rev R1" in r["rfq"]["title"]
    assert sorted((l["description"], l["qty"]) for l in r["lines"]) == [("Cement", 100), ("Sand", 4)]
    assert tenant.post("/api/drawings/%d/takeoff/enquiry" % did, json={"lines": [{"description": "x", "quantity": 0}]}).status_code == 400


def test_another_company_cannot_send_its_quantities(tenant, second_tenant):
    _, did = _drawing_on_job(tenant)
    assert second_tenant.post("/api/drawings/%d/takeoff/enquiry" % did, json={"lines": SENT}).status_code == 404


def test_another_company_cannot_read_it(tenant, second_tenant):
    did = _drawing(tenant, "plan.dxf", plan(), "application/dxf")
    assert second_tenant.post("/api/drawings/%d/takeoff" % did, json={}).status_code == 404
