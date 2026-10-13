"""One-off: take the GST off retention releases that were raised before releases stopped carrying it.

GST is charged on the whole of every RA bill and every gang bill, retention included. A retention release used to
charge it again, on both sides, so the GST registers were overstated by the tax on every release.

    python backend/scripts/fix_release_gst.py            # dry run: lists what would change, changes nothing
    python backend/scripts/fix_release_gst.py --apply    # does it, after writing a backup CSV next to this script

What --apply does to each live release that carries tax: gst_percent and the CGST / SGST / IGST amounts become 0, and
net_amount becomes the retention released. The old figures go into the backup CSV and the audit log.

Read this before applying: the registers for a month already filed will no longer agree with what was filed. The
correction belongs in the month you are in (a revised figure on the next return), so give your accountant the CSV.
Releases against which money has already moved are listed separately - the receipt or payment was for the larger
figure, and the difference needs a decision from a person, so the script leaves those alone even with --apply.
"""
import argparse
import csv
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))      # backend/

from app import models                          # noqa: E402  (builds the application first)
from app.core.audit import log_audit            # noqa: E402
from app.db import SessionLocal                 # noqa: E402
from app.services.crm import settled_on         # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="make the change (default is a dry run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = db.query(models.DBRetentionRelease).filter(
            models.DBRetentionRelease.status != "CANCELLED").order_by(models.DBRetentionRelease.id).all()
        todo = [r for r in rows if (r.gst_amount or 0) > 0]
        print("%d live release(s); %d carry GST." % (len(rows), len(todo)))
        fixable, held_back = [], []
        for r in todo:
            got = settled_on(db, r.client_id, "retention_release", r.id) or 0.0
            (held_back if got > 0 else fixable).append((r, got))

        def show(label, items):
            if not items:
                return
            print("\n%s" % label)
            for r, got in items:
                print("  #%-5s %-12s %-10s %-10s released %12.2f  GST %10.2f (%s%%)  settled %.2f" % (
                    r.id, r.number, r.side, (r.release_on or "")[:10], r.amount or 0, r.gst_amount or 0,
                    r.gst_percent or 0, got))
            print("  GST to come off: %.2f" % sum(r.gst_amount or 0 for r, _ in items))

        show("Will be corrected:", fixable)
        show("LEFT ALONE - money has moved against these (decide by hand):", held_back)

        if not args.apply:
            print("\nDry run. Nothing was changed. Run again with --apply to correct the first list.")
            return
        if not fixable:
            print("\nNothing to correct.")
            return

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(HERE, "release_gst_backup_%s.csv" % stamp)
        cols = ["id", "client_id", "number", "side", "release_on", "amount", "gst_percent", "gst_amount",
                "cgst_amount", "sgst_amount", "igst_amount", "net_amount"]
        with open(backup, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for r, _ in fixable:
                w.writerow([getattr(r, c) for c in cols])
        print("\nBackup written: %s" % backup)

        for r, _ in fixable:
            was = "GST %.2f (%s%%), net %.2f" % (r.gst_amount or 0, r.gst_percent or 0, r.net_amount or 0)
            r.gst_percent = 0.0
            r.gst_amount = r.cgst_amount = r.sgst_amount = r.igst_amount = 0.0
            r.net_amount = r.amount or 0.0
            log_audit(db, r.client_id, "retention_release_gst_removed", "retention_release", r.id, r.number,
                      "GST was already charged on the bills; removed from the release. Was: " + was)
        db.commit()
        print("Corrected %d release(s)." % len(fixable))
    finally:
        db.close()


if __name__ == "__main__":
    main()
