"""The money endpoints."""
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.db import get_db, get_read_db

from app.constants.money import COST_CATEGORIES, EXPENSE_HEADS, INCOME_HEADS, MONEY_MODES, PARTY_TYPES
from app.constants.projects import JOB_FINISHED
from app.core.audit import log_audit
from app.core.auth import (
    current_member, get_client_user, owned_or_404, require_items_access, session_employee, session_person, wo_actor,
)
from app.core.cache import cached_read
from app.core.currency import amount_in_words, inr, money
from app.core.dates import ageing_bucket, days_after
from app.core.notifications import notify
from app.core.sheets import sheet_response
from app.core.tenant_settings import put_setting, tenant_setting
from app.documents.forms import _pre, form_pdf_response, money_voucher_spec, statement_form_spec
from app.documents.letterhead import our_party
from app.schemas.money import (BankAccountEditIn, BankAccountIn, CashBoxIn, MoneyLockIn, ClearIn, LineBookIn, LineMatchIn, MoneyIn, PaymentDecisionIn,
                               PaymentRulesIn, RequestPayIn, SiteCashExpenseIn, TallySettingsIn, TransferIn)
from app.services import bank_reco, site_cash, tally
from app.services import payment_requests as preq
from app.services.credit_notes import credit_totals_by_bill, credits_by_job
from app.services.crm import (
    _ledger_rows,
    norm_name,
    settled_amounts,
    supplier_dict,
)
from app.services.money import (
    MONEY_LOCK_KEY,
    _doc_for,
    _doc_for_any,
    _empty_buckets,
    _settle_doc,
    account_balance,
    already_settled,
    account_dict,
    balance_sheet,
    base_currency,
    entry_date,
    invoices_by_currency,
    job_money,
    money_entry_dict,
    money_locked_upto,
    next_money_number,
    opening_day,
    owed_to_us_rows,
    profit_and_loss,
    refuse_duplicate_cheque,
    refuse_if_locked,
)
from app.services.projects import job_or_404, preload_pnl
from app.services.subcontract_billing import released_by_job


router = APIRouter()


@router.get("/api/reports/profit-loss")
def profit_loss_report(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    """Accrual profit and loss: billed and certified work in, bills and expense vouchers out (see
    services.money.profit_and_loss)."""
    client = require_items_access(request, db, "reports.view")
    f, t = _tally_period(date_from, date_to)
    return profit_and_loss(db, client, f, t)


@router.get("/api/reports/balance-sheet")
def balance_sheet_report(request: Request, db: Session = Depends(get_read_db)):
    """Assets, liabilities and equity today. Equity is assets less liabilities, so it balances by construction."""
    client = require_items_access(request, db, "reports.view")
    return balance_sheet(db, client)


@router.get("/api/reports/cash-summary")
def cash_summary_report(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "reports.view")
    base = base_currency(client)
    invoices = db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).all()
    bills = db.query(models.DBBill).filter(models.DBBill.client_id == client.id).all()
    groups = invoices_by_currency(invoices, base)

    def figures(inv_list, bill_list):
        monthly_in = {}
        monthly_out = {}
        for inv in inv_list:
            m = inv.issue_date[:7] if inv.issue_date and len(inv.issue_date) >= 7 else "Unknown"
            monthly_in[m] = monthly_in.get(m, 0) + (inv.paid or 0)
        for b in bill_list:
            m = b.issue_date[:7] if b.issue_date and len(b.issue_date) >= 7 else "Unknown"
            monthly_out[m] = monthly_out.get(m, 0) + (b.amount_paid or 0)
        all_months = sorted(set(list(monthly_in.keys()) + list(monthly_out.keys())))
        return {
            "months": all_months,
            "money_in": [money(monthly_in.get(m, 0)) for m in all_months],
            "money_out": [money(monthly_out.get(m, 0)) for m in all_months],
            "net_cash": [money(monthly_in.get(m, 0) - monthly_out.get(m, 0)) for m in all_months],
        }

    report = figures(groups.get(base, []), bills)
    report["currency"] = base
    report["other_currencies"] = [
        dict(figures(groups[code], []), currency=code)
        for code in sorted(groups) if code != base
    ]
    return report


# The aged report's own bucket names, kept for whatever reads them; the buckets themselves are the Owed page's.
_AGED_KEYS = {"Not due": "current", "0-30": "1_30", "31-60": "31_60", "61-90": "61_90", "90+": "over_90"}


@router.get("/api/reports/aged-receivables")
def aged_receivables(request: Request, db: Session = Depends(get_read_db)):
    """Outstanding balances bucketed by how late they are - invoices, certified client RA bills and retention
    releases, aged exactly as the Owed page ages them (a missing due date sits with the oldest)."""
    client = require_items_access(request, db, "reports.view")
    base = base_currency(client)
    rows = owed_to_us_rows(db, client, date.today())

    def figures(group):
        buckets = {k: 0.0 for k in _AGED_KEYS.values()}
        out = []
        for r in group:
            bucket = _AGED_KEYS[r["bucket"]]
            buckets[bucket] = money(buckets[bucket] + r["outstanding"])
            out.append({"number": r["number"], "kind": r["kind"], "doc_type": r.get("doc_type", "invoice"),
                        "contact": r["customer"], "project": r["project"], "due_date": r["due_date"],
                        "outstanding": r["outstanding"], "days_overdue": r["days_overdue"], "bucket": bucket,
                        # Each row carries its own currency so a mixed table prints the right symbol on every line.
                        "currency": r["currency"]})
        out.sort(key=lambda r: r["days_overdue"], reverse=True)
        return {"buckets": buckets, "total_outstanding": money(sum(buckets.values())), "invoices": out}

    groups = {}
    for r in rows:
        groups.setdefault(r["currency"], []).append(r)
    report = figures(groups.get(base, []))
    report["currency"] = base
    report["other_currencies"] = [dict(figures(groups[code]), currency=code) for code in sorted(groups) if code != base]
    return report


@router.get("/api/costs/by-project")
def costs_by_project(request: Request, db: Session = Depends(get_db)):
    """Every project on one screen, with the money on each."""
    client = require_items_access(request, db, "reports.view")
    # Nineteen queries to add up; kept until anything is saved.
    return cached_read(("costs-by-project", client.id), lambda: costs_by_project_payload(db, client), ttl=60)


def costs_by_project_payload(db, client):
    jobs = db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id).order_by(models.DBJob.id.desc()).all()
    pre = preload_pnl(db, client.id)          # once for every project, not per row
    rows = [job_money(db, client.id, j, pre=pre) for j in jobs]
    return {
        "projects": rows,
        "summary": {
            "projects": len(rows),
            "sold": money(sum(r["contract_value"] for r in rows)),
            "incurred": money(sum(r["incurred"] for r in rows)),
            "commitment": money(sum(r["commitment"] for r in rows)),
            "cost": money(sum(r["cost"] for r in rows)),
            "forecast_cost": money(sum(r["forecast_cost"] for r in rows)),
            "margin": money(sum(r["margin"] for r in rows)),
            "labour": money(sum(r["labour"] for r in rows)),
            "invoiced": money(sum(r["invoiced"] for r in rows)),
            "received": money(sum(r["received"] for r in rows)),
            "outstanding": money(sum(r["outstanding"] for r in rows)),
            "retention_held": money(sum(r["retention_held"] for r in rows)),
            "over_billed": money(sum(r["over_billed"] for r in rows)),
            "billed": money(sum(r["billed"] for r in rows)),
            "unpaid": money(sum(r["unpaid"] for r in rows)),
            "awaiting_approval": sum(r["bills_awaiting_approval"] for r in rows),
            "over_budget": len([r for r in rows if r["over_budget"] > 0]),
            "categories": [
                {"key": key, "label": label,
                 "amount": money(sum(
                     next((c["amount"] for c in r["categories"] if c["key"] == key), 0.0)
                     for r in rows))}
                for key, label in COST_CATEGORIES
            ],
        },
    }


@router.get("/api/costs/by-project/{job_id}")
def costs_for_project(job_id: int, request: Request, db: Session = Depends(get_db)):
    """One project, with the documents behind each figure.

    The totals are only worth anything if you can get from them to the papers
    they came from, so every one of them lists what it is made of.
    """
    client = require_items_access(request, db, "reports.view")
    job = job_or_404(db, client.id, job_id)
    row = job_money(db, client.id, job)

    row["work_order_list"] = [
        {"id": w.id, "number": w.number, "status": w.status or "",
         "value": money(w.total_value), "approval": w.approval_status or "none"}
        for w in db.query(models.DBWorkOrder).filter(
            models.DBWorkOrder.client_id == client.id,
            models.DBWorkOrder.job_id == job.id).all()]
    row["purchase_order_list"] = [
        {"id": p.id, "number": p.number or "", "supplier": p.supplier_name or "",
         "total": money(p.total), "status": p.status or ""}
        for p in db.query(models.DBPurchaseOrder).filter(
            models.DBPurchaseOrder.client_id == client.id,
            models.DBPurchaseOrder.job_id == job.id).all()]
    row["bill_list"] = [
        {"id": b.id, "number": b.number or "", "supplier": b.vendor_name or "",
         "total": money(b.total or b.amount), "status": b.status or "",
         "approval": b.approval_status or "none"}
        for b in db.query(models.DBBill).filter(
            models.DBBill.client_id == client.id,
            models.DBBill.job_id == job.id).all()]
    row["subcontract_list"] = [
        {"id": s.id, "number": s.wo_number or "", "status": s.status or "",
         "net": money(s.net_order_value)}
        for s in db.query(models.DBSubcontractOrder).filter(
            models.DBSubcontractOrder.client_id == client.id,
            models.DBSubcontractOrder.job_id == job.id).all()]
    return row


@router.get("/api/costs/by-project.xlsx")
def costs_by_project_xlsx(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "reports.view")
    jobs = db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id).order_by(models.DBJob.id.desc()).all()
    pre = preload_pnl(db, client.id)
    rows = [job_money(db, client.id, j, pre=pre) for j in jobs]
    return sheet_response(
        ["Project", "Name", "Customer", "Sold", "Budgeted cost", "Committed",
         "Subcontracted", "Total cost", "Margin", "Margin %", "Billed", "Unpaid"],
        [[r["number"], r["name"], r["customer_name"], r["sold"], r["budgeted_cost"],
          r["committed"], r["subcontracted"], r["cost"], r["margin"],
          r["margin_percent"], r["billed"], r["unpaid"]] for r in rows],
        "cost_by_project.xlsx",
        preamble=[["Cost by project", "", "", "", "", "", "", "", "", "", "",
                   client.company_name or ""],
                  ["As at " + datetime.now().strftime("%d/%m/%Y %H:%M")], []])


def _on_account_by_party(db, client_id, party_types, incoming):
    """{normalised party name: [name, money on account]} - receipts (incoming) or payments not against any bill, less
    what moved the other way on account. For clients, the advance their RA bills have already recovered is used up and
    comes off, so an advance is not counted both as on account and as a deduction from the bills."""
    out = {}
    for e in db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.doc_type == "on_account",
            models.DBMoneyEntry.party_type.in_(party_types), models.DBMoneyEntry.voided.isnot(True)).all():
        key = norm_name(e.party_name)
        if not key:
            continue
        row = out.setdefault(key, [e.party_name or "", 0.0])
        sign = 1 if (e.direction == "IN") == incoming else -1
        row[1] = money(row[1] + sign * (e.amount or 0))
    if "client" in party_types:
        jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
        for b in db.query(models.DBRABill).filter(
                models.DBRABill.client_id == client_id, models.DBRABill.status != "CANCELLED",
                models.DBRABill.advance_recovery > 0).all():
            job = jobs.get(b.job_id)
            key = norm_name(job.customer_name if job else "")
            if key in out:
                out[key][1] = money(out[key][1] - (b.advance_recovery or 0))
    return out


