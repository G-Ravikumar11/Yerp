"""Who owes what today, and what is worth looking at this morning.

The app could say what a project earned and what it cost. It could not say
how long a debt had been outstanding, or how much of the money already earned
was sitting with the client as retention - which on a contract is the quiet
one, because it is never invoiced and nobody diaries it.
"""
from datetime import date, timedelta

from conftest import make_invoice
from test_measurement_and_ra_bills import placed_order, book, measure


def days_ago(n):
    return (date.today() - timedelta(days=n)).strftime("%Y-%m-%d")


def days_ahead(n):
    return (date.today() + timedelta(days=n)).strftime("%Y-%m-%d")


def owed(tenant, due_date, amount=100000, status="Sent"):
    return make_invoice(tenant, status=status, due_date=due_date,
                        line_items=[{"description": "RA 1", "qty": 1,
                                     "price": amount, "tax_rate": "0%"}])


# --- Ageing -------------------------------------------------------------------

def test_money_not_yet_due_is_kept_out_of_the_chase_list(tenant):
    """A healthy ledger must not read like a chase list."""
    owed(tenant, days_ahead(10))
    r = tenant.get("/api/money/receivables").json()
    assert r["buckets"]["Not due"] == 100000
    assert r["summary"]["overdue"] == 0
    assert r["summary"]["owed"] == 100000


def test_each_debt_lands_in_the_right_column(tenant):
    for n, amount in ((10, 1000), (45, 2000), (75, 3000), (200, 4000)):
        owed(tenant, days_ago(n), amount)
    b = tenant.get("/api/money/receivables").json()["buckets"]
    assert b["0-30"] == 1000
    assert b["31-60"] == 2000
    assert b["61-90"] == 3000
    assert b["90+"] == 4000


def test_an_invoice_with_no_due_date_is_not_lost(tenant):
    """It cannot be chased on a date, so it sits where somebody will see it."""
    owed(tenant, "")
    r = tenant.get("/api/money/receivables").json()
    assert r["buckets"]["90+"] == 100000


def test_a_paid_invoice_is_not_owed(tenant):
    owed(tenant, days_ago(60), status="Paid")
    assert tenant.get("/api/money/receivables").json()["summary"]["owed"] == 0


def test_a_draft_invoice_is_not_owed_either(tenant):
    owed(tenant, days_ago(60), status="Draft")
    assert tenant.get("/api/money/receivables").json()["summary"]["owed"] == 0


def test_the_worst_debt_is_listed_first(tenant):
    owed(tenant, days_ago(5), 1000)
    owed(tenant, days_ago(120), 2000)
    rows = tenant.get("/api/money/receivables").json()["invoices"]
    assert rows[0]["outstanding"] == 2000
    assert rows[0]["days_overdue"] >= 120


def test_receivables_download(tenant):
    owed(tenant, days_ago(40))
    res = tenant.get("/api/money/receivables.xlsx")
    assert res.status_code == 200 and res.content[:2] == b"PK"


# --- What we owe --------------------------------------------------------------

def certified_bill(tenant, qty=400, rate=60):
    wo = placed_order(tenant, qty=1000, rate=rate)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], qty)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    return wo, b


def test_a_certified_bill_is_something_we_owe(tenant):
    """The work was measured and somebody signed for it."""
    certified_bill(tenant)
    p = tenant.get("/api/money/payables").json()
    ra = [r for r in p["bills"] if r["kind"] == "RA bill"]
    assert len(ra) == 1
    assert ra[0]["outstanding"] > 0
    assert p["summary"]["owed"] == ra[0]["outstanding"]


def test_a_paid_bill_stops_being_owed(tenant):
    wo, b = certified_bill(tenant)
    tenant.post("/api/ra-bills/%d/pay" % b["id"], json={})
    assert tenant.get("/api/money/payables").json()["summary"]["owed"] == 0


