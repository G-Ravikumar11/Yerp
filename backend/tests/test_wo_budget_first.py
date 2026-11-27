"""Budget first: on a project with a BOQ, a sub contractor work order is sent for approval only once every line is costed on
the Budgeting tab. A line priced above its budget is sent only with a reason, which its approvers read and the Master signs
- and which never reaches the contractor or the order's PDF."""
from conftest import budget_all
from test_boq import contractor_order, make_boq, saved
from test_budgeting import put_line


def setup(tenant, rate=150):
    jid, boq = make_boq(tenant)
    lines = {l["group_code"]: l for l in saved(tenant, boq)["lines"] if l["kind"] == "item"}
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, rate)])
    budget_all(tenant, jid, skip={lines["EXC"]["key"]})       # the rest of the project; each test sets EXC's own budget
    return jid, lines, order


def labour(tenant, jid, key, rate):
    res = put_line(tenant, jid, key, [{"kind": "LABOUR", "description": "Excavation gang", "uom": "cum", "coefficient": 1, "rate": rate}])
    assert res.status_code == 200, res.text


def submit(tenant, order, comments=""):
    return tenant.post("/api/wo/orders/%d/submit" % order["id"], json={"comments": comments})


def test_an_order_whose_line_is_not_budgeted_is_not_sent_and_says_which_line(tenant):
    _, _, order = setup(tenant)
    res = submit(tenant, order)
    assert res.status_code == 400 and "Budget it first" in res.json()["detail"] and "EXC" in res.json()["detail"]


def test_within_the_budget_it_goes_without_a_reason(tenant):
    jid, lines, order = setup(tenant, rate=150)
    labour(tenant, jid, lines["EXC"]["key"], 160)
    assert submit(tenant, order).status_code == 200


def test_above_the_budget_it_needs_a_reason_and_the_master_signs_it(tenant):
    jid, lines, order = setup(tenant, rate=200)
    labour(tenant, jid, lines["EXC"]["key"], 160)
    refused = submit(tenant, order)
    assert refused.status_code == 409 and "above the budget" in refused.json()["detail"]
    assert "4,000" in refused.json()["detail"]                  # 100 cum x 40 more
    assert submit(tenant, order, "Hard rock found at 2 m").status_code == 200
    got = tenant.get("/api/wo/orders/%d" % order["id"]).json()
    got = got.get("order") or got
    assert got["over_budget_reason"].startswith("Hard rock found at 2 m")
    inbox = tenant.get("/api/approvals/inbox").json()
    item = next(i for i in inbox["items"] if i.get("ref_id") == order["id"] or i.get("id") == order["id"])
    assert any("above the budget" in w for w in item.get("warnings", []))


def test_the_reason_never_goes_on_the_orders_pdf(tenant):
    jid, lines, order = setup(tenant, rate=200)
    labour(tenant, jid, lines["EXC"]["key"], 160)
    assert submit(tenant, order, "Secret reason XYZZY").status_code == 200
    pdf = tenant.get("/api/wo/orders/%d/document.pdf" % order["id"])
    assert pdf.status_code == 200 and b"XYZZY" not in pdf.content
