"""What accounts and the store owe the books today, found without anybody opening the right screen.

The dashboard's list and the morning digest carry these beside the projects' own; accounts are told each morning; and
two things are simply done: every store is checked against its reorder levels each night, and goods sent back to a
supplier come off that supplier's bill as a debit note the moment the return is posted, when there is one bill it can
only belong to.
"""
from datetime import date, timedelta
from decimal import Decimal

from app import models
from app.core.config import logger
from app.core.currency import inr, money
from app.core.scheduler import digest_key, scheduled_job

GRNI_DAYS = 15              # goods in the store this long with no bill from the supplier
FILE_DAYS = 2               # a payment file made and not marked paid


def _s(n):
    return "" if n == 1 else "s"


def accounts_items(db, client, today=None):
    """Attention items for accounts and the store's side of the books."""
    from app.models.journals import DBJournal, DBJournalLine
    from app.models.payouts import DBExpenseClaim, DBPaymentBatch, DBPostDatedCheque
    from app.models.store_extras import DBStoreCrossCharge
    from app.routers.money import payables_payload
    from app.services import store_accounts
    from app.services.journals import returns_without_note
    today = today or date.today()
    cid = client.id
    items = []

    def add(kind, severity, title, detail, view, value=0.0, count=0):
        items.append({"kind": kind, "severity": severity, "value": money(value), "count": count, "view": view, "title": title, "detail": detail})

    # --- MSME suppliers and their 45 days -------------------------------------------------------------------------------
    pay = payables_payload(db, client)
    late = [r for r in pay["bills"] if r.get("msme") and r["msme"]["days_left"] < 0]
    soon = [r for r in pay["bills"] if r.get("msme") and 0 <= r["msme"]["days_left"] <= 7]
    if late:
        worst = min(late, key=lambda r: r["msme"]["days_left"])
        add("msme_overdue", "wrong", "MSME bills past 45 days",
            "%s owed to micro and small suppliers is past the 45 days; %s (%s) is %d days over. Unpaid, it is disallowed as an expense and interest is owed."
            % (inr(sum(r["outstanding"] for r in late)), worst["number"], worst["party"], -worst["msme"]["days_left"]),
            "owe-view", sum(r["outstanding"] for r in late), len(late))
    if soon:
        first = min(soon, key=lambda r: r["msme"]["days_left"])
        add("msme_due_soon", "action", "MSME bills due this week",
            "%s to micro and small suppliers reaches its 45 days within a week; %s (%s) first, by %s."
            % (inr(sum(r["outstanding"] for r in soon)), first["number"], first["party"], first["msme"]["due"]),
            "owe-view", sum(r["outstanding"] for r in soon), len(soon))

    # --- post-dated cheques whose day has come -------------------------------------------------------------------------
    due = db.query(DBPostDatedCheque).filter(DBPostDatedCheque.client_id == cid, DBPostDatedCheque.status == "HELD",
                                             DBPostDatedCheque.cheque_date <= today.isoformat()).all()
    ours = [p for p in due if p.direction == "OUT"]
    theirs = [p for p in due if p.direction == "IN"]
    if theirs:
        add("pdc_to_deposit", "money", "Cheques to deposit",
            "%d post-dated cheque%s held, worth %s, can go to the bank now (%s first)." % (
                len(theirs), _s(len(theirs)), inr(sum(p.amount or 0 for p in theirs)), theirs[0].party_name),
            "bank-payments-view", sum(p.amount or 0 for p in theirs), len(theirs))
    if ours:
        add("pdc_presented", "action", "Our post-dated cheques are due",
            "%d cheque%s we gave, worth %s, may be presented from today. Keep the money in the account, and enter each once it clears." % (
                len(ours), _s(len(ours)), inr(sum(p.amount or 0 for p in ours))),
            "bank-payments-view", sum(p.amount or 0 for p in ours), len(ours))

    # --- payment files made and not marked paid ---------------------------------------------------------------------------
    cut = (today - timedelta(days=FILE_DAYS)).isoformat()
    files = [b for b in db.query(DBPaymentBatch).filter(DBPaymentBatch.client_id == cid, DBPaymentBatch.status == "DRAFT").all()
             if (b.pay_on or (b.made_at or "")[:10]) <= cut]
    if files:
        add("payment_files_open", "action", "Payment files not marked paid",
            "%s made and not yet marked paid. If the bank has paid, mark it so the payments reach the bank book; if not, close it."
            % ", ".join(b.number for b in files[:4]), "bank-payments-view", 0.0, len(files))

    # --- waiting on a decision -------------------------------------------------------------------------------------------
    pending = db.query(DBJournal).filter(DBJournal.client_id == cid, DBJournal.status == "PENDING").all()
    if pending:
        worth = sum(d or 0 for (d,) in db.query(DBJournalLine.debit).filter(DBJournalLine.journal_id.in_([j.id for j in pending])).all())
        add("journals_pending", "action", "Journals waiting for the Master",
            "%d journal voucher%s (%s) count for nothing until approved." % (len(pending), _s(len(pending)), inr(worth)),
            "adjustments-view", 0.0, len(pending))
    claims = db.query(DBExpenseClaim).filter(DBExpenseClaim.client_id == cid, DBExpenseClaim.status == "SUBMITTED").all()
    if claims:
        add("claims_waiting", "action", "Expense claims to check",
            "%d claim%s from staff, %s in all, waiting for accounts." % (len(claims), _s(len(claims)), inr(sum(c.amount or 0 for c in claims))),
            "claims-view", 0.0, len(claims))

    # --- what the store has handed the books --------------------------------------------------------------------------
    back = returns_without_note(db, cid)
    if back:
        add("returns_no_debit_note", "money", "Goods sent back, no debit note",
            "%s returned to suppliers with nothing taken off their bills yet (%s first). Raise the debit notes."
            % (inr(sum(r["total"] for r in back)), back[0]["number"]), "adjustments-view", sum(r["total"] for r in back), len(back))
    try:
        with db.begin_nested():
            store_accounts.sync_cross_charges(db, cid)
    except Exception:
        logger.exception("Could not bring the cross-charges up to date for %s", cid)
    cross = db.query(DBStoreCrossCharge).filter(DBStoreCrossCharge.client_id == cid, DBStoreCrossCharge.status.in_(("PENDING", "REVERSE"))).all()
    if cross:
        add("cross_charges", "action", "Material moved between sites to charge across",
            "%d transfer%s between projects, %s, not yet adjusted in the books." % (
                len(cross), _s(len(cross)), inr(sum(float(c.amount or 0) for c in cross))), "store-accounts-view", 0.0, len(cross))
    old = (today - timedelta(days=GRNI_DAYS)).isoformat()
    unbilled = [r for r in store_accounts.grni(db, cid) if r["status"] == "NOT_BILLED" and r["last_received"] and r["last_received"] <= old]
    if unbilled:
        worth = sum(Decimal(r["difference"]) for r in unbilled)
        add("grni_old", "action", "Received long ago, still not billed",
            "%s of goods on %d order%s came in over %d days ago with no bill entered (%s, %s first). Ask the supplier for the bill."
            % (inr(float(worth)), len(unbilled), _s(len(unbilled)), GRNI_DAYS, unbilled[0]["po_number"], unbilled[0]["supplier_name"]),
            "store-accounts-view", 0.0, len(unbilled))
    return items


