// Tests for YerpBiometric.cs, with a fake database standing in for SQL Server (which is not on a build machine) so what
// it sends is what the real one would. Compiled together with the program and run by backend/tests/test_biometric_tool.py
// on Windows:  csc /main:YerpBiometric.SelfTest /out:selftest.exe /r:System.Web.Extensions.dll YerpBiometric.cs test\SelfTest.cs
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;

namespace YerpBiometric
{
    /// <summary>Answers the few queries the program makes, from tables given as name -> (columns, rows).</summary>
    class FakeDb : IDb
    {
        readonly Dictionary<string, KeyValuePair<string[], List<object[]>>> tables;

        public FakeDb(Dictionary<string, KeyValuePair<string[], List<object[]>>> tables) { this.tables = tables; }

        public List<object[]> Query(string sql, params object[] args)
        {
            var s = string.Join(" ", sql.Split(new[] { ' ', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries));
            if (s.Contains("FROM INFORMATION_SCHEMA.COLUMNS"))
            {
                KeyValuePair<string[], List<object[]>> t;
                return tables.TryGetValue((string)args[0], out t) ? t.Key.Select(c => new object[] { c }).ToList() : new List<object[]>();
            }
            if (s.Contains("FROM INFORMATION_SCHEMA.TABLES"))
            {
                var pattern = (string)args[0];
                var prefix = pattern.Split('[')[0];
                return tables.Keys.Where(n => pattern.Contains("[") ? n.StartsWith(prefix) : n == pattern).Select(n => new object[] { n }).ToList();
            }
            if (s.Contains("FROM Employees")) return tables["Employees"].Value;
            if (s.Contains("FROM [DeviceLogs_")) return tables[s.Split(new[] { "FROM [" }, StringSplitOptions.None)[1].Split(']')[0]].Value;
            if (s.Contains("FROM AttendanceLogs")) return tables["AttendanceLogs"].Value;
            throw new Exception("unexpected query: " + s);
        }
    }

    static class SelfTest
    {
        static int failed, passed;

        static void Check(string name, bool ok, string detail = "")
        {
            if (ok) passed++; else failed++;
            Console.WriteLine((ok ? "PASS " : "FAIL ") + name + (ok || detail.Length == 0 ? "" : "  -> " + detail));
        }

        static KeyValuePair<string[], List<object[]>> T(string[] cols, params object[][] rows) { return new KeyValuePair<string[], List<object[]>>(cols, rows.ToList()); }

        // Rows come back in the order the program selects them: id, code, number on the machine, name.
        static KeyValuePair<string[], List<object[]>> Employees()
        {
            return T(new[] { "EmployeeId", "EmployeeName", "EmployeeCode", "EmployeeCodeInDevice" },
                     new object[] { 11, "E-77", "5", "RAVI  KUMAR" }, new object[] { 12, "E-78", "6", "Sita Rao" }, new object[] { 13, "", "7", "No Code" });
        }

        static Settings Cfg(string send = "code")
        {
            var c = Settings.Read(Path.Combine(Path.GetTempPath(), "no-such-yerp-config.ini"));
            c.Set("database", "send", send);
            return c;
        }

