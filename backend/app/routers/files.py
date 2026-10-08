"""The files endpoints."""
import io
import re
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import defer, Session

from app import models
from app.db import get_db

from app.core.audit import log_audit
from app.core.auth import get_client_user, require_erp_read, require_items_access, session_employee, wo_actor
from app.core.currency import money, sheet_number
from app.core.files import (
    _file_or_404,
    attachment_target,
    file_bytes,
    file_dict,
    file_headers,
    image_data_url,
    served_type,
    store_file,
)
from app.core.serials import allocate_bill_number, next_wo_number
from app.core.sheets import (
    map_headers_with,
    mapping_report,
    read_sheet_rows,
    rows_from,
    sheet_note,
    sheet_response,
)
from app.core.tenant_settings import put_setting
from app.documents.forms import _pre
from app.documents.letterhead import DOC_SIGNATORIES, doc_seal, doc_signatories
from app.services.crm import advance_paid, norm_name
from app.services.files import _check_sheet_rows, _sheet_kind, fy_quarter, sheet_overview


router = APIRouter()


@router.post("/api/erp/sheets/inspect")
async def erp_inspect_sheet(request: Request, file: UploadFile = File(...),
                            sheet: str = Form(""), db: Session = Depends(get_db)):
    """Open any workbook and say what is in it, without saving a thing.

    The step that was missing. Every other route asks you to declare what a
    file is before it will open it, so a file that is not what you thought is
    refused with a message about a column, having read a sheet you never chose.
    """
    require_erp_read(request, db)
    raw = await file.read()
    if len(raw) > 8_000_000:
        raise HTTPException(400, "That file is too large. Split it and upload in parts.")
    return dict(sheet_overview(raw, sheet), filename=file.filename or "")


