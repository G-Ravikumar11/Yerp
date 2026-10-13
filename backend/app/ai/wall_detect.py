"""Find the walls of a floor plan from the picture itself, with no model.

A drawn wall is a long, straight, dark band. Reading those off the pixels is exact where a vision model is
approximate, instant where a model takes seconds to minutes, and free. The model is then only needed for what
pixels cannot say: the names of the rooms, where the doors are, and the width in metres.

The method is plain, and made to cope with a photograph of a sheet as well as a clean export:
  1. find the paper (a photo has a dark table or screen around it, which would read as one huge wall);
  2. set "ink" relative to how bright that paper is, so a dim photo and a scan both work;
  3. find the long horizontal runs of ink in every row (and, on the turned picture, every column), stack runs that
     sit on top of each other into bands, and keep the bands thick enough to be a wall and not a hairline;
  4. join the pieces that line up, then keep only the pieces that are connected to the building, which drops a
     scale bar, a north arrow, a title block and anything else drawn beside the plan.
"""
import io
import re
from typing import List, Optional

WORK_PX = 1000            # the sheet is looked at this big; walls are measured as a share of it
MIN_LEN = 0.045           # a wall is at least this share of the paper's width or height
MIN_THICK = 0.0030        # ...and at least this thick (a share of the long side): a hairline is not a wall
MAX_THICK = 0.05          # ...and at most this thick: a filled title block is not a wall
EDGE = 0.012              # lines this close to the paper's edge are its border, not a wall
JOIN = 0.015              # lines this close, and overlapping, are one wall (a double-line wall, or a broken scan)
GAP = 0.012               # pieces on one line closer than this are joined
LINK = 0.055              # pieces this close (about a door's width) belong to the same building
MAX_WALLS = 150

_RUN = re.compile(rb"\x01+(?:\x00{1,2}\x01+)*")     # ink, allowing a one or two pixel gap in a scanned line


def _load(raw: bytes):
    """The sheet as a grey picture of at most WORK_PX, or None when it is not a picture."""
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.split()[-1])
            im = flat
        im = im.convert("L")
        im.thumbnail((WORK_PX, WORK_PX))
        return im
    except Exception:
        return None