def _party_positions(rows, credits, on_account, name_of):
    """Per party: what is owed on open documents, what credit notes left in their favour, what sits on account, and
    the net of the three. A party with only a credit balance or only money on account is listed too."""
    out = {}

    def slot(name):
        key = norm_name(name)
        return out.setdefault(key, {"party": name or "", "owed": 0.0, "credit": 0.0, "on_account": 0.0})
    for r in rows:
        p = slot(name_of(r))
        p["owed"] = money(p["owed"] + r["outstanding"])
    for c in credits:
        p = slot(c["party"])
        p["credit"] = money(p["credit"] + c["amount"])
    for key, (name, amount) in on_account.items():
        if amount:
            p = out.setdefault(key, {"party": name, "owed": 0.0, "credit": 0.0, "on_account": 0.0})
            p["on_account"] = money(p["on_account"] + amount)
    for p in out.values():
        # What they owe less what is in their favour. Money on account the bills already used is not counted twice
        # (see _on_account_by_party); a negative on-account figure - more advance recovered than the ledger shows
        # received - is shown as it is, and not netted.
        p["net"] = money(p["owed"] - p["credit"] - max(p["on_account"], 0.0))
    return sorted((p for p in out.values() if p["credit"] or p["on_account"]), key=lambda p: p["party"].lower())


@router.get("/api/money/receivables")
def receivables(request: Request, db: Session = Depends(get_read_db)):
    """What customers owe, and how long they have owed it."""
    return receivables_payload(db, require_items_access(request, db, "bills.view_all"))


def receivables_payload(db, client):
    """The receivables page's figures for one company - also what the morning digest reads, so the two agree."""
    today = date.today()
    rows, buckets = owed_to_us_rows(db, client, today), _empty_buckets()
    # A credit note after the money came in leaves the client in credit: we owe it back, or it comes off their next
    # bill. Shown, not dropped.
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
    settled = settled_amounts(db, client.id)
    ra_credits = credit_totals_by_bill(db, client.id, "client")
    credits = []
    for r in db.query(models.DBRABill).filter(
            models.DBRABill.client_id == client.id,
            models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all():
        over = money((r.net_payable or 0) - ra_credits.get(r.id, {}).get("net", 0.0)
                     - settled.get(("ra_bill", r.id), 0.0))
        if over < 0:
            job = jobs.get(r.job_id)
            credits.append({"id": r.id, "number": r.number or "", "doc_type": "ra_bill",
                            "party": job.customer_name if job else "", "project": job.name if job else "",
                            "amount": money(-over)})
    for r in rows:
        buckets[r["bucket"]] = money(buckets[r["bucket"]] + r["outstanding"])
    rows.sort(key=lambda r: -(r["days_overdue"] or 0))
    overdue = money(sum(r["outstanding"] for r in rows if r["bucket"] != "Not due"))
    parties = _party_positions(rows, credits, _on_account_by_party(db, client.id, ("client",), True),
                               lambda r: r["customer"])
    owed = money(sum(r["outstanding"] for r in rows))
    in_credit = money(sum(c["amount"] for c in credits))
    on_account = money(sum(max(p["on_account"], 0.0) for p in parties))
    return {
        "invoices": rows, "buckets": buckets, "credits": credits, "parties": parties,
        "summary": {
            "owed": owed,
            "overdue": overdue,
            "invoices": len(rows),
            "worst_days": max([r["days_overdue"] for r in rows] or [0]),
            "over_90": buckets["90+"],
            # In the clients' favour: credit notes past what was owed, and money they paid on account.
            "credit_balances": in_credit, "on_account": on_account,
            "net_owed": money(owed - in_credit - on_account),
        },
    }


@router.get("/api/money/payables")
def payables(request: Request, db: Session = Depends(get_read_db)):
    """What the business owes: supplier bills, and bills it has certified.

    A certified RA bill is a promise already made - the work was measured and
    somebody signed for it - so it belongs here beside the supplier invoices
    rather than out of sight on the subcontract screen.
    """
    return payables_payload(db, require_items_access(request, db, "bills.view_all"))


def payables_payload(db, client):
    """The payables page's figures for one company - also what the morning digest reads, so the two agree."""
    today = date.today()
    jobs = {j.id: j for j in db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id).all()}

    rows, buckets = [], _empty_buckets()
    for b in db.query(models.DBBill).filter(
            models.DBBill.client_id == client.id).all():
        # A draft is a bill nobody here has accepted yet - one a supplier sent
        # in through the portal, say. The ledger and the payment box both leave
        # it out until it is; counting it here said we owed it already.
        if (b.status or "") in ("Draft", "Paid", "Cancelled", "Rejected"):
            continue
        if (b.approval_status or "none") == "rejected":
            continue
        outstanding = money((b.total or 0) - (b.amount_paid or 0))
        if outstanding <= 0:
            continue
        bucket, days = ageing_bucket(b.due_date, today)
        buckets[bucket] = money(buckets[bucket] + outstanding)
        job = jobs.get(b.job_id)
        rows.append({
            "kind": "Supplier bill", "doc_type": "supplier_bill", "id": b.id, "number": b.number or "",
            "party": b.vendor_name or "", "project": job.name if job else "",
            "due_date": b.due_date or "", "outstanding": outstanding,
            "bucket": bucket, "days_overdue": days if (days or 0) > 0 else 0,
            "status": b.status or "",
            "approved": (b.approval_status or "none") == "approved",
        })

    # A subcontractor's certified bill is money we owe the contractor. Aged from
    # the day it was certified, because that is the day the promise was made.
    # (Client RA bills used to be listed here too, which was wrong - those are
    # money coming in and belong on the other page. Counting them on both
    # sides made the business look poorer than it was by exactly that sum.)
    contractors = {c.id: c for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id).all()}
    settled = settled_amounts(db, client.id)
    terms_of = dict(db.query(models.DBSubcontractOrder.id, models.DBSubcontractOrder.payment_days).filter(
        models.DBSubcontractOrder.client_id == client.id).all())
    sub_credits = credit_totals_by_bill(db, client.id, "contractor")
    credits = []
    for r in db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client.id,
            models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all():
        outstanding = money((r.net_payable or 0) - sub_credits.get(r.id, {}).get("net", 0.0)
                            - settled.get(("sub_bill", r.id), 0.0))
        if outstanding < 0:
            # Their credit note came after we paid: the contractor owes it back, or it comes off their next bill.
            con = contractors.get(r.contractor_id)
            job = jobs.get(r.job_id)
            credits.append({"id": r.id, "number": r.number or "", "doc_type": "sub_bill",
                            "party": con.company_name if con else "", "project": job.name if job else "",
                            "amount": money(-outstanding)})
            continue
        if outstanding == 0 or r.status != "CERTIFIED":
            continue
        # The order says how many days after certification the contractor is paid.
        terms = terms_of.get(r.order_id) or 0
        due = days_after(r.certified_at, terms)
        bucket, days = ageing_bucket(due or r.certified_at, today)
        buckets[bucket] = money(buckets[bucket] + outstanding)
        job = jobs.get(r.job_id)
        con = contractors.get(r.contractor_id)
        rows.append({
            "kind": "Subcontractor bill", "doc_type": "sub_bill", "id": r.id, "number": r.number or "",
            "party": con.company_name if con else "", "project": job.name if job else "",
            "due_date": due or (r.certified_at or "")[:10], "outstanding": outstanding,
            "bucket": bucket, "days_overdue": days if (days or 0) > 0 else 0,
            "status": r.status or "", "approved": True,
        })

    # A contractor's retention, once released, is owed on their order's terms.
    for rel in db.query(models.DBRetentionRelease).filter(
            models.DBRetentionRelease.client_id == client.id,
            models.DBRetentionRelease.side == "contractor",
            models.DBRetentionRelease.status == "CERTIFIED").all():
        outstanding = money((rel.net_amount or 0) - settled.get(("retention_release", rel.id), 0.0))
        if outstanding <= 0:
            continue
        terms = terms_of.get(rel.sub_order_id) or 0
        due = days_after(rel.release_on, terms)
        bucket, days = ageing_bucket(due or rel.release_on, today)
        buckets[bucket] = money(buckets[bucket] + outstanding)
        job = jobs.get(rel.job_id)
        con = contractors.get(rel.contractor_id)
        rows.append({
            "kind": "Retention release", "doc_type": "retention_release", "id": rel.id,
            "number": rel.number or "", "party": con.company_name if con else "",
            "project": job.name if job else "", "due_date": due or rel.release_on or "",
            "outstanding": outstanding, "bucket": bucket,
            "days_overdue": days if (days or 0) > 0 else 0,
            "status": rel.status or "", "approved": True,
        })

    rows.sort(key=lambda r: -(r["days_overdue"] or 0))
    parties = _party_positions(rows, credits, _on_account_by_party(db, client.id, ("contractor", "supplier"), False),
                               lambda r: r["party"])
    owed = money(sum(r["outstanding"] for r in rows))
    in_credit = money(sum(c["amount"] for c in credits))
    on_account = money(sum(max(p["on_account"], 0.0) for p in parties))
    return {
        "bills": rows, "buckets": buckets, "credits": credits, "parties": parties,
        "summary": {
            # In our favour: their credit notes past what we owed, and advances we paid them on account.
            "credit_balances": in_credit, "on_account": on_account,
            "net_owed": money(owed - in_credit - on_account),
            "owed": owed,
            "overdue": money(sum(r["outstanding"] for r in rows
                                 if r["bucket"] != "Not due")),
            "bills": len(rows),
            # Sitting unapproved is different from sitting unpaid, and only
            # one of them is somebody's decision to make.
            "awaiting_approval": money(sum(r["outstanding"] for r in rows
                                           if not r["approved"])),
            "over_90": buckets["90+"],
        },
    }


