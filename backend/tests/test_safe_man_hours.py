"""Safe man-hours: hours worked since the last lost-time injury, from the site diaries' labour, and the rates per million."""
from datetime import date, timedelta

import pytest

INCIDENT = {"happened_at": "10:00", "location": "Block A", "description": "Slipped", "injured_name": "Ravi", "injury": "", "treatment": "",
            "immediate_action": "Cordoned off"}


def d(n):
    return (date.today() - timedelta(days=n)).isoformat()


def site(tenant, name="Safety site"):
    j = tenant.post("/api/jobs", json={"name": name, "customer_name": "Kokapet LLP"}).json()
    return j.get("id") or j["job"]["id"]


def diary(tenant, job, on, heads, hours=8):
    res = tenant.post("/api/diary", json={"job_id": job, "diary_date": on, "weather": "Clear", "working_hours": hours,
                                          "labour": [{"trade": "Mason", "headcount": heads, "hours": hours, "rate": 900}]})
    assert res.status_code == 200, res.text


def incident(tenant, job, on, kind, lost=0):
    res = tenant.post("/api/safety/incidents", json={"job_id": job, "happened_on": on, "kind": kind, "lost_days": lost, **INCIDENT})
    assert res.status_code == 200, res.text


def hours(tenant, job=0):
    return tenant.get("/api/safety/man-hours" + ("?job_id=%d" % job if job else "")).json()


def test_with_no_injury_every_hour_is_a_safe_hour(tenant):
    j = site(tenant)
    diary(tenant, j, d(3), 20)
    diary(tenant, j, d(2), 30)
    got = hours(tenant, j)
    assert got["total_hours"] == 400 and got["safe_hours"] == 400 and got["since"] is None and got["ltifr"] == 0


def test_a_lost_time_injury_starts_the_count_again(tenant):
    j = site(tenant)
    diary(tenant, j, d(5), 10)
    incident(tenant, j, d(4), "Lost time injury", lost=3)
    diary(tenant, j, d(3), 25)
    got = hours(tenant, j)
    assert got["safe_hours"] == 200 and got["since"] == d(4) and got["ltis"] == 1
    assert got["ltifr"] == pytest.approx(1 * 1_000_000 / 280, abs=0.01)
    assert got["severity_rate"] == pytest.approx(3 * 1_000_000 / 280, abs=0.01)


def test_a_first_aid_case_is_not_a_lost_time_injury_but_a_day_off_makes_one(tenant):
    j = site(tenant)
    diary(tenant, j, d(5), 10)
    incident(tenant, j, d(4), "First aid")
    assert hours(tenant, j)["safe_hours"] == 80
    incident(tenant, j, d(3), "Medical treatment", lost=1)
    assert hours(tenant, j)["safe_hours"] == 0 and hours(tenant, j)["recordable"] == 1


def test_each_site_counts_its_own_and_all_sites_add_up(tenant):
    a, b = site(tenant, "A"), site(tenant, "B")
    diary(tenant, a, d(2), 10)
    diary(tenant, b, d(2), 5)
    incident(tenant, b, d(1), "Lost time injury")
    assert hours(tenant, a)["safe_hours"] == 80 and hours(tenant, b)["safe_hours"] == 0


def test_another_company_sees_none_of_it(tenant, second_tenant):
    diary(tenant, site(tenant), d(2), 10)
    assert second_tenant.get("/api/safety/man-hours").json()["total_hours"] == 0
