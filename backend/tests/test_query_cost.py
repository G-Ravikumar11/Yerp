"""How much work a screen costs the database.

Correctness tests do not notice a screen that issues one query per row - it
answers correctly, just slowly, and only once there is real data in the system.
These count the round trips instead, so the pattern is caught at the point it
is introduced rather than after a customer reports a slow page.
"""
import pytest
from sqlalchemy import event

from app import db as database
import main
from conftest import make_employee, make_invoice


class Counter:
    """Counts statements issued against the engine while it is active."""

    def __init__(self):
        self.statements = []

    def __enter__(self):
        event.listen(database.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        event.remove(database.engine, "before_cursor_execute", self._record)
        return False

    def _record(self, conn, cursor, statement, params, context, executemany):
        # The start-up thread that reads the schema for deletes shares this engine; its look at the schema is not the screen's.
        if statement.lstrip().upper().startswith('PRAGMA') or 'sqlite_master' in statement:
            return
        self.statements.append(statement)

    def __len__(self):
        return len(self.statements)


def make_job(tenant, name):
    return tenant.post("/api/jobs", json={
        "name": name, "customer_name": "Acme", "status": "in_progress"}).json()


def test_the_jobs_board_does_not_query_per_job(tenant):
    """The board reads each table once and groups in memory.

    Costing each job in turn issued about seven queries per row, so fifty live
    jobs meant three hundred and fifty round trips to draw one screen.
    """
    for n in range(3):
        make_job(tenant, "Job %d" % n)
    with Counter() as few:
        assert tenant.get("/api/jobs-summary").status_code == 200

    for n in range(3, 12):
        make_job(tenant, "Job %d" % n)
    with Counter() as many:
        assert tenant.get("/api/jobs-summary").status_code == 200

    # Four times the jobs must not mean four times the queries.
    assert len(many) <= len(few) + 2, (
        "%d jobs cost %d queries, 3 jobs cost %d - this is scaling with rows"
        % (12, len(many), len(few)))


def test_the_board_still_adds_up(tenant):
    """Bulk costing has to produce what the per-job version produced."""
    job = make_job(tenant, "Fairview")
    make_invoice(tenant, job_id=job["id"],
                 line_items=[{"description": "w", "qty": 1, "price": 10000.0,
                              "tax_rate": "No Tax"}])
    tenant.post("/api/bills", json={"number": "QB1", "vendor_name": "X",
                                    "amount": 3000.0, "total": 3000.0,
                                    "job_id": job["id"]})

    board = tenant.get("/api/jobs-summary").json()
    row = [r for r in board["jobs"] if r["id"] == job["id"]][0]["costing"]
    single = tenant.get("/api/jobs/%d" % job["id"]).json()["costing"]

    for field in ("spent", "used", "remaining", "total_cost", "ordered", "budgeted"):
        assert row[field] == single[field], field


def test_saving_an_item_does_not_read_the_item_master(tenant):
    """Checking a code is free must ask about that code, not load the table.

    The first version pulled every row in the system to build a set, on every
    save. Correct, and ruinous once a business has a hundred thousand parts.
    """
    for n in range(20):
        tenant.post("/api/erp/items", json={"kind": "RM", "item_name": "Part %d" % n})

    with Counter() as counted:
        res = tenant.post("/api/erp/items", json={"kind": "RM", "item_name": "One more"})
    assert res.status_code == 200

    # Whatever the exact number, it must not grow with the master's size.
    loaded = [s for s in counted.statements
              if "FROM erp_items" in s and "WHERE" not in s.upper()]
    assert not loaded, "something is reading the whole item master"


def test_a_sheet_asks_about_its_own_codes_only(tenant):
    for n in range(20):
        tenant.post("/api/erp/items", json={"kind": "RM", "item_name": "Part %d" % n})

    sheet = ("Item Code,Item Name,Sub Category\r\n"
             "QQQ001,A,RM\r\nQQQ002,B,RM\r\n").encode("utf-8-sig")
    with Counter() as counted:
        res = tenant.post("/api/erp/items/analyse",
                          files={"file": ("s.csv", sheet, "text/csv")})
    assert res.status_code == 200
    unbounded = [s for s in counted.statements
                 if "FROM erp_items" in s and "WHERE" not in s.upper()]
    assert not unbounded, "the analyser is reading the whole item master"


def test_the_code_lookup_handles_more_codes_than_a_statement_can_bind(tenant):
    """Databases cap how many bind parameters one statement may carry, so the
    lookup is chunked. A sheet with a few thousand rows must still work."""
    codes = ["Z%05d" % n for n in range(2500)]
    found = main.codes_in_use(database.SessionLocal(), codes)
    assert found == set()


def _po(tenant, n, job_id=None):
    body = {"supplier_name": "Supplier %d" % n, "issue_date": "2026-10-01",
            "line_items": [{"description": "Cement", "qty": 10, "price": 400.0, "tax_rate": "0%"},
                           {"description": "Sand", "qty": 5, "price": 100.0, "tax_rate": "0%"}]}
    if job_id:
        body["job_id"] = job_id
    res = tenant.post("/api/purchase-orders", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_the_order_list_does_not_query_per_order(tenant):
    """Each order's project, lines, bills and receipts are fetched for the whole list at once."""
    job = make_job(tenant, "Fairview")
    for n in range(2):
        _po(tenant, n, job["id"])
    with Counter() as few:
        assert tenant.get("/api/purchase-orders").status_code == 200
    for n in range(2, 12):
        _po(tenant, n, job["id"])
    with Counter() as many:
        assert tenant.get("/api/purchase-orders").status_code == 200
    assert len(many) <= len(few) + 2, "12 orders cost %d queries, 2 cost %d" % (len(many), len(few))
    with Counter() as match:
        assert tenant.get("/api/match/three-way").status_code == 200
    assert len(match) <= len(few) + 4, "the three-way match costs %d queries for 12 orders" % len(match)


def test_the_batched_order_list_says_what_each_single_order_says(tenant):
    job = make_job(tenant, "Fairview")
    made = [_po(tenant, n, job["id"]) for n in range(3)]
    listed = {o["id"]: o for o in tenant.get("/api/purchase-orders").json()["orders"]}
    for o in made:
        one = tenant.get("/api/purchase-orders/%d" % o["id"]).json()
        for key in ("job_name", "billed_total", "billed_count", "received_total", "receipt_count", "remaining", "line_items"):
            assert listed[o["id"]][key] == one[key], key


def test_the_wallet_does_not_query_per_pricing_rule(tenant):
    """Its monthly usage is one grouped read, not one query for every rule."""
    assert tenant.get("/api/wallet").status_code == 200        # the first read seeds the price list
    with Counter() as q:
        assert tenant.get("/api/wallet").status_code == 200
    assert len(q) <= 8, "the wallet cost %d queries" % len(q)
