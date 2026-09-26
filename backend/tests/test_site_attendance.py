"""A clock-in on a project's site is tagged to that project; one outside
every site says so. The office was the only place anybody was checked
against."""
from conftest import make_employee

SITE = (17.4239, 78.3413)          # Kokapet
NEAR = (17.4251, 78.3420)          # about 150 m away
FAR = (17.4486, 78.3908)           # Hitec City, 5 km off


def job(tenant):
    return tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()


def staff_in(tenant, client, lat, lng):
    tenant.put("/api/attendance/settings", json={"auto_clock_in": False})
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


def test_a_radius_is_kept_within_reason(tenant):
    j = job(tenant)
    loc = tenant.put("/api/jobs/%d/site-location" % j["id"],
                     json={"lat": SITE[0], "lng": SITE[1], "radius_m": 99999}).json()
    assert loc["radius_m"] == 5000


def test_another_company_cannot_move_the_site(tenant, second_tenant):
    j = job(tenant)
    res = second_tenant.put("/api/jobs/%d/site-location" % j["id"], json={"lat": SITE[0], "lng": SITE[1]})
    assert res.status_code == 404
