"""Store module - what accounts need from the stores: the value of stock held, goods received but not yet billed, scrap sales still to be paid for,
the cost that must be charged across when stock moves between two projects, and the price differences found when a gate delivery was linked to its
order. Nothing here moves stock. The one thing it writes is the receipt for a scrap sale, into the bank book, where accounts already keep money."""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.models.store_control import DBStoreScrap, DBStoreScrapLine, DBStoreTransfer, DBStoreTransferLine
from app.models.store_core import DBStore, DocStatus
from app.models.store_extras import DBStoreCrossCharge, DBStoreScrapReceipt
from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
from app.services import store_reports
from app.services.money import next_money_number

ZERO = Decimal("0")
BILLED = ("Awaiting Approval", "Approved for payment", "Paid")        # a supplier bill that counts as billed (not a draft, not rejected)
SCRAP_HEAD = "Scrap sale"


def v2(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def s2(x) -> str:
    return format(v2(x), "f")


# --- goods received, not billed ---------------------------------------------------------------------------------------------

def grni(db, client_id):
    """Per purchase order: what the posted receipts took into stock (accepted quantity at the rate received), what suppliers have billed against the
    order, and the difference. Positive is received and not yet billed; negative is billed for more than was received."""
    rows = (db.query(DBStoreGrn.po_id, func.sum(DBStoreGrnLine.accepted_qty * DBStoreGrnLine.rate), func.max(DBStoreGrn.grn_date))
            .join(DBStoreGrnLine, DBStoreGrnLine.grn_id == DBStoreGrn.id)
            .filter(DBStoreGrn.client_id == client_id, DBStoreGrn.status == DocStatus.POSTED.value, DBStoreGrn.po_id.isnot(None)).group_by(DBStoreGrn.po_id).all())
    received = {po: (Decimal(str(v or 0)), last) for po, v, last in rows}
    ids = list(received)
    billed = {po: Decimal(str(v or 0)) for po, v in db.query(models.DBBill.purchase_order_id, func.sum(models.DBBill.amount)).filter(
        models.DBBill.client_id == client_id, models.DBBill.purchase_order_id.in_(ids or [0]), models.DBBill.status.in_(BILLED)).group_by(models.DBBill.purchase_order_id).all()}
    pos = {p.id: p for p in db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.id.in_(ids or [0])).all()}
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    out = []
    for po_id, (got, last) in received.items():
        po = pos.get(po_id)
        gap = v2(got) - v2(billed.get(po_id, ZERO))
        if po is None or gap == 0:
            continue
        job = jobs.get(po.job_id)
        out.append({"po_id": po_id, "po_number": po.number or "", "supplier_name": po.supplier_name or "", "project": (job.name or job.number) if job else "",
                    "received_value": s2(got), "billed_value": s2(billed.get(po_id, ZERO)), "difference": format(gap, "f"), "last_received": last.isoformat() if last else "",
                    "status": "NOT_BILLED" if gap > 0 else "OVER_BILLED"})
    out.sort(key=lambda r: (r["status"] != "OVER_BILLED", -abs(Decimal(r["difference"]))))
    return out


# --- scrap sales -----------------------------------------------------------------------------------------------------------

def scrap_sales(db, client_id, store_ids=None):
    """Posted scrap documents that sold something: what they were to fetch, what has been received into the bank book, and what is still to collect."""
    q = (db.query(DBStoreScrap, func.sum(DBStoreScrapLine.realised_value))
         .join(DBStoreScrapLine, DBStoreScrapLine.scrap_id == DBStoreScrap.id)
         .filter(DBStoreScrap.client_id == client_id, DBStoreScrap.status == DocStatus.POSTED.value).group_by(DBStoreScrap.id))
    if store_ids is not None:
        q = q.filter(DBStoreScrap.store_id.in_(list(store_ids) or [0]))
    rows = [(s, Decimal(str(v or 0))) for s, v in q.all()]
    rows = [(s, v) for s, v in rows if v > 0]
    got = {sid: Decimal(str(v or 0)) for sid, v in db.query(DBStoreScrapReceipt.scrap_id, func.sum(DBStoreScrapReceipt.amount)).filter(
        DBStoreScrapReceipt.client_id == client_id, DBStoreScrapReceipt.scrap_id.in_([s.id for s, _v in rows] or [0])).group_by(DBStoreScrapReceipt.scrap_id).all()}
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.client_id == client_id).all()}
    out = []
    for s, due in rows:
        have = got.get(s.id, ZERO)
        out.append({"scrap_id": s.id, "number": s.number, "date": s.scrap_date.isoformat() if s.scrap_date else "", "store_code": stores[s.store_id].code if s.store_id in stores else "",
                    "store_id": s.store_id, "project_id": s.project_id, "buyer": s.buyer or "", "reference": s.reference or "", "realised": s2(due), "received": s2(have),
                    "outstanding": s2(max(ZERO, due - have)), "settled": have >= due})
    out.sort(key=lambda r: (r["settled"], r["date"]), reverse=False)
    return out


