"""The procurement endpoints."""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.approvals import PO_APPROVED, PO_AWAITING_APPROVAL, PO_REJECTED
from app.constants.common import GRN_EDITABLE, PURCHASE_ORDER_STATUSES
from app.core.audit import log_audit
from app.core.auth import require_erp_read, require_items_access, session_employee, wo_actor
from app.core.currency import amount_in_words, inr, money, tax_percent_of, unit_rate
from app.core.dates import days_after
from app.core.serials import allocate_grn_number, allocate_po_number, next_sequence_number
from app.core.sheets import sheet_response
from app.documents.forms import _pre, form_pdf_response, po_form_spec
from app.documents.letterhead import our_party
from app.routers.employee_portal import employee_create_purchase_order
from app.schemas.procurement import AwardIn, GRNActionIn, GRNIn, GRNUpdateIn, QuoteIn, RfqIn, SupplierIn
from app.services.client_billing import received_to_date
from app.services.crm import norm_name, supplier_dict
from app.services.procurement import (
    _apply_supplier,
    _make_rfq,
    _rfq_lines,
    apply_order_fields,
    billed_against_po,
    comparative_statement,
    grn_actor,
    grn_apply,
    grn_dict,
    grn_or_404,
    match_verdict,
    next_supplier_code,
    order_is_committed,
    purchase_order_or_404,
    purchase_order_to_dict,
    recost_grn,
    rfq_dict,
    rfq_or_404,
    supplier_payment_days,
)
from app.services.stores import material_required
from app.services.subcontract_orders import work_order_or_404


router = APIRouter()


@router.get("/api/purchase-orders")
def list_purchase_orders(request: Request, job_id: int = 0, status: str = "",
                         db: Session = Depends(get_db)):
    client = require_items_access(request, db, ("purchase.manage", "bills.view_all", "stores.receive"))
    query = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.client_id == client.id)
    if job_id:
        query = query.filter(models.DBPurchaseOrder.job_id == job_id)
    if status:
        query = query.filter(models.DBPurchaseOrder.status == status)
    orders = query.order_by(models.DBPurchaseOrder.id.desc()).limit(300).all()
    return {"orders": [purchase_order_to_dict(db, o) for o in orders]}


@router.get("/api/purchase-orders/{order_id}")
def get_purchase_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, ("purchase.manage", "bills.view_all", "stores.receive"))
    order = purchase_order_or_404(db, client.id, order_id)
    row = purchase_order_to_dict(db, order, include_chain=True)
    row["our"] = our_party(db, client.id)
    row["amount_in_words"] = amount_in_words(order.total or 0)
    job = db.query(models.DBJob).filter(models.DBJob.id == order.job_id).first() if order.job_id else None
    row["deliver_to"] = job.site_address if job else ""
    return row


@router.post("/api/purchase-orders")
def create_purchase_order(request: Request, body: dict = None,
                          db: Session = Depends(get_db)):
    client = require_items_access(request, db, "purchase.manage")
    # Staff raise an order through the same route as everyone else, and theirs
    # goes for approval the moment it exists - the owner's is theirs to place.
    if session_employee(request, db):
        return employee_create_purchase_order(request, body, db)
    body = body or {}
    order = models.DBPurchaseOrder(
        client_id=client.id, number=allocate_po_number(db, client.id), status="Draft")
    apply_order_fields(db, client.id, order, body)
    db.add(order)
    db.flush()
    for li in (body.get("line_items") or [])[:50]:
        db.add(models.DBPurchaseOrderLineItem(
            order_id=order.id, description=(li.get("description") or "")[:500],
            item_code=(li.get("item_code") or "")[:60],
            uom=(li.get("uom") or "")[:20],
            qty=float(li.get("qty") or 1), price=float(li.get("price") or 0),
            tax_rate=li.get("tax_rate") or "0%"))
    log_audit(db, client.id, "purchase_order_created", "purchase_order", order.id,
              order.number, f"{order.supplier_name}, {order.total}", request)
    db.commit()
    db.refresh(order)
    return purchase_order_to_dict(db, order, include_chain=True)


@router.put("/api/purchase-orders/{order_id}")
def update_purchase_order(order_id: int, request: Request, body: dict = None,
                          db: Session = Depends(get_db)):
    client = require_items_access(request, db, "purchase.manage")
    staff = session_employee(request, db)
    order = purchase_order_or_404(db, client.id, order_id)
    if order.approval_status == "pending":
        raise HTTPException(status_code=409,
                            detail="This order is with an approver and cannot be changed.")
    wanted = (body or {}).get("status")
    if staff and wanted in (PO_AWAITING_APPROVAL, PO_APPROVED, PO_REJECTED) and wanted != order.status:
        raise HTTPException(403, "Approval is given in Approvals, by whoever the order is "
                                 "sent to - not by changing its status.")
    before = (order.supplier_name, money(order.total or 0))
    apply_order_fields(db, client.id, order, body or {})
    # An approved order that a member of staff then changes is a different
    # order from the one that was approved, and goes back to be approved again.
    if staff and order.approval_status == "approved" and \
            before != (order.supplier_name, money(order.total or 0)):
        order.approval_status, order.status, order.current_approval_step = "none", "Draft", 0

    # An order that was promised and then was not has to be able to say so.
    # Without this there was no way to cancel one at all, and a withdrawn
    # commitment went on counting against the project's cost for ever.
    wanted = (body or {}).get("status")
    if wanted in PURCHASE_ORDER_STATUSES and wanted != order.status:
        was, order.status = order.status, wanted
        log_audit(db, client.id, "purchase_order_status", "purchase_order", order.id,
                  order.number or "", "%s -> %s" % (was, wanted), request)

    db.commit()
    return purchase_order_to_dict(db, order, include_chain=True)


