"""The Master's setup check: what the controls rely on that is not yet set, each with where to put it right."""
from conftest import make_employee
from test_boq import make_boq, saved


def by_key(tenant):
    res = tenant.get("/api/setup-check")
    assert res.status_code == 200, res.text
    return {i["key"]: i for i in res.json()["items"]}


def test_it_lists_what_falls_back_to_the_master_and_where_to_fix_it(tenant):
    make_employee(tenant, status="active")                    # reports to nobody
    saved(tenant, make_boq(tenant)[1])                        # a BOQ with nothing budgeted
    got = by_key(tenant)
    assert not got["reports_to"]["ok"] and got["reports_to"]["link"].startswith("/people/employees")
    assert not got["budgets"]["ok"] and got["budgets"]["count"] > 0 and got["budgets"]["link"] == "/projects/budgeting"
    assert not got["budget_people"]["ok"]                     # only the Master can set budgets
    assert all({"title", "detail", "fix", "link", "ok"} <= set(i) for i in got.values())


def test_giving_somebody_the_budget_right_clears_that_item(tenant):
    make_employee(tenant, permission_role="ho_qs", status="active")
    assert by_key(tenant)["budget_people"]["ok"]


def test_only_the_master_sees_it(tenant, portal):
    from test_subcontract_orders import sign_in, staff
    sign_in(portal, staff(tenant, "project_manager"))
    assert portal.get("/api/setup-check").status_code in (401, 403)