def receive_scrap_proceeds(db, actor, scrap_id, amount, account_id, paid_on, mode, reference):
    """Record money received for a scrap sale as a sundry receipt (head 'Scrap sale') in the bank book, charged to the scrap's project, and link it."""
    scrap = db.get(DBStoreScrap, scrap_id)
    if scrap is None or scrap.client_id != actor.client.id:
        raise HTTPException(404, "Scrap document not found")
    if scrap.status != DocStatus.POSTED.value:
        raise HTTPException(409, "Only a posted scrap document has been sold.")
    due = Decimal(str(db.query(func.sum(DBStoreScrapLine.realised_value)).filter(DBStoreScrapLine.scrap_id == scrap.id).scalar() or 0))
    have = Decimal(str(db.query(func.sum(DBStoreScrapReceipt.amount)).filter(DBStoreScrapReceipt.scrap_id == scrap.id).scalar() or 0))
    try:
        amt = Decimal(str(amount).strip())
    except Exception:
        raise HTTPException(400, "How much was received?") from None
    if not amt.is_finite() or amt <= 0:
        raise HTTPException(400, "How much was received?")
    if amt > due - have:
        raise HTTPException(400, "%s has only %s left to collect; %s is more than that." % (scrap.number, s2(max(ZERO, due - have)), s2(amt)))
    on = (paid_on or date.today().isoformat())[:10]
    try:
        if datetime.strptime(on, "%Y-%m-%d").date() > date.today():
            raise HTTPException(400, "The date cannot be in the future.")
    except ValueError:
        raise HTTPException(400, "The date is not a date (use YYYY-MM-DD).") from None
    account = None
    if account_id:
        account = db.query(models.DBBankAccount).filter(models.DBBankAccount.id == account_id, models.DBBankAccount.client_id == actor.client.id).first()
        if account is None:
            raise HTTPException(404, "That bank account is not on file.")
    mode = mode if mode in ("Bank transfer", "Cheque", "Cash", "UPI") else "Bank transfer"
    if account is not None and account.kind == "Cash":
        mode = "Cash"
    if mode == "Cheque" and not (reference or "").strip():
        raise HTTPException(400, "A cheque needs the cheque number.")
    entry = models.DBMoneyEntry(client_id=actor.client.id, number=next_money_number(db, actor.client.id, "IN"), direction="IN", party_type="other", party_name=scrap.buyer or "Scrap buyer",
                                doc_type="income", doc_number=scrap.number, job_id=scrap.project_id, account_id=account.id if account else None, amount=float(amt), paid_on=on, mode=mode,
                                reference=(reference or "").strip()[:80], note=("Scrap sale %s" % scrap.number)[:300], recorded_by_name=actor.name, head=SCRAP_HEAD)
    db.add(entry)
    db.flush()
    db.add(DBStoreScrapReceipt(client_id=actor.client.id, scrap_id=scrap.id, money_entry_id=entry.id, amount=amt))
    db.flush()
    return entry


# --- inter-project transfers -----------------------------------------------------------------------------------------------

def sync_cross_charges(db, client_id):
    """Keep one row for each received inter-project transfer. A row whose transfer has since been cancelled is voided - or, if accounts had already
    adjusted for it, marked REVERSE so they put it back."""
    moved = db.query(DBStoreTransfer).filter(DBStoreTransfer.client_id == client_id, DBStoreTransfer.inter_project == 1, DBStoreTransfer.status == DocStatus.POSTED.value,
                                             DBStoreTransfer.receipt_status == "RECEIVED").all()
    have = {r.transfer_id: r for r in db.query(DBStoreCrossCharge).filter(DBStoreCrossCharge.client_id == client_id).all()}
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.client_id == client_id).all()}
    worth = {t: Decimal(str(v or 0)) for t, v in db.query(DBStoreTransferLine.transfer_id, func.sum(DBStoreTransferLine.value)).filter(
        DBStoreTransferLine.transfer_id.in_([t.id for t in moved] or [0])).group_by(DBStoreTransferLine.transfer_id).all()}
    live = set()
    for t in moved:
        live.add(t.id)
        if t.id not in have:
            src, dest = stores.get(t.store_id), stores.get(t.to_store_id)
            db.add(DBStoreCrossCharge(client_id=client_id, transfer_id=t.id, from_project_id=src.project_id if src else None, to_project_id=dest.project_id if dest else None,
                                      amount=worth.get(t.id, ZERO), status="PENDING"))
    for tid, row in have.items():
        if tid not in live:
            if row.status == "PENDING":
                row.status = "VOID"
            elif row.status == "ADJUSTED":
                row.status = "REVERSE"
        elif row.status in ("VOID", "REVERSE"):                      # received again after a cancel was undone by a new transfer is a new row; this one is live again
            row.status = "ADJUSTED" if row.adjusted_on else "PENDING"
    db.flush()


