"""The month's files for the bank (NEFT), EPFO (ECR 2.0) and ESIC."""
import csv
import io

import openpyxl

from conftest import make_employee

MONTH = "2026-08"
SLIP = {"period_start": "2026-08-01", "period_end": "2026-08-31", "pay_date": "2026-08-31"}


def person(tenant, salary, **details):
    emp = make_employee(tenant, salary=salary, tax_rate=0.0, first_name="Ravi", last_name="Kumar%d" % int(salary))
    if details:
        res = tenant.put("/api/employees/%d" % emp["id"], json=details)
        assert res.status_code == 200, res.text
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], **SLIP})
    assert res.status_code == 200, res.text
    return emp, tenant.get("/api/payslips/%d" % res.json()["id"]).json()


FULL = {"bank_account": "5010 0123 4567", "bank_ifsc": "HDFC0001234", "uan_no": "100200300400", "esi_no": "3112345678"}


def sheet_rows(res):
    book = openpyxl.load_workbook(io.BytesIO(res.content))
    return [list(r) for r in book.active.iter_rows(values_only=True) if any(c is not None for c in r)]


def get(tenant, kind, **params):
    return tenant.get("/api/payroll/exports/" + kind, params={"month": MONTH, **params})


# --- NEFT ------------------------------------------------------------------------------------------------------------

def test_neft_has_a_row_per_person_with_net_pay_and_the_narration(tenant):
    _, slip = person(tenant, 18000, **FULL)
    res = get(tenant, "neft")
    assert res.status_code == 200, res.text
    rows = sheet_rows(res)
    assert rows[0] == ["Beneficiary Account No", "Beneficiary Name", "IFSC Code", "Amount", "Transaction Reference / Narration"]
    assert rows[1] == ["501001234567", "Ravi Kumar18000", "HDFC0001234", slip["net_pay"], "Salary for August 2026"]
    assert res.headers["X-Rows-Left-Out"] == "0"


def test_neft_as_csv(tenant):
    person(tenant, 18000, **FULL)
    res = get(tenant, "neft", format="csv")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows[1][0] == "501001234567" and rows[1][2] == "HDFC0001234"


def test_neft_names_whoever_has_no_bank_details_and_leaves_them_out_only_when_told(tenant):
    person(tenant, 18000, **FULL)
    person(tenant, 20000, bank_account="123456")                     # no IFSC
    res = get(tenant, "neft")
    assert res.status_code == 400 and "Ravi Kumar20000 (no IFSC)" in res.json()["detail"]
    res = get(tenant, "neft", allow_incomplete="true")
    assert res.status_code == 200 and len(sheet_rows(res)) == 2 and res.headers["X-Rows-Left-Out"] == "1"


# --- ECR -------------------------------------------------------------------------------------------------------------

def ecr_lines(res, sep="#~#"):
    assert res.status_code == 200, res.text
    return [line.split(sep) for line in res.content.decode().split("\r\n") if line]


def test_ecr_line_under_the_wage_ceiling(tenant):
    # 18,000 salary: Basic 7,200 (40%), gross 12,600; PF 864, EPS 600 (8.33% = 599.76), difference 264.
    person(tenant, 18000, **FULL)
    assert ecr_lines(get(tenant, "ecr")) == [
        ["100200300400", "RAVI KUMAR", "12600", "7200", "7200", "7200", "864", "600", "264", "0", "0"]]


def test_ecr_caps_the_wages_and_the_pension_and_still_adds_up(tenant):
    # 60,000 salary: Basic 24,000, so PF wages stop at 15,000; EPS 1,250 at most; EPS + difference = 1,800 exactly.
    person(tenant, 60000, **FULL)
    line = ecr_lines(get(tenant, "ecr"))[0]
    assert line[3:9] == ["15000", "15000", "15000", "1800", "1250", "550"]
    assert int(line[7]) + int(line[8]) == int(line[6])


def test_ecr_with_pipes_when_asked(tenant):
    person(tenant, 18000, **FULL)
    assert ecr_lines(get(tenant, "ecr", sep="pipe"), "|")[0][0] == "100200300400"


def test_ecr_leaves_out_people_without_pf_and_names_those_without_a_uan(tenant):
    person(tenant, 18000, **FULL)
    person(tenant, 19000, pf_enabled=False, **{k: v for k, v in FULL.items() if k != "uan_no"})   # no PF: not a member line
    person(tenant, 20000, bank_account="1", bank_ifsc="HDFC0001234")                              # PF but no UAN
    res = get(tenant, "ecr")
    assert res.status_code == 400 and "no 12-digit UAN" in res.json()["detail"] and "19000" not in res.json()["detail"]
    assert len(ecr_lines(get(tenant, "ecr", allow_incomplete="true"))) == 1


def test_ecr_carries_loss_of_pay_as_ncp_days(tenant):
    emp = make_employee(tenant, salary=18000.0, tax_rate=0.0, start_date="2026-08-17")
    tenant.put("/api/employees/%d" % emp["id"], json={"uan_no": "100200300401"})
    tenant.post("/api/payslips", json={"employee_id": emp["id"], **SLIP})
    line = ecr_lines(get(tenant, "ecr"))[0]
    assert line[0] == "100200300401" and line[9] == "0", "days before joining are not NCP days"


# --- ESIC ------------------------------------------------------------------------------------------------------------

def test_esic_has_each_insured_person_with_days_wages_and_both_shares(tenant):
    _, slip = person(tenant, 18000, **FULL)
    rows = sheet_rows(get(tenant, "esic"))
    assert rows[0][0] == "IP Number" and rows[0][4:] == ["Employee Contribution", "Employer Contribution"]
    assert rows[1] == ["3112345678", "Ravi Kumar18000", 21, 12600, 94.5, 409.5]   # August 2026: 21 working days


def test_esic_skips_people_over_the_limit_and_names_those_without_an_ip_number(tenant):
    person(tenant, 18000, **FULL)
    person(tenant, 60000, **FULL)                                     # gross 42,000: not insured
    person(tenant, 19000, bank_account="1", bank_ifsc="HDFC0001234")  # insured, no IP number
    res = get(tenant, "esic")
    assert res.status_code == 400 and "no 10-digit ESI (IP) number" in res.json()["detail"]
    rows = sheet_rows(get(tenant, "esic", allow_incomplete="true"))
    assert [r[1] for r in rows[1:]] == ["Ravi Kumar18000"]


# --- all three -------------------------------------------------------------------------------------------------------

def test_a_month_without_payslips_or_a_bad_month(tenant):
    for kind in ("neft", "ecr", "esic"):
        assert get(tenant, kind).status_code == 404
        assert tenant.get("/api/payroll/exports/" + kind, params={"month": "Aug"}).status_code == 400


def test_the_files_are_hr_and_the_masters(tenant, portal):
    person(tenant, 18000, **FULL)
    plain = make_employee(tenant, password="EmpPass123")
    tenant.put("/api/employees/%d" % plain["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": plain["email"], "password": "EmpPass123"})
    for kind in ("neft", "ecr", "esic"):
        assert portal.get("/api/payroll/exports/" + kind, params={"month": MONTH}).status_code in (401, 403)


def test_one_company_cannot_download_anothers_files(tenant, second_tenant):
    person(tenant, 18000, **FULL)
    for kind in ("neft", "ecr", "esic"):
        assert second_tenant.get("/api/payroll/exports/" + kind, params={"month": MONTH}).status_code == 404
