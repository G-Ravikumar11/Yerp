"""Which portals each role sees follows the ladder: the higher the rank, the more of them.

A portal is a part of the menu that is not everybody's (Projects, Clients, Subcontractors, Store, Money).
Having its right puts the group in the sidebar. The Master always has all of them, and nothing here changes
what the Master may do about anybody's rights.
"""
from app.core.permissions import (
    MANAGEMENT_RANK, PERMISSION_KEYS, PERMISSION_ROLES, ROLE_PERMISSIONS, permissions_for,
)

PORTALS = ("projects.view", "clients.view", "subcontractors.view", "store.view", "money.view")


class Person:
    def __init__(self, role, extra="", denied=""):
        self.permission_role, self.extra_permissions, self.denied_permissions = role, extra, denied


def portals(role):
    return {p for p in PORTALS if p in ROLE_PERMISSIONS[role]}


def test_every_portal_has_a_right_the_master_can_hand_out():
    assert set(PORTALS) <= PERMISSION_KEYS


def test_the_master_has_every_portal():
    assert portals("owner") == set(PORTALS)


def test_from_the_project_manager_up_a_role_has_every_portal():
    for r in PERMISSION_ROLES:
        if r.get("rank", 1) >= MANAGEMENT_RANK:
            assert portals(r["code"]) == set(PORTALS), r["code"]


def test_nobody_higher_on_the_ladder_has_fewer_portals_than_somebody_below():
    roles = [(r["code"], r.get("rank", 1)) for r in PERMISSION_ROLES]
    for high, high_rank in roles:
        for low, low_rank in roles:
            if high_rank > low_rank:
                assert portals(low) <= portals(high), "%s (rank %d) lacks what %s (rank %d) has" % (high, high_rank, low, low_rank)


def test_site_staff_see_only_the_projects_portal():
    assert portals("staff") == {"projects.view"}


def test_the_departments_see_the_portals_they_work_in():
    assert "money.view" in portals("accounts") and "money.view" not in portals("purchase")
    assert "clients.view" in portals("planning_billing") and "clients.view" not in portals("stores")
    assert "store.view" in portals("stores") and "store.view" in portals("purchase")
    assert "subcontractors.view" in portals("construction") and "subcontractors.view" not in portals("stores")
    assert portals("hr") == set(PORTALS)                                    # HR looks across every portal


def test_the_master_can_still_grant_and_withhold_a_portal_for_one_person():
    plain = Person("staff")
    assert "money.view" not in permissions_for(plain)
    assert "money.view" in permissions_for(Person("staff", extra="money.view"))
    assert "projects.view" not in permissions_for(Person("staff", denied="projects.view"))
    assert "money.view" not in permissions_for(Person("accounts", denied="money.view"))


# --- the cards the Master sets: No access, Read only, Read & write ---------------

from app.core.permissions import PORTAL_KEYS, PORTALS as CARDS, portal_level


def levels(role):
    return {p["code"]: portal_level(ROLE_PERMISSIONS[role], p) for p in CARDS if p["read"]}


def test_a_right_belongs_to_one_card_only():
    seen = {}
    for p in CARDS:
        for k in p["read"] + p["write"]:
            assert k not in seen, "%s is on both %s and %s" % (k, seen[k], p["code"])
            seen[k] = p["code"]
    assert PORTAL_KEYS <= PERMISSION_KEYS


def test_the_people_card_can_be_set_like_any_other():
    people = next(p for p in CARDS if p["code"] == "people")
    assert "locked" not in people
    assert people["read"] == ["people.manage"]
    assert people["write"] == ["payroll.manage", "recruitment.manage", "attendance.view_team", "leave.approve"]


def test_the_master_is_on_read_and_write_everywhere():
    assert set(levels("owner").values()) == {"write"}


def test_each_roles_preset_lands_on_the_cards_it_should():
    assert levels("staff") == {"projects": "write", "clients": "none", "subcontractors": "none", "store": "none", "money": "none", "people": "none"}
    assert levels("accounts")["money"] == "write" and levels("accounts")["subcontractors"] == "read"
    assert levels("purchase")["store"] == "write" and levels("purchase")["money"] == "none"
    assert levels("planning_billing")["clients"] == "write" and levels("planning_billing")["money"] == "none"
    # HR writes in the People portal and only reads in every other.
    assert levels("hr") == {"projects": "read", "clients": "read", "subcontractors": "read", "store": "read",
                            "money": "read", "people": "write"}
    # Whoever signs off the work does not also pay for it.
    assert levels("project_manager")["money"] == "read"


def test_a_card_with_no_view_right_is_no_access_whatever_else_is_held():
    assert portal_level({"site.record", "site.signoff"}, CARDS[0]) == "none"
    assert portal_level({"projects.view"}, CARDS[0]) == "read"
    assert portal_level({"projects.view", "site.record"}, CARDS[0]) == "write"


def test_the_catalogue_hands_the_cards_to_the_screen(tenant):
    body = tenant.get("/api/hr/levels").json()
    assert [p["code"] for p in body["portals"]] == ["projects", "clients", "subcontractors", "store", "money", "people"]
    assert all({"label", "blurb", "read", "write"} <= set(p) for p in body["portals"])


# --- the HR designation: hidden from the picker, the Master's to give ------------

def test_the_hr_designation_is_fixed_and_hidden_from_the_picker():
    from app.core.permissions import ASSIGNABLE_ROLES, EMPLOYEE_ROLES, FIXED_ROLES
    hr = next(r for r in EMPLOYEE_ROLES if r["code"] == "hr")
    assert (hr["label"], hr["level"], hr["department"], hr["reports_to"], hr["access"]) == ("HR", "L3", "HR", "hod", "hr")
    assert "hr" in FIXED_ROLES and "hr" not in {r["code"] for r in ASSIGNABLE_ROLES}
    assert not any(r["code"] == "sr_hr" for r in EMPLOYEE_ROLES)


def test_the_master_can_give_a_fixed_designation(tenant):
    from conftest import make_employee
    assert make_employee(tenant, role="hr")["role"] == "hr"                      # the Master signed in: allowed


def test_an_hr_login_can_give_a_fixed_designation(tenant):
    import uuid
    import main
    from fastapi.testclient import TestClient
    from conftest import make_employee
    tag = uuid.uuid4().hex[:6]
    email = "hr-%s@example.com" % tag
    make_employee(tenant, email=email, password="Crew1234", permission_role="hr", status="active")
    target = make_employee(tenant, email="tg-%s@example.com" % tag, password="Crew1234", status="active")
    c = TestClient(main.app)
    c.__enter__()
    try:
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        assert c.put("/api/employees/%d" % target["id"], json={"role": "hod"}).status_code == 200
    finally:
        c.__exit__(None, None, None)
