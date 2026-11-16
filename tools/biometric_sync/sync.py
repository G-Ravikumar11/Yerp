"""Y ERP biometric sync: reads new punches from the eSSL eTimeTrackLite database and sends them to Y ERP.

Runs on the office computer that can reach the attendance system's SQL Server. It only READS that database.

    python sync.py --check      look at the database and the key, send nothing
    python sync.py --once       send what is new, then stop          (what the Windows scheduled task runs)
    python sync.py              keep running, sending every `every_seconds`
    python sync.py --backfill 30    also send the last 30 days (once, after setting up)

Settings are in config.ini beside this file (copy config.example.ini). What has been sent is remembered in state.json,
so a restart sends nothing twice - and Y ERP ignores a punch it already has.
"""
import argparse
import configparser
import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
STATE = os.path.join(HERE, "state.json")
BATCH = 500
log = logging.getLogger("yerp-biometric")


def settings():
    path = os.path.join(HERE, "config.ini")
    if not os.path.exists(path):
        sys.exit("config.ini is missing. Copy config.example.ini to config.ini and fill it in.")
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    return cfg


def connect(cfg):
    try:
        import pyodbc
    except ImportError:
        sys.exit("pyodbc is not installed. Run:  pip install pyodbc")
    db = cfg["database"]
    driver = db.get("driver", "").strip()
    if not driver:
        have = pyodbc.drivers()
        for want in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server Native Client 11.0", "SQL Server"):
            if want in have:
                driver = want
                break
        if not driver:
            sys.exit("No SQL Server ODBC driver found on this computer. Drivers here: %s" % ", ".join(have))
    parts = ["DRIVER={%s}" % driver, "SERVER=%s" % db.get("server", "localhost"), "DATABASE=%s" % db.get("name", "etimetracklite"),
             "ApplicationIntent=ReadOnly"]
    if db.get("user", "").strip():
        parts += ["UID=%s" % db["user"], "PWD=%s" % db.get("password", "")]
    else:
        parts.append("Trusted_Connection=yes")          # the Windows account the program runs as
    if "18" in driver:
        parts.append("TrustServerCertificate=yes")
    return pyodbc.connect(";".join(parts), timeout=15, autocommit=True)


def columns(cur, table):
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?", table)
    return {r[0].lower(): r[0] for r in cur.fetchall()}


def tables_like(cur, pattern):
    cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE ?", pattern)
    return [r[0] for r in cur.fetchall()]


def pick(cols, *names):
    for n in names:
        if n.lower() in cols:
            return cols[n.lower()]
    return None


def employee_codes(cur):
    """{what a log row calls the person: the employee code to send}. eTimeTrackLite keeps its own EmployeeId, the code HR
    gave (EmployeeCode) and the number enrolled on the machine (EmployeeCodeInDevice)."""
    cols = columns(cur, "Employees")
    if not cols:
        return {}, {}
    eid, code, in_device = pick(cols, "EmployeeId"), pick(cols, "EmployeeCode"), pick(cols, "EmployeeCodeInDevice")
    if not code:
        return {}, {}
    cur.execute("SELECT %s, %s, %s FROM Employees" % (eid or "NULL", code, in_device or "NULL"))
    by_id, by_device = {}, {}
    for i, c, d in cur.fetchall():
        c = str(c or "").strip()
        if not c:
            continue
        if i is not None:
            by_id[str(i).strip()] = c
        if d is not None and str(d).strip():
            by_device[str(d).strip()] = c
    return by_id, by_device


