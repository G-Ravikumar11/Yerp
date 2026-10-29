"""Store > Material Issue Voucher: the printed voucher, kept field for field, in Sl. No. order, with each one
printable as a PDF in the form's own layout and the whole register downloadable as Excel."""
import json
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.core.auth import require_erp_read, wo_actor
from app.core.sheets import sheet_response
from app.db import get_db, get_read_db
from app.documents import form_pdf
from app.documents.forms import _field_doc, _pre, form_pdf_response
from app.services.projects import job_or_404

router = APIRouter()


class VoucherLine(BaseModel):
    description: str = ""
    uom: str = ""
    issued_qty: float = 0
    returned_qty: float = 0
    remarks: str = ""


class VoucherIn(BaseModel):
    job_id: int
    voucher_on: Optional[str] = ""
    indented_by: Optional[str] = ""
    issued_by: Optional[str] = ""
    issued_for: Optional[str] = ""
    lines: List[VoucherLine] = []


def _lines(v):
    try:
        out = json.loads(v.lines or "[]")
        return out if isinstance(out, list) else []
    except ValueError:
        return []


def _dict(v, projects):
    lines = _lines(v)
    return {"id": v.id, "job_id": v.job_id, "project": projects.get(v.job_id, ""), "number": v.number or 0,
            "voucher_on": v.voucher_on or "", "indented_by": v.indented_by or "", "issued_by": v.issued_by or "",
            "issued_for": v.issued_for or "", "lines": lines, "recorded_by": v.recorded_by or "",
            "total_issued": round(sum(float(l.get("issued_qty") or 0) for l in lines), 3),
            "total_returned": round(sum(float(l.get("returned_qty") or 0) for l in lines), 3)}


def _projects(db, client_id):
    return {j.id: (("%s %s" % (j.number or "", j.name or "")).strip()) for j in db.query(
        models.DBJob.id, models.DBJob.number, models.DBJob.name).filter(models.DBJob.client_id == client_id).all()}


def _list(db, client_id, job_id):
    q = db.query(models.DBMaterialVoucher).filter(models.DBMaterialVoucher.client_id == client_id,
                                                  models.DBMaterialVoucher.removed == 0)
    if job_id:
        q = q.filter(models.DBMaterialVoucher.job_id == job_id)
    return q.order_by(models.DBMaterialVoucher.number.asc(), models.DBMaterialVoucher.id.asc()).all()


