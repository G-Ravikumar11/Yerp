"""Paper that waits for a decision reaches the phones of those who can decide it: bell and push, for every kind in the inbox.

Purchase orders (through the approval chain), site cash and leave. The push itself is recorded here rather than sent.
"""
import pytest

from conftest import make_employee
from test_departments_and_approvals import person, sign_in
from test_site_cash import setup as site_cash_setup, spend


@pytest.fixture
def pushes(monkeypatch):
    """Every push the server would send: who it was for (an employee, or the Master's phones) and what it said."""
    sent = []

    def record(db, client_id, title, body="", link="", employee_id=None, owner=False):
        sent.append({"employee_id": employee_id, "owner": owner, "title": title, "body": body, "link": link})

    monkeypatch.setattr("app.core.notifications.push_to", record)
    return sent


def to(sent, employee):
    return [p for p in sent if p["employee_id"] == employee["id"]]


def test_a_purchase_order_reaches_its_approver_and_the_masters_phone_when_nobody_ranks_above(tenant, portal, pushes):
    pm = person(tenant, "project_manager")
    buyer = person(tenant, "purchase")
    sign_in(portal, buyer)
    assert portal.post("/api/employee/purchase-orders", json={"supplier_name": "Jindal", "amount": 90000.0}).status_code == 200
    assert to(pushes, pm) and to(pushes, pm)[0]["link"] == "/next/approvals"
    assert not to(pushes, buyer)

    pushes.clear()
    head = person(tenant, "head_projects")
    sign_in(portal, head)
    assert portal.post("/api/employee/purchase-orders", json={"supplier_name": "Tata", "amount": 400000.0}).status_code == 200
    assert any(p["owner"] for p in pushes)


def test_site_cash_spent_on_site_reaches_accounts_and_the_master(tenant, pushes):
    accounts = person(tenant, "accounts")
    bystander = person(tenant, "stores")
    box, job, engineer = site_cash_setup(tenant)
    pushes.clear()
    res = spend(engineer, box, amount=4500, paid_to="HP pump, Gajuwaka")
    assert res.status_code == 200, res.text
    number = res.json()["expense"]["number"]
    told = to(pushes, accounts)
    assert told and number in told[0]["title"] and "4,500" in told[0]["body"]
    assert any(p["owner"] for p in pushes)
    assert not to(pushes, bystander)


def test_nobody_is_told_of_the_masters_own_site_cash(tenant, pushes):
    accounts = person(tenant, "accounts")
    box, job, engineer = site_cash_setup(tenant)
    pushes.clear()
    # The Master enters it: accounts check it, but the Master is not pushed about their own entry.
    assert tenant.post("/api/site-cash/expenses", json={"account_id": box["id"], "amount": 900, "head": "Diesel & fuel", "paid_to": "HP pump"}).status_code == 200
    assert to(pushes, accounts)
    assert not any(p["owner"] for p in pushes)


def test_a_leave_request_reaches_the_manager_hr_and_the_master_but_nobody_else(tenant, portal, pushes):
    boss = person(tenant, "construction")
    other = person(tenant, "construction")
    hr = person(tenant, "hr")
    hand = person(tenant, "staff", reports_to=boss["id"])
    sign_in(portal, hand)
    pushes.clear()
    res = portal.post("/api/employee/leave", json={"leave_type": "annual", "start_date": "2026-10-05", "end_date": "2026-10-06", "reason": "Family function"})
    assert res.status_code == 200, res.text
    assert to(pushes, boss) and "annual leave" in to(pushes, boss)[0]["body"]
    assert to(pushes, hr)
    assert any(p["owner"] for p in pushes)
    assert not to(pushes, other) and not to(pushes, hand)
    # And on the manager's bell.
    sign_in(portal, boss)
    titles = [n["title"] for n in portal.get("/api/employee/notifications").json()["notifications"]]
    assert any(t.startswith("Leave to decide") for t in titles)
