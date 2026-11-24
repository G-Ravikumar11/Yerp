# Restoring the database from a nightly backup

Every night at 02:00 India time, GitHub Actions ("Nightly database backup") copies the live database, restores the copy
into a scratch database to prove every table and row came across, encrypts it with the backup passphrase and keeps it
for 30 days.

## Get a copy

1. On GitHub: **Actions > Nightly database backup**, open the night you want, and download **yerp-database-YYYY-MM-DD**
   (a zip holding `yerp-YYYY-MM-DD.dump.gpg`). Unzip it.
2. Decrypt it with the passphrase (the `BACKUP_PASSPHRASE` secret - kept by the Master, not readable back from GitHub):

   ```
   gpg --output yerp.dump --decrypt yerp-YYYY-MM-DD.dump.gpg
   ```

   (Windows: install Gpg4win; the same command works in its command prompt.)

## Look at it without touching the live site

Restore into a new, empty database - a local PostgreSQL 17, or a new branch in Neon:

```
pg_restore --no-owner --no-privileges --dbname="postgresql://USER:PASSWORD@HOST/NEWDB" yerp.dump
```

## Put it back on the live site (only when the live data is lost or damaged)

1. Tell everybody to stop using Y ERP; note the time.
2. Make a fresh copy of the live database as it is now, first (run the workflow by hand, or `python backend/scripts/backup_db.py`),
   so nothing is lost if the wrong night is chosen.
3. Restore into a **new** database (a new Neon branch is quickest), check it in a copy of the app, then point Railway's
   `DATABASE_URL` at it and redeploy. Restoring over the live database in place is the last resort.
4. Anything entered after the backup's night has to be entered again.

## Checks

- A night that failed shows red under Actions, and GitHub emails the repository owner.
- Neon also keeps its own point-in-time history for a short window; that is the faster way back from a mistake made
  in the last few hours.
