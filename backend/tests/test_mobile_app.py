"""The app on a phone: installable, opens with no signal, and keeps a diary
written offline - but keeps nothing else of the business on the device."""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(HERE, "..", "..", "frontend")


def read(name):
    with open(os.path.join(FRONTEND, name), encoding="utf-8") as f:
        return f.read()


def test_it_installs_as_y_erp_and_opens_on_the_app(client):
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200
    m = json.loads(res.text)
    assert m["name"] == "Y ERP" and m["start_url"] == "/app.html" and m["display"] == "standalone"
    assert any(i["sizes"] == "512x512" for i in m["icons"])
    html = read("app.html")
    for s in m["shortcuts"]:
        view = s["url"].split("#", 1)[1]
        assert 'id="%s"' % view in html, view


def test_the_service_worker_is_served_from_the_root(client):
    res = client.get("/sw.js")
    assert res.status_code == 200 and "javascript" in res.headers["content-type"]


def test_only_what_the_diary_needs_is_kept_offline():
    """Money, payroll and parties never sit in the phone's cache."""
    sw = read("sw.js")
    kept = re.search(r"var API_KEPT = \[(.*?)\];", sw, re.S).group(1)
    for word in ("bills", "money", "ledger", "employees", "payroll", "portal", "gst", "invoices"):
        assert word not in kept, word
    assert "req.method !== 'GET'" in sw, "only reads are ever answered from the cache"


def test_signing_out_wipes_the_offline_copy():
    assert "forgetOfflineCopy()" in read("app.js")
    assert "forgetOfflineCopy()" in read("staff-portal.js")
    assert "caches.delete('yerp-api')" in read("offline.js")


def test_a_diary_without_signal_goes_to_the_outbox():
    d = read("diary.js")
    assert "outboxKeepDiary(" in d and "navigator.onLine" in d
    html = read("app.html")
    assert 'id="diary-outbox"' in html and 'id="offline-bar"' in html and "offline.js" in html


def test_the_camera_opens_straight_from_the_diary_the_photos_and_the_chat():
    html = read("app.html")
    assert html.count('capture="environment"') >= 3
