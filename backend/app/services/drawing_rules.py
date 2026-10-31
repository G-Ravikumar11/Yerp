"""The drawing register's rules.

- The current revision is the latest by its own name, not the last one typed in: R1 recorded late, after R2, goes on
  the register superseded, and R2 stays the one to build to. R0 < R1 < R10, A < B < Z < AA, P01 < P02.
- Every status change is logged, with what it was and what it became.
- A drawing that was ever released Good for construction stays on the register: something may have been built to it.
"""
import re

from app import models
from app.core.audit import log_audit

GFC = "Good for construction"
_REV = re.compile(r"^([A-Z]*)(\d*)(.*)$")


def revision_key(rev):
    """Order revision names: the same scheme compares by its number (R2 < R10) or letters (Z < AA); a name with digits
    sorts before a letters-only one, and anything else falls back to the text."""
    prefix, num, rest = _REV.match((rev or "").strip().upper()).groups()
    if num:
        return (0, prefix, int(num), rest)
    return (1, len(prefix), prefix, rest)


def is_later(rev, than):
    return not than or revision_key(rev) > revision_key(than)


def log_status(db, client_id, d, before, after, request=None, revision=""):
    """One audit line per status change of a drawing."""
    if (before or "") == (after or ""):
        return
    log_audit(db, client_id, "drawing_status", "drawing", d.id, d.number or "",
              "%s%s -> %s" % (("rev %s: " % revision) if revision else "", before or "(none)", after), request)
    if after == GFC:
        d.ever_gfc = True


def ever_gfc(db, d):
    """Released Good for construction at any time - now, on any revision, or by the log - and so never to be deleted."""
    if getattr(d, "ever_gfc", False) or d.status == GFC:
        return True
    if db.query(models.DBDrawingRevision.id).filter(models.DBDrawingRevision.drawing_id == d.id,
                                                    models.DBDrawingRevision.status == GFC).first():
        return True
    return db.query(models.DBAuditLog.id).filter(models.DBAuditLog.entity_type == "drawing", models.DBAuditLog.entity_id == d.id,
                                                 models.DBAuditLog.details.like("%" + GFC + "%")).first() is not None
