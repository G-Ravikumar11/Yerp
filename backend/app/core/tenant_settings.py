"""Company-wide settings kept in the database."""
from sqlalchemy import case, event, func
from sqlalchemy.orm import Session

from app import models


# A page reads several settings - the approval limits, the owner-signs switches, the payment rules - and each was a query of
# its own. The first read in a request now takes all of the company's small settings in one query, and the rest are answered
# from it. A value too big to carry about (a signature or seal image) is left out and read by itself when asked for. Anything
# written, committed or rolled back in the session throws what was read away, so a read never sees a setting out of date.
_SMALL = 4000


def _changing(session):
    return any(isinstance(o, models.DBSettings) for o in (*session.new, *session.dirty, *session.deleted))


def _settings_of(db, client_id):
    held = db.info.setdefault("settings", {})
    if client_id not in held:
        size = func.length(models.DBSettings.value)
        rows = db.query(models.DBSettings.key, case((size <= _SMALL, models.DBSettings.value), else_=None), size).filter(
            models.DBSettings.client_id == client_id).order_by(models.DBSettings.id).all()
        mine = {}
        for k, v, n in rows:
            mine.setdefault(k, (v, (n or 0) > _SMALL))     # {key: (value, too big to hold)}; the first row of a key, as before
        held[client_id] = mine
    return held[client_id]


def tenant_setting(db, client_id, key, default=""):
    if _changing(db):
        # A setting changed here and not yet saved: ask for this one itself, as the session holds it.
        db.info.pop("settings", None)
        row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == key).first()
        return row.value if row and row.value not in (None, "") else default
    got = _settings_of(db, client_id).get(key)
    if got is None:
        return default
    value, big = got
    if big:
        row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == key).first()
        value = row.value if row else None
    return value if value not in (None, "") else default


def _forget_settings(session, *_):
    session.info.pop("settings", None)


@event.listens_for(Session, "before_flush")
def _settings_changed(session, flush_context, instances):
    if session.info.get("settings") and _changing(session):
        session.info.pop("settings", None)


event.listen(Session, "after_commit", _forget_settings)
event.listen(Session, "after_rollback", _forget_settings)


#
# What prints on a work order is only as good as what is on file. The company
# block, the contractor's PAN and GSTIN, the conditions and the signatures could be
# entered once and never corrected; these routes let them be kept up.
def put_setting(db, client_id, key, value):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id,
                                             models.DBSettings.key == key).first()
    if row:
        row.value = value
    else:
        db.add(models.DBSettings(client_id=client_id, key=key, value=value))
