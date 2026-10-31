"""A floor plan traced for the 3D view is kept: a restart (the memory cache gone), or the same picture added again as
a new revision, does not pay the AI to trace it a second time."""
import io

from PIL import Image, ImageDraw

from app.ai import drawing_3d
from app.ai.llm_client import AiResult
from test_project_files import job


def plan_png():
    im = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, 360, 260], outline="black", width=6)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_a_traced_plan_is_kept_across_a_restart_and_a_repeated_upload(tenant, monkeypatch):
    calls = []

    def fake_trace(picture, found=None):
        calls.append(1)
        return AiResult(True, data={"walls": [[10, 10, 90, 10]], "rooms": [{"name": "Hall", "points": [[10, 10], [90, 10], [90, 90]]}],
                                    "openings": [], "confidence": 0.9}, provider="test", model="test-model")
    monkeypatch.setattr(drawing_3d, "_trace", fake_trace)
    j = job(tenant)
    d = tenant.post("/api/jobs/%d/drawings" % j["id"], json={"number": "ARC-501", "title": "Ground floor"}).json()["drawing"]
    png = plan_png()
    tenant.post("/api/drawings/%d/revisions" % d["id"], files={"file": ("gf.png", io.BytesIO(png), "image/png")}, data={"revision": "R0"})
    first = tenant.post("/api/ai/drawings/%d/to-3d" % d["id"]).json()
    assert first["available"] is True and calls == [1]
    drawing_3d._CACHE.clear()                                          # a restart: the memory cache is gone
    again = tenant.post("/api/ai/drawings/%d/to-3d" % d["id"]).json()
    assert again["available"] is True and calls == [1] and again["walls"] == first["walls"]
    # The same picture added as R1: found by its fingerprint, not traced again.
    tenant.post("/api/drawings/%d/revisions" % d["id"], files={"file": ("gf-r1.png", io.BytesIO(png), "image/png")}, data={"revision": "R1"})
    drawing_3d._CACHE.clear()
    r1 = tenant.post("/api/ai/drawings/%d/to-3d" % d["id"]).json()
    assert r1["available"] is True and r1["revision"] == "R1" and calls == [1]