@router.delete("/api/purchase-orders/{order_id}")
def delete_purchase_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "purchase.manage")
    order = purchase_order_or_404(db, client.id, order_id)
    if db.query(models.DBBill).filter(models.DBBill.purchase_order_id == order.id).count():
        raise HTTPException(
            status_code=409,
            detail="A bill has been matched to this order. Cancel it instead of deleting it.")
    # Goods received against it are in the store; the receipt and the stock
    # it put there would be left hanging off an order that no longer exists.
    if db.query(models.DBGoodsReceipt).filter(
            models.DBGoodsReceipt.purchase_order_id == order.id,
            models.DBGoodsReceipt.status != "CANCELLED").count():
        raise HTTPException(
            status_code=409,
            detail="Goods have been received against this order. Cancel it instead of deleting it.")
    db.query(models.DBPurchaseOrderLineItem).filter(
        models.DBPurchaseOrderLineItem.order_id == order.id).delete()
    db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == "purchase_order",
        models.DBApprovalChain.entity_id == order.id).delete()
    log_audit(db, client.id, "purchase_order_deleted", "purchase_order", order.id,
              order.number, "", request)
    db.delete(order)
    db.commit()
    return {"ok": True}


@router.get("/api/purchase-orders/{po_id}/export.xlsx")
def purchase_order_xlsx(po_id: int, request: Request, db: Session = Depends(get_db)):
    """One purchase order, as sent to the supplier."""
    client = require_items_access(request, db, ("purchase.manage", "bills.view_all", "stores.receive"))
    po = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == po_id,
        models.DBPurchaseOrder.client_id == client.id).first()
    if not po:
        raise HTTPException(404, "Purchase order not found")

    lines = db.query(models.DBPurchaseOrderLineItem).filter(
        models.DBPurchaseOrderLineItem.order_id == po.id).all()
    job = db.query(models.DBJob).filter(models.DBJob.id == po.job_id).first()

    return sheet_response(
        ["Description", "Qty", "Price", "Tax", "Amount"],
        [[l.description or "", money(l.qty), money(l.price), l.tax_rate or "",
          money((l.qty or 0) * (l.price or 0))] for l in lines],
        "purchase_order_%s.xlsx" % re.sub(r"[^A-Za-z0-9]+", "_", po.number or ""),
        preamble=[["Purchase Order", "", "", "", client.company_name or ""],
                  ["No: " + (po.number or "") + "   (" + (po.status or "") + ")"],
                  ["Supplier: " + (po.supplier_name or "")],
                  ["Job: " + (("%s %s" % (job.number, job.name)).strip() if job else "")],
                  ["Issued: " + (po.issue_date or "") +
                   ("   Needed by: " + po.needed_by if po.needed_by else "")],
                  []],
        closing=[[], ["", "", "", "Subtotal", money(po.amount)],
                 ["", "", "", "Tax", money(po.tax_amount)],
                 ["", "", "", "Total", money(po.total)]])


@router.get("/api/grn/open-orders")
def grn_open_orders(request: Request, db: Session = Depends(get_db)):
    """Orders that still have material to come, so a storekeeper can pick one.

    An order that is fully received is dropped from the list: offering it
    invites somebody to receive the same delivery twice.
    """
    client = require_erp_read(request, db)
    out = []
    for po in db.query(models.DBPurchaseOrder).filter(
            models.DBPurchaseOrder.client_id == client.id).order_by(
                models.DBPurchaseOrder.id.desc()).limit(200).all():
        if not order_is_committed(po):
            continue
        got = received_to_date(db, po.id)
        lines = db.query(models.DBPurchaseOrderLineItem).filter(
            models.DBPurchaseOrderLineItem.order_id == po.id).all()
        pending = money(sum(max(0.0, (l.qty or 0) - got.get(l.id, 0.0)) * (l.price or 0)
                            for l in lines))
        if lines and pending <= 0:
            continue
        job = db.query(models.DBJob).filter(models.DBJob.id == po.job_id).first()
        out.append({
            "id": po.id, "number": po.number or "",
            "supplier_name": po.supplier_name or "",
            "project": ("%s %s" % (job.number, job.name)).strip() if job else "",
            "ordered_value": money(po.total or po.amount),
            "pending_value": pending, "line_count": len(lines),
        })
    return {"orders": out}


@router.get("/api/grn")
def list_goods_receipts(request: Request, db: Session = Depends(get_db),
                        purchase_order_id: int = 0, status: str = ""):
    client = require_erp_read(request, db)
    q = db.query(models.DBGoodsReceipt).filter(
        models.DBGoodsReceipt.client_id == client.id)
    if purchase_order_id:
        q = q.filter(models.DBGoodsReceipt.purchase_order_id == purchase_order_id)
    if status:
        q = q.filter(models.DBGoodsReceipt.status == status.upper())
    rows = [grn_dict(db, g) for g in
            q.order_by(models.DBGoodsReceipt.id.desc()).limit(500).all()]
    live = [r for r in rows if r["status"] != "CANCELLED"]
    return {
        "goods_receipts": rows,
        "summary": {
            "count": len(rows),
            "awaiting_posting": len([r for r in rows if r["status"] == "DRAFT"]),
            "received_value": money(sum(r["received_value"] for r in live)),
            "accepted_value": money(sum(r["accepted_value"] for r in live)),
            "rejected_value": money(sum(r["rejected_value"] for r in live)),
        },
    }


