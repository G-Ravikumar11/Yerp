"""The office sync program (tools/biometric_sync/sync.py): its reading of the attendance system's tables, with a fake
database cursor standing in for SQL Server - which is not here - so what it sends is what the real one would."""
import importlib.util
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("biometric_sync", os.path.join(ROOT, "tools", "biometric_sync", "sync.py"))
sync = importlib.util.module_from_spec(spec)
_argv, sys.argv = sys.argv, ["sync.py"]
spec.loader.exec_module(sync)
sys.argv = _argv


class Cur:
    """Answers the few queries the program makes from tables given as {name: (columns, rows)}."""

    def __init__(self, tables):
        self.t, self.last = tables, []

    def execute(self, sql, *args):
        s = " ".join(sql.split())
        if "FROM INFORMATION_SCHEMA.COLUMNS" in s:
            cols = self.t.get(args[0], ([], []))[0]
            self.last = [(c,) for c in cols]
        elif "FROM INFORMATION_SCHEMA.TABLES" in s:
            pat = args[0]
            hit = [n for n in self.t if (n.startswith(pat.split("[")[0]) if "[" in pat else n == pat)]
            self.last = [(n,) for n in hit]
        elif "FROM Employees" in s:
            self.last = self.t["Employees"][1]
        elif "FROM [DeviceLogs_" in s:
            table = s.split("FROM [")[1].split("]")[0]
            self.last = self.t[table][1]
        elif "FROM AttendanceLogs" in s:
            self.last = self.t["AttendanceLogs"][1]
        else:
            raise AssertionError("unexpected query: " + s)

    def fetchall(self):
        return self.last


def cfg(**db):
    c = sync.settings(must_exist=False)
    for k, v in db.items():
        c["database"][k] = v
    return c


# Columns as the table has them; the rows come back in the order the program selects them: id, code, number, name.
EMPLOYEES = (["EmployeeId", "EmployeeName", "EmployeeCode", "EmployeeCodeInDevice"],
             [(11, "E-77", "5", "RAVI  KUMAR"), (12, "E-78", "6", "Sita Rao"), (13, "", "7", "No Code")])


def test_raw_punches_carry_the_hr_code_and_the_name():
    now = datetime.now()
    table = "DeviceLogs_%d_%d" % (now.month, now.year)
    t = {"Employees": EMPLOYEES, table: (["UserId", "LogDate", "DeviceId", "Direction"], [("5", now, 3, "In"), ("9", now, 3, None)])}
    source, punches = sync.gather(cfg(), Cur(t), now.replace(hour=0, minute=0, second=0, microsecond=0))
    assert source == "DeviceLogs"
    assert punches[0]["employee_code"] == "E-77" and punches[0]["employee_name"] == "RAVI KUMAR" and punches[0]["direction"] == "in"
    assert punches[1]["employee_code"] == "9" and punches[1]["employee_name"] == ""          # a number nobody has: sent as it is
    assert sync.gather(cfg(send="device"), Cur(t), now.replace(hour=0, minute=0, second=0))[1][0]["employee_code"] == "5"


def test_daily_rows_give_an_in_and_an_out_when_there_are_no_raw_logs():
    day = datetime(2026, 11, 16)
    t = {"Employees": EMPLOYEES,
         "AttendanceLogs": (["EmployeeId", "AttendanceDate", "InTime", "OutTime", "InDeviceId", "OutDeviceId"],
                            [(12, day, "09:02", "18:31", 1, 1), (11, day, "09:10", "1900-01-01 00:00:00", 1, None)])}
    source, punches = sync.gather(cfg(), Cur(t), day)
    assert source == "AttendanceLogs"
    got = {(p["employee_code"], p["direction"]): p for p in punches}
    assert got[("E-78", "in")]["time"] == "2026-11-16 09:02:00" and got[("E-78", "out")]["time"] == "2026-11-16 18:31:00"
    assert ("E-77", "out") not in got and got[("E-77", "in")]["employee_name"] == "RAVI KUMAR"


def test_server_names_to_try_start_with_the_one_given_and_have_no_repeats():
    got = sync.server_candidates("YPPL_WEB01")
    assert got[0] == "YPPL_WEB01" and "localhost" in got and len(got) == len(set(got))


def test_config_is_written_and_read_back_as_it_was(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "CONFIG", str(tmp_path / "config.ini"))
    c = sync.settings(must_exist=False)
    c["yerp"]["url"], c["yerp"]["api_key"] = "https://yalavartiinfra.com", "ybio_1_" + "k" * 30
    c["database"].update(server="YPPL_WEB01", name="etimetracklite", user="yerp_reader", password="p@ss=word")
    sync.write_config(c)
    back = sync.settings()
    assert back["yerp"]["api_key"] == c["yerp"]["api_key"] and back["database"]["password"] == "p@ss=word"
    assert back["database"]["source"] == "auto" and back["database"]["send"] == "code"


def test_the_set_up_package_files_all_exist():
    from app.services.biometric import SETUP_FILES
    for name in SETUP_FILES:
        assert os.path.exists(os.path.join(ROOT, "tools", "biometric_sync", name)), name
