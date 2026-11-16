"""The full and final sheet takes back the salary advance the person still holds and adds their unpaid expense claims."""
from conftest import make_employee

LAST = {"last_day": "2026-03-13"}


def sheet(tenant, emp, **params):
    res = tenant.get("/api/employees/%d/full-and-final" % emp["id"], params={**LAST, **params})
    assert res.status_code == 200, res.text
    return res.json()


def part(f, item):
    return next(p for p in f["parts"] if p["item"] == item)


def person(tenant):
    emp = make_employee(tenant, salary=65000.0, tax_rate=0.0, start_date="2018-04-01")
    return emp, "%s %s" % (emp["first_name"], emp["last_name"])


def advance(tenant, name, amount, direction="OUT", mode="Bank transfer"):
    res = tenant.post("/api/money/entries", json={"doc_type": "on_account", "direction": direction, "party_type": "staff",
                                                  "party_name": name, "amount": amount, "paid_on": "2026-02-01", "mode": mode})
    assert res.status_code == 200, res.text


def claim(tenant, emp, amount, approve=True):
    c = tenant.post("/api/expense-claims", json={"spent_on": "2026-03-02", "head": "Travel & conveyance", "amount": amount,
                                                "description": "Bus to site and back", "employee_id": emp["id"]}).json()
    if approve:
        assert tenant.post("/api/expense-claims/%d/decide" % c["id"], json={"decision": "approve"}).status_code == 200
    return c


def test_nothing_changes_when_there_is_no_advance_and_no_claim(tenant):
    emp, _ = person(tenant)
    f = sheet(tenant, emp)
    assert part(f, "Salary advance recovered")["amount"] == 0 and part(f, "Unpaid expense claims")["amount"] == 0
    assert f["advance"]["held"] == 0 and f["claims"]["rows"] == [] and f["recoverable"] == 0
    assert f["total"] == round(sum(p["amount"] for p in f["parts"]), 2)


def test_the_advance_still_held_is_taken_back_and_what_came_back_is_not(tenant):
    emp, name = person(tenant)
    base = sheet(tenant, emp)["total"]
    advance(tenant, name, 10000)
    advance(tenant, name, 4000, direction="IN", mode="Adjustment")           # part already recovered
    f = sheet(tenant, emp)
    assert f["advance"]["held"] == 6000 and part(f, "Salary advance recovered")["amount"] == -6000
    assert f["total"] == round(base - 6000, 2)


def test_unpaid_approved_claims_are_added_but_waiting_ones_and_paid_ones_are_not(tenant):
    emp, name = person(tenant)
    base = sheet(tenant, emp)["total"]
    open_claim = claim(tenant, emp, 850)
    claim(tenant, emp, 300, approve=False)                                   # not yet approved
    paid = claim(tenant, emp, 500)
    assert tenant.post("/api/money/entries", json={"doc_type": "expense_claim", "doc_id": paid["id"], "amount": 500,
                                                   "mode": "Cash", "paid_on": "2026-03-05"}).status_code == 200
    f = sheet(tenant, emp)
    assert [r["number"] for r in f["claims"]["rows"]] == [open_claim["number"]]
    assert part(f, "Unpaid expense claims")["amount"] == 850 and f["total"] == round(base + 850, 2)


def test_a_claim_already_on_a_payslip_is_not_counted_twice(tenant):
    emp, _ = person(tenant)
    c = claim(tenant, emp, 850)
    tenant.post("/api/expense-claims/%d/pay-with-salary" % c["id"], json={})
    assert sheet(tenant, emp)["claims"]["total"] == 850, "queued for the salary but no payslip carries it yet"
    tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-02-01", "period_end": "2026-02-28", "pay_date": "2026-02-28"})
    assert sheet(tenant, emp)["claims"]["total"] == 0, "the payslip carries it"


def test_an_advance_a_payslip_already_recovers_is_not_taken_twice(tenant):
    emp, name = person(tenant)
    advance(tenant, name, 10000)
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-02-01", "period_end": "2026-02-28",
                                             "pay_date": "2026-02-28", "advance_recovery": 4000})
    assert res.status_code == 200, res.text
    assert sheet(tenant, emp)["advance"]["held"] == 6000, "4,000 comes off that unreleased payslip"
    tenant.post("/api/payslips/%d/mark-paid" % res.json()["id"])
    assert sheet(tenant, emp)["advance"]["held"] == 6000, "released: the receipt now carries it"


def test_an_advance_larger_than_the_dues_leaves_a_sum_to_recover_and_the_pdf_says_so(tenant):
    emp = make_employee(tenant, salary=20000.0, tax_rate=0.0, start_date="2026-03-01")
    name = "%s %s" % (emp["first_name"], emp["last_name"])
    advance(tenant, name, 500000)
    f = sheet(tenant, emp)
    assert f["total"] < 0 and f["recoverable"] == round(-f["total"], 2)
    res = tenant.get("/api/employees/%d/full-and-final.pdf" % emp["id"], params=LAST)
    assert res.status_code == 200 and res.content.startswith(b"%PDF")
