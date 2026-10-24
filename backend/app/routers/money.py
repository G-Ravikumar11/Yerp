"""The money endpoints."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.client_billing import RA_CREDIT_DAYS
from app.constants.money import COST_CATEGORIES, EXPENSE_HEADS, INCOME_HEADS, MONEY_MODES, PARTY_TYPES
from app.constants.projects import JOB_FINISHED
from app.core.audit import log_audit
from app.core.auth import get_client_user, owned_or_404, require_items_access, session_employee, session_person, wo_actor
from app.core.cache import cached_read
from app.core.currency import amount_in_words, inr, money
from app.core.dates import ageing_bucket, days_after
from app.core.notifications import notify
from app.core.sheets import sheet_response
from app.documents.forms import _pre, form_pdf_response, money_voucher_spec, statement_form_spec
from app.documents.letterhead import our_party
from app.schemas.money import (BankAccountIn, CashBoxIn, MoneyIn, PaymentDecisionIn, PaymentRulesIn, RequestPayIn,
                               SiteCashExpenseIn, TransferIn)
from app.services import site_cash
from app.services import payment_requests as preq
from app.services.credit_notes import credit_totals_by_bill, credits_by_job
from app.services.crm import (
    _ledger_rows,
    invoice_overdue_days,
    norm_name,
    settled_amounts,
    settled_on,
    supplier_dict,
)
from app.services.money import (
    _doc_for,
    _doc_for_any,
    _empty_buckets,
    _settle_doc,
    account_balance,
    account_dict,
    base_currency,
    invoices_by_currency,
    job_money,
    money_entry_dict,
    next_money_number,
)
from app.services.projects import invoice_total, job_or_404, preload_pnl
from app.services.subcontract_billing import released_by_job


router = APIRouter()


@router.get("/api/reports/profit-loss")
def profit_loss_report(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "reports.view")
    base = base_currency(client)
    invoices = db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).all()
    bills = db.query(models.DBBill).filter(models.DBBill.client_id == client.id).all()
    groups = invoices_by_currency(invoices, base)

    def figures(inv_list, bill_list):
        monthly_revenue = {}
        monthly_expenses = {}
        for inv in inv_list:
            m = inv.issue_date[:7] if inv.issue_date and len(inv.issue_date) >= 7 else "Unknown"
            monthly_revenue[m] = monthly_revenue.get(m, 0) + (inv.paid or 0)
        for b in bill_list:
            m = b.issue_date[:7] if b.issue_date and len(b.issue_date) >= 7 else "Unknown"
            monthly_expenses[m] = monthly_expenses.get(m, 0) + (b.total or 0)
        all_months = sorted(set(list(monthly_revenue.keys()) + list(monthly_expenses.keys())))
        total_revenue = money(sum(monthly_revenue.values()))
        total_expenses = money(sum(monthly_expenses.values()))
        return {
            "months": all_months,
            "revenue": [money(monthly_revenue.get(m, 0)) for m in all_months],
            "expenses": [money(monthly_expenses.get(m, 0)) for m in all_months],
            "profit": [money(monthly_revenue.get(m, 0) - monthly_expenses.get(m, 0)) for m in all_months],
            "total_revenue": total_revenue,
            "total_expenses": total_expenses,
            "net_profit": money(total_revenue - total_expenses),
        }

    report = figures(groups.get(base, []), bills)
    report["currency"] = base
    report["other_currencies"] = [
        dict(figures(groups[code], []), currency=code)
        for code in sorted(groups) if code != base
    ]
    return report


@router.get("/api/reports/balance-sheet")
def balance_sheet_report(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "reports.view")
    base = base_currency(client)
    invoices = db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).all()
    bills = db.query(models.DBBill).filter(models.DBBill.client_id == client.id).all()
    groups = invoices_by_currency(invoices, base)

    def figures(inv_list, bill_list):
        collected = money(sum(inv.paid or 0 for inv in inv_list))
        outstanding = money(sum(inv.due or 0 for inv in inv_list if inv.status != "Paid"))
        bills_paid = money(sum(b.amount_paid or 0 for b in bill_list))
        bills_unpaid = money(sum((b.total or 0) - (b.amount_paid or 0) for b in bill_list))
        return {
            "assets": {"cash_collected": collected, "accounts_receivable": outstanding},
            "liabilities": {"accounts_payable": bills_unpaid},
            "equity": {"retained_earnings": money(collected - bills_paid)},
            "total_assets": money(collected + outstanding),
            "total_liabilities": bills_unpaid,
            "total_equity": money(collected - bills_paid),
        }

    report = figures(groups.get(base, []), bills)
    report["currency"] = base
    report["other_currencies"] = [
        dict(figures(groups[code], []), currency=code)
        for code in sorted(groups) if code != base
    ]
    return report


@router.get("/api/reports/cash-summary")
def cash_summary_report(request: Request, db: Session = Depends(get_db)):
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


@router.get("/api/reports/aged-receivables")
def aged_receivables(request: Request, db: Session = Depends(get_db)):
    """Outstanding balances bucketed by how late they are - the report every
    finance team asks for first."""
    client = require_items_access(request, db, "reports.view")
    base = base_currency(client)
    invoices = db.query(models.DBInvoice).filter(
        models.DBInvoice.client_id == client.id,
        models.DBInvoice.status.notin_(["Draft", "Paid", "Void"]),
    ).all()
    today = datetime.now().date()

    def figures(inv_list):
        buckets = {"current": 0.0, "1_30": 0.0, "31_60": 0.0, "61_90": 0.0, "over_90": 0.0}
        rows = []
        for inv in inv_list:
            outstanding = money(inv.due or 0)
            if outstanding <= 0:
                continue
            days = invoice_overdue_days(inv, today)
            if days == 0:
                bucket = "current"
            elif days <= 30:
                bucket = "1_30"
            elif days <= 60:
                bucket = "31_60"
            elif days <= 90:
                bucket = "61_90"
            else:
                bucket = "over_90"
            buckets[bucket] = money(buckets[bucket] + outstanding)
            rows.append({
                "number": inv.number, "contact": inv.to_contact, "due_date": inv.due_date,
                "outstanding": outstanding, "days_overdue": days, "bucket": bucket,
                # Each row carries its own currency so a mixed table can print
                # the right symbol against every line.
                "currency": ((inv.currency or "") or base).upper() or base,
            })
        rows.sort(key=lambda r: r["days_overdue"], reverse=True)
        return {
            "buckets": buckets,
            "total_outstanding": money(sum(buckets.values())),
            "invoices": rows,
        }

    groups = invoices_by_currency(invoices, base)
    report = figures(groups.get(base, []))
    report["currency"] = base
    report["other_currencies"] = [
        dict(figures(groups[code]), currency=code)
        for code in sorted(groups) if code != base
    ]
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


@router.get("/api/money/receivables")
def receivables(request: Request, db: Session = Depends(get_db)):
    """What customers owe, and how long they have owed it."""
    client = require_items_access(request, db, "bills.view_all")
    today = date.today()
    jobs = {j.id: j for j in db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id).all()}

    rows, buckets = [], _empty_buckets()
    for inv in db.query(models.DBInvoice).filter(
            models.DBInvoice.client_id == client.id).all():
        if (inv.status or "") in ("Draft", "Paid", "Cancelled", "Void"):
            continue
        outstanding = money(inv.due)
        if outstanding <= 0:
            continue
        bucket, days = ageing_bucket(inv.due_date, today)
        buckets[bucket] = money(buckets[bucket] + outstanding)
        job = jobs.get(inv.job_id)
        rows.append({
            "id": inv.id, "number": inv.number or "",
            "customer": inv.to_contact or "", "project": job.name if job else "",
            "job_id": inv.job_id,
            "issue_date": inv.issue_date or "", "due_date": inv.due_date or "",
            "total": invoice_total(inv), "paid": money(inv.paid),
            "outstanding": outstanding, "bucket": bucket,
            "days_overdue": days if (days or 0) > 0 else 0,
            "status": inv.status or "",
        })
    # A client RA bill that has been certified and not paid is owed to us
    # just as an invoice is. Aged from certification. What has already been
    # received against it comes off - a part-paid bill owes what is left.
    settled = settled_amounts(db, client.id)
    ra_credits = credit_totals_by_bill(db, client.id, "client")
    for r in db.query(models.DBRABill).filter(
            models.DBRABill.client_id == client.id,
            models.DBRABill.status == "CERTIFIED").all():
        received = settled.get(("ra_bill", r.id), 0.0)
        # What a credit note took back is no longer owed.
        outstanding = money((r.net_payable or 0) - ra_credits.get(r.id, {}).get("net", 0.0) - received)
        if outstanding <= 0:
            continue
        # Due a month after the signature, as the dashboard already reads it -
        # a bill certified this morning was being shown as overdue by noon.
        due = days_after(r.certified_at, RA_CREDIT_DAYS)
        bucket, days = ageing_bucket(due or r.certified_at, today)
        buckets[bucket] = money(buckets[bucket] + outstanding)
        job = jobs.get(r.job_id)
        rows.append({
            "id": r.id, "number": r.number or "", "kind": "RA bill",
            "customer": job.customer_name if job else "",
            "project": job.name if job else "", "job_id": r.job_id,
            "issue_date": (r.certified_at or "")[:10], "due_date": due or (r.certified_at or "")[:10],
            "total": money((r.net_payable or 0) - ra_credits.get(r.id, {}).get("net", 0.0)),
            "paid": money(received), "outstanding": outstanding,
            "doc_type": "ra_bill",
            "bucket": bucket, "days_overdue": days if (days or 0) > 0 else 0,
            "status": r.status or "",
        })
    # Retention released and claimed is owed like any certified bill.
    for rel in db.query(models.DBRetentionRelease).filter(
            models.DBRetentionRelease.client_id == client.id,
            models.DBRetentionRelease.side == "client",
            models.DBRetentionRelease.status == "CERTIFIED").all():
        received = settled.get(("retention_release", rel.id), 0.0)
        outstanding = money((rel.net_amount or 0) - received)
        if outstanding <= 0:
            continue
        due = days_after(rel.release_on, RA_CREDIT_DAYS)
        bucket, days = ageing_bucket(due or rel.release_on, today)
        buckets[bucket] = money(buckets[bucket] + outstanding)
        job = jobs.get(rel.job_id)
        rows.append({
            "id": rel.id, "number": rel.number or "", "kind": "Retention release",
            "customer": job.customer_name if job else "",
            "project": job.name if job else "", "job_id": rel.job_id,
            "issue_date": rel.release_on or "", "due_date": due or rel.release_on or "",
            "total": money(rel.net_amount), "paid": money(received), "outstanding": outstanding,
            "doc_type": "retention_release",
            "bucket": bucket, "days_overdue": days if (days or 0) > 0 else 0,
            "status": rel.status or "",
        })
    for r in rows:
        r.setdefault("kind", "Invoice")

    rows.sort(key=lambda r: -(r["days_overdue"] or 0))
    overdue = money(sum(r["outstanding"] for r in rows if r["bucket"] != "Not due"))
    return {
        "invoices": rows, "buckets": buckets,
        "summary": {
            "owed": money(sum(r["outstanding"] for r in rows)),
            "overdue": overdue,
            "invoices": len(rows),
            "worst_days": max([r["days_overdue"] for r in rows] or [0]),
            "over_90": buckets["90+"],
        },
    }


@router.get("/api/money/payables")
def payables(request: Request, db: Session = Depends(get_db)):
    """What the business owes: supplier bills, and bills it has certified.

    A certified RA bill is a promise already made - the work was measured and
    somebody signed for it - so it belongs here beside the supplier invoices
    rather than out of sight on the subcontract screen.
    """
    client = require_items_access(request, db, "bills.view_all")
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
    for r in db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client.id,
            models.DBSubBill.status == "CERTIFIED").all():
        outstanding = money((r.net_payable or 0) - sub_credits.get(r.id, {}).get("net", 0.0)
                            - settled.get(("sub_bill", r.id), 0.0))
        if outstanding <= 0:
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
    return {
        "bills": rows, "buckets": buckets,
        "summary": {
            "owed": money(sum(r["outstanding"] for r in rows)),
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
def retention_register(request: Request, db: Session = Depends(get_db)):
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
def receivables_export(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    data = receivables(request, db)
    b = data["buckets"]
    rows = [(r["number"], r["customer"], r["project"], r["issue_date"],
             r["due_date"], r["total"], r["paid"], r["outstanding"],
             r["bucket"], r["days_overdue"]) for r in data["invoices"]]
    return sheet_response(
        ("Invoice", "Customer", "Project", "Issued", "Due", "Total", "Paid",
         "Outstanding", "Age", "Days overdue"),
        rows, "receivables.xlsx",
        preamble=[("WHAT WE ARE OWED", client.company_name or ""),
                  ("As at", date.today().strftime("%Y-%m-%d")),
                  (),
                  ("Not due", b["Not due"], "0-30", b["0-30"], "31-60", b["31-60"]),
                  ("61-90", b["61-90"], "90+", b["90+"]),
                  ()],
        closing=[(), ("Total owed", "", "", "", "", "", "",
                      data["summary"]["owed"])])


@router.get("/api/money/retention.xlsx")
def retention_export(request: Request, db: Session = Depends(get_db)):
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
def list_bank_accounts(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    rows = db.query(models.DBBankAccount).filter(
        models.DBBankAccount.client_id == client.id).order_by(models.DBBankAccount.id).all()
    out = []
    for a in rows:
        d = account_dict(a)
        d["balance"] = account_balance(db, client.id, a)
        out.append(d)
    return {"accounts": out}


@router.post("/api/bank-accounts")
def create_bank_account(body: BankAccountIn, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Name the account - \"SBI current\", \"Site cash\".")
    kind = body.kind if body.kind in ("Bank", "Cash") else "Bank"
    a = models.DBBankAccount(
        client_id=client.id, name=name, kind=kind, bank_name=(body.bank_name or "").strip(),
        account_no=(body.account_no or "").strip(), ifsc=(body.ifsc or "").strip().upper(),
        opening_balance=money(body.opening_balance or 0),
        opening_date=(body.opening_date or datetime.now().strftime("%Y-%m-%d")))
    db.add(a)
    db.commit()
    db.refresh(a)
    return account_dict(a)


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
    on = (body.paid_on or datetime.now().strftime("%Y-%m-%d"))[:10]
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
        owed = money(worth - settled_on(db, client.id, doc_type, doc.id))
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

    approved = None
    if body.request_id:
        approved = preq.use_for_payment(db, client.id, body.request_id, doc_type, doc.id if doc else None, amount, party_name, job_id)
    elif direction == "OUT" and preq.needs_request(db, client.id, session_employee(request, db), amount):
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
def money_voucher_pdf(entry_id: int, request: Request, db: Session = Depends(get_db)):
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
def payment_rules(request: Request, db: Session = Depends(get_db)):
    client, emp = _request_reader(request, db)
    rules = preq.approval_rules(db, client.id)
    return {**rules, "can_check": preq.can_check(emp), "can_release": preq.can_release(emp), "master": emp is None,
            "me": emp.id if emp is not None else None}


@router.put("/api/payment-requests/rules")
def save_payment_rules(body: PaymentRulesIn, request: Request, db: Session = Depends(get_db)):
    """Whether payments wait for approval - the Master's decision."""
    client, emp = session_person(request, db)
    if emp is not None:
        raise HTTPException(403, "Only the Master sets how payments are approved.")
    if body.md_above is not None and body.free_below is not None and body.md_above and body.md_above < body.free_below:
        raise HTTPException(400, "The MD's limit cannot be below the amount that needs no approval.")
    preq.save_rules(db, client.id, body.on, body.free_below, body.md_above)
    log_audit(db, client.id, "payment_rules_changed", "settings", None, "payment approval",
              "%s; free below %s; MD above %s" % ("on" if body.on else "off", inr(body.free_below or 0), inr(body.md_above or 0)),
              request)
    db.commit()
    return {**preq.approval_rules(db, client.id), "message": "Payment approval %s." % ("on" if body.on else "off")}