@router.get("/api/material-vouchers")
def voucher_list(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    """Every voucher, in Sl. No. order."""
    client = require_erp_read(request, db)
    projects = _projects(db, client.id)
    vouchers = [_dict(v, projects) for v in _list(db, client.id, job_id)]
    return {"vouchers": vouchers, "summary": {"vouchers": len(vouchers), "lines": sum(len(v["lines"]) for v in vouchers)}}


@router.post("/api/material-vouchers")
def voucher_add(body: VoucherIn, request: Request, db: Session = Depends(get_db)):
    """Record a voucher. Its Sl. No. is the next in the company's sequence."""
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = job_or_404(db, client.id, body.job_id)
    lines = [l for l in body.lines if (l.description or "").strip()]
    if not lines:
        raise HTTPException(400, "Add at least one item, with its description.")
    for n, l in enumerate(lines, 1):
        if l.issued_qty <= 0:
            raise HTTPException(400, "Line %d: the issued quantity." % n)
        if l.returned_qty < 0 or l.returned_qty > l.issued_qty:
            raise HTTPException(400, "Line %d: the returned quantity cannot be more than was issued." % n)
    last = db.query(func.max(models.DBMaterialVoucher.number)).filter(
        models.DBMaterialVoucher.client_id == client.id).scalar() or 0
    v = models.DBMaterialVoucher(
        client_id=client.id, job_id=job.id, number=int(last) + 1,
        voucher_on=(body.voucher_on or date.today().isoformat())[:10],
        indented_by=(body.indented_by or "").strip()[:120], issued_by=(body.issued_by or "").strip()[:120],
        issued_for=(body.issued_for or "").strip()[:200], recorded_by=actor_name,
        lines=json.dumps([{"description": l.description.strip()[:300], "uom": (l.uom or "").strip()[:20],
                           "issued_qty": round(l.issued_qty, 3), "returned_qty": round(l.returned_qty, 3),
                           "remarks": (l.remarks or "").strip()[:300]} for l in lines]))
    db.add(v)
    db.commit()
    return {"voucher": _dict(v, _projects(db, client.id)), "message": "Voucher Sl. No. %d saved." % v.number}


@router.delete("/api/material-vouchers/{vid}")
def voucher_remove(vid: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "site.signoff")
    v = db.query(models.DBMaterialVoucher).filter(models.DBMaterialVoucher.id == vid,
                                                  models.DBMaterialVoucher.client_id == client.id).first()
    if not v or v.removed:
        raise HTTPException(404, "Voucher not found")
    v.removed = 1                       # kept, hidden: the next voucher never takes its Sl. No.
    db.commit()
    return {"message": "Voucher Sl. No. %d removed." % (v.number or 0)}


def _qty(n):
    return form_pdf.qty_text(n) if n else ""


@router.get("/api/material-vouchers/{vid}/document.pdf")
def voucher_pdf(vid: int, request: Request, db: Session = Depends(get_read_db)):
    """The voucher as the printed form: the company's head, MATERIAL ISSUE VOUCHER, the four fields, the items, and
    the four signatures."""
    client = require_erp_read(request, db)
    v = db.query(models.DBMaterialVoucher).filter(models.DBMaterialVoucher.id == vid,
                                                  models.DBMaterialVoucher.client_id == client.id).first()
    if not v or v.removed:
        raise HTTPException(404, "Voucher not found")
    d = _dict(v, _projects(db, client.id))
    rows = [[str(n), l.get("description", ""), l.get("uom", ""), _qty(l.get("issued_qty")), _qty(l.get("returned_qty")),
             l.get("remarks", "")] for n, l in enumerate(d["lines"], 1)]
    blocks = [
        {"type": "pairs", "rows": [("Project Name", d["project"] or "-"), ("Material Indented By", d["indented_by"] or "-"),
                                   ("Issued By", d["issued_by"] or "-"), ("Issued For", d["issued_for"] or "-")],
         "label_width": 46},
        {"type": "table", "columns": [("S.No.", 12, "C"), ("Item Description", 70, "L"), ("Uom", 16, "C"),
                                      ("Issued Qty.", 22, "R"), ("Returned Qty.", 24, "R"), ("Remarks", 38, "L")],
         "rows": rows},
    ]
    sig = [("Indented By", d["indented_by"] or ""), ("Received By", ""), ("Stores", d["issued_by"] or ""),
           ("Authorised Signature", "")]
    name = "MIV-%d" % d["number"]
    return form_pdf_response(_field_doc(db, client, "MATERIAL ISSUE VOUCHER",
                                        [("Sl. No.", str(d["number"])), ("Date", form_pdf.date_text(d["voucher_on"]))],
                                        blocks, sig, name), name)


@router.get("/api/material-vouchers.xlsx")
def voucher_register(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    """The register: every line of every voucher, in Sl. No. order, with the voucher's fields beside it."""
    client = require_erp_read(request, db)
    projects = _projects(db, client.id)
    rows = []
    for v in (_dict(x, projects) for x in _list(db, client.id, job_id)):
        for n, l in enumerate(v["lines"], 1):
            rows.append((v["number"], v["voucher_on"], v["project"], v["indented_by"], v["issued_by"], v["issued_for"], n,
                         l.get("description", ""), l.get("uom", ""), l.get("issued_qty") or 0, l.get("returned_qty") or 0,
                         l.get("remarks", "")))
    return sheet_response(("Sl. No.", "Date", "Project Name", "Material Indented By", "Issued By", "Issued For", "S.No.",
                           "Item Description", "Uom", "Issued Qty.", "Returned Qty.", "Remarks"), rows,
                          "material_issue_vouchers.xlsx", preamble=_pre(client, "MATERIAL ISSUE VOUCHER REGISTER"))
