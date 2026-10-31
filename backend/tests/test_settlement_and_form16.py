"""Full and final settlement (gratuity, leave encashment, arrears) and Form 16."""
from datetime import date

import pytest

from app import db as database
from app import models
from app.services import income_tax as it
from app.services import settlement as st
from conftest import make_employee


# --- the rules -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("start,last,expected", [
    (date(2020, 1, 1), date(2025, 6, 30), (5, 5)),      # five and a half years less a day: the part year is not over six months
    (date(2020, 1, 1), date(2025, 7, 15), (5, 6)),      # over six months: counts as a whole year
    (date(2021, 1, 1), date(2025, 12, 31), (4, 5)),
    (date(2020, 2, 29), date(2025, 3, 1), (5, 5)),
])
def test_years_of_service(start, last, expected):
    assert st.years_of_service(start, last) == expected


@pytest.mark.parametrize("last,counted", [(date(2025, 7, 1), 5), (date(2025, 7, 2), 6)])
def test_a_part_year_counts_only_when_it_is_more_than_six_months(last, counted):
    """Joined 1 January 2020: six months past the fifth anniversary is 1 July; the day after is the first that counts."""
    assert st.years_of_service(date(2020, 1, 1), last) == (5, counted)


def test_no_joining_date_is_said_plainly():
    g = st.gratuity(26000, None, date(2025, 3, 31))
    assert not g["eligible"] and "no joining date" in g["reason"]


def test_gratuity_is_fifteen_twenty_sixths_of_basic_a_year():
    g = st.gratuity(26000, date(2018, 4, 1), date(2025, 3, 31))      # seven years
    assert g["eligible"] and g["years_counted"] == 7 and g["amount"] == 15000 * 7


def test_no_gratuity_before_five_completed_years_even_if_rounded_up():
    g = st.gratuity(26000, date(2021, 1, 1), date(2025, 12, 31))     # four years and almost twelve months
    assert not g["eligible"] and g["amount"] == 0 and "after 5 years" in g["reason"]


def test_gratuity_is_capped_at_twenty_lakh():
    assert st.gratuity(500000, date(1990, 1, 1), date(2025, 1, 1))["amount"] == st.GRATUITY_CAP


# --- the settlement --------------------------------------------------------------------------------------------------

@pytest.fixture
def s():
    session = database.SessionLocal()
    yield session
    session.close()


def test_a_full_and_final_settlement(tenant):
    emp = make_employee(tenant, salary=65000.0, tax_rate=0.0, start_date="2018-04-01")
    res = tenant.get("/api/employees/%d/full-and-final" % emp["id"], params={"last_day": "2026-03-13"})
    assert res.status_code == 200, res.text
    f = res.json()
    assert f["last_basic"] == 26000.0, "the structure's Basic, 40% of 65,000"
    assert f["gratuity"]["eligible"] and f["gratuity"]["years_counted"] == 8
    assert f["gratuity"]["amount"] == 15000.0 * 8
    # March 2026: 22 working days, on the books for 10 of them (2 to 13 March).
    assert f["final_month"]["working_days"] == 22 and f["final_month"]["paid_days"] == 10
    assert f["final_month"]["amount"] == round(65000 * 10 / 22, 2)
    assert f["leave"]["day_pay"] == 1000.0 and f["leave"]["amount"] == f["leave"]["unused_days"] * 1000.0
    assert f["total"] == round(sum(p["amount"] for p in f["parts"]), 2)


def test_a_final_month_already_paid_is_not_paid_again(tenant):
    emp = make_employee(tenant, salary=30000.0, start_date="2024-01-01")
    tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-03-01", "period_end": "2026-03-31", "pay_date": "2026-03-31"})
    f = tenant.get("/api/employees/%d/full-and-final" % emp["id"], params={"last_day": "2026-03-13"}).json()
    assert f["final_month"]["amount"] == 0 and f["final_month"]["covered_by"].startswith("PS-")


