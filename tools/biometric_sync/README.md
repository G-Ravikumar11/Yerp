# Y ERP biometric sync

Sends punches from the office's eSSL eTimeTrackLite attendance system to Y ERP, so attendance shows there within a
minute or two. It runs on the office computer that holds the attendance database and only **reads** it.

## Set up (about a minute)

1. **On the office computer** (over AnyDesk is fine), open Y ERP in its browser, sign in as the Master, and go to
   People > Attendance > **Biometric** > **Download set-up package**.
2. **Unzip it** and double-click **`SETUP.bat`**. Click **Yes** when Windows asks for permission.

That is all. `SETUP.bat`:
- makes the program (`YerpBiometric.exe`) on the spot with the C# compiler that comes with Windows' .NET Framework -
  **nothing is downloaded and nothing is installed**;
- finds the SQL Server and the attendance database by itself, signing in with this Windows account, or asking for
  the SQL login you use in Management Studio if that does not work;
- gives the sync **read-only** access: a read-only SQL login, or - when SQL Server allows Windows sign-in only, as SQL
  Express does out of the box - read access for the computer's own SYSTEM account, so no password is kept at all;
- sends the last 7 days' punches, starts an every-minute Windows task that keeps going with nobody signed in, and runs
  it once to prove it works.

### Which Windows

Any Windows from **Windows 7 SP1 / Server 2008 R2 to Windows 11 / Server 2025, 32- or 64-bit**. It needs the
Microsoft .NET Framework 4.5 or newer, which Windows 8, 10 and 11 already have. On Windows 7, if `SETUP.bat` says .NET
is missing, install ".NET Framework 4.8" (the offline installer from microsoft.com) and run it again. It talks to SQL
Server 2005 or newer through .NET's own client, so no ODBC driver is needed, and to Y ERP over TLS 1.2.

Internet is needed only for reaching Y ERP itself.

To bring in more history later: `YerpBiometric.exe --backfill 30` (in this folder).

## In Y ERP afterwards

The Biometric tab says **Working** when punches are arriving.

- **Machines:** each appears the first time it sends a punch. Give it a name and the site it stands at.
- **Punches belonging to nobody:** a number from the machines that matches no employee code. Where the machine's name
  for the person plainly matches an employee, a **"Looks like ... - match"** button is shown; press it. Otherwise put the
  number against the person in the list below.

## If something is wrong

- `sync.log` in this folder says what happened each minute (kept to about 2 MB; the one before is `sync.log.1`).
- **".NET Framework 4.5 or newer"**: see *Which Windows* above.
- **"key is not in use"** or **401**: a new package or key was made in Y ERP. Download the package again and run
  `SETUP.bat`.
- **Login failed** in `sync.log`: run `SETUP.bat` again; it gives the access afresh.
- **Nothing new although people punched:** eTimeTrackLite has not downloaded from the machines yet; its own download
  interval decides how "live" attendance can be.

## Other files

| File | What it does |
|---|---|
| `YerpBiometric.cs` | The program, as readable source. `build.bat` turns it into `YerpBiometric.exe`. |
| `run_check.bat` | Looks at the database and the key, shows what it found, sends nothing. |
| `run_now.bat` | Sends once. |
| `install_task.bat` / `remove_task.bat` | Starts / stops the every-minute task (as administrator). |
| `make_reader_login.sql` | The read-only access, to give by hand in Management Studio if the set-up could not. |
| `config.ini` | The settings. Holds a key (and a password if a SQL login is used): keep the folder where only administrators can open it. |
| `test\SelfTest.cs` | Tests, run by the Y ERP test suite on Windows; not part of the package. |