def month_tables(since, until):
    out, d = [], since.replace(day=1)
    while d <= until:
        out.append("DeviceLogs_%d_%d" % (d.month, d.year))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def raw_punches(cur, since, by_device, use):
    """Every punch since `since` from the monthly DeviceLogs_<month>_<year> tables - the machines' own log."""
    out = []
    have = {t.lower(): t for t in tables_like(cur, "DeviceLogs[_]%")}
    for name in month_tables(since, datetime.now()):
        table = have.get(name.lower())
        if not table:
            continue
        cols = columns(cur, table)
        user, when = pick(cols, "UserId", "EmployeeCode"), pick(cols, "LogDate", "PunchTime")
        device, way = pick(cols, "DeviceId"), pick(cols, "Direction", "AttDirection", "C1")
        if not user or not when:
            log.warning("%s has no UserId/LogDate columns; skipped", table)
            continue
        cur.execute("SELECT %s, %s, %s, %s FROM [%s] WHERE %s > ? ORDER BY %s" % (
            user, when, device or "NULL", way or "NULL", table, when, when), since)
        for u, t, d, w in cur.fetchall():
            u = str(u or "").strip()
            if not u or t is None:
                continue
            out.append({"employee_code": by_device.get(u, u) if use == "code" else u, "time": t.strftime("%Y-%m-%d %H:%M:%S"),
                        "device": str(d or "").strip(), "direction": str(w or "").strip().lower()})
    return out


def daily_punches(cur, since, by_id):
    """From AttendanceLogs - one row a person a day with the day's first in and last out - where there are no raw logs."""
    cols = columns(cur, "AttendanceLogs")
    day, emp = pick(cols, "AttendanceDate"), pick(cols, "EmployeeId")
    t_in, t_out = pick(cols, "InTime"), pick(cols, "OutTime")
    d_in, d_out = pick(cols, "InDeviceId"), pick(cols, "OutDeviceId")
    if not (day and emp and t_in):
        sys.exit("AttendanceLogs does not have the columns expected (AttendanceDate, EmployeeId, InTime). Run --check and send the output.")
    cur.execute("SELECT %s, %s, %s, %s, %s, %s FROM AttendanceLogs WHERE %s >= ?" % (
        emp, day, t_in, t_out or "NULL", d_in or "NULL", d_out or "NULL", day), since.replace(hour=0, minute=0, second=0, microsecond=0))
    out = []
    for e, d, i, o, di, do in cur.fetchall():
        code = by_id.get(str(e).strip(), str(e).strip())
        for raw, device, way in ((i, di, "in"), (o, do, "out")):
            when = clock(d, raw)
            if when:
                out.append({"employee_code": code, "time": when, "device": str(device or "").strip(), "direction": way})
    return out


def clock(day, raw):
    """AttendanceLogs keeps InTime as text - a time ("09:02") or a whole date and time - and "1900-01-01..." for none."""
    s = str(raw or "").strip()
    if not s or s.startswith("1900") or s in ("00:00", "00:00:00", "--:--"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(s[:22].strip(), fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p"):
        try:
            t = datetime.strptime(s, fmt)
            return "%s %s" % (day.strftime("%Y-%m-%d"), t.strftime("%H:%M:%S"))
        except (ValueError, AttributeError):
            pass
    return None


def call(cfg, path, body=None):
    erp = cfg["yerp"]
    url = erp.get("url", "").rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers={
        "X-Biometric-Key": erp.get("api_key", "").strip(), "Content-Type": "application/json", "User-Agent": "yerp-biometric-sync/1"})
    try:
        with urllib.request.urlopen(req, timeout=40) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("Y ERP answered %s: %s" % (exc.code, detail))
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach Y ERP at %s: %s" % (url, exc.reason))


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE)


def gather(cfg, cur, since):
    by_id, by_device = employee_codes(cur)
    source = cfg["database"].get("source", "auto").strip().lower()
    use = cfg["database"].get("send", "code").strip().lower()          # code = the HR employee code; device = the number on the machine
    has_raw = bool(tables_like(cur, "DeviceLogs[_]%"))
    if source == "devicelogs" or (source == "auto" and has_raw):
        return "DeviceLogs", raw_punches(cur, since, by_device, use)
    return "AttendanceLogs", daily_punches(cur, since, by_id)