@router.post("/api/grn")
def create_goods_receipt(body: GRNIn, request: Request, db: Session = Depends(get_db)):
    """Open a receipt against an order, pre-filled with what is still to come.

    The quantities default to the outstanding balance because that is what a
    full delivery looks like; the storekeeper's job is then to correct the
    lines that came up short, not to type the whole order back in.
    """
    client, actor_id, actor_name = grn_actor(request, db)
    po = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == body.purchase_order_id,
        models.DBPurchaseOrder.client_id == client.id).first()
    if not po:
        raise HTTPException(404, "Purchase order not found")
    if not order_is_committed(po):
        raise HTTPException(
            409, "Only an approved order can be received against. This one is %s."
                 % (po.status or "Draft"))

    grn = models.DBGoodsReceipt(
        client_id=client.id, purchase_order_id=po.id, job_id=po.job_id,
        number=allocate_grn_number(db, client.id),
        supplier_name=po.supplier_name or "", status="DRAFT",
        received_on=(body.received_on or datetime.now().strftime("%Y-%m-%d")),
        challan_number=(body.challan_number or "").strip(),
        invoice_number=(body.invoice_number or "").strip(),
        vehicle_number=(body.vehicle_number or "").strip(),
        store_location=(body.store_location or "").strip(),
        inspected_by=(body.inspected_by or "").strip(),
        remarks=(body.remarks or "").strip(),
        received_by=actor_id, received_by_name=actor_name)
    db.add(grn)
    db.flush()

    got = received_to_date(db, po.id)
    order = 0
    for l in db.query(models.DBPurchaseOrderLineItem).filter(
            models.DBPurchaseOrderLineItem.order_id == po.id).order_by(
                models.DBPurchaseOrderLineItem.id).all():
        had = money(got.get(l.id, 0.0))
        balance = money(max(0.0, (l.qty or 0) - had))
        order += 1
        db.add(models.DBGoodsReceiptLine(
            goods_receipt_id=grn.id, po_line_id=l.id,
            item_code=getattr(l, "item_code", "") or "",
            description=(l.description or "")[:500],
            uom=getattr(l, "uom", "") or "",
            ordered_qty=money(l.qty), previously_received=had,
            received_qty=balance, accepted_qty=balance, rejected_qty=0.0,
            rate=unit_rate(l.price), amount=money(balance * (l.price or 0)),
            display_order=order))
    db.flush()
    recost_grn(db, grn)
    log_audit(db, client.id, "grn_created", "goods_receipt", grn.id, grn.number,
              "against %s" % (po.number or ""), request)
    db.commit()
    db.refresh(grn)
    return grn_dict(db, grn, detail=True)


@router.put("/api/grn/{grn_id}")
def update_goods_receipt(grn_id: int, body: GRNUpdateIn, request: Request,
                         db: Session = Depends(get_db)):
    client, actor_id, actor_name = grn_actor(request, db)
    grn = grn_or_404(db, client.id, grn_id)
    if (grn.status or "DRAFT") not in GRN_EDITABLE:
        raise HTTPException(
            409, "A %s receipt cannot be changed. Cancel it and take a new one."
                 % (grn.status or "").lower())

    for field in ("received_on", "challan_number", "invoice_number",
                  "vehicle_number", "store_location", "inspected_by", "remarks"):
        val = getattr(body, field)
        if val is not None:
            setattr(grn, field, str(val).strip())

    if body.lines is not None:
        rows = {l.id: l for l in db.query(models.DBGoodsReceiptLine).filter(
            models.DBGoodsReceiptLine.goods_receipt_id == grn.id).all()}
        for inp in body.lines:
            row = rows.get(inp.id)
            if not row:
                continue
            received = money(max(0.0, inp.received_qty or 0.0))
            rejected = money(max(0.0, inp.rejected_qty or 0.0))
            # Accepted is derived when it is not given, because the two numbers
            # have to add up to what arrived. A store that can record eight
            # accepted and three rejected out of ten is a store whose figures
            # nobody can use.
            accepted = (money(inp.accepted_qty) if inp.accepted_qty is not None
                        else money(received - rejected))
            if accepted < 0:
                raise HTTPException(400, "More rejected than arrived on %s"
                                    % (row.description or row.item_code or "a line"))
            if money(accepted + rejected) > received:
                raise HTTPException(
                    400, "Accepted and rejected come to more than arrived on %s"
                         % (row.description or row.item_code or "a line"))
            row.received_qty, row.accepted_qty, row.rejected_qty = (
                received, accepted, rejected)
            row.rejection_reason = (inp.rejection_reason or "")[:300]
    recost_grn(db, grn)
    db.commit()
    db.refresh(grn)
    return grn_dict(db, grn, detail=True)


