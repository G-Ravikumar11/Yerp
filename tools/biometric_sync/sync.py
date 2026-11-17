"""Y ERP biometric sync: reads new punches from the eSSL eTimeTrackLite database and sends them to Y ERP.

Runs on the office computer that can reach the attendance system's SQL Server. It only READS that database.

    python sync.py --setup      guided set-up: finds the database, makes a read-only login, sends the first punches and
                                starts the every-minute schedule (SETUP.bat runs this)
    python sync.py --check      look at the database and the key, send nothing
    python sync.py --once       send what is new, then stop          (what the Windows scheduled task runs)
    python sync.py              keep running, sending every `every_seconds`
    python sync.py --backfill 30    also send the last 30 days

Settings are in config.ini beside this file. What has been sent is remembered in state.json, so a restart sends nothing
twice - and Y ERP ignores a punch it already has.
"""
import argparse
import configparser
import getpass
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG = os.path.join(HERE, "config.ini")
STATE = os.path.join(HERE, "state.json")
BATCH = 500
TASK = "YERP Biometric Sync"
READER = "yerp_reader"
log = logging.getLogger("yerp-biometric")


# --- settings -----------------------------------------------------------------------------------------------------------

def settings(must_exist=True):
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG):
        cfg.read(CONFIG, encoding="utf-8")
    elif must_exist:
        sys.exit("config.ini is missing. Run SETUP.bat (or: python sync.py --setup), which makes it for you.")
    for section, defaults in (("yerp", {"url": "", "api_key": "", "every_seconds": "60", "overlap_minutes": "30"}),
                              ("database", {"server": "", "name": "etimetracklite", "user": "", "password": "", "driver": "",
                                            "source": "auto", "send": "code"})):
        if not cfg.has_section(section):
            cfg.add_section(section)
        for k, v in defaults.items():
            if not cfg.has_option(section, k):
                cfg.set(section, k, v)
    return cfg


def write_config(cfg):
    """config.ini as the program reads it, with a note at the top. Written whole: it holds only what the set-up asked."""
    y, d = cfg["yerp"], cfg["database"]
    text = (
        "; Settings for the Y ERP biometric sync. Made by the set-up; safe to edit by hand.\n"
        "; This file holds a key and a password: keep the folder where only administrators can open it.\n\n"
        "[yerp]\nurl = %s\napi_key = %s\nevery_seconds = %s\noverlap_minutes = %s\n\n"
        "[database]\nserver = %s\nname = %s\nuser = %s\npassword = %s\ndriver = %s\n"
        "; auto = the machines' raw logs when they exist, else the daily table.  Or force: devicelogs / attendancelogs\n"
        "source = %s\n"
        "; code = send each person's HR employee code.  device = send the number enrolled on the machine.\nsend = %s\n"
        % (y.get("url", ""), y.get("api_key", ""), y.get("every_seconds", "60"), y.get("overlap_minutes", "30"),
           d.get("server", ""), d.get("name", ""), d.get("user", ""), d.get("password", ""), d.get("driver", ""),
           d.get("source", "auto"), d.get("send", "code")))
    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write(text)


# --- the database -------------------------------------------------------------------------------------------------------

def find_driver(pyodbc, wanted=""):
    if wanted.strip():
        return wanted.strip()
    have = pyodbc.drivers()
    for want in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server Native Client 11.0", "SQL Server"):
        if want in have:
            return want
    sys.exit("No SQL Server ODBC driver found on this computer. Drivers here: %s" % (", ".join(have) or "none"))


def open_db(server, database, user="", password="", driver="", timeout=15):
    try:
        import pyodbc
    except ImportError:
        sys.exit("pyodbc is not installed. Run SETUP.bat, or:  pip install pyodbc")
    driver = find_driver(pyodbc, driver)
    parts = ["DRIVER={%s}" % driver, "SERVER=%s" % (server or "localhost"), "DATABASE=%s" % (database or "master")]
    if user.strip():
        parts += ["UID=%s" % user, "PWD=%s" % password]
    else:
        parts.append("Trusted_Connection=yes")          # the Windows account the program runs as
    if "18" in driver:
        parts.append("TrustServerCertificate=yes")
    return pyodbc.connect(";".join(parts), timeout=timeout, autocommit=True)


