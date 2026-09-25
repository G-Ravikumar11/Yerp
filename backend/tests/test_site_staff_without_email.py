"""A mason or an operator is on the payroll without ever signing in, and
often has no email. Only somebody given a login needs one."""


def test_site_staff_can_be_added_without_an_email(tenant):
    res = tenant.post("/api/employees", json={"first_name": "Ramaiah", "last_name": "K",
                                               "job_title": "Mason", "salary": 18000})
    assert res.status_code == 200, res.text
    res = tenant.post("/api/employees", json={"first_name": "Suresh", "last_name": "B",
                                               "job_title": "Operator", "email": ""})
    assert res.status_code == 200, "two without an email are not duplicates of each other"


def test_a_login_still_needs_an_email(tenant):
    res = tenant.post("/api/employees", json={"first_name": "Anil", "last_name": "P",
                                               "password": "Passw0rdTest"})
    assert res.status_code == 400 and "email" in res.json()["detail"].lower()


def test_nobody_signs_in_with_a_blank_email(tenant, client):
    tenant.post("/api/employees", json={"first_name": "Ramaiah", "last_name": "K"})
    res = client.post("/api/employee/auth/login", json={"email": "", "password": ""})
    assert res.status_code in (400, 401)


def test_they_are_paid_like_anyone_else(tenant):
    tenant.post("/api/employees", json={"first_name": "Ramaiah", "last_name": "K",
                                        "job_title": "Mason", "salary": 216000,
                                        "pay_frequency": "monthly"})
    res = tenant.post("/api/payroll/run", json={"period_start": "2026-09-01",
                                                "period_end": "2026-09-30",
                                                "pay_date": "2026-10-01"})
    assert res.status_code == 200, res.text
    assert len(res.json()["created"]) == 1
