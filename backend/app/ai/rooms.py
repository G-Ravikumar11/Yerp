"""Rooms from walls.

Once the walls of a plan are known, its rooms are the spaces they enclose. Working that out from the geometry is exact
and instant; asking a small model to draw boxes is neither. The model is then only needed to say which printed name
sits in which space.

The walls are drawn on a coarse grid and thickened a little so a doorway closes; the open cells are then grouped, the
groups that reach the edge of the picture are the outside, and every other group is a room.
"""
from typing import Dict, List, Optional, Tuple

GRID = 150                # the plan is looked at as GRID x GRID cells
SEAL = 3                  # walls are thickened by this many cells each way, which closes small cracks and corners
BRIDGE = 18.0             # a gap this wide (percent) between two pieces of one line is a door or a window: close it
MIN_AREA = 0.004          # a space smaller than this share of the picture is a cupboard or a stair, not a room
MAX_ROOMS = 40


def _bridge(walls: List[list]) -> List[list]:
    """The walls with every door and window gap closed: pieces on one straight line, with a gap of at most BRIDGE
    between them, become one wall. Rooms are the spaces these enclose; the 3D view keeps the real gaps."""
    horizontal, vertical = [], []
    for x1, y1, x2, y2 in walls:
        if abs(x2 - x1) >= abs(y2 - y1):
            horizontal.append(((y1 + y2) / 2, min(x1, x2), max(x1, x2)))
        else:
            vertical.append(((x1 + x2) / 2, min(y1, y2), max(y1, y2)))

    def close(lines):
        lines.sort()
        clusters: List[list] = []
        for pos, a, b in lines:
            if clusters and abs(clusters[-1][0][0] - pos) <= 1.5:
                clusters[-1].append((pos, a, b))
            else:
                clusters.append([(pos, a, b)])
        out = []
        for cl in clusters:
            pos = sum(p for p, _, _ in cl) / len(cl)
            cl.sort(key=lambda t: t[1])
            a, b = cl[0][1], cl[0][2]
            for _, s, e in cl[1:]:
                if s - b <= BRIDGE:
                    b = max(b, e)
                else:
                    out.append((pos, a, b))
                    a, b = s, e
            out.append((pos, a, b))
        return out
    return [[a, p, b, p] for p, a, b in close(horizontal)] + [[p, a, p, b] for p, a, b in close(vertical)]


def _draw(walls: List[list]) -> List[bytearray]:
    grid = [bytearray(GRID) for _ in range(GRID)]
    for x1, y1, x2, y2 in walls:
        c1, r1 = int(round(x1 / 100 * (GRID - 1))), int(round(y1 / 100 * (GRID - 1)))
        c2, r2 = int(round(x2 / 100 * (GRID - 1))), int(round(y2 / 100 * (GRID - 1)))
        steps = max(abs(c2 - c1), abs(r2 - r1), 1)
        for i in range(steps + 1):
            c = c1 + (c2 - c1) * i // steps
            r = r1 + (r2 - r1) * i // steps
            if 0 <= r < GRID and 0 <= c < GRID:
                grid[r][c] = 1
    return grid


def _thicken(grid: List[bytearray], k: int) -> List[bytearray]:
    """Every wall cell grown by k cells in each direction (a square), in two cheap passes."""
    n = GRID
    wide = [bytearray(n) for _ in range(n)]
    for r in range(n):
        row = grid[r]
        for c in range(n):
            if row[c]:
                for cc in range(max(0, c - k), min(n, c + k + 1)):
                    wide[r][cc] = 1
    out = [bytearray(n) for _ in range(n)]
    for r in range(n):
        for rr in range(max(0, r - k), min(n, r + k + 1)):
            src = wide[rr]
            dst = out[r]
            for c in range(n):
                if src[c]:
                    dst[c] = 1
    return out


def _groups(blocked: List[bytearray]):
    """Connected groups of open cells as lists of (row, col); each marked with whether it touches the edge."""
    n = GRID
    seen = [bytearray(n) for _ in range(n)]
    found = []
    for r0 in range(n):
        for c0 in range(n):
            if blocked[r0][c0] or seen[r0][c0]:
                continue
            stack, cells, edge = [(r0, c0)], [], False
            seen[r0][c0] = 1
            while stack:
                r, c = stack.pop()
                cells.append((r, c))
                if r in (0, n - 1) or c in (0, n - 1):
                    edge = True
                for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                    if 0 <= rr < n and 0 <= cc < n and not blocked[rr][cc] and not seen[rr][cc]:
                        seen[rr][cc] = 1
                        stack.append((rr, cc))
            found.append((cells, edge))
    return found


def _box(cells, scale):
    """{"x", "y", "w", "h"} in percent for a set of cells, with the cells the thickening ate given back."""
    rs = [r for r, _ in cells]
    cs = [c for _, c in cells]
    top, left = max(0, min(rs) - SEAL), max(0, min(cs) - SEAL)
    bottom, right = min(GRID - 1, max(rs) + SEAL), min(GRID - 1, max(cs) + SEAL)
    return {"x": round(left * scale, 1), "y": round(top * scale, 1),
            "w": round((right - left + 1) * scale, 1), "h": round((bottom - top + 1) * scale, 1)}


def rooms_from_walls(walls: List[list], labels: Optional[List[Tuple[str, float, float]]] = None) -> List[Dict]:
    """[{"name", "x", "y", "w", "h"}] in percent of the picture, one per room.

    The enclosed spaces come from the walls. Every printed name the model located is given to the nearest space; a
    space that holds two or more names (an open-plan living room and kitchen, or rooms whose walls do not quite close)
    is divided between them, each cell going to its nearest name. A space with no name is "Room N"."""
    if len(walls) < 4:
        return []
    blocked = _thicken(_draw(_bridge(walls)), SEAL)
    spaces = [cells for cells, edge in _groups(blocked) if not edge and len(cells) >= MIN_AREA * GRID * GRID]
    spaces.sort(key=lambda cells: (min(r for r, _ in cells) // 12, min(c for _, c in cells)))     # reading order
    spaces = spaces[:MAX_ROOMS]
    scale = 100 / (GRID - 1)

    # each label goes to the space it is inside, or else the space whose nearest cell is closest to it
    named: List[list] = [[] for _ in spaces]
    for name, lx, ly in labels or []:
        col, row = lx / 100 * (GRID - 1), ly / 100 * (GRID - 1)
        best, best_d = None, None
        for i, cells in enumerate(spaces):
            d = min((r - row) ** 2 + (c - col) ** 2 for r, c in cells[::3] or cells)
            if best_d is None or d < best_d:
                best, best_d = i, d
        if best is not None and best_d is not None and best_d <= (0.18 * GRID) ** 2:     # within ~18% of the plan
            named[best].append((name, col, row))

    rooms, count = [], 0
    for cells, names in zip(spaces, named):
        if len(names) <= 1:
            count += 1
            rooms.append(dict({"name": names[0][0] if names else "Room %d" % count}, **_box(cells, scale)))
            continue
        parts: List[list] = [[] for _ in names]
        for r, c in cells:
            k = min(range(len(names)), key=lambda j: (names[j][2] - r) ** 2 + (names[j][1] - c) ** 2)
            parts[k].append((r, c))
        for (name, _, _), part in zip(names, parts):
            if part:
                rooms.append(dict({"name": name}, **_box(part, scale)))
    return rooms
