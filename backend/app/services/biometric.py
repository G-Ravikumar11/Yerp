"""Attendance from the biometric machines.

A small program in the office reads the attendance system's database and sends each new punch here (see
tools/biometric_sync). Every punch is kept; a day's attendance is worked out again from all of that person's punches
each time one arrives:
    the first punch of the day is the clock-in
    the last is the clock-out - when the machine says it was an "out", or, where the machine does not say, when the
    day has an even number of punches (in, out, in, out). An odd number means the person is inside.
A day somebody also clocked in on the phone keeps the earlier clock-in and the later clock-out of the two.
"""
import hashlib
import hmac
import io
import re
import secrets
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from app import models
from app.core.tenant_settings import put_setting, tenant_setting
from app.models.biometric import DBBiometricDevice, DBBiometricPunch

KEY_SETTING, LAST_SYNC, LAST_AGENT = "biometric_key_hash", "biometric_last_sync", "biometric_agent"
MAX_BATCH = 2000
SAME_PUNCH_SECONDS = 60             # a finger pressed twice: one punch


def _hash(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_key(db, client_id):
    """A new secret for the office program; the old one stops working. Returned once - only its hash is kept."""
    key = "ybio_%d_%s" % (client_id, secrets.token_urlsafe(32))
    put_setting(db, client_id, KEY_SETTING, _hash(key))
    return key


def client_for_key(db, key):
    """The company a key belongs to, or 401."""
    m = re.match(r"^ybio_(\d+)_[A-Za-z0-9_\-]{20,}$", (key or "").strip())
    if not m:
        raise HTTPException(401, "The biometric key is missing or not of the right form.")
    client = db.query(models.DBClient).filter(models.DBClient.id == int(m.group(1)), models.DBClient.is_active.is_(True)).first()
    kept = tenant_setting(db, client.id, KEY_SETTING, "") if client else ""
    if not kept or not hmac.compare_digest(kept, _hash(key.strip())):
        raise HTTPException(401, "That biometric key is not in use. Make a new one under People > Attendance > Biometric.")
    return client


def norm_id(value):
    """A person's number as it is compared: no spaces, no leading noughts, capitals. "0045", "45" and " 45 " are one."""
    s = re.sub(r"\s", "", str(value or "")).upper()
    return s.lstrip("0") or ("0" if s else "")


def employee_index(db, client_id):
    """{normalised number: employee} - the biometric number where HR has set one, the employee code otherwise."""
    out = {}
    people = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id).all()
    for e in people:                                    # the employee code first...
        if norm_id(e.employee_id):
            out.setdefault(norm_id(e.employee_id), e)
    for e in people:                                    # ...then a number HR set by hand, which wins
        if norm_id(e.biometric_id):
            out[norm_id(e.biometric_id)] = e
    return out


def _when(value):
    """YYYY-MM-DD HH:MM:SS from what the program sent, or None."""
    s = str(value or "").strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _direction(value):
    s = str(value or "").strip().lower()
    if s in ("in", "i", "checkin", "check-in", "0"):
        return "in"
    if s in ("out", "o", "checkout", "check-out", "1"):
        return "out"
    return ""


