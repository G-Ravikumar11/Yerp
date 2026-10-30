"""The boq endpoints."""
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.core.fastjson import fast_json
from sqlalchemy.orm import Session

from app import models
from app.db import get_db, get_read_db

from app.constants.boq import BOQ_IMPORT_ALIASES, BOQ_PRICED, BOQ_RATE_ONLY_WORDS, BV_TRANSITIONS
from app.core.audit import log_audit
from app.core.auth import require_erp_read, require_items_access, wo_actor
from app.core.currency import inr, money, sheet_number, unit_rate
from app.core.notifications import notify, notify_employee
from app.core.serials import next_sequence_number
from app.core.sheets import (
    map_headers_with,
    mapping_report,
    read_sheet_rows,
    rows_from,
    sheet_note,
    sheet_response,
)
from app.documents.forms import _pre
from app.routers.client_orders import erp_build_work_order
from app.schemas.boq import BoqVariationIn, ProjectBoqIn, ProjectBoqLinesIn
from app.schemas.client_orders import DocLineIn, WorkOrderIn
from app.services.approvals import owner_label
from app.services.boq import (
    boq_client_orders,
    boq_given_to_contractors,
    boq_link_orders,
    boq_head,
    boq_heads,
    boq_kind_of,
    boq_lines_with_subtotals,
    boq_new_key,
    boq_or_404,
    boq_revision_of,
    boq_revisions_list,
    boq_save_lines,
    boq_summary,
    boq_tracker_data,
    boq_variation_or_404,
    bv_apply,
    bv_current_step,
    bv_decide,
    bv_dict,
    bv_next_number,
    bv_start_chain,
    bv_write_lines,
)
from app.services.boq_outline import boq_outline, rate_suggestions
from app.services.crm import estimate_or_404
from app.services.projects import job_or_404
from app.services.subcontract_billing import past_tense, sub_bill_step_name


router = APIRouter()


@router.get("/api/wo/boq/template")
def wo_boq_template(request: Request, db: Session = Depends(get_read_db)):
    """The shape we can read, as a workbook to fill in."""
    require_erp_read(request, db)
    return sheet_response(
        ["Activity No", "Item Code", "Description of work", "Material", "Specification",
         "UOM", "Quantity", "Rate"],
        [["1.0", "CIV-RMC-25",
          "M25 grade RMC pouring for raft, including pumping and vibrating", "M25",
          "Cube strength 25 MPa at 28 days, 14-day curing", "cum", 840, 6420]],
        "boq_template.xlsx")


@router.get("/api/boqs/sample.xlsx")
def boq_sample_sheet(request: Request, db: Session = Depends(get_read_db)):
    """A filled-in sample in exactly the shape the BOQ import reads: headings in capitals, priced lines under them,
    a group code on each, and rate-only (R/o) lines. Fill it in, or import it as it is to see how a BOQ comes in."""
    require_erp_read(request, db)
    sub, sup, fin = "SUB STRUCTURE WORKS", "SUPER STRUCTURE WORKS", "FINISHING WORKS"
    return sheet_response(
        ["Group code", "Item code", "Description", "Material", "Unit", "Quantity", "Rate", "Amount"],
        [["", "", "PLAIN CEMENT CONCRETE", "", "", "", "", ""],
         [sub, "", "PCC M10 (1:3:6) below footings", "M10", "Cum", 277, 5230, 1448710],
         [sub, "", "PCC M10 flooring bed", "M10", "Cum", 764, 5230, 3995720],
         ["", "", "REINFORCED CEMENT CONCRETE", "", "", "", "", ""],
         [sub, "", "RCC footings", "M30", "Cum", 809, 6064, 4905776],
         [sup, "", "RCC podium slab", "M40", "Cum", 762, 6592, 5023104],
         ["", "", "REINFORCEMENT STEEL", "", "", "", "", ""],
         [sub, "", "Reinforcement steel in footings", "Fe550/550D", "MT", 133.05, 73900, 9832395],
         ["", "", "MASONRY AND PLASTERING", "", "", "", "", ""],
         [fin, "", "Solid concrete block masonry 150mm in CM 1:6", "", "Sqm", 3333, 1350, 4499550],
         [fin, "", "External plastering 20mm in CM 1:6, two coats", "", "Sqm", "R/o", 740, ""],
         ["ELECTRICAL WORKS", "", "Conduiting and wiring for common areas", "", "LS", 1, 850000, 850000],
         ["PLUMBING WORKS", "", "CPVC water supply lines, 25mm", "", "Rmt", 1200, 420, 504000]],
        "sample_boq.xlsx")