@router.post("/api/grn/{grn_id}/post")
def post_goods_receipt(grn_id: int, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = grn_actor(request, db)
    grn = grn_or_404(db, client.id, grn_id)
    lines = db.query(models.DBGoodsReceiptLine).filter(
        models.DBGoodsReceiptLine.goods_receipt_id == grn.id).all()
    if not any((l.received_qty or 0) for l in lines):
        raise HTTPException(400, "Nothing arrived on this receipt.")
    recost_grn(db, grn)
    grn_apply(db, client.id, grn, "POST", request, actor_name)
    db.commit()

    # Said rather than refused: a lorry that brings more than the order is a
    # real event, and the buyer needs to know before the bill turns up.
    over = []
    for l in lines:
        total = money((l.previously_received or 0) + (l.accepted_qty or 0))
        if total > money(l.ordered_qty or 0):
            over.append("%s by %s" % (l.item_code or l.description or "line",
                                      money(total - money(l.ordered_qty))))
    msg = "%s posted. %s accepted into the store." % (grn.number, inr(grn.accepted_value))
    if over:
        msg += " Over the order: %s." % "; ".join(over[:4])
    return {"ok": True, "over_received": over,
            "goods_receipt": grn_dict(db, grn, detail=True), "message": msg}


@router.post("/api/grn/{grn_id}/cancel")
def cancel_goods_receipt(grn_id: int, request: Request, body: GRNActionIn = None,
                         db: Session = Depends(get_db)):
    """Cancelling returns the quantity, so the delivery can be recorded again."""
    client, actor_id, actor_name = grn_actor(request, db)
    grn = grn_or_404(db, client.id, grn_id)
    body = body or GRNActionIn()
    if not (body.comments or "").strip():
        raise HTTPException(400, "Say why this receipt is being cancelled.")
    grn_apply(db, client.id, grn, "CANCEL", request, actor_name, body.comments)
    grn.remarks = ("%s\nCancelled: %s" % (grn.remarks or "", body.comments)).strip()
    db.commit()
    return {"ok": True, "message": "%s cancelled." % grn.number}


@router.delete("/api/grn/{grn_id}")
def delete_goods_receipt(grn_id: int, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = grn_actor(request, db)
    grn = grn_or_404(db, client.id, grn_id)
    if (grn.status or "DRAFT") != "DRAFT":
        raise HTTPException(
            409, "A posted receipt is a record of what arrived. Cancel it instead.")
    db.query(models.DBGoodsReceiptLine).filter(
        models.DBGoodsReceiptLine.goods_receipt_id == grn.id).delete()
    number = grn.number
    db.delete(grn)
    log_audit(db, client.id, "grn_deleted", "goods_receipt", grn_id, number or "",
              "draft discarded", request)
    db.commit()
    return {"ok": True, "message": "%s discarded." % number}


@router.get("/api/grn/{grn_id}/export.xlsx")
def export_goods_receipt(grn_id: int, request: Request, db: Session = Depends(get_db)):
    """The receipt as a workbook, for the file the store keeps by the gate."""
    client = require_erp_read(request, db)
    grn = grn_or_404(db, client.id, grn_id)
    d = grn_dict(db, grn, detail=True)
    return sheet_response(
        ["#", "Item code", "Description", "UOM", "Ordered", "Already received",
         "Arrived", "Accepted", "Rejected", "Reason", "Rate", "Value"],
        [[i, l["item_code"], l["description"], l["uom"], l["ordered_qty"],
          l["previously_received"], l["received_qty"], l["accepted_qty"],
          l["rejected_qty"], l["rejection_reason"], l["rate"], l["amount"]]
         for i, l in enumerate(d["lines"], 1)],
        "%s.xlsx" % d["number"],
        preamble=[["GOODS RECEIPT NOTE"],
                  ["GRN number", d["number"], "", "Purchase order", d["purchase_order"]],
                  ["Supplier", d["supplier_name"], "", "Project", d["project"]],
                  ["Received on", d["received_on"], "", "Challan", d["challan_number"]],
                  ["Supplier invoice", d["invoice_number"], "",
                   "Vehicle", d["vehicle_number"]],
                  ["Store", d["store_location"], "", "Status", d["status"]],
                  ["Received by", d["received_by_name"], "",
                   "Inspected by", d["inspected_by"]],
                  []],
        closing=[[],
                 ["", "", "", "", "", "", "", "", "", "", "Arrived", d["received_value"]],
                 ["", "", "", "", "", "", "", "", "", "", "Accepted", d["accepted_value"]],
                 ["", "", "", "", "", "", "", "", "", "", "Rejected", d["rejected_value"]]])


@router.get("/api/grn/{grn_id}")
def get_goods_receipt(grn_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return grn_dict(db, grn_or_404(db, client.id, grn_id), detail=True)


@router.get("/api/match/three-way")
def three_way_match(request: Request, db: Session = Depends(get_db),
                    job_id: int = 0, only_exceptions: bool = False):
    """Every order with what was ordered, what arrived and what was billed.

    This is the report that stops a business paying for material it never
    received, which is the single most expensive thing a site office gets
    wrong.
    """
    client = require_erp_read(request, db)
    q = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.client_id == client.id,
        models.DBPurchaseOrder.status != "Cancelled")
    if job_id:
        q = q.filter(models.DBPurchaseOrder.job_id == job_id)

    rows = []
    for po in q.order_by(models.DBPurchaseOrder.id.desc()).limit(500).all():
        lines = db.query(models.DBPurchaseOrderLineItem).filter(
            models.DBPurchaseOrderLineItem.order_id == po.id).all()
        got = received_to_date(db, po.id)
        billed = billed_against_po(db, po.id)
        receipts = db.query(models.DBGoodsReceipt).filter(
            models.DBGoodsReceipt.purchase_order_id == po.id,
            models.DBGoodsReceipt.status != "CANCELLED").count()

        ordered_value = money(sum((l.qty or 0) * (l.price or 0) for l in lines))
        received_value = money(sum(got.get(l.id, 0.0) * (l.price or 0) for l in lines))
        verdict, note = match_verdict(ordered_value, received_value, billed["value"])
        job = db.query(models.DBJob).filter(models.DBJob.id == po.job_id).first()
        rows.append({
            "purchase_order_id": po.id, "number": po.number or "",
            "supplier_name": po.supplier_name or "",
            "status": po.status or "",
            "project": ("%s %s" % (job.number, job.name)).strip() if job else "",
            "ordered_value": ordered_value,
            "received_value": received_value,
            "billed_value": billed["value"], "paid_value": billed["paid"],
            "bill_count": len(billed["bills"]), "receipt_count": receipts,
            "unbilled_receipts": (money(received_value - billed["value"])
                                  if received_value > billed["value"] else 0.0),
            "verdict": verdict, "note": note,
        })

    exceptions = [r for r in rows if r["verdict"] in
                  ("OVER_BILLED", "OVER_RECEIVED", "AWAITING_RECEIPT")]
    return {
        "orders": exceptions if only_exceptions else rows,
        "summary": {
            "orders": len(rows),
            "matched": len([r for r in rows if r["verdict"] == "MATCHED"]),
            "exceptions": len(exceptions),
            "over_billed": money(sum(r["billed_value"] - r["received_value"]
                                     for r in rows if r["verdict"] == "OVER_BILLED")),
            # What has arrived and not been billed is a cost already incurred.
            # Left off the books it makes a month look cheaper than it was.
            "accrual_owed": money(sum(r["unbilled_receipts"] for r in rows)),
            "ordered_value": money(sum(r["ordered_value"] for r in rows)),
            "received_value": money(sum(r["received_value"] for r in rows)),
            "billed_value": money(sum(r["billed_value"] for r in rows)),
        },
    }


@router.get("/api/match/three-way/{po_id}")
def three_way_match_detail(po_id: int, request: Request, db: Session = Depends(get_db)):
    """The same comparison, line by line, for one order."""
    client = require_erp_read(request, db)
    po = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == po_id,
        models.DBPurchaseOrder.client_id == client.id).first()
    if not po:
        raise HTTPException(404, "Purchase order not found")

    got = received_to_date(db, po.id)
    billed = billed_against_po(db, po.id)
    lines = []
    for l in db.query(models.DBPurchaseOrderLineItem).filter(
            models.DBPurchaseOrderLineItem.order_id == po.id).order_by(
                models.DBPurchaseOrderLineItem.id).all():
        rec = money(got.get(l.id, 0.0))
        bil = money(billed["per_line"].get(l.id, 0.0))
        verdict, note = match_verdict(money(l.qty), rec, bil)
        lines.append({
            "po_line_id": l.id, "item_code": getattr(l, "item_code", "") or "",
            "description": l.description or "", "uom": getattr(l, "uom", "") or "",
            "ordered_qty": money(l.qty), "received_qty": rec, "billed_qty": bil,
            "rate": unit_rate(l.price),
            "ordered_value": money((l.qty or 0) * (l.price or 0)),
            "received_value": money(rec * (l.price or 0)),
            "billed_value": money(bil * (l.price or 0)),
            "verdict": verdict, "note": note,
        })

    return {
        "purchase_order": purchase_order_to_dict(db, po),
        "lines": lines,
        "goods_receipts": [grn_dict(db, g) for g in
                           db.query(models.DBGoodsReceipt).filter(
                               models.DBGoodsReceipt.purchase_order_id == po.id).order_by(
                                   models.DBGoodsReceipt.id.desc()).all()],
        "bills": [{"id": b.id, "number": b.number or "", "status": b.status or "",
                   "total": money(b.total), "amount_paid": money(b.amount_paid),
                   "issue_date": b.issue_date or ""} for b in billed["bills"]],
        # Only meaningful when the bill lines name the order lines they settle.
        # Without that the totals still compare; the per line figures do not.
        "line_level_available": bool(billed["per_line"]),
    }


@router.post("/api/grn/{grn_id}/bill")
def bill_from_receipt(grn_id: int, request: Request, body: dict = None,
                      db: Session = Depends(get_db)):
    """The supplier bill for what actually arrived.

    Drawn from the accepted quantities, not the ordered ones, so the bill a
    supplier is paid against is the delivery the store signed for. Retyping
    it is where the three figures quietly stop matching, and the three-way
    match then reports a difference nobody caused.
    """
    client, actor_id, actor_name = grn_actor(request, db)
    grn = grn_or_404(db, client.id, grn_id)
    if (grn.status or "") != "POSTED":
        raise HTTPException(
            409, "Post the receipt first. A bill drawn from a draft is a bill "
                 "for material nobody has confirmed arrived.")

    existing = db.query(models.DBBill).filter(
        models.DBBill.client_id == client.id,
        models.DBBill.reference == (grn.number or "")).first()
    if existing and (grn.number or ""):
        raise HTTPException(
            409, "%s already has a bill (%s). Two bills against one delivery "
                 "is how a supplier gets paid twice."
                 % (grn.number, existing.number or "unnumbered"))

    lines = [l for l in db.query(models.DBGoodsReceiptLine).filter(
        models.DBGoodsReceiptLine.goods_receipt_id == grn.id).all()
        if (l.accepted_qty or 0) > 0]
    if not lines:
        raise HTTPException(
            400, "Nothing on this receipt was accepted, so there is nothing "
                 "to pay for.")

    amount = money(sum((l.accepted_qty or 0) * unit_rate(l.rate) for l in lines))
    # GST at the rate each line was ordered at. The bill used to carry none,
    # so a supplier's invoice for 2.37 lakh was booked at the 1.85 lakh of
    # goods alone: the payable, the ledger and the input credit all short.
    po_lines = db.query(models.DBPurchaseOrderLineItem).filter(
        models.DBPurchaseOrderLineItem.order_id == grn.purchase_order_id).all()
    po_rates = {pl.id: (pl.tax_rate or "0%") for pl in po_lines}
    po = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == grn.purchase_order_id).first()
    # The lines' own rates, where they account for the tax the order was
    # actually agreed at. Orders saved before a rate was asked for carry a
    # label that does not; for those the order's own rate is the one used.
    by_lines = money(sum((pl.qty or 0) * (pl.price or 0) * tax_percent_of(pl.tax_rate) / 100.0
                         for pl in po_lines))
    agreed_tax = money(po.tax_amount or 0) if po else 0.0
    if po and abs(by_lines - agreed_tax) > 1.0:
        flat = round(agreed_tax / po.amount * 100.0, 2) if po.amount else 0.0
        po_rates = {k: "%g%%" % flat for k in po_rates}
    rate_of = {l.id: po_rates.get(l.po_line_id, "0%") for l in lines}
    tax = money(sum((l.accepted_qty or 0) * unit_rate(l.rate) * tax_percent_of(rate_of[l.id]) / 100.0
                    for l in lines))
    body = body or {}
    bill = models.DBBill(
        client_id=client.id, job_id=grn.job_id,
        number=next_sequence_number(db, models.DBBill, client.id, "BILL-"),
        vendor_name=grn.supplier_name or "",
        issue_date=datetime.now().strftime("%Y-%m-%d"),
        # Undated, a bill is filed as the oldest debt there is; the supplier's
        # own terms say when it is really due.
        due_date=(body.get("due_date") or days_after(
            datetime.now().strftime("%Y-%m-%d"),
            supplier_payment_days(db, client.id, grn.supplier_name))),
        amount=amount, tax_amount=tax, total=money(amount + tax),
        status="Draft", category="material",
        reference=grn.number or "",
        notes="Raised from %s%s" % (grn.number or "a receipt",
                                    " - challan %s" % grn.challan_number
                                    if grn.challan_number else ""),
        purchase_order_id=grn.purchase_order_id)
    db.add(bill)
    db.flush()
    for l in lines:
        db.add(models.DBBillLineItem(
            bill_id=bill.id, po_line_id=l.po_line_id,
            description=l.description or l.item_code or "",
            qty=money(l.accepted_qty), price=unit_rate(l.rate),
            tax_rate=rate_of[l.id] or "0%"))
    log_audit(db, client.id, "bill_from_receipt", "bill", bill.id,
              bill.number or "", "%s %s" % (grn.number, inr(amount)), request)
    db.commit()
    db.refresh(bill)
    return {"ok": True, "bill": {"id": bill.id, "number": bill.number or "",
                                 "vendor_name": bill.vendor_name or "",
                                 "total": money(bill.total),
                                 "status": bill.status or "",
                                 "reference": bill.reference or "",
                                 "purchase_order_id": bill.purchase_order_id},
            "message": "%s drawn up for %s from what actually arrived - %s "
                       "across %d line%s%s." % (bill.number, bill.vendor_name,
                                                inr(amount), len(lines),
                                                "" if len(lines) == 1 else "s",
                                                (", %s with GST" % inr(amount + tax)) if tax else "")}