def take_punches(db, client, rows, agent=""):
    """Keep the punches sent and bring the attendance of everybody they touch up to date.
    Returns {"received", "new", "duplicates", "unmatched", "refused", "days"}."""
    if len(rows) > MAX_BATCH:
        raise HTTPException(413, "Send at most %d punches at a time." % MAX_BATCH)
    people = employee_index(db, client.id)
    now = datetime.now()
    new = dup = refused = 0
    unmatched, touched, devices = set(), set(), {}
    have = set()
    stamps = [w.strftime("%Y-%m-%d %H:%M:%S") for w in (_when(r.get("time")) for r in rows) if w]
    if stamps:
        for b, t, d in db.query(DBBiometricPunch.biometric_id, DBBiometricPunch.punched_at, DBBiometricPunch.device_code).filter(
                DBBiometricPunch.client_id == client.id, DBBiometricPunch.punched_at >= min(stamps),
                DBBiometricPunch.punched_at <= max(stamps)).all():
            have.add((b, t, d))
    for r in rows:
        bid, when = norm_id(r.get("employee_code")), _when(r.get("time"))
        # A machine with a wrong clock can send next year's punches; one from long ago is history, not attendance to redo.
        if not bid or when is None or when > now + timedelta(minutes=10) or when < now - timedelta(days=120):
            refused += 1
            continue
        stamp, device = when.strftime("%Y-%m-%d %H:%M:%S"), str(r.get("device") or "").strip()[:60]
        if (bid, stamp, device) in have:
            dup += 1
            continue
        have.add((bid, stamp, device))
        emp = people.get(bid)
        db.add(DBBiometricPunch(client_id=client.id, biometric_id=bid, punched_at=stamp, device_code=device,
                                direction=_direction(r.get("direction")), employee_id=emp.id if emp else None,
                                employee_name=" ".join(str(r.get("employee_name") or "").split())[:100]))
        new += 1
        if device:
            devices[device] = max(devices.get(device, ""), stamp)
        if emp is None:
            unmatched.add(bid)
        else:
            touched.add((emp.id, stamp[:10]))
    db.flush()
    known = {d.device_code: d for d in db.query(DBBiometricDevice).filter(DBBiometricDevice.client_id == client.id).all()}
    for code, last in devices.items():
        d = known.get(code)
        if d is None:
            d = DBBiometricDevice(client_id=client.id, device_code=code, name="Machine %s" % code)
            db.add(d)
            known[code] = d
        d.last_punch_at = max(d.last_punch_at or "", last)
    db.flush()
    for emp_id, day in sorted(touched):
        apply_day(db, client.id, emp_id, day, known)
    put_setting(db, client.id, LAST_SYNC, now.strftime("%Y-%m-%d %H:%M:%S"))
    if agent:
        put_setting(db, client.id, LAST_AGENT, str(agent)[:120])
    return {"received": len(rows), "new": new, "duplicates": dup, "unmatched": sorted(unmatched), "refused": refused,
            "days": len(touched)}


def _distinct(punches):
    """The day's punches with a finger pressed twice within a minute counted once."""
    out = []
    for p in punches:
        t = datetime.strptime(p.punched_at, "%Y-%m-%d %H:%M:%S")
        if out and (t - out[-1][0]).total_seconds() < SAME_PUNCH_SECONDS:
            if p.direction and not out[-1][1].direction:
                out[-1] = (out[-1][0], p)
            continue
        out.append((t, p))
    return out