@router.get("/api/money/retention")
def retention_register(request: Request, db: Session = Depends(get_read_db)):
    """Money already earned that is being held back.

    Held on every certified bill, invoiced on none of them. Half is normally
    released at practical completion and half at the end of the defects
    period, so a job that finished a year ago may still be owed the second
    half - and nothing in this app used to say so.
    """
    client = require_items_access(request, db, "bills.view_all")
    jobs = {j.id: j for j in db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id).all()}

    by_job = {}
    for b in db.query(models.DBRABill).filter(
            models.DBRABill.client_id == client.id,
            models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all():
        held = money(b.retention_amount)
        if held <= 0:
            continue
        job = jobs.get(b.job_id)
        row = by_job.setdefault(b.job_id or 0, {
            "job_id": b.job_id, "number": job.number if job else "",
            "project": job.name if job else "Unattached",
            "customer": job.customer_name if job else "",
            "job_status": job.status if job else "",
            "held": 0.0, "bills": [], "claimed_value": 0.0,
        })
        row["held"] = money(row["held"] + held)
        row["claimed_value"] = money(row["claimed_value"] + money(b.this_bill))
        row["bills"].append({
            "id": b.id, "number": b.number or "", "status": b.status or "",
            "this_bill": money(b.this_bill), "retention": held,
            "percent": b.retention_percent or 0,
            "certified_at": (b.certified_at or "")[:10],
        })

    # What has been released is no longer held; held is what is left. Retention on work a credit note took back
    # is not held either.
    released = released_by_job(db, client.id)
    credited = credits_by_job(db, client.id, "client")
    for r in by_job.values():
        cn = credited.get(r["job_id"], {})
        r["held"] = money(max(0.0, r["held"] - cn.get("retention", 0.0)))
        r["claimed_value"] = money(max(0.0, r["claimed_value"] - cn.get("taxable", 0.0)))
        r["retained"] = r["held"]
        r["released"] = money(released.get(r["job_id"], 0.0))
        r["held"] = money(max(0.0, r["retained"] - r["released"]))
    rows = sorted(by_job.values(), key=lambda r: -r["held"])
    for r in rows:
        # A finished job's retention is money that should be being chased;
        # a running job's is money that is simply not due yet.
        r["releasable"] = (r["job_status"] or "").lower() == JOB_FINISHED and r["held"] > 0
        r["effective_percent"] = (round(r["retained"] / r["claimed_value"] * 100, 2)
                                  if r["claimed_value"] else 0.0)
    return {
        "projects": rows,
        "summary": {
            "held": money(sum(r["held"] for r in rows)),
            "released": money(sum(r["released"] for r in rows)),
            "projects": len(rows),
            "on_finished_jobs": money(sum(r["held"] for r in rows
                                          if r["releasable"])),
            "bills": sum(len(r["bills"]) for r in rows),
        },
    }


@router.get("/api/money/receivables.xlsx")
def receivables_export(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    data = receivables(request, db)
    b = data["buckets"]
    gstin = {c.id: (c.gstin or "") for c in db.query(models.DBContact).filter(
        models.DBContact.client_id == client.id).all()}
    by_name = {norm_name(c.name): (c.gstin or "") for c in db.query(models.DBContact).filter(
        models.DBContact.client_id == client.id).all() if (c.gstin or "").strip()}
    rows = [(r["number"], r["kind"], r["customer"],
             gstin.get(r.get("contact_id")) or by_name.get(norm_name(r["customer"]), ""),
             r["project"], r["issue_date"],
             r["due_date"], r["total"], r["paid"], r["outstanding"],
             r["bucket"], r["days_overdue"]) for r in data["invoices"]]
    rows += [(c["number"], "Credit balance", c["party"], by_name.get(norm_name(c["party"]), ""), c["project"],
              "", "", "", "", -c["amount"], "", "") for c in data["credits"]]
    rows += [("", "On account", p["party"], by_name.get(norm_name(p["party"]), ""), "", "", "", "", "",
              -p["on_account"], "", "") for p in data["parties"] if p["on_account"]]
    return sheet_response(
        ("Document", "Kind", "Customer", "GSTIN", "Project", "Issued", "Due", "Total", "Paid",
         "Outstanding", "Age", "Days overdue"),
        rows, "receivables.xlsx",
        preamble=[("WHAT WE ARE OWED", client.company_name or ""),
                  ("As at", date.today().strftime("%Y-%m-%d")),
                  (),
                  ("Not due", b["Not due"], "0-30", b["0-30"], "31-60", b["31-60"]),
                  ("61-90", b["61-90"], "90+", b["90+"]),
                  ()],
        closing=[(), ("Total owed", "", "", "", "", "", "", "", "", data["summary"]["owed"]),
                 ("In their favour (credit notes, on account)", "", "", "", "", "", "", "", "",
                  -money(data["summary"]["credit_balances"] + data["summary"]["on_account"])),
                 ("Net owed", "", "", "", "", "", "", "", "", data["summary"]["net_owed"])])


@router.get("/api/money/retention.xlsx")
def retention_export(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    data = retention_register(request, db)
    rows = [(r["number"], r["project"], r["customer"], r["job_status"],
             r["claimed_value"], r["retained"], r["released"], r["held"],
             r["effective_percent"], len(r["bills"]), "yes" if r["releasable"] else "")
            for r in data["projects"]]
    return sheet_response(
        ("Project", "Name", "Customer", "Status", "Claimed", "Retained", "Released",
         "Still held", "Effective %", "Bills", "Job finished"),
        rows, "retention_register.xlsx",
        preamble=[("RETENTION HELD", client.company_name or ""),
                  ("As at", date.today().strftime("%Y-%m-%d")),
                  ("Money already earned and not yet released",),
                  ()],
        closing=[(), ("Released", "", "", "", "", "", data["summary"]["released"]),
                 ("Still held", "", "", "", "", "", "", data["summary"]["held"]),
                 ("On finished jobs", "", "", "", "", "", "",
                  data["summary"]["on_finished_jobs"])])


@router.get("/api/bank-accounts")
def list_bank_accounts(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    rows = db.query(models.DBBankAccount).filter(
        models.DBBankAccount.client_id == client.id).order_by(models.DBBankAccount.id).all()
    out = []
    for a in rows:
        d = account_dict(a)
        d["balance"] = account_balance(db, client.id, a)
        out.append(d)
    return {"accounts": out}


def _opening_date(raw):
    return entry_date(raw, "The opening date") if (raw or "").strip() else date.today().isoformat()


@router.post("/api/bank-accounts")
def create_bank_account(body: BankAccountIn, request: Request, db: Session = Depends(get_db)):
    # The same right as every other money screen: a member of staff who pays is let in, not signed out by a 401.
    client, _, _ = wo_actor(request, db, "bills.pay")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Name the account - \"SBI current\", \"Site cash\".")
    kind = body.kind if body.kind in ("Bank", "Cash") else "Bank"
    a = models.DBBankAccount(
        client_id=client.id, name=name, kind=kind, bank_name=(body.bank_name or "").strip(),
        account_no=(body.account_no or "").strip(), ifsc=(body.ifsc or "").strip().upper(),
        opening_balance=money(body.opening_balance or 0),
        opening_date=_opening_date(body.opening_date))
    db.add(a)
    db.flush()
    log_audit(db, client.id, "bank_account_added", "bank_account", a.id, a.name,
              "%s; opening %s on %s" % (kind, inr(a.opening_balance), a.opening_date), request)
    db.commit()
    db.refresh(a)
    return account_dict(a)


@router.put("/api/bank-accounts/{account_id}")
def edit_bank_account(account_id: int, body: BankAccountEditIn, request: Request, db: Session = Depends(get_db)):
    """Correct an account's name, bank details, opening balance and date, or close it. The opening balance and date
    are the start of its book, so they cannot be moved inside a closed period."""
    client, _, _ = wo_actor(request, db, "bills.pay")
    a = bank_reco.bank_account_or_404(db, client.id, account_id)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(400, "The account needs a name.")
        a.name = body.name.strip()
    for field in ("bank_name", "account_no"):
        if getattr(body, field) is not None:
            setattr(a, field, getattr(body, field).strip())
    if body.ifsc is not None:
        a.ifsc = body.ifsc.strip().upper()
    if body.is_active is not None:
        a.is_active = bool(body.is_active)
    before = (money(a.opening_balance), a.opening_date or "")
    new_balance = money(body.opening_balance) if body.opening_balance is not None else before[0]
    new_date = _opening_date(body.opening_date) if body.opening_date is not None else before[1]
    if (new_balance, new_date) != before:
        for day in {before[1], new_date}:
            refuse_if_locked(db, client.id, day, "changed")
        a.opening_balance, a.opening_date = new_balance, new_date
        log_audit(db, client.id, "bank_account_opening_changed", "bank_account", a.id, a.name or "",
                  "opening %s on %s -> %s on %s" % (inr(before[0]), before[1] or "-", inr(new_balance), new_date or "-"),
                  request)
    else:
        log_audit(db, client.id, "bank_account_edited", "bank_account", a.id, a.name or "", "details", request)
    db.commit()
    d = account_dict(a)
    d["balance"] = account_balance(db, client.id, a)
    return d


@router.get("/api/money/lock")
def money_lock(request: Request, db: Session = Depends(get_read_db)):
    """The day the money books are closed up to."""
    client = require_items_access(request, db, "bills.view_all")
    return {"locked_upto": money_locked_upto(db, client.id), "can_edit": _is_master(request, db)}


@router.put("/api/money/lock")
def set_money_lock(body: MoneyLockIn, request: Request, db: Session = Depends(get_db)):
    """Close the money books up to a day, or reopen them. The Master alone."""
    client, _ = session_person(request, db)
    if not _is_master(request, db):
        raise HTTPException(403, "Only the Master closes or reopens the money books.")
    upto = (body.locked_upto or "").strip()[:10]
    if upto:
        upto = entry_date(upto, "The lock date")
        if upto >= date.today().isoformat():
            raise HTTPException(400, "The books can be closed up to yesterday at the latest.")
    before = money_locked_upto(db, client.id)
    put_setting(db, client.id, MONEY_LOCK_KEY, upto)
    log_audit(db, client.id, "money_lock_changed", "settings", None, "money lock", "%s -> %s" % (before or "open", upto or "open"),
              request)
    db.commit()
    return {"locked_upto": upto, "can_edit": True,
            "message": ("Money books closed up to %s." % upto) if upto else "Money books reopened."}


@router.post("/api/money/entries")
def record_money(body: MoneyIn, request: Request, db: Session = Depends(get_db)):
    """A receipt or a payment, against a bill or on account.

    Against a bill it may be any part of what is still owed on it, never more;
    the bill moves to paid the moment the last rupee lands. On account it is
    an advance with nobody's bill to settle yet - it still sits in the party's
    ledger and the bank book, which is the point.
    """
    client, actor_id, actor_name = wo_actor(request, db, "bills.pay")
    if body.request_id:
        # Paying an approved request: the payee, project and head are the approved ones and cannot be changed here.
        preq.lock_to_request(db, client.id, body)
    amount = money(body.amount or 0)
    if amount <= 0:
        raise HTTPException(400, "How much?")
    mode = body.mode if body.mode in MONEY_MODES else "Bank transfer"
    on = entry_date(body.paid_on, "The payment date")
    refuse_if_locked(db, client.id, on)
    account = None
    if body.account_id:
        account = db.query(models.DBBankAccount).filter(
            models.DBBankAccount.id == body.account_id,
            models.DBBankAccount.client_id == client.id).first()
        if not account:
            raise HTTPException(404, "That bank account is not on file.")
        if account.kind == "Cash" and mode not in ("Cash", "Adjustment"):
            mode = "Cash"
    if mode == "Cheque" and not (body.reference or "").strip():
        raise HTTPException(400, "A cheque payment needs the cheque number.")

    doc_type = (body.doc_type or "on_account").strip()
    doc = None
    head = ""
    if doc_type in ("expense", "income"):
        # An expense voucher (diesel, rent, site expenses) or a sundry receipt (scrap sold, interest): no bill behind
        # it, booked under a head, charged to the project it was for. Nobody's ledger carries it.
        direction = "OUT" if doc_type == "expense" else "IN"
        heads = EXPENSE_HEADS if doc_type == "expense" else INCOME_HEADS
        head = next((h for h in heads if h.lower() == (body.head or "").strip().lower()), "")
        if not head:
            raise HTTPException(400, "Book it under one of: %s." % ", ".join(heads))
        party_name = (body.party_name or "").strip()
        if not party_name:
            raise HTTPException(400, "Paid to whom?" if doc_type == "expense" else "Received from whom?")
        party_type, party_id, doc_number = "other", None, ""
        job_id = owned_or_404(db, models.DBJob, client.id, body.job_id, "Project")
    elif doc_type != "on_account":
        if not body.doc_id:
            raise HTTPException(400, "Which bill is this against?")
        doc, worth, direction, party_type, party_name, party_id, job_id = _doc_for(
            db, client.id, doc_type, body.doc_id)
        owed = money(worth - already_settled(db, client.id, doc_type, doc, worth))
        if owed <= 0:
            raise HTTPException(409, "%s is already fully settled." % doc.number)
        if direction == "OUT" and party_type == "contractor":
            # Nobody is paid whose labour licence, PF, ESI or insurance has lapsed - the Master alone may, saying why.
            from app.services.subcontract_rules import compliance_gate
            papers = compliance_gate(db, client.id, party_id, actor_id, body.note, "paid")
            if papers:
                body.note = papers[:300]
        if amount > owed + 0.009:
            raise HTTPException(400, "%s has only %s left to settle; %s is more than that."
                                     % (doc.number, inr(owed), inr(amount)))
        if doc_type == "supplier_bill":
            # No money for goods that have not come: paying a bill billed ahead of what was received needs a reason,
            # which is kept with the payment and in the audit trail.
            from app.services.procurement import bill_ahead_of_goods
            ahead = bill_ahead_of_goods(db, doc)
            if ahead:
                why = (body.override_reason or "").strip()
                if len(why) < 5:
                    raise HTTPException(409, "%s is billed ahead of the goods received: %s Give the reason it is paid "
                                             "anyway (override reason) to pay it." % (doc.number, ahead[1]))
                body.note = ("Override - %s: %s%s" % (ahead[0].replace("_", " ").lower(), why,
                                                       (" | " + body.note) if body.note else ""))[:300]
                log_audit(db, client.id, "bill_paid_ahead_of_goods", "bill", doc.id, doc.number or "",
                          "%s; reason: %s" % (ahead[1], why), request)
        doc_number = doc.number or ""
    else:
        direction = (body.direction or "").upper()
        if direction not in ("IN", "OUT"):
            raise HTTPException(400, "Is this money coming in or going out?")
        party_type = body.party_type if body.party_type in PARTY_TYPES else "other"
        party_name = (body.party_name or "").strip()
        if not party_name:
            raise HTTPException(400, "Who is this from or to?")
        party_id, job_id, doc_number = None, owned_or_404(db, models.DBJob, client.id, body.job_id, "Project"), ""

    if mode == "Cheque" and direction == "OUT":
        refuse_duplicate_cheque(db, client.id, account.id if account else None, body.reference)

    # Paid in pieces is paid all the same: what already went out against this bill, or to this party today, without a
    # request counts with this payment against the limit.
    so_far = preq.paid_unasked(db, client.id, party_name, on, doc_type, doc.id if doc else None) \
        if (direction == "OUT" and not body.request_id) else 0.0
    # A colleague of the Master's signs in as the company but is not the Master: their payments are approved like anyone's.
    if not body.request_id and direction == "OUT" and preq.needs_request(db, client.id, None, amount, member=_colleague(request, db),
                                                                         so_far=so_far):
        raise HTTPException(409, "Payments are approved before they are made: send it for approval "
                                 "(a payment request), and pay it once it is approved.")

    approved = None
    if body.request_id:
        approved = preq.use_for_payment(db, client.id, body.request_id, doc_type, doc.id if doc else None, amount, party_name, job_id,
                                    head=head if doc_type == "expense" else None)
    elif direction == "OUT" and preq.needs_request(db, client.id, session_employee(request, db), amount, so_far=so_far):
        raise HTTPException(409, "Payments are approved before they are made: send it for approval "
                                 "(a payment request), and pay it once it is approved.")
    e = models.DBMoneyEntry(
        client_id=client.id, number=next_money_number(db, client.id, direction),
        direction=direction, party_type=party_type, party_name=party_name,
        party_id=party_id, doc_type=doc_type, doc_id=(doc.id if doc else None),
        doc_number=doc_number, job_id=job_id, account_id=(account.id if account else None),
        amount=amount, paid_on=on, mode=mode, reference=(body.reference or "").strip()[:80],
        note=(body.note or "").strip()[:300], recorded_by_name=actor_name, head=head)
    db.add(e)
    db.flush()
    if approved is not None:
        approved.status, approved.entry_id = "PAID", e.id
    settled = _settle_doc(db, client.id, doc_type, doc, worth, on) if doc else None
    log_audit(db, client.id, "money_" + direction.lower(), doc_type, e.doc_id or 0,
              e.number, "%s %s %s" % (party_name, inr(amount), doc_number), request)
    db.commit()
    db.refresh(e)
    notify(db, client.id, "money_in" if direction == "IN" else "money_out",
           "%s %s %s %s" % (e.number, "received" if direction == "IN" else "paid", inr(amount),
                            ("from " if direction == "IN" else "to ") + (party_name or "")),
           "%s%s by %s." % (("against " + doc_number + ", ") if doc_number else "on account, ",
                            mode or "", actor_name or ""),
           view="ledger-view", ref_type="money", ref_id=e.id,
           severity="money")
    db.refresh(e)
    left = money(worth - settled) if doc else None
    return {"ok": True, "entry": money_entry_dict(e, {account.id: account} if account else {}),
            "settled": settled, "left": left,
            "message": ("%s %s %s %s." % (e.number, "received" if direction == "IN" else "paid",
                                           inr(amount), ("against " + doc_number) if doc_number
                                           else ("%s, %s" % (head, party_name)) if head
                                           else ("on account, " + party_name)))
                       + ((" %s left on it." % inr(left)) if left else (" Settled in full." if doc else ""))}


@router.get("/api/money/entries/{entry_id}/voucher.pdf")
def money_voucher_pdf(entry_id: int, request: Request, db: Session = Depends(get_read_db)):
    """The voucher for one receipt, payment, expense or transfer, on the company's letterhead - to file, to sign, or
    to hand the payer as their receipt."""
    client = require_items_access(request, db, "bills.view_all")
    e = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.id == entry_id,
                                             models.DBMoneyEntry.client_id == client.id).first()
    if not e:
        raise HTTPException(404, "Entry not found")
    accounts = {a.id: a for a in db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client.id).all()}
    job = db.query(models.DBJob).filter(models.DBJob.id == e.job_id, models.DBJob.client_id == client.id).first() \
        if e.job_id else None
    return form_pdf_response(money_voucher_spec(db, client, e, accounts, job), e.number or "voucher")


def _colleague(request, db):
    """A colleague of the Master's: signed in as the company, but not the Master - their payments are approved like anyone's."""
    try:
        get_client_user(request, db)
    except HTTPException:
        return None
    return current_member(request, db)


def _is_master(request, db):
    """The Master themselves: not a member of staff, and not a colleague signed in as the company."""
    return session_employee(request, db) is None and _colleague(request, db) is None


def _request_reader(request, db):
    """Who may see payment requests: whoever sees the money, and whoever approves it."""
    client, emp = session_person(request, db)
    if emp is not None and not (preq.can_check(emp) or require_view(emp)):
        raise HTTPException(403, "Your access does not include payments.")
    return client, emp


def require_view(emp):
    from app.core.permissions import employee_can
    return employee_can(emp, "bills.view_all") or employee_can(emp, "bills.pay")


@router.get("/api/payment-requests/rules")
def payment_rules(request: Request, db: Session = Depends(get_read_db)):
    client, emp = _request_reader(request, db)
    rules = preq.approval_rules(db, client.id)
    master = emp is None and _colleague(request, db) is None
    return {**rules, "can_check": preq.can_check(emp), "can_release": preq.can_release(emp), "master": master,
            "me": emp.id if emp is not None else None}


@router.put("/api/payment-requests/rules")
def save_payment_rules(body: PaymentRulesIn, request: Request, db: Session = Depends(get_db)):
    """Whether payments wait for approval - the Master's decision."""
    client, emp = session_person(request, db)
    if emp is not None or _colleague(request, db) is not None:      # a colleague signs in as the company, but is not the Master
        raise HTTPException(403, "Only the Master sets how payments are approved.")
    if body.md_above is not None and body.free_below is not None and body.md_above and body.md_above < body.free_below:
        raise HTTPException(400, "The MD's limit cannot be below the amount that needs no approval.")
    preq.save_rules(db, client.id, body.on, body.free_below, body.md_above, body.valid_days)
    log_audit(db, client.id, "payment_rules_changed", "settings", None, "payment approval",
              "%s; free below %s; MD above %s" % ("on" if body.on else "off", inr(body.free_below or 0), inr(body.md_above or 0)),
              request)
    db.commit()
    return {**preq.approval_rules(db, client.id), "message": "Payment approval %s." % ("on" if body.on else "off")}


@router.get("/api/payment-requests")
def list_payment_requests(request: Request, status: str = "", db: Session = Depends(get_read_db)):
    client, _ = _request_reader(request, db)
    q = db.query(models.DBPaymentRequest).filter(models.DBPaymentRequest.client_id == client.id)
    if status == "open":
        q = q.filter(models.DBPaymentRequest.status.in_(preq.OPEN))
    elif status:
        q = q.filter(models.DBPaymentRequest.status == status.upper())
    rows = q.order_by(models.DBPaymentRequest.id.desc()).limit(500).all()
    accounts = {a.id: a for a in db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client.id).all()}
    job_ids = {r.job_id for r in rows if r.job_id}
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.id.in_(job_ids)).all()} if job_ids else {}
    days = preq.valid_days(db, client.id)
    out = [preq.request_dict(r, accounts, jobs, days) for r in rows]
    by = lambda *s: money(sum(r["amount"] for r in out if r["status"] in s and not r["expired"]))
    return {"requests": out, "summary": {"with_accounts": by("PENDING"), "with_md": by("AWAITING_MD"),
                                         "to_pay": by("APPROVED"), "open": len([r for r in out if r["status"] in preq.OPEN])}}


