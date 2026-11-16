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
    res = get(tenant, "neft", pay_on="2026-08-31")
    assert res.status_code == 200, res.text
    rows = sheet_rows(res)
    # With no bank chosen it is the plain sheet of the payment files, in the same columns.
    assert rows[0] == ["Beneficiary Name", "Account No", "IFSC", "Bank", "Amount", "Mode", "Date", "Reference", "Email"]
    assert rows[1][:3] == ["Ravi Kumar18000", "501001234567", "HDFC0001234"] and rows[1][4] == slip["net_pay"]
    assert rows[1][5] == "NEFT" and rows[1][6] == "2026-08-31" and rows[1][7] == "SAL-2026-08 %s" % slip["number"]
    assert res.headers["X-Rows-Left-Out"] == "0"


def test_neft_as_csv(tenant):
    person(tenant, 18000, **FULL)
    res = get(tenant, "neft", format="csv")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows[1][1] == "501001234567" and rows[1][2] == "HDFC0001234"


def bank_rows(res):
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv") and res.headers["content-disposition"].endswith('.csv"')
    return list(csv.reader(io.StringIO(res.content.decode("utf-8"))))


def our_account(tenant, ifsc="HDFC0000999"):
    res = tenant.post("/api/bank-accounts", json={"name": "Salary account", "kind": "Bank", "account_no": "50100999888", "ifsc": ifsc,
                                                  "opening_balance": 0, "opening_date": "2026-01-01"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_each_bank_gets_its_own_layout_and_a_transfer_within_the_bank_goes_as_one(tenant):
    _, slip = person(tenant, 18000, **FULL)                      # HDFC account
    person(tenant, 20000, bank_account="9988776655", bank_ifsc="SBIN0001234")
    acc = our_account(tenant)
    net = "%.2f" % slip["net_pay"]

    rows = bank_rows(get(tenant, "neft", bank="hdfc", account_id=acc, pay_on="2026-08-31"))
    assert len(rows) == 2 and all(len(r) == 28 for r in rows), "Enet: no header, 28 fields"
    mine = next(r for r in rows if r[2] == "501001234567")
    assert mine[0] == "I" and mine[3] == net and mine[4] == "Ravi Kumar18000", "same bank: a transfer within HDFC"
    assert next(r for r in rows if r[2] == "9988776655")[0] == "N"

    rows = bank_rows(get(tenant, "neft", bank="icici", account_id=acc, pay_on="2026-08-31"))
    assert rows[0][0] == "Debit Ac No" and rows[1][0] == "50100999888" and rows[1][-1].startswith("SAL-2026-08 PS-")

    rows = bank_rows(get(tenant, "neft", bank="sbi"))
    assert rows[0][:4] == ["Beneficiary Name", "Beneficiary Account No", "IFSC", "Amount"] and rows[1][4] == "NEFT"

    rows = bank_rows(get(tenant, "neft", bank="axis", account_id=acc, pay_on="2026-08-31"))
    assert rows[0][0] == "Payment Mode" and rows[1][2] == "31-08-2026" and rows[1][6] == "50100999888"
    assert rows[1][7] == "SAL-2026-08"


def test_a_big_salary_goes_by_rtgs(tenant):
    person(tenant, 400000, bank_account="9988776655", bank_ifsc="SBIN0001234")
    rows = bank_rows(get(tenant, "neft", bank="sbi"))
    assert rows[1][4] == "RTGS"


def test_the_bank_file_needs_a_known_layout_and_the_account_the_bank_names(tenant):
    person(tenant, 18000, **FULL)
    assert get(tenant, "neft", bank="nosuchbank").status_code == 400
    res = get(tenant, "neft", bank="icici")
    assert res.status_code == 400 and "choose it" in res.json()["detail"]
    assert get(tenant, "neft", bank="axis", account_id=99999).status_code == 400
    assert get(tenant, "neft", bank="sbi", pay_on="31/08/2026").status_code == 400


def test_neft_names_whoever_has_no_bank_details_and_leaves_them_out_only_when_told(tenant):
    person(tenant, 18000, **FULL)
    person(tenant, 20000, bank_account="123456")                     # no IFSC
    res = get(tenant, "neft")
    assert res.status_code == 400 and "Ravi Kumar20000 (no IFSC)" in res.json()["detail"]
    res = get(tenant, "neft", allow_incomplete="true")
    assert res.status_code == 200 and len(sheet_rows(res)) == 2 and res.headers["X-Rows-Left-Out"] == "1"
    res = get(tenant, "neft", bank="sbi")
    assert res.status_code == 400 and "Ravi Kumar20000 (no IFSC)" in res.json()["detail"]
    res = get(tenant, "neft", bank="sbi", allow_incomplete="true")
    assert len(bank_rows(res)) == 2 and res.headers["X-Rows-Left-Out"] == "1"


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
