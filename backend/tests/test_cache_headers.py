"""What a browser may keep, and what it must ask about again.

The app's pages must always be asked about: a copy kept across a deploy names
script files that no longer exist, and the app opens blank until the cache is
cleared by hand. Files named by a hash of their contents can be kept for good,
because a changed file arrives under a new name."""
import os
import re

from _frontend import FRONTEND_DIST, needs_frontend_build

pytestmark = needs_frontend_build


def cache_control(client, path):
    res = client.get(path)
    assert res.status_code == 200, (path, res.status_code)
    return res.headers.get("cache-control", ""), res


def test_the_app_shell_is_always_revalidated(client):
    for path in ("/next/", "/next/index.html"):
        header, _ = cache_control(client, path)
        assert "no-cache" in header or "no-store" in header, "%s: %r" % (path, header)


def test_a_page_inside_the_app_is_revalidated_too(client):
    # Not a file: answered with index.html so the app's router can draw it.
    header, res = cache_control(client, "/next/people/departments")
    assert res.headers["content-type"].startswith("text/html")
    assert "no-cache" in header or "no-store" in header, repr(header)


def test_hashed_files_are_kept_for_good(client):
    assets = os.path.join(FRONTEND_DIST, "assets")
    hashed = next(f for f in os.listdir(assets) if re.search(r"-[A-Za-z0-9_-]{6,}\.js$", f))
    header, _ = cache_control(client, "/next/assets/" + hashed)
    assert "immutable" in header and "max-age=31536000" in header, repr(header)


def test_the_service_worker_is_never_kept(client):
    header, _ = cache_control(client, "/next/sw.js")
    assert "no-cache" in header or "no-store" in header, repr(header)


def test_pictures_that_keep_their_name_are_kept_briefly_then_checked(client):
    icons = os.path.join(FRONTEND_DIST, "icons")
    picture = next(f for f in os.listdir(icons) if f.endswith(".png"))
    header, res = cache_control(client, "/next/icons/" + picture)
    assert "max-age=3600" in header and "immutable" not in header, repr(header)
    assert res.headers.get("etag"), "so the check after the hour is a 304, not the whole file again"


# --- which build is live, and starting a device clean -----------------------------------------------------------------

def test_every_answer_says_which_build_is_live(client, monkeypatch, tmp_path):
    """An open app that sees a newer build loads it at the next change of screen (frontend/src/lib/freshness.ts)."""
    from app.core import config
    (tmp_path / "build.json").write_text('{"build": "1790000000000"}', encoding="utf-8")
    monkeypatch.setattr(config, "FRONTEND_DIST", str(tmp_path))
    assert client.get("/api/health").headers.get("X-App-Build") == "1790000000000"
    # a rebuild on a running server is noticed
    (tmp_path / "build.json").write_text('{"build": "1790000099999"}', encoding="utf-8")
    os.utime(tmp_path / "build.json", (2_000_000_000, 2_000_000_000))
    assert client.get("/api/health").headers.get("X-App-Build") == "1790000099999"


def test_with_no_build_nothing_is_claimed(client, monkeypatch, tmp_path):
    from app.core import config
    monkeypatch.setattr(config, "FRONTEND_DIST", str(tmp_path))
    assert "X-App-Build" not in client.get("/api/health").headers


def test_the_operator_can_ask_every_device_to_start_clean(client, monkeypatch):
    from _patching import patch_app
    assert "X-Client-Reset" not in client.get("/api/health").headers
    patch_app(monkeypatch, "CLIENT_RESET", "2026-10-14")
    assert client.get("/api/health").headers.get("X-Client-Reset") == "2026-10-14"


def test_the_reset_page_empties_the_browsers_cache_but_not_its_storage(client):
    """Storage holds offline saves not yet sent, and cookies the sign-in: only the cache is cleared."""
    res = client.get("/next/reset")
    assert res.headers.get("Clear-Site-Data") == '"cache"'
    assert "storage" not in res.headers.get("Clear-Site-Data") and "cookies" not in res.headers.get("Clear-Site-Data")
