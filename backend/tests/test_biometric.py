"""Attendance from the biometric machines: the office program sends punches with a key, each is kept once, matched to its
person by employee code or the number HR set, and the day's clock-in and clock-out are worked out from them."""
from datetime import date, datetime, timedelta

from conftest import make_employee
from test_payment_approval import person

# Yesterday: a punch later than the clock on the wall is refused, and a test may run in the morning.
TODAY = (date.today() - timedelta(days=1)).isoformat()


def at(hhmm, day=TODAY):
    return "%s %s:00" % (day, hhmm)


def key_for(tenant):
    res = tenant.post("/api/biometric/key")
    assert res.status_code == 200, res.text
    return res.json()["key"]


def send(tenant, key, punches, **kw):
    return tenant.post("/api/biometric/punches", json={"punches": punches, "agent": "test"}, headers={"X-Biometric-Key": key}, **kw)


def day_of(tenant, emp_id, day=TODAY):
    from app import db as database, models
    with database.SessionLocal() as s:
        r = s.query(models.DBAttendance).filter(models.DBAttendance.employee_id == emp_id, models.DBAttendance.date == day).first()
        return None if r is None else {"clock_in": r.clock_in or "", "clock_out": r.clock_out or "", "check_type": r.check_type,
                                       "total_hours": r.total_hours, "job_id": r.job_id, "location_label": r.location_label}


def coded(tenant, code, **kw):
    """An employee whose employee code is `code` - what a punch is matched on when HR has set no other number."""
    from app import db as database, models
    emp = make_employee(tenant, **kw)
    with database.SessionLocal() as s:
        s.get(models.DBEmployee, emp["id"]).employee_id = code
        s.commit()
    return emp


def test_punches_need_the_key_and_only_the_master_makes_one(tenant):
    assert tenant.post("/api/biometric/punches", json={"punches": []}).status_code == 401
    assert send(tenant, "ybio_1_" + "x" * 40, []).status_code == 401
    hr = person(tenant, role="hr")
    try:
        assert hr.post("/api/biometric/key").status_code == 403
    finally:
        hr.__exit__(None, None, None)
    key = key_for(tenant)
    assert tenant.get("/api/biometric/ping", headers={"X-Biometric-Key": key}).json()["ok"] is True
    newer = key_for(tenant)
    assert send(tenant, key, []).status_code == 401                 # the old key stops working
    assert send(tenant, newer, []).status_code == 200


def test_a_day_is_the_first_punch_in_and_the_last_out(tenant):
    key = key_for(tenant)
    emp = make_employee(tenant)
    assert tenant.put("/api/biometric/employees/%d" % emp["id"], json={"biometric_id": "0045"}).status_code == 200
    res = send(tenant, key, [{"employee_code": "45", "time": at("09:02"), "device": "3"}])
    assert res.status_code == 200, res.text
    assert res.json()["new"] == 1 and res.json()["unmatched"] == []
    d = day_of(tenant, emp["id"])
    assert d["clock_in"] == "09:02:00" and not d["clock_out"] and d["check_type"] == "biometric"       # inside
    send(tenant, key, [{"employee_code": "45", "time": at("13:00"), "device": "3"},
                       {"employee_code": "45", "time": at("13:00") [:-2] + "20", "device": "3"}])           # pressed twice
    d = day_of(tenant, emp["id"])
    assert d["clock_out"] == "13:00:00" and d["total_hours"] == 3.97
    send(tenant, key, [{"employee_code": "45", "time": at("13:45"), "device": "3"}])                       # back from lunch
    assert not day_of(tenant, emp["id"])["clock_out"]
    send(tenant, key, [{"employee_code": "45", "time": at("18:02"), "device": "3"}])
    d = day_of(tenant, emp["id"])
    assert d["clock_in"] == "09:02:00" and d["clock_out"] == "18:02:00" and d["total_hours"] == 9.0
    # The same punches sent again change nothing.
    again = send(tenant, key, [{"employee_code": "45", "time": at("18:02"), "device": "3"}]).json()
    assert again["new"] == 0 and again["duplicates"] == 1


def test_the_machine_s_own_in_and_out_are_believed(tenant):
    key = key_for(tenant)
    emp = coded(tenant, "E-77")
    send(tenant, key, [{"employee_code": "e-77", "time": at("08:55"), "direction": "in"},
                       {"employee_code": "E-77", "time": at("12:10"), "direction": "in"},
                       {"employee_code": "E-77", "time": at("12:40"), "direction": "in"}])
    assert not day_of(tenant, emp["id"])["clock_out"]                  # three "in"s: still inside
    send(tenant, key, [{"employee_code": "E-77", "time": at("17:30"), "direction": "out"}])
    assert day_of(tenant, emp["id"])["clock_out"] == "17:30:00"


