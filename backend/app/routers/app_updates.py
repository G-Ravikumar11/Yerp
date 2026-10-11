"""The newest Android app, for the "Update available" prompt inside the app.

Each signed build is published by the mobile workflow as a GitHub Release tagged android-v<version code>, with the
APK attached. The app asks here rather than GitHub itself: one place to change where builds live, and no browser
cross-origin rules to get round.
"""
import os
import re
import time

import httpx
from fastapi import APIRouter

from app.core.config import logger


router = APIRouter()

_TAG = re.compile(r"^android-v(\d+)$")
_CACHE_SECONDS = 600
_cache = {"at": 0.0, "value": None}


def _latest_from_github():
    repo = os.getenv("APP_RELEASES_REPO", "G-Ravikumar11/Yerp").strip()
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN", "").strip()  # optional: only raises GitHub's rate limit
    if token:
        headers["Authorization"] = "Bearer " + token
    r = httpx.get("https://api.github.com/repos/%s/releases?per_page=20" % repo, headers=headers, timeout=10)
    r.raise_for_status()
    for rel in r.json():
        m = _TAG.match(rel.get("tag_name") or "")
        if not m or rel.get("draft") or rel.get("prerelease"):
            continue
        apk = next((a for a in rel.get("assets") or [] if (a.get("name") or "").endswith(".apk")), None)
        if apk:
            return {"version_code": int(m.group(1)), "version_name": rel.get("name") or rel["tag_name"],
                    "apk_url": apk["browser_download_url"], "notes": (rel.get("body") or "")[:500]}
    return None


@router.get("/api/app/android/latest")
def latest_android_app():
    """{version_code, version_name, apk_url, notes}, or {version_code: 0} when nothing is published or GitHub is unreachable."""
    now = time.time()
    if now - _cache["at"] > _CACHE_SECONDS:
        try:
            _cache["value"] = _latest_from_github()
        except Exception as exc:
            logger.warning("Could not read the latest app release: %s", exc)
        _cache["at"] = now
    return _cache["value"] or {"version_code": 0}