@router.get("/api/boqs/materials")
def boq_materials(request: Request, db: Session = Depends(get_read_db)):
    """Every material or grade that has been put on any of this business's BOQ lines, for the Material dropdown: an
    item added once is on the list from then on, on every BOQ."""
    client = require_erp_read(request, db)
    rows = db.query(models.DBBoqLine.material).join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id).filter(
        models.DBBoq.client_id == client.id, models.DBBoqLine.material.isnot(None), models.DBBoqLine.material != "").distinct().all()
    return {"materials": sorted({r[0].strip() for r in rows if r[0] and r[0].strip()}, key=str.lower)}


@router.get("/api/boqs")
def boq_list(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    rows = db.query(models.DBBoq).filter(models.DBBoq.client_id == client.id).order_by(models.DBBoq.id.desc()).all()
    return {"boqs": boq_heads(db, rows)}


@router.post("/api/boqs")
def boq_create(body: ProjectBoqIn, request: Request, db: Session = Depends(get_db)):
    # A project's BOQ is opened at head office, by HO QS (or the Master).
    client, _, actor_name = wo_actor(request, db, "boq.create")
    job = job_or_404(db, client.id, body.job_id)
    if db.query(models.DBBoq).filter(models.DBBoq.client_id == client.id, models.DBBoq.job_id == job.id).first():
        raise HTTPException(409, "%s already has a BOQ. Open it, or add a revision." % job.name)
    boq = models.DBBoq(client_id=client.id, job_id=job.id, number=next_sequence_number(db, models.DBBoq, client.id, "BOQ-"),
                       title=(body.title or "").strip() or ("BOQ - %s" % job.name), created_by_name=actor_name)
    db.add(boq)
    db.flush()
    db.add(models.DBBoqRevision(boq_id=boq.id, rev_no=0, label="R0 - Tender", status="OPEN", created_by_name=actor_name))
    log_audit(db, client.id, "boq_created", "boq", boq.id, boq.number, job.name, request)
    boq_link_orders(db, boq)
    db.commit()
    return {"boq": boq_head(db, boq), "message": "%s opened for %s." % (boq.number, job.name)}


@router.get("/api/boqs/{boq_id}")
def boq_get(boq_id: int, request: Request, rev: Optional[int] = None, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    boq = boq_or_404(db, client.id, boq_id)
    revision = boq_revision_of(db, boq, rev)
    lines, total = boq_lines_with_subtotals(db, revision)
    return fast_json({"boq": boq_head(db, boq, revision), "revisions": boq_revisions_list(db, boq), "lines": lines, "total": total,
                      "editable": revision.status == "OPEN" and revision.rev_no == boq.current_rev})


@router.get("/api/boqs/{boq_id}/summary")
def boq_get_summary(boq_id: int, request: Request, rev: Optional[int] = None, gst: float = 18.0,
                    db: Session = Depends(get_db)):
    """Section totals, then the total, GST and total with GST: the front page of the BOQ."""
    client = require_erp_read(request, db)
    boq = boq_or_404(db, client.id, boq_id)
    revision = boq_revision_of(db, boq, rev)
    return fast_json({"boq": boq_head(db, boq, revision), **boq_summary(db, revision, gst)})


@router.put("/api/boqs/{boq_id}/lines")
def boq_set_lines(boq_id: int, body: ProjectBoqLinesIn, request: Request, db: Session = Depends(get_db)):
    """Save the BOQ as it is on screen: the lines are replaced as a whole, as the grid holds them."""
    client, _, _ = wo_actor(request, db)
    boq = boq_or_404(db, client.id, boq_id)
    rev = boq_revision_of(db, boq)
    if rev.status != "OPEN":
        raise HTTPException(409, "%s is issued and cannot be changed. Start a new revision to change it." % (rev.label or "R%d" % rev.rev_no))
    if len(body.lines) > 5000:
        raise HTTPException(400, "A BOQ of more than 5,000 lines is split by section before it is saved.")
    kept, issued = boq_save_lines(db, boq, rev, body.lines, bool(body.issue_codes), client.id)
    log_audit(db, client.id, "boq_saved", "boq", boq.id, boq.number, "%d lines" % len(kept), request)
    db.commit()
    lines, total = boq_lines_with_subtotals(db, rev)
    return {"boq": boq_head(db, boq, rev), "lines": lines, "total": total,
            "message": "%d line%s saved, %s%s." % (len(kept), "" if len(kept) == 1 else "s", inr(total),
                                                     (" - %d item code%s given" % (issued, "" if issued == 1 else "s")) if issued else "")}


@router.post("/api/boqs/{boq_id}/revisions")
def boq_new_revision(boq_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    """Issue the revision being worked on (locking it) and open the next one as a copy."""
    client, _, actor_name = wo_actor(request, db)
    boq = boq_or_404(db, client.id, boq_id)
    cur = boq_revision_of(db, boq)
    if cur.status == "OPEN":
        cur.status = "ISSUED"
        cur.issued_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if (body.get("issued_label") or "").strip():
            cur.label = body["issued_label"].strip()[:60]
    nxt = models.DBBoqRevision(boq_id=boq.id, rev_no=cur.rev_no + 1, status="OPEN", created_by_name=actor_name,
                               label=((body.get("label") or "").strip()[:60] or "R%d" % (cur.rev_no + 1)),
                               note=(body.get("note") or "").strip())
    db.add(nxt)
    db.flush()
    for l in db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == cur.id).order_by(models.DBBoqLine.display_order).all():
        db.add(models.DBBoqLine(boq_id=boq.id, revision_id=nxt.id, key=l.key, kind=l.kind, item_no=l.item_no, group_code=l.group_code, description=l.description,
                                uom=l.uom, quantity=l.quantity, rate=l.rate, amount=l.amount,
                                item_code=l.item_code, remarks=l.remarks, material=l.material, rate_only=l.rate_only,
                                display_order=l.display_order))
    boq.current_rev = nxt.rev_no
    log_audit(db, client.id, "boq_revised", "boq", boq.id, boq.number, nxt.label, request)
    db.commit()
    return {"boq": boq_head(db, boq, nxt), "message": "%s issued. %s is open for changes." % (cur.label or "R%d" % cur.rev_no, nxt.label)}


@router.get("/api/boqs/{boq_id}/changes")
def boq_changes(boq_id: int, request: Request, frm: int = 0, to: Optional[int] = None, db: Session = Depends(get_read_db)):
    """What changed between two revisions: lines added, removed, and changed in quantity, rate or words."""
    client = require_erp_read(request, db)
    boq = boq_or_404(db, client.id, boq_id)
    a, b = boq_revision_of(db, boq, frm), boq_revision_of(db, boq, to)
    get = lambda rev: {l.key: l for l in db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).all()}
    old, new = get(a), get(b)
    label = lambda l: ("%s %s" % (l.group_code or "", (l.description or "").split("\n")[0][:70])).strip()
    out = []
    for k, l in new.items():
        if k not in old:
            out.append({"change": "added", "line": label(l), "amount": money(l.amount)})
            continue
        o, diffs = old[k], []
        for field, name in (("quantity", "quantity"), ("rate", "rate"), ("description", "description"), ("uom", "unit")):
            if (getattr(o, field) or "") != (getattr(l, field) or ""):
                diffs.append("%s %s -> %s" % (name, getattr(o, field), getattr(l, field)))
        if diffs:
            out.append({"change": "changed", "line": label(l), "detail": "; ".join(diffs), "amount": money(l.amount - o.amount)})
    for k, l in old.items():
        if k not in new:
            out.append({"change": "removed", "line": label(l), "amount": -money(l.amount)})
    return {"from": a.label or "R%d" % a.rev_no, "to": b.label or "R%d" % b.rev_no, "changes": out,
            "difference": money(sum(c["amount"] for c in out))}


@router.post("/api/boqs/{boq_id}/import")
async def boq_import(boq_id: int, request: Request, file: UploadFile = File(...), sheet: str = Form(""),
                     db: Session = Depends(get_db)):
    """Read the client's BOQ sheet as they sent it and hand it back as lines, without saving: they land in the grid to be
    read against the file, and the ordinary save commits them. The sheet's own amounts are checked against its lines."""
    client, _, _ = wo_actor(request, db)
    boq = boq_or_404(db, client.id, boq_id)
    if boq_revision_of(db, boq).status != "OPEN":
        raise HTTPException(409, "Open a new revision first: the current one is issued.")
    header, body = await read_sheet_rows(file, sheet)
    mapping, unmapped = map_headers_with(header, BOQ_IMPORT_ALIASES)
    # A client's sheet often has a title block above its headings: the heading row is the first that names both a
    # description and a quantity.
    if not {"description", "quantity"} <= set(mapping.values()):
        everything = [(0, header)] + list(body)
        for at, (_, row) in enumerate(everything[:40]):
            m, u = map_headers_with(row, BOQ_IMPORT_ALIASES)
            if {"description", "quantity"} <= set(m.values()):
                header, mapping, unmapped, body = row, m, u, everything[at + 1:]
                break
    fields = set(mapping.values())
    if "description" not in fields or "quantity" not in fields:
        raise HTTPException(400, "No description and quantity columns found. Expected headings such as 'Description of work' "
                                 "and 'Qty'. Found: %s.%s" % (", ".join(sorted(fields)) or "nothing", sheet_note()))
    lines, warnings, skipped, running = [], [], 0, 0.0
    for row in rows_from(header, body, mapping):
        text = (row.get("description") or "").strip()
        qty, rate = money(sheet_number(row.get("quantity"))), unit_rate(sheet_number(row.get("rate")))
        stated = sheet_number(row.get("amount")) if row.get("amount") else None
        # "R/o" where the quantity should be: the rate is agreed, the quantity is not.
        rate_only = bool(rate) and re.sub(r"\s+", "", str(row.get("quantity") or "")).lower() in BOQ_RATE_ONLY_WORDS
        if rate_only:
            qty, stated = 0.0, None
        if not text:
            skipped += 1
            continue
        if re.match(r"^(grand\s+)?total\b|^sub\s*-?\s*total\b|^carried|^brought", text.lower()):
            if stated and re.match(r"^grand", text.lower()) and abs(stated - running) > 1:
                warnings.append("The sheet's grand total is %s but its lines come to %s." % (inr(stated), inr(running)))
            skipped += 1
            continue
        if stated and not rate and qty:
            rate = unit_rate(stated / qty)           # a sheet with an amount and no rate: the rate is what it implies
        no = (row.get("item_no") or "").strip()[:20]
        # A numbered line with no quantity is a heading of the client's tree (2.1 "Excavation in all kinds of soil ..."),
        # however long it runs; only an unnumbered one can be a note.
        kind = "section" if no and not (qty or rate or rate_only) else boq_kind_of(text, qty, rate)
        rate_only = rate_only and kind in BOQ_PRICED
        if kind in BOQ_PRICED and not rate_only:
            running += qty * rate
            if stated and abs(stated - qty * rate) > 1:
                warnings.append("Row %s: %s x %s is %s but the sheet says %s." % (
                    row.get("_line"), qty, rate, inr(qty * rate), inr(stated)))
        lines.append({"key": "", "kind": kind, "item_no": no, "group_code": (row.get("group_code") or "").strip()[:40], "description": text,
                      "uom": (row.get("uom") or "").strip() if kind in BOQ_PRICED else "", "quantity": qty if kind in BOQ_PRICED else 0,
                      "rate": rate if kind in BOQ_PRICED else 0, "amount": money(qty * rate) if kind in BOQ_PRICED else 0,
                      "item_code": (row.get("item_code") or "").strip().upper()[:40] if kind in BOQ_PRICED else "", "remarks": (row.get("remarks") or "").strip(),
                      "material": (row.get("material") or "").strip()[:60] if kind in BOQ_PRICED else "", "rate_only": rate_only})
    if not any(l["kind"] in BOQ_PRICED for l in lines):
        raise HTTPException(400, "Nothing on that sheet read as a priced line." + sheet_note())
    return {"lines": lines[:5000], "read_as": mapping_report(header, mapping), "ignored_columns": unmapped,
            "skipped_rows": skipped, "warnings": warnings[:50], "total": money(running),
            "message": "%d line(s) read, %s. Check them against the sheet, then save." % (len(lines), inr(running))}


@router.post("/api/boqs/from-estimate/{estimate_id}")
def boq_from_estimate(estimate_id: int, request: Request, db: Session = Depends(get_db)):
    """A tender that was won becomes the project's BOQ, R0: its items, quantities and quoted rates.
    Opening a BOQ is HO QS's, however it starts."""
    client, _, actor_name = wo_actor(request, db, "boq.create")
    est = estimate_or_404(db, client.id, estimate_id)
    if not est.job_id:
        raise HTTPException(409, "Attach the tender to its project first.")
    if db.query(models.DBBoq).filter(models.DBBoq.client_id == client.id, models.DBBoq.job_id == est.job_id).first():
        raise HTTPException(409, "That project already has a BOQ.")
    boq = models.DBBoq(client_id=client.id, job_id=est.job_id, number=next_sequence_number(db, models.DBBoq, client.id, "BOQ-"),
                       title=est.title or "BOQ", created_by_name=actor_name)
    db.add(boq)
    db.flush()
    rev = models.DBBoqRevision(boq_id=boq.id, rev_no=0, label="R0 - Tender %s" % (est.number or ""), status="OPEN", created_by_name=actor_name)
    db.add(rev)
    db.flush()
    n = 0
    for i in db.query(models.DBEstimateItem).filter(models.DBEstimateItem.estimate_id == est.id).order_by(
            models.DBEstimateItem.display_order, models.DBEstimateItem.id).all():
        qty, rate = money(i.quantity), unit_rate(i.quoted_rate)
        db.add(models.DBBoqLine(boq_id=boq.id, revision_id=rev.id, key=boq_new_key(), kind="item",
                                description=i.description or "", uom=i.uom or "", quantity=qty, rate=rate,
                                amount=money(qty * rate), item_code=(i.fg_code or "").upper(), display_order=n))
        n += 1
    boq_link_orders(db, boq)
    log_audit(db, client.id, "boq_from_tender", "boq", boq.id, boq.number, est.number or "", request)
    db.commit()
    return {"boq": boq_head(db, boq, rev), "message": "%s opened from %s with %d lines." % (boq.number, est.number, n)}


@router.post("/api/boqs/{boq_id}/client-order")
def boq_make_client_order(boq_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    """The client's work order, drawn from the BOQ: its priced lines, in the item codes the BOQ gave them.
    A new work order, so HO QS's to open."""
    client = require_items_access(request, db, "workorders.create")
    boq = boq_or_404(db, client.id, boq_id)
    made = next((w for w in boq_client_orders(db, boq) if w.status != "Rejected"), None)
    if made:
        raise HTTPException(409, "%s is already the client's work order for this project, against this BOQ." % made.number)
    rev = boq_revision_of(db, boq)
    priced = [l for l in db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id,
                                                          models.DBBoqLine.kind.in_(BOQ_PRICED)).order_by(models.DBBoqLine.display_order).all()
              if (l.quantity or 0) > 0]
    if not priced:
        raise HTTPException(409, "The BOQ has no priced lines yet.")
    missing = [l for l in priced if not l.item_code]
    if missing:
        raise HTTPException(409, "%d line%s still without an item code (first: %s). Save the BOQ with 'give new lines item codes' first."
                            % (len(missing), " is" if len(missing) == 1 else "s are", missing[0].description[:30]))
    out = erp_build_work_order(WorkOrderIn(
        job_id=boq.job_id, reference=(body.get("reference") or "")[:60], notes=(body.get("notes") or "").strip() or "From %s %s" % (boq.number, rev.label or ""),
        lines=[DocLineIn(code=l.item_code, qty=l.quantity, rate=l.rate, description=(l.description or "").split("\n")[0][:300]) for l in priced]),
        request, db)
    wo = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id == out["work_order"]["id"]).first()
    wo.boq_id = boq.id
    db.commit()
    return {"work_order": out["work_order"], "message": "%s created from %s." % (wo.number, boq.number)}


