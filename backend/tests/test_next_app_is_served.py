"""The React app is served by the backend under /next/.

Any address inside the app that is not a file must serve the app itself (its
router draws the page), a missing file is a real 404, and the manifest and
service worker - what make it installable and usable with no signal - are
served as what they are.
"""
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BUILT = os.path.isdir(os.path.join(HERE, "..", "..", "frontend-next"))

pytestmark = pytest.mark.skipif(not BUILT, reason="frontend-next has not been built")


def test_the_app_opens_at_next(client):
    res = client.get("/next/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert '<div id="root">' in res.text


def test_a_page_inside_the_app_serves_the_app_so_a_reload_or_a_link_works(client):
    for path in ("/next/subcontractors/work-orders", "/next/subcontractors/work-orders/12", "/next/approvals"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert '<div id="root">' in res.text, path


def test_a_missing_file_is_a_404_not_the_app(client):
    res = client.get("/next/assets/does-not-exist.js")
    assert res.status_code == 404


def test_the_manifest_is_served_as_a_manifest(client):
    res = client.get("/next/manifest.webmanifest")
    assert res.status_code == 200
    assert "manifest+json" in res.headers["content-type"]
    manifest = res.json()
    assert manifest["scope"] == "/next/" and manifest["start_url"] == "/next/"
    assert manifest["display"] == "standalone"
    sizes = {i["sizes"] for i in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes


def test_the_icons_the_manifest_names_exist(client):
    manifest = client.get("/next/manifest.webmanifest").json()
    for icon in manifest["icons"]:
        res = client.get("/next/" + icon["src"])
        assert res.status_code == 200, icon["src"]
        assert res.headers["content-type"] == "image/png"


def test_the_service_worker_is_javascript_and_never_cached_stale(client):
    res = client.get("/next/sw.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]
    # A worker that browsers hold on to cannot be replaced by a new release.
    assert "no-cache" in res.headers["cache-control"]


def test_the_sign_in_pages_are_still_served_at_the_root_and_the_old_app_forwards(client):
    assert "/next/" in client.get("/app.html").text
    assert client.get("/login.html").status_code == 200       # forwarded to /next/login, which serves the app
    assert client.get("/next/login").status_code == 200
    assert client.get("/next/reset-password?token=x").status_code == 200
