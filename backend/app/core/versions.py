"""An edit made on a copy that somebody else has since changed.

A phone that was out of signal keeps an edit and sends it later, with the version of the record it started from (the
`X-Base-Version` header: the record's `updated_at` as it was read). If the record has moved on since, the edit is refused
and says so in these words, and the app asks the person whose version stands, "keep mine" or "take theirs", instead of the
last save silently winning. A request with no version is not checked: it is the website, or a phone that was online, and
there the last save has always won.
"""
from fastapi import HTTPException, Request

# The app recognises a conflict by these words (CONFLICT_TEXT in frontend/src/stores/offline.ts): change them in both.
CONFLICT_TEXT = "was changed by somebody else"

# What a record that has never been edited has for a version, so that "none yet" can be sent as a value.
NO_VERSION = "-"


def version_of(stamp) -> str:
    return stamp or NO_VERSION


def check_base_version(request: Request, stamp, what: str):
    """Refuse the edit if the copy it started from is no longer the record's current one."""
    base = (request.headers.get("x-base-version") or "").strip()
    if base and base != version_of(stamp):
        raise HTTPException(409, "%s %s while you were away from signal." % (what, CONFLICT_TEXT))