@router.get("/api/boqs/{boq_id}/available")
def boq_available(boq_id: int, request: Request, db: Session = Depends(get_db)):
    """The BOQ's priced lines with how much of each is still to be given to a contractor - for adding lines to an order."""
    client = require_erp_read(request, db)
    boq = boq_or_404(db, client.id, boq_id)
    rev = boq_revision_of(db, boq)
    given = boq_given_to_contractors(db, client.id)
    lines = db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).order_by(
        models.DBBoqLine.display_order, models.DBBoqLine.id).all()
    # Every heading over a line, main and sub, with the text written under it; and a contractor rate to start from.
    heads, path, _place = boq_outline(lines)
    suggest = rate_suggestions(db, client.id, boq.job_id, {l.key for l in lines if l.kind in BOQ_PRICED})
    rows = []
    for l in lines:
        if l.kind == "section":
            h = heads[l.key]
            rows.append({"kind": "section", "key": l.key, "item_no": h["item_no"], "group_code": h["group_code"],
                         "description": l.description, "level": h["level"], "path": h["path"], "notes": "\n".join(h["notes"])})
        elif l.kind in BOQ_PRICED:
            g = given.get(l.key, {"qty": 0.0})
            rate, source = suggest.get(l.key, (0.0, ""))
            rows.append({"kind": l.kind, "key": l.key, "item_no": l.item_no or "", "group_code": l.group_code or "",
                         "description": l.description, "uom": l.uom or "", "material": l.material or "", "remarks": l.remarks or "",
                         "item_code": l.item_code or "", "quantity": money(l.quantity), "rate": unit_rate(l.rate),
                         "given": money(g["qty"]), "left": money(max(0.0, (l.quantity or 0) - g["qty"])),
                         "path": path.get(l.key, []), "suggested_rate": rate, "rate_from": source})
    return {"boq": boq_head(db, boq, rev), "lines": rows}


