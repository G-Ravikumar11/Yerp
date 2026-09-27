"""The /admin panel edits every company's rows directly, so it opens only
with a real password set in the environment - never with admin/admin."""
import main


def attempt(client, password):
    client.cookies.clear()
    return client.post("/admin/login", data={"username": "admin", "password": password},
                       follow_redirects=False)


def test_admin_admin_does_not_open_the_panel(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    main.ensure_admin_user()
    assert attempt(client, "admin").status_code not in (302, 303)
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    main.ensure_admin_user()
    assert attempt(client, "admin").status_code not in (302, 303)


def test_a_proper_password_from_the_environment_opens_it(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "Panel-Password-2026")
    main.ensure_admin_user()
    assert attempt(client, "wrong-password-here").status_code not in (302, 303)
    assert attempt(client, "Panel-Password-2026").status_code in (302, 303)