@router.get("/api/registers/tds")
def tds_register(request: Request, year: str = "", quarter: str = "",
                 db: Session = Depends(get_db)):
    """TDS both ways, by quarter.

    Deducted: what we withheld from the gangs' bills under 194C, which has to
    be deposited by the 7th and filed in the 26Q. Suffered: what our clients
    withheld from our bills, which has to be matched against the 26AS before
    it can be claimed. Two directions, one screen, because both are checked
    against the same calendar.
    """
    client = require_items_access(request, db, "bills.view_all")
    contractors = {c.id: c for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id).all()}
    jobs = {j.id: j for j in db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id).all()}

    def wanted(fy, q):
        return (not year or fy == year) and (not quarter or q == quarter)

    deducted = []
    for b in db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client.id,
            models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all():
        on = (b.certified_at or b.created_at or "")[:10]
        fy, q = fy_quarter(on)
        if not wanted(fy, q) or not (b.tds_amount or 0):
            continue
        con = contractors.get(b.contractor_id)
        deducted.append({
            "date": on, "year": fy, "quarter": q, "bill": b.number or "",
            "deductee": con.company_name if con else "", "pan": (con.pan or "") if con else "",
            "section": "194C", "rate": b.tds_percent or 0,
            "amount_credited": money(b.this_bill), "tds": money(b.tds_amount),
            "paid_on": (b.paid_at or "")[:10], "status": b.status,
            "missing_pan": not (con and (con.pan or "").strip()),
        })

    suffered = []
    for b in db.query(models.DBRABill).filter(
            models.DBRABill.client_id == client.id,
            models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all():
        on = (b.certified_at or b.created_at or "")[:10]
        fy, q = fy_quarter(on)
        if not wanted(fy, q) or not (b.tds_amount or 0):
            continue
        job = jobs.get(b.job_id)
        suffered.append({
            "date": on, "year": fy, "quarter": q, "bill": b.number or "",
            "deductor": job.customer_name if job else "", "project": job.name if job else "",
            "section": "194C", "rate": b.tds_percent or 0,
            "amount_credited": money(b.this_bill), "tds": money(b.tds_amount),
            "status": b.status,
        })

    def by_quarter(rows):
        out = {}
        for r in rows:
            k = "%s %s" % (r["year"], r["quarter"])
            o = out.setdefault(k, {"period": k, "year": r["year"], "quarter": r["quarter"],
                                   "bills": 0, "amount_credited": 0.0, "tds": 0.0})
            o["bills"] += 1
            o["amount_credited"] = money(o["amount_credited"] + r["amount_credited"])
            o["tds"] = money(o["tds"] + r["tds"])
        return sorted(out.values(), key=lambda o: o["period"], reverse=True)

    deducted.sort(key=lambda r: r["date"], reverse=True)
    suffered.sort(key=lambda r: r["date"], reverse=True)
    years = sorted({r["year"] for r in deducted + suffered}, reverse=True)
    return {
        "deducted": deducted, "suffered": suffered,
        "deducted_by_quarter": by_quarter(deducted), "suffered_by_quarter": by_quarter(suffered),
        "years": years,
        "summary": {
            "deducted": money(sum(r["tds"] for r in deducted)),
            "suffered": money(sum(r["tds"] for r in suffered)),
            "deductees_without_pan": len({r["deductee"] for r in deducted if r["missing_pan"]}),
        },
    }


@router.get("/api/registers/guarantees")
def guarantee_register(request: Request, db: Session = Depends(get_db)):
    """Every bank guarantee held against a subcontractor, and when it lapses.

    A guarantee that expires while the defects period is still running is
    worth nothing, and the bank does not write to say so.
    """
    client = require_items_access(request, db, "bills.view_all")
    today = datetime.now().strftime("%Y-%m-%d")
    contractors = {c.id: c for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id).all()}
    rows = []
    for o in db.query(models.DBSubcontractOrder).filter(
            models.DBSubcontractOrder.client_id == client.id,
            models.DBSubcontractOrder.bank_guarantee_applicable.is_(True),
            models.DBSubcontractOrder.status.in_(("APPROVED", "EXECUTED"))).all():
        con = contractors.get(o.contractor_id)
        valid = (o.bank_guarantee_validity or "")[:10]
        days = None
        if valid:
            try:
                days = (datetime.strptime(valid, "%Y-%m-%d") - datetime.now()).days
            except ValueError:
                days = None
        rows.append({
            "order_id": o.id, "order": o.wo_number or "", "contractor": con.company_name if con else "",
            "amount": money(o.bank_guarantee_amount), "valid_until": valid, "days_left": days,
            "completion_date": o.completion_date or "",
            "defect_liability_months": o.defect_liability_months or 0,
            "state": ("no expiry recorded" if days is None else
                      "lapsed" if days < 0 else "lapses within 30 days" if days <= 30 else "in force"),
        })
    rows.sort(key=lambda r: (r["days_left"] is None, r["days_left"] if r["days_left"] is not None else 0))
    return {
        "guarantees": rows,
        "summary": {
            "held": money(sum(r["amount"] for r in rows if r["state"] != "lapsed")),
            "lapsed": len([r for r in rows if r["state"] == "lapsed"]),
            "lapsing_soon": len([r for r in rows if r["state"] == "lapses within 30 days"]),
            "no_expiry": len([r for r in rows if r["days_left"] is None]),
        },
    }


