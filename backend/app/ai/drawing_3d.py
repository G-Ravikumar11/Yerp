"""Read an uploaded floor plan (picture or PDF) into walls and rooms, so the Drawings screen can stand it up in 3D.

Nothing is saved and nothing is measured from it: the result is a visual aid. The model only traces what the sheet
shows; every coordinate is checked, tidied and clamped here, and anything unusable is dropped.

How it stays accurate and does not fail on the free provider tier:
  - the picture is sent with a labelled 10% grid drawn over it, so the model reads positions off the grid instead of
    guessing; this alone cut the wall error from about 8% to about 2% on a test plan;
  - the answer is plain text, not forced JSON (a forced-JSON answer that runs out of room is thrown away whole), and
    what arrives is parsed or recovered here;
  - the provider allows about 7000 input and 1000 output tokens a minute, so one trace is made at a time, a traced
    sheet is remembered, and a refusal is retried after the wait the provider names.

    POST /api/ai/drawings/{drawing_id}/to-3d
"""
import io
import json
import threading
import time
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.ai import guard
from app.ai.llm_client import AiResult, Attachment, ask, parse_json
from app.core.auth import require_erp_read
from app.core.files import file_bytes
from app.db import get_db

router = APIRouter()

ACTION_KEY = "ai_drawing_3d"
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
MAX_WALLS, MAX_ROOMS, MAX_OPENINGS = 400, 60, 120
PICTURE_PX = 1280
MAX_TOKENS = 900                      # the provider's output limit is 1000 a minute
MAX_ATTEMPTS = 4
MAX_WAIT_S = 20

# A traced sheet is kept in memory by (client, file): asking again costs nothing and cannot hit the rate limit. A new
# revision is a new file, so it is traced afresh.
_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_CACHE_MAX = 64
_LOCK = threading.Lock()              # one trace at a time: two at once would spend the same minute's allowance
_RETRY_REASONS = ("rate_limited", "upstream_error", "timeout", "network_error", "bad_answer")

SYSTEM = (
    "You trace an architectural floor plan so it can be extruded into a simple 3D model. Report only what the drawing "
    "shows; never invent rooms or walls. All positions are whole-number percentages of the picture, read against the "
    "red labelled grid lines drawn on it (0 to 100 from the left and from the top). Be compact: no explanations."
)

PROMPT = (
    "Trace this floor plan. Return one JSON object with these keys, using plain arrays of whole numbers:\n"
    '  "walls": [[x1,y1,x2,y2], ...] straight wall segments; merge collinear pieces; at most 45 walls, outer walls first\n'
    '  "rooms": [["Name",x,y,w,h], ...] each labelled room as left, top, width, height; at most 14\n'
    '  "openings": [["door" or "window",x,y], ...] centre points; at most 20\n'
    '  "width_m": real width in metres of the whole plan from printed dimensions or scale, or null\n'
    '  "storeys": 1\n'
    '  "confidence": 0 to 1\n'
    "Answer with the JSON object only."
)


def _picture_of(data: bytes, media: str):
    """The picture to look at: the file itself, or the scan inside a PDF. None when a PDF holds no picture."""
    if media in IMAGE_TYPES:
        return data
    if media != "application/pdf":
        return None
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        best = None
        for page in reader.pages[:3]:
            for img in page.images:
                if best is None or len(img.data) > len(best):
                    best = img.data
            if best:
                break
        return best
    except Exception:
        return None