# --- done without being asked ---------------------------------------------------------------------------------------------

def auto_debit_note(db, ret):
    """A posted purchase return comes off the supplier's bill by itself when it can only belong to one: the order has a
    single bill accepted, with at least the return's worth still to pay. Anything else is left for accounts to decide.
    Returns the note, or None."""
    from app.models.journals import DBSupplierDebitNote
    from app.models.store_inward import DBStoreGrn
    from app.services.journals import bill_debited, raise_debit_note
    from app.services.money import already_settled
    total = money(float(ret.debit_value or 0) + float(ret.tax_value or 0))
    grn = db.get(DBStoreGrn, ret.grn_id)
    if total <= 0 or grn is None or not grn.po_id:
        return None
    if db.query(DBSupplierDebitNote.id).filter(DBSupplierDebitNote.purchase_return_id == ret.id, DBSupplierDebitNote.status == "ISSUED").first():
        return None
    bills = db.query(models.DBBill).filter(models.DBBill.client_id == ret.client_id, models.DBBill.purchase_order_id == grn.po_id,
                                           models.DBBill.status.notin_(("Cancelled", "Rejected", "Draft"))).all()
    if len(bills) != 1:
        return None
    bill = bills[0]
    left = money((bill.total or bill.amount or 0) - bill_debited(db, bill) - already_settled(db, ret.client_id, "supplier_bill", bill, bill.total or 0))
    if total > left + 0.009:
        return None
    return raise_debit_note(db, ret.client_id, {
        "purchase_return_id": ret.id, "bill_id": bill.id, "note_date": ret.return_date.isoformat() if ret.return_date else "",
        "reason": ("Goods returned - %s%s" % (ret.number, (": " + ret.reason) if ret.reason else ""))[:300],
        "taxable": float(ret.debit_value or 0), "tax": float(ret.tax_value or 0)}, "Raised with the return")