@router.get("/api/registers/advances")
def advance_register(request: Request, db: Session = Depends(get_db)):
    """Mobilisation advances given to the gangs, and how much has come back.

    Summed from the bills, not stored: a cancelled bill gives its recovery
    back without anybody having to remember to.
    """
    client = require_items_access(request, db, "bills.view_all")
    contractors = {c.id: c for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id).all()}
    recovered = {}
    for b in db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client.id,
            models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all():
        recovered[b.order_id] = money(recovered.get(b.order_id, 0.0) + (b.advance_recovery or 0))
    rows = []
    for o in db.query(models.DBSubcontractOrder).filter(
            models.DBSubcontractOrder.client_id == client.id,
            models.DBSubcontractOrder.status.in_(("APPROVED", "EXECUTED"))).all():
        if not (o.mobilization_advance_amount or 0):
            continue
        con = contractors.get(o.contractor_id)
        # Given means paid. The order's figure is what may be paid; until the
        # money goes out there is nothing for the bills to take back.
        agreed = money(o.mobilization_advance_amount)
        given = advance_paid(db, client.id, o.id)
        back = money(recovered.get(o.id, 0.0))
        rows.append({
            "order_id": o.id, "order": o.wo_number or "", "contractor": con.company_name if con else "",
            "agreed": agreed, "not_yet_paid": money(max(0.0, agreed - given)),
            "advance": given, "recovery_percent": o.advance_recovery_percent or 0,
            "recovered": back, "outstanding": money(given - back),
            "percent_recovered": round(back / given * 100, 1) if given else 0.0,
            "secured_by_bg": bool(o.bank_guarantee_applicable),
        })
    rows.sort(key=lambda r: -r["outstanding"])
    return {
        "advances": rows,
        "summary": {
            "agreed": money(sum(r["agreed"] for r in rows)),
            "given": money(sum(r["advance"] for r in rows)),
            "recovered": money(sum(r["recovered"] for r in rows)),
            "outstanding": money(sum(r["outstanding"] for r in rows)),
            "unsecured": money(sum(r["outstanding"] for r in rows if not r["secured_by_bg"])),
        },
    }


