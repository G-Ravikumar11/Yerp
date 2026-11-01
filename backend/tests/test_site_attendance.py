"""A clock-in on a project's site is tagged to that project; one outside
every site says so. The office was the only place anybody was checked
against."""
from fastapi.testclient import TestClient

import main
from conftest import make_employee

SITE = (17.4239, 78.3413)          # Kokapet
NEAR = (17.4251, 78.3420)          # about 150 m away
FAR = (17.4486, 78.3908)           # Hitec City, 5 km off


def job(tenant):
    return tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()


def staff_in(tenant, client, lat, lng):
    emp = make_employee(tenant, password="EmpPass123", job_title="Site engineer")
    client.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    res = client.post("/api/employee/attendance/clock-in", json={"latitude": lat, "longitude": lng})
    assert res.status_code == 200, res.text
    return res.json()


def test_a_site_location_is_set_from_a_pasted_maps_link(tenant):
    j = job(tenant)
    res = tenant.put("/api/jobs/%d/site-location" % j["id"],
                     json={"position": "https://www.google.com/maps/place/Kokapet/@17.4239,78.3413,17z", "radius_m": 250})
    assert res.status_code == 200, res.text
    loc = res.json()
    assert loc["set"] and loc["lat"] == 17.4239 and loc["radius_m"] == 250
    assert tenant.put("/api/jobs/%d/site-location" % j["id"], json={"position": "near the lake"}).status_code == 400


def test_a_clock_in_on_site_lands_on_the_project(tenant, client):
    j = job(tenant)
    tenant.put("/api/jobs/%d/site-location" % j["id"], json={"lat": SITE[0], "lng": SITE[1], "radius_m": 300})
    out = staff_in(tenant, client, *NEAR)
    assert out["check_type"] == "site" and out["site"]["job_id"] == j["id"]
    assert "Vanya City STP" in out["message"]
    day = tenant.get("/api/attendance/by-site").json()
    site = [x for x in day["sites"] if x["job_id"] == j["id"]][0]
    assert [p["job_title"] for p in site["people"]] == ["Site engineer"]
    assert day["elsewhere"] == []


def test_a_clock_in_off_every_site_says_so(tenant, client):
    j = job(tenant)
    tenant.put("/api/jobs/%d/site-location" % j["id"], json={"lat": SITE[0], "lng": SITE[1], "radius_m": 300})
    out = staff_in(tenant, client, *FAR)
    assert out["check_type"] != "site" and out["site"] is None
    day = tenant.get("/api/attendance/by-site").json()
    assert len(day["elsewhere"]) == 1
    site = [x for x in day["sites"] if x["job_id"] == j["id"]][0]
    assert site["people"] == [] and site["fenced"]


def test_a_clock_in_with_a_position_is_office_or_field_and_without_one_is_refused_or_manual(tenant):
    """What the phone's location permission is for: with the position the day is saved as office or field. Without one it
    is refused while the company requires location (the default once attendance is set up), and saved as manual when the
    company has switched that off."""
    res = tenant.put("/api/attendance/settings", json={"office_name": "Head Office", "office_lat": SITE[0], "office_lng": SITE[1], "geofence_radius": 300})
    assert res.status_code == 200, res.text
    # Everybody is made first: the owner's browser is the one that signs in as staff in the other tests here.
    people = [make_employee(tenant, password="EmpPass123") for _ in range(4)]

    def clock_in(emp, body):
        with TestClient(main.app) as phone:
            assert phone.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"}).status_code == 200
            return phone.post("/api/employee/attendance/clock-in", json=body)

    near = clock_in(people[0], {"latitude": NEAR[0], "longitude": NEAR[1]})
    assert near.status_code == 200 and near.json()["check_type"] == "office"
    far = clock_in(people[1], {"latitude": FAR[0], "longitude": FAR[1]})
    assert far.status_code == 200 and far.json()["check_type"] == "field"
    # No position (the phone's location permission refused): turned away, with what to do about it.
    none = clock_in(people[2], {})
    assert none.status_code == 400 and "Allow location access" in none.json()["detail"]
    # A company that does not require location still takes it, as manual.
    assert tenant.put("/api/attendance/settings", json={"require_location": False}).status_code == 200
    manual = clock_in(people[3], {})
    assert manual.status_code == 200 and manual.json()["check_type"] == "manual"


def test_a_radius_is_kept_within_reason(tenant):
    j = job(tenant)
    loc = tenant.put("/api/jobs/%d/site-location" % j["id"],
                     json={"lat": SITE[0], "lng": SITE[1], "radius_m": 99999}).json()
    assert loc["radius_m"] == 5000


def test_another_company_cannot_move_the_site(tenant, second_tenant):
    j = job(tenant)
    res = second_tenant.put("/api/jobs/%d/site-location" % j["id"], json={"lat": SITE[0], "lng": SITE[1]})
    assert res.status_code == 404