@router.get("/api/suppliers")
def list_suppliers(request: Request, q: str = "", db: Session = Depends(get_db)):
    """The supplier master - and the names already on orders and bills that
    are not in it yet, so the history can be adopted in one click."""
    client = require_erp_read(request, db)
    rows = db.query(models.DBSupplier).filter(
        models.DBSupplier.client_id == client.id).order_by(models.DBSupplier.name).all()
    known = {norm_name(s.name) for s in rows}
    seen = {}
    for (name,) in db.query(models.DBPurchaseOrder.supplier_name).filter(
            models.DBPurchaseOrder.client_id == client.id).all():
        if name and norm_name(name) not in known:
            seen.setdefault(norm_name(name), name.strip())
    for (name,) in db.query(models.DBBill.vendor_name).filter(
            models.DBBill.client_id == client.id).all():
        if name and norm_name(name) not in known:
            seen.setdefault(norm_name(name), name.strip())
    needle = norm_name(q)
    out = [supplier_dict(s) for s in rows if not needle or needle in norm_name(s.name)]
    return {"suppliers": out, "unregistered": sorted(seen.values())}


@router.post("/api/suppliers")
def create_supplier(body: SupplierIn, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "purchase.manage")
    s = models.DBSupplier(client_id=client.id, code=next_supplier_code(db, client.id))
    _apply_supplier(db, client.id, s, body)
    db.add(s)
    db.commit()
    db.refresh(s)
    return supplier_dict(s)


