"""The app on a phone: it installs as Y ERP and opens on the current interface. The previous
interface is gone - its old addresses forward, and its offline worker removes itself."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(HERE, "..", "..", "frontend")


def read(name):
    with open(os.path.join(FRONTEND, name), encoding="utf-8") as f:
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
                         ("hr.html", "/next/people/employees")):
        res = client.get("/" + page)
        assert res.status_code == 200
        assert "location.replace" in res.text and target in res.text, page


def test_the_previous_interface_is_gone():
    for name in ("app.js", "styles.css", "staff-portal.js", "offline.js", "jobs.js", "subbills.js"):
        assert not os.path.exists(os.path.join(FRONTEND, name)), name


def test_the_old_service_worker_removes_itself_and_what_it_kept(client):
    res = client.get("/sw.js")
    assert res.status_code == 200 and "javascript" in res.headers["content-type"]
    sw = read("sw.js")
    assert "unregister()" in sw and "caches.delete" in sw
    assert "addEventListener('fetch'" not in sw, "it must not answer requests"