def test_settlement_needs_a_last_day(tenant):
    emp = make_employee(tenant)
    assert tenant.get("/api/employees/%d/full-and-final" % emp["id"]).status_code == 400


def test_the_settlement_as_a_pdf(tenant):
    emp = make_employee(tenant, salary=30000.0, start_date="2020-01-01")
    res = tenant.get("/api/employees/%d/full-and-final.pdf" % emp["id"], params={"last_day": "2026-03-13"})
    assert res.status_code == 200 and res.content.startswith(b"%PDF")


def test_arrears_after_a_backdated_increment(tenant, s):
    emp = make_employee(tenant, salary=30000.0, tax_rate=0.0)
    for m, end in (("01", "31"), ("02", "28")):
        assert tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-%s-01" % m,
                                                  "period_end": "2026-%s-%s" % (m, end), "pay_date": "2026-%s-%s" % (m, end)}).status_code == 200
    # Entered now, in force from 1 January: both payslips were made at 30,000.
    s.add(models.DBSalaryRevision(client_id=s.query(models.DBEmployee).get(emp["id"]).client_id, employee_id=emp["id"],
                                  old_salary=30000, new_salary=33000, mode="amount", effective_date="2026-01-01",
                                  created_at="2099-01-01 00:00:00"))
    s.query(models.DBEmployee).get(emp["id"]).salary = 33000
    s.commit()
    a = tenant.get("/api/employees/%d/arrears" % emp["id"]).json()
    assert [(r["paid_on_salary"], r["salary_now"], r["amount"]) for r in a["rows"]] == [(30000, 33000, 3000), (30000, 33000, 3000)]
    assert a["total"] == 6000


def test_no_arrears_when_the_increment_was_known_when_the_payslips_were_made(tenant):
    emp = make_employee(tenant, salary=30000.0)
    res = tenant.post("/api/employees/%d/increment" % emp["id"], json={"mode": "amount", "value": 33000, "effective_date": "2026-01-01"})
    assert res.status_code == 200, res.text
    # Made after the increment was entered: paid at 33,000 already, so nothing is owed.
    assert tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-01-01",
                                              "period_end": "2026-01-31", "pay_date": "2026-01-31"}).status_code == 200
    assert tenant.get("/api/employees/%d/arrears" % emp["id"]).json() == {"rows": [], "total": 0.0}


# --- Form 16 ---------------------------------------------------------------------------------------------------------

def year_of_payslips(tenant, emp, months=("2025-04-30", "2025-05-31", "2025-06-30", "2025-07-31")):
    for end in months:
        assert tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": end[:8] + "01",
                                                  "period_end": end, "pay_date": end, "use_structure": False}).status_code == 200


def test_form_16_figures(tenant):
    emp = make_employee(tenant, salary=150000.0, tax_rate=0.0, pan_no="ABCDE1234F")
    year_of_payslips(tenant, emp)
    d = tenant.get("/api/employees/%d/form16" % emp["id"], params={"fy": "2025-26", "format": "json"}).json()
    assert d["fy"] == "2025-26" and d["assessment_year"] == "2026-27" and d["payslips"] == 4
    q = {x["quarter"]: x for x in d["quarters"]}
    assert q["Q1"]["paid"] == 450000 and q["Q2"]["paid"] == 150000 and q["Q3"]["tds"] == 0
    assert d["gross"] == 600000 and d["tds"] == round(sum(x["tds"] for x in d["quarters"]), 2)
    assert d["tax"] == it.annual_tax(600000, 2025)
    assert d["employee"]["pan"] == "ABCDE1234F"


