"""PF, ESI and professional tax on a monthly payslip."""
from types import SimpleNamespace

from app.services import statutory as s
from app.services.payroll import compute_payslip_figures
from app.services.salary_structure import apply_statutory


def emp(**kw):
    base = dict(pf_enabled=True, esi_enabled=True, pt_enabled=True, pt_state="TS", pay_frequency="monthly",
                salary=30000, hourly_rate=0, tax_rate=0, deductions=0)
    return SimpleNamespace(**{**base, **kw})


def test_pf_is_twelve_percent_of_basic_up_to_the_ceiling():
    assert s.provident_fund(emp(), 10000) == (1200.0, 367.0, 833.0)
    assert s.provident_fund(emp(), 40000)[0] == 1800.0          # basic counts only to 15,000


def test_employer_pension_is_capped_and_epf_is_the_rest():
    employee, epf, eps = s.provident_fund(emp(), 15000)
    assert eps <= 1250.0 and round(epf + eps, 2) == employee == 1800.0


def test_hourly_pay_is_left_as_typed():
    assert s.professional_tax(emp(salary=0), 50000) == 0.0 and s.state_insurance(emp(salary=0), 5000) == (0.0, 0.0)


def test_pf_switched_off_or_not_monthly():
    assert s.provident_fund(emp(pf_enabled=False), 10000) == (0.0, 0.0, 0.0)
    assert s.provident_fund(emp(pay_frequency="weekly"), 10000) == (0.0, 0.0, 0.0)


def test_esi_only_up_to_21000_gross():
    assert s.state_insurance(emp(), 20000) == (150.0, 650.0)
    assert s.state_insurance(emp(), 21000) == (157.5, 682.5)
    assert s.state_insurance(emp(), 21000.01) == (0.0, 0.0)
    assert s.state_insurance(emp(esi_enabled=False), 20000) == (0.0, 0.0)


def test_professional_tax_slabs_for_both_states():
    for state in ("TS", "AP"):
        e = emp(pt_state=state)
        assert [s.professional_tax(e, g) for g in (15000, 15001, 20000, 20001)] == [0.0, 150.0, 150.0, 200.0]
    assert s.professional_tax(emp(pt_enabled=False), 50000) == 0.0
    assert s.professional_tax(emp(pt_state="XX"), 50000) == 200.0     # an unknown state falls back to the default slab


def test_structure_lines_carry_the_statutory_amounts():
    lines = [
        {"kind": "earning", "counts_as": "basic", "amount": 20000.0, "name": "Basic", "basis": "percent", "percent": 40.0},
        {"kind": "earning", "counts_as": "allowance", "amount": 30000.0, "name": "HRA", "basis": "manual", "percent": 0.0},
        {"kind": "deduction", "counts_as": "pf", "amount": 6000.0, "name": "PF", "basis": "percent", "percent": 12.0},
    ]
    out = apply_statutory(lines, emp())
    pf = [l for l in out if l["counts_as"] == "pf"][0]
    assert pf["amount"] == 1800.0
    assert not [l for l in out if l["counts_as"] == "esi"]          # 50,000 gross: over the ESI limit


def test_structure_without_esi_line_gets_one_when_due():
    lines = [{"kind": "earning", "counts_as": "basic", "amount": 8000.0, "name": "Basic", "basis": "percent", "percent": 40.0},
             {"kind": "earning", "counts_as": "allowance", "amount": 8000.0, "name": "HRA", "basis": "manual", "percent": 0.0}]
    out = apply_statutory(lines, emp())
    assert {l["counts_as"]: l["amount"] for l in out if l["kind"] == "deduction"} == {"pf": 960.0, "esi": 120.0}


