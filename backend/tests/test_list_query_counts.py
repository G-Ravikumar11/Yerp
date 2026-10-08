"""The long lists ask the database the same number of questions however long they are.

On the hosted database every question is a trip across the network, so a list that asked one per row took
seconds once there were a few hundred rows. Each list here is measured with a few rows and again with more:
the count may not grow with them.
"""
import pytest
from sqlalchemy import event

from app import db as database
from test_subcontractor_bills import live_order, measure, raise_bill

LISTS = ["/api/wo/orders", "/api/sub-bills", "/api/jobs", "/api/jobs?costing=false", "/api/costs/by-project",
         "/api/approvals/inbox", "/api/money/payables", "/api/schedule-overview"]


def queries(client, path):
    seen = [0]

    def count(*_):
        seen[0] += 1
    event.listen(database.engine, "before_cursor_execute", count)
    try:
        res = client.get(path)
    finally:
        event.remove(database.engine, "before_cursor_execute", count)
    assert res.status_code == 200, (path, res.text)
    return seen[0]


def add_orders(tenant, n):
    for i in range(n):
        o = live_order(tenant, pay_advance=False)
        item = tenant.get("/api/sub-mb/%d" % o["id"]).json()["lines"][0]["item_id"]
        measure(tenant, o["id"], item, 1)
        bill = raise_bill(tenant, o["id"]).json()["bill"]
        tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
        if i % 2:
            tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})


@pytest.mark.parametrize("path", LISTS)
def test_a_list_does_not_ask_once_per_row(tenant, path):
    add_orders(tenant, 2)
    few = queries(tenant, path)
    add_orders(tenant, 6)
    many = queries(tenant, path)
    assert many <= few + 2, "%s: %d queries for 2 orders, %d for 8" % (path, few, many)


def test_the_staff_home_screen_does_not_ask_once_per_site(tenant, portal):
    from test_subcontract_orders import sign_in, staff
    site = staff(tenant, "staff")
    sign_in(portal, site)
    for i in range(2):
        tenant.post("/api/jobs", json={"name": "Site %d" % i, "status": "in_progress"})
    few = queries(portal, "/api/employee/today")
    for i in range(6):
        tenant.post("/api/jobs", json={"name": "More %d" % i, "status": "in_progress"})
    many = queries(portal, "/api/employee/today")
    assert many <= few + 1, (few, many)


def test_every_answer_says_how_long_it_spent_in_the_database(tenant):
    res = tenant.get("/api/wo/orders")
    assert "db;dur=" in res.headers.get("server-timing", "") and "queries" in res.headers["server-timing"]
