"""Late is measured against the baseline - what was promised - not against the plan as it stands, which the programme moves along
with every late predecessor. An activity that is late needs a hindrance against it or a reason, and one with neither is called out."""
from datetime import date, timedelta

from test_programme_edit import edit, ok, url
from test_programme_progress import block
from test_schedule import job


def _monday(weeks):
    t = date.today() + timedelta(weeks=weeks)
    return t - timedelta(days=t.weekday())


def acts(tenant, j):
    s = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()
    return {a["name"]: a for a in s["activities"]}, s["summary"]


def late_site(tenant):
    """Flooring then skirting, both meant to be over weeks ago, baselined; then the flooring is given three more days."""
    j = job(tenant)
    ids, _ = block(tenant, j, _monday(-4))
    before, _ = acts(tenant, j)
    ok(tenant.post(url(j, "/baseline"), json={"label": "As agreed"}))
    ok(edit(tenant, j, ids["floor"], days=8))
    return j, ids, before


def test_late_is_counted_from_the_baseline_finish_not_the_moved_plan(tenant):
    j, ids, before = late_site(tenant)
    a, s = acts(tenant, j)
    sk = a["Skirting"]
    promised = before["Skirting"]["planned_finish"]
    assert sk["planned_finish"] > promised, "the plan moved the skirting back"
    assert sk["baseline_finish"] == promised and sk["measured_against"] == "baseline"
    assert sk["days_late"] == (date.today() - date.fromisoformat(promised)).days, "late from the promised day, not the moved one"
    assert sk["delay_days"] >= sk["days_late"] and sk["state"] == "late" and sk["overdue"]
    assert s["measured_against"] == "baseline" and s["baseline_finish"] == promised
    assert s["slip_days"] == (date.fromisoformat(s["forecast_finish"]) - date.fromisoformat(promised)).days
    # The day plan says the same.
    day = tenant.get("/api/jobs/%d/schedule/day" % j["id"]).json()
    over = {r["name"]: r for r in day["overdue"]}
    assert over["Skirting"]["days_late"] == sk["days_late"] and over["Skirting"]["baseline_finish"] == promised


def test_without_a_baseline_the_plan_is_what_late_is_measured_from(tenant):
    j = job(tenant)
    block(tenant, j, _monday(-4))
    a, s = acts(tenant, j)
    assert a["Skirting"]["measured_against"] == "plan" and a["Skirting"]["baseline_finish"] == a["Skirting"]["planned_finish"]
    assert s["measured_against"] == "plan"


def test_a_late_activity_needs_a_hindrance_or_a_reason(tenant):
    j, ids, _ = late_site(tenant)
    a, s = acts(tenant, j)
    assert a["Flooring"]["needs_reason"] and a["Skirting"]["needs_reason"] and s["unexplained"] == 2
    attention = tenant.get("/api/attention").json()
    items = attention if isinstance(attention, list) else attention.get("items", [])
    assert any(i["kind"] == "delay_unexplained" and i["count"] == 2 for i in items)

    # A hindrance on the register against the flooring explains it ...
    h = tenant.post("/api/jobs/%d/hindrances" % j["id"], json={"cause": "Drawings or details awaited", "from_date": _monday(-4).isoformat(),
                                                                 "to_date": _monday(-3).isoformat(), "responsibility": "Client", "activity_id": ids["floor"]})
    assert h.status_code == 200, h.text
    # ... and a reason explains the skirting.
    res = tenant.put("/api/schedule/activities/%d/delay-reason" % ids["skirt"], json={"reason": "Predecessor finished late", "note": "Flooring ran over"})
    assert res.status_code == 200, res.text
    a, s = acts(tenant, j)
    assert not a["Flooring"]["needs_reason"] and a["Flooring"]["hindrances"] == ["H-001"]
    assert not a["Skirting"]["needs_reason"] and a["Skirting"]["delay_reason"] == "Predecessor finished late" and a["Skirting"]["delay_note"] == "Flooring ran over"
    assert s["unexplained"] == 0
    # A rejected hindrance explains nothing.
    tenant.put("/api/hindrances/%d" % h.json()["hindrance"]["id"], json={"status": "Rejected"})
    assert acts(tenant, j)[0]["Flooring"]["needs_reason"]
    # The reason taken away, it is wanted again.
    tenant.put("/api/schedule/activities/%d/delay-reason" % ids["skirt"], json={"reason": ""})
    assert acts(tenant, j)[0]["Skirting"]["needs_reason"]


def test_what_a_reason_must_be(tenant):
    j, ids, _ = late_site(tenant)
    put = lambda body: tenant.put("/api/schedule/activities/%d/delay-reason" % ids["skirt"], json=body)
    assert put({"reason": "The moon"}).status_code == 400
    assert put({"reason": "Other"}).status_code == 400                       # "other" has to say what
    assert put({"reason": "Other", "note": "Festival week, site shut"}).status_code == 200
    assert "Weather" in tenant.get("/api/delay-reasons").json()["reasons"]


def test_an_activity_on_time_needs_nothing(tenant):
    j = job(tenant)
    block(tenant, j, _monday(2))
    ok(tenant.post(url(j, "/baseline"), json={}))
    a, s = acts(tenant, j)
    assert all(r["delay_days"] == 0 and not r["needs_reason"] for r in a.values()) and s["unexplained"] == 0
