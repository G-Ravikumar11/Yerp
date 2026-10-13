"""The update checks: the newest android-v<N> APK and the newest web-v<N> screens, or version 0."""
from app.routers import app_updates


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _fresh(monkeypatch, releases):
    app_updates._cache.update(at=0.0, releases=[])
    monkeypatch.setattr(app_updates.httpx, "get", lambda *a, **k: _Resp(releases))


def test_newest_android_release_with_an_apk(client, monkeypatch):
    _fresh(monkeypatch, [
        {"tag_name": "v-something-else", "assets": [{"name": "x.apk", "browser_download_url": "u0"}]},
        {"tag_name": "android-v9", "draft": True, "assets": [{"name": "a.apk", "browser_download_url": "u9"}]},
        {"tag_name": "android-v7", "name": "Y ERP 1.0.7", "assets": [{"name": "Yerp-1.0.7.apk", "browser_download_url": "u7"}]},
    ])
    body = client.get("/api/app/android/latest").json()
    assert body["version_code"] == 7 and body["apk_url"] == "u7" and body["version_name"] == "Y ERP 1.0.7"


def test_nothing_published_or_github_down(client, monkeypatch):
    _fresh(monkeypatch, [])
    assert client.get("/api/app/android/latest").json() == {"version_code": 0}

    def boom(*a, **k):
        raise RuntimeError("no network")
    app_updates._cache.update(at=0.0, releases=[])
    monkeypatch.setattr(app_updates.httpx, "get", boom)
    assert client.get("/api/app/android/latest").json() == {"version_code": 0}


def test_newest_web_bundle_and_what_app_it_needs(client, monkeypatch):
    _fresh(monkeypatch, [
        {"tag_name": "web-v12", "body": "Screens 12\nmin_native=0", "assets": [{"name": "web-12.zip", "browser_download_url": "z12"}]},
        {"tag_name": "web-v15", "body": "min_native=4", "assets": [{"name": "web-15.zip", "browser_download_url": "z15"}]},
        {"tag_name": "web-v20", "assets": []},
        {"tag_name": "web-v30", "prerelease": True, "assets": [{"name": "web-30.zip", "browser_download_url": "z30"}]},
        {"tag_name": "android-v99", "assets": [{"name": "a.apk", "browser_download_url": "a99"}]},
    ])
    assert client.get("/api/app/web/latest").json() == {"version": 15, "zip_url": "z15", "min_native": 4}
    # The two kinds of release do not get in each other's way.
    assert client.get("/api/app/android/latest").json()["version_code"] == 99


def test_web_bundle_without_a_note_works_in_any_app_and_none_published(client, monkeypatch):
    _fresh(monkeypatch, [{"tag_name": "web-v3", "assets": [{"name": "web-3.zip", "browser_download_url": "z3"}]}])
    assert client.get("/api/app/web/latest").json() == {"version": 3, "zip_url": "z3", "min_native": 0}
    _fresh(monkeypatch, [])
    assert client.get("/api/app/web/latest").json() == {"version": 0}