        public static int Main()
        {
            var now = DateTime.Now;
            var today = DateTime.Today;
            var month = string.Format("DeviceLogs_{0}_{1}", now.Month, now.Year);

            // The machines' raw logs carry the HR code and the name; a number nobody has is sent as it is.
            var raw = new Dictionary<string, KeyValuePair<string[], List<object[]>>> {
                { "Employees", Employees() },
                { month, T(new[] { "UserId", "LogDate", "DeviceId", "Direction" }, new object[] { "5", now, 3, "In" }, new object[] { "9", now, 3, null }) },
            };
            var got = Attendance.Gather(Cfg(), new FakeDb(raw), today);
            Check("raw logs are read when they exist", got.Key == "DeviceLogs", got.Key);
            var p = got.Value;
            Check("a raw punch carries the HR code and the tidied name", p[0].Code == "E-77" && p[0].Name == "RAVI KUMAR" && p[0].Direction == "in", p[0].Code + "/" + p[0].Name);
            Check("a number nobody has is sent as it is, with no name", p[1].Code == "9" && p[1].Name == "" && p[1].Device == "3");
            Check("send = device sends the number on the machine", Attendance.Gather(Cfg("device"), new FakeDb(raw), today).Value[0].Code == "5");

            // Without raw logs, the daily table gives an in and an out; "1900-01-01" is no out.
            var day = new DateTime(2026, 11, 16);
            var daily = new Dictionary<string, KeyValuePair<string[], List<object[]>>> {
                { "Employees", Employees() },
                { "AttendanceLogs", T(new[] { "EmployeeId", "AttendanceDate", "InTime", "OutTime", "InDeviceId", "OutDeviceId" },
                    new object[] { 12, day, "09:02", "18:31", 1, 1 }, new object[] { 11, day, "09:10", "1900-01-01 00:00:00", 1, null },
                    new object[] { 13, day, new DateTime(2026, 11, 16, 8, 55, 0), new TimeSpan(17, 5, 0), 2, 2 }) },
            };
            got = Attendance.Gather(Cfg(), new FakeDb(daily), day);
            var by = got.Value.ToDictionary(x => x.Code + "/" + x.Direction);
            Check("the daily table is read when there are no raw logs", got.Key == "AttendanceLogs");
            Check("a day's in and out, as times on that day", by["E-78/in"].Time == "2026-11-16 09:02:00" && by["E-78/out"].Time == "2026-11-16 18:31:00");
            Check("no out when the out is 1900", !by.ContainsKey("E-77/out") && by["E-77/in"].Name == "RAVI KUMAR");
            Check("real datetime and time columns are read too", by["13/in"].Time == "2026-11-16 08:55:00" && by["13/out"].Time == "2026-11-16 17:05:00");

            // Times written every way the attendance system has been seen to write them.
            Check("clock: 24-hour with seconds", Attendance.Clock(day, "09:02:07") == "2026-11-16 09:02:07");
            Check("clock: 12-hour", Attendance.Clock(day, "6:31 PM") == "2026-11-16 18:31:00");
            Check("clock: a whole date and time", Attendance.Clock(day, "16/11/2026 09:02:00") == "2026-11-16 09:02:00");
            Check("clock: blanks are no time", Attendance.Clock(day, "") == null && Attendance.Clock(day, "--:--") == null && Attendance.Clock(day, null) == null);

            // The month tables to look in run across a year's end.
            var tables = Attendance.MonthTables(new DateTime(2025, 12, 20), new DateTime(2026, 1, 5));
            Check("month tables across a year's end", tables.SequenceEqual(new[] { "DeviceLogs_12_2025", "DeviceLogs_1_2026" }), string.Join(",", tables));

            // Server names to try start with the one given and have no repeats.
            var servers = Setup.ServerCandidates("OFFICE-PC\\SQLEXPRESS");
            Check("server names start with the one given, no repeats", servers[0] == "OFFICE-PC\\SQLEXPRESS" && servers.Count == servers.Distinct().Count());

            // config.ini is written and read back as it was.
            var path = Path.Combine(Path.GetTempPath(), "yerp-selftest-" + Guid.NewGuid().ToString("N") + ".ini");
            var c = Cfg();
            c.Set("yerp", "url", "https://example.test"); c.Set("yerp", "api_key", "k-123");
            c.Set("database", "server", ".\\SQLEXPRESS"); c.Set("database", "user", "");
            c.Write(path);
            var back = Settings.Read(path);
            File.Delete(path);
            Check("config.ini round trip", back.Get("yerp", "api_key") == "k-123" && back.Get("database", "server") == ".\\SQLEXPRESS"
                  && back.Get("database", "user") == "" && back.Get("database", "send") == "code" && back.GetInt("yerp", "every_seconds", 0) == 60);

            // Sending: only what is new, in batches, remembered so a second run sends nothing again but still says it is alive.
            if (File.Exists(Program.StatePath)) File.Delete(Program.StatePath);
            var bodies = new List<Dictionary<string, object>>();
            Func<string, object, Dictionary<string, object>> send = (route, body) => {
                var d = (Dictionary<string, object>)body;
                bodies.Add(d);
                var n = ((System.Collections.ICollection)d["punches"]).Count;
                var answer = new Dictionary<string, object>();
                answer["new"] = n; answer["unmatched"] = new List<object>();
                return answer;
            };
            var added = Program.RunOnce(Cfg(), 0, new FakeDb(raw), send);
            Check("the first run sends today's punches", added == 2 && bodies.Count == 1 && ((string)bodies[0]["agent"]).EndsWith("(DeviceLogs)"));
            Program.RunOnce(Cfg(), 0, new FakeDb(raw), send);
            Check("a second run sends nothing twice but still calls in", bodies.Count == 2 && ((System.Collections.ICollection)bodies[1]["punches"]).Count == 0);
            var state = State.Load(Program.StatePath);
            Check("what was sent is remembered", state.Recent.Count == 2 && state.Last == now.ToString(Attendance.TimeFormat, CultureInfo.InvariantCulture));
            File.Delete(Program.StatePath);

            Console.WriteLine(string.Format("{0} passed, {1} failed", passed, failed));
            return failed == 0 ? 0 : 1;
        }
    }
}