def prepare(data: bytes, media: str):
    """The sheet as a JPEG of at most 1280 px with a labelled 10% grid over it; None if it cannot be read as a picture."""
    raw = _picture_of(data, media)
    if not raw:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.split()[-1])
            im = flat
        else:
            im = im.convert("RGB")
        im.thumbnail((PICTURE_PX, PICTURE_PX))
        w, h = im.size
        over = Image.new("RGBA", im.size, (0, 0, 0, 0))
        g = ImageDraw.Draw(over)
        try:
            font = ImageFont.load_default(size=max(11, w // 90))
        except TypeError:                 # an older Pillow has one fixed size
            font = ImageFont.load_default()
        for p in range(0, 101, 10):
            x, y = p * (w - 1) / 100, p * (h - 1) / 100
            g.line([(x, 0), (x, h)], fill=(220, 0, 0, 110), width=1)
            g.line([(0, y), (w, y)], fill=(220, 0, 0, 110), width=1)
            g.text((x + 2, 2), str(p), fill=(200, 0, 0, 255), font=font)
            g.text((2, y + 1), str(p), fill=(200, 0, 0, 255), font=font)
        im = Image.alpha_composite(im.convert("RGBA"), over).convert("RGB")
        out = io.BytesIO()
        im.save(out, "JPEG", quality=82)
        return out.getvalue()
    except Exception:
        return None


def _pct(v):
    try:
        return max(0.0, min(100.0, float(v)))
    except (TypeError, ValueError):
        return None


def _as_list(v):
    """A list, whatever shape the model used: a dict of items becomes its values, anything else becomes empty."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        vals = list(v.values())
        return vals if vals and all(isinstance(x, (dict, list)) for x in vals) else [v]
    return []


def _walls_of(item):
    """(x1, y1, x2, y2) from either [x1,y1,x2,y2] or {"x1":..}."""
    if isinstance(item, (list, tuple)) and len(item) >= 4:
        return item[0], item[1], item[2], item[3]
    if isinstance(item, dict):
        return item.get("x1"), item.get("y1"), item.get("x2"), item.get("y2")
    return None, None, None, None


def salvage(text: str):
    """The complete part of an answer that was cut off mid-way: closes what is open after the last whole value."""
    start = text.find("{")
    if start < 0:
        return None
    text = text[start:]
    stack, in_str, esc, cuts = [], False, False, []
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
        elif ch == ",":
            cuts.append((i, "".join("}" if c == "{" else "]" for c in reversed(stack))))
    for i, closers in reversed(cuts[-300:]):
        try:
            data = json.loads(text[:i] + closers)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _snap(values, tol):
    """Each value moved to the mean of the cluster of values within `tol` of it, so walls that meet really meet."""
    order = sorted(set(values))
    mapping, cluster = {}, []
    for v in order + [None]:
        if cluster and (v is None or v - cluster[-1] > tol):
            mean = sum(cluster) / len(cluster)
            for c in cluster:
                mapping[c] = mean
            cluster = []
        if v is not None:
            cluster.append(v)
    return mapping


def tidy(walls):
    """Straighten nearly horizontal or vertical walls and join the ends that meet. Plans are mostly square; a model
    reads positions a point or two off, and that is what makes a traced plan look crooked."""
    out = []
    for w in walls:
        x1, y1, x2, y2 = w["x1"], w["y1"], w["x2"], w["y2"]
        if abs(y1 - y2) <= 2.5 and abs(x1 - x2) > 2.5:
            y1 = y2 = (y1 + y2) / 2
        elif abs(x1 - x2) <= 2.5 and abs(y1 - y2) > 2.5:
            x1 = x2 = (x1 + x2) / 2
        out.append([x1, y1, x2, y2])
    xmap = _snap([v for w in out for v in (w[0], w[2])], 2.0)
    ymap = _snap([v for w in out for v in (w[1], w[3])], 2.0)
    result = []
    for x1, y1, x2, y2 in out:
        x1, x2, y1, y2 = xmap[x1], xmap[x2], ymap[y1], ymap[y2]
        if abs(x1 - x2) < 0.2 and abs(y1 - y2) < 0.2:
            continue
        result.append({"x1": round(x1, 1), "y1": round(y1, 1), "x2": round(x2, 1), "y2": round(y2, 1)})
    return result


def clean(read: dict) -> dict:
    """Keep only walls, rooms and openings with usable coordinates, inside the picture."""
    walls, rooms, openings = [], [], []
    for w in _as_list(read.get("walls"))[:MAX_WALLS]:
        x1, y1, x2, y2 = (_pct(v) for v in _walls_of(w))
        if None in (x1, y1, x2, y2) or (abs(x1 - x2) < 0.2 and abs(y1 - y2) < 0.2):
            continue
        walls.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
    for r in _as_list(read.get("rooms"))[:MAX_ROOMS]:
        if isinstance(r, (list, tuple)) and len(r) >= 5:
            name, vals = r[0], r[1:5]
        elif isinstance(r, dict):
            name, vals = r.get("name"), [r.get("x"), r.get("y"), r.get("w"), r.get("h")]
        else:
            continue
        x, y, w, h = (_pct(v) for v in vals)
        if None in (x, y, w, h) or w < 1 or h < 1:
            continue
        rooms.append({"name": str(name or "")[:40], "x": x, "y": y, "w": min(w, 100 - x), "h": min(h, 100 - y)})
    for o in _as_list(read.get("openings"))[:MAX_OPENINGS]:
        if isinstance(o, (list, tuple)) and len(o) >= 3:
            kind, x, y = o[0], _pct(o[1]), _pct(o[2])
        elif isinstance(o, dict):
            kind, x, y = o.get("type"), _pct(o.get("x")), _pct(o.get("y"))
        else:
            continue
        if x is None or y is None:
            continue
        openings.append({"type": "window" if str(kind).lower() == "window" else "door", "x": x, "y": y})
    width = read.get("width_m")
    width = float(width) if isinstance(width, (int, float)) and not isinstance(width, bool) and 2 <= width <= 500 else None
    storeys = read.get("storeys")
    conf = read.get("confidence")
    return {"walls": tidy(walls), "rooms": rooms, "openings": openings, "width_m": width,
            "storeys": int(storeys) if isinstance(storeys, (int, float)) and 1 <= storeys <= 10 else 1,
            "confidence": conf if isinstance(conf, (int, float)) else None}


def _trace(picture: bytes) -> AiResult:
    """One model call, retried after the wait the provider names (or a short back-off) when it is busy or refuses."""
    result = AiResult(False, reason="upstream_error")
    for attempt in range(MAX_ATTEMPTS):
        result = ask(SYSTEM, PROMPT, [Attachment(picture, "image/jpeg")], smart=True, max_tokens=MAX_TOKENS,
                     groq_extra={"reasoning_effort": "none"})
        if result.ok:
            data = parse_json(result.text)
            if not isinstance(data, dict):
                data = salvage(result.text)
            if isinstance(data, dict) and (data.get("walls") or data.get("rooms")):
                result.data = data
                return result
            result = AiResult(False, text=result.text, reason="bad_answer", provider=result.provider,
                              model=result.model, usage=result.usage)
        if result.reason not in _RETRY_REASONS or attempt == MAX_ATTEMPTS - 1:
            break
        time.sleep(min(max(result.retry_after + 0.5, 2.0 * (attempt + 1)), MAX_WAIT_S))
    return result


@router.post("/api/ai/drawings/{drawing_id}/to-3d")
def drawing_to_3d(drawing_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    row = (db.query(models.DBDrawing, models.DBDrawingRevision)
           .outerjoin(models.DBDrawingRevision, models.DBDrawingRevision.drawing_id == models.DBDrawing.id)
           .filter(models.DBDrawing.id == drawing_id, models.DBDrawing.client_id == client.id)
           .order_by(models.DBDrawingRevision.id.desc()).first())
    if not row:
        raise HTTPException(404, "Drawing not found")
    d, cur = row
    if not cur or not cur.file_id:
        raise HTTPException(409, "Add a revision with a picture or PDF of the plan first.")
    key = (client.id, cur.file_id)
    if key in _CACHE:                       # a sheet already traced: no file read, no model call
        _CACHE.move_to_end(key)
        return _CACHE[key]

    f = db.query(models.DBFile).filter(models.DBFile.id == cur.file_id, models.DBFile.client_id == client.id).first()
    if not f:
        raise HTTPException(409, "The file for this revision is missing. Add the revision again.")
    media = (f.content_type or "").lower()
    if media not in IMAGE_TYPES and media != "application/pdf":
        raise HTTPException(400, "Only a picture (JPG, PNG) or a PDF of a plan can be shown in 3D. DWG and DXF are not supported yet.")
    data = file_bytes(db, f)
    picture = prepare(data, media) if data else None
    if not picture:
        raise HTTPException(400, "No picture could be read from this file. A PDF drawn as lines (not a scan) cannot be traced: "
                                 "export the plan as a JPG or PNG and add it as the revision.")

    with _LOCK:
        if key in _CACHE:                   # another click traced it while this one waited
            return _CACHE[key]
        result = guard.run_feature(db, request, client, ACTION_KEY, "3D view %s" % d.number, d.number or "",
                                   lambda: _trace(picture))
    if not result.ok:
        message = result.message
        if result.reason == "bad_answer":
            message = "No walls or rooms could be found on this sheet. It may not be a floor plan, or it is too faint to read."
        elif result.reason == "rate_limited":
            message = "The AI is busy right now. Wait a few seconds and try again."
        return {"available": False, "reason": result.reason, "message": message}
    out = clean(result.data)
    if not out["walls"] and not out["rooms"]:
        return {"available": False, "reason": "bad_answer",
                "message": "No walls or rooms could be found on this sheet. It may not be a floor plan."}
    out.update({"available": True, "model": result.model, "revision": cur.revision,
                "low_confidence": out["confidence"] is not None and out["confidence"] < 0.6})
    _CACHE[key] = out
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return out
