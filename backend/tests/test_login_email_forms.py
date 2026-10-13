"""Owner sign-in treats the email as an address, not a string: case and stray spaces do not matter."""
PASSWORD = "Passw0rdTest"


def _login(client, email, password=PASSWORD):
    return client.post("/api/client/login", json={"email": email, "password": password})


def test_register_then_login_with_same_credentials(client, account):
    assert _login(client, account["email"], account["password"]).status_code == 200


def test_login_ignores_case_and_surrounding_spaces(client, account):
    email = account["email"]
    assert _login(client, "  %s  " % email, account["password"]).status_code == 200
    assert _login(client, email.upper(), account["password"]).status_code == 200


def test_wrong_password_and_unknown_email_are_401(client, account):
    assert _login(client, account["email"], "WrongPass1").status_code == 401
    assert _login(client, "nobody@example.com").status_code == 401


def test_register_stores_a_normalised_email_and_blocks_case_duplicates(client):
    res = client.post("/api/client/register", json={"email": "  Mixed.Case@Example.com ", "password": PASSWORD})
    if res.status_code == 403:      # single-company install: registration is closed once one exists
        return
    assert res.status_code == 200
    assert _login(client, "mixed.case@example.com").status_code == 200
    dup = client.post("/api/client/register", json={"email": "MIXED.CASE@example.com", "password": PASSWORD})
    assert dup.status_code == 400