@router.get("/api/payment-requests")
def list_payment_requests(request: Request, status: str = "", db: Session = Depends(get_db)):
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
    out = [preq.request_dict(r, accounts, jobs) for r in rows]
    by = lambda *s: money(sum(r["amount"] for r in out if r["status"] in s))
    return {"requests": out, "summary": {"with_accounts": by("PENDING"), "with_md": by("AWAITING_MD"),
                                         "to_pay": by("APPROVED"), "open": len([r for r in out if r["status"] in preq.OPEN])}}


@router.post("/api/payment-requests")
def raise_payment_request(body: MoneyIn, request: Request, db: Session = Depends(get_db)):
    """Ask for a payment to be approved: a bill or part of it, an advance on account, or an expense."""
    client, _, actor_name = wo_actor(request, db, "bills.pay")
    r = preq.raise_request(db, client, session_employee(request, db), actor_name, body)
    log_audit(db, client.id, "payment_requested", r.doc_type, r.doc_id or 0, r.number,
              "%s %s %s" % (r.party_name, inr(r.amount), r.doc_number), request)
    db.commit()
    return {"ok": True, "request": preq.request_dict(r),
            "message": "%s: %s to %s sent for approval." % (r.number, inr(r.amount), r.party_name)}


@router.post("/api/payment-requests/{request_id}/decide")
def decide_payment_request(request_id: int, body: PaymentDecisionIn, request: Request, db: Session = Depends(get_db)):
    client, emp = session_person(request, db)
    return _decide_payment(db, client, emp, request_id, body.decision, body.note, request)


