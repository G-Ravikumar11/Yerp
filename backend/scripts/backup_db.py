"""Back up the database to a timestamped file, and optionally prove the backup restores.

    python scripts/backup_db.py                  # write backups/yerp-<time>.sql.gz (Postgres) or .db (SQLite)
    python scripts/backup_db.py --out D:\\safe   # choose the folder
    python scripts/backup_db.py --keep 14        # delete all but the newest 14 backups
    python scripts/backup_db.py --verify         # also restore into a scratch DB and compare table counts

Postgres needs pg_dump (and, for --verify, psql/createdb/dropdb) on PATH. DATABASE_URL is read from the
environment or backend/.env, the same as the app. Run it from cron / Task Scheduler / a Railway cron service.
"""
import argparse
import glob
import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND_DIR, ".env"))
except ImportError:
    pass


def _sqlite_path(url: str) -> str:
    path = url.split("sqlite:///", 1)[1]
    return path if os.path.isabs(path) else os.path.join(BACKEND_DIR, path)


def _sqlite_counts(path: str) -> dict:
    con = sqlite3.connect(path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


def backup_sqlite(url: str, out_dir: str, stamp: str, verify: bool) -> str:
    src = _sqlite_path(url)
    dest = os.path.join(out_dir, f"yerp-{stamp}.db")
    # The online backup API gives a consistent copy even while the app is writing.
    source, target = sqlite3.connect(src), sqlite3.connect(dest)
    with target:
        source.backup(target)
    source.close()
    target.close()
    if verify:
        if _sqlite_counts(src) != _sqlite_counts(dest):
            raise SystemExit("VERIFY FAILED: backup table counts differ from the live database")
        print("Verified: backup opens and every table has the same row count.")
    return dest


def backup_postgres(url: str, out_dir: str, stamp: str, verify: bool) -> str:
    if not shutil.which("pg_dump"):
        raise SystemExit("pg_dump was not found on PATH")
    dest = os.path.join(out_dir, f"yerp-{stamp}.sql.gz")
    dump = subprocess.run(["pg_dump", "--no-owner", "--no-privileges", url],
                          capture_output=True, check=True)
    with gzip.open(dest, "wb") as f:
        f.write(dump.stdout)
    if verify:
        _verify_postgres(url, dest, stamp)
    return dest


def _verify_postgres(url: str, dump_path: str, stamp: str) -> None:
    for tool in ("psql", "createdb", "dropdb"):
        if not shutil.which(tool):
            raise SystemExit(f"--verify needs {tool} on PATH")
    scratch = f"yerp_verify_{stamp.replace('-', '_')}"
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    scratch_url = urlunsplit(parts._replace(path="/" + scratch))
    count_sql = ("SELECT table_name, (xpath('/row/c/text()', query_to_xml("
                 "format('SELECT COUNT(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text "
                 "FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' "
                 "ORDER BY 1")

    def counts(target: str) -> str:
        return subprocess.run(["psql", "-At", target, "-c", count_sql],
                              capture_output=True, check=True, text=True).stdout

    subprocess.run(["createdb", "--maintenance-db", url, scratch], check=True)
    try:
        with gzip.open(dump_path, "rb") as f:
            subprocess.run(["psql", "-q", scratch_url], input=f.read(), check=True, capture_output=True)
        if counts(url) != counts(scratch_url):
            raise SystemExit("VERIFY FAILED: restored table counts differ from the live database")
        print("Verified: backup restored into a scratch database with matching row counts.")
    finally:
        subprocess.run(["dropdb", "--maintenance-db", url, scratch], check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(BACKEND_DIR, "backups"))
    ap.add_argument("--keep", type=int, default=0, help="keep only the newest N backups (0 = keep all)")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        url = "sqlite:///" + os.path.join(BACKEND_DIR, "demo_portal.db")
    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    if url.startswith("sqlite"):
        dest = backup_sqlite(url, args.out, stamp, args.verify)
    else:
        dest = backup_postgres(url, args.out, stamp, args.verify)
    print(f"Backup written: {dest} ({os.path.getsize(dest):,} bytes)")

    if args.keep > 0:
        old = sorted(glob.glob(os.path.join(args.out, "yerp-*")), reverse=True)[args.keep:]
        for path in old:
            os.remove(path)
            print(f"Removed old backup: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