@router.post("/api/payment-requests")
def raise_payment_request(body: MoneyIn, request: Request, db: Session = Depends(get_db)):
    """Ask for a payment to be approved: a bill or part of it, an advance on account, or an expense."""
    client, _, actor_name = wo_actor(request, db, "bills.pay")
    r = preq.raise_request(db, client, session_employee(request, db), actor_name, body, member=_colleague(request, db))
    log_audit(db, client.id, "payment_requested", r.doc_type, r.doc_id or 0, r.number,
              "%s %s %s" % (r.party_name, inr(r.amount), r.doc_number), request)
    db.commit()
    return {"ok": True, "request": preq.request_dict(r),
            "message": "%s: %s to %s sent for approval." % (r.number, inr(r.amount), r.party_name)}


@router.post("/api/payment-requests/{request_id}/decide")
def decide_payment_request(request_id: int, body: PaymentDecisionIn, request: Request, db: Session = Depends(get_db)):
    client, emp = session_person(request, db)
    return _decide_payment(db, client, emp, request_id, body.decision, body.note, request, member=_colleague(request, db))


def _decide_payment(db, client, emp, request_id, decision, note, request, member=None):
    from app.services.hr import employee_name
    who = employee_name(emp) if emp is not None else ((member.name or member.email) if member is not None else (client.contact_name or "Master"))
    r = preq.request_or_404(db, client.id, request_id)
    message = preq.decide(db, client, emp, who, r, decision, note, member=member)
    log_audit(db, client.id, "payment_" + ("approved" if decision == "approve" else "rejected"), r.doc_type,
              r.doc_id or 0, r.number, message, request)
    db.commit()
    return {"ok": True, "request": preq.request_dict(r), "message": message}


