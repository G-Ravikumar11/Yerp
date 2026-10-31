"""New-regime income tax and the monthly TDS spread over the financial year."""
import pytest

from app.services import income_tax as it
from conftest import make_employee


@pytest.mark.parametrize("gross,expected", [
    (475000, 0),                # taxable 4,00,000: the nil slab
    (1275000, 0),               # taxable 12,00,000: the slab tax of 60,000 is all rebated under 87A
    (1285000, 10400),           # taxable 12,10,000: marginal relief - no more than the 10,000 over 12 lakh, plus 4% cess
    (1675000, 124800),          # taxable 16,00,000: 1,20,000 slab tax plus cess, no rebate
    (2475000, 312000),          # taxable 24,00,000: 3,00,000 plus cess
])
def test_the_years_tax(gross, expected):
    assert it.annual_tax(gross, 2025)["total_tax"] == expected


def test_the_steps_are_shown_for_form_16():
    t = it.annual_tax(1675000, 2025)
    assert (t["standard_deduction"], t["taxable"], t["slab_tax"], t["rebate_87a"], t["cess"]) == (75000, 1600000, 120000, 0, 4800)


def test_surcharge_above_fifty_lakh():
    t = it.annual_tax(6075000, 2025)                  # taxable 60 lakh
    assert t["surcharge"] == round(t["slab_tax"] * 0.10, 2)


def test_the_financial_year():
    assert (it.fy_start_year("2026-03-31"), it.fy_start_year("2026-04-01")) == (2025, 2026)
    assert it.fy_label(2025) == "2025-26"
    assert [it.months_left(m) for m in ("2025-04-30", "2025-10-31", "2026-03-31")] == [12, 6, 1]


def test_a_later_year_uses_the_latest_slabs_until_told_otherwise():
    assert it.slabs_for(2030) is it.SLABS[max(it.SLABS)]


def test_monthly_tds_spreads_the_year_and_catches_up():
    # 1,50,000 a month from April: 18 lakh for the year, taxable 17,25,000.
    year_tax = it.annual_tax(1800000, 2025)["total_tax"]
    april = it.tds_for_month(0, 0, 150000, 0, "2025-04-30")
    assert april == round(year_tax / 12, 2)
    # Half the year gone with nothing deducted: the rest is spread over the six months left.
    october = it.tds_for_month(900000, 0, 150000, 0, "2025-10-31")
    assert october == round(year_tax / 6, 2)
    # A one-off bonus is taxed in its month, not projected for every month after it.
    with_bonus = it.tds_for_month(900000, 0, 250000, 100000, "2025-10-31")
    projected = 900000 + 250000 + 150000 * 5
    assert with_bonus == round(it.annual_tax(projected, 2025)["total_tax"] / 6, 2)


def test_no_tds_under_the_rebate():
    assert it.tds_for_month(0, 0, 100000, 0, "2025-04-30") == 0           # 12 lakh a year


# --- on payslips -----------------------------------------------------------------------------------------------------

def slip(tenant, emp, month_end, **extra):
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": month_end[:8] + "01",
                                             "period_end": month_end, "pay_date": month_end, "use_structure": False, **extra})
    assert res.status_code == 200, res.text
    return tenant.get("/api/payslips/%d" % res.json()["id"]).json()


def test_a_payslip_deducts_new_regime_tds_when_there_is_no_flat_rate(tenant):
    emp = make_employee(tenant, salary=150000.0, tax_rate=0.0)
    p = slip(tenant, emp, "2025-04-30")
    assert p["tax_amount"] == it.tds_for_month(0, 0, p["gross_pay"], 0, "2025-04-30") > 0


def test_tds_already_deducted_is_taken_into_account(tenant):
    emp = make_employee(tenant, salary=150000.0, tax_rate=0.0)
    april = slip(tenant, emp, "2025-04-30")
    may = slip(tenant, emp, "2025-05-31")
    expected = it.tds_for_month(april["gross_pay"], april["tax_amount"], may["gross_pay"], 0, "2025-05-31")
    assert may["tax_amount"] == expected


def test_a_flat_rate_on_the_record_still_wins(tenant):
    emp = make_employee(tenant, salary=150000.0, tax_rate=10.0)
    p = slip(tenant, emp, "2025-04-30")
    assert p["tax_amount"] == round(p["gross_pay"] * 0.10, 2)


def test_a_typed_tax_amount_still_wins(tenant):
    emp = make_employee(tenant, salary=150000.0, tax_rate=0.0)
    assert slip(tenant, emp, "2025-04-30", tax_amount=1234)["tax_amount"] == 1234


def test_editing_a_payslip_recomputes_its_tds(tenant):
    emp = make_employee(tenant, salary=150000.0, tax_rate=0.0)
    p = slip(tenant, emp, "2025-04-30")
    res = tenant.put("/api/payslips/%d" % p["id"], json={"bonus": 200000})
    assert res.status_code == 200
    after = tenant.get("/api/payslips/%d" % p["id"]).json()
    assert after["tax_amount"] == it.tds_for_month(0, 0, after["gross_pay"], 200000, "2025-04-30") > p["tax_amount"]
