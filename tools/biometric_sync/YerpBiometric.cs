// Y ERP biometric sync: reads new punches from the eSSL eTimeTrackLite database and sends them to Y ERP.
//
// It runs on the office computer that can reach the attendance system's SQL Server, and only READS that database.
// It needs nothing but Windows: SETUP.bat compiles this file with the C# compiler that comes with the .NET Framework
// (Windows 8 and later have it; Windows 7 SP1 has it once .NET Framework 4.5 or newer is installed), talks to SQL Server
// through .NET's own SqlClient - no ODBC driver - and to Y ERP over TLS 1.2. 32- and 64-bit alike.
//
//     YerpBiometric.exe --setup         guided set-up: finds the database, gives the sync read-only access, sends the
//                                       first punches and starts the every-minute task (SETUP.bat runs this)
//     YerpBiometric.exe --check         look at the database and the key, send nothing
//     YerpBiometric.exe --once          send what is new, then stop    (what the Windows scheduled task runs)
//     YerpBiometric.exe                 keep running, sending every `every_seconds`
//     YerpBiometric.exe --backfill 30   also send the last 30 days
//
// Settings are in config.ini beside the program. What has been sent is remembered in state.json, so a restart sends
// nothing twice - and Y ERP ignores a punch it already has.
//
// Written for the C# 5 compiler that Windows carries (no string interpolation, no ?. and the like).
using System;
using System.Collections.Generic;
using System.Data.SqlClient;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace YerpBiometric
{
    // --- settings -----------------------------------------------------------------------------------------------------

    /// <summary>config.ini: [yerp] and [database], "key = value", ";" or "#" starting a note.</summary>
    public class Settings
    {
        public readonly Dictionary<string, Dictionary<string, string>> Sections = new Dictionary<string, Dictionary<string, string>>();

        static readonly string[][] Defaults = {
            new[] { "yerp", "url", "" }, new[] { "yerp", "api_key", "" }, new[] { "yerp", "every_seconds", "60" },
            new[] { "yerp", "overlap_minutes", "30" },
            new[] { "database", "server", "" }, new[] { "database", "name", "etimetracklite" }, new[] { "database", "user", "" },
            new[] { "database", "password", "" }, new[] { "database", "source", "auto" }, new[] { "database", "send", "code" },
        };

        public static Settings Read(string path)
        {
            var s = new Settings();
            if (File.Exists(path))
            {
                string section = "";
                foreach (var raw in File.ReadAllLines(path, Encoding.UTF8))
                {
                    var line = raw.Trim();
                    if (line.Length == 0 || line.StartsWith(";") || line.StartsWith("#")) continue;
                    if (line.StartsWith("[") && line.EndsWith("]")) { section = line.Substring(1, line.Length - 2).Trim().ToLowerInvariant(); continue; }
                    int eq = line.IndexOf('=');
                    if (eq < 0 || section.Length == 0) continue;
                    s.Set(section, line.Substring(0, eq).Trim().ToLowerInvariant(), line.Substring(eq + 1).Trim());
                }
            }
            foreach (var d in Defaults)
                if (s.Get(d[0], d[1], null) == null) s.Set(d[0], d[1], d[2]);
            return s;
        }

        public string Get(string section, string key, string fallback = "")
        {
            Dictionary<string, string> sec;
            string v;
            if (Sections.TryGetValue(section, out sec) && sec.TryGetValue(key, out v)) return v;
            return fallback;
        }

        public void Set(string section, string key, string value)
        {
            Dictionary<string, string> sec;
            if (!Sections.TryGetValue(section, out sec)) { sec = new Dictionary<string, string>(); Sections[section] = sec; }
            sec[key] = value ?? "";
        }

        public int GetInt(string section, string key, int fallback)
        {
            int n;
            return int.TryParse(Get(section, key), out n) ? n : fallback;
        }

        /// <summary>Written whole, with a note at the top: it holds only what the set-up asked.</summary>
        public void Write(string path)
        {
            var b = new StringBuilder();
            b.Append("; Settings for the Y ERP biometric sync. Made by the set-up; safe to edit by hand.\r\n");
            b.Append("; This file holds a key (and a password if a SQL login is used): keep the folder where only administrators can open it.\r\n\r\n");
            b.Append("[yerp]\r\n");
            foreach (var k in new[] { "url", "api_key", "every_seconds", "overlap_minutes" }) b.Append(k + " = " + Get("yerp", k) + "\r\n");
            b.Append("\r\n[database]\r\n");
            b.Append("; user empty = sign in to SQL Server as the Windows account the sync runs as (the every-minute task runs as SYSTEM).\r\n");
            foreach (var k in new[] { "server", "name", "user", "password" }) b.Append(k + " = " + Get("database", k) + "\r\n");
            b.Append("; auto = the machines' raw logs when they exist, else the daily table.  Or force: devicelogs / attendancelogs\r\n");
            b.Append("source = " + Get("database", "source") + "\r\n");
            b.Append("; code = send each person's HR employee code.  device = send the number enrolled on the machine.\r\n");
            b.Append("send = " + Get("database", "send") + "\r\n");
            File.WriteAllText(path, b.ToString(), new UTF8Encoding(false));
        }
    }

    // --- the database ---------------------------------------------------------------------------------------------------

    /// <summary>What the program asks of the attendance database: a query with @p0, @p1 ... and its rows. A fake stands in
    /// for SQL Server in the tests.</summary>
    public interface IDb
    {
        List<object[]> Query(string sql, params object[] args);
    }

    public class SqlDb : IDb, IDisposable
    {
        readonly SqlConnection conn;

        public SqlDb(string server, string database, string user, string password, int timeoutSeconds = 15)
        {
            var b = new SqlConnectionStringBuilder();
            b.DataSource = string.IsNullOrEmpty(server) ? "localhost" : server;
            b.InitialCatalog = string.IsNullOrEmpty(database) ? "master" : database;
            b.ConnectTimeout = timeoutSeconds;
            b.ApplicationName = "Y ERP biometric sync";
            if (string.IsNullOrEmpty(user)) b.IntegratedSecurity = true;     // the Windows account the program runs as
            else { b.UserID = user; b.Password = password ?? ""; }
            conn = new SqlConnection(b.ConnectionString);
            conn.Open();
        }

        public List<object[]> Query(string sql, params object[] args)
        {
            using (var cmd = conn.CreateCommand())
            {
                cmd.CommandText = sql;
                cmd.CommandTimeout = 120;
                for (int i = 0; i < args.Length; i++) cmd.Parameters.AddWithValue("@p" + i, args[i] ?? DBNull.Value);
                var rows = new List<object[]>();
                using (var r = cmd.ExecuteReader())
                {
                    do
                    {
                        while (r.Read())
                        {
                            var row = new object[r.FieldCount];
                            r.GetValues(row);
                            for (int c = 0; c < row.Length; c++) if (row[c] is DBNull) row[c] = null;
                            rows.Add(row);
                        }
                    } while (r.NextResult());
                }
                return rows;
            }
        }

        public void Execute(string sql)
        {
            using (var cmd = conn.CreateCommand()) { cmd.CommandText = sql; cmd.CommandTimeout = 60; cmd.ExecuteNonQuery(); }
        }

        public void Dispose() { conn.Dispose(); }
    }

    public class Punch
    {
        public string Code, Name, Time, Device, Direction;
        public string Key { get { return Code + "|" + Time + "|" + Device; } }

        public Dictionary<string, object> ToJson()
        {
            var d = new Dictionary<string, object>();
            d["employee_code"] = Code; d["employee_name"] = Name; d["time"] = Time; d["device"] = Device; d["direction"] = Direction;
            return d;
        }
    }

    /// <summary>Reading eTimeTrackLite's tables. Column names are looked up rather than assumed: versions differ.</summary>
    public static class Attendance
    {
        public const string TimeFormat = "yyyy-MM-dd HH:mm:ss";

        public static Dictionary<string, string> Columns(IDb db, string table)
        {
            var cols = new Dictionary<string, string>();
            foreach (var r in db.Query("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = @p0", table))
                cols[Str(r[0]).ToLowerInvariant()] = Str(r[0]);
            return cols;
        }

        public static List<string> TablesLike(IDb db, string pattern)
        {
            return db.Query("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE @p0", pattern).Select(r => Str(r[0])).ToList();
        }

        public static string Pick(Dictionary<string, string> cols, params string[] names)
        {
            foreach (var n in names)
            {
                string actual;
                if (cols.TryGetValue(n.ToLowerInvariant(), out actual)) return actual;
            }
            return null;
        }

        public static string Str(object v) { return v == null ? "" : Convert.ToString(v, CultureInfo.InvariantCulture).Trim(); }

        static string Q(string name) { return "[" + name.Replace("]", "]]") + "]"; }

        /// <summary>From the Employees table: what a daily row calls the person -> code, the number on the machine -> code,
        /// and code -> name. eTimeTrackLite keeps its own EmployeeId, the code HR gave (EmployeeCode) and the number enrolled
        /// on the machine (EmployeeCodeInDevice).</summary>
        public static void People(IDb db, out Dictionary<string, string> byId, out Dictionary<string, string> byDevice, out Dictionary<string, string> names)
        {
            byId = new Dictionary<string, string>(); byDevice = new Dictionary<string, string>(); names = new Dictionary<string, string>();
            var cols = Columns(db, "Employees");
            string eid = Pick(cols, "EmployeeId"), code = Pick(cols, "EmployeeCode"), inDevice = Pick(cols, "EmployeeCodeInDevice");
            string name = Pick(cols, "EmployeeName", "FullName", "Name");
            if (code == null) return;
            var sql = string.Format("SELECT {0}, {1}, {2}, {3} FROM Employees", eid == null ? "NULL" : Q(eid), Q(code),
                                    inDevice == null ? "NULL" : Q(inDevice), name == null ? "NULL" : Q(name));
            foreach (var r in db.Query(sql))
            {
                var c = Str(r[1]);
                if (c.Length == 0) continue;
                if (r[0] != null) byId[Str(r[0])] = c;
                if (r[2] != null && Str(r[2]).Length > 0) byDevice[Str(r[2])] = c;
                if (r[3] != null && Str(r[3]).Length > 0)
                {
                    var n = string.Join(" ", Str(r[3]).Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries));
                    names[c] = n.Length > 100 ? n.Substring(0, 100) : n;
                }
            }
        }

        public static List<string> MonthTables(DateTime since, DateTime until)
        {
            var output = new List<string>();
            for (var d = new DateTime(since.Year, since.Month, 1); d <= until; d = d.AddMonths(1))
                output.Add(string.Format("DeviceLogs_{0}_{1}", d.Month, d.Year));
            return output;
        }

        /// <summary>Every punch since `since` from the monthly DeviceLogs_month_year tables - the machines' own log.</summary>
        public static List<Punch> RawPunches(IDb db, DateTime since, Dictionary<string, string> byDevice, string use, Dictionary<string, string> names)
        {
            var output = new List<Punch>();
            var have = new Dictionary<string, string>();
            foreach (var t in TablesLike(db, "DeviceLogs[_]%")) have[t.ToLowerInvariant()] = t;
            foreach (var wanted in MonthTables(since, DateTime.Now))
            {
                string table;
                if (!have.TryGetValue(wanted.ToLowerInvariant(), out table)) continue;
                var cols = Columns(db, table);
                string user = Pick(cols, "UserId", "EmployeeCode"), when = Pick(cols, "LogDate", "PunchTime");
                string device = Pick(cols, "DeviceId"), way = Pick(cols, "Direction", "AttDirection", "C1");
                if (user == null || when == null) { Log.Warn(table + " has no UserId/LogDate columns; skipped"); continue; }
                var sql = string.Format("SELECT {0}, {1}, {2}, {3} FROM {4} WHERE {1} > @p0 ORDER BY {1}", Q(user), Q(when),
                                        device == null ? "NULL" : Q(device), way == null ? "NULL" : Q(way), Q(table));
                foreach (var r in db.Query(sql, since))
                {
                    var u = Str(r[0]);
                    if (u.Length == 0 || !(r[1] is DateTime)) continue;
                    string known;
                    var hr = byDevice.TryGetValue(u, out known) ? known : u;
                    string name;
                    output.Add(new Punch {
                        Code = use == "code" ? hr : u,
                        Name = names.TryGetValue(hr, out name) ? name : "",
                        Time = ((DateTime)r[1]).ToString(TimeFormat, CultureInfo.InvariantCulture),
                        Device = Str(r[2]), Direction = Str(r[3]).ToLowerInvariant(),
                    });
                }
            }
            return output;
        }

        /// <summary>From AttendanceLogs - one row a person a day with the day's first in and last out - where there are no raw logs.</summary>
        public static List<Punch> DailyPunches(IDb db, DateTime since, Dictionary<string, string> byId, Dictionary<string, string> names)
        {
            var cols = Columns(db, "AttendanceLogs");
            string day = Pick(cols, "AttendanceDate"), emp = Pick(cols, "EmployeeId"), tIn = Pick(cols, "InTime"), tOut = Pick(cols, "OutTime");
            string dIn = Pick(cols, "InDeviceId"), dOut = Pick(cols, "OutDeviceId");
            if (day == null || emp == null || tIn == null)
                throw new ApplicationException("AttendanceLogs does not have the columns expected (AttendanceDate, EmployeeId, InTime). Run run_check.bat and send what it shows.");
            var sql = string.Format("SELECT {0}, {1}, {2}, {3}, {4}, {5} FROM AttendanceLogs WHERE {1} >= @p0", Q(emp), Q(day), Q(tIn),
                                    tOut == null ? "NULL" : Q(tOut), dIn == null ? "NULL" : Q(dIn), dOut == null ? "NULL" : Q(dOut));
            var output = new List<Punch>();
            foreach (var r in db.Query(sql, since.Date))
            {
                string known, name;
                var code = byId.TryGetValue(Str(r[0]), out known) ? known : Str(r[0]);
                var on = r[1] is DateTime ? (DateTime)r[1] : DateTime.MinValue;
                foreach (var side in new[] { new { Raw = r[2], Device = r[4], Way = "in" }, new { Raw = r[3], Device = r[5], Way = "out" } })
                {
                    var when = Clock(on, side.Raw);
                    if (when == null) continue;
                    output.Add(new Punch { Code = code, Name = names.TryGetValue(code, out name) ? name : "", Time = when, Device = Str(side.Device), Direction = side.Way });
                }
            }
            return output;
        }

        static readonly string[] DateTimeFormats = { "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm", "yyyy-MM-ddTHH:mm:ss", "dd-MM-yyyy HH:mm:ss",
                                                     "dd/MM/yyyy HH:mm:ss", "M/d/yyyy h:mm:ss tt", "MM/dd/yyyy hh:mm:ss tt" };
        static readonly string[] TimeFormats = { "HH:mm:ss", "H:mm:ss", "HH:mm", "H:mm", "h:mm tt", "hh:mm tt" };

        /// <summary>AttendanceLogs keeps InTime as a time ("09:02"), a whole date and time, or a real datetime, and
        /// "1900-01-01..." for none.</summary>
        public static string Clock(DateTime day, object raw)
        {
            if (raw == null) return null;
            if (raw is DateTime)
            {
                var t = (DateTime)raw;
                if (t.Year <= 1900) return null;
                return t.ToString(TimeFormat, CultureInfo.InvariantCulture);
            }
            if (raw is TimeSpan)
            {
                if (day == DateTime.MinValue) return null;
                return day.Date.Add((TimeSpan)raw).ToString(TimeFormat, CultureInfo.InvariantCulture);
            }
            var s = Str(raw);
            if (s.Length == 0 || s.StartsWith("1900") || s == "00:00" || s == "00:00:00" || s == "--:--") return null;
            DateTime parsed;
            var head = s.Length > 22 ? s.Substring(0, 22).Trim() : s;
            if (DateTime.TryParseExact(head, DateTimeFormats, CultureInfo.InvariantCulture, DateTimeStyles.None, out parsed))
                return parsed.ToString(TimeFormat, CultureInfo.InvariantCulture);
            if (day != DateTime.MinValue && DateTime.TryParseExact(s, TimeFormats, CultureInfo.InvariantCulture, DateTimeStyles.None, out parsed))
                return day.Date.Add(parsed.TimeOfDay).ToString(TimeFormat, CultureInfo.InvariantCulture);
            return null;
        }

        /// <summary>(where the punches were read from, the punches since `since`).</summary>
        public static KeyValuePair<string, List<Punch>> Gather(Settings cfg, IDb db, DateTime since)
        {
            Dictionary<string, string> byId, byDevice, names;
            People(db, out byId, out byDevice, out names);
            var source = cfg.Get("database", "source", "auto").ToLowerInvariant();
            var use = cfg.Get("database", "send", "code").ToLowerInvariant();         // code = the HR employee code; device = the number on the machine
            var hasRaw = TablesLike(db, "DeviceLogs[_]%").Count > 0;
            if (source == "devicelogs" || (source == "auto" && hasRaw))
                return new KeyValuePair<string, List<Punch>>("DeviceLogs", RawPunches(db, since, byDevice, use, names));
            return new KeyValuePair<string, List<Punch>>("AttendanceLogs", DailyPunches(db, since, byId, names));
        }
    }

    // --- Y ERP and what has been sent -----------------------------------------------------------------------------------

    public static class Erp
    {
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };

        static Erp()
        {
            // TLS 1.2 on every Windows that has .NET 4.5 or newer, Windows 7 included; whatever newer the system offers too.
            try { ServicePointManager.SecurityProtocol |= (SecurityProtocolType)3072; } catch (NotSupportedException) { }
            ServicePointManager.Expect100Continue = false;
        }

        public static string Encode(object value) { return Json.Serialize(value); }

        public static Dictionary<string, object> Decode(string text)
        {
            var d = Json.DeserializeObject(text) as Dictionary<string, object>;
            return d ?? new Dictionary<string, object>();
        }

        public static Dictionary<string, object> Call(Settings cfg, string path, object body = null)
        {
            var url = cfg.Get("yerp", "url").TrimEnd('/') + path;
            HttpWebRequest req;
            try { req = (HttpWebRequest)WebRequest.Create(url); }
            catch (UriFormatException) { throw new ApplicationException("The Y ERP address in config.ini is not a web address: " + url); }
            req.Method = body == null ? "GET" : "POST";
            req.Timeout = 40000; req.ReadWriteTimeout = 40000;
            req.UserAgent = "yerp-biometric-sync/3 (.NET)";
            req.Headers["X-Biometric-Key"] = cfg.Get("yerp", "api_key").Trim();
            try
            {
                if (body != null)
                {
                    var bytes = Encoding.UTF8.GetBytes(Encode(body));
                    req.ContentType = "application/json";
                    req.ContentLength = bytes.Length;
                    using (var s = req.GetRequestStream()) s.Write(bytes, 0, bytes.Length);
                }
                using (var res = (HttpWebResponse)req.GetResponse())
                using (var reader = new StreamReader(res.GetResponseStream(), Encoding.UTF8))
                    return Decode(reader.ReadToEnd());
            }
            catch (WebException exc)
            {
                var res = exc.Response as HttpWebResponse;
                if (res != null)
                {
                    string detail;
                    using (var reader = new StreamReader(res.GetResponseStream(), Encoding.UTF8)) detail = reader.ReadToEnd();
                    if (detail.Length > 300) detail = detail.Substring(0, 300);
                    throw new ApplicationException(string.Format("Y ERP answered {0}: {1}", (int)res.StatusCode, detail));
                }
                throw new ApplicationException(string.Format("Could not reach Y ERP at {0}: {1}", url, exc.Message));
            }
        }
    }

    public class State
    {
        public string Last = "";
        public List<string> Recent = new List<string>();

        public static State Load(string path)
        {
            var s = new State();
            try
            {
                var d = Erp.Decode(File.ReadAllText(path, Encoding.UTF8));
                object last, recent;
                if (d.TryGetValue("last", out last) && last != null) s.Last = last.ToString();
                if (d.TryGetValue("recent", out recent) && recent is System.Collections.IEnumerable)
                    foreach (var k in (System.Collections.IEnumerable)recent) s.Recent.Add(Convert.ToString(k));
            }
            catch (Exception) { }
            return s;
        }

        public void Save(string path)
        {
            var d = new Dictionary<string, object>();
            d["last"] = Last; d["recent"] = Recent;
            var tmp = path + ".tmp";
            File.WriteAllText(tmp, Erp.Encode(d), new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(tmp, path, null); else File.Move(tmp, path);
        }
    }

    // --- the log --------------------------------------------------------------------------------------------------------

    public static class Log
    {
        public static string FilePath;
        public static bool Quiet;

        public static void Info(string message) { Write(message); }
        public static void Warn(string message) { Write("warning: " + message); }
        public static void Error(string message) { Write("failed: " + message); }

        static void Write(string message)
        {
            var line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) + " " + message;
            if (!Quiet) Console.WriteLine(line);
            if (FilePath == null) return;
            try
            {
                // Kept to about 2 MB, with the one before it beside it: a task that writes every minute fills a disk otherwise.
                var info = new FileInfo(FilePath);
                if (info.Exists && info.Length > 2 * 1024 * 1024)
                {
                    File.Copy(FilePath, FilePath + ".1", true);
                    File.WriteAllText(FilePath, "");
                }
                File.AppendAllText(FilePath, line + "\r\n", new UTF8Encoding(false));
            }
            catch (IOException) { }
        }
    }

    // --- the program ----------------------------------------------------------------------------------------------------

    public static class Program
    {
        public const string Task = "YERP Biometric Sync";
        public const string Reader = "yerp_reader";
        const int Batch = 500;
        public static readonly string Here = AppDomain.CurrentDomain.BaseDirectory;
        public static string ConfigPath { get { return Path.Combine(Here, "config.ini"); } }
        public static string StatePath { get { return Path.Combine(Here, "state.json"); } }

        public static SqlDb Connect(Settings cfg)
        {
            var name = cfg.Get("database", "name");
            return new SqlDb(cfg.Get("database", "server"), name.Length > 0 ? name : "etimetracklite", cfg.Get("database", "user"), cfg.Get("database", "password"));
        }

        static string AgentName(string source) { return Environment.MachineName + " (" + source + ")"; }

        /// <summary>Sends what is new. `db` is given by the tests; otherwise the attendance database is opened here.</summary>
        public static int RunOnce(Settings cfg, int backfillDays, IDb db = null, Func<string, object, Dictionary<string, object>> send = null)
        {
            if (send == null) send = (path, body) => Erp.Call(cfg, path, body);
            var state = State.Load(StatePath);
            var overlap = TimeSpan.FromMinutes(cfg.GetInt("yerp", "overlap_minutes", 30));     // read a little back: a machine may upload late
            DateTime since, last;
            if (backfillDays > 0) since = DateTime.Now.AddDays(-backfillDays);
            else if (DateTime.TryParseExact(state.Last, Attendance.TimeFormat, CultureInfo.InvariantCulture, DateTimeStyles.None, out last)) since = last - overlap;
            else since = DateTime.Today;                                                             // first run: today
            KeyValuePair<string, List<Punch>> got;
            if (db != null) got = Attendance.Gather(cfg, db, since);
            else using (var conn = Connect(cfg)) got = Attendance.Gather(cfg, conn, since);
            var source = got.Key;
            var punches = got.Value;
            var sentAlready = new HashSet<string>(state.Recent);
            var fresh = punches.Where(p => !sentAlready.Contains(p.Key)).ToList();
            if (fresh.Count == 0)
            {
                Log.Info(string.Format("nothing new since {0} ({1})", since.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture), source));
                send("/api/biometric/punches", Body(new List<Punch>(), source));            // still says "I am alive"
                return 0;
            }
            int added = 0, unmatched = 0;
            for (int i = 0; i < fresh.Count; i += Batch)
            {
                var res = send("/api/biometric/punches", Body(fresh.Skip(i).Take(Batch).ToList(), source));
                object n, um;
                if (res.TryGetValue("new", out n) && n != null) added += Convert.ToInt32(n, CultureInfo.InvariantCulture);
                if (res.TryGetValue("unmatched", out um) && um is System.Collections.ICollection) unmatched += ((System.Collections.ICollection)um).Count;
            }
            var newest = punches.Max(p => p.Time);
            state.Last = string.CompareOrdinal(newest, state.Last) > 0 ? newest : state.Last;
            var keys = punches.Select(p => p.Key).ToList();
            state.Recent = keys.Skip(Math.Max(0, keys.Count - 5000)).ToList();
            state.Save(StatePath);
            Log.Info(string.Format("sent {0} punches from {1}: {2} new{3}", fresh.Count, source, added,
                unmatched > 0 ? string.Format(", {0} employee number{1} Y ERP does not know - see People > Attendance > Biometric", unmatched, unmatched == 1 ? "" : "s") : ""));
            return added;
        }

        static Dictionary<string, object> Body(List<Punch> punches, string source)
        {
            var d = new Dictionary<string, object>();
            d["punches"] = punches.Select(p => p.ToJson()).ToList();
            d["agent"] = AgentName(source);
            return d;
        }

        public static void Check(Settings cfg)
        {
            Console.WriteLine("1. Y ERP ...");
            try { Console.WriteLine("   key accepted for: " + Attendance.Str(Erp.Call(cfg, "/api/biometric/ping").Get("company"))); }
            catch (ApplicationException exc) { Console.WriteLine("   PROBLEM: " + exc.Message); }
            Console.WriteLine("2. Attendance database ...");
            using (var db = Connect(cfg))
            {
                var raw = Attendance.TablesLike(db, "DeviceLogs[_]%").OrderBy(t => t).ToList();
                Console.WriteLine("   raw punch tables (DeviceLogs_*): " + (raw.Count > 0 ? string.Join(", ", raw.Skip(Math.Max(0, raw.Count - 6))) : "none found"));
                var look = raw.Skip(Math.Max(0, raw.Count - 1)).Concat(new[] { "AttendanceLogs", "Employees" });
                foreach (var t in look)
                {
                    var cols = Attendance.Columns(db, t).Values.OrderBy(c => c).ToList();
                    Console.WriteLine(string.Format("   {0} columns: {1}", t, cols.Count > 0 ? string.Join(", ", cols) : "TABLE NOT FOUND"));
                }
                Dictionary<string, string> byId, byDevice, names;
                Attendance.People(db, out byId, out byDevice, out names);
                Console.WriteLine(string.Format("   employees with a code: {0} ({1} with a number on the machine, {2} with a name)", byId.Count, byDevice.Count, names.Count));
                var got = Attendance.Gather(cfg, db, DateTime.Today);
                Console.WriteLine(string.Format("3. Today's punches read from {0}: {1}", got.Key, got.Value.Count));
                foreach (var p in got.Value.Take(5)) Console.WriteLine(string.Format("    {0}  {1}  {2}  machine {3}  {4}", p.Code, p.Name, p.Time, p.Device, p.Direction));
            }
            Console.WriteLine("Nothing was sent. run_now.bat sends.");
        }

        public static int Main(string[] args)
        {
            Log.FilePath = Path.Combine(Here, "sync.log");
            var list = args.Select(a => a.ToLowerInvariant()).ToList();
            int backfill = 0;
            var at = list.IndexOf("--backfill");
            if (at >= 0 && (at + 1 >= list.Count || !int.TryParse(list[at + 1], out backfill) || backfill < 1))
            {
                Console.WriteLine("--backfill needs a number of days, for example: YerpBiometric.exe --backfill 30");
                return 2;
            }
            try
            {
                if (list.Contains("--setup")) return Setup.Run();
                if (!File.Exists(ConfigPath)) { Console.WriteLine("config.ini is missing. Run SETUP.bat, which makes it for you."); return 1; }
                var cfg = Settings.Read(ConfigPath);
                if (list.Contains("--check")) { Check(cfg); return 0; }
                if (list.Contains("--once") || backfill > 0)
                {
                    Log.Quiet = list.Contains("--quiet");
                    RunOnce(cfg, backfill);
                    return 0;
                }
                var every = Math.Max(30, cfg.GetInt("yerp", "every_seconds", 60));
                Log.Info(string.Format("running; sending every {0} seconds. Close this window (or Ctrl+C) to stop.", every));
                while (true)
                {
                    try { RunOnce(cfg, 0); }
                    catch (Exception exc) { Log.Error(Short(exc) + " - will try again"); }   // the network or the database being down is not the end
                    Thread.Sleep(every * 1000);
                }
            }
            catch (Exception exc)
            {
                Log.Error(Short(exc));
                return 1;
            }
        }

        /// <summary>An error as one plain line: SQL Server's own message without its stack of brackets.</summary>
        public static string Short(Exception exc)
        {
            var msg = exc.Message.Replace("\r", " ").Replace("\n", " ");
            return msg.Length > 240 ? msg.Substring(0, 240) : msg;
        }

        static object Get(this Dictionary<string, object> d, string key)
        {
            object v;
            return d.TryGetValue(key, out v) ? v : null;
        }
    }

    // --- guided set-up --------------------------------------------------------------------------------------------------

    public static class Setup
    {
        static string Ask(string prompt, string fallback = "")
        {
            Console.Write(prompt + (fallback.Length > 0 ? " [" + fallback + "]" : "") + ": ");
            var answer = (Console.ReadLine() ?? "").Trim();
            return answer.Length > 0 ? answer : fallback;
        }

        static string AskSecret(string prompt)
        {
            Console.Write(prompt + ": ");
            var b = new StringBuilder();
            try
            {
                while (true)
                {
                    var k = Console.ReadKey(true);
                    if (k.Key == ConsoleKey.Enter) break;
                    if (k.Key == ConsoleKey.Backspace) { if (b.Length > 0) b.Length -= 1; continue; }
                    if (!char.IsControl(k.KeyChar)) b.Append(k.KeyChar);
                }
            }
            catch (InvalidOperationException) { return (Console.ReadLine() ?? "").Trim(); }   // not a real console: read it plainly
            Console.WriteLine();
            return b.ToString();
        }

        public static List<string> ServerCandidates(string extra)
        {
            var host = Environment.MachineName;
            var output = new List<string>();
            foreach (var s in new[] { extra, ".", "localhost", "(local)", ".\\SQLEXPRESS", host, host + "\\SQLEXPRESS", "127.0.0.1" })
                if (!string.IsNullOrEmpty(s) && !output.Contains(s)) output.Add(s);
            return output;
        }

        /// <summary>The user databases on this server that hold the attendance system's tables (usually just etimetracklite).</summary>
        static List<string> AttendanceDatabases(SqlDb db)
        {
            var found = new List<string>();
            foreach (var r in db.Query("SELECT name FROM sys.databases WHERE database_id > 4 AND state = 0 ORDER BY name"))
            {
                var name = Attendance.Str(r[0]);
                try
                {
                    var n = db.Query("SELECT COUNT(*) FROM [" + name.Replace("]", "]]") + "].INFORMATION_SCHEMA.TABLES " +
                                     "WHERE TABLE_NAME = 'AttendanceLogs' OR TABLE_NAME LIKE 'DeviceLogs[_]%'");
                    if (Convert.ToInt32(n[0][0]) > 0) found.Add(name);
                }
                catch (SqlException) { }
            }
            return found;
        }

        static string NewPassword()
        {
            var bytes = new byte[18];
            using (var rng = new RNGCryptoServiceProvider()) rng.GetBytes(bytes);
            return Convert.ToBase64String(bytes).Replace("+", "x").Replace("/", "y").Replace("=", "z");
        }

        /// <summary>A SQL login that can only read the attendance database, with a password made here.</summary>
        static bool MakeReader(SqlDb db, string database, out string password)
        {
            password = NewPassword();
            var quoted = "[" + database.Replace("]", "]]") + "]";
            try
            {
                db.Execute(string.Format("IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = '{0}') " +
                                         "CREATE LOGIN [{0}] WITH PASSWORD = '{1}', CHECK_POLICY = OFF " +
                                         "ELSE ALTER LOGIN [{0}] WITH PASSWORD = '{1}'", Program.Reader, password));
                db.Execute(string.Format("USE {0}; IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '{1}') " +
                                         "CREATE USER [{1}] FOR LOGIN [{1}]; EXEC sp_addrolemember 'db_datareader', '{1}'", quoted, Program.Reader));
                return true;
            }
            catch (SqlException exc)
            {
                Console.WriteLine("   (could not make a read-only login: " + Program.Short(exc) + ")");
                return false;
            }
        }

        /// <summary>Read-only access for the computer's own SYSTEM account, which the every-minute task runs as: what a SQL
        /// Server that only allows Windows sign-in needs, and no password is kept anywhere.</summary>
        static bool GrantSystem(SqlDb db, string database)
        {
            const string who = "NT AUTHORITY\\SYSTEM";
            var quoted = "[" + database.Replace("]", "]]") + "]";
            try
            {
                db.Execute(string.Format("IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'{0}') CREATE LOGIN [{0}] FROM WINDOWS", who));
                db.Execute(string.Format("USE {0}; IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'{1}') " +
                                         "CREATE USER [{1}] FOR LOGIN [{1}]; EXEC sp_addrolemember 'db_datareader', N'{1}'", quoted, who));
                return true;
            }
            catch (SqlException exc)
            {
                Console.WriteLine("   (could not give the SYSTEM account read access: " + Program.Short(exc) + ")");
                return false;
            }
        }

        static bool WindowsSignInOnly(SqlDb db)
        {
            try { return Convert.ToInt32(db.Query("SELECT CONVERT(int, SERVERPROPERTY('IsIntegratedSecurityOnly'))")[0][0]) == 1; }
            catch (SqlException) { return false; }
        }

        static string RunTool(string file, string arguments)
        {
            var p = new ProcessStartInfo(file, arguments) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
            using (var proc = Process.Start(p))
            {
                var output = proc.StandardOutput.ReadToEnd() + proc.StandardError.ReadToEnd();
                proc.WaitForExit();
                return proc.ExitCode == 0 ? null : output.Trim();
            }
        }

        /// <summary>The every-minute Windows task, as SYSTEM so it runs with nobody signed in. Needs an administrator.</summary>
        static bool InstallTask()
        {
            var exe = Path.Combine(Program.Here, "YerpBiometric.exe");
            var problem = RunTool("schtasks", string.Format("/Create /F /TN \"{0}\" /SC MINUTE /MO 1 /RU SYSTEM /RL HIGHEST /TR \"\\\"{1}\\\" --once --quiet\"", Program.Task, exe));
            if (problem == null) return true;
            Console.WriteLine("   Windows said: " + (problem.Length > 200 ? problem.Substring(0, 200) : problem));
            Console.WriteLine("   Right-click SETUP.bat and choose 'Run as administrator', then run it again.");
            return false;
        }

        /// <summary>Runs the task once now and waits for it to say how it went in sync.log: the proof that the SYSTEM
        /// account can read the database, which this window (signed in as somebody else) cannot test itself.</summary>
        static bool TaskWorks()
        {
            var logPath = Path.Combine(Program.Here, "sync.log");
            long before = File.Exists(logPath) ? new FileInfo(logPath).Length : 0;
            if (RunTool("schtasks", string.Format("/Run /TN \"{0}\"", Program.Task)) != null) return false;
            for (int i = 0; i < 40; i++)
            {
                Thread.Sleep(1000);
                if (!File.Exists(logPath) || new FileInfo(logPath).Length <= before) continue;
                string tail;
                using (var f = new FileStream(logPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    f.Seek(before, SeekOrigin.Begin);
                    tail = new StreamReader(f, Encoding.UTF8).ReadToEnd();
                }
                if (tail.Contains("failed:")) { Console.WriteLine("   the task said: " + tail.Trim()); return false; }
                if (tail.Contains("nothing new") || tail.Contains("sent ")) return true;
            }
            Console.WriteLine("   the task has not reported yet; look at sync.log in a minute.");
            return true;
        }

        public static int Run()
        {
            Console.WriteLine(new string('=', 66));
            Console.WriteLine(" Y ERP biometric attendance - set-up");
            Console.WriteLine(new string('=', 66));
            var cfg = Settings.Read(Program.ConfigPath);
            Console.WriteLine();
            Console.WriteLine(string.Format("1. This computer: {0}, {1}-bit Windows {2}, .NET {3}", Environment.MachineName,
                Environment.Is64BitOperatingSystem ? 64 : 32, Environment.OSVersion.Version, Environment.Version));

            Console.WriteLine();
            Console.WriteLine("2. Connecting to Y ERP ...");
            bool connected = false;
            for (int attempt = 0; attempt < 3 && !connected; attempt++)
            {
                if (cfg.Get("yerp", "url").Length == 0) cfg.Set("yerp", "url", Ask("   Y ERP address", "https://yalavartiinfra.com").TrimEnd('/'));
                var key = cfg.Get("yerp", "api_key");
                if (key.Length == 0 || key.StartsWith("PASTE")) cfg.Set("yerp", "api_key", Ask("   Paste the key from Y ERP (People > Attendance > Biometric)"));
                try
                {
                    var res = Erp.Call(cfg, "/api/biometric/ping");
                    object company;
                    Console.WriteLine("   key accepted for: " + (res.TryGetValue("company", out company) ? Attendance.Str(company) : ""));
                    connected = true;
                }
                catch (ApplicationException exc)
                {
                    Console.WriteLine("   " + exc.Message);
                    cfg.Set("yerp", "api_key", "");
                }
            }
            if (!connected)
            {
                Console.WriteLine("   Could not connect to Y ERP. Check the internet and the key, then run SETUP.bat again.");
                return 1;
            }

            Console.WriteLine();
            Console.WriteLine("3. Finding the attendance database ...");
            SqlDb db = null;
            string server = "", user = "", password = "";
            if (cfg.Get("database", "server").Length > 0 && cfg.Get("database", "user").Length > 0)
            {
                try
                {
                    db = new SqlDb(cfg.Get("database", "server"), "master", cfg.Get("database", "user"), cfg.Get("database", "password"));
                    server = cfg.Get("database", "server"); user = cfg.Get("database", "user"); password = cfg.Get("database", "password");
                }
                catch (SqlException) { db = null; }
            }
            if (db == null)
            {
                foreach (var s in ServerCandidates(cfg.Get("database", "server")))
                {
                    try
                    {
                        db = new SqlDb(s, "master", "", "", 6);         // this Windows account
                        server = s;
                        Console.WriteLine("   found SQL Server at " + s + " (signed in with this Windows account)");
                        break;
                    }
                    catch (SqlException) { }
                }
            }
            for (int tries = 1; db == null && tries <= 3; tries++)
            {
                Console.WriteLine("   Could not sign in automatically. Use the SQL Server login you use in Management Studio.");
                var candidates = ServerCandidates("");
                server = Ask("   SQL Server name", tries == 1 ? candidates[candidates.Count - 2] : server);
                user = Ask("   Login name", "sa");
                password = AskSecret("   Password (not shown)");
                try { db = new SqlDb(server, "master", user, password); }
                catch (SqlException exc) { Console.WriteLine("   Could not connect: " + Program.Short(exc)); }
            }
            if (db == null)
            {
                Console.WriteLine("   Giving up on the database. Ask for help with the message above.");
                return 1;
            }

            string database;
            bool asSystem = false;
            using (db)
            {
                var dbs = AttendanceDatabases(db);
                if (dbs.Count == 1)
                {
                    database = dbs[0];
                    Console.WriteLine("   the attendance database is: " + database);
                }
                else if (dbs.Count > 1)
                {
                    for (int i = 0; i < dbs.Count; i++) Console.WriteLine(string.Format("     {0}. {1}", i + 1, dbs[i]));
                    int choice;
                    var answer = Ask("   Which one is the attendance system's database (number)", "1");
                    database = int.TryParse(answer, out choice) && choice >= 1 && choice <= dbs.Count ? dbs[choice - 1] : dbs[0];
                }
                else database = Ask("   No attendance tables found. Database name", cfg.Get("database", "name", "etimetracklite"));

                Console.WriteLine();
                Console.WriteLine("4. Giving the every-minute sync read-only access ...");
                string made;
                if (WindowsSignInOnly(db))
                {
                    Console.WriteLine("   this SQL Server allows Windows sign-in only");
                    asSystem = GrantSystem(db, database);
                    if (asSystem) { user = ""; password = ""; Console.WriteLine("   the computer's SYSTEM account may now read " + database + " (no password is kept)"); }
                }
                else if (MakeReader(db, database, out made))
                {
                    user = Program.Reader; password = made;
                    Console.WriteLine(string.Format("   made the login '{0}' (it can only read {1})", user, database));
                }
                else if (GrantSystem(db, database))
                {
                    asSystem = true; user = ""; password = "";
                    Console.WriteLine("   the computer's SYSTEM account may now read " + database + " (no password is kept)");
                }
                if (!asSystem && user.Length == 0)
                {
                    Console.WriteLine("   This Windows account cannot give the sync access. Use a SQL login that can read " + database + ".");
                    user = Ask("   SQL login name", "sa");
                    password = AskSecret("   Password (not shown)");
                }
            }
            cfg.Set("database", "server", server); cfg.Set("database", "name", database);
            cfg.Set("database", "user", user); cfg.Set("database", "password", password);
            if (!asSystem)
            {
                try
                {
                    Program.Connect(cfg).Dispose();
                    Console.WriteLine(string.Format("   signed in to {0} as {1}: ok", database, user));
                }
                catch (SqlException exc)
                {
                    Console.WriteLine("   Could not sign in with that login: " + Program.Short(exc));
                    return 1;
                }
            }
            cfg.Write(Program.ConfigPath);
            Console.WriteLine("   saved config.ini");

            Console.WriteLine();
            Console.WriteLine("5. Reading the attendance system ...");
            // The SYSTEM account cannot be tried from this window; this Windows account reads it for the check and the first send.
            var here = Settings.Read(Program.ConfigPath);
            if (asSystem) { here.Set("database", "user", ""); here.Set("database", "password", ""); }
            try { Program.Check(here); }
            catch (Exception exc) { Console.WriteLine("   Could not read it: " + Program.Short(exc)); return 1; }

            Console.WriteLine();
            Console.WriteLine("6. Sending the last 7 days' punches ...");
            try { Program.RunOnce(here, 7); }
            catch (Exception exc) { Console.WriteLine("   Failed: " + Program.Short(exc)); return 1; }

            Console.WriteLine();
            Console.WriteLine("7. Starting the every-minute sync ...");
            if (!InstallTask())
            {
                Console.WriteLine("   The punches were sent, but the every-minute task is not set up yet (see above).");
                return 1;
            }
            Console.WriteLine(string.Format("   done: the task '{0}' runs every minute, with nobody signed in.", Program.Task));
            Console.WriteLine("   trying it once now ...");
            if (!TaskWorks())
            {
                Console.WriteLine("   The task could not read the database as SYSTEM. Run SETUP.bat again, or ask for help with sync.log.");
                return 1;
            }
            Console.WriteLine("   it works.");
            Console.WriteLine();
            Console.WriteLine("All set. In Y ERP open People > Attendance > Biometric: it should say 'Working'.");
            Console.WriteLine("People shown there as 'belonging to nobody' are numbers from the machines that match no employee yet.");
            return 0;
        }
    }
}