def connect(cfg):
    d = cfg["database"]
    return open_db(d.get("server", ""), d.get("name", "") or "etimetracklite", d.get("user", ""), d.get("password", ""), d.get("driver", ""))


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


def people(cur):
    """({what a daily row calls the person: code}, {number on the machine: code}, {code: name}) from the Employees table.
    eTimeTrackLite keeps its own EmployeeId, the code HR gave (EmployeeCode) and the number enrolled on the machine
    (EmployeeCodeInDevice)."""
    cols = columns(cur, "Employees")
    if not cols:
        return {}, {}, {}
    eid, code, in_device = pick(cols, "EmployeeId"), pick(cols, "EmployeeCode"), pick(cols, "EmployeeCodeInDevice")
    name = pick(cols, "EmployeeName", "FullName", "Name")
    if not code:
        return {}, {}, {}
    cur.execute("SELECT %s, %s, %s, %s FROM Employees" % (eid or "NULL", code, in_device or "NULL", name or "NULL"))
    by_id, by_device, names = {}, {}, {}
    for i, c, d, n in cur.fetchall():
        c = str(c or "").strip()
        if not c:
            continue
        if i is not None:
            by_id[str(i).strip()] = c
        if d is not None and str(d).strip():
            by_device[str(d).strip()] = c
        if n:
            names[c] = " ".join(str(n).split())[:100]
    return by_id, by_device, names


def employee_codes(cur):
    by_id, by_device, _ = people(cur)
    return by_id, by_device


def month_tables(since, until):
    out, d = [], since.replace(day=1)
    while d <= until:
        out.append("DeviceLogs_%d_%d" % (d.month, d.year))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def raw_punches(cur, since, by_device, use, names=None):
    """Every punch since `since` from the monthly DeviceLogs_<month>_<year> tables - the machines' own log."""
    out = []
    names = names or {}
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
            code = by_device.get(u, u) if use == "code" else u
            out.append({"employee_code": code, "employee_name": names.get(by_device.get(u, u), ""),
                        "time": t.strftime("%Y-%m-%d %H:%M:%S"), "device": str(d or "").strip(), "direction": str(w or "").strip().lower()})
    return out


def daily_punches(cur, since, by_id, names=None):
    """From AttendanceLogs - one row a person a day with the day's first in and last out - where there are no raw logs."""
    names = names or {}
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
                out.append({"employee_code": code, "employee_name": names.get(code, ""), "time": when,
                            "device": str(device or "").strip(), "direction": way})
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


def gather(cfg, cur, since):
    by_id, by_device, names = people(cur)
    source = cfg["database"].get("source", "auto").strip().lower()
    use = cfg["database"].get("send", "code").strip().lower()          # code = the HR employee code; device = the number on the machine
    has_raw = bool(tables_like(cur, "DeviceLogs[_]%"))
    if source == "devicelogs" or (source == "auto" and has_raw):
        return "DeviceLogs", raw_punches(cur, since, by_device, use, names)
    return "AttendanceLogs", daily_punches(cur, since, by_id, names)


# --- Y ERP --------------------------------------------------------------------------------------------------------------

def call(cfg, path, body=None):
    erp = cfg["yerp"]
    url = erp.get("url", "").rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers={
        "X-Biometric-Key": erp.get("api_key", "").strip(), "Content-Type": "application/json", "User-Agent": "yerp-biometric-sync/2"})
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


