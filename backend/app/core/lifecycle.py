"""What happens when the server starts: migrations, back-fills and the background scheduler."""
import json
import re

from sqlalchemy import func, or_

from app import models
from app.db import SessionLocal

from app.core.config import logger
from app.core.currency import money


# Whether the database came up. Read by the health check, so an instance that
# cannot reach its database is taken out of rotation rather than serving
# half-working pages.
DB_READY = {"ok": False, "error": ""}


def _boot_step(label, fn):
    """One step of start-up that must never take the process down.

    A database that is unreachable at boot - a rotated password, a sleeping
    instance, a network blip - used to leave start-up half-finished: the
    server never began listening and every request answered 502, with
    nothing on the page to say why. Now each step is survivable, the failure
    is logged once in words, and the health check reports it.
    """
    try:
        fn()
        return True
    except Exception as exc:
        logger.error("Start-up step %s failed: %s", label, exc)
        DB_READY["error"] = "%s: %s" % (label, exc)
        return False


def fill_document_names():
    """Names for documents uploaded before the names were kept beside them."""
    db = SessionLocal()
    try:
        rows = db.query(models.DBContractor).filter(
            or_(models.DBContractor.document_names.is_(None), models.DBContractor.document_names == "{}"),
            models.DBContractor.document_files.isnot(None), models.DBContractor.document_files != "{}",
            models.DBContractor.document_files != "").all()
        for c in rows:
            try:
                files = json.loads(c.document_files or "{}")
            except Exception:
                continue
            c.document_names = json.dumps({k: v.get("name") or "" for k, v in files.items()
                                           if isinstance(v, dict) and v.get("data")})
        db.commit()
    finally:
        db.close()


def backfill_entry_codes():
    """Entries recorded before they had codes are numbered, oldest first, after any that already have one."""
    with SessionLocal() as db:
        orders = [r[0] for r in db.query(models.DBSubMeasurement.order_id).filter(
            or_(models.DBSubMeasurement.code.is_(None), models.DBSubMeasurement.code == "")).distinct().all()]
        for order_id in orders:
            wo = db.query(models.DBSubcontractOrder.wo_number).filter(
                models.DBSubcontractOrder.id == order_id).scalar() or "MB"
            top = db.query(func.max(models.DBSubMeasurement.code_no)).filter(
                models.DBSubMeasurement.order_id == order_id).scalar() or 0
            for m in db.query(models.DBSubMeasurement).filter(
                    models.DBSubMeasurement.order_id == order_id,
                    or_(models.DBSubMeasurement.code.is_(None), models.DBSubMeasurement.code == "")).order_by(
                        models.DBSubMeasurement.id).all():
                top += 1
                m.code_no, m.code = top, "%s/MB-%03d" % (wo, top)
            db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == order_id).update(
                {"mb_code_seq": top}, synchronize_session=False)
        db.commit()


#
# An import once wrote the sheet's hold into each block as a line - "Held back for finishes and handing over
# (55% of 7059.4)" - so the printed block came to less than the sheet says. Those lines are taken out, the block
# is put back to what the sheet measured, and the hold is recorded once for its group. The quantity billed does
# not change. An entry on a bill that has been sent is left as it is.
LEGACY_HOLD_PREFIX = "Held back for finishes and handing over ("


def convert_legacy_holds(db, client_id=None):
    q = db.query(models.DBMeasurementDimension).filter(
        models.DBMeasurementDimension.sub_measurement_id.isnot(None),
        models.DBMeasurementDimension.particulars.like(LEGACY_HOLD_PREFIX + "%"))
    lines = q.all()
    by_entry = {}
    for d in lines:
        by_entry.setdefault(d.sub_measurement_id, []).append(d)
    converted, skipped, groups = 0, set(), {}
    for entry_id, dl in by_entry.items():
        m = db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.id == entry_id).first()
        if not m or (client_id and m.client_id != client_id) or (getattr(m, "kind", "") or ""):
            continue
        if m.sub_bill_id:
            bill = db.query(models.DBSubBill).filter(models.DBSubBill.id == m.sub_bill_id).first()
            if bill and (bill.status or "") != "DRAFT":
                skipped.add(bill.number or str(bill.id))
                continue
        mult = getattr(m, "multiplier", None) or 1.0
        cut = sum(abs(d.quantity or 0) for d in dl)
        held = money(cut * mult)
        pct = re.search(r"\(([0-9.]+)%", dl[0].particulars or "")
        for d in dl:
            db.delete(d)
        m.quantity = money((m.quantity or 0) + held)
        key = (m.client_id, m.order_id, m.item_id, (getattr(m, "group_ref", "") or "").strip() or "e%d" % m.id,
               m.mb_ref or "", m.sub_bill_id)
        g = groups.setdefault(key, {"entry": m, "held": 0.0, "entries": [], "pct": pct.group(1) if pct else ""})
        g["held"] = money(g["held"] + held)
        g["entries"].append(m)
        converted += 1
    for key, g in groups.items():
        first = g["entry"]
        new_ref = ("cv%d-%s" % (first.id, key[3]))[:60]
        for m in g["entries"]:
            m.group_ref = new_ref
        db.add(models.DBSubMeasurement(
            client_id=first.client_id, order_id=first.order_id, item_id=first.item_id, activity_no=first.activity_no or "",
            measured_on=first.measured_on, quantity=-g["held"], kind="hold", mb_ref=first.mb_ref or "",
            location="Held back", remarks="Held back for finishes and handing over%s" % ((" - %s%% held" % g["pct"]) if g["pct"] else ""),
            recorded_by=first.recorded_by, recorded_by_name=first.recorded_by_name,
            section=getattr(first, "section", "") or "", group_ref=new_ref, sub_bill_id=first.sub_bill_id))
    if converted:
        db.flush()
    return {"converted": converted, "holds": len(groups), "left_on_sent_bills": sorted(skipped)}


def convert_legacy_holds_all():
    """At start-up: books imported the old way are put right. A failure is logged and never stops the server."""
    try:
        with SessionLocal() as db:
            done = db.query(models.DBSettings).filter(models.DBSettings.client_id.is_(None),
                                                      models.DBSettings.key == "legacy_holds_converted").first()
            if done:
                return
            out = convert_legacy_holds(db)
            if not out["converted"]:
                db.add(models.DBSettings(client_id=None, key="legacy_holds_converted", value="1",
                                         description="Old imports with the hold written into the blocks were put right"))
            db.commit()
            if out["converted"]:
                logger.info("Old imported holds put right: %s", out)
    except Exception:
        logger.exception("Could not put right the old imported holds")