def _decide_payment(db, client, emp, request_id, decision, note, request):
    from app.services.hr import employee_name
    who = employee_name(emp) if emp is not None else (client.contact_name or "Master")
    r = preq.request_or_404(db, client.id, request_id)
    message = preq.decide(db, client, emp, who, r, decision, note)
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
    money_body = MoneyIn(
        doc_type=r.doc_type, doc_id=r.doc_id, amount=body.amount or r.amount, paid_on=body.paid_on or "",
        mode=body.mode or r.mode or "Bank transfer", reference=body.reference or "",
        account_id=body.account_id or r.account_id, note=r.note or "", direction="OUT", party_type=r.party_type,
        party_name=r.party_name, job_id=r.job_id, head=r.head, request_id=r.id)
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
def site_cash_view(request: Request, account_id: int = 0, status: str = "", db: Session = Depends(get_db)):
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
    who = employee_name(emp) if emp is not None else (client.contact_name or "Master")
    x = site_cash.submit(db, client, emp, who, box, body)
    log_audit(db, client.id, "site_cash_spent", "site_cash", x.id, x.number,
              "%s %s %s" % (x.head, inr(x.amount), x.paid_to), request)
    db.commit()
    return {"ok": True, "expense": site_cash.expense_dict(x),
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
    who = employee_name(emp) if emp is not None else (client.contact_name or "Master")
    x = site_cash.expense_or_404(db, client.id, expense_id)
    message = site_cash.decide(db, client, emp, who, x, decision, note)
    log_audit(db, client.id, "site_cash_" + ("approved" if decision == "approve" else "rejected"), "site_cash",
              x.id, x.number, message, request)
    db.commit()
    return {"ok": True, "expense": site_cash.expense_dict(x), "message": message}


@router.get("/api/site-cash/boxes/{account_id}/statement.pdf")
def cash_box_statement(account_id: int, request: Request, date_from: str = "", date_to: str = "",
                       db: Session = Depends(get_db)):
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


@router.get("/api/money/heads")
def money_heads(request: Request, db: Session = Depends(get_db)):
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
    on = (body.paid_on or datetime.now().strftime("%Y-%m-%d"))[:10]
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
    e.voided, e.void_reason = True, reason[:300]
    booked = site_cash.expense_for_entry(db, e.id)
    if booked is not None and booked.status == "APPROVED":
        booked.status, booked.entry_id, booked.checked_by_name, booked.checked_at = "SUBMITTED", None, "", ""
    paid_for = preq.request_for_entry(db, e.id)
    if paid_for is not None and paid_for.status == "PAID":
        paid_for.status, paid_for.entry_id = "APPROVED", None     # still approved; the payment was the mistake
    if e.pair_id:
        # A transfer is undone whole: money cannot have left one account and not arrived in the other.
        other = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.id == e.pair_id,
                                                     models.DBMoneyEntry.client_id == client.id).first()
        if other is not None and not other.voided:
            other.voided, other.void_reason = True, reason[:300]
    db.flush()
    if e.doc_id and e.doc_type != "on_account":
        doc, worth, *_ = _doc_for_any(db, client.id, e.doc_type, e.doc_id)
        _settle_doc(db, client.id, e.doc_type, doc, worth, "")
    log_audit(db, client.id, "money_voided", e.doc_type, e.doc_id or 0, e.number, reason, request)
    db.commit()
    return {"ok": True, "message": "%s voided." % e.number}