def cross_charges(db, client_id, status=""):
    sync_cross_charges(db, client_id)
    q = db.query(DBStoreCrossCharge, DBStoreTransfer).join(DBStoreTransfer, DBStoreTransfer.id == DBStoreCrossCharge.transfer_id).filter(DBStoreCrossCharge.client_id == client_id)
    if status:
        q = q.filter(DBStoreCrossCharge.status == status.strip().upper())
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    name = lambda pid: ((jobs[pid].name or jobs[pid].number) if pid in jobs else "")
    return [{"id": c.id, "transfer_id": t.id, "transfer_number": t.number, "date": t.received_at.date().isoformat() if t.received_at else (t.transfer_date.isoformat() if t.transfer_date else ""),
             "from_project_id": c.from_project_id, "from_project": name(c.from_project_id), "to_project_id": c.to_project_id, "to_project": name(c.to_project_id),
             "amount": s2(c.amount), "status": c.status, "adjusted_on": c.adjusted_on.isoformat() if c.adjusted_on else "", "adjusted_by": c.adjusted_by_name or "", "note": c.note or ""}
            for c, t in q.order_by(DBStoreCrossCharge.id.desc()).limit(500).all()]


def mark_adjusted(db, actor, charge_id, note=""):
    row = db.get(DBStoreCrossCharge, charge_id)
    if row is None or row.client_id != actor.client.id:
        raise HTTPException(404, "Charge not found")
    if row.status not in ("PENDING", "REVERSE"):
        raise HTTPException(409, "That charge is %s, so there is nothing to adjust." % row.status.lower())
    note = " ".join((note or "").split())[:200]
    if row.status == "REVERSE":
        row.status, row.adjusted_on, row.note = "VOID", None, note or "Adjustment put back"
    else:
        row.status, row.adjusted_on, row.adjusted_by_name, row.note = "ADJUSTED", date.today(), actor.name, note
    db.flush()
    return row


# --- price differences and the summary -------------------------------------------------------------------------------------

def price_variances(db, client_id):
    """Gate deliveries linked to their order: what the order's rate came to above (or below) the rate the stock was taken in at."""
    rows = db.query(DBStoreGrn).filter(DBStoreGrn.client_id == client_id, DBStoreGrn.gate_delivery == 1, DBStoreGrn.status == DocStatus.POSTED.value,
                                       DBStoreGrn.po_id.isnot(None), DBStoreGrn.price_variance != 0).order_by(DBStoreGrn.id.desc()).limit(500).all()
    pos = {p.id: p for p in db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.id.in_([g.po_id for g in rows] or [0])).all()}
    return [{"grn_id": g.id, "grn_number": g.number, "supplier_name": g.supplier_name or "", "po_number": pos[g.po_id].number if g.po_id in pos else "",
             "linked_at": g.linked_at.date().isoformat() if g.linked_at else "", "variance": s2(g.price_variance)} for g in rows]


def summary(db, client_id, store_ids=None, as_on=None):
    """The figures accounts take from the stores in one place."""
    val = store_reports.valuation(db, client_id, store_ids, as_on)
    pending = grni(db, client_id)
    sales = scrap_sales(db, client_id, store_ids)
    charges = [c for c in cross_charges(db, client_id) if c["status"] in ("PENDING", "REVERSE")]
    var = price_variances(db, client_id)
    return {"as_on": val["as_on"], "stock_value": s2(val["total_value"]), "by_category": [{"category": c["category"], "lines": c["lines"], "value": s2(c["value"])} for c in val["by_category"]],
            "not_billed": s2(sum((Decimal(r["difference"]) for r in pending if r["status"] == "NOT_BILLED"), ZERO)), "not_billed_orders": len([r for r in pending if r["status"] == "NOT_BILLED"]),
            "over_billed": s2(-sum((Decimal(r["difference"]) for r in pending if r["status"] == "OVER_BILLED"), ZERO)), "over_billed_orders": len([r for r in pending if r["status"] == "OVER_BILLED"]),
            "scrap_to_collect": s2(sum((Decimal(r["outstanding"]) for r in sales), ZERO)), "scrap_sales_open": len([r for r in sales if not r["settled"]]),
            "cross_charges_pending": s2(sum((Decimal(c["amount"]) for c in charges), ZERO)), "cross_charges_open": len(charges),
            "price_variance": s2(sum((Decimal(v["variance"]) for v in var), ZERO))}
