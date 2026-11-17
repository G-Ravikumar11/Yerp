# Y ERP biometric sync

Sends punches from the office's eSSL eTimeTrackLite attendance system to Y ERP, so attendance shows there within a
minute or two. It runs on the office computer that holds the attendance database and only **reads** it.

## Set up (under 2 minutes)

1. **On the office computer** (over AnyDesk is fine), open Y ERP in its browser, sign in as the Master, and go to
   People > Attendance > **Biometric** > **Download set-up package**.
2. **Unzip it** and double-click **`SETUP.bat`**. Click **Yes** when Windows asks for permission.

That is all. `SETUP.bat`:
- fetches its own copy of Python and pyodbc into the folder (about 11 MB, the first time only), checking both files
  against fixed fingerprints; nothing is installed in Windows;
- finds the SQL Server and the attendance database by itself, signing in with this Windows account, or asking for
  the SQL login you use in Management Studio if that does not work;
- makes a login that can only **read** the attendance database;
- sends the last 7 days' punches, and starts an every-minute Windows task that keeps going with nobody signed in.

Needs 64-bit Windows 8.1 / Server 2012 R2 or newer, and internet on that computer. On older Windows, `SETUP.bat`
says which Python to install by hand. To bring in more history later: `python\python.exe sync.py --backfill 30`.

## In Y ERP afterwards

The Biometric tab says **Working** when punches are arriving.

- **Machines:** each appears the first time it sends a punch. Give it a name and the site it stands at.
- **Punches belonging to nobody:** a number from the machines that matches no employee code. Where the machine's name
  for the person plainly matches an employee, a **"Looks like ... - match"** button is shown; press it. Otherwise put the
  number against the person in the list below.

## If something is wrong

- `sync.log` in this folder says what happened each minute.
- **"key is not in use":** a new package or key was made in Y ERP. Download the package again and run `SETUP.bat`.
- **Login failed:** the SQL Server may only allow Windows sign-in. In Management Studio: server properties > Security >
  "SQL Server and Windows Authentication mode", then restart the SQL Server service.
- **Nothing new although people punched:** eTimeTrackLite has not downloaded from the machines yet; its own download
  interval decides how "live" attendance can be.

## Other files (for doing it by hand)

| File | What it does |
|---|---|
| `run_check.bat` | Looks at the database and the key, shows what it found, sends nothing. |
| `run_now.bat` | Sends once. |
| `install_task.bat` / `remove_task.bat` | Starts / stops the every-minute task (as administrator). |
| `make_reader_login.sql` | The read-only login, to run by hand in Management Studio. |
| `config.ini` | The settings. Holds a key and a password: keep the folder where only administrators can open it. |
