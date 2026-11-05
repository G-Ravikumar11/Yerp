"""Job Lock: staff clock in only at the office or a site they are assigned to, and the server decides, not the phone."""
from conftest import make_employee

PASSWORD = "Crew1234"
SITE = (17.4239, 78.3413)          # Tellapur
OTHER = (17.4500, 78.3800)         # Kokapet, a few km off
HOME = (16.5062, 80.6480)          # Vijayawada


def project(tenant, name, at=None, radius=300):
    j = tenant.post("/api/jobs", json={"name": name, "customer_name": "Kokapet LLP"}).json()
    jid = j.get("id") or j["job"]["id"]
    if at:
        res = tenant.put("/api/jobs/%d/site-location" % jid, json={"lat": at[0], "lng": at[1], "radius_m": radius})
        assert res.status_code == 200, res.text
    return jid


def staff_on(tenant, browser, sites):
    e = make_employee(tenant, permission_role="staff", password=PASSWORD, site_ids=sites, emergency_contact="Asha", emergency_phone="9999999999")
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    assert browser.post("/api/employee/auth/login", json={"email": e["email"], "password": PASSWORD}).status_code == 200
    return e


def clock_in(browser, at=None, accuracy=20, **extra):
    body = {"device_info": "test", **extra}
    if at:
        body.update(latitude=at[0], longitude=at[1])
    if accuracy is not None:
        body["accuracy"] = accuracy
    return browser.post("/api/employee/attendance/clock-in", json=body)


def test_clocking_in_from_home_is_refused_and_hr_sees_it(tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    e = staff_on(tenant, portal, [site])
    res = clock_in(portal, HOME)
    assert res.status_code == 403 and "km from" in res.json()["detail"]
    got = tenant.get("/api/attendance/job-lock").json()
    row = got["refused"][0]
    assert e["first_name"] in row["employee"] and row["distance_m"] > 100000 and row["lat"] == HOME[0]


def test_on_their_own_site_it_goes_through_and_is_tagged_to_it(tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    staff_on(tenant, portal, [site])
    res = clock_in(portal, SITE)
    assert res.status_code == 200, res.text
    assert res.json()["site"]["job_id"] == site and res.json()["check_type"] == "site"


def test_allow_remote_no_longer_opens_the_lock(tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    assert tenant.put("/api/attendance/settings", json={"allow_remote": True}).status_code == 200
    staff_on(tenant, portal, [site])
    assert clock_in(portal, HOME).status_code == 403


def test_another_site_is_not_their_site(tenant, portal):
    mine = project(tenant, "Tellapur Towers", SITE)
    project(tenant, "Kokapet Heights", OTHER)
    staff_on(tenant, portal, [mine])
    res = clock_in(portal, OTHER)
    assert res.status_code == 403 and "not one of your sites" in res.json()["detail"]


def test_no_location_and_weak_gps_are_refused(tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    staff_on(tenant, portal, [site])
    assert "location is needed" in clock_in(portal).json()["detail"]
    weak = clock_in(portal, SITE, accuracy=1200)
    assert weak.status_code == 403 and "Step outside" in weak.json()["detail"]


def test_a_person_on_no_particular_site_may_use_any_site(tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    staff_on(tenant, portal, [])
    assert clock_in(portal, HOME).status_code == 403
    assert clock_in(portal, SITE).json()["site"]["job_id"] == site


def test_field_staff_let_off_the_lock_clock_in_anywhere(tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    e = staff_on(tenant, portal, [site])
    assert tenant.put("/api/attendance/job-lock/exempt/%d" % e["id"], json={"exempt": True}).status_code == 200
    assert clock_in(portal, HOME).status_code == 200


def test_lock_switched_off_goes_back_to_the_old_rules(tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    assert tenant.put("/api/attendance/settings", json={"job_lock": False}).status_code == 200
    staff_on(tenant, portal, [site])
    assert clock_in(portal, HOME).status_code == 200


def test_a_site_with_no_location_does_not_lock_its_people_out_but_is_flagged(tenant, portal):
    project(tenant, "Fenced", SITE)
    bare = project(tenant, "Not set yet")
    staff_on(tenant, portal, [bare])
    assert clock_in(portal, HOME).status_code == 200
    got = tenant.get("/api/attendance/job-lock").json()
    assert any("Not set yet" in s["name"] for s in got["sites_without_location"])
    assert "location set" in got["flagged"][0]["flag"]


def test_a_company_with_no_locations_at_all_is_not_locked_out(tenant, portal):
    site = project(tenant, "Not set yet")
    staff_on(tenant, portal, [site])
    assert clock_in(portal, HOME).status_code == 200


def test_too_perfect_gps_is_flagged(tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    staff_on(tenant, portal, [site])
    assert clock_in(portal, SITE, accuracy=0.5).status_code == 200
    assert "too perfect" in tenant.get("/api/attendance/job-lock").json()["flagged"][0]["flag"]


def test_one_phone_for_two_people_on_a_day_is_named(tenant, portal):
    from datetime import datetime
    from app import models
    from app.db import SessionLocal
    from app.services.employee_portal import same_device_flag
    site = project(tenant, "Tellapur Towers", SITE)
    e = staff_on(tenant, portal, [site])
    assert clock_in(portal, SITE, device_id="phone-1").status_code == 200
    db = SessionLocal()
    try:
        row = db.query(models.DBAttendance).filter(models.DBAttendance.employee_id == e["id"]).first()
        today = datetime.now().strftime("%Y-%m-%d")
        assert row.device_id == "phone-1"
        assert e["first_name"] in same_device_flag(db, row.client_id, e["id"] + 1, "phone-1", today)
        assert same_device_flag(db, row.client_id, e["id"], "phone-1", today) == ""      # their own phone
    finally:
        db.close()


def test_a_phone_cannot_say_where_it_is_calling_from(tenant, portal):
    from app import models
    from app.db import SessionLocal
    site = project(tenant, "Tellapur Towers", SITE)
    e = staff_on(tenant, portal, [site])
    assert clock_in(portal, SITE, ip_address="1.2.3.4").status_code == 200
    db = SessionLocal()
    try:
        assert db.query(models.DBAttendance).filter(models.DBAttendance.employee_id == e["id"]).first().ip_address != "1.2.3.4"
    finally:
        db.close()


def test_clocking_out_away_from_site_is_never_refused_but_is_flagged(tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    staff_on(tenant, portal, [site])
    assert clock_in(portal, SITE).status_code == 200
    res = portal.post("/api/employee/attendance/clock-out", json={"latitude": HOME[0], "longitude": HOME[1]})
    assert res.status_code == 200, res.text
    assert "Clocked out" in tenant.get("/api/attendance/job-lock").json()["flagged"][0]["flag"]


def test_another_company_sees_none_of_it(tenant, second_tenant, portal):
    site = project(tenant, "Tellapur Towers", SITE)
    staff_on(tenant, portal, [site])
    clock_in(portal, HOME)
    assert second_tenant.get("/api/attendance/job-lock").json()["refused"] == []