def test_form_16_as_a_pdf_and_for_the_employee(tenant, portal):
    emp = make_employee(tenant, salary=150000.0, tax_rate=0.0, password="EmpPass123")
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    year_of_payslips(tenant, emp, ("2025-04-30",))
    res = tenant.get("/api/employees/%d/form16" % emp["id"], params={"fy": "2025-26"})
    assert res.status_code == 200 and res.content.startswith(b"%PDF")
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    assert portal.get("/api/employee/form16", params={"fy": "2025-26"}).status_code == 404, "a draft is not theirs yet"
    sid = tenant.get("/api/payslips").json()[0]["id"]
    tenant.post("/api/payslips/%d/mark-paid" % sid)
    mine = portal.get("/api/employee/form16", params={"fy": "2025-26"})
    assert mine.status_code == 200 and mine.content.startswith(b"%PDF")


def test_form_16_is_hrs_and_the_masters(tenant, portal):
    emp = make_employee(tenant, password="EmpPass123")
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    for path in ("form16", "full-and-final", "arrears"):
        assert portal.get("/api/employees/%d/%s" % (emp["id"], path)).status_code in (401, 403)


def test_a_settlement_worked_out_before_the_last_day_still_pays_the_final_month(tenant, s):
    """Days that have not come yet are not absences: somebody whose attendance is kept is not shown as unpaid for them."""
    emp = make_employee(tenant, salary=65000.0, start_date="2020-01-01")
    row = s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one()
    s.add(models.DBAttendance(client_id=row.client_id, employee_id=row.id, date="2026-10-01", clock_in="09:00:00", status="completed"))
    s.commit()
    f = tenant.get("/api/employees/%d/full-and-final" % emp["id"], params={"last_day": "2099-12-15"}).json()["final_month"]
    assert f["paid_days"] == f["lop_days"] + f["paid_days"] and f["lop_days"] == 0 and f["paid_days"] > 0
    assert f["amount"] > 0


def test_the_pdfs_print_no_rupee_sign_the_font_cannot_draw(tenant):
    import re
    from app.services import form16
    emp = make_employee(tenant, salary=30000.0, start_date="2020-01-01")
    assert tenant.get("/api/employees/%d/full-and-final.pdf" % emp["id"], params={"last_day": "2026-03-13"}).content.startswith(b"%PDF")
    data = {"fy": "2025-26", "assessment_year": "2026-27", "period": ("2025-04-01", "2026-03-31"),
            "employer": {"name": "X", "address": "", "tan": "", "pan": ""}, "employee": {"name": "Y", "pan": "", "designation": "", "employee_id": ""},
            "quarters": [{"quarter": "Q%d" % i, "months": "m", "paid": 1500000.0, "tds": 1200.0} for i in range(1, 5)], "payslips": 4,
            "gross": 6000000.0, "tds": 4800.0, "balance": 0.0,
            "tax": {"gross": 6000000.0, "standard_deduction": 75000.0, "taxable": 5925000.0, "slab_tax": 1.0, "rebate_87a": 0.0, "surcharge": 0.0, "cess": 0.0, "total_tax": 2.0}}
    assert "₹" not in repr(form16.pdf_spec(data)) and re.search(r"60,00,000", repr(form16.pdf_spec(data)))


def test_the_missing_details_message_reads_properly_for_one_person_and_for_many(tenant):
    a = make_employee(tenant, salary=18000.0, first_name="Ravi", last_name="One")
    tenant.put("/api/employees/%d" % a["id"], json={"bank_account": "1"})
    tenant.post("/api/payslips", json={"employee_id": a["id"], "period_start": "2026-02-01", "period_end": "2026-02-28", "pay_date": "2026-02-28"})
    one = tenant.get("/api/payroll/exports/neft", params={"month": "2026-02"}).json()["detail"]
    assert one.startswith("1 person cannot go in the file")
    b = make_employee(tenant, salary=18000.0, first_name="Ravi", last_name="Two")
    tenant.put("/api/employees/%d" % b["id"], json={"bank_account": "2"})
    tenant.post("/api/payslips", json={"employee_id": b["id"], "period_start": "2026-02-01", "period_end": "2026-02-28", "pay_date": "2026-02-28"})
    assert tenant.get("/api/payroll/exports/neft", params={"month": "2026-02"}).json()["detail"].startswith("2 people cannot go in the file")