def test_a_bill_still_awaiting_approval_is_counted_apart(tenant):
    """Unapproved is a decision somebody owes; unpaid is money."""
    tenant.post("/api/bills", json={
        "vendor_name": "Steel Co", "amount": 50000, "total": 50000,
        "due_date": days_ago(10), "status": "Awaiting Approval",
        "line_items": [{"description": "Fe500D", "qty": 1, "price": 50000}]})
    s = tenant.get("/api/money/payables").json()["summary"]
    assert s["owed"] == 50000
    assert s["awaiting_approval"] == 50000


# --- Retention ----------------------------------------------------------------

def test_retention_held_is_written_down_somewhere_at_last(tenant):
    certified_bill(tenant)
    r = tenant.get("/api/money/retention").json()
    assert r["summary"]["held"] == 1200        # 5% of 24,000
    assert r["summary"]["projects"] == 1
    assert r["projects"][0]["bills"][0]["retention"] == 1200


def test_paying_a_bill_does_not_release_its_retention(tenant):
    """The money is paid; the retention stays with the client regardless."""
    wo, b = certified_bill(tenant)
    tenant.post("/api/ra-bills/%d/pay" % b["id"], json={})
    assert tenant.get("/api/money/retention").json()["summary"]["held"] == 1200


def test_a_cancelled_bill_holds_nothing_back(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/cancel" % b["id"], json={"comments": "wrong"})
    assert tenant.get("/api/money/retention").json()["summary"]["held"] == 0


def test_retention_on_a_finished_job_is_money_to_chase(tenant):
    wo, b = certified_bill(tenant)
    got = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    # The update takes a whole job, not a patch, so the rest goes back with it.
    res = tenant.put("/api/jobs/%d" % got["job_id"], json={
        "name": "Fairview plot 3", "customer_name": "L&T", "status": "complete"})
    assert res.status_code == 200, res.text
    r = tenant.get("/api/money/retention").json()
    assert r["projects"][0]["releasable"] is True
    assert r["summary"]["on_finished_jobs"] == 1200


def test_retention_downloads(tenant):
    certified_bill(tenant)
    res = tenant.get("/api/money/retention.xlsx")
    assert res.status_code == 200 and res.content[:2] == b"PK"


# --- What needs a look --------------------------------------------------------

def test_a_quiet_business_is_not_nagged(tenant):
    assert tenant.get("/api/attention").json()["items"] == []


def test_work_measured_and_never_billed_is_surfaced(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    out = tenant.get("/api/attention").json()
    hit = [i for i in out["items"] if i["kind"] == "unbilled"][0]
    assert hit["value"] == 24000
    assert out["summary"]["money_at_stake"] >= 24000


def test_a_bill_waiting_on_a_signature_is_surfaced(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    out = tenant.get("/api/attention").json()
    assert [i for i in out["items"] if i["kind"] == "certify"]
    assert out["summary"]["needs_a_decision"] >= 1


def test_over_run_work_is_surfaced_as_money(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 1200)
    hit = [i for i in tenant.get("/api/attention").json()["items"]
           if i["kind"] == "over_run"][0]
    assert hit["value"] == 12000


def test_a_draft_diary_is_a_reminder_not_an_alarm(tenant):
    job = tenant.post("/api/jobs", json={"name": "S", "customer_name": "C"}).json()
    tenant.post("/api/diary", json={"job_id": job["id"], "diary_date": "2026-09-01"})
    hit = [i for i in tenant.get("/api/attention").json()["items"]
           if i["kind"] == "diaries"][0]
    assert hit["severity"] == "notice"


def test_money_is_listed_above_paperwork(tenant):
    """Ordered by what it costs to ignore, not by which module it came from."""
    job = tenant.post("/api/jobs", json={"name": "S", "customer_name": "C"}).json()
    tenant.post("/api/diary", json={"job_id": job["id"], "diary_date": "2026-09-01"})
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    kinds = [i["kind"] for i in tenant.get("/api/attention").json()["items"]]
    assert kinds.index("unbilled") < kinds.index("diaries")


def test_another_tenant_sees_none_of_this(tenant, second_tenant):
    owed(tenant, days_ago(40))
    assert second_tenant.get("/api/money/receivables").json()["summary"]["owed"] == 0
    assert second_tenant.get("/api/money/retention").json()["projects"] == []
    assert second_tenant.get("/api/attention").json()["items"] == []