@router.post("/api/payment-requests/{request_id}/pay")
def pay_payment_request(request_id: int, body: RequestPayIn, request: Request, db: Session = Depends(get_db)):
    """Pay what was approved, exactly as it was approved: the same bill, party, head and project."""
    client = require_items_access(request, db, "bills.pay")
    r = preq.request_or_404(db, client.id, request_id)
    if r.status != "APPROVED":
        raise HTTPException(409, "%s is %s, not approved to pay." % (r.number, preq.STATUS_LABEL.get(r.status, r.status).lower()))
    preq.refuse_if_expired(db, client.id, r)
    money_body = MoneyIn(
        doc_type=r.doc_type, doc_id=r.doc_id, amount=body.amount or r.amount, paid_on=body.paid_on or "",
        mode=body.mode or r.mode or "Bank transfer", reference=body.reference or "",
        account_id=body.account_id or r.account_id, note=r.note or "", direction="OUT", party_type=r.party_type,
        party_name=r.party_name, job_id=r.job_id, head=r.head, request_id=r.id,
        override_reason=body.override_reason or "")
    return record_money(money_body, request, db)


@router.post("/api/payment-requests/{request_id}/cancel")
def cancel_payment_request(request_id: int, request: Request, db: Session = Depends(get_db)):
    client, emp = session_person(request, db)
    r = preq.request_or_404(db, client.id, request_id)
    message = preq.cancel(db, client, emp, r)
    log_audit(db, client.id, "payment_request_withdrawn", r.doc_type, r.doc_id or 0, r.number, message, request)
    db.commit()
    return {"ok": True, "message": message}


# --- site cash (imprest) -----------------------------------------------------------------------------------------------

def _site_cash_names(db, client_id, ids):
    from app.services.hr import employee_name
    ids = {i for i in ids if i}
    return {e.id: employee_name(e) for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client_id, models.DBEmployee.id.in_(ids)).all()} if ids else {}


def _jobs(db, client_id, ids):
    ids = {i for i in ids if i}
    return {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id,
                                                           models.DBJob.id.in_(ids)).all()} if ids else {}


@router.get("/api/site-cash")
def site_cash_view(request: Request, account_id: int = 0, status: str = "", db: Session = Depends(get_read_db)):
    """The cash boxes this person sees - every one for accounts, their own for a site engineer - with what each should
    hold, what is waiting to be checked, and the payments made out of them."""
    client, emp = session_person(request, db)
    boxes = site_cash.boxes_for(db, client.id, emp)
    pending = site_cash.pending_by_box(db, client.id)
    names = _site_cash_names(db, client.id, [b.custodian_id for b in boxes])
    ids = [b.id for b in boxes]
    q = db.query(models.DBSiteCashExpense).filter(models.DBSiteCashExpense.client_id == client.id,
                                                  models.DBSiteCashExpense.account_id.in_(ids or [0]))
    if account_id:
        q = q.filter(models.DBSiteCashExpense.account_id == account_id)
    if status:
        q = q.filter(models.DBSiteCashExpense.status == status.upper())
    rows = q.order_by(models.DBSiteCashExpense.spent_on.desc(), models.DBSiteCashExpense.id.desc()).limit(500).all()
    jobs = _jobs(db, client.id, [b.job_id for b in boxes] + [x.job_id for x in rows])
    from app.services.rfq_quotes import documents_of
    photos = documents_of(db, client.id, "site_cash", [x.id for x in rows])
    return {"boxes": [site_cash.box_dict(db, b, account_balance(db, client.id, b), pending.get(b.id, 0.0), names, jobs)
                      for b in boxes],
            "expenses": [site_cash.expense_dict(x, photos, names, jobs) for x in rows],
            "manage": site_cash.can_manage(emp), "me": emp.id if emp is not None else None}


@router.put("/api/site-cash/boxes/{account_id}")
def set_cash_box(account_id: int, body: CashBoxIn, request: Request, db: Session = Depends(get_db)):
    """Make a cash box a site's imprest: the site, the member of staff who holds it, and the float it is kept at."""
    client, emp = session_person(request, db)
    if not site_cash.can_manage(emp):
        raise HTTPException(403, "Accounts set up the site cash boxes.")
    box = site_cash.box_or_404(db, client.id, emp, account_id)
    box.job_id = owned_or_404(db, models.DBJob, client.id, body.job_id, "Project")
    box.custodian_id = owned_or_404(db, models.DBEmployee, client.id, body.custodian_id, "Custodian")
    box.imprest_amount = money(max(0.0, body.imprest_amount or 0))
    log_audit(db, client.id, "cash_box_set", "bank_account", box.id, box.name or "",
              "float %s" % inr(box.imprest_amount), request)
    db.commit()
    return {"ok": True, "message": "%s set up: float %s." % (box.name, inr(box.imprest_amount))}


@router.post("/api/site-cash/expenses")
def submit_site_expense(body: SiteCashExpenseIn, request: Request, db: Session = Depends(get_db)):
    """A payment made out of the site's cash box, entered from site."""
    from app.services.hr import employee_name
    client, emp = session_person(request, db)
    box = site_cash.box_or_404(db, client.id, emp, body.account_id)
    body.spent_on = entry_date(body.spent_on, "The day it was spent")
    refuse_if_locked(db, client.id, body.spent_on)
    member = _colleague(request, db) if emp is None else None
    who = employee_name(emp) if emp is not None else (
        (member.name or member.email) if member is not None else (client.contact_name or "Master"))
    x = site_cash.submit(db, client, emp, who, box, body, member=member)
    warning = site_cash.cash_warning(db, client.id, x.paid_to, x.spent_on)
    log_audit(db, client.id, "site_cash_spent", "site_cash", x.id, x.number,
              "%s %s %s" % (x.head, inr(x.amount), x.paid_to), request)
    db.commit()
    return {"ok": True, "expense": site_cash.expense_dict(x), "warning": warning,
            "message": "%s: %s to %s entered; accounts will check it." % (x.number, inr(x.amount), x.paid_to)}


@router.post("/api/site-cash/expenses/{expense_id}/photo")
def site_expense_photo(expense_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """The bill, photographed on site, kept with the expense."""
    from app.core.files import store_file
    from app.services.hr import employee_name
    client, emp = session_person(request, db)
    x = site_cash.expense_or_404(db, client.id, expense_id)
    site_cash.box_or_404(db, client.id, emp, x.account_id)
    if x.status != "SUBMITTED":
        raise HTTPException(409, "%s is already %s." % (x.number, x.status.lower()))
    who = employee_name(emp) if emp is not None else (client.contact_name or "Master")
    f = store_file(db, client.id, file, file.file.read(), job_id=x.job_id, attached_type="site_cash", attached_id=x.id,
                   kind="bill", caption="Bill for %s, %s" % (x.number, x.paid_to), by=who)
    db.commit()
    return {"ok": True, "photo": {"id": f.id, "name": f.name}, "message": "Bill kept with %s." % x.number}


@router.post("/api/site-cash/expenses/{expense_id}/decide")
def decide_site_expense(expense_id: int, body: PaymentDecisionIn, request: Request, db: Session = Depends(get_db)):
    client, emp = session_person(request, db)
    return _decide_site_expense(db, client, emp, expense_id, body.decision, body.note, request)


def _decide_site_expense(db, client, emp, expense_id, decision, note, request):
    from app.services.hr import employee_name
    member = _colleague(request, db) if emp is None and request is not None else None
    who = employee_name(emp) if emp is not None else (
        (member.name or member.email) if member is not None else (client.contact_name or "Master"))
    x = site_cash.expense_or_404(db, client.id, expense_id)
    if decision == "approve":
        refuse_if_locked(db, client.id, x.spent_on, "booked")       # approved, it is booked on the day it was spent
    message = site_cash.decide(db, client, emp, who, x, decision, note, member=member)
    warning = site_cash.cash_warning(db, client.id, x.paid_to, x.spent_on) if decision == "approve" else ""
    if warning:
        message = "%s %s" % (message, warning)
    log_audit(db, client.id, "site_cash_" + ("approved" if decision == "approve" else "rejected"), "site_cash",
              x.id, x.number, message, request)
    db.commit()
    return {"ok": True, "expense": site_cash.expense_dict(x), "message": message, "warning": warning}


@router.get("/api/site-cash/boxes/{account_id}/statement.pdf")
def cash_box_statement(account_id: int, request: Request, date_from: str = "", date_to: str = "",
                       db: Session = Depends(get_read_db)):
    """The box's cash book for the period, on the letterhead: opening, every top-up and every expense booked, the
    closing balance - and what has been spent and not yet checked - for the custodian to sign and accounts to keep."""
    from app.documents.forms import cash_statement_spec
    client, emp = session_person(request, db)
    box = site_cash.box_or_404(db, client.id, emp, account_id)
    book = cash_book(db, client.id, box, date_from, date_to)
    pending = site_cash.pending_by_box(db, client.id).get(box.id, 0.0)
    names = _site_cash_names(db, client.id, [box.custodian_id])
    job = _jobs(db, client.id, [box.job_id]).get(box.job_id)
    return form_pdf_response(cash_statement_spec(db, client, box, book, pending, names.get(box.custodian_id, ""), job,
                                                 date_from, date_to), "cash_book_%s" % (box.name or "site"))


# --- bank reconciliation and the cheque register ----------------------------------------------------------------------

@router.get("/api/bank-reco/{account_id}")
def bank_reco_view(account_id: int, request: Request, as_of: str = "", db: Session = Depends(get_read_db)):
    """One bank account against its statement: the reconciliation on a day, the statement lines not yet matched (with
    the entries each could be), and the entries the bank has not moved yet."""
    client = require_items_access(request, db, "bills.view_all")
    account = bank_reco.bank_account_or_404(db, client.id, account_id)
    day = (as_of or date.today().isoformat())[:10]
    lines = db.query(models.DBBankStatementLine).filter(
        models.DBBankStatementLine.client_id == client.id, models.DBBankStatementLine.account_id == account.id,
        models.DBBankStatementLine.status == "UNMATCHED").order_by(models.DBBankStatementLine.txn_date).limit(500).all()
    counts = dict(db.query(models.DBBankStatementLine.status, func.count(models.DBBankStatementLine.id)).filter(
        models.DBBankStatementLine.client_id == client.id, models.DBBankStatementLine.account_id == account.id).group_by(
        models.DBBankStatementLine.status).all())
    return {"account": account_dict(account), "brs": bank_reco.brs(db, client.id, account, day),
            "lines": [bank_reco.line_dict(l) for l in lines],
            "suggestions": bank_reco.suggestions(db, client.id, account, lines),
            "counts": {"matched": counts.get("MATCHED", 0), "unmatched": counts.get("UNMATCHED", 0),
                       "ignored": counts.get("IGNORED", 0)}}


@router.post("/api/bank-reco/{account_id}/statement")
def bank_statement_upload(account_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """The bank's statement as downloaded from its site: read, stored (lines already in are not stored twice), and
    matched to the books."""
    client, _, actor_name = wo_actor(request, db, "bills.pay")
    account = bank_reco.bank_account_or_404(db, client.id, account_id)
    data = file.file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "That statement is over 10 MB. Download a shorter period.")
    lines = bank_reco.read_statement(data, file.filename or "")
    added, again, matched = bank_reco.import_statement(db, client.id, account, lines, file.filename, actor_name)
    log_audit(db, client.id, "bank_statement_imported", "bank_account", account.id, account.name or "",
              "%d lines, %d matched" % (added, matched), request)
    db.commit()
    return {"ok": True, "added": added, "already_in": again, "matched": matched,
            "message": "%d line%s read from the statement%s; %d matched to the books." % (
                added, "" if added == 1 else "s", (" (%d already in)" % again) if again else "", matched)}


def _line_or_404(db, client_id, line_id):
    l = db.query(models.DBBankStatementLine).filter(models.DBBankStatementLine.id == line_id,
                                                    models.DBBankStatementLine.client_id == client_id).first()
    if l is None:
        raise HTTPException(404, "Statement line not found")
    return l


@router.post("/api/bank-reco/lines/{line_id}/match")
def bank_line_match(line_id: int, body: LineMatchIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "bills.pay")
    l = _line_or_404(db, client.id, line_id)
    e = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.id == body.entry_id,
                                             models.DBMoneyEntry.client_id == client.id).first()
    if e is None or e.account_id != l.account_id or e.voided:
        raise HTTPException(400, "That entry is not through this account.")
    if (e.direction == "IN") != (l.credit > 0) or abs(money(e.amount) - money(l.credit or l.debit)) > 0.009:
        raise HTTPException(400, "%s is %s %s; the bank's line is %s %s." % (
            e.number, "in" if e.direction == "IN" else "out", inr(e.amount),
            "in" if l.credit > 0 else "out", inr(l.credit or l.debit)))
    if e.statement_line_id and e.statement_line_id != l.id:
        raise HTTPException(409, "%s is already matched to another line of the statement." % e.number)
    if l.status == "MATCHED" and l.entry_id and l.entry_id != e.id:
        # Re-pointing a matched line silently un-cleared the entry it was matched to: unmatch it first, on purpose.
        was = db.query(models.DBMoneyEntry.number).filter(models.DBMoneyEntry.id == l.entry_id).scalar()
        raise HTTPException(409, "That line is already matched to %s. Unmatch it first." % (was or "another entry"))
    bank_reco.match(l, e)
    log_audit(db, client.id, "bank_line_matched", "bank_account", l.account_id, e.number,
              "%s %s line of %s" % (inr(e.amount), "in" if e.direction == "IN" else "out", l.txn_date), request)
    db.commit()
    return {"ok": True, "message": "Matched to %s; cleared on %s." % (e.number, l.txn_date)}


