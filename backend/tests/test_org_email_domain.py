"""Staff sign in with an address the business issues.

Once HR sets a domain, new accounts are created on it. People who already had
an account keep the address they sign in with - rewriting those would lock a
whole workforce out at once, which is why setting the domain is not a bulk
rename.
"""
import uuid

from conftest import make_employee


def set_domain(tenant, domain):
    res = tenant.put("/api/hr/org-domain", json={"domain": domain})
    assert res.status_code == 200, res.text
    return res.json()


def test_no_domain_set_accepts_any_address(tenant):
    assert tenant.get("/api/hr/org-domain").json()["domain"] == ""
    emp = make_employee(tenant, email="someone@gmail.com")
    assert emp["email"] == "someone@gmail.com"


def test_a_new_account_must_use_the_org_domain(tenant):
    set_domain(tenant, "acme.co.uk")
    res = tenant.post("/api/employees", json={
        "first_name": "Ravi", "last_name": "Kumar", "email": "ravi@gmail.com",
    })
    assert res.status_code == 400
    assert "acme.co.uk" in res.json()["detail"]

    ok = make_employee(tenant, first_name="Ravi", last_name="Kumar",
                       email="ravi.kumar@acme.co.uk")
    assert ok["email"] == "ravi.kumar@acme.co.uk"


def test_the_domain_is_cleaned_up_on_the_way_in(tenant):
    assert set_domain(tenant, "@acme.co.uk")["domain"] == "acme.co.uk"
    assert set_domain(tenant, "https://www.acme.co.uk/")["domain"] == "acme.co.uk"
    assert set_domain(tenant, "  ACME.CO.UK ")["domain"] == "acme.co.uk"


def test_nonsense_is_refused(tenant):
    for bad in ("not a domain", "acme", "http://", "@@"):
        res = tenant.put("/api/hr/org-domain", json={"domain": bad})
        assert res.status_code == 400, f"{bad} should be refused"


def test_clearing_the_domain_lifts_the_rule(tenant):
    set_domain(tenant, "acme.co.uk")
    assert tenant.post("/api/employees", json={
        "first_name": "A", "last_name": "B", "email": "a@gmail.com"}).status_code == 400
    set_domain(tenant, "")
    assert make_employee(tenant, email="a@gmail.com")["email"] == "a@gmail.com"


def test_existing_people_are_left_alone_but_counted(tenant):
    make_employee(tenant, email="old.hand@gmail.com")
    set_domain(tenant, "acme.co.uk")
    state = tenant.get("/api/hr/org-domain").json()
    assert state["domain"] == "acme.co.uk"
    assert state["employees_off_domain"] == 1


def test_an_address_is_suggested_from_the_name(tenant):
    set_domain(tenant, "acme.co.uk")
    res = tenant.get("/api/hr/suggest-email",
                     params={"first_name": "Ravi", "last_name": "Kumar"})
    assert res.json()["email"] == "ravi.kumar@acme.co.uk"


def test_a_suggestion_never_collides_with_somebody_already_there(tenant):
    set_domain(tenant, "acme.co.uk")
    make_employee(tenant, first_name="Ravi", last_name="Kumar",
                  email="ravi.kumar@acme.co.uk")
    res = tenant.get("/api/hr/suggest-email",
                     params={"first_name": "Ravi", "last_name": "Kumar"})
    assert res.json()["email"] == "ravi.kumar2@acme.co.uk"


def test_awkward_names_still_produce_a_usable_address(tenant):
    set_domain(tenant, "acme.co.uk")
    res = tenant.get("/api/hr/suggest-email",
                     params={"first_name": "Mary-Jane", "last_name": "O'Brien"})
    assert res.json()["email"] == "maryjane.obrien@acme.co.uk"


def test_no_suggestion_without_a_domain(tenant):
    assert tenant.get("/api/hr/suggest-email",
                      params={"first_name": "A", "last_name": "B"}).json()["email"] == ""


def test_editing_an_employee_onto_a_personal_address_is_refused(tenant):
    emp = make_employee(tenant, email="ravi.kumar@acme.co.uk")
    set_domain(tenant, "acme.co.uk")
    res = tenant.put(f"/api/employees/{emp['id']}", json={"email": "ravi@gmail.com"})
    assert res.status_code == 400, res.text


def test_the_domain_is_per_business(client):
    """One tenant's domain must not constrain another's."""
    import uuid as _uuid

    def register():
        email = f"user-{_uuid.uuid4().hex[:10]}@example.com"
        client.post("/api/client/register", json={"email": email, "password": "Passw0rdTest"})
        client.post("/api/client/login", json={"email": email, "password": "Passw0rdTest"})

    register()
    set_domain(client, "acme.co.uk")

    register()
    assert client.get("/api/hr/org-domain").json()["domain"] == ""
    assert make_employee(client, email="free@gmail.com")["email"] == "free@gmail.com"