def _paper(im):
    """(left, top, right, bottom) of the bright sheet inside the picture; the whole picture when it is all paper."""
    from PIL import Image
    w, h = im.size
    small = im.resize((max(8, w // 4), max(8, h // 4)), Image.Resampling.BOX)
    sw, sh = small.size
    px = small.tobytes()
    hist = [0] * 256
    for v in px:
        hist[v] += 1
    # the brightest tenth of the picture is paper (or a white page margin); half of its level is the cut-off
    acc, bright = 0, 255
    for v in range(255, -1, -1):
        acc += hist[v]
        if acc >= len(px) * 0.10:
            bright = v
            break
    cut = max(60, int(bright * 0.7))
    rows = [sum(1 for v in px[y * sw:(y + 1) * sw] if v > cut) / sw for y in range(sh)]
    cols = [sum(1 for y in range(sh) if px[y * sw + x] > cut) / sh for x in range(sw)]
    ys = [y for y, r in enumerate(rows) if r > 0.30]
    xs = [x for x, c in enumerate(cols) if c > 0.30]
    if not ys or not xs:
        return 0, 0, w, h
    left, right, top, bottom = xs[0] * 4, (xs[-1] + 1) * 4, ys[0] * 4, (ys[-1] + 1) * 4
    return max(0, left), max(0, top), min(w, right), min(h, bottom)


def _bands(data: bytes, w: int, h: int):
    """Long horizontal bands of ink as (y_top, y_bottom, x_left, x_right), found row by row."""
    min_len = max(8, int(w * MIN_LEN))
    done, active = [], []
    for y in range(h):
        row = data[y * w:(y + 1) * w]
        segs = [(m.start(), m.end()) for m in _RUN.finditer(row) if m.end() - m.start() >= min_len]
        still = []
        for x1, x2 in segs:
            hit = None
            for b in active:
                if b[1] != y - 1:
                    continue
                overlap = min(x2, b[3]) - max(x1, b[2])
                if overlap >= 0.7 * min(x2 - x1, b[3] - b[2]):
                    hit = b
                    break
            if hit:
                hit[1] = y
                hit[2], hit[3] = min(hit[2], x1), max(hit[3], x2)
                still.append(hit)
            else:
                still.append([y, y, x1, x2])
        for b in active:
            if b not in still:
                done.append(tuple(b))
        active = still
    done.extend(tuple(b) for b in active)
    return done


def _lines(im, ink: int, vertical: bool):
    """Walls in one direction as [position, from, to] with all three as a share of this picture, 0 to 100."""
    if vertical:
        from PIL import Image
        im = im.transpose(Image.Transpose.TRANSPOSE)
    w, h = im.size
    data = im.point(lambda p: 1 if p < ink else 0).tobytes()
    long_side = max(w, h)
    out = []
    for top, bottom, x1, x2 in _bands(data, w, h):
        thick = bottom - top + 1
        if thick < max(2, MIN_THICK * long_side) or thick > MAX_THICK * long_side:
            continue
        pos = (top + bottom + 1) / 2 / h * 100
        if pos < EDGE * 100 or pos > 100 - EDGE * 100:
            continue
        out.append([pos, x1 / w * 100, x2 / w * 100])
    return out


def _join(lines: List[list]) -> List[list]:
    """Merge lines that are the same wall: nearly the same position, overlapping or nearly touching."""
    lines = sorted(lines, key=lambda l: (l[0], l[1]))
    merged: List[list] = []
    for pos, a, b in lines:
        for m in merged:
            if abs(m[0] - pos) <= JOIN * 100 and a <= m[2] + GAP * 100 and b >= m[1] - GAP * 100:
                n = (m[2] - m[1]) + (b - a)
                m[0] = (m[0] * (m[2] - m[1]) + pos * (b - a)) / n if n else m[0]
                m[1], m[2] = min(m[1], a), max(m[2], b)
                break
        else:
            merged.append([pos, a, b])
    return merged


def _gap(a, b) -> float:
    """Distance between two axis-aligned segments (x1, y1, x2, y2), as a share of the picture."""
    ax1, ax2 = sorted((a[0], a[2]))
    ay1, ay2 = sorted((a[1], a[3]))
    bx1, bx2 = sorted((b[0], b[2]))
    by1, by2 = sorted((b[1], b[3]))
    dx = max(bx1 - ax2, ax1 - bx2, 0)
    dy = max(by1 - ay2, ay1 - by2, 0)
    return (dx * dx + dy * dy) ** 0.5


def _the_building(walls: List[list]) -> List[list]:
    """Keep the walls that form the building. A scale bar, a north arrow and the pieces of a title block are small
    and sit outside it, so they go."""
    n = len(walls)
    if n < 2:
        return walls
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if _gap(walls[i], walls[j]) <= LINK * 100:
                parent[find(i)] = find(j)
    groups = {}
    for i, w in enumerate(walls):
        groups.setdefault(find(i), []).append(w)

    def length(g):
        return sum(abs(w[2] - w[0]) + abs(w[3] - w[1]) for w in g)
    longest = max(length(g) for g in groups.values())
    # every substantial structure is part of the building (an open-plan room splits it in two); a scale bar or a
    # north arrow is not, and neither is anything that sits outside the box around the substantial structures
    substantial = [g for g in groups.values() if length(g) >= 0.12 * longest]
    xs = [v for g in substantial for w in g for v in (w[0], w[2])]
    ys = [v for g in substantial for w in g for v in (w[1], w[3])]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    keep: List[list] = []
    for g in groups.values():
        gx = [v for w in g for v in (w[0], w[2])]
        gy = [v for w in g for v in (w[1], w[3])]
        cx, cy = (min(gx) + max(gx)) / 2, (min(gy) + max(gy)) / 2
        if g in substantial or (x0 <= cx <= x1 and y0 <= cy <= y1):
            keep.extend(g)
    return keep


def detect_walls(raw: Optional[bytes]) -> List[list]:
    """The walls of a plan as [[x1, y1, x2, y2], ...], each as a share of the picture (0 to 100); [] when none."""
    if not raw:
        return []
    im = _load(raw)
    if im is None:
        return []
    W, H = im.size
    left, top, right, bottom = _paper(im)
    inset = int(0.006 * max(W, H))                       # step in from the paper's edge, off the sheet's border line
    left, top, right, bottom = left + inset, top + inset, right - inset, bottom - inset
    if right - left < 40 or bottom - top < 40:
        left, top, right, bottom = 0, 0, W, H
    page = im.crop((left, top, right, bottom))
    pw, ph = page.size
    # "ink" is a good deal darker than this sheet's paper: the brightness most pixels have
    hist = page.histogram()
    acc, paper = 0, 200
    for v in range(255, -1, -1):
        acc += hist[v]
        if acc >= pw * ph * 0.30:
            paper = v
            break
    ink = max(50, min(150, int(paper * 0.55)))

    horizontal = _join(_lines(page, ink, vertical=False))
    vertical = _join(_lines(page, ink, vertical=True))

    def to_picture_x(p):                                  # a share of the cropped page -> a share of the whole picture
        return (left + p / 100 * pw) / W * 100

    def to_picture_y(p):
        return (top + p / 100 * ph) / H * 100
    walls = [[to_picture_x(a), to_picture_y(p), to_picture_x(b), to_picture_y(p)] for p, a, b in horizontal]
    walls += [[to_picture_x(p), to_picture_y(a), to_picture_x(p), to_picture_y(b)] for p, a, b in vertical]
    walls = _the_building(walls)
    walls.sort(key=lambda w: -(abs(w[2] - w[0]) + abs(w[3] - w[1])))
    return [[round(v, 1) for v in w] for w in walls[:MAX_WALLS]]
