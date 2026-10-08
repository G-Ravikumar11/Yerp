"""The client billing endpoints."""
import io
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.client_billing import RA_EDITABLE, VO_TRANSITIONS
from app.core.audit import log_audit
from app.core.auth import require_erp_read, require_items_access, wo_actor
from app.core.currency import inr, money, unit_rate
from app.core.notifications import notify
from app.core.sheets import sheet_response
from app.documents.forms import form_pdf_response, ra_form_spec
from app.schemas.client_billing import RAActionIn, RABillIn, VariationIn
from app.services.client_billing import (
    _ra_action,
    apply_variation,
    billed_qty_to_date,
    claimable_lines,
    measured_to_date,
    next_vo_number,
    order_variations,
    over_measured_lines,
    ra_bill_dict,
    ra_bill_or_404,
    recost_ra_bill,
    recost_variation,
    refuse_unapproved_order,
    vo_dict,
    vo_or_404,
    write_ra_bill_lines,
)
from app.services.invoicing import einvoice_payload
from app.services.subcontract_billing import past_tense
from app.services.subcontract_orders import work_order_or_404


router = APIRouter()


@router.post("/api/ra-bills")
def raise_ra_bill(body: RABillIn, request: Request, db: Session = Depends(get_db)):
    """Draw up the next bill on an order.

    Nothing is typed. The bill is what has been measured to date minus what
    earlier bills already claimed, which is the one calculation nobody should
    be doing on paper.
    """
    client, actor_id, actor_name = wo_actor(request, db, "billing.manage")
    wo = work_order_or_404(db, client.id, body.work_order_id)
    if (wo.status or "") == "Draft":
        raise HTTPException(409, "Place the order before billing against it.")
    refuse_unapproved_order(wo, "billed")

    open_bill = db.query(models.DBRABill).filter(
        models.DBRABill.work_order_id == wo.id,
        models.DBRABill.status.in_(("DRAFT", "SUBMITTED"))).first()
    if open_bill:
        raise HTTPException(
            409, "%s is still open on this order. Finish or cancel it before "
                 "raising another - two live bills claiming the same "
                 "measurements is how work gets paid for twice." % open_bill.number)

    measured = measured_to_date(db, wo.id)
    billed = billed_qty_to_date(db, wo.id)
    lines = db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == wo.id).all()

    claimable = claimable_lines(db, wo)
    if not claimable:
        raise HTTPException(
            409, "Nothing has been measured since the last bill. Record the "
                 "work in the measurement book first.")

    seq = (db.query(func.max(models.DBRABill.sequence)).filter(
        models.DBRABill.work_order_id == wo.id).scalar() or 0) + 1
    bill = models.DBRABill(
        client_id=client.id, work_order_id=wo.id, job_id=wo.job_id,
        number="%s/RA-%02d" % (wo.number or "WO", seq), sequence=seq,
        period_from=(body.period_from or "").strip(),
        period_to=(body.period_to or datetime.now().strftime("%Y-%m-%d")),
        status="DRAFT",
        previously_billed=money(sum(
            money(billed.get(l.id, 0.0)) * unit_rate(l.rate) for l in lines)),
        retention_percent=body.retention_percent if body.retention_percent is not None else 5.0,
        advance_recovery=money(body.advance_recovery or 0),
        other_deductions=money(body.other_deductions or 0),
        deduction_notes=(body.deduction_notes or "").strip(),
        tax_percent=body.tax_percent if body.tax_percent is not None else 18.0,
        tds_percent=body.tds_percent if body.tds_percent is not None else 1.0)
    db.add(bill)
    db.flush()

    write_ra_bill_lines(db, bill, claimable)
    log_audit(db, client.id, "ra_bill_raised", "ra_bill", bill.id, bill.number,
              "%s, %d line(s)" % (wo.number, len(claimable)), request)
    db.commit()
    db.refresh(bill)
    return {"bill": ra_bill_dict(db, bill, detail=True),
            "message": "%s drawn up for %s." % (bill.number, inr(bill.this_bill))}


