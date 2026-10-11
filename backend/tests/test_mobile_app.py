"""The app on a phone: it installs as Y ERP and opens on the current interface. The previous
interface is gone - its old addresses forward, and its offline worker removes itself."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(HERE, "..", "..", "frontend")
# The old app's files the server still sends: its self-removing service worker and its manifest.
STATIC = os.path.join(HERE, "..", "app", "static")


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


def test_it_installs_as_y_erp_and_opens_on_the_new_interface(client):
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200
    m = json.loads(res.text)
    assert m["name"] == "Y ERP" and m["start_url"] == "/next/" and m["display"] == "standalone"
    assert any(i["sizes"] == "512x512" for i in m["icons"])
    for s in m["shortcuts"]:
        assert s["url"].startswith("/next/"), s


def test_old_addresses_forward_to_the_new_interface(client):
    for page, target in (("app.html", "/next/"), ("employee-dashboard.html", "/next/"),
                         ("hr.html", "/next/people/employees"), ("login.html", "/next/login"),
                         ("employee-login.html", "/next/login"), ("portal.html", "/next/portal"),
                         ("superadmin.html", "/next/superadmin"), ("superadmin-login.html", "/next/superadmin/login"),
                         ("onboard.html", "/next/onboard"), ("jobs.html", "/next/jobs"),
                         ("recruitment.html", "/next/apply"), ("meeting.html", "/next/meeting"),
                         ("reset-password.html", "/next/reset-password")):
        res = client.get("/" + page, follow_redirects=False)
        assert res.status_code in (302, 307), page
        assert res.headers["location"] == target, page


def test_a_forwarded_address_keeps_its_query_string(client):
    res = client.get("/reset-password.html?token=abc&portal=employee", follow_redirects=False)
    assert res.headers["location"] == "/next/reset-password?token=abc&portal=employee"
    res = client.get("/portal.html?invite=xyz", follow_redirects=False)
    assert res.headers["location"] == "/next/portal?invite=xyz"


def test_the_previous_interface_is_gone():
    for name in ("app.js", "styles.css", "staff-portal.js", "offline.js", "jobs.js", "subbills.js"):
        assert not os.path.exists(os.path.join(FRONTEND, name)), name


def test_the_old_service_worker_removes_itself_and_what_it_kept(client):
    res = client.get("/sw.js")
    assert res.status_code == 200 and "javascript" in res.headers["content-type"]
    sw = read("legacy-sw.js")
    assert "unregister()" in sw and "caches.delete" in sw
    assert "addEventListener('fetch'" not in sw, "it must not answer requests"