def apply_day(db, client_id, employee_id, day, devices=None):
    """Work one person's day out again from their punches. Does not commit."""
    from app.services.employee_portal import attendance_settings_for, end_shift
    punches = db.query(DBBiometricPunch).filter(
        DBBiometricPunch.client_id == client_id, DBBiometricPunch.employee_id == employee_id,
        DBBiometricPunch.punched_at >= day + " 00:00:00", DBBiometricPunch.punched_at <= day + " 23:59:59").order_by(
        DBBiometricPunch.punched_at).all()
    seen = _distinct(punches)
    if not seen:
        return None
    first, last = seen[0], seen[-1]
    says = last[1].direction
    # Out, when the machine says so; where it does not, an even number of punches (in, out, in, out) ends outside.
    gone = len(seen) > 1 and (says == "out" or (says == "" and len(seen) % 2 == 0))
    bio_in = first[0].strftime("%H:%M:%S")
    bio_out = last[0] if gone else None

    att = db.query(models.DBAttendance).filter(models.DBAttendance.client_id == client_id,
                                               models.DBAttendance.employee_id == employee_id, models.DBAttendance.date == day).first()
    if devices is None:
        devices = {d.device_code: d for d in db.query(DBBiometricDevice).filter(DBBiometricDevice.client_id == client_id).all()}
    device = devices.get(first[1].device_code)
    label = (device.name if device and device.name else "Biometric machine %s" % (first[1].device_code or "")).strip()
    if att is None:
        att = models.DBAttendance(client_id=client_id, employee_id=employee_id, date=day, clock_in=bio_in, status="present",
                                  check_type="biometric", device_info="Biometric", location_label=label[:120],
                                  job_id=device.job_id if device else None)
        db.add(att)
        phone = False
    else:
        phone = (att.check_type or "") != "biometric"
        if not att.clock_in or bio_in < att.clock_in:
            att.clock_in = bio_in                           # the earlier of the two
        if (att.status or "") == "absent":
            att.status = "present"
        if not att.job_id and device and device.job_id:
            att.job_id = device.job_id
        if not phone:
            att.location_label = label[:120]
        elif "biometric" not in (att.notes or "").lower():
            att.notes = ((att.notes or "") + " Also punched on the biometric machine.").strip()[:300]

    # Late, by the company's hours - as a clock-in on the phone is judged.
    settings = attendance_settings_for(db, client_id)
    if settings and settings.work_start and (att.status or "") in ("present", "late"):
        try:
            late_by = (datetime.strptime("%s %s" % (day, att.clock_in), "%Y-%m-%d %H:%M:%S")
                       - datetime.strptime("%s %s" % (day, settings.work_start), "%Y-%m-%d %H:%M")).total_seconds() / 60
            att.status = "late" if late_by > (settings.grace_minutes or 0) else "present"
        except (ValueError, TypeError):
            pass

    if bio_out is not None:
        keep = None
        if phone and att.clock_out and att.clock_out > bio_out.strftime("%H:%M:%S"):
            keep = datetime.strptime("%s %s" % (day, att.clock_out), "%Y-%m-%d %H:%M:%S")      # the later of the two
        end_shift(db, att, client_id, keep or bio_out)
    elif not phone and att.clock_out:
        # Back inside after a punch that had looked like leaving: the day is open again.
        att.clock_out, att.total_hours, att.overtime_hours = "", 0.0, 0.0
        if (att.status or "") == "completed":
            att.status = "present"
    return att


def rematch(db, client_id):
    """Punches that belonged to nobody, now that somebody's number may have been filled in. Returns how many found
    their person."""
    people = employee_index(db, client_id)
    waiting = db.query(DBBiometricPunch).filter(DBBiometricPunch.client_id == client_id, DBBiometricPunch.employee_id.is_(None)).all()
    touched, found = set(), 0
    for p in waiting:
        emp = people.get(p.biometric_id)
        if emp is not None:
            p.employee_id = emp.id
            touched.add((emp.id, p.punched_at[:10]))
            found += 1
    db.flush()
    for emp_id, day in sorted(touched):
        apply_day(db, client_id, emp_id, day)
    return found


def _tokens(name):
    return set(re.sub(r"[^a-z ]", " ", (name or "").lower()).split())


def suggest_person(candidates, name):
    """The one employee a machine's name for somebody most plainly is, or None. `candidates` are (id, display name).
    The same words (in any order) or - from two words up - all the words of the shorter name inside the longer one
    ("Ravi Kumar" is "Ravi Kumar Reddy"). More than one possible person is no suggestion: a wrong match counts someone
    else's attendance."""
    want = _tokens(name)
    if not want:
        return None
    hits = []
    for emp_id, shown in candidates:
        have = _tokens(shown)
        if not have:
            continue
        same = want == have
        inside = min(len(want), len(have)) >= 2 and (want <= have or have <= want)
        if same or inside:
            hits.append((emp_id, shown))
    return {"id": hits[0][0], "name": hits[0][1]} if len(hits) == 1 else None


SETUP_FILES = ("sync.py", "SETUP.bat", "get_python.ps1", "run_check.bat", "run_now.bat", "install_task.bat", "remove_task.bat",
               "make_reader_login.sql", "README.md")