def test_a_punch_for_nobody_waits_and_counts_once_the_number_is_set(tenant):
    key = key_for(tenant)
    emp = make_employee(tenant)
    res = send(tenant, key, [{"employee_code": "912", "time": at("09:10"), "device": "A"},
                             {"employee_code": "912", "time": at("17:40"), "device": "A"},
                             {"employee_code": "", "time": at("09:00")}, {"employee_code": "5", "time": "not a time"},
                             {"employee_code": "5", "time": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")}]).json()
    assert res["unmatched"] == ["912"] and res["new"] == 2 and res["refused"] == 3
    assert day_of(tenant, emp["id"]) is None
    st = tenant.get("/api/biometric/status").json()
    assert st["unmatched"][0]["biometric_id"] == "912" and st["unmatched"][0]["punches"] == 2 and st["connected"] is True
    done = tenant.put("/api/biometric/employees/%d" % emp["id"], json={"biometric_id": "912"})
    assert done.status_code == 200 and done.json()["matched"] == 2
    d = day_of(tenant, emp["id"])
    assert d["clock_in"] == "09:10:00" and d["clock_out"] == "17:40:00"
    other = make_employee(tenant)
    assert tenant.put("/api/biometric/employees/%d" % other["id"], json={"biometric_id": "0912"}).status_code == 409


def test_a_machine_put_on_a_site_gives_the_day_that_site(tenant):
    key = key_for(tenant)
    emp = coded(tenant, "S9")
    job = tenant.post("/api/jobs", json={"name": "Vizag Bypass"}).json()
    send(tenant, key, [{"employee_code": "S9", "time": at("07:00", (date.today() - timedelta(days=2)).isoformat()), "device": "GATE-1"}])
    [dev] = tenant.get("/api/biometric/status").json()["devices"]
    assert dev["device_code"] == "GATE-1"
    assert tenant.put("/api/biometric/devices/%d" % dev["id"], json={"name": "Site gate", "job_id": job["id"]}).status_code == 200
    send(tenant, key, [{"employee_code": "S9", "time": at("09:00"), "device": "GATE-1"}])
    d = day_of(tenant, emp["id"])
    assert d["job_id"] == job["id"] and d["location_label"] == "Site gate"


def test_one_company_s_key_reaches_only_its_own_people(tenant, second_tenant):
    key = key_for(tenant)
    theirs = coded(second_tenant, "X1")
    res = send(tenant, key, [{"employee_code": "X1", "time": at("09:00")}]).json()
    assert res["unmatched"] == ["X1"]
    assert day_of(second_tenant, theirs["id"]) is None


# --- easier set-up ----------------------------------------------------------------------------------------------------------

def test_the_master_downloads_a_set_up_package_with_the_key_already_in_it(tenant):
    import io
    import zipfile
    hr = person(tenant, role="hr")
    try:
        assert hr.post("/api/biometric/setup-package").status_code == 403
    finally:
        hr.__exit__(None, None, None)
    res = tenant.post("/api/biometric/setup-package")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(res.content))
    names = set(z.namelist())
    assert {"biometric_sync/YerpBiometric.cs", "biometric_sync/build.bat", "biometric_sync/SETUP.bat", "biometric_sync/config.ini",
            "biometric_sync/START HERE.txt"} <= names
    assert not any(n.endswith((".py", ".ps1", ".exe")) for n in names), "nothing to download or trust beyond the source and batch files"
    config = z.read("biometric_sync/config.ini").decode()
    key = [l.split("=", 1)[1].strip() for l in config.splitlines() if l.startswith("api_key")][0]
    assert key.startswith("ybio_") and "url = http" in config
    assert tenant.get("/api/biometric/ping", headers={"X-Biometric-Key": key}).json()["ok"] is True      # the key in it works
    assert b"\r\n" in z.read("biometric_sync/SETUP.bat")                                                   # Windows line ends
    assert key_for(tenant) != key and tenant.get("/api/biometric/ping", headers={"X-Biometric-Key": key}).status_code == 401


def test_a_machine_s_name_for_somebody_suggests_who_a_number_is(tenant):
    key = key_for(tenant)
    ravi = make_employee(tenant, first_name="Ravi", last_name="Kumar")
    sita = make_employee(tenant, first_name="Sita", last_name="Rao")
    make_employee(tenant, first_name="Anil", last_name="Kumar")
    send(tenant, key, [{"employee_code": "701", "employee_name": "RAVI KUMAR", "time": at("09:00"), "device": "A"},
                       {"employee_code": "702", "employee_name": "Rao Sita", "time": at("09:01"), "device": "A"},
                       {"employee_code": "703", "employee_name": "Kumar", "time": at("09:02"), "device": "A"},       # too little to go on
                       {"employee_code": "704", "employee_name": "Nobody Here", "time": at("09:03"), "device": "A"}])
    st = {u["biometric_id"]: u for u in tenant.get("/api/biometric/status").json()["unmatched"]}
    assert st["701"]["name"] == "RAVI KUMAR" and st["701"]["suggestion"]["id"] == ravi["id"]
    assert st["702"]["suggestion"]["id"] == sita["id"]                                                           # any order of words
    assert st["703"]["suggestion"] is None and st["704"]["suggestion"] is None
    done = tenant.put("/api/biometric/employees/%d" % ravi["id"], json={"biometric_id": "701"})          # one click on "Match"
    assert done.status_code == 200 and done.json()["matched"] == 1
    assert "701" not in {u["biometric_id"] for u in tenant.get("/api/biometric/status").json()["unmatched"]}


def test_two_people_who_could_be_the_one_get_no_suggestion():
    from app.services.biometric import suggest_person
    people = [(1, "Ravi Kumar Reddy"), (2, "Ravi Kumar Naidu"), (3, "Sita Rao")]
    assert suggest_person(people, "Ravi Kumar") is None
    assert suggest_person(people, "Ravi Kumar Naidu")["id"] == 2
    assert suggest_person(people, "sita rao")["id"] == 3
    assert suggest_person(people, "") is None and suggest_person([], "Sita Rao") is None