@router.get("/api/boqs/{boq_id}/tracker")
def boq_tracker(boq_id: int, request: Request, db: Session = Depends(get_db)):
    """Per BOQ line: the client's quantity and rate, what the contractors have been given (and at what rate), what they have
    executed and billed, what the client has been billed, and the flags worth looking at."""
    client = require_items_access(request, db, ("reports.view",))
    return fast_json(boq_tracker_data(db, client, boq_or_404(db, client.id, boq_id)))


@router.get("/api/boqs/{boq_id}/export.xlsx")
def boq_export(boq_id: int, request: Request, rev: Optional[int] = None, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    boq = boq_or_404(db, client.id, boq_id)
    revision = boq_revision_of(db, boq, rev)
    lines, total = boq_lines_with_subtotals(db, revision)
    head = boq_head(db, boq, revision)
    summary = boq_summary(db, revision)
    rows = []
    for l in lines:
        if l["kind"] == "section":
            rows.append((l["group_code"], "", l["description"].upper(), "", "", "", "", l["subtotal"], l["remarks"]))
        elif l["kind"] == "note":
            rows.append(("", "", l["description"], "", "", "", "", "", l["remarks"]))
        else:
            rows.append((l["group_code"], l["item_code"], l["description"], l["material"], l["uom"],
                         "R/o" if l["rate_only"] else l["quantity"], l["rate"], "" if l["rate_only"] else l["amount"], l["remarks"]))
    return sheet_response(("Group code", "Item code", "Description", "Material", "UoM", "Qty", "Rate", "Amount", "Remarks"), rows,
                          "boq_%s.xlsx" % re.sub(r"[^A-Za-z0-9]+", "_", head["number"]),
                          preamble=_pre(client, "BILL OF QUANTITIES", ("Project", head["project"]), ("Revision", head["revision"]),
                                        ("BOQ", head["number"])),
                          logo_watermark=True,
                          closing=[(), ("Total", "", "", "", "", "", "", total, ""),
                                   ("GST @%g%%" % summary["gst_percent"], "", "", "", "", "", "", summary["gst"], ""),
                                   ("Total incl. GST", "", "", "", "", "", "", summary["total_with_gst"], "")])


@router.get("/api/boq-variations")
def bv_list(request: Request, boq_id: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBBoqVariation).filter(models.DBBoqVariation.client_id == client.id)
    if boq_id:
        q = q.filter(models.DBBoqVariation.boq_id == boq_id)
    rows = [bv_dict(db, v) for v in q.order_by(models.DBBoqVariation.id.desc()).limit(300).all()]
    return {"variations": rows, "summary": {
        "raised": len(rows), "awaiting_approval": len([r for r in rows if r["status"] == "SUBMITTED"]),
        "approved_value": money(sum(r["value"] for r in rows if r["status"] == "APPROVED")),
        "pending_value": money(sum(r["value"] for r in rows if r["status"] in ("DRAFT", "SUBMITTED")))}}


@router.get("/api/boq-variations/suggest/{boq_id}")
def bv_suggest(boq_id: int, request: Request, db: Session = Depends(get_db)):
    """The lines the work already done calls for: every BOQ line executed past its quantity, at its rate."""
    client = require_items_access(request, db, ("reports.view", "workorders.manage"))
    boq = boq_or_404(db, client.id, boq_id)
    out = []
    for r in boq_tracker_data(db, client, boq)["rows"]:
        if r["kind"] in BOQ_PRICED and "over_executed" in (r.get("flags") or []):
            done = max(r["executed"], r["client_executed"])
            extra = money(done - r["quantity"])
            out.append({"kind": "quantity", "boq_key": r["key"], "description": r["description"], "uom": r["uom"],
                        "old_qty": r["quantity"], "change_qty": extra, "rate": r["rate"], "amount": money(extra * r["rate"])})
    return {"lines": out, "value": money(sum(l["amount"] for l in out))}


@router.post("/api/boq-variations")
def bv_create(body: BoqVariationIn, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db)
    boq = boq_or_404(db, client.id, body.boq_id or 0)
    rev = boq_revision_of(db, boq)
    if not db.query(models.DBBoqLine.id).filter(models.DBBoqLine.revision_id == rev.id, models.DBBoqLine.kind.in_(BOQ_PRICED)).first():
        raise HTTPException(409, "The BOQ has no priced lines yet - there is nothing to vary.")
    number, seq = bv_next_number(db, boq)
    vo = models.DBBoqVariation(client_id=client.id, boq_id=boq.id, job_id=boq.job_id, number=number, sequence=seq, status="DRAFT",
                               reason=(body.reason or "").strip(), basis_rev=boq.current_rev, raised_by=actor_id, raised_by_name=actor_name)
    db.add(vo)
    db.flush()
    bv_write_lines(db, boq, vo, body.lines)
    log_audit(db, client.id, "boq_variation_raised", "boq", boq.id, boq.number, "%s %s" % (number, inr(vo.value)), request)
    db.commit()
    return {"variation": bv_dict(db, vo, detail=True), "message": "%s drawn up - %s." % (number, inr(vo.value))}


@router.get("/api/boq-variations/{vid}")
def bv_get(vid: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return bv_dict(db, boq_variation_or_404(db, client.id, vid), detail=True)


@router.put("/api/boq-variations/{vid}")
def bv_update(vid: int, body: BoqVariationIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db)
    vo = boq_variation_or_404(db, client.id, vid)
    if (vo.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Only a draft variation can be changed. Send it back first.")
    boq = boq_or_404(db, client.id, vo.boq_id)
    vo.reason = (body.reason or "").strip()
    vo.basis_rev = boq.current_rev
    bv_write_lines(db, boq, vo, body.lines)
    db.commit()
    return {"variation": bv_dict(db, vo, detail=True), "message": "%s saved - %s." % (vo.number, inr(vo.value))}


@router.delete("/api/boq-variations/{vid}")
def bv_delete(vid: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db)
    vo = boq_variation_or_404(db, client.id, vid)
    if (vo.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Only a draft can be deleted. Cancel it instead.")
    db.query(models.DBBoqVariationLine).filter(models.DBBoqVariationLine.variation_id == vo.id).delete()
    db.delete(vo)
    db.commit()
    return {"ok": True, "message": "Draft removed."}


@router.post("/api/boq-variations/{vid}/{action}")
def act_on_boq_variation(vid: int, action: str, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, ("workorders.manage", "subcontracts.approve"))
    vo = boq_variation_or_404(db, client.id, vid)
    boq = boq_or_404(db, client.id, vo.boq_id)
    move = (action or "").upper()
    allowed = BV_TRANSITIONS.get(vo.status or "DRAFT", {})
    if move not in allowed:
        raise HTTPException(409, "A %s variation cannot be %s." % ((vo.status or "draft").lower(), past_tense(move)))
    body = body or {}
    comments = (body.get("comments") or "").strip()
    require_items_access(request, db, "subcontracts.approve" if move in ("APPROVE", "REJECT") else "workorders.manage")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if move == "SUBMIT":
        if not db.query(models.DBBoqVariationLine.id).filter(models.DBBoqVariationLine.variation_id == vo.id).first():
            raise HTTPException(409, "There is nothing on this variation to submit.")
        bv_start_chain(db, client.id, vo, actor_id)
        vo.raised_by, vo.raised_by_name = actor_id, actor_name if actor_id else (vo.raised_by_name or actor_name)
    elif move == "REJECT":
        if not comments:
            raise HTTPException(400, "Say why it is going back.")
        bv_decide(db, client, vo, actor_id, actor_name, False, comments)
        vo.rejection_reason = comments
    elif move == "APPROVE":
        if not bv_decide(db, client, vo, actor_id, actor_name, True, comments):
            vo.updated_at = now
            db.commit()
            step = bv_current_step(db, vo)
            return {"ok": True, "variation": bv_dict(db, vo, detail=True),
                    "message": "Signed. %s now waits with %s." % (vo.number, sub_bill_step_name(db, step))}
        bv_apply(db, client, boq, vo)
        vo.approved_by_name = actor_name if actor_id else owner_label(db, client.id)
        vo.approved_at = now
    was, vo.status = vo.status, allowed[move]
    vo.updated_at = now
    log_audit(db, client.id, "boq_variation_%s" % move.lower(), "boq", boq.id, vo.number or "", "%s -> %s %s" % (was, vo.status, comments), request)
    db.commit()
    if move in ("SUBMIT", "APPROVE"):
        step = bv_current_step(db, vo) if move == "SUBMIT" else None
        notify(db, client.id, "boq_variation_submitted" if move == "SUBMIT" else "boq_variation_approved",
               ("%s is waiting for approval" if move == "SUBMIT" else "%s agreed - the BOQ is now %s") % ((vo.number,) if move == "SUBMIT" else (vo.number, "R%d" % boq.current_rev)),
               "%s of change to %s." % (inr(vo.value), boq.number), view="boq-view", ref_type="boq_variation", ref_id=vo.id,
               severity="action" if move == "SUBMIT" else "money")
        if step is not None and step.approver_id:
            notify_employee(db, client.id, step.approver_id, "BOQ variation awaiting your approval",
                            "%s - %s." % (vo.number, inr(vo.value)), link="/next/approvals")
        db.commit()
    db.refresh(vo)
    return {"ok": True, "variation": bv_dict(db, vo, detail=True),
            "message": "%s is now %s%s." % (vo.number, vo.status.lower(), (" - the BOQ is " + (boq_revision_of(db, boq).label or "")) if move == "APPROVE" else "")}
