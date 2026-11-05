"""Quantity take-off from a drawing: how much wall, floor, doors and windows the sheet shows, and the material that takes.

Two sources, kept apart because they are not worth the same:

  a DXF (AutoCAD)   exact. Every line has a real length and every closed outline a real area, in the drawing's own units,
                    gathered by layer. A person says what each layer is; the name usually gives it away.
  a picture or PDF  an estimate. The 3D trace (app/ai/drawing_3d.py) gives walls and rooms as positions on the sheet, and
                    the real width of the plan turns them into metres. Good for an early idea, never for ordering.

A DWG cannot be read here: the format is closed and needs Autodesk's or the Open Design Alliance's own library. AutoCAD
saves the same drawing as DXF in one step, with nothing lost.

Materials are the quantities times rules of thumb, each of them on the form to change. Columns, beams and footings are
left out: their sizes are in the structural schedules, not on a plan.
"""
import io
import math
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

KINDS = ("wall", "slab", "door", "window", "ignore")
# What a layer's name says it holds, first match wins. Annotation comes first: A-WALL-DIMS is dimensions, not walls.
LAYER_WORDS = (
    ("ignore", ("dim", "text", "note", "grid", "hatch", "title", "defpoint", "furn", "draw", "sheet", "tree", "plant", "axis", "centre", "center")),
    ("door", ("door", "dr-", "-dr")),
    ("window", ("window", "win", "glaz", "ventilator")),
    ("slab", ("slab", "floor", "room", "area", "flr")),
    ("wall", ("wall", "brick", "masonry", "partition", "blk", "block")),
)
# $INSUNITS to metres. 0 means the file did not say; drawings in this trade are in millimetres.
UNIT_TO_M = {0: 0.001, 1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
UNIT_NAME = {0: "millimetres (not stated in the file)", 1: "inches", 2: "feet", 4: "millimetres", 5: "centimetres", 6: "metres"}

DEFAULTS: Dict[str, float] = {
    "storeys": 1, "wall_height_m": 3.0, "wall_thickness_m": 0.23, "double_line_walls": 1,
    "door_area_sqm": 2.1, "window_area_sqm": 1.8,
    "bricks_per_cum": 500, "mortar_share": 0.25, "cement_bags_per_cum_mortar": 6.0, "sand_cum_per_cum_mortar": 1.05,
    "plaster_mm": 12, "paint_sqm_per_litre": 12, "paint_coats": 2,
    "slab_thickness_m": 0.15, "concrete_bags_per_cum": 7.5, "concrete_sand_cum": 0.42, "concrete_aggregate_cum": 0.84,
    "steel_kg_per_cum": 90, "wastage_percent": 5,
}


def layer_kind(name: str) -> str:
    low = (name or "").lower()
    for kind, words in LAYER_WORDS:
        if any(w in low for w in words):
            return kind
    return "ignore"


def _polygon_area(points) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _path_length(points, closed) -> float:
    pts = points + points[:1] if closed else points
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def read_dxf(data: bytes) -> Dict[str, Any]:
    """Every layer of the model space: length of its lines, area of its closed outlines, and how many of each block."""
    import ezdxf
    from ezdxf import recover
    try:
        doc, _ = recover.read(io.BytesIO(data))
    except (IOError, ezdxf.DXFStructureError):
        raise HTTPException(400, "This DXF could not be read. Open it in AutoCAD and save it again as DXF.")
    units = int(doc.header.get("$INSUNITS", 0) or 0)
    to_m = UNIT_TO_M.get(units, 0.001)
    layers: Dict[str, Dict[str, Any]] = {}

    def layer(name):
        return layers.setdefault(name, {"name": name, "length_m": 0.0, "area_sqm": 0.0, "blocks": 0, "block_names": {}, "kind": layer_kind(name)})

    for e in doc.modelspace():
        kind, row = e.dxftype(), layer(e.dxf.layer)
        if kind == "LINE":
            s, t = e.dxf.start, e.dxf.end
            row["length_m"] += math.hypot(t[0] - s[0], t[1] - s[1]) * to_m
        elif kind == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            row["length_m"] += _path_length(pts, e.closed) * to_m
            if e.closed and len(pts) >= 3:
                row["area_sqm"] += _polygon_area(pts) * to_m * to_m
        elif kind == "POLYLINE":
            pts = [(v.dxf.location[0], v.dxf.location[1]) for v in e.vertices]
            row["length_m"] += _path_length(pts, e.is_closed) * to_m
            if e.is_closed and len(pts) >= 3:
                row["area_sqm"] += _polygon_area(pts) * to_m * to_m
        elif kind == "ARC":
            sweep = (e.dxf.end_angle - e.dxf.start_angle) % 360
            row["length_m"] += math.radians(sweep) * e.dxf.radius * to_m
        elif kind == "CIRCLE":
            row["length_m"] += 2 * math.pi * e.dxf.radius * to_m
        elif kind == "INSERT":
            row["blocks"] += 1
            row["block_names"][e.dxf.name] = row["block_names"].get(e.dxf.name, 0) + 1
    out = []
    for row in layers.values():
        if not (row["length_m"] or row["area_sqm"] or row["blocks"]):
            continue
        out.append({**row, "length_m": round(row["length_m"], 2), "area_sqm": round(row["area_sqm"], 2)})
    if not out:
        raise HTTPException(400, "This DXF has nothing drawn in its model space. A plan kept only in a paper-space layout has to be drawn in model space.")
    return {"source": "cad", "exact": True, "units": UNIT_NAME.get(units, "unit %d" % units), "units_stated": units != 0,
            "layers": sorted(out, key=lambda r: r["name"].lower())}


def cad_quantities(layers: List[dict], kinds: Dict[str, str], a: Dict[str, float]) -> Dict[str, float]:
    """The layers, as the person has named them, added up. A wall drawn as two faces has twice its real length."""
    q = {"wall_m": 0.0, "floor_sqm": 0.0, "doors": 0, "windows": 0}
    for row in layers:
        kind = kinds.get(row["name"]) or row["kind"]
        if kind == "wall":
            q["wall_m"] += row["length_m"] / (2.0 if a["double_line_walls"] else 1.0)
        elif kind == "slab":
            q["floor_sqm"] += row["area_sqm"]
        elif kind == "door":
            q["doors"] += row["blocks"]
        elif kind == "window":
            q["windows"] += row["blocks"]
    return q


def plan_quantities(trace: dict, width_m: float, aspect: float) -> Dict[str, float]:
    """The traced plan in metres. Positions are percentages of the sheet: across by its width, down by its height."""
    per_x = width_m / 100.0
    per_y = (width_m * aspect) / 100.0
    wall = sum(math.hypot((w["x2"] - w["x1"]) * per_x, (w["y2"] - w["y1"]) * per_y) for w in trace.get("walls") or [])
    floor = sum(r["w"] * per_x * r["h"] * per_y for r in trace.get("rooms") or [])
    gaps = trace.get("openings") or []
    return {"wall_m": wall, "floor_sqm": floor, "doors": len([o for o in gaps if o["type"] == "door"]),
            "windows": len([o for o in gaps if o["type"] == "window"])}


def clean_assumptions(given: Optional[dict]) -> Dict[str, float]:
    out = dict(DEFAULTS)
    for key, val in (given or {}).items():
        if key not in DEFAULTS:
            continue
        try:
            n = float(val)
        except (TypeError, ValueError):
            raise HTTPException(400, "%s has to be a number." % key.replace("_", " "))
        if not math.isfinite(n) or n < 0 or n > 100000:
            raise HTTPException(400, "%s is out of range." % key.replace("_", " "))
        out[key] = n
    out["storeys"] = max(1.0, out["storeys"])
    return out


def materials(q: Dict[str, float], a: Dict[str, float]) -> List[dict]:
    """What the quantities take, wastage included, each line with the sum behind it."""
    storeys, extra = a["storeys"], 1 + a["wastage_percent"] / 100.0
    wall_face = q["wall_m"] * a["wall_height_m"] * storeys
    gaps = (q["doors"] * a["door_area_sqm"] + q["windows"] * a["window_area_sqm"]) * storeys
    wall_area = max(0.0, wall_face - gaps)
    masonry = wall_area * a["wall_thickness_m"]
    mortar = masonry * a["mortar_share"]
    plaster_area = wall_area * 2
    plaster = plaster_area * a["plaster_mm"] / 1000.0
    floor = q["floor_sqm"] * storeys
    concrete = floor * a["slab_thickness_m"]

    def line(group, item, qty, uom, how, waste=True):
        return {"group": group, "item": item, "quantity": round(qty * (extra if waste else 1), 2), "uom": uom, "how": how}
    out = []
    if q["wall_m"]:
        out += [
            line("Quantities", "Wall length", q["wall_m"], "m", "Per floor, from the drawing", False),
            line("Quantities", "Wall area, openings taken off", wall_area, "sqm", "Length x height x floors, less doors and windows", False),
            line("Quantities", "Masonry", masonry, "cum", "Wall area x thickness", False),
            line("Masonry", "Bricks", masonry * a["bricks_per_cum"], "nos", "%g a cum" % a["bricks_per_cum"]),
            line("Masonry", "Cement", mortar * a["cement_bags_per_cum_mortar"], "bags", "Mortar is %g of the masonry" % a["mortar_share"]),
            line("Masonry", "Sand", mortar * a["sand_cum_per_cum_mortar"], "cum", "Mortar is %g of the masonry" % a["mortar_share"]),
            line("Plaster", "Plaster area", plaster_area, "sqm", "Both faces of the wall", False),
            line("Plaster", "Cement", plaster * a["cement_bags_per_cum_mortar"], "bags", "%g mm thick" % a["plaster_mm"]),
            line("Plaster", "Sand", plaster * a["sand_cum_per_cum_mortar"], "cum", "%g mm thick" % a["plaster_mm"]),
            line("Paint", "Paint", plaster_area * a["paint_coats"] / max(a["paint_sqm_per_litre"], 0.1), "litres", "%g coats, %g sqm a litre" % (a["paint_coats"], a["paint_sqm_per_litre"])),
        ]
    if q["floor_sqm"]:
        out += [
            line("Quantities", "Floor area", floor, "sqm", "From the drawing x floors", False),
            line("Slab", "Concrete", concrete, "cum", "Floor area x %g m" % a["slab_thickness_m"], False),
            line("Slab", "Cement", concrete * a["concrete_bags_per_cum"], "bags", "%g a cum" % a["concrete_bags_per_cum"]),
            line("Slab", "Sand", concrete * a["concrete_sand_cum"], "cum", "%g a cum" % a["concrete_sand_cum"]),
            line("Slab", "Aggregate", concrete * a["concrete_aggregate_cum"], "cum", "%g a cum" % a["concrete_aggregate_cum"]),
            line("Slab", "Steel", concrete * a["steel_kg_per_cum"], "kg", "Rule of thumb: %g kg a cum. Take the real figure from the bar bending schedule" % a["steel_kg_per_cum"]),
            line("Slab", "Shuttering", floor, "sqm", "Floor area", False),
            line("Finishes", "Floor tiles", floor, "sqm", "Floor area"),
        ]
    if q["doors"]:
        out.append(line("Openings", "Doors", q["doors"] * storeys, "nos", "Counted on the drawing x floors", False))
    if q["windows"]:
        out.append(line("Openings", "Windows", q["windows"] * storeys, "nos", "Counted on the drawing x floors", False))
    return out
