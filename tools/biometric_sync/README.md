# Y ERP biometric sync

Sends punches from the office's eSSL eTimeTrackLite attendance system to Y ERP, so attendance shows there within a
minute or two. It runs on the office computer that holds the attendance database and only **reads** it.

## Set up (about 5 minutes)

1. **In Y ERP**, signed in as the Master: People > Attendance > **Biometric** > **Download set-up package**. It is a
   zip with this program and a `config.ini` that already holds your address and a key.
2. **Copy the zip to the office computer**, unzip it (for example to `C:\YERP\biometric_sync`).
3. **Double-click `SETUP.bat`** and answer what it asks. It:
   - installs the one extra part it needs (pyodbc), if Python is there;
   - finds the SQL Server and the attendance database by itself, signing in with this Windows account, or asking for
     the SQL login you use in Management Studio if that does not work;
   - makes a login that can only **read** the attendance database;
   - sends the first punches (it asks how many days back);
   - starts an every-minute Windows task, so it keeps going with nobody signed in and after restarts.

If Python is not on that computer, `SETUP.bat` says so and opens the download page. Install Python 3 (64-bit) and
**tick "Add python.exe to PATH"**, then double-click `SETUP.bat` again. Windows 7 needs Python 3.8, Windows 8.1 needs
3.9; Windows 10, 11 and Server 2016 or newer take 3.12.

For the every-minute task, right-click `SETUP.bat` > **Run as administrator** if it says it could not make it.

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
