"""Read an uploaded floor plan (picture or PDF) into walls and rooms, so the Drawings screen can stand it up in 3D.

Nothing is saved and nothing is measured from it: the result is a visual aid. The model only traces what the sheet
shows; every coordinate is checked and clamped here, and anything unusable is dropped.

    POST /api/ai/drawings/{drawing_id}/to-3d
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.ai import guard
from app.ai.llm_client import Attachment, ask_json
from app.core.auth import require_erp_read
from app.core.files import file_bytes
from app.db import get_db

router = APIRouter()

ACTION_KEY = "ai_drawing_3d"
READABLE = ("application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif")
MAX_WALLS, MAX_ROOMS, MAX_OPENINGS = 400, 60, 120

SYSTEM = (
    "You trace an architectural floor plan so it can be extruded into a simple 3D model. Report only what the drawing "
    "shows; never invent rooms or walls. All positions are percentages of the picture: x from 0 (left edge) to 100 "
    "(right edge), y from 0 (top edge) to 100 (bottom edge)."
)

PROMPT = (
    "Trace this floor plan and return a JSON object with:\n"
    '  "walls": every wall as {"x1": number, "y1": number, "x2": number, "y2": number}, straight segments only\n'
    '  "rooms": {"name": text, "x": left, "y": top, "w": width, "h": height} for each labelled room\n'
    '  "openings": doors and windows as {"type": "door" or "window", "x": centre x, "y": centre y}\n'
    '  "width_m": the real width in metres of the whole plan across the picture, from printed dimensions or scale, or null\n'
    '  "storeys": number of floors shown, usually 1\n'
    '  "confidence": from 0 to 1\n'
)


def _pct(v):
    try:
        return max(0.0, min(100.0, float(v)))
    except (TypeError, ValueError):
        return None


def clean(read: dict) -> dict:
    """Keep only walls, rooms and openings with usable coordinates, inside the picture."""
    walls, rooms, openings = [], [], []
    for w in (read.get("walls") or [])[:MAX_WALLS]:
        if not isinstance(w, dict):
            continue
        x1, y1, x2, y2 = (_pct(w.get(k)) for k in ("x1", "y1", "x2", "y2"))
        if None in (x1, y1, x2, y2) or (abs(x1 - x2) < 0.2 and abs(y1 - y2) < 0.2):
            continue
        walls.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
    for r in (read.get("rooms") or [])[:MAX_ROOMS]:
        if not isinstance(r, dict):
            continue
        x, y, w, h = (_pct(r.get(k)) for k in ("x", "y", "w", "h"))
        if None in (x, y, w, h) or w < 1 or h < 1:
            continue
        rooms.append({"name": str(r.get("name") or "")[:40], "x": x, "y": y, "w": min(w, 100 - x), "h": min(h, 100 - y)})
    for o in (read.get("openings") or [])[:MAX_OPENINGS]:
        if not isinstance(o, dict):
            continue
        x, y = _pct(o.get("x")), _pct(o.get("y"))
        if x is None or y is None:
            continue
        openings.append({"type": "window" if str(o.get("type")).lower() == "window" else "door", "x": x, "y": y})
    width = read.get("width_m")
    width = float(width) if isinstance(width, (int, float)) and 2 <= width <= 500 else None
    storeys = read.get("storeys")
    conf = read.get("confidence")
    return {"walls": walls, "rooms": rooms, "openings": openings, "width_m": width,
            "storeys": int(storeys) if isinstance(storeys, (int, float)) and 1 <= storeys <= 10 else 1,
            "confidence": conf if isinstance(conf, (int, float)) else None}


@router.post("/api/ai/drawings/{drawing_id}/to-3d")
def drawing_to_3d(drawing_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = db.query(models.DBDrawing).filter(models.DBDrawing.id == drawing_id, models.DBDrawing.client_id == client.id).first()
    if not d:
        raise HTTPException(404, "Drawing not found")
    cur = db.query(models.DBDrawingRevision).filter(models.DBDrawingRevision.drawing_id == d.id).order_by(
        models.DBDrawingRevision.id.desc()).first()
    f = db.query(models.DBFile).filter(models.DBFile.id == cur.file_id, models.DBFile.client_id == client.id).first() if cur and cur.file_id else None
    if not f:
        raise HTTPException(409, "Add a revision with a picture or PDF of the plan first.")
    media = (f.content_type or "").lower()
    data = file_bytes(db, f)
    if media not in READABLE or not data:
        raise HTTPException(400, "Only a picture (JPG, PNG) or a PDF of a plan can be shown in 3D. DWG and DXF are not supported yet.")
    result = guard.run_feature(db, request, client, ACTION_KEY, "3D view %s" % d.number, d.number or "",
                               lambda: ask_json(SYSTEM, PROMPT, [Attachment(data, media)], smart=True, max_tokens=4000))
    if not result.ok:
        return {"available": False, "reason": result.reason, "message": result.message}
    out = clean(result.data)
    if not out["walls"] and not out["rooms"]:
        return {"available": False, "reason": "bad_answer", "message": "No walls or rooms could be found on this sheet. It may not be a floor plan."}
    out.update({"available": True, "model": result.model, "revision": cur.revision,
                "low_confidence": out["confidence"] is not None and out["confidence"] < 0.6})
    return out
