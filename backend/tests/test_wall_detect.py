"""Walls read from the pixels of a floor plan: exact positions, no model, and no false walls from hairlines or borders."""
import io

from PIL import Image, ImageDraw

from app.ai.wall_detect import detect_walls

W, H = 1600, 1100
L, T, R, B = 120, 120, 1480, 980


def _plan(with_noise=False) -> bytes:
    im = Image.new("RGB", (W, H), "white")
    g = ImageDraw.Draw(im)
    for a in [(L, T, R, T), (R, T, R, B), (R, B, L, B), (L, B, L, T), (700, T, 700, 600), (L, 600, R, 600), (1100, 600, 1100, B)]:
        g.line(a, fill="black", width=14)
    if with_noise:
        g.line([L, 1040, R, 1040], fill="black", width=1)            # a dimension line
        g.rectangle([8, 8, W - 9, H - 9], outline="black", width=3)   # the sheet's border
        g.text((300, 330), "LIVING ROOM", fill="black")
    out = io.BytesIO()
    im.save(out, "JPEG", quality=92)
    return out.getvalue()


def _has(walls, x1, y1, x2, y2, tol=1.5):
    return any(abs(w[0] - x1) <= tol and abs(w[1] - y1) <= tol and abs(w[2] - x2) <= tol and abs(w[3] - y2) <= tol for w in walls)


def test_the_outer_and_inner_walls_are_found_where_they_are():
    walls = detect_walls(_plan())
    assert _has(walls, 7.5, 11, 92.5, 11) or _has(walls, 7.1, 11, 93, 11)       # top wall, full width
    assert any(abs(w[0] - 43.8) <= 1.5 and abs(w[2] - 43.8) <= 1.5 and abs(w[3] - w[1]) > 20 for w in walls)  # the middle upright
    assert len(walls) >= 7


def test_a_dimension_line_and_the_sheet_border_are_not_walls():
    clean, noisy = detect_walls(_plan()), detect_walls(_plan(with_noise=True))
    assert len(noisy) == len(clean)


def test_a_blank_sheet_or_a_non_picture_has_no_walls():
    blank = io.BytesIO()
    Image.new("RGB", (800, 600), "white").save(blank, "PNG")
    assert detect_walls(blank.getvalue()) == []
    assert detect_walls(b"not a picture") == []
    assert detect_walls(None) == []


def test_rooms_come_from_the_walls_and_take_the_names_the_model_located():
    from app.ai.rooms import rooms_from_walls
    walls = detect_walls(_plan())
    rooms = rooms_from_walls(walls)
    assert 4 <= len(rooms) <= 6                                   # the plan has five rooms, doors included
    assert all(r["name"].startswith("Room ") for r in rooms)
    named = rooms_from_walls(walls, [("LIVING ROOM", 25, 33), ("KITCHEN", 70, 33)])
    assert {"LIVING ROOM", "KITCHEN"} <= {r["name"] for r in named}
    assert rooms_from_walls([], None) == []
