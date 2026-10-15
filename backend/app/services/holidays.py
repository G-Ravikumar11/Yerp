"""The days the business has marked as holidays, which every employee has off."""
from app import models


def custom_holidays(db, client_id, start=None, end=None):
    """{YYYY-MM-DD: name} for the business's own holidays, optionally only those from `start` to `end` (inclusive)."""
    q = db.query(models.DBCustomHoliday.date, models.DBCustomHoliday.name).filter(
        models.DBCustomHoliday.client_id == client_id)
    if start is not None:
        q = q.filter(models.DBCustomHoliday.date >= str(start))
    if end is not None:
        q = q.filter(models.DBCustomHoliday.date <= str(end))
    return {d: n for d, n in q.all()}