@router.post("/api/bank-reco/lines/{line_id}/unmatch")
def bank_line_unmatch(line_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "bills.pay")
    l = _line_or_404(db, client.id, line_id)
    was = db.query(models.DBMoneyEntry.number).filter(models.DBMoneyEntry.id == l.entry_id).scalar() if l.entry_id else ""
    bank_reco.unmatch(db, l)
    log_audit(db, client.id, "bank_line_unmatched", "bank_account", l.account_id, was or "",
              "line of %s, %s" % (l.txn_date, inr(l.credit or l.debit)), request)
    db.commit()
    return {"ok": True, "message": "Line put back as not matched."}


@router.post("/api/bank-reco/lines/{line_id}/ignore")
def bank_line_ignore(line_id: int, request: Request, db: Session = Depends(get_db)):
    """A line that is nothing for the books (a reversal and its correction, both by the bank)."""
    client, _, _ = wo_actor(request, db, "bills.pay")
    l = _line_or_404(db, client.id, line_id)
    if l.status == "MATCHED":
        bank_reco.unmatch(db, l)
    l.status = "IGNORED"
    log_audit(db, client.id, "bank_line_ignored", "bank_account", l.account_id, "",
              "line of %s, %s: %s" % (l.txn_date, inr(l.credit or l.debit), (l.narration or "")[:120]), request)
    db.commit()
    return {"ok": True, "message": "Line set aside."}


@router.post("/api/bank-reco/lines/{line_id}/book")
def bank_line_book(line_id: int, body: LineBookIn, request: Request, db: Session = Depends(get_db)):
    """What the bank booked on its own - charges out, interest in - booked in the books from its line, and matched."""
    client, _, actor_name = wo_actor(request, db, "bills.pay")
    l = _line_or_404(db, client.id, line_id)
    if l.status != "UNMATCHED":
        raise HTTPException(409, "That line is already %s." % l.status.lower())
    refuse_if_locked(db, client.id, l.txn_date)
    out = l.debit > 0
    heads = EXPENSE_HEADS if out else INCOME_HEADS
    head = next((h for h in heads if h.lower() == (body.head or "").strip().lower()), "")
    if not head:
        raise HTTPException(400, "Book it under one of: %s." % ", ".join(heads))
    e = models.DBMoneyEntry(
        client_id=client.id, number=next_money_number(db, client.id, "OUT" if out else "IN"),
        direction="OUT" if out else "IN", party_type="other", party_name="Bank",
        doc_type="expense" if out else "income", account_id=l.account_id, amount=money(l.debit or l.credit),
        paid_on=l.txn_date, mode="Bank transfer", reference=(l.reference or "")[:80],
        note=((body.note or "").strip() or l.narration or "")[:300], head=head, recorded_by_name=actor_name)
    db.add(e)
    db.flush()
    bank_reco.match(l, e)
    log_audit(db, client.id, "bank_line_booked", "bank_account", l.account_id, e.number, "%s %s" % (head, inr(e.amount)), request)
    db.commit()
    return {"ok": True, "entry": money_entry_dict(e), "message": "%s booked: %s %s." % (e.number, head, inr(e.amount))}


@router.post("/api/money/entries/{entry_id}/clear")
def clear_entry(entry_id: int, body: ClearIn, request: Request, db: Session = Depends(get_db)):
    """A cheque cleared (or not after all), by hand - from the passbook, without a statement to read in."""
    client, _, _ = wo_actor(request, db, "bills.pay")
    e = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.id == entry_id, models.DBMoneyEntry.client_id == client.id).first()
    if e is None:
        raise HTTPException(404, "Entry not found")
    if e.voided:
        raise HTTPException(409, "%s is void; a void entry does not clear." % e.number)
    account = db.query(models.DBBankAccount).filter(models.DBBankAccount.id == e.account_id).first() if e.account_id else None
    if account is None or account.kind == "Cash":
        raise HTTPException(409, "%s is not through a bank account; only a bank clears an entry." % e.number)
    if e.statement_line_id:
        raise HTTPException(409, "%s is matched to the bank's statement; unmatch the line instead." % e.number)
    on = (body.cleared_on or "").strip()[:10]
    if on:
        on = entry_date(on, "The clearing date")
        if on < (e.paid_on or "")[:10]:
            raise HTTPException(400, "It cannot have cleared before it was written.")
        if on > date.today().isoformat():
            raise HTTPException(400, "It cannot have cleared on a day still to come.")
    before = e.cleared_on or ""
    e.cleared_on = on
    log_audit(db, client.id, "money_cleared" if on else "money_uncleared", e.doc_type or "", e.doc_id or 0, e.number,
              "cleared %s -> %s" % (before or "-", on or "-"), request)
    db.commit()
    return {"ok": True, "message": ("%s cleared on %s." % (e.number, on)) if on else "%s marked not cleared." % e.number}


@router.get("/api/bank-reco/{account_id}/brs.pdf")
def brs_pdf(account_id: int, request: Request, as_of: str = "", db: Session = Depends(get_read_db)):
    """The bank reconciliation statement on a day, on the letterhead, for the auditor's file."""
    from app.documents.forms import brs_spec
    client = require_items_access(request, db, "bills.view_all")
    account = bank_reco.bank_account_or_404(db, client.id, account_id)
    day = (as_of or date.today().isoformat())[:10]
    return form_pdf_response(brs_spec(db, client, account, bank_reco.brs(db, client.id, account, day)),
                             "BRS_%s_%s" % (account.name or "bank", day))


@router.get("/api/cheques")
def cheque_register(request: Request, status: str = "", account_id: int = 0, db: Session = Depends(get_read_db)):
    """Every cheque written or received: number, date, party, amount, account, and where it stands."""
    client = require_items_access(request, db, "bills.view_all")
    q = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.client_id == client.id, models.DBMoneyEntry.mode == "Cheque")
    if account_id:
        q = q.filter(models.DBMoneyEntry.account_id == account_id)
    accounts = {a.id: a for a in db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client.id).all()}
    today = date.today()
    rows = []
    for e in q.order_by(models.DBMoneyEntry.paid_on.desc(), models.DBMoneyEntry.id.desc()).limit(1000).all():
        if e.doc_type == "contra" and e.direction == "IN":
            continue                                         # a cheque between our own accounts is one cheque, not two
        st = bank_reco.cheque_status(e, today)
        if status and st != status.upper():
            continue
        rows.append(dict(money_entry_dict(e, accounts), status=st))
    live = [r for r in rows if r["status"] in ("PENDING", "STALE")]
    return {"cheques": rows, "summary": {
        "issued_pending": money(sum(r["amount"] for r in live if r["direction"] == "OUT")),
        "received_pending": money(sum(r["amount"] for r in live if r["direction"] == "IN")),
        "stale": len([r for r in rows if r["status"] == "STALE"]),
        "bounced": len([r for r in rows if r["status"] == "BOUNCED"])}}


# --- Tally ------------------------------------------------------------------------------------------------------------

def _tally_period(date_from, date_to):
    for d in (date_from, date_to):
        if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise HTTPException(400, "Dates as 2026-04-01.")
    if date_from and date_to and date_to < date_from:
        raise HTTPException(400, "The period ends before it starts.")
    return date_from or "", date_to or ""


@router.get("/api/tally/settings")
def tally_settings(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    names = tally.ledger_names(db, client.id)
    return {"company": tenant_setting(db, client.id, "tally_company", "") or "",
            "ledgers": [{"key": k, "label": tally.LABELS[k], "name": names[k], "default": d, "group": g}
                        for k, (d, g, _) in tally.LEDGERS.items()]}


@router.put("/api/tally/settings")
def save_tally_settings(body: TallySettingsIn, request: Request, db: Session = Depends(get_db)):
    """The ledger names as they are in the company's Tally, so what is imported lands on the ledgers already there."""
    client, _, _ = wo_actor(request, db, "accounts.manage")
    if body.ledgers is not None:
        tally.save_ledger_names(db, client.id, body.ledgers)
    company = re.sub(r"\s+", " ", body.company or "").strip()[:120]
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client.id, models.DBSettings.key == "tally_company").first()
    if row:
        row.value = company
    elif company:
        db.add(models.DBSettings(client_id=client.id, key="tally_company", value=company, description="Company name in Tally"))
    db.commit()
    return {"ok": True, "message": "Tally ledger names saved."}