@router.get("/api/money/entries")
def list_money(request: Request, direction: str = "", party: str = "", job_id: int = 0,
               date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
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
def ledger_parties(request: Request, party_type: str = "", db: Session = Depends(get_db)):
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
                     date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
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
               db: Session = Depends(get_db)):
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


def cash_book(db, client_id, account, date_from="", date_to=""):
    """Every movement through one account (or all of them), in date order, with the balance after each."""
    q = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.voided.is_(False))
    q = q.filter(models.DBMoneyEntry.account_id == account.id) if account else q
    entries = q.order_by(models.DBMoneyEntry.paid_on, models.DBMoneyEntry.id).all()
    balance = money(account.opening_balance) if account else 0.0
    rows = []
    for e in entries:
        signed = e.amount if e.direction == "IN" else -e.amount
        if date_from and (e.paid_on or "") < date_from:
            balance = money(balance + signed)
            continue
        if date_to and (e.paid_on or "") > date_to:
            continue
        opening_row = balance if not rows else None
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
def doc_outstanding(doc_type: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    """What is still owed on one bill - for the payment box to open with."""
    client = require_items_access(request, db, "bills.view_all")
    doc, worth = _doc_for_any(db, client.id, doc_type, doc_id)
    got = settled_on(db, client.id, doc_type, doc_id)
    if doc_type in ("ra_bill", "sub_bill") and doc.status == "PAID" and not got:
        got = worth
    if doc_type == "supplier_bill":
        got = max(got, money(doc.amount_paid or 0))
    return {"number": doc.number, "worth": worth, "settled": got,
            "outstanding": money(max(0.0, worth - got)),
            "entries": [money_entry_dict(e) for e in db.query(models.DBMoneyEntry).filter(
                models.DBMoneyEntry.client_id == client.id,
                models.DBMoneyEntry.doc_type == doc_type,
                models.DBMoneyEntry.doc_id == doc_id).order_by(models.DBMoneyEntry.id).all()]}


@router.get("/api/ledger/statement.pdf")
def ledger_statement_pdf(request: Request, party_type: str, party: str, date_from: str = "", date_to: str = "",
                         db: Session = Depends(get_db)):
    """The office's copy of a party's statement, to send them."""
    client = require_items_access(request, db, "bills.view_all")
    s = ledger_statement(request, party_type, party, date_from, date_to, db)
    label = {"client": "Client", "contractor": "Sub Contractor", "supplier": "Supplier"}.get(party_type, "Party")
    return form_pdf_response(statement_form_spec(client, party, label, s, date_from, date_to, db=db), "statement_" + party)


@router.get("/api/money/payables.xlsx")
def payables_export(request: Request, db: Session = Depends(get_db)):
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
                         date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
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