@router.get("/api/ra-bills")
def list_ra_bills(request: Request, work_order_id: int = 0, status: str = "",
                  db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBRABill).filter(models.DBRABill.client_id == client.id)
    if work_order_id:
        q = q.filter(models.DBRABill.work_order_id == work_order_id)
    if status:
        q = q.filter(models.DBRABill.status == status.upper())
    rows = [ra_bill_dict(db, b) for b in q.order_by(models.DBRABill.id.desc()).limit(300).all()]
    live = [r for r in rows if r["status"] not in ("CANCELLED",)]
    return {
        "bills": rows,
        "summary": {
            "bills": len(rows),
            "awaiting_certification": len([r for r in rows if r["status"] == "SUBMITTED"]),
            "certified_unpaid": money(sum(r["net_payable"] for r in rows
                                          if r["status"] == "CERTIFIED")),
            "claimed": money(sum(r["this_bill"] for r in live)),
            "retention_held": money(sum(r["retention_amount"] for r in live)),
            "paid": money(sum(r["net_payable"] for r in rows if r["status"] == "PAID")),
        },
    }


@router.get("/api/ra-bills/{bill_id}")
def get_ra_bill(bill_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return {"bill": ra_bill_dict(db, ra_bill_or_404(db, client.id, bill_id), detail=True)}


@router.put("/api/ra-bills/{bill_id}")
def update_ra_bill(bill_id: int, body: RABillIn, request: Request,
                   db: Session = Depends(get_db)):
    """The deductions are a judgement; the quantities are not, so only the
    deductions can be changed here."""
    client, actor_id, actor_name = wo_actor(request, db, "billing.manage")
    bill = ra_bill_or_404(db, client.id, bill_id)
    if bill.status not in RA_EDITABLE:
        raise HTTPException(
            409, "%s is %s and cannot be changed." % (bill.number, bill.status.lower()))
    if body.retention_percent is not None:
        bill.retention_percent = body.retention_percent
    if body.tax_percent is not None:
        bill.tax_percent = body.tax_percent
    if body.tds_percent is not None:
        bill.tds_percent = body.tds_percent
    bill.advance_recovery = money(body.advance_recovery or 0)
    bill.other_deductions = money(body.other_deductions or 0)
    bill.deduction_notes = (body.deduction_notes or "").strip()
    bill.period_from = (body.period_from or bill.period_from or "").strip()
    bill.period_to = (body.period_to or bill.period_to or "").strip()
    recost_ra_bill(db, bill)
    db.commit()
    db.refresh(bill)
    return {"bill": ra_bill_dict(db, bill, detail=True), "message": "Saved."}


@router.post("/api/ra-bills/{bill_id}/submit")
def submit_ra_bill(bill_id: int, body: RAActionIn, request: Request,
                   db: Session = Depends(get_db)):
    return _ra_action(bill_id, "SUBMIT", body, request, db)


@router.post("/api/ra-bills/{bill_id}/certify")
def certify_ra_bill(bill_id: int, body: RAActionIn, request: Request,
                    db: Session = Depends(get_db)):
    """Certification is a separate right: the person who measured the work
    should not be the person who certifies payment for it."""
    return _ra_action(bill_id, "CERTIFY", body, request, db, "subcontracts.approve")


@router.post("/api/ra-bills/{bill_id}/reject")
def reject_ra_bill(bill_id: int, body: RAActionIn, request: Request,
                   db: Session = Depends(get_db)):
    return _ra_action(bill_id, "REJECT", body, request, db, "subcontracts.approve")


@router.post("/api/ra-bills/{bill_id}/pay")
def pay_ra_bill(bill_id: int, body: RAActionIn, request: Request,
                db: Session = Depends(get_db)):
    return _ra_action(bill_id, "PAY", body, request, db, "bills.pay")


@router.post("/api/ra-bills/{bill_id}/cancel")
def cancel_ra_bill(bill_id: int, body: RAActionIn, request: Request,
                   db: Session = Depends(get_db)):
    return _ra_action(bill_id, "CANCEL", body, request, db)


@router.get("/api/ra-bills/{bill_id}/export.xlsx")
def ra_bill_xlsx(bill_id: int, request: Request, db: Session = Depends(get_db)):
    """The bill as it is presented for certification."""
    client = require_erp_read(request, db)
    bill = ra_bill_or_404(db, client.id, bill_id)
    d = ra_bill_dict(db, bill, detail=True)
    varied = order_variations(db, bill)
    rows = [[l["fg_code"], l["description"], l["uom"], l["ordered_qty"],
             l["measured_to_date"], l["previously_billed_qty"], l["this_bill_qty"],
             l["rate"], l["amount"]] for l in d["lines"]]
    return sheet_response(
        ["Item", "Description", "UOM", "Ordered", "Measured to date",
         "Previously billed", "This bill", "Rate", "Amount"],
        rows, "ra_bill_%s.xlsx" % re.sub(r"[^A-Za-z0-9]+", "_", d["number"]),
        preamble=[["Running Account Bill", "", "", "", "", "", "", "", client.company_name or ""],
                  ["No: " + d["number"] + "   (" + d["status"] + ")"],
                  ["Work order: " + d["work_order"]],
                  ["Project: " + d["project"]],
                  ["Period to: " + d["period_to"]]]
                 + ([["Order value as first placed: %s; variations agreed: %s (%s); as varied: %s" % (
                     inr(varied["original"]), inr(sum(x["value"] for x in varied["variations"])),
                     ", ".join(x["number"] for x in varied["variations"]), inr(varied["varied"]))]] if varied else [])
                 + [[]],
        closing=[[], ["", "", "", "", "", "", "", "This bill", d["this_bill"]],
                 ["", "", "", "", "", "", "", "Retention @ %s%%" % d["retention_percent"],
                  -d["retention_amount"]],
                 ["", "", "", "", "", "", "", "Advance recovery", -d["advance_recovery"]],
                 ["", "", "", "", "", "", "", "Other deductions", -d["other_deductions"]],
                 ["", "", "", "", "", "", "", "GST @ %s%%" % d["tax_percent"], d["tax_amount"]],
                 ["", "", "", "", "", "", "", "TDS @ %s%%" % d["tds_percent"], -d["tds_amount"]],
                 ["", "", "", "", "", "", "", "Net payable", d["net_payable"]]])


@router.get("/api/variations")
def list_variations(request: Request, work_order_id: int = 0,
                    db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBVariationOrder).filter(
        models.DBVariationOrder.client_id == client.id)
    if work_order_id:
        q = q.filter(models.DBVariationOrder.work_order_id == work_order_id)
    rows = [vo_dict(db, v) for v in q.order_by(
        models.DBVariationOrder.id.desc()).limit(200).all()]
    live = [r for r in rows if r["status"] not in ("CANCELLED", "REJECTED")]
    return {
        "variations": rows,
        "summary": {
            "raised": len(rows),
            "awaiting_approval": len([r for r in rows if r["status"] == "SUBMITTED"]),
            "approved_value": money(sum(r["value"] for r in rows
                                        if r["status"] == "APPROVED")),
            "pending_value": money(sum(r["value"] for r in live
                                       if r["status"] != "APPROVED")),
        },
    }


@router.get("/api/variations/suggest/{work_order_id}")
def suggest_variation(work_order_id: int, request: Request,
                      db: Session = Depends(get_db)):
    """What the app would raise, without raising it.

    The screen asks this to decide whether to offer the button at all, so a
    site with nothing over-run is never nagged about a variation it does not
    need.
    """
    client = require_erp_read(request, db)
    wo = work_order_or_404(db, client.id, work_order_id)
    lines = over_measured_lines(db, wo)
    return {"lines": lines, "value": money(sum(l["amount"] for l in lines)),
            "count": len(lines)}


@router.post("/api/variations")
def create_variation(body: VariationIn, request: Request,
                     db: Session = Depends(get_db)):
    """Draw one up - from the measurement book unless lines are supplied."""
    client, actor_id, actor_name = wo_actor(request, db, "billing.manage")
    wo = work_order_or_404(db, client.id, body.work_order_id)
    if (wo.status or "") == "Draft":
        raise HTTPException(409, "Vary the order after it has been placed, not before.")

    supplied = body.lines
    origin = "manual" if supplied else "measured"
    rows = supplied if supplied else over_measured_lines(db, wo)
    if not rows:
        raise HTTPException(
            409, "Nothing is over the ordered quantity, so there is nothing to vary. "
                 "Measure the extra work first, or add the lines yourself.")

    number, seq = next_vo_number(db, wo)
    vo = models.DBVariationOrder(
        client_id=client.id, work_order_id=wo.id, job_id=wo.job_id,
        number=number, sequence=seq, status="DRAFT", origin=origin,
        reason=(body.reason or "").strip(),
        raised_by=actor_id, raised_by_name=actor_name)
    db.add(vo)
    db.flush()

    for i, r in enumerate(rows):
        extra = money(r.get("extra_qty") or 0)
        rate = unit_rate(r.get("rate") or 0)
        if not extra:
            continue
        db.add(models.DBVariationLine(
            variation_order_id=vo.id, line_id=r.get("line_id"),
            fg_code=(r.get("fg_code") or "")[:120],
            description=(r.get("description") or "")[:500],
            uom=(r.get("uom") or "")[:40],
            ordered_qty=money(r.get("ordered_qty") or 0),
            measured_qty=money(r.get("measured_qty") or 0),
            extra_qty=extra, rate=rate, amount=money(extra * rate),
            display_order=i))
    db.flush()
    recost_variation(db, vo)
    log_audit(db, client.id, "variation_raised", "work_order", wo.id, wo.number or "",
              "%s %s %s" % (number, origin, inr(vo.value)), request)
    db.commit()
    db.refresh(vo)
    return {"ok": True, "variation": vo_dict(db, vo, detail=True),
            "message": ("%s drawn up from the measurement book - %s of extra work."
                        % (number, inr(vo.value)) if origin == "measured"
                        else "%s created." % number)}


@router.get("/api/variations/{vo_id}")
def get_variation(vo_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return vo_dict(db, vo_or_404(db, client.id, vo_id), detail=True)


@router.post("/api/variations/{vo_id}/{action}")
def act_on_variation(vo_id: int, action: str, request: Request, body: dict = None,
                     db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, "billing.manage")
    vo = vo_or_404(db, client.id, vo_id)
    move = (action or "").upper()
    allowed = VO_TRANSITIONS.get(vo.status or "DRAFT", {})
    if move not in allowed:
        raise HTTPException(
            409, "A %s variation cannot be %s." % ((vo.status or "draft").lower(),
                                                    past_tense(move)))
    body = body or {}
    if move == "APPROVE":
        # Approving raises the contract value, so it is the approver's right
        # rather than the raiser's. Whoever may approve a subcontract may
        # approve a change to one.
        require_items_access(request, db, "subcontracts.approve")
        vo.approved_by_name = actor_name
        vo.approved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not vo.applied_at:
            apply_variation(db, vo)
    if move == "REJECT":
        reason = (body.get("comments") or "").strip()
        if not reason:
            raise HTTPException(400, "Say why it is going back.")
        vo.rejection_reason = reason

    was, vo.status = vo.status, allowed[move]
    vo.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_audit(db, client.id, "variation_%s" % move.lower(), "work_order",
              vo.work_order_id, vo.number or "", "%s -> %s" % (was, vo.status), request)
    db.commit()
    db.refresh(vo)
    if move in ("SUBMIT", "APPROVE"):
        notify(db, client.id, "variation_submitted" if move == "SUBMIT" else "variation_approved",
               ("%s is waiting for approval" if move == "SUBMIT" else "%s agreed") % vo.number,
               "%s of extra work." % inr(vo.value), view="measurement-view",
               ref_type="variation", ref_id=vo.id, severity="action" if move == "SUBMIT" else "money")
        db.refresh(vo)
    return {"ok": True, "variation": vo_dict(db, vo, detail=True),
            "message": "%s is now %s." % (vo.number, vo.status.lower())}


@router.delete("/api/variations/{vo_id}")
def delete_variation(vo_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    vo = vo_or_404(db, client.id, vo_id)
    if (vo.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Only a draft can be deleted. Cancel it instead.")
    db.query(models.DBVariationLine).filter(
        models.DBVariationLine.variation_order_id == vo.id).delete()
    db.delete(vo)
    db.commit()
    return {"ok": True, "message": "Draft removed."}


@router.get("/api/ra-bills/{bill_id}/einvoice")
def einvoice_check(bill_id: int, request: Request, db: Session = Depends(get_db)):
    """Whether this bill can be e-invoiced, and if not, what is missing."""
    client = require_erp_read(request, db)
    bill = ra_bill_or_404(db, client.id, bill_id)
    payload, problems = einvoice_payload(db, client, bill)
    return {"ready": not problems, "missing": problems, "payload": payload if not problems else None}


@router.get("/api/ra-bills/{bill_id}/einvoice.json")
def einvoice_download(bill_id: int, request: Request, db: Session = Depends(get_db)):
    """The file to upload to the Invoice Registration Portal."""
    client = require_erp_read(request, db)
    bill = ra_bill_or_404(db, client.id, bill_id)
    payload, problems = einvoice_payload(db, client, bill)
    if problems:
        raise HTTPException(409, "Not ready for the portal - still needed: " + "; ".join(problems) + ".")
    name = re.sub(r"[^A-Za-z0-9]+", "_", bill.number or "ra_bill")
    body = json.dumps([payload], indent=2, ensure_ascii=False).encode("utf-8")
    return StreamingResponse(io.BytesIO(body), media_type="application/json",
                             headers={"Content-Disposition": 'attachment; filename="einvoice_%s.json"' % name})


@router.get("/api/ra-bills/{bill_id}/document.pdf")
def ra_bill_pdf(bill_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    bill = ra_bill_or_404(db, client.id, bill_id)
    return form_pdf_response(ra_form_spec(db, client, bill), bill.number)