@router.get("/api/tally/summary")
def tally_summary(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
    """What a period's export holds: vouchers by type, the ledgers and cost centres it names, anything left out."""
    client = require_items_access(request, db, "bills.view_all")
    f, t = _tally_period(date_from, date_to)
    return tally.Books(db, client, f, t).summary()


def _tally_file(xml, name):
    from fastapi.responses import Response
    return Response(content=xml.encode("utf-8"), media_type="application/xml",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@router.get("/api/tally/masters.xml")
def tally_masters(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
    """The ledgers and cost centres the period's vouchers use - imported first (Import > Masters)."""
    client = require_items_access(request, db, "bills.view_all")
    f, t = _tally_period(date_from, date_to)
    books = tally.Books(db, client, f, t)
    log_audit(db, client.id, "tally_export", "tally", None, "masters", "%s to %s" % (f or "start", t or "today"), request)
    db.commit()
    return _tally_file(tally.masters_xml(books, tenant_setting(db, client.id, "tally_company", "")),
                       "yerp_masters_%s_%s.xml" % (f or "start", t or "today"))


@router.get("/api/tally/vouchers.xml")
def tally_vouchers(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
    """The period's vouchers - imported after the masters (Import > Transactions)."""
    client = require_items_access(request, db, "bills.view_all")
    f, t = _tally_period(date_from, date_to)
    books = tally.Books(db, client, f, t)
    log_audit(db, client.id, "tally_export", "tally", None, "vouchers",
              "%d vouchers, %s to %s" % (len(books.vouchers), f or "start", t or "today"), request)
    # Kept: a voided entry is sent as a cancellation only when an earlier export took it.
    db.commit()
    return _tally_file(tally.vouchers_xml(books, tenant_setting(db, client.id, "tally_company", "")),
                       "yerp_vouchers_%s_%s.xml" % (f or "start", t or "today"))


@router.get("/api/money/heads")
def money_heads(request: Request, db: Session = Depends(get_read_db)):
    """The heads an expense voucher or a sundry receipt is booked under."""
    require_items_access(request, db, "bills.view_all")
    return {"expense": list(EXPENSE_HEADS), "income": list(INCOME_HEADS)}


@router.post("/api/money/transfer")
def transfer_money(body: TransferIn, request: Request, db: Session = Depends(get_db)):
    """A contra: cash drawn from the bank for a site's cash box, a cash box paid back into the bank, or money moved
    between two banks. One voucher, two entries - out of one account and into the other - so each book is right and
    neither is a receipt or a payment to anybody."""
    client, _, actor_name = wo_actor(request, db, "bills.pay")
    amount = money(body.amount or 0)
    if amount <= 0:
        raise HTTPException(400, "How much?")
    if body.from_account_id == body.to_account_id:
        raise HTTPException(400, "Money moves from one account to another: choose two different accounts.")
    accounts = {a.id: a for a in db.query(models.DBBankAccount).filter(
        models.DBBankAccount.client_id == client.id,
        models.DBBankAccount.id.in_((body.from_account_id, body.to_account_id))).all()}
    src, dst = accounts.get(body.from_account_id), accounts.get(body.to_account_id)
    if not src or not dst:
        raise HTTPException(404, "That bank account or cash box is not on file.")
    mode = body.mode if body.mode in MONEY_MODES else ("Cash" if "Cash" in (src.kind, dst.kind) else "Bank transfer")
    if mode == "Cheque" and not (body.reference or "").strip():
        raise HTTPException(400, "A cheque needs its number.")
    on = entry_date(body.paid_on, "The transfer date")
    refuse_if_locked(db, client.id, on)
    if mode == "Cheque":
        refuse_duplicate_cheque(db, client.id, src.id, body.reference)
    if src.kind == "Cash":
        # A cash box holds what is in it; a bank account may run on an overdraft or cash credit, a cash box cannot.
        held = account_balance(db, client.id, src)
        if amount > held + 0.009:
            raise HTTPException(409, "%s holds only %s; %s cannot be moved out of it." % (src.name, inr(held), inr(amount)))
    rules = preq.approval_rules(db, client.id)
    if rules["on"]:
        # Where payments wait for a signature, moving money was the way round it: a clerk drew 5 lakh from the bank into
        # a cash box with nobody's say. Over the limit (counting what else left this account today by transfer), a move
        # is made by whoever checks payments - the accounts head or the Master.
        emp, member = session_employee(request, db), _colleague(request, db)
        moved_today = money(sum(e.amount or 0 for e in db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.client_id == client.id, models.DBMoneyEntry.account_id == src.id,
            models.DBMoneyEntry.doc_type == "contra", models.DBMoneyEntry.direction == "OUT",
            models.DBMoneyEntry.voided.is_(False), models.DBMoneyEntry.paid_on == on).all()))
        if money(amount + moved_today) > rules["free_below"] and (
                member is not None or (emp is not None and not preq.can_check(emp))):
            raise HTTPException(409, "Payments are approved before they are made, and %s out of %s is over the %s "
                                     "limit: the accounts head or the Master moves it."
                                     % (inr(amount), src.name, inr(rules["free_below"])))
    number = next_money_number(db, client.id, "OUT", stem="CON-")
    common = dict(client_id=client.id, number=number, party_type="other", doc_type="contra", amount=amount,
                  paid_on=on, mode=mode, reference=(body.reference or "").strip()[:80],
                  note=(body.note or "").strip()[:300], recorded_by_name=actor_name)
    out = models.DBMoneyEntry(direction="OUT", party_name=dst.name or "", account_id=src.id, **common)
    into = models.DBMoneyEntry(direction="IN", party_name=src.name or "", account_id=dst.id, **common)
    db.add_all([out, into])
    db.flush()
    out.pair_id, into.pair_id = into.id, out.id
    log_audit(db, client.id, "money_transfer", "contra", out.id, number,
              "%s %s to %s" % (inr(amount), src.name, dst.name), request)
    db.commit()
    return {"ok": True, "entry": money_entry_dict(out, accounts),
            "message": "%s: %s moved from %s to %s." % (number, inr(amount), src.name, dst.name)}


def _unmatch_statement(db, e):
    """A voided entry's line on the bank's statement is unmatched again: the money the bank moved is still to be accounted for."""
    if e.statement_line_id:
        line = db.query(models.DBBankStatementLine).filter(models.DBBankStatementLine.id == e.statement_line_id).first()
        if line is not None:
            bank_reco.unmatch(db, line)
        else:
            e.statement_line_id, e.cleared_on = None, ""


@router.post("/api/money/entries/{entry_id}/void")
def void_money(entry_id: int, request: Request, body: dict = None,
               db: Session = Depends(get_db)):
    """A mistake is voided, never deleted; the bill goes back to owing."""
    client, actor_id, actor_name = wo_actor(request, db, "bills.pay")
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "Say why it is being voided.")
    e = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.id == entry_id, models.DBMoneyEntry.client_id == client.id).first()
    if not e:
        raise HTTPException(404, "Entry not found")
    if e.voided:
        raise HTTPException(409, "%s is already void." % e.number)
    other = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.id == e.pair_id,
                                                 models.DBMoneyEntry.client_id == client.id).first() if e.pair_id else None
    legs = [x for x in (e, other) if x is not None]
    for x in legs:
        refuse_if_locked(db, client.id, x.paid_on, "voided")
    cleared = next((x for x in legs if x.cleared_on or x.statement_line_id), None)
    if cleared is not None and not _is_master(request, db):
        # Money the bank has already moved does not un-move because the books say so: undoing it is the Master's call.
        raise HTTPException(409, "%s has cleared the bank%s. Only the Master voids an entry the bank has moved, "
                                 "saying why." % (cleared.number, (" on " + cleared.cleared_on) if cleared.cleared_on else ""))
    e.voided, e.void_reason = True, reason[:300]
    _unmatch_statement(db, e)
    booked = site_cash.expense_for_entry(db, e.id)
    if booked is not None and booked.status == "APPROVED":
        booked.status, booked.entry_id, booked.checked_by_name, booked.checked_at = "SUBMITTED", None, "", ""
    paid_for = preq.request_for_entry(db, e.id)
    if paid_for is not None and paid_for.status == "PAID":
        paid_for.status, paid_for.entry_id = "APPROVED", None     # still approved; the payment was the mistake
    if e.pair_id:
        # A transfer is undone whole: money cannot have left one account and not arrived in the other.
        if other is not None and not other.voided:
            other.voided, other.void_reason = True, reason[:300]
            _unmatch_statement(db, other)                 # the other account's statement line is open again too
    db.flush()
    if e.doc_id and e.doc_type != "on_account":
        doc, worth, *_ = _doc_for_any(db, client.id, e.doc_type, e.doc_id)
        _settle_doc(db, client.id, e.doc_type, doc, worth, "")
    log_audit(db, client.id, "money_voided", e.doc_type, e.doc_id or 0, e.number, reason, request)
    db.commit()
    return {"ok": True, "message": "%s voided." % e.number}


@router.get("/api/money/entries")
def list_money(request: Request, direction: str = "", party: str = "", job_id: int = 0,
               date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    q = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.client_id == client.id)
    if direction:
        q = q.filter(models.DBMoneyEntry.direction == direction.upper())
    if job_id:
        q = q.filter(models.DBMoneyEntry.job_id == job_id)
    accounts = {a.id: a for a in db.query(models.DBBankAccount).filter(
        models.DBBankAccount.client_id == client.id).all()}
    rows = []
    for e in q.order_by(models.DBMoneyEntry.paid_on.desc(), models.DBMoneyEntry.id.desc()).limit(1000).all():
        if party and norm_name(party) not in norm_name(e.party_name):
            continue
        if date_from and (e.paid_on or "") < date_from:
            continue
        if date_to and (e.paid_on or "") > date_to:
            continue
        rows.append(money_entry_dict(e, accounts))
    live = [r for r in rows if not r["voided"]]
    # A transfer between our own accounts is neither received nor paid: it only moved.
    moved = [r for r in live if r["doc_type"] != "contra"]
    return {"entries": rows, "summary": {
        "received": money(sum(r["amount"] for r in moved if r["direction"] == "IN")),
        "paid": money(sum(r["amount"] for r in moved if r["direction"] == "OUT")),
        "expenses": money(sum(r["amount"] for r in moved if r["doc_type"] == "expense")),
        "transferred": money(sum(r["amount"] for r in live if r["doc_type"] == "contra" and r["direction"] == "OUT")),
        "entries": len(live)}}


