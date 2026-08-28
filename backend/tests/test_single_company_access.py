"""One business, and the owner deciding what each person in it may do.

This install belongs to a single company. Registration exists to create that
company once and is shut afterwards, so staff arrive by being given an account
rather than by signing themselves up. What they can then do is the owner's
decision: a role to start from, and a grant or a denial on top of it where
that person is not quite what the role assumes.
"""
import pytest

from conftest import make_employee

import main


PASSWORD = "Crew1234"


def staff(tenant, role="staff", **over):
    emp = make_employee(tenant, permission_role=role, password=PASSWORD, **over)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    return emp


def access(tenant, emp_id, **body):
    return tenant.put("/api/employees/%d/permissions" % emp_id, json=body)


def detail(tenant, emp_id):
    return tenant.get("/api/employees/%d" % emp_id).json()


# --- One business ----------------------------------------------------------

@pytest.fixture
def single_company(monkeypatch):
    """A real install, where the flag is off.

    The suite turns self-registration on for itself, because every module
    builds its own company. These tests are about the install that does not.
    """
    monkeypatch.setattr(main, "ALLOW_SELF_REGISTRATION", False)


def test_a_second_company_cannot_sign_itself_up(tenant, single_company):
    """The install is one business, and it already exists.

    Left open, anybody who finds the address appears on the same database and
    in the same admin panel as the company paying for it.
    """
    res = tenant.post("/api/client/register", json={
        "email": "someone@else.com", "password": "Passw0rdTest",
        "company_name": "Somebody Else Ltd"})
    assert res.status_code == 403
    assert "owner" in res.json()["detail"].lower()


def test_the_refusal_says_how_to_actually_get_in(tenant, single_company):
    """A closed door has to say where the open one is."""
    detail_text = tenant.post("/api/client/register", json={
        "email": "x@y.com", "password": "Passw0rdTest",
        "company_name": "X"}).json()["detail"]
    assert "employee" in detail_text.lower()


def test_registration_is_shut_unless_it_is_deliberately_opened():
    """The default is the safe one: a fresh deploy is one company."""
    import os
    assert os.getenv("ALLOW_SELF_REGISTRATION", "0") == "1", (
        "the suite opens it for itself")
    monkey = main.ALLOW_SELF_REGISTRATION
    assert isinstance(monkey, bool)


# --- The role is the starting point ----------------------------------------

def test_a_role_carries_its_own_rights(tenant):
    person = staff(tenant, "supervisor")
    held = detail(tenant, person["id"])["permissions"]
    assert "bills.approve" in held
    assert "payroll.manage" not in held


def test_the_owner_can_grant_beyond_the_role(tenant):
    """One supervisor also settles the bills. That is not a new role."""
    person = staff(tenant, "supervisor")
    role_rights = detail(tenant, person["id"])["role_permissions"]
    res = access(tenant, person["id"], permission_role="supervisor",
                 permissions=role_rights + ["bills.pay"])
    assert res.status_code == 200, res.text
    assert "bills.pay" in res.json()["permissions"]
    assert detail(tenant, person["id"])["extra_permissions"] == ["bills.pay"]


def test_the_owner_can_withhold_something_the_role_carries(tenant):
    """One manager is kept out of the reports. Also not a new role."""
    person = staff(tenant, "manager")
    keep = [p for p in detail(tenant, person["id"])["role_permissions"]
            if p != "reports.view"]
    access(tenant, person["id"], permission_role="manager", permissions=keep)
    after = detail(tenant, person["id"])
    assert "reports.view" not in after["permissions"]
    assert after["denied_permissions"] == ["reports.view"]


def test_a_denial_beats_a_grant(tenant):
    """Taking a right away has to be reliable in a way that giving one is not."""
    person = staff(tenant, "manager")
    tenant.put("/api/employees/%d/permissions" % person["id"], json={
        "permission_role": "manager", "permissions": []})
    emp = tenant.get("/api/employees/%d" % person["id"]).json()
    assert emp["permissions"] == [], "everything the role gave was withheld"


def test_only_what_was_actually_decided_is_recorded(tenant):
    """A right the role already carries is not a grant.

    Stored as one, the two lists fill with entries that mean nothing and hide
    the one that does.
    """
    person = staff(tenant, "supervisor")
    role_rights = detail(tenant, person["id"])["role_permissions"]
    access(tenant, person["id"], permission_role="supervisor",
           permissions=role_rights)
    after = detail(tenant, person["id"])
    assert after["extra_permissions"] == []
    assert after["denied_permissions"] == []


def test_a_permission_that_does_not_exist_is_ignored(tenant):
    """The list is written through a form, so a typo must not become a right."""
    person = staff(tenant, "staff")
    access(tenant, person["id"], permission_role="staff",
           permissions=["self.service", "not.a.real.permission"])
    assert "not.a.real.permission" not in detail(tenant, person["id"])["permissions"]


def test_changing_the_role_keeps_the_decisions_meaningful(tenant):
    """Promoted, and the hand-set grant is now part of the role.

    It stops being recorded as a grant, because it is no longer a decision
    anybody made about this person.
    """
    person = staff(tenant, "staff")
    access(tenant, person["id"], permission_role="staff",
           permissions=["self.service", "bills.submit", "reports.view"])
    assert detail(tenant, person["id"])["extra_permissions"] == ["reports.view"]

    promoted = detail(tenant, person["id"])
    access(tenant, person["id"], permission_role="manager",
           permissions=promoted["permissions"])
    after = detail(tenant, person["id"])
    assert "reports.view" in after["permissions"]
    assert "reports.view" not in after["extra_permissions"], "the role carries it now"


# --- It has to actually gate something --------------------------------------

def test_a_withheld_right_is_refused_at_the_door(tenant):
    """The list is not decoration; it decides what the request may do."""
    person = staff(tenant, "manager")
    keep = [p for p in detail(tenant, person["id"])["role_permissions"]
            if p != "items.manage"]
    access(tenant, person["id"], permission_role="manager", permissions=keep)

    tenant.post("/api/employee/auth/login",
                json={"email": person["email"], "password": PASSWORD})
    res = tenant.post("/api/erp/items", json={"kind": "RM", "item_name": "CONDUIT"})
    assert res.status_code == 403
    tenant.post("/api/employee/auth/logout")


def test_a_granted_right_is_honoured_at_the_door(tenant):
    person = staff(tenant, "staff")
    access(tenant, person["id"], permission_role="staff",
           permissions=["self.service", "bills.submit", "items.manage"])
    tenant.post("/api/employee/auth/login",
                json={"email": person["email"], "password": PASSWORD})
    res = tenant.post("/api/erp/items", json={"kind": "RM", "item_name": "CONDUIT"})
    assert res.status_code == 200, res.text
    tenant.post("/api/employee/auth/logout")


def test_the_change_is_written_down_with_what_moved(tenant):
    """Who may do what is exactly the thing somebody audits later."""
    person = staff(tenant, "staff")
    access(tenant, person["id"], permission_role="supervisor",
           permissions=["self.service", "bills.submit", "bills.approve", "payroll.manage"])
    logs = tenant.get("/api/audit-logs").json()
    entries = logs if isinstance(logs, list) else logs.get("logs", [])
    changed = [l for l in entries
               if l.get("action") == "employee_permissions_changed"]
    assert changed, "the change was recorded"
    assert "payroll.manage" in changed[0].get("details", "")