def agent_name(source):
    return "%s (%s)" % (socket.gethostname(), source)


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
    by_id, by_device, names = people(cur)
    print("   employees with a code: %d (%d with a number on the machine, %d with a name)" % (len(by_id), len(by_device), len(names)))
    source, punches = gather(cfg, cur, datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
    conn.close()
    print("3. Today's punches read from %s: %d" % (source, len(punches)))
    for p in punches[:5]:
        print("   ", p)
    print("Nothing was sent. Run  python sync.py --once  to send.")


# --- guided set-up ------------------------------------------------------------------------------------------------------

def ask(prompt, default=""):
    shown = " [%s]" % default if default else ""
    try:
        answer = input("%s%s: " % (prompt, shown)).strip()
    except EOFError:
        answer = ""
    return answer or default


def server_candidates(extra=""):
    host = socket.gethostname()
    out = []
    for s in (extra, ".", "localhost", "(local)", ".\\SQLEXPRESS", host, host + "\\SQLEXPRESS", "127.0.0.1"):
        if s and s not in out:
            out.append(s)
    return out


def attendance_databases(conn):
    """The user databases on this server that hold the attendance system's tables (usually just etimetracklite)."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sys.databases WHERE database_id > 4 AND state = 0 ORDER BY name")
    found = []
    for (name,) in cur.fetchall():
        quoted = "[" + name.replace("]", "]]") + "]"
        try:
            cur.execute("SELECT COUNT(*) FROM " + quoted + ".INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_NAME = 'AttendanceLogs' OR TABLE_NAME LIKE 'DeviceLogs[_]%'")
            if cur.fetchone()[0]:
                found.append(name)
        except Exception:
            continue
    return found


def make_reader(conn, database):
    """A login that can only read `database`, with a password made here. Returns (user, password) or None when the
    account the set-up signed in with may not create logins."""
    password = secrets.token_urlsafe(18).replace("-", "x").replace("_", "y")
    quoted = "[" + database.replace("]", "]]") + "]"
    try:
        cur = conn.cursor()
        cur.execute("IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = '%s') "
                    "CREATE LOGIN [%s] WITH PASSWORD = '%s', CHECK_POLICY = OFF "
                    "ELSE ALTER LOGIN [%s] WITH PASSWORD = '%s'" % (READER, READER, password, READER, password))
        cur.execute("USE " + quoted)
        cur.execute("IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '%s') "
                    "CREATE USER [%s] FOR LOGIN [%s]" % (READER, READER, READER))
        cur.execute("ALTER ROLE db_datareader ADD MEMBER [%s]" % READER)
        return READER, password
    except Exception as exc:
        print("   (could not make a read-only login: %s)" % str(exc).split("]")[-1].strip()[:120])
        return None


def python_deps():
    try:
        import pyodbc  # noqa: F401
        return True
    except ImportError:
        print("   Installing pyodbc (the part that talks to SQL Server) ...")
        code = subprocess.call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "pyodbc"])
        try:
            import importlib
            importlib.invalidate_caches()
            import pyodbc  # noqa: F401,F811
            return True
        except ImportError:
            print("   Could not install pyodbc (pip said %s). Check this computer's internet and run SETUP.bat again." % code)
            return False


def install_task():
    """The every-minute Windows task. As SYSTEM so it runs with nobody signed in; needs an administrator."""
    cmd = ['"%s" "%s" --once' % (sys.executable, os.path.join(HERE, "sync.py"))]
    run = ["schtasks", "/Create", "/F", "/TN", TASK, "/SC", "MINUTE", "/MO", "1", "/RU", "SYSTEM", "/RL", "HIGHEST", "/TR", cmd[0]]
    try:
        done = subprocess.run(run, capture_output=True, text=True)
    except OSError as exc:
        print("   Could not start schtasks: %s" % exc)
        return False
    if done.returncode == 0:
        return True
    print("   Windows said: %s" % (done.stdout + done.stderr).strip()[:200])
    print("   Right-click SETUP.bat and choose 'Run as administrator', then run it again.")
    return False


def setup():
    print("=" * 66)
    print(" Y ERP biometric attendance - set-up")
    print("=" * 66)
    cfg = settings(must_exist=False)
    print("\n1. Checking Python ...")
    if not python_deps():
        return 1
    print("   ok")

    print("\n2. Connecting to Y ERP ...")
    for attempt in range(3):
        if not cfg["yerp"].get("url", "").strip():
            cfg["yerp"]["url"] = ask("   Y ERP address", "https://yalavartiinfra.com").rstrip("/")
        key = cfg["yerp"].get("api_key", "").strip()
        if not key or key.startswith("PASTE"):
            cfg["yerp"]["api_key"] = ask("   Paste the key from Y ERP (People > Attendance > Biometric)")
        try:
            print("   key accepted for: %s" % call(cfg, "/api/biometric/ping").get("company"))
            break
        except RuntimeError as exc:
            print("   %s" % exc)
            cfg["yerp"]["api_key"] = ""
    else:
        print("   Could not connect to Y ERP. Check the internet and the key, then run SETUP.bat again.")
        return 1

    print("\n3. Finding the attendance database ...")
    d = cfg["database"]
    conn, server, user, password = None, "", "", ""
    if d.get("server", "").strip() and d.get("user", "").strip():
        try:
            conn = open_db(d["server"], "master", d["user"], d.get("password", ""), d.get("driver", ""))
            server, user, password = d["server"], d["user"], d.get("password", "")
        except Exception:
            conn = None
    if conn is None:
        for s in server_candidates(d.get("server", "")):
            try:
                conn = open_db(s, "master", driver=d.get("driver", ""), timeout=6)       # this Windows account
                server = s
                print("   found SQL Server at %s (signed in with this Windows account)" % s)
                break
            except Exception:
                continue
    tries = 0
    while conn is None and tries < 3:
        tries += 1
        print("   Could not sign in automatically. Use the SQL Server login you use in Management Studio.")
        server = ask("   SQL Server name", server_candidates()[-2] if tries == 1 else server)
        user = ask("   Login name", "sa")
        password = getpass.getpass("   Password (not shown): ")
        try:
            conn = open_db(server, "master", user, password, d.get("driver", ""))
        except Exception as exc:
            print("   Could not connect: %s" % str(exc).split("]")[-1].strip()[:160])
    if conn is None:
        print("   Giving up on the database. Ask for help with the message above.")
        return 1
    dbs = attendance_databases(conn)
    if len(dbs) == 1:
        database = dbs[0]
        print("   the attendance database is: %s" % database)
    elif dbs:
        for i, name in enumerate(dbs, 1):
            print("     %d. %s" % (i, name))
        pick_ = ask("   Which one is the attendance system's database (number)", "1")
        database = dbs[int(pick_) - 1] if pick_.isdigit() and 1 <= int(pick_) <= len(dbs) else dbs[0]
    else:
        database = ask("   No attendance tables found. Database name", d.get("name") or "etimetracklite")

    print("\n4. Making a read-only login for the sync ...")
    made = make_reader(conn, database)
    if made:
        user, password = made
        print("   made the login '%s' (it can only read %s)" % (user, database))
    elif not user:
        print("   This Windows account cannot make logins, and the every-minute task needs one. Use a SQL login.")
        user = ask("   SQL login name", "sa")
        password = getpass.getpass("   Password (not shown): ")
    conn.close()
    d["server"], d["name"], d["user"], d["password"] = server, database, user, password
    try:
        connect(cfg).close()
        print("   signed in to %s as %s: ok" % (database, user))
    except Exception as exc:
        print("   Could not sign in with that login: %s" % str(exc).split("]")[-1].strip()[:160])
        return 1
    write_config(cfg)
    print("   saved config.ini")

    print("\n5. Reading the attendance system ...")
    check(cfg)
    days = ask("\n   How many days back should be brought into Y ERP now (0 = just today)", "7")
    print("\n6. Sending the first punches ...")
    try:
        run_once(cfg, int(days) if days.isdigit() else 0)
    except Exception as exc:
        print("   Failed: %s" % exc)
        return 1

    print("\n7. Starting the every-minute sync ...")
    if install_task():
        print("   done: the task '%s' now runs every minute, with nobody signed in." % TASK)
    else:
        print("   The punches were sent, but the every-minute task is not set up yet (see above).")
        return 1
    print("\nAll set. In Y ERP open People > Attendance > Biometric: it should say 'Working'.")
    print("People shown there as 'belonging to nobody' are numbers from the machines that match no employee yet.")
    return 0


# --- main ---------------------------------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Send biometric punches to Y ERP")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--backfill", type=int, default=0, metavar="DAYS")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(HERE, "sync.log"), encoding="utf-8")])
    if args.setup:
        sys.exit(setup())
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
