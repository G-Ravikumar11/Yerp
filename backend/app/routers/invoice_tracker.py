"""The invoice tracker in the store portal."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.auth import require_items_access, session_employee
from app.core.currency import money, unit_rate
from app.core.sheets import sheet_response
from app.documents.letterhead import letterhead
from app.documents.pdf_twins import SHEET_AS_PDF
from app.documents.tracker_xlsx import build_workbook
from app.db import get_db
from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
from app.services.invoice_tracker import DEFAULT_GST, DEFAULT_MARKUP, build_tracker

router = APIRouter()

# Looking is for anyone who works with purchases or the store; keying in what a supplier's bill says is for the store.
SEE = ("stores.receive", "stores.manage", "purchase.manage", "bills.view_all")
KEEP = ("stores.receive", "stores.manage", "purchase.manage")


class InvoiceIn(BaseModel):
    invoice_date: Optional[str] = None
    invoice_amount: Optional[float] = None
    clear_amount: bool = False
    freight: Optional[float] = None
    insurance: Optional[float] = None
    hamali: Optional[float] = None
    remark: Optional[str] = None


class RateIn(BaseModel):
    job_id: int = 0
    item_key: str
    rate: Optional[float] = None          # None clears it


class BlockIn(BaseModel):
    block: str = ""


class NoteIn(BaseModel):
    job_id: int = 0
    category: str
    wo_amount: Optional[float] = None
    remarks: Optional[str] = None


def _pct(value):
    return max(0.0, min(value, 100.0))


@router.get("/api/invoice-tracker")
def invoice_tracker(request: Request, job_id: int = 0, gst: float = DEFAULT_GST, markup: float = DEFAULT_MARKUP,
                    db: Session = Depends(get_db)):
    client = require_items_access(request, db, SEE)
    return build_tracker(db, client.id, job_id, _pct(gst), _pct(markup))


@router.put("/api/invoice-tracker/invoices/{grn_id}")
def save_invoice(grn_id: int, body: InvoiceIn, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, KEEP)
    # A negative id is a receipt made in the Store Hub (see hub_receipts).
    found = (db.query(DBStoreGrn.id).filter(DBStoreGrn.id == -grn_id, DBStoreGrn.client_id == client.id).first() if grn_id < 0 else
             db.query(models.DBGoodsReceipt.id).filter(models.DBGoodsReceipt.id == grn_id,
                                                       models.DBGoodsReceipt.client_id == client.id).first())
    if not found:
        raise HTTPException(404, "Goods receipt not found")
    row = db.query(models.DBTrackerInvoice).filter(models.DBTrackerInvoice.client_id == client.id,
                                                   models.DBTrackerInvoice.grn_id == grn_id).first()
    if not row:
        row = models.DBTrackerInvoice(client_id=client.id, grn_id=grn_id)
        db.add(row)
    if body.invoice_date is not None:
        row.invoice_date = body.invoice_date.strip()
    if body.clear_amount:
        row.invoice_amount = None
    elif body.invoice_amount is not None:
        if body.invoice_amount < 0:
            raise HTTPException(400, "The invoice amount cannot be negative.")
        row.invoice_amount = money(body.invoice_amount)
    if body.freight is not None:
        if body.freight < 0:
            raise HTTPException(400, "Freight cannot be negative.")
        row.freight = money(body.freight)
    for kind, amount in (("insurance", body.insurance), ("hamali", body.hamali)):
        if amount is None:
            continue
        if amount < 0:
            raise HTTPException(400, "%s cannot be negative." % kind.capitalize())
        charge = db.query(models.DBTrackerCharge).filter(
            models.DBTrackerCharge.client_id == client.id, models.DBTrackerCharge.grn_id == grn_id,
            models.DBTrackerCharge.kind == kind).first()
        if not charge:
            charge = models.DBTrackerCharge(client_id=client.id, grn_id=grn_id, kind=kind)
            db.add(charge)
        charge.amount = money(amount)
    if body.remark is not None:
        note = db.query(models.DBTrackerInvoiceNote).filter(
            models.DBTrackerInvoiceNote.client_id == client.id, models.DBTrackerInvoiceNote.grn_id == grn_id).first()
        if not note:
            note = models.DBTrackerInvoiceNote(client_id=client.id, grn_id=grn_id)
            db.add(note)
        note.remark = body.remark.strip()[:1000]
    db.commit()
    return {"ok": True}


@router.put("/api/invoice-tracker/blocks/{line_id}")
def save_block(line_id: int, body: BlockIn, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, KEEP)
    line = (db.query(DBStoreGrnLine.id).join(DBStoreGrn, DBStoreGrn.id == DBStoreGrnLine.grn_id).filter(
        DBStoreGrnLine.id == -line_id, DBStoreGrn.client_id == client.id).first() if line_id < 0 else
            db.query(models.DBGoodsReceiptLine).join(
        models.DBGoodsReceipt, models.DBGoodsReceipt.id == models.DBGoodsReceiptLine.goods_receipt_id).filter(
        models.DBGoodsReceiptLine.id == line_id, models.DBGoodsReceipt.client_id == client.id).first())
    if not line:
        raise HTTPException(404, "Receipt line not found")
    row = db.query(models.DBTrackerBlock).filter(models.DBTrackerBlock.client_id == client.id,
                                                 models.DBTrackerBlock.grn_line_id == line_id).first()
    if not row:
        row = models.DBTrackerBlock(client_id=client.id, grn_line_id=line_id)
        db.add(row)
    row.block = body.block.strip()[:60]
    db.commit()
    return {"ok": True}


@router.put("/api/invoice-tracker/working-rates")
def save_working_rate(body: RateIn, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, KEEP)
    key = body.item_key.strip().upper()
    if not key:
        raise HTTPException(400, "Say which material this is for.")
    row = db.query(models.DBTrackerWorkingRate).filter(
        models.DBTrackerWorkingRate.client_id == client.id, models.DBTrackerWorkingRate.job_id == (body.job_id or 0),
        models.DBTrackerWorkingRate.item_key == key).first()
    if body.rate is None:
        if row:
            db.delete(row)
    else:
        if body.rate < 0:
            raise HTTPException(400, "A rate cannot be negative.")
        if not row:
            row = models.DBTrackerWorkingRate(client_id=client.id, job_id=body.job_id or 0, item_key=key)
            db.add(row)
        row.rate = unit_rate(body.rate)
    db.commit()
    return {"ok": True}


@router.put("/api/invoice-tracker/categories")
def save_category(body: NoteIn, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, KEEP)
    name = body.category.strip()
    if not name:
        raise HTTPException(400, "Say which category this is for.")
    row = db.query(models.DBTrackerNote).filter(
        models.DBTrackerNote.client_id == client.id, models.DBTrackerNote.job_id == (body.job_id or 0),
        models.DBTrackerNote.category == name).first()
    if not row:
        row = models.DBTrackerNote(client_id=client.id, job_id=body.job_id or 0, category=name)
        db.add(row)
    if body.wo_amount is not None:
        if body.wo_amount < 0:
            raise HTTPException(400, "The work-order amount cannot be negative.")
        row.wo_amount = money(body.wo_amount)
    if body.remarks is not None:
        row.remarks = body.remarks.strip()[:1000]
    db.commit()
    return {"ok": True}


@router.get("/api/invoice-tracker/export.xlsx")
def invoice_tracker_export(request: Request, job_id: int = 0, gst: float = DEFAULT_GST, markup: float = DEFAULT_MARKUP,
                           db: Session = Depends(get_db)):
    client = require_items_access(request, db, SEE)
    gst, markup = _pct(gst), _pct(markup)
    t = build_tracker(db, client.id, job_id, gst, markup)
    job = db.query(models.DBJob).filter(models.DBJob.id == job_id, models.DBJob.client_id == client.id).first() if job_id else None
    project = ("%s %s" % (job.number or "", job.name or "")).strip() if job else "All projects"

    if SHEET_AS_PDF.get() is not None:
        # The .pdf twin of this address: the invoice list on paper, with the logo as a watermark.
        tot = t["totals"]
        rows = [(i["grn"], i["supplier"], i["invoice_number"], i["invoice_date"], i["po_number"], i["amount"], i["gst"],
                 i["freight"], i["insurance"], i["hamali"], i["total"], "" if i["invoice_amount"] is None else i["invoice_amount"],
                 "" if i["difference"] is None else i["difference"]) for i in t["invoices"]]
        return sheet_response(
            ("GRN", "Supplier", "Invoice no", "Invoice date", "PO", "Amount", "GST", "Freight", "Insurance", "Hamali",
             "Total", "Invoice amount", "Difference"),
            rows, "invoice_tracker.xlsx", logo_watermark=True,
            preamble=[("INVOICE TRACKER", client.company_name or ""), ("Project", project), ("GST", "%g%%" % t["gst_percent"]), ()],
            closing=[(), ("Total", "", "", "", "", tot["amount"], tot["gst"], tot["freight"], tot["insurance"], tot["hamali"], tot["total"])])

    company = letterhead(db, client)
    emp = session_employee(request, db)
    who = ("%s %s" % (emp.first_name, emp.last_name or "")).strip() if emp else (client.company_name or "")
    return Response(
        content=build_workbook(t, company, project, gst, markup, who),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="invoice_tracker.xlsx"'})
