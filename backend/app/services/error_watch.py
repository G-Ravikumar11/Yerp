"""Watching the server's own faults, for the platform admin (the super-admin), not the companies.

A company's Master sees its errors in Settings > Error log - the code, the ref, the message - but not the traceback:
that is the platform's code, read by whoever runs the platform. The super-admin sees every company's errors with the
traceback, and is told when server faults (YE-SRV) spike: an hour with at least ERROR_SPIKE_THRESHOLD of them (10
unless set) and three times the usual hourly rate of the day before. The alert is emailed to PLATFORM_ALERT_EMAIL when
it is set, and is always shown on the super-admin page and in the server log.
"""
import os
from datetime import datetime, timedelta

from app import models
from app.core.config import logger
from app.core.scheduler import scheduled_job

SERVER_FAULT = "YE-SRV%"


def _threshold():
    try:
        return max(1, int(os.getenv("ERROR_SPIKE_THRESHOLD", "10")))
    except ValueError:
        return 10


def _count(db, since, until):
    return db.query(models.DBErrorLog.id).filter(models.DBErrorLog.code.like(SERVER_FAULT), models.DBErrorLog.at >= since,
                                                 models.DBErrorLog.at < until).count()


def spike(db, now=None):
    """This hour's server faults against the usual: {"last_hour", "usual_per_hour", "threshold", "spiking"}."""
    now = now or datetime.now()
    fmt = "%Y-%m-%d %H:%M:%S"
    hour_ago, day_ago = now - timedelta(hours=1), now - timedelta(hours=25)
    last = _count(db, hour_ago.strftime(fmt), now.strftime(fmt))
    usual = _count(db, day_ago.strftime(fmt), hour_ago.strftime(fmt)) / 24.0
    limit = _threshold()
    return {"last_hour": last, "usual_per_hour": round(usual, 1), "threshold": limit,
            "spiking": last >= limit and last >= 3 * usual}


def hour_key(now=None):
    return (now or datetime.now()).strftime("%Y-%m-%d %H")


@scheduled_job("error_spike_alert", hour_key)
def job_error_spike_alert(db, now):
    """At most once an hour: tell the platform admin when server faults spike."""
    s = spike(db, now)
    if not s["spiking"]:
        return "%d server faults in the last hour (usual %s)" % (s["last_hour"], s["usual_per_hour"])
    paths = {}
    since = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    for (path,) in db.query(models.DBErrorLog.path).filter(models.DBErrorLog.code.like(SERVER_FAULT), models.DBErrorLog.at >= since).all():
        paths[path or "?"] = paths.get(path or "?", 0) + 1
    worst = ", ".join("%s (%d)" % p for p in sorted(paths.items(), key=lambda p: -p[1])[:5])
    text = ("Server faults are spiking: %d in the last hour against a usual %s an hour. Most from: %s. "
            "Every one, with its traceback, is under Server errors on the super-admin page." % (s["last_hour"], s["usual_per_hour"], worst))
    logger.error(text)
    to = (os.getenv("PLATFORM_ALERT_EMAIL") or "").strip()
    if to:
        from app.core.notifications import default_from_email, send_email_background
        ok, why = send_email_background(to, "Y ERP: server faults spiking (%d in an hour)" % s["last_hour"], text,
                                        "Y ERP <%s>" % default_from_email())
        return "spike: %d; emailed %s: %s" % (s["last_hour"], to, "sent" if ok else why)
    return "spike: %d; PLATFORM_ALERT_EMAIL is not set, so it is in the log only" % s["last_hour"]