@router.post("/api/files")
def upload_file(request: Request, file: UploadFile = File(...), thumb: Optional[UploadFile] = File(None),
                attached_type: str = Form("job"), attached_id: int = Form(0),
                kind: str = Form(""), caption: str = Form(""), taken_on: str = Form(""),
                db: Session = Depends(get_db)):
    """A photo or a document, kept against the record it proves."""
    client, _, actor_name = wo_actor(request, db, "site.record")
    job_id, _locked = attachment_target(db, client.id, attached_type, attached_id)
    data = file.file.read()
    small = thumb.file.read() if thumb is not None else None
    ctype = (file.content_type or "").lower()
    kind = kind if kind in ("photo", "drawing", "document") else (
        "photo" if ctype.startswith("image/") else "document")
    f = store_file(db, client.id, file, data, job_id=job_id, attached_type=attached_type,
                   attached_id=attached_id, kind=kind, caption=caption,
                   taken_on=taken_on or date.today().isoformat(), by=actor_name, thumb=small)
    log_audit(db, client.id, "file_added", attached_type, attached_id, f.name,
              "%s, %d KB" % (f.kind, f.size // 1024), request)
    db.commit()
    return {"file": file_dict(f)}


@router.get("/api/files")
def list_files(request: Request, attached_type: str = "", attached_id: int = 0, job_id: int = 0,
               kind: str = "", q: str = "", date_from: str = "", date_to: str = "", by: str = "",
               db: Session = Depends(get_db)):
    """The files kept against something, filtered the way they are looked
    for: drawings or photos, words in the name or caption, when they were
    taken, who added them."""
    client = require_erp_read(request, db)
    query = db.query(models.DBFile.id, models.DBFile.job_id, models.DBFile.kind, models.DBFile.attached_type,
                     models.DBFile.attached_id, models.DBFile.name, models.DBFile.content_type,
                     models.DBFile.size, models.DBFile.original_size, models.DBFile.blob_of,
                     models.DBFile.caption, models.DBFile.taken_on,
                     models.DBFile.uploaded_by_name, models.DBFile.created_at).filter(
        models.DBFile.client_id == client.id)
    if attached_type:
        types = [t for t in attached_type.split(",") if t]
        query = query.filter(models.DBFile.attached_type.in_(types))
    if attached_id:
        query = query.filter(models.DBFile.attached_id == attached_id)
    if job_id:
        query = query.filter(models.DBFile.job_id == job_id)
    if kind:
        query = query.filter(models.DBFile.kind.in_([k for k in kind.split(",") if k]))
    if q.strip():
        like = "%" + q.strip() + "%"
        query = query.filter(or_(models.DBFile.name.ilike(like), models.DBFile.caption.ilike(like)))
    if date_from:
        query = query.filter(models.DBFile.taken_on >= date_from[:10])
    if date_to:
        query = query.filter(models.DBFile.taken_on <= date_to[:10])
    if by.strip():
        query = query.filter(models.DBFile.uploaded_by_name.ilike("%" + by.strip() + "%"))
    out = []
    for r in query.order_by(models.DBFile.id.desc()).limit(1000).all():
        is_image = (r.content_type or "").startswith("image/")
        out.append({"id": r.id, "job_id": r.job_id, "kind": r.kind, "attached_type": r.attached_type,
                    "attached_id": r.attached_id, "name": r.name or "", "content_type": r.content_type or "",
                    "size": r.size or 0, "original_size": r.original_size or r.size or 0,
                    "shared": bool(r.blob_of),
                    "caption": r.caption or "", "taken_on": r.taken_on or "",
                    "uploaded_by_name": r.uploaded_by_name or "", "created_at": r.created_at or "",
                    "is_image": is_image, "url": "/api/files/%d" % r.id,
                    "thumb_url": "/api/files/%d/thumb" % r.id if is_image else ""})
    # Whether what they are kept against is closed - a signed-off day keeps
    # its photographs, so the window does not offer to remove them.
    locked = False
    if attached_type and attached_id and "," not in attached_type:
        _, locked = attachment_target(db, client.id, attached_type, attached_id)
    stored = sum(0 if f["shared"] else f["size"] for f in out)
    came_in = sum(f["original_size"] for f in out)
    return {"files": out, "locked": locked,
            "summary": {"count": len(out),
                        "drawings": len([f for f in out if f["kind"] == "drawing"]),
                        "photos": len([f for f in out if f["kind"] == "photo"]),
                        "documents": len([f for f in out if f["kind"] == "document"]),
                        "stored_bytes": stored, "saved_bytes": max(0, came_in - stored),
                        "uploaders": sorted({f["uploaded_by_name"] for f in out if f["uploaded_by_name"]})}}


@router.get("/api/files/{fid}")
def get_file(fid: int, request: Request, download: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    f = _file_or_404(db, client.id, fid, bytes_too=True)
    media = served_type(f.content_type)
    inline = not download and media != "application/octet-stream"
    disp = '%s; filename="%s"' % ("inline" if inline else "attachment",
                                  re.sub(r'[^A-Za-z0-9._ -]', "_", f.name or "file"))
    return StreamingResponse(io.BytesIO(file_bytes(db, f) or b""), media_type=media,
                             headers=dict(file_headers(media), **{"Content-Disposition": disp,
                                                                  "Cache-Control": "private, max-age=86400"}))


@router.get("/api/files/{fid}/thumb")
def get_file_thumb(fid: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    # The picture copy only; the full file is read below if there is no copy.
    f = db.query(models.DBFile).options(defer(models.DBFile.data)).filter(
        models.DBFile.id == fid, models.DBFile.client_id == client.id).first()
    if not f:
        raise HTTPException(404, "File not found")
    small = file_bytes(db, f, thumb=True)
    body = small or (file_bytes(db, f) if (f.content_type or "").startswith("image/") else b"")
    media = "image/jpeg" if small else served_type(f.content_type)
    if not media.startswith("image/"):
        media, body = "image/jpeg", b""
    return StreamingResponse(io.BytesIO(body or b""), media_type=media,
                             headers=dict(file_headers(media), **{"Cache-Control": "private, max-age=86400"}))


@router.delete("/api/files/{fid}")
def delete_file(fid: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db)
    f = _file_or_404(db, client.id, fid)
    if f.attached_id:
        _, locked = attachment_target(db, client.id, f.attached_type, f.attached_id)
        if locked:
            raise HTTPException(409, "That photo is on a signed-off diary day. It is part of the "
                                     "record now and stays.")
    if db.query(models.DBDrawingRevision).filter(models.DBDrawingRevision.file_id == f.id).first():
        raise HTTPException(409, "That file is a drawing revision on the register; it stays as issued.")
    log_audit(db, client.id, "file_removed", f.attached_type, f.attached_id or 0, f.name, "", request)
    # Most files are read by no other record: that is found out from ids alone, before any bytes are touched.
    reader_ids = [r[0] for r in db.query(models.DBFile.id).filter(models.DBFile.blob_of == f.id).order_by(models.DBFile.id).all()]
    readers = (db.query(models.DBFile).options(defer(models.DBFile.data), defer(models.DBFile.thumb))
               .filter(models.DBFile.id.in_(reader_ids)).order_by(models.DBFile.id).all()) if reader_ids else []
    if readers:
        # Another record keeps the same file: it becomes the stored copy.
        heir = readers[0]
        heir.data, heir.thumb, heir.blob_of = f.data, f.thumb, None   # (the bytes are read only now, when they have to move)
        for r in readers[1:]:
            r.blob_of = heir.id
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.get("/api/documents/signatories")
def get_doc_signatories(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    sig = doc_signatories(db, client.id)
    seal = doc_seal(db, client.id)
    # The signature images are the owner's to see and change. Staff are told
    # whether one is on file, not handed a copy of somebody's signature.
    owner = session_employee(request, db) is None
    for s in sig.values():
        s["has_image"] = bool(s["image"])
        if not owner:
            s["image"] = ""
    return {"signatories": sig, "seal": seal if owner else "", "has_seal": bool(seal)}


@router.put("/api/documents/signatories")
def save_doc_signatories(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    for key, _, _ in DOC_SIGNATORIES:
        item = (body or {}).get(key) or {}
        for field in ("name", "title"):
            if field not in item:
                continue
            put_setting(db, client.id, "sig_%s_%s" % (key, field), str(item.get(field) or "").strip()[:80])
        if "image" in item:
            put_setting(db, client.id, "sig_%s_image" % key,
                        image_data_url(item.get("image"), "The signature"))
    if "seal" in (body or {}):
        put_setting(db, client.id, "doc_seal_image", image_data_url(body.get("seal"), "The seal"))
    db.commit()
    return {"signatories": doc_signatories(db, client.id), "seal": doc_seal(db, client.id),
            "message": "Saved. Every document signs with these."}


@router.get("/api/sheets/{kind}/template.xlsx")
def sheet_template(kind: str, request: Request, db: Session = Depends(get_db)):
    require_erp_read(request, db)
    spec = _sheet_kind(kind)
    return sheet_response([label for _, label in spec["columns"]], [spec["example"]],
                          "%s_template.xlsx" % kind)


@router.post("/api/sheets/{kind}/read")
async def read_sheet(kind: str, request: Request, file: UploadFile = File(...), sheet: str = Form(""),
                     db: Session = Depends(get_db)):
    """Every row of the sheet, with what is wrong with each. Nothing is saved."""
    client = require_erp_read(request, db)
    spec = _sheet_kind(kind)
    header, body = await read_sheet_rows(file, sheet)
    mapping, unmapped = map_headers_with(header, spec["aliases"])
    fields = set(mapping.values())
    wanted = [k for k, _ in spec["columns"]]
    if not fields & set(wanted):
        raise HTTPException(400, "None of the columns could be read. Download the template to see the headings "
                                 "expected - %s." % ", ".join(label for _, label in spec["columns"]) + sheet_note())
    rows, skipped = [], 0
    for r in rows_from(header, body, mapping):
        row = {k: (r.get(k) or "").strip() for k in wanted}
        for k in spec["numbers"]:
            row[k] = sheet_number(row.get(k))
        # The sheet's own grand total: numbers and no words. Counted, not read as a line.
        words = [k for k in wanted if k not in spec["numbers"] and row.get(k)]
        if not words:
            skipped += 1
            continue
        row["_line"] = r.get("_line")
        rows.append(row)
    if kind == "po_lines":
        master = {i.item_code.upper(): i for i in db.query(models.DBItem).filter(
            models.DBItem.client_id == client.id, models.DBItem.kind == "RM").all()}
        for row in rows:
            it = master.get((row.get("item_code") or "").upper())
            if it:
                row["item_code"] = it.item_code
                row["description"] = row.get("description") or it.item_name
                row["uom"] = row.get("uom") or (it.units_of_measure or "")
    problems = _check_sheet_rows(db, client.id, kind, rows)
    return {"kind": kind, "columns": [{"key": k, "label": l, "number": k in spec["numbers"]} for k, l in spec["columns"]],
            "rows": rows, "problems": {str(k): v for k, v in problems.items()}, "skipped": skipped,
            "read_as": mapping_report(header, mapping),
            "message": "%d row%s read%s." % (len(rows), "" if len(rows) == 1 else "s",
                                             ("; %d total or blank row%s left out" % (skipped, "" if skipped == 1 else "s"))
                                             if skipped else "")}


@router.post("/api/sheets/{kind}/check")
def check_sheet_rows(kind: str, request: Request, body: dict = None, db: Session = Depends(get_db)):
    """The same checks, on rows as edited in the grid."""
    client = require_erp_read(request, db)
    spec = _sheet_kind(kind)
    rows = []
    for r in (body or {}).get("rows") or []:
        row = {k: str(r.get(k) or "").strip() for k, _ in spec["columns"]}
        for k in spec["numbers"]:
            row[k] = sheet_number(r.get(k))
        rows.append(row)
    return {"problems": {str(k): v for k, v in _check_sheet_rows(db, client.id, kind, rows).items()}}


@router.post("/api/sheets/bills/import")
def import_bills(body: dict, request: Request, db: Session = Depends(get_db)):
    """Every row of a bills sheet, as edited in the grid, raised as a Draft
    bill each. Not sent for approval here - each is checked and submitted
    like any other bill, from the Bills screen."""
    client, actor_id, actor_name = wo_actor(request, db, ("accounts.manage", "bills.pay"))
    made = []
    for r in (body or {}).get("rows") or []:
        vendor = str(r.get("vendor_name") or "").strip()
        amount = sheet_number(r.get("amount"))
        if not vendor or amount <= 0:
            continue
        tax = sheet_number(r.get("tax_amount"))
        bill = models.DBBill(
            client_id=client.id, number=allocate_bill_number(db, client.id),
            vendor_name=vendor, issue_date=str(r.get("issue_date") or "").strip() or
            datetime.now().strftime("%Y-%m-%d"), due_date=str(r.get("due_date") or "").strip(),
            amount=money(amount), tax_amount=money(tax), total=money(amount + tax),
            status="Draft", category="general", reference=str(r.get("reference") or "").strip(),
            submitted_by=actor_id, approval_status="none")
        db.add(bill)
        made.append(bill)
    db.flush()
    for bill in made:
        log_audit(db, client.id, "bill_imported", "bill", bill.id, bill.number,
                  "%s, %s" % (bill.vendor_name, bill.total), request, user_name=actor_name)
    db.commit()
    return {"count": len(made), "message": "%d bill%s brought in as drafts - check each before sending it up."
            % (len(made), "" if len(made) == 1 else "s")}


@router.post("/api/sheets/subcontract_orders/import")
def import_subcontract_orders(body: dict, request: Request, db: Session = Depends(get_db)):
    """A register of gangs and dates, brought in as one draft order each - the
    contractor and project matched by name where they are already on file,
    left blank to be picked when they are not, so a mistyped name never
    silently attaches an order to the wrong gang."""
    client, actor_id, actor_name = wo_actor(request, db)
    contractors = {norm_name(c.company_name): c for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id).all()}
    jobs = {norm_name(j.name): j for j in db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id).all()}
    made, unmatched = [], []
    for r in (body or {}).get("rows") or []:
        subject = str(r.get("subject") or "").strip()
        contractor_name = str(r.get("contractor") or "").strip()
        if not subject or not contractor_name:
            continue
        con = contractors.get(norm_name(contractor_name))
        job = jobs.get(norm_name(str(r.get("project") or "").strip()))
        if not con:
            unmatched.append(contractor_name)
        dept = str(r.get("department") or "").strip()
        order = models.DBSubcontractOrder(
            client_id=client.id, status="DRAFT",
            wo_number=next_wo_number(db, client.id, dept, r.get("commencement_date")),
            contractor_id=con.id if con else None, job_id=job.id if job else None,
            department=dept, subject=subject,
            commencement_date=str(r.get("commencement_date") or "").strip(),
            completion_date=str(r.get("completion_date") or "").strip(),
            gst_rate=18.0, tds_rate=1.0, submitted_by=actor_id)
        db.add(order)
        made.append(order)
    db.flush()
    for order in made:
        log_audit(db, client.id, "subcontract_imported", "subcontract_order", order.id,
                  order.wo_number, subject, request, user_name=actor_name)
    db.commit()
    note = (" %d contractor name%s not on file yet - pick one on each before pricing it: %s."
            % (len(unmatched), "" if len(unmatched) == 1 else "s", ", ".join(sorted(set(unmatched))[:5]))) \
        if unmatched else ""
    return {"count": len(made), "message": ("%d order%s brought in as drafts." %
            (len(made), "" if len(made) == 1 else "s")) + note}


@router.get("/api/registers/tds.xlsx")
def tds_export(request: Request, year: str = "", quarter: str = "", db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    d = tds_register(request, year, quarter, db)
    rows = []
    for side, label in (("deducted", "Deducted by us"), ("suffered", "Deducted from us")):
        for r in d.get(side) or []:
            rows.append((label, r.get("date", ""), r.get("quarter", ""), r.get("bill", ""),
                         r.get("deductee") or r.get("deductor") or r.get("party", ""), r.get("pan", ""),
                         r.get("section", ""), r.get("rate", 0), r.get("amount_credited") or r.get("amount", 0),
                         r.get("tds", 0), r.get("paid_on", "") or r.get("status", "")))
    return sheet_response(("Side", "Date", "Quarter", "Bill", "Party", "PAN", "Section", "Rate %", "Amount", "TDS",
                           "Paid / status"), rows, "tds_register.xlsx",
                          preamble=_pre(client, "TDS REGISTER", ("Year", year or "all", "Quarter", quarter or "all")),
                          closing=[(), ("Deducted by us", "", "", "", "", "", "", "", "",
                                        money(sum(r.get("tds", 0) for r in d.get("deducted") or []))),
                                   ("Deducted from us", "", "", "", "", "", "", "", "",
                                    money(sum(r.get("tds", 0) for r in d.get("suffered") or [])))])


@router.get("/api/registers/guarantees.xlsx")
def guarantees_export(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    d = guarantee_register(request, db)
    keys = [k for k in (d["guarantees"][0].keys() if d["guarantees"] else ["number", "bank", "amount", "valid_until", "status"])
            if not k.endswith("_id") and k != "id"]
    rows = [tuple(g.get(k, "") for k in keys) for g in d["guarantees"]]
    return sheet_response(tuple(k.replace("_", " ").title() for k in keys), rows, "guarantees.xlsx",
                          preamble=_pre(client, "BANK GUARANTEES"))


@router.get("/api/registers/advances.xlsx")
def advances_export(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    d = advance_register(request, db)
    rows = [(a["order"], a["contractor"], a["agreed"], a["advance"], a["recovery_percent"], a["recovered"],
             a["outstanding"], a["percent_recovered"]) for a in d["advances"]]
    return sheet_response(("Order", "Contractor", "Agreed", "Paid", "Recovery %", "Recovered", "Still to recover",
                           "% recovered"), rows, "advances.xlsx", preamble=_pre(client, "MOBILISATION ADVANCES"),
                          closing=[(), ("Total", "", money(sum(a["agreed"] for a in d["advances"])),
                                        money(sum(a["advance"] for a in d["advances"])), "",
                                        money(sum(a["recovered"] for a in d["advances"])),
                                        money(sum(a["outstanding"] for a in d["advances"])))])