@router.get("/api/ledger/parties")
def ledger_parties(request: Request, party_type: str = "", db: Session = Depends(get_read_db)):
    """Every party, what has been billed with them, what has moved, and the
    balance - owed to us for a client, owed by us for everybody else."""
    client = require_items_access(request, db, "bills.view_all")
    parties = {}
    for r in _ledger_rows(db, client.id):
        if party_type and r["party_type"] != party_type:
            continue
        if not r["party"]:
            continue
        key = (r["party_type"], norm_name(r["party"]))
        p = parties.setdefault(key, {"party_type": r["party_type"], "party": r["party"],
                                     "billed": 0.0, "moved": 0.0, "last": ""})
        p["billed"] = money(p["billed"] + r["billed"])
        p["moved"] = money(p["moved"] + r["moved"])
        p["last"] = max(p["last"], r["date"] or "")
    out = []
    for p in parties.values():
        p["balance"] = money(p["billed"] - p["moved"])
        out.append(p)
    out.sort(key=lambda p: -abs(p["balance"]))
    return {"parties": out, "summary": {
        "owed_to_us": money(sum(p["balance"] for p in out if p["party_type"] == "client" and p["balance"] > 0)),
        "we_owe": money(sum(p["balance"] for p in out if p["party_type"] != "client" and p["balance"] > 0)),
        "advances_out": money(-sum(p["balance"] for p in out if p["party_type"] != "client" and p["balance"] < 0)),
        "advances_in": money(-sum(p["balance"] for p in out if p["party_type"] == "client" and p["balance"] < 0)),
        "parties": len(out)}}


@router.get("/api/ledger/statement")
def ledger_statement(request: Request, party_type: str, party: str,
                     date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    """A statement of account for one party, oldest first, with the balance
    after every line - the document that is sent to a supplier to agree what
    is owed, and the one a client is sent before a payment is chased."""
    client = require_items_access(request, db, "bills.view_all")
    key = norm_name(party)
    rows = [r for r in _ledger_rows(db, client.id)
            if r["party_type"] == party_type and norm_name(r["party"]) == key]
    rows.sort(key=lambda r: (r["date"] or "", 0 if r["billed"] else 1, r["number"] or ""))
    opening, balance, out = 0.0, 0.0, []
    for r in rows:
        change = money(r["billed"] - r["moved"])
        if date_from and (r["date"] or "") < date_from:
            opening = money(opening + change)
            balance = opening
            continue
        if date_to and (r["date"] or "") > date_to:
            continue
        balance = money(balance + change)
        r = dict(r, balance=balance)
        out.append(r)
    master = None
    if party_type == "supplier":
        master = next((supplier_dict(s) for s in db.query(models.DBSupplier).filter(
            models.DBSupplier.client_id == client.id).all() if norm_name(s.name) == key), None)
    elif party_type == "contractor":
        con = next((c for c in db.query(models.DBContractor).filter(
            models.DBContractor.client_id == client.id).all()
            if norm_name(c.company_name) == key), None)
        if con:
            master = {"name": con.company_name, "gstin": con.gst_number or "", "pan": con.pan or "",
                      "address": con.address or "", "phone": con.phone_number or ""}
    return {"party": party, "party_type": party_type, "master": master,
            "our": our_party(db, client.id), "opening": opening,
            "rows": out, "closing": balance,
            "billed": money(sum(r["billed"] for r in out)),
            "moved": money(sum(r["moved"] for r in out)),
            "closing_words": amount_in_words(abs(balance)),
            "period": {"from": date_from, "to": date_to}}


@router.get("/api/money/book")
def money_book(request: Request, account_id: int = 0, date_from: str = "", date_to: str = "",
               db: Session = Depends(get_read_db)):
    """The bank book or the cash book: every movement through one account,
    in date order, with the balance after each."""
    client = require_items_access(request, db, "bills.view_all")
    account = None
    if account_id:
        account = db.query(models.DBBankAccount).filter(
            models.DBBankAccount.id == account_id,
            models.DBBankAccount.client_id == client.id).first()
        if not account:
            raise HTTPException(404, "Account not found")
    return cash_book(db, client.id, account, date_from, date_to)


def all_accounts_book(db, client_id):
    """(opening, entries) for every account together: every live account's opening balance, and the live entries in
    date order less what each account holds inside that balance already (and what went through a closed account)."""
    held = {a.id: a for a in db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client_id).all()}
    balance = money(sum(a.opening_balance or 0 for a in held.values() if a.is_active is not False))
    entries = []
    for e in db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.voided.is_(False)).order_by(
            models.DBMoneyEntry.paid_on, models.DBMoneyEntry.id).all():
        a = held.get(e.account_id) if e.account_id else None
        if a is not None and (a.is_active is False or (opening_day(a) and (e.paid_on or "") < opening_day(a))):
            continue
        entries.append(e)
    return balance, entries


@router.get("/api/money/cash-flow")
def cash_flow(request: Request, months: int = 12, db: Session = Depends(get_read_db)):
    """Money in and out by month, and the balance at each month's end, for the dashboard - totalled here over every
    entry, not the last thousand. A transfer between our own accounts is neither in nor out (its two legs still sit in
    the balance, where they cancel); a voided entry is nothing. The balance starts from the accounts' opening balances
    and agrees with the all-accounts cash book."""
    client = require_items_access(request, db, "bills.view_all")
    months = max(1, min(int(months or 12), 36))
    today = datetime.now().date()
    keys = []
    for i in range(months - 1, -1, -1):
        y, m = divmod(today.year * 12 + today.month - 1 - i, 12)
        keys.append("%04d-%02d" % (y, m + 1))
    rows = {k: {"month": k, "received": 0.0, "paid": 0.0, "moved": 0.0} for k in keys}
    opening, entries = all_accounts_book(db, client.id)
    for e in entries:
        signed = e.amount if e.direction == "IN" else -e.amount
        month = (e.paid_on or "")[:7]
        if month < keys[0]:
            opening += signed                                   # the balance the window starts from
        elif month in rows:
            rows[month]["moved"] += signed
            if e.doc_type != "contra":
                rows[month]["received" if e.direction == "IN" else "paid"] += e.amount
    out, running = [], money(opening)
    for k in keys:
        r = rows[k]
        running = money(running + r["moved"])
        out.append({"month": k, "received": money(r["received"]), "paid": money(r["paid"]),
                    "net": money(r["received"] - r["paid"]), "running": running})
    return {"months": out, "opening": money(opening)}


def cash_book(db, client_id, account, date_from="", date_to=""):
    """Every movement through one account (or all of them), in date order, with the balance after each."""
    q = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.voided.is_(False))
    if account:
        q = q.filter(models.DBMoneyEntry.account_id == account.id)
        start = opening_day(account)
        if start:
            # The opening balance is the balance on the opening day; what moved before it is already inside it.
            q = q.filter(models.DBMoneyEntry.paid_on >= start)
        entries = q.order_by(models.DBMoneyEntry.paid_on, models.DBMoneyEntry.id).all()
        balance = money(account.opening_balance)
    else:
        balance, entries = all_accounts_book(db, client_id)
    rows = []
    for e in entries:
        signed = e.amount if e.direction == "IN" else -e.amount
        if date_from and (e.paid_on or "") < date_from:
            balance = money(balance + signed)
            continue
        if date_to and (e.paid_on or "") > date_to:
            continue
        balance = money(balance + signed)
        rows.append({"id": e.id, "date": e.paid_on, "number": e.number, "party": e.party_name,
                     "against": e.doc_number or e.head or ("Transfer" if e.doc_type == "contra" else "on account"),
                     "mode": e.mode,
                     "reference": e.reference or "",
                     "received": money(e.amount) if e.direction == "IN" else 0.0,
                     "paid": money(e.amount) if e.direction == "OUT" else 0.0,
                     "balance": balance})
    first = rows[0] if rows else None
    opening = money((first["balance"] - first["received"] + first["paid"]) if first else balance)
    return {"account": account_dict(account) if account else {"name": "All accounts"},
            "opening": opening, "rows": rows, "closing": balance,
            "received": money(sum(r["received"] for r in rows)),
            "paid": money(sum(r["paid"] for r in rows))}


@router.get("/api/money/outstanding/{doc_type}/{doc_id}")
def doc_outstanding(doc_type: str, doc_id: int, request: Request, db: Session = Depends(get_read_db)):
    """What is still owed on one bill - for the payment box to open with."""
    client = require_items_access(request, db, "bills.view_all")
    doc, worth = _doc_for_any(db, client.id, doc_type, doc_id)
    got = already_settled(db, client.id, doc_type, doc, worth)
    ahead = None
    if doc_type == "supplier_bill":
        # Said before the payment is tried: paying it needs a reason (record_money refuses it without one).
        from app.services.procurement import bill_ahead_of_goods
        found = bill_ahead_of_goods(db, doc)
        ahead = {"verdict": found[0], "note": found[1]} if found else None
    return {"number": doc.number, "worth": worth, "settled": got,
            "outstanding": money(max(0.0, worth - got)), "ahead_of_goods": ahead,
            "entries": [money_entry_dict(e) for e in db.query(models.DBMoneyEntry).filter(
                models.DBMoneyEntry.client_id == client.id,
                models.DBMoneyEntry.doc_type == doc_type,
                models.DBMoneyEntry.doc_id == doc_id).order_by(models.DBMoneyEntry.id).all()]}


@router.get("/api/ledger/statement.pdf")
def ledger_statement_pdf(request: Request, party_type: str, party: str, date_from: str = "", date_to: str = "",
                         db: Session = Depends(get_read_db)):
    """The office's copy of a party's statement, to send them."""
    client = require_items_access(request, db, "bills.view_all")
    s = ledger_statement(request, party_type, party, date_from, date_to, db)
    label = {"client": "Client", "contractor": "Sub Contractor", "supplier": "Supplier"}.get(party_type, "Party")
    return form_pdf_response(statement_form_spec(client, party, label, s, date_from, date_to, db=db), "statement_" + party)


@router.get("/api/money/payables.xlsx")
def payables_export(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    d = payables(request, db)
    rows = [(r["number"], r["kind"], r["party"], r["project"], r["due_date"], r["outstanding"], r["bucket"],
             r["days_overdue"], "yes" if r.get("approved") else "no") for r in d["bills"]]
    b = d["buckets"]
    return sheet_response(("Document", "Kind", "Party", "Project", "Due", "Outstanding", "Age", "Days overdue", "Approved"),
                          rows, "what_we_owe.xlsx",
                          preamble=_pre(client, "WHAT WE OWE", ("Not due", b["Not due"], "0-30", b["0-30"], "31-60", b["31-60"]),
                                        ("61-90", b["61-90"], "90+", b["90+"])),
                          closing=[(), ("Total owed", "", "", "", "", d["summary"]["owed"])])


@router.get("/api/money/entries.xlsx")
def money_entries_export(request: Request, direction: str = "", party: str = "", job_id: int = 0,
                         date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    d = list_money(request, direction, party, job_id, date_from, date_to, db)
    rows = [(e["paid_on"], e["number"], "Received" if e["direction"] == "IN" else "Paid", e["party_name"],
             e["doc_number"] or "on account", e["mode"], e["reference"], e["account"], e["amount"],
             "void" if e["voided"] else "") for e in d["entries"]]
    s = d["summary"]
    return sheet_response(("Date", "Voucher", "Way", "Party", "Against", "Mode", "Reference", "Account", "Amount", "Void"),
                          rows, "payments_and_receipts.xlsx",
                          preamble=_pre(client, "PAYMENTS AND RECEIPTS",
                                        ("Period", "%s to %s" % (date_from or "start", date_to or "today"))),
                          closing=[(), ("Received", "", "", "", "", "", "", "", s["received"]),
                                   ("Paid", "", "", "", "", "", "", "", s["paid"])])