@router.put("/api/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, body: SupplierIn, request: Request,
                    db: Session = Depends(get_db)):
    client = require_items_access(request, db, "purchase.manage")
    s = db.query(models.DBSupplier).filter(
        models.DBSupplier.id == supplier_id, models.DBSupplier.client_id == client.id).first()
    if not s:
        raise HTTPException(404, "Supplier not found")
    _apply_supplier(db, client.id, s, body)
    db.commit()
    return supplier_dict(s)


@router.post("/api/suppliers/adopt")
def adopt_suppliers(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Put the suppliers already named on orders and bills into the master.
    Their history is theirs from that moment: the ledger matches by name."""
    client = require_items_access(request, db, "purchase.manage")
    names = (body or {}).get("names") or list_suppliers(request, "", db)["unregistered"]
    made = []
    for name in names[:200]:
        name = (name or "").strip()
        if not name:
            continue
        if any(norm_name(x.name) == norm_name(name) for x in db.query(models.DBSupplier).filter(
                models.DBSupplier.client_id == client.id).all()):
            continue
        s = models.DBSupplier(client_id=client.id, code=next_supplier_code(db, client.id),
                              name=name, payment_days=30, is_active=True)
        db.add(s)
        db.flush()
        made.append(s.name)
    db.commit()
    return {"ok": True, "added": made,
            "message": "%d supplier%s added from the orders and bills already here."
                       % (len(made), "" if len(made) == 1 else "s")}


@router.get("/api/rfqs")
def list_rfqs(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    rows = [rfq_dict(db, r) for r in db.query(models.DBRfq).filter(
        models.DBRfq.client_id == client.id).order_by(models.DBRfq.id.desc()).limit(300).all()]
    return {"rfqs": rows, "summary": {
        "open": len([r for r in rows if r["status"] == "OPEN"]),
        "awarded": len([r for r in rows if r["status"] == "AWARDED"]),
        "waiting_for_quotes": len([r for r in rows if r["status"] == "OPEN" and r["quotes"] < 3])}}


@router.post("/api/rfqs")
def create_rfq(body: RfqIn, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, "purchase.manage")
    if not (body.title or "").strip():
        raise HTTPException(400, "Say what is being bought - \"Cement for Block A raft\".")
    r = _make_rfq(db, client, actor_name, body.title, body.job_id, body.needed_by, body.notes,
                  [l.dict() for l in body.lines])
    db.commit()
    return {"ok": True, "rfq": rfq_dict(db, r), "message": "%s opened." % r.number}


@router.post("/api/rfqs/from-work-order/{wo_id}")
def rfq_from_work_order(wo_id: int, request: Request, db: Session = Depends(get_db)):
    """An enquiry for exactly what the order still needs: what its budget
    calls for, less what is in the store and already on order."""
    client, actor_id, actor_name = wo_actor(request, db, "purchase.manage")
    wo = work_order_or_404(db, client.id, wo_id)
    rows = [r for r in material_required(db, client.id, wo) if not r["covered"]]
    if not rows:
        raise HTTPException(409, "%s needs nothing more - the store and the orders already "
                                 "cover its budget." % wo.number)
    r = _make_rfq(db, client, actor_name, "Material for %s" % wo.number, wo.job_id, "", "",
                  [{"item_code": x["item_code"], "description": x["item_name"] or x["item_code"],
                    "uom": x["uom"], "qty": x["to_buy"]} for x in rows], work_order_id=wo.id)
    db.commit()
    return {"ok": True, "rfq": rfq_dict(db, r),
            "message": "%s opened for %d item%s %s still needs."
                       % (r.number, len(rows), "" if len(rows) == 1 else "s", wo.number)}


@router.get("/api/rfqs/{rfq_id}")
def get_rfq(rfq_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return comparative_statement(db, rfq_or_404(db, client.id, rfq_id))


@router.post("/api/rfqs/{rfq_id}/quotes")
def record_quote(rfq_id: int, body: QuoteIn, request: Request, db: Session = Depends(get_db)):
    """A supplier's answer. Sent again, it replaces their last one - a
    revised quote is the same supplier changing their mind, not a new one."""
    client, actor_id, actor_name = wo_actor(request, db, "purchase.manage")
    r = rfq_or_404(db, client.id, rfq_id)
    if r.status != "OPEN":
        raise HTTPException(409, "%s is %s; its quotes are closed." % (r.number, r.status.lower()))
    name = (body.supplier_name or "").strip()
    if not name:
        raise HTTPException(400, "Whose quote is this?")
    valid_ids = {l.id for l in _rfq_lines(db, r.id)}
    lines = [l for l in body.lines if l.rfq_line_id in valid_ids and (l.rate or 0) > 0]
    if not lines:
        raise HTTPException(400, "The quote has no rates on it.")
    if any(l.rate < 0 for l in body.lines) or (body.freight or 0) < 0:
        raise HTTPException(400, "A rate or freight cannot be negative.")
    existing = next((q for q in db.query(models.DBRfqQuote).filter(
        models.DBRfqQuote.rfq_id == r.id).all() if norm_name(q.supplier_name) == norm_name(name)), None)
    if existing:
        db.query(models.DBRfqQuoteLine).filter(
            models.DBRfqQuoteLine.quote_id == existing.id).delete()
        q = existing
    else:
        q = models.DBRfqQuote(rfq_id=r.id)
        db.add(q)
    q.supplier_name = name
    q.quote_ref = (body.quote_ref or "").strip()
    q.quote_date = (body.quote_date or datetime.now().strftime("%Y-%m-%d"))[:10]
    q.delivery_days = max(0, int(body.delivery_days or 0))
    q.payment_terms = (body.payment_terms or "").strip()
    q.freight = money(body.freight or 0)
    q.valid_until = (body.valid_until or "").strip()
    q.notes = (body.notes or "").strip()
    db.flush()
    for l in lines:
        db.add(models.DBRfqQuoteLine(quote_id=q.id, rfq_line_id=l.rfq_line_id,
                                     rate=unit_rate(l.rate), tax_percent=l.tax_percent or 0,
                                     remarks=(l.remarks or "").strip()))
    db.commit()
    return {"ok": True, "comparison": comparative_statement(db, r),
            "message": "%s's quote %s on %s." % (name, "revised" if existing else "recorded", r.number)}


@router.post("/api/rfqs/{rfq_id}/award")
def award_rfq(rfq_id: int, body: AwardIn, request: Request, db: Session = Depends(get_db)):
    """The choice, and the purchase orders it makes - one per supplier, at
    the rates they quoted. Anything but the lowest has to say why."""
    client, actor_id, actor_name = wo_actor(request, db, "purchase.manage")
    r = rfq_or_404(db, client.id, rfq_id)
    if r.status != "OPEN":
        raise HTTPException(409, "%s is already %s." % (r.number, r.status.lower()))
    cmp_ = comparative_statement(db, r)
    if not cmp_["suppliers"]:
        raise HTTPException(409, "No quotes yet. Record what the suppliers came back with first.")
    mode = body.mode or "lowest_per_line"
    choice = {}
    if mode == "lowest_per_line":
        for row in cmp_["lines"]:
            if not row["lowest"]:
                raise HTTPException(409, "%s has not been quoted by anybody." % row["description"])
            choice[row["rfq_line_id"]] = row["lowest"]
    elif mode == "one_supplier":
        name = (body.supplier_name or "").strip()
        sup = next((s for s in cmp_["suppliers"] if norm_name(s["supplier_name"]) == norm_name(name)), None)
        if not sup:
            raise HTTPException(400, "%s has not quoted on %s." % (name or "Nobody", r.number))
        if not sup["complete"]:
            raise HTTPException(409, "%s did not quote every line." % sup["supplier_name"])
        for row in cmp_["lines"]:
            choice[row["rfq_line_id"]] = sup["supplier_name"]
    else:
        for a in body.awards or []:
            choice[int(a.get("rfq_line_id"))] = (a.get("supplier_name") or "").strip()
        missing = [row["description"] for row in cmp_["lines"] if not choice.get(row["rfq_line_id"])]
        if missing:
            raise HTTPException(400, "Choose a supplier for: " + ", ".join(missing[:4]))

    # Is anything going to somebody other than the lowest?
    passed_over = []
    for row in cmp_["lines"]:
        pick = choice[row["rfq_line_id"]]
        offer = next((o for o in row["offers"] if norm_name(o["supplier_name"]) == norm_name(pick)), None)
        if not offer:
            raise HTTPException(400, "%s did not quote for %s." % (pick, row["description"]))
        if offer["rate"] > row["lowest_rate"] + 0.0001:
            passed_over.append("%s (%s at %s over %s at %s)" % (
                row["description"], pick, offer["rate"], row["lowest"], row["lowest_rate"]))
    if mode == "one_supplier" and cmp_["l1"] and norm_name(body.supplier_name) != norm_name(cmp_["l1"]):
        passed_over.append("the whole order to %s over L1 %s" % (body.supplier_name, cmp_["l1"]))
    reason = (body.reason or "").strip()
    if passed_over and not reason:
        raise HTTPException(400, "Not the lowest: %s. Say why, so the file shows it."
                                 % "; ".join(passed_over[:3]))

    # One purchase order per supplier, at what they quoted.
    quotes = {norm_name(s["supplier_name"]): s for s in cmp_["suppliers"]}
    lines_by_id = {l.id: l for l in _rfq_lines(db, r.id)}
    by_supplier = {}
    for row in cmp_["lines"]:
        pick = choice[row["rfq_line_id"]]
        offer = next(o for o in row["offers"] if norm_name(o["supplier_name"]) == norm_name(pick))
        by_supplier.setdefault(offer["supplier_name"], []).append((row, offer))
    made = []
    for supplier, picks in by_supplier.items():
        q = quotes[norm_name(supplier)]
        amount = sum(o["amount"] for _, o in picks)
        tax = sum(o["amount"] * (o["tax_percent"] or 0) / 100.0 for _, o in picks)
        # Freight goes with the order when the supplier gets everything they
        # quoted for; split awards carry it pro rata to what they got.
        freight = q["freight"] * (amount / q["basic"]) if q["basic"] else 0.0
        po = models.DBPurchaseOrder(
            client_id=client.id, number=allocate_po_number(db, client.id), status="Draft",
            submitted_by=actor_id, approval_status="none",
            supplier_name=supplier, job_id=r.job_id,
            issue_date=datetime.now().strftime("%Y-%m-%d"),
            needed_by=(body.needed_by or r.needed_by or ""), category="materials",
            reference="%s / their quote %s" % (r.number, q["quote_ref"] or q["quote_date"]),
            notes=("Payment: %s. Delivery within %s days." % (q["payment_terms"] or "as agreed",
                                                             q["delivery_days"] or "the agreed"))
                  + (" Freight to site %s." % inr(freight) if freight else ""),
            amount=money(amount + freight), tax_amount=money(tax),
            total=money(amount + freight + tax))
        db.add(po)
        db.flush()
        for row, offer in picks:
            db.add(models.DBPurchaseOrderLineItem(
                order_id=po.id, description=row["description"][:500], item_code=row["item_code"][:60],
                uom=row["uom"][:20], qty=row["qty"], price=offer["rate"],
                tax_rate="%g%%" % (offer["tax_percent"] or 0)))
            l = lines_by_id[row["rfq_line_id"]]
            l.awarded_supplier, l.awarded_rate, l.po_id = supplier, offer["rate"], po.id
        if freight:
            db.add(models.DBPurchaseOrderLineItem(
                order_id=po.id, description="Freight to site", item_code="", uom="Lot",
                qty=1, price=money(freight), tax_rate="0%"))
        made.append({"id": po.id, "number": po.number, "supplier": supplier,
                     "total": money(amount + freight + tax)})
    r.status = "AWARDED"
    r.awarded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    r.award_reason = reason
    log_audit(db, client.id, "rfq_awarded", "rfq", r.id, r.number,
              "; ".join("%s %s" % (m["number"], m["supplier"]) for m in made)
              + ((" - " + reason) if reason else ""), request)
    db.commit()
    return {"ok": True, "orders": made, "comparison": comparative_statement(db, r),
            "message": "%s awarded: %s." % (r.number, ", ".join(
                "%s to %s (%s)" % (m["number"], m["supplier"], inr(m["total"])) for m in made))}


@router.post("/api/rfqs/{rfq_id}/cancel")
def cancel_rfq(rfq_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "purchase.manage")
    r = rfq_or_404(db, client.id, rfq_id)
    if r.status != "OPEN":
        raise HTTPException(409, "%s is %s." % (r.number, r.status.lower()))
    r.status = "CANCELLED"
    r.notes = ((r.notes or "") + "\nCancelled: " + ((body or {}).get("reason") or "")).strip()
    db.commit()
    return {"ok": True, "message": "%s cancelled." % r.number}


@router.get("/api/purchase-orders/{order_id}/document.pdf")
def purchase_order_pdf(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    order = purchase_order_or_404(db, client.id, order_id)
    return form_pdf_response(po_form_spec(db, client, order), order.number)


@router.get("/api/rfqs/{rfq_id}/comparison.xlsx")
def rfq_comparison_export(rfq_id: int, request: Request, db: Session = Depends(get_db)):
    """The comparative statement: each line against each supplier, then each
    supplier's total landed at site and its rank."""
    client = require_erp_read(request, db)
    d = comparative_statement(db, rfq_or_404(db, client.id, rfq_id))
    names = [s["supplier_name"] for s in d["suppliers"]]
    rows = []
    for l in d["lines"]:
        by = {o["supplier_name"]: o["rate"] for o in l["offers"]}
        rows.append(tuple([l["item_code"], l["description"], l["uom"], l["qty"]] + [by.get(n, "") for n in names] +
                          [l["lowest"], l["lowest_rate"]]))
    closing = [(), tuple(["Basic", "", "", ""] + [s["basic"] for s in d["suppliers"]]),
               tuple(["GST", "", "", ""] + [s["tax"] for s in d["suppliers"]]),
               tuple(["Freight", "", "", ""] + [s["freight"] for s in d["suppliers"]]),
               tuple(["Landed at site", "", "", ""] + [s["landed"] for s in d["suppliers"]]),
               tuple(["Rank", "", "", ""] + [s.get("rank", "incomplete") for s in d["suppliers"]])]
    rfq = d.get("rfq") or {}
    return sheet_response(tuple(["Code", "Description", "UoM", "Qty"] + names + ["Lowest", "Lowest rate"]), rows,
                          "comparison_%s.xlsx" % (rfq.get("number") or rfq_id),
                          preamble=_pre(client, "COMPARATIVE STATEMENT", ("Enquiry", rfq.get("number", ""),
                                                                          "L1", d.get("l1") or "-")),
                          closing=closing)