def debit_note_on_return(db, ret):
    """Called as a return is posted. Never the reason the return fails."""
    from app.core.notifications import notify
    try:
        with db.begin_nested():
            note = auto_debit_note(db, ret)
        if note is None:
            return None
        notify(db, ret.client_id, "debit_note", "Debit note %s raised for %s" % (note.number, ret.number),
               "%s came off %s's bill for the goods sent back. Cancel it under Journals & Debit Notes if it should not have." % (
                   inr(note.total), note.supplier_name), view="adjustments-view", ref_type="supplier_debit_note", ref_id=note.id)
        return note
    except Exception:
        logger.exception("No automatic debit note for return %s", getattr(ret, "number", ""))
        return None


def scan_reorder_levels(db, client_id, store_ids=None):
    """Raise the alert for every item at or below its reorder level in a store with none open. Returns how many."""
    from app.models.store_core import DBStore, DBStoreItemSettings, DBStoreStockBalance
    from app.services import store_levels
    from app.services.stock_ledger import raise_reorder_alert
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.client_id == client_id, DBStore.is_active.is_(True)).all()
              if store_ids is None or s.id in store_ids}
    if not stores:
        return 0
    over = store_levels.overrides(db, list(stores))
    held = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id.in_(list(stores))).all()
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_([b.item_id for b in held] or [0])).all()}
    raised = 0
    for bal in held:
        level = store_levels.effective(sets.get(bal.item_id), over.get((bal.store_id, bal.item_id)))[0]
        if level > 0 and Decimal(str(bal.qty)) <= level:
            item = db.get(models.DBItem, bal.item_id)
            if item is not None and raise_reorder_alert(db, client_id, stores[bal.store_id], item, Decimal(str(bal.qty)), level):
                raised += 1
    return raised


@scheduled_job("accounts_store_watch", digest_key)
def job_accounts_store_watch(db, now):
    """Each morning: check every store against its reorder levels, and tell accounts what is waiting on them."""
    from app.core.notifications import tell_approvers
    from app.services.site_cash import CHECKERS
    if now.hour < 7:
        return "too early"
    alerts = told = 0
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        try:
            alerts += scan_reorder_levels(db, client.id)
            db.commit()
            items = accounts_items(db, client, now.date())
            if items:
                tell_approvers(db, client.id, "Accounts: %d thing%s to see to today" % (len(items), _s(len(items))),
                               "\n".join("- %s: %s" % (i["title"], i["detail"]) for i in items[:6]),
                               rights=CHECKERS, link="/next/money/dashboard", owner=False)
                told += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("Accounts and store watch for %s failed: %s", client.id, exc)
    return "%d reorder alert(s), %d office(s) told" % (alerts, told)
