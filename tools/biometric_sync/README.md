# Y ERP biometric sync

Sends punches from the office's eSSL eTimeTrackLite attendance system to Y ERP, so attendance shows there within a
minute or two. It runs on the office computer that holds the attendance database and only **reads** it.

## Set up (once, about 15 minutes)

1. **In Y ERP** (signed in as the Master): People > Attendance > **Biometric** > **Make the key**. Copy the key.
2. **On the office computer**, copy this whole `biometric_sync` folder to `C:\YERP\biometric_sync`.
3. **Install Python 3** from python.org if it is not there. Tick **"Add python.exe to PATH"** in the installer.
4. Open Command Prompt in that folder and run: `pip install pyodbc`
5. **Make a read-only database login:** open `make_reader_login.sql` in SQL Server Management Studio, change the
   password in it, and press Execute.
6. Copy `config.example.ini` to `config.ini`. Put in the key from step 1 and the password from step 5. If SQL Server is
   a named instance, set `server` (for example `localhost\SQLEXPRESS`).
7. Double-click **`run_check.bat`**. It should say the key is accepted, list the tables it found and show a few of
   today's punches. It sends nothing.
8. Double-click **`run_now.bat`** to send today's punches. Look at People > Attendance > Biometric in Y ERP.
9. Right-click **`install_task.bat`** > **Run as administrator**. From now on it sends every minute by itself, also
   after the computer restarts.

To bring in earlier days once: `python sync.py --backfill 30` (up to 120 days).

## In Y ERP afterwards

- **Machines:** each machine appears the first time it sends a punch. Give it a name and the site it stands at.
- **Punches belonging to nobody:** a number from the machine that matches no employee code. Put the number against the
  person in the list below it; their waiting punches are counted at once.

## If something is wrong

- `sync.log` in this folder says what happened each minute.
- "key is not in use": a new key was made in Y ERP; put it in `config.ini`.
- "Login failed": the user or password in `config.ini`, or SQL Server does not allow SQL logins (Server properties >
  Security > "SQL Server and Windows Authentication mode").
- Nothing new although people punched: eTimeTrackLite has not downloaded from the machines yet. Its own download
  interval decides how "live" attendance can be.
- To stop it: run `remove_task.bat` as administrator.

`config.ini` holds a password and the key. Keep the folder where only administrators can open it.
