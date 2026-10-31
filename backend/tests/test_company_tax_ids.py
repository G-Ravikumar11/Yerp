"""The company's TAN and PAN: checked when saved, and printed on Form 16."""
from conftest import make_employee


def test_a_valid_tan_and_pan_are_saved_in_capitals_without_spaces(tenant):
    res = tenant.post("/api/settings", json={"company_tan": "hyde 12345 a", "company_pan": "abcde1234f"})
    assert res.status_code == 200, res.text
    saved = {k: v for k, v in tenant.get("/api/settings").json().items() if k in ("company_tan", "company_pan")}
    assert saved == {"company_tan": "HYDE12345A", "company_pan": "ABCDE1234F"}


def test_a_malformed_tan_or_pan_is_refused_and_nothing_is_saved(tenant):
    assert tenant.post("/api/settings", json={"company_tan": "HYDE1234"}).status_code == 400
    assert tenant.post("/api/settings", json={"company_pan": "ABCDE12345"}).status_code == 400
    assert "company_tan" not in tenant.get("/api/settings").json() or tenant.get("/api/settings").json()["company_tan"] == ""


def test_clearing_them_is_allowed(tenant):
    tenant.post("/api/settings", json={"company_tan": "HYDE12345A"})
    assert tenant.post("/api/settings", json={"company_tan": ""}).status_code == 200


def test_form_16_carries_the_companys_tan_and_pan(tenant):
    tenant.post("/api/settings", json={"company_tan": "HYDE12345A", "company_pan": "ABCDE1234F"})
    emp = make_employee(tenant, salary=150000.0, tax_rate=0.0)
    assert tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2025-04-01", "period_end": "2025-04-30",
                                              "pay_date": "2025-04-30", "use_structure": False}).status_code == 200
    d = tenant.get("/api/employees/%d/form16" % emp["id"], params={"fy": "2025-26", "format": "json"}).json()
    assert d["employer"]["tan"] == "HYDE12345A" and d["employer"]["pan"] == "ABCDE1234F"


def test_form_16_for_a_year_with_no_payslips_is_not_found(tenant):
    emp = make_employee(tenant)
    assert tenant.get("/api/employees/%d/form16" % emp["id"], params={"fy": "2019-20"}).status_code == 404
    assert tenant.get("/api/employees/%d/form16" % emp["id"], params={"fy": "banana"}).status_code == 400
