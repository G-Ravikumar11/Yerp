"""Start the application against a database and fail if its schema did not come out right.

    DATABASE_URL=postgresql://... python scripts/check_migrations.py

Start-up runs every schema step (create_all, then the ALTER ... IF NOT EXISTS steps for databases made by an earlier
version). Those steps are non-fatal by design - a failed one is recorded and the server still starts - so a broken
migration does not stop a deploy on its own. This makes it stop CI instead:

- every start-up schema step must succeed (migration_report() empty, /api/health "ok", not "ok_with_warnings");
- every table and column the models define must exist in the database afterwards. On a database made by an earlier
  version this is what catches a column added to a model without the ALTER that adds it to existing databases.

Run it on an empty database (a new install) and on one an earlier commit has already set up (an upgrade). It changes
nothing but the schema of the database it is pointed at - use a throwaway one.
"""
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("Set DATABASE_URL to a throwaway database.")
    os.environ.setdefault("SECRET_KEY", "migration-check-only")
    os.environ.setdefault("SCHEDULER_ENABLED", "0")
    os.environ.setdefault("COOKIE_SECURE", "false")
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        os.environ[k] = ""                                   # never send mail
    sys.path.insert(0, BACKEND)
    os.chdir(BACKEND)

    from fastapi.testclient import TestClient
    from sqlalchemy import inspect

    from app import db as database
    from app import models
    import main as app_main

    with TestClient(app_main.app) as c:                      # the whole start-up, as a deploy runs it
        health = c.get("/api/health").json()
    errors = database.migration_report()

    insp = inspect(database.engine)
    have_tables = set(insp.get_table_names())
    missing_tables, missing_columns = [], []
    for name, table in sorted(models.Base.metadata.tables.items()):
        if name not in have_tables:
            missing_tables.append(name)
            continue
        cols = {c["name"] for c in insp.get_columns(name)}
        missing_columns += ["%s.%s" % (name, c.name) for c in table.columns if c.name not in cols]

    print("Database: %s" % database.engine.dialect.name)
    print("Health: %s" % health.get("status"))
    print("Tables the models define: %d" % len(models.Base.metadata.tables))
    failed = False
    if errors:
        failed = True
        print("FAIL: %d start-up schema step(s) failed:" % len(errors))
        for e in errors:
            print("  - %s" % e)
    if health.get("status") != "ok" or health.get("database") not in (None, "ok"):
        failed = True
        print("FAIL: /api/health answered %s" % health)
    if missing_tables:
        failed = True
        print("FAIL: tables missing after start-up: %s" % ", ".join(missing_tables))
    if missing_columns:
        failed = True
        print("FAIL: columns the models define but the database lacks (a migration is missing): %s" % ", ".join(missing_columns))
    print("RESULT: %s" % ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
