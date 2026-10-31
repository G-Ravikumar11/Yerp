"""The Bar Bending Schedule: its arithmetic, its shapes, and who may change what."""
import pytest

import main
from app import models


@pytest.fixture(autouse=True)
def _fresh():
    main.rate_limiter._hits.clear()


def job(tenant):
    return tenant.post("/api/jobs", json={"name": "Tower A", "customer_name": "L&T"}).json()


def body(j, **over):
    b = {"job_id": j["id"], "block": "A", "floor": "First", "element": "Beam", "member_ref": "B1", "bar_mark": "a", "diameter_mm": 16, "grade": "Fe500D", "shape": "Straight", "dims": {"A": 6000}, "num_bars": 10}
    b.update(over)
    return b


def add(tenant, j, **over):
    res = tenant.post("/api/bbs", json=body(j, **over))
    assert res.status_code == 200, res.text
    return res.json()["entry"]


def test_length_and_weight_follow_the_formulas_unrounded(tenant):
    e = add(tenant, job(tenant))
    assert e["cutting_length_mm"] == 6000 and e["total_length_m"] == 60
    assert e["unit_weight_kg_m"] == pytest.approx(16 * 16 / 162, abs=1e-12)
    assert e["total_weight_kg"] == pytest.approx(60 * 256 / 162, abs=1e-9)


def test_each_shape_takes_off_its_bends(tenant):
    j = job(tenant)
    d = 10
    cases = {"L": ({"A": 2000, "B": 300}, 2300 - 2 * d), "U": ({"A": 300, "B": 2000, "C": 300}, 2600 - 4 * d),
             "Crank": ({"A": 5000, "D": 200}, 5000 + 0.84 * 200 - 4 * d), "Stirrup": ({"A": 300, "B": 500}, 1600 - 6 * d - 6 * d + 20 * d)}
    for n, (shape, (dims, want)) in enumerate(cases.items()):
        assert add(tenant, j, shape=shape, dims=dims, diameter_mm=d, bar_mark="m%d" % n)["cutting_length_mm"] == pytest.approx(want)


def test_a_custom_shape_takes_the_length_given(tenant):
    e = add(tenant, job(tenant), shape="Custom", dims={}, cutting_length_mm=4321)
    assert e["cutting_length_mm"] == 4321


def test_the_rules_are_set_for_the_company_or_the_project_and_saved_entries_stay(tenant):
    j = job(tenant)
    bent = add(tenant, j, shape="L", dims={"A": 2000, "B": 300}, diameter_mm=10, bar_mark="b")
    assert bent["cutting_length_mm"] == 2280
    assert tenant.put("/api/bbs/rules", json={"bend_45": 1, "bend_90": 3, "bend_135": 3, "hook": 9}).status_code == 200
    assert tenant.post("/api/bbs/calculate", json=body(j, shape="L", dims={"A": 2000, "B": 300}, diameter_mm=10)).json()["cutting_length_mm"] == 2270
    assert tenant.put("/api/bbs/rules", json={"job_id": j["id"], "bend_45": 1, "bend_90": 4, "bend_135": 3, "hook": 9}).status_code == 200
    assert tenant.post("/api/bbs/calculate", json=body(j, shape="L", dims={"A": 2000, "B": 300}, diameter_mm=10)).json()["cutting_length_mm"] == 2260
    assert tenant.get("/api/bbs/rules").json()["bend_90"] == 3 and tenant.get("/api/bbs/rules?job_id=%d" % j["id"]).json()["bend_90"] == 4
    assert tenant.get("/api/bbs?job_id=%d" % j["id"]).json()["entries"][0]["cutting_length_mm"] == 2280     # already saved
    assert tenant.put("/api/bbs/rules", json={"bend_45": -1, "bend_90": 3, "bend_135": 3, "hook": 9}).status_code == 400


@pytest.mark.parametrize("bad", [{"diameter_mm": 0}, {"diameter_mm": -8}, {"num_bars": 0}, {"num_bars": -2}, {"dims": {"A": 0}}, {"dims": {}}, {"shape": "Star"}, {"element": "Roof"}, {"grade": "Fe1"},
                                 {"bar_mark": " "}, {"floor": ""}, {"shape": "Custom", "dims": {}, "cutting_length_mm": 0}, {"shape": "L", "diameter_mm": 500, "dims": {"A": 100, "B": 100}}])
