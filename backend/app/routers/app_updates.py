"""The newest Android app and the newest screens, for the update prompts inside the phone app.

The mobile workflow publishes two kinds of GitHub Release:
  android-v<n>  a signed APK. A new native shell: installed by the person, from the "Update available" prompt.
  web-v<n>      web-<n>.zip, the app's screens only. Downloaded by the app itself and used the next time it opens,
                with nothing to install. Its notes carry "min_native=<n>": the oldest installed APK (by version code)
                the screens work in, so a bundle that needs a newer native plugin is never pushed to an older app, and
                "sha256=<hex>": the zip's fingerprint, which the phone checks the download against. A release without
                one is not offered: the phone's updater refuses a download it cannot check.
The app asks here rather than GitHub itself: one place to change where builds live, and no browser cross-origin rules
to get round.
"""
import os
import re
import time

import httpx
from fastapi import APIRouter

from app.core.config import logger


router = APIRouter()

_ANDROID_TAG = re.compile(r"^android-v(\d+)$")
_WEB_TAG = re.compile(r"^web-v(\d+)$")
_MIN_NATIVE = re.compile(r"min_native=(\d+)")
_SHA256 = re.compile(r"sha256=([0-9a-fA-F]{64})")
_CACHE_SECONDS = 600
_cache = {"at": 0.0, "releases": []}


def _releases():
    """The repository's recent releases, read from GitHub at most every few minutes. Kept as they were on a failed read."""
    now = time.time()
    if now - _cache["at"] > _CACHE_SECONDS:
        repo = os.getenv("APP_RELEASES_REPO", "G-Ravikumar11/Yerp").strip()
        headers = {"Accept": "application/vnd.github+json"}
        token = os.getenv("GITHUB_TOKEN", "").strip()  # optional: only raises GitHub's rate limit
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            # Every build adds a web release, so look far enough back to still find the newest APK.
            r = httpx.get("https://api.github.com/repos/%s/releases?per_page=100" % repo, headers=headers, timeout=10)
            r.raise_for_status()
            _cache["releases"] = [rel for rel in r.json() if not rel.get("draft") and not rel.get("prerelease")]
        except Exception as exc:
            logger.warning("Could not read the latest app release: %s", exc)
        _cache["at"] = now
    return _cache["releases"]


def _newest(tag_pattern, asset_suffix):
    """(version number, release, asset) of the highest-numbered release with that tag and an asset ending so."""
    best = None
    for rel in _releases():
        m = tag_pattern.match(rel.get("tag_name") or "")
        if not m:
            continue
        asset = next((a for a in rel.get("assets") or [] if (a.get("name") or "").endswith(asset_suffix)), None)
        if asset and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), rel, asset)
    return best


@router.get("/api/app/android/latest")
def latest_android_app():
    """{version_code, version_name, apk_url, notes}, or {version_code: 0} when nothing is published or GitHub is unreachable."""
    found = _newest(_ANDROID_TAG, ".apk")
    if not found:
        return {"version_code": 0}
    number, rel, apk = found
    return {"version_code": number, "version_name": rel.get("name") or rel["tag_name"],
            "apk_url": apk["browser_download_url"], "notes": (rel.get("body") or "")[:500]}


@router.get("/api/app/web/latest")
def latest_web_bundle():
    """{version, zip_url, checksum, min_native}: the newest screens that can be checked, and the oldest installed app they
    work in. {version: 0} when there are none."""
    best = None
    for rel in _releases():
        m = _WEB_TAG.match(rel.get("tag_name") or "")
        digest = _SHA256.search(rel.get("body") or "")
        zipped = next((a for a in rel.get("assets") or [] if (a.get("name") or "").endswith(".zip")), None)
        if m and digest and zipped and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), rel, zipped, digest.group(1).lower())
    if not best:
        return {"version": 0}
    number, rel, zipped, checksum = best
    floor = _MIN_NATIVE.search(rel.get("body") or "")
    return {"version": number, "zip_url": zipped["browser_download_url"], "checksum": checksum,
            "min_native": int(floor.group(1)) if floor else 0}