def test_payslip_figures_include_pt_and_employer_shares():
    lines = [{"kind": "earning", "counts_as": "basic", "amount": 10000.0, "name": "Basic", "basis": "percent", "percent": 40.0},
             {"kind": "earning", "counts_as": "allowance", "amount": 15000.0, "name": "HRA", "basis": "manual", "percent": 0.0}]
    lines = apply_statutory(lines, emp())
    f = compute_payslip_figures(emp(), {}, lines)
    assert f["gross_pay"] == 25000.0 and f["retirement"] == 1200.0 and f["insurance"] == 0.0
    assert f["professional_tax"] == 200.0 and f["employer_pf"] == 1200.0 and f["employer_esi"] == 0.0
    assert f["total_deductions"] == 1400.0 and f["net_pay"] == 23600.0


def test_without_a_structure_the_engine_fills_in_what_was_not_typed():
    f = compute_payslip_figures(emp(salary=18000), {"basic_salary": 18000})
    assert f["retirement"] == 1800.0 and f["insurance"] == 135.0 and f["professional_tax"] == 150.0
    typed = compute_payslip_figures(emp(salary=18000), {"basic_salary": 18000, "retirement": 500})
    assert typed["retirement"] == 500.0


from conftest import make_employee


def test_an_employee_carries_the_payroll_fields(tenant):
    emp = make_employee(tenant, salary=18000.0)
    got = tenant.get("/api/employees/%d" % emp["id"]).json()
    assert (got["pf_enabled"], got["esi_enabled"], got["pt_enabled"], got["pt_state"], got["bank_ifsc"]) == (True, True, True, "TS", "")
    res = tenant.put("/api/employees/%d" % emp["id"], json={
        "bank_ifsc": "hdfc0001234", "pt_state": "ap", "esi_enabled": False,
        "probation_end_date": "2027-01-15", "contract_end_date": ""})
    assert res.status_code == 200, res.text
    got = tenant.get("/api/employees/%d" % emp["id"]).json()
    assert got["bank_ifsc"] == "HDFC0001234" and got["pt_state"] == "AP" and got["esi_enabled"] is False
    assert got["probation_end_date"] == "2027-01-15" and got["contract_end_date"] == ""


def test_bad_payroll_fields_are_refused(tenant):
    emp = make_employee(tenant)
    for body in ({"bank_ifsc": "HDFC123"}, {"pt_state": "KA"}, {"probation_end_date": "15/01/2027"}):
        assert tenant.put("/api/employees/%d" % emp["id"], json=body).status_code == 400, body


def test_switching_off_pf_and_pt_on_the_employee_changes_the_payslip(tenant):
    emp = make_employee(tenant, salary=30000.0, tax_rate=0.0)
    tenant.put("/api/employees/%d" % emp["id"], json={"pf_enabled": False, "pt_enabled": False, "esi_enabled": False})
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-03-01",
                                             "period_end": "2026-03-31", "pay_date": "2026-03-31"})
    slip = tenant.get("/api/payslips/%d" % res.json()["id"]).json()
    assert slip["retirement"] == 0 and slip["professional_tax"] == 0 and slip["net_pay"] == slip["gross_pay"]


def test_esi_follows_the_gross_with_overtime_and_bonus_added():
    """Earnings are resolved first; the statutory lines are then worked from the basic and the whole gross."""
    lines = [{"kind": "earning", "counts_as": "basic", "amount": 10000.0, "name": "Basic", "basis": "percent", "percent": 40.0},
             {"kind": "earning", "counts_as": "allowance", "amount": 10000.0, "name": "HRA", "basis": "manual", "percent": 0.0}]
    lines = apply_statutory(lines, emp())                      # 20,000 gross: ESI 150
    assert {l["counts_as"]: l["amount"] for l in lines if l["kind"] == "deduction"} == {"pf": 1200.0, "esi": 150.0}
    f = compute_payslip_figures(emp(), {"bonus": 2000}, lines)  # 22,000 gross: over the limit
    assert f["gross_pay"] == 22000.0 and f["insurance"] == 0.0 and f["retirement"] == 1200.0
    assert f["employer_esi"] == 0.0 and f["professional_tax"] == 200.0
    f = compute_payslip_figures(emp(), {"bonus": 500}, lines)   # 20,500 gross: ESI 153.75
    assert f["insurance"] == 153.75 and f["employer_esi"] == 666.25