def test_bad_figures_are_refused(tenant, bad):
    assert tenant.post("/api/bbs", json=body(job(tenant), **bad)).status_code == 400


def test_one_bar_mark_once_on_a_member(tenant):
    j = job(tenant)
    add(tenant, j)
    assert tenant.post("/api/bbs", json=body(j, bar_mark=" A ", floor="first")).status_code == 409
    assert add(tenant, j, floor="Second")["floor"] == "Second"


def test_every_change_keeps_the_last_version(tenant):
    j = job(tenant)
    e = add(tenant, j)
    res = tenant.put("/api/bbs/%d" % e["id"], json=body(j, num_bars=12, reason="Drawing rev B"))
    assert res.status_code == 200 and res.json()["entry"]["revision"] == 1 and res.json()["entry"]["total_length_m"] == 72
    rev = tenant.get("/api/bbs/%d/revisions" % e["id"]).json()["revisions"]
    assert len(rev) == 1 and rev[0]["entry"]["num_bars"] == 10 and rev[0]["reason"] == "Drawing rev B"


def test_an_approved_entry_is_protected(tenant, portal):
    j = job(tenant)
    e = add(tenant, j)
    assert portal.post("/api/bbs/approve", json={"ids": [e["id"]]}).status_code in (401, 403)
    assert tenant.post("/api/bbs/approve", json={"ids": [e["id"]]}).json()["approved"] == 1
    got = tenant.get("/api/bbs?job_id=%d" % j["id"]).json()["entries"][0]
    assert got["status"] == "Approved" and got["approved_by"]
    assert portal.put("/api/bbs/%d" % e["id"], json=body(j, num_bars=11, reason="x")).status_code in (401, 403)
    assert tenant.put("/api/bbs/%d" % e["id"], json=body(j, num_bars=11)).status_code == 400                # no reason
    res = tenant.put("/api/bbs/%d" % e["id"], json=body(j, num_bars=11, reason="Site change"))
    assert res.status_code == 200 and res.json()["entry"]["status"] == "Draft" and res.json()["entry"]["approved_by"] == ""
    with main.SessionLocal() as db:
        assert db.query(models.DBAuditLog).filter(models.DBAuditLog.action == "bbs.revised", models.DBAuditLog.entity_id == e["id"]).count() == 1


def test_filters_summary_and_exports(tenant):
    j = job(tenant)
    add(tenant, j)
    add(tenant, j, bar_mark="b", diameter_mm=20, num_bars=4, dims={"A": 5000})
    add(tenant, j, floor="Second", element="Column", member_ref="C1", bar_mark="c", diameter_mm=20, num_bars=8, dims={"A": 3000})
    data = tenant.get("/api/bbs?job_id=%d" % j["id"]).json()
    s = data["summary"]
    assert s["entries"] == 3 and len(s["by_group"]) == 2
    d20 = [x for x in s["by_diameter"] if x["diameter_mm"] == 20][0]
    assert d20["total_length_m"] == 44 and d20["total_weight_kg"] == pytest.approx(44 * 400 / 162)
    assert s["total_weight_kg"] == pytest.approx(60 * 256 / 162 + 44 * 400 / 162)
    q = lambda p: len(tenant.get("/api/bbs?job_id=%d&%s" % (j["id"], p)).json()["entries"])
    assert q("floor=Second") == 1 and q("element=Beam") == 2 and q("bar_mark=B") == 1 and q("diameter=20") == 2
    assert tenant.get("/api/bbs/export.xlsx?job_id=%d" % j["id"]).status_code == 200
    assert tenant.get("/api/bbs/schedule.pdf?job_id=%d" % j["id"]).status_code == 200


def test_another_company_sees_none_of_it(tenant, second_tenant):
    j = job(tenant)
    e = add(tenant, j)
    assert second_tenant.get("/api/bbs").json()["entries"] == []
    assert second_tenant.put("/api/bbs/%d" % e["id"], json=body(j)).status_code == 404
    assert second_tenant.post("/api/bbs", json=body(j)).status_code == 404