def setup_package(db, client, base_url):
    """The office program as a zip, with its config.ini already holding this company's address and a NEW key (the one
    before it stops working). Unzip on the office computer and double-click SETUP.bat."""
    folder = Path(__file__).resolve().parents[3] / "tools" / "biometric_sync"
    key = new_key(db, client.id)
    crlf = lambda text: text.replace("\r\n", "\n").replace("\n", "\r\n")        # batch files need Windows line ends
    config = ("; Made by Y ERP for %s. Safe to edit by hand; the set-up fills in the database part.\n"
              "[yerp]\nurl = %s\napi_key = %s\nevery_seconds = 60\noverlap_minutes = 30\n\n"
              "[database]\nserver =\nname =\nuser =\npassword =\ndriver =\nsource = auto\nsend = code\n"
              % (client.company_name or "this company", base_url.rstrip("/"), key))
    start = ("START HERE\n\n1. Copy this whole folder to the computer that holds the attendance system's database "
             "(for example C:\\YERP\\biometric_sync).\n2. Double-click SETUP.bat and answer what it asks. It finds the database, "
             "makes a read-only login, sends the first punches and starts the every-minute sync.\n\n"
             "config.ini holds this company's key. Do not share the folder; if it gets out, make a new key in Y ERP "
             "(People > Attendance > Biometric) and the old one stops working.\n")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in SETUP_FILES:
            path = folder / name
            if path.exists():
                z.writestr("biometric_sync/" + name, crlf(path.read_text(encoding="utf-8")))
        z.writestr("biometric_sync/config.ini", crlf(config))
        z.writestr("biometric_sync/START HERE.txt", crlf(start))
    return out.getvalue()


def status(db, client_id):
    from app.services.hr import employee_name
    today = datetime.now().strftime("%Y-%m-%d")
    last = tenant_setting(db, client_id, LAST_SYNC, "")
    stale = None
    if last:
        try:
            stale = int((datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).total_seconds() // 60)
        except ValueError:
            stale = None
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    waiting = {}
    for bid, at, who in db.query(DBBiometricPunch.biometric_id, DBBiometricPunch.punched_at, DBBiometricPunch.employee_name).filter(
            DBBiometricPunch.client_id == client_id, DBBiometricPunch.employee_id.is_(None)).all():
        w = waiting.setdefault(bid, {"biometric_id": bid, "punches": 0, "last": "", "name": "", "suggestion": None})
        w["punches"] += 1
        if at >= w["last"]:
            w["last"] = at
            w["name"] = who or w["name"]
    people = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id).order_by(models.DBEmployee.first_name).all()
    free = [(e.id, employee_name(e)) for e in people if not norm_id(e.biometric_id)
            and (e.status or "active") not in ("terminated", "left", "inactive")]
    for w in waiting.values():
        w["suggestion"] = suggest_person(free, w["name"])
    return {
        "connected": bool(tenant_setting(db, client_id, KEY_SETTING, "")), "last_sync": last, "minutes_since_sync": stale,
        "agent": tenant_setting(db, client_id, LAST_AGENT, ""),
        "punches_today": db.query(DBBiometricPunch).filter(DBBiometricPunch.client_id == client_id,
                                                           DBBiometricPunch.punched_at >= today + " 00:00:00").count(),
        "people_today": db.query(models.DBAttendance).filter(models.DBAttendance.client_id == client_id, models.DBAttendance.date == today,
                                                             models.DBAttendance.check_type == "biometric").count(),
        "devices": [{"id": d.id, "device_code": d.device_code, "name": d.name or "", "job_id": d.job_id,
                     "site": (jobs[d.job_id].name if d.job_id in jobs else ""), "last_punch_at": d.last_punch_at or ""}
                    for d in db.query(DBBiometricDevice).filter(DBBiometricDevice.client_id == client_id).order_by(DBBiometricDevice.device_code).all()],
        "unmatched": sorted(waiting.values(), key=lambda w: -w["punches"])[:200],
        "employees": [{"id": e.id, "name": employee_name(e), "employee_code": e.employee_id or "", "biometric_id": e.biometric_id or "",
                       "status": e.status or ""} for e in people if (e.status or "active") not in ("terminated", "left", "inactive")],
    }