def run_once(cfg, backfill_days=0):
    state = load_state()
    overlap = timedelta(minutes=int(cfg["yerp"].get("overlap_minutes", "30")))     # read a little back: a machine may upload late
    if backfill_days:
        since = datetime.now() - timedelta(days=backfill_days)
    elif state.get("last"):
        since = datetime.strptime(state["last"], "%Y-%m-%d %H:%M:%S") - overlap
    else:
        since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)   # first run: today
    conn = connect(cfg)
    try:
        source, punches = gather(cfg, conn.cursor(), since)
    finally:
        conn.close()
    sent_already = set(state.get("recent", []))
    fresh = [p for p in punches if "%s|%s|%s" % (p["employee_code"], p["time"], p["device"]) not in sent_already]
    if not fresh:
        log.info("nothing new since %s (%s)", since.strftime("%Y-%m-%d %H:%M"), source)
        call(cfg, "/api/biometric/punches", {"punches": [], "agent": agent_name(source)})      # still says "I am alive"
        return 0
    new = unmatched = 0
    for i in range(0, len(fresh), BATCH):
        res = call(cfg, "/api/biometric/punches", {"punches": fresh[i:i + BATCH], "agent": agent_name(source)})
        new += res.get("new", 0)
        unmatched += len(res.get("unmatched", []))
    last = max(p["time"] for p in punches)
    keys = ["%s|%s|%s" % (p["employee_code"], p["time"], p["device"]) for p in punches]
    state.update(last=max(last, state.get("last", "")), recent=keys[-5000:])
    save_state(state)
    log.info("sent %d punches from %s: %d new%s", len(fresh), source, new,
             (", %d employee numbers Y ERP does not know - see People > Attendance > Biometric" % unmatched) if unmatched else "")
    return new


def agent_name(source):
    return "%s (%s)" % (socket.gethostname(), source)


def check(cfg):
    print("1. Y ERP ...")
    try:
        print("   key accepted for:", call(cfg, "/api/biometric/ping").get("company"))
    except RuntimeError as exc:
        print("   PROBLEM:", exc)
    print("2. Attendance database ...")
    conn = connect(cfg)
    cur = conn.cursor()
    raw = sorted(tables_like(cur, "DeviceLogs[_]%"))
    print("   raw punch tables (DeviceLogs_*): %s" % (", ".join(raw[-6:]) if raw else "none found"))
    for t in (raw[-1:] if raw else []) + ["AttendanceLogs", "Employees"]:
        print("   %s columns: %s" % (t, ", ".join(sorted(columns(cur, t).values())) or "TABLE NOT FOUND"))
    by_id, by_device = employee_codes(cur)
    print("   employees with a code: %d (%d with a number on the machine)" % (len(by_id), len(by_device)))
    source, punches = gather(cfg, cur, datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
    conn.close()
    print("3. Today's punches read from %s: %d" % (source, len(punches)))
    for p in punches[:5]:
        print("   ", p)
    print("Nothing was sent. Run  python sync.py --once  to send.")


def main():
    ap = argparse.ArgumentParser(description="Send biometric punches to Y ERP")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--backfill", type=int, default=0, metavar="DAYS")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(HERE, "sync.log"), encoding="utf-8")])
    cfg = settings()
    if args.check:
        return check(cfg)
    if args.once or args.backfill:
        try:
            run_once(cfg, args.backfill)
        except Exception as exc:
            log.error("failed: %s", exc)
            sys.exit(1)
        return
    every = max(30, int(cfg["yerp"].get("every_seconds", "60")))
    log.info("running; sending every %d seconds. Close this window (or Ctrl+C) to stop.", every)
    while True:
        try:
            run_once(cfg)
        except Exception as exc:                                    # the network or the database being down is not the end
            log.error("failed, will try again: %s", exc)
        time.sleep(every)


if __name__ == "__main__":
    main()
