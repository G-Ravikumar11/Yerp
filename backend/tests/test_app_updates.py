"""The "Update available" check: the newest android-v<N> release with an APK, or version 0."""
from app.routers import app_updates


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _fresh(monkeypatch, releases):
    app_updates._cache.update(at=0.0, value=None)
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
    app_updates._cache.update(at=0.0, value=None)
    monkeypatch.setattr(app_updates.httpx, "get", boom)
    assert client.get("/api/app/android/latest").json() == {"version_code": 0}
