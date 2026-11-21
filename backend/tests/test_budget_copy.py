"""A new project's budget filled from another's in one go: each BOQ line takes the costs of the matching line (same item
code, else the same description and unit); lines already budgeted are kept unless asked to overwrite."""
from test_boq import make_boq, saved
from test_budgeting import put_line

GANG = [{"kind": "LABOUR", "description": "Gang", "uom": "cum", "coefficient": 1, "rate": 160}]


def two_projects(tenant):
    a, boq_a = make_boq(tenant)
    b, boq_b = make_boq(tenant)
    la = {l["group_code"]: l["key"] for l in saved(tenant, boq_a)["lines"] if l["kind"] == "item"}
    lb = {l["group_code"]: l["key"] for l in saved(tenant, boq_b)["lines"] if l["kind"] == "item"}
    return a, b, la, lb


def row(tenant, jid, key):
    return next(r for r in tenant.get("/api/jobs/%d/budget" % jid).json()["rows"] if r["key"] == key)


def test_matching_lines_take_the_other_projects_costs(tenant):
    a, b, la, lb = two_projects(tenant)
    put_line(tenant, a, la["EXC"], GANG)
    res = tenant.post("/api/jobs/%d/budget/copy" % b, json={"from_job_id": a})
    assert res.status_code == 200, res.text
    assert res.json()["copied"]["filled"] == 1 and "budgeted from" in res.json()["message"]
    got = row(tenant, b, lb["EXC"])
    assert got["budgeted"] and got["unit_labour"] == 160


def test_a_line_already_budgeted_is_kept_unless_overwriting(tenant):
    a, b, la, lb = two_projects(tenant)
    put_line(tenant, a, la["EXC"], GANG)
    put_line(tenant, b, lb["EXC"], [dict(GANG[0], rate=120)])
    kept = tenant.post("/api/jobs/%d/budget/copy" % b, json={"from_job_id": a}).json()
    assert kept["copied"]["already_budgeted"] >= 1 and row(tenant, b, lb["EXC"])["unit_labour"] == 120
    tenant.post("/api/jobs/%d/budget/copy" % b, json={"from_job_id": a, "overwrite": True})
    assert row(tenant, b, lb["EXC"])["unit_labour"] == 160


def test_only_those_who_set_budgets_copy_them(tenant, portal):
    from test_subcontract_orders import sign_in, staff
    a, b, _, _ = two_projects(tenant)
    sign_in(portal, staff(tenant, "planning_billing"))
    assert portal.post("/api/jobs/%d/budget/copy" % b, json={"from_job_id": a}).status_code == 403
