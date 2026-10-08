"""The items endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.items import BOM_COLUMNS, BOM_HEADERS, ITEM_COLUMNS, ITEM_HEADERS
from app.core.audit import log_audit
from app.core.auth import require_erp_read, require_items_access, require_workorder_access
from app.core.currency import money, unit_rate
from app.core.serials import CODE_ALPHABET, CODE_LENGTH, encode_serial, normalise_code
from app.core.sheets import (
    BOM_HEADER_ALIASES,
    HEADER_ALIASES,
    map_headers_with,
    mapping_report,
    parse_sheet,
    read_sheet_rows,
    rows_from,
    sheet_note,
    sheet_response,
)
from app.core.units import CATEGORY_BY_KIND, ITEM_KINDS, ITEM_TYPES, UNITS_OF_MEASURE, canonical_unit
from app.schemas.items import BomIn, ItemBulkIn, ItemCommitIn, ItemIn, MDDecision
from app.services.approvals import set_approval_display_status
from app.services.items import (
    build_item,
    codes_in_use,
    detect_row_kind,
    issue_item_code,
    item_row,
    map_headers,
    repair_row,
)
from app.services.subcontract_orders import work_order_or_404, work_order_to_dict
from app.validators.common import check_item_row, validate_bom_sheet, validate_items


router = APIRouter()


@router.get("/api/erp/items/template")
def erp_item_template(kind: str = "RM", request: Request = None,
                      db: Session = Depends(get_db)):
    require_items_access(request, db)
    kind = kind.upper()
    if kind not in ITEM_KINDS:
        raise HTTPException(400, "kind must be RM or FG")
    prefix = "RM" if kind == "RM" else "FG"
    sample = [[f"{prefix}0001", "20MM LMS PVC ISI CONDUIT", "", "20MM LMS PVC ISI CONDUIT",
               CATEGORY_BY_KIND[kind], kind, "3917", "18%", "Purchased", "Meters", ""]]
    return sheet_response(ITEM_HEADERS, sample, f"item_template_{kind}.xlsx")


@router.post("/api/erp/items/validate")
async def erp_items_validate(request: Request, file: UploadFile = File(...),
                             kind: str = Form("RM"), sheet: str = Form(""),
                             db: Session = Depends(get_db)):
    client = require_items_access(request, db)
    kind = kind.upper()
    if kind not in ITEM_KINDS:
        raise HTTPException(400, "kind must be RM or FG")
    rows = await parse_sheet(file, ITEM_COLUMNS, HEADER_ALIASES, sheet)
    return validate_items(db, client.id, rows, kind)


@router.post("/api/erp/items/upload")
async def erp_items_upload(request: Request, file: UploadFile = File(...),
                           kind: str = Form("RM"), sheet: str = Form(""),
                           db: Session = Depends(get_db)):
    """Validation runs again here rather than trusting that /validate was
    called first: a check the caller can skip is not a check."""
    client = require_items_access(request, db)
    kind = kind.upper()
    if kind not in ITEM_KINDS:
        raise HTTPException(400, "kind must be RM or FG")

    rows = await parse_sheet(file, ITEM_COLUMNS, HEADER_ALIASES, sheet)
    result = validate_items(db, client.id, rows, kind)
    if not result["ok"]:
        return {**result, "created": 0,
                "message": "Nothing was uploaded. Fix the errors and try again."}

    skipped = {w["code"] for w in result["warnings"]}
    created = 0
    for row in rows:
        code = row["item_code"].strip().upper()
        if code in skipped:
            continue
        db.add(models.DBItem(
            client_id=client.id, kind=kind, item_code=code,
            item_name=row["item_name"].strip(),
            segment=row.get("segment", "").strip(),
            description=(row.get("description") or row["item_name"]).strip(),
            category=CATEGORY_BY_KIND[kind], sub_category=kind,
            hsn_code=row.get("hsn_code", "").strip(),
            item_tax_type=row.get("item_tax_type", "").strip(),
            item_type=row.get("item_type", "").strip() or "Purchased",
            units_of_measure=canonical_unit(row.get("units_of_measure")) or "Nos",
            make=row.get("make", "").strip()))
        created += 1

    log_audit(db, client.id, "erp_items_uploaded", "item", None, kind,
              f"{created} code(s) created, {len(skipped)} reused", request)
    db.commit()
    return {**result, "created": created,
            "message": f"{created} {kind} code(s) uploaded."
                       + (f" {len(skipped)} already in the master and reused." if skipped else "")}


@router.post("/api/erp/items/analyse")
async def erp_items_analyse(request: Request, file: UploadFile = File(...),
                            kind: str = Form(""), sheet: str = Form(""),
                            db: Session = Depends(get_db)):
    """Read a sheet, work out what it is, and repair what is unambiguous.

    Deliberately writes nothing. It returns the rows it made of the file, the
    column mapping it assumed, every correction it applied and every problem
    left over, so the sheet can be fixed on screen and committed - instead of
    being bounced back to Excel to be uploaded again.
    """
    client = require_items_access(request, db)
    header, body = await read_sheet_rows(file, sheet)
    mapping, unmapped = map_headers(header)
    if "item_code" not in mapping.values():
        raise HTTPException(
            400, "No item code column found. Expected a column headed something "
                 "like 'Item Code', 'Material Code' or 'SKU'." + sheet_note())

    forced = (kind or "").upper() or None
    if forced and forced not in ITEM_KINDS:
        raise HTTPException(400, "kind must be RM or FG")

    rows, repairs, unknown_kind = [], [], 0
    for row in rows_from(header, body, mapping):
        row_kind = forced or detect_row_kind(row)
        if not row_kind:
            unknown_kind += 1
            row["_kind"] = ""
            row["_problems"] = [{"field": "category",
                                 "message": "Cannot tell if this is raw material or a finished good",
                                 "fix": None}]
            rows.append(row)
            continue
        row["_kind"] = row_kind
        row["_repairs"] = repair_row(row, row_kind, set())
        repairs.extend(row["_repairs"])
        rows.append(row)

    # Duplicates are judged per kind, because RM and FG codes are separate
    # series and the same digits in each are two different things.
    counts, seen_by_kind = {}, {"RM": {}, "FG": {}}
    on_file = codes_in_use(db, [r.get("item_code") for r in rows])
    taken_by_kind = {k: on_file for k in ITEM_KINDS}
    for row in rows:
        k = row.get("_kind")
        if not k:
            continue
        counts[k] = counts.get(k, 0) + 1
        row["_problems"] = check_item_row(row, k, seen_by_kind[k], taken_by_kind[k])
        code = (row.get("item_code") or "").strip().upper()
        if code and code not in seen_by_kind[k]:
            seen_by_kind[k][code] = row["_line"]

    blocked = [r for r in rows if r.get("_problems")]
    # An RM code already in the master is not a problem - it is the same
    # material being used again - so it is reported separately from the rest.
    reused = [r for r in rows if r.get("_kind") == "RM"
              and (r.get("item_code") or "").upper() in taken_by_kind["RM"]
              and not r.get("_problems")]

    return {
        "ok": not blocked,
        "mapping": mapping_report(header, mapping),
        "unmapped_headers": unmapped,
        "detected": counts,
        "unknown_kind": unknown_kind,
        "rows": rows,
        "repairs": repairs,
        "reused": [r["_line"] for r in reused],
        "summary": {
            "total": len(rows),
            "ready": len(rows) - len(blocked),
            "blocked": len(blocked),
            "repaired": len({r["line"] for r in repairs}),
        },
    }


@router.post("/api/erp/items/commit")
def erp_items_commit(body: ItemCommitIn, request: Request, db: Session = Depends(get_db)):
    """Save the rows as they now stand, after any on-screen corrections.

    Re-checks everything rather than trusting the grid: the analyse step is a
    convenience, not a permission, and this endpoint is reachable without it.
    """
    client = require_items_access(request, db)
    seen_by_kind = {"RM": {}, "FG": {}}
    on_file = codes_in_use(db, [r.get("item_code") for r in body.rows])
    taken_by_kind = {k: set(on_file) for k in ITEM_KINDS}
    errors, created, reused = [], 0, 0

    for row in body.rows:
        line = row.get("_line")
        kind = (row.get("_kind") or "").upper()
        if kind not in ITEM_KINDS:
            errors.append({"line": line, "field": "category",
                           "message": "Choose whether this is raw material or a finished good"})
            continue
        code = normalise_code(row.get("item_code"))
        problems = check_item_row({**row, "item_code": code}, kind,
                                  seen_by_kind[kind], taken_by_kind[kind])
        if problems:
            errors.extend([{**p, "line": line} for p in problems])
            continue
        if not code:
            code = issue_item_code(db, set(seen_by_kind[kind]) | taken_by_kind[kind])
        seen_by_kind[kind][code] = line

        # An RM code already held is the same material, reused. Nothing to
        # create and nothing wrong.
        if code in taken_by_kind[kind]:
            reused += 1
            continue

        db.add(models.DBItem(
            client_id=client.id, kind=kind, item_code=code,
            item_name=(row.get("item_name") or "").strip(),
            segment=(row.get("segment") or "").strip(),
            description=(row.get("description") or row.get("item_name") or "").strip(),
            category=CATEGORY_BY_KIND[kind], sub_category=kind,
            hsn_code=(row.get("hsn_code") or "").strip(),
            item_tax_type=(row.get("item_tax_type") or "").strip(),
            item_type=(row.get("item_type") or "Purchased").strip(),
            units_of_measure=canonical_unit(row.get("units_of_measure")) or "Nos",
            make=(row.get("make") or "").strip()))
        taken_by_kind[kind].add(code)
        created += 1

    if errors:
        db.rollback()
        return {"ok": False, "created": 0, "errors": errors,
                "message": "Nothing was saved. Fix the highlighted rows and commit again."}

    log_audit(db, client.id, "erp_items_uploaded", "item", None, "item master",
              f"{created} created, {reused} reused", request)
    db.commit()
    parts = [f"{created} code(s) saved"]
    if reused:
        parts.append(f"{reused} already in the master and reused")
    return {"ok": True, "created": created, "reused": reused, "errors": [],
            "message": ", ".join(parts) + "."}


@router.get("/api/erp/vocabulary")
def erp_vocabulary(request: Request, db: Session = Depends(get_db)):
    """Everything the pickers need, so the browser never invents an option."""
    require_erp_read(request, db)
    return {
        "kinds": list(ITEM_KINDS),
        "item_types": list(ITEM_TYPES),
        "units": list(UNITS_OF_MEASURE),
        "categories": CATEGORY_BY_KIND,
        "tax_rates": ["0%", "5%", "12%", "18%", "28%"],
    }


@router.get("/api/erp/items/next-code")
def erp_next_item_code(request: Request, kind: str = "RM",
                       db: Session = Depends(get_db)):
    require_items_access(request, db)
    # Peek only: nothing is reserved until the item is saved, so a picker that
    # is opened and abandoned does not burn a code.
    row = db.query(models.DBCodeSequence).filter(
        models.DBCodeSequence.name == "item").first()
    return {"kind": (kind or "").upper(),
            "item_code": encode_serial(row.next_value if row else 1),
            "preview": True,
            "format": "%d characters, %s" % (CODE_LENGTH, "".join(CODE_ALPHABET))}


@router.post("/api/erp/items")
def erp_create_item(body: ItemIn, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db)
    item = build_item(db, client.id, body, set())
    log_audit(db, client.id, "erp_item_created", "item", None, item.item_code,
              item.item_name, request)
    db.commit()
    db.refresh(item)
    return dict(item_row(item), message=item.item_code + " added.")


@router.post("/api/erp/items/bulk")
def erp_create_items_bulk(body: ItemBulkIn, request: Request,
                          db: Session = Depends(get_db)):
    """Several rows typed in one go, all or nothing.

    A half-saved batch leaves somebody working out which half, which is worse
    than saving none of it.
    """
    client = require_items_access(request, db)
    if not body.items:
        raise HTTPException(400, "Nothing to save")
    # One set for the whole batch: codes are a single series now, so a row
    # cannot take a number just because it is a different kind.
    claimed = set()
    created = []
    try:
        for row in body.items:
            created.append(build_item(db, client.id, row, claimed))
    except HTTPException:
        db.rollback()
        raise
    log_audit(db, client.id, "erp_items_created", "item", None, "item master",
              str(len(created)) + " entered directly", request)
    db.commit()
    return {"created": len(created), "codes": [i.item_code for i in created],
            "message": str(len(created)) + " code(s) added."}


@router.put("/api/erp/items/{item_id}")
def erp_update_item(item_id: int, body: ItemIn, request: Request,
                    db: Session = Depends(get_db)):
    client = require_items_access(request, db)
    item = db.query(models.DBItem).filter(
        models.DBItem.id == item_id, models.DBItem.client_id == client.id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    name = (body.item_name or "").strip()
    if not name:
        raise HTTPException(400, "An item name is required")
    # The code itself is deliberately not editable: work order and BOM lines
    # already reference it, and renaming it would quietly detach them.
    item.item_name = name
    item.description = (body.description or "").strip() or name
    item.hsn_code = (body.hsn_code or "").strip()
    item.item_tax_type = (body.item_tax_type or "").strip()
    if (body.item_type or "") in ITEM_TYPES:
        item.item_type = body.item_type
    if (body.units_of_measure or "").strip():
        unit = canonical_unit(body.units_of_measure)
        if not unit:
            raise HTTPException(400, "%s is not a unit this app knows. Use one of: %s"
                                     % (body.units_of_measure, ", ".join(UNITS_OF_MEASURE)))
        item.units_of_measure = unit
    if body.reorder_level is not None:
        item.reorder_level = max(0.0, money(body.reorder_level))
    db.commit()
    return {"ok": True, "message": item.item_code + " updated."}


@router.delete("/api/erp/items/{item_id}")
def erp_delete_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    """Only while nothing references it."""
    client = require_items_access(request, db)
    item = db.query(models.DBItem).filter(
        models.DBItem.id == item_id, models.DBItem.client_id == client.id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    used = db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.fg_code == item.item_code).count()
    used += db.query(models.DBBomLine).filter(
        models.DBBomLine.client_id == client.id,
        or_(models.DBBomLine.rm_code == item.item_code,
            models.DBBomLine.fg_code == item.item_code)).count()
    if used:
        raise HTTPException(
            409, item.item_code + " is used on " + str(used) +
                 " document line(s) and cannot be removed.")
    log_audit(db, client.id, "erp_item_deleted", "item", item.id, item.item_code, "", request)
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/api/erp/bom/build")
def erp_build_bom(body: BomIn, request: Request, db: Session = Depends(get_db)):
    """The budget, allocated on screen against the lines actually sold."""
    client = require_workorder_access(request, db)
    wo = work_order_or_404(db, client.id, body.work_order_id)
    if (wo.approval_status or "none") == "pending":
        raise HTTPException(409, "This order is with an approver; its budget cannot change.")

    rm_master = {i.item_code.upper(): i for i in db.query(models.DBItem).filter(
        models.DBItem.client_id == client.id, models.DBItem.kind == "RM").all()}
    sold = {l.fg_code.upper() for l in db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == wo.id).all()}

    allocations = []
    for index, line in enumerate(body.lines, start=1):
        fg = (line.fg_code or "").strip().upper()
        rm = (line.rm_code or "").strip().upper()
        if fg not in sold:
            raise HTTPException(400, "Line %d: %s is not on %s" % (index, fg, wo.number))
        if rm not in rm_master:
            raise HTTPException(400, "Line %d: %s is not a raw material code" % (index, rm))
        qty, rate = money(line.qty), unit_rate(line.rate)
        if qty <= 0:
            raise HTTPException(400, "Line %d: quantity must be more than zero" % index)
        item = rm_master[rm]
        allocations.append({"fg_code": fg, "rm_code": rm, "rm_name": item.item_name,
                            "qty": qty, "uom": item.units_of_measure,
                            "rate": rate, "amount": money(qty * rate)})

    # Replaces rather than adds, so budgeting twice cannot double the cost.
    db.query(models.DBBomLine).filter(models.DBBomLine.work_order_id == wo.id).delete()
    for a in allocations:
        db.add(models.DBBomLine(client_id=client.id, work_order_id=wo.id, **a))
    total = money(sum(a["amount"] for a in allocations))
    log_audit(db, client.id, "work_order_budgeted", "work_order", wo.id, wo.number,
              "%d material line(s), cost %s" % (len(allocations), total), request)
    db.commit()
    db.refresh(wo)
    return {"ok": True, "total_cost": total,
            "work_order": work_order_to_dict(db, wo, detail=True),
            "message": "Budget saved for %s: %d line(s)." % (wo.number, len(allocations))}


@router.get("/api/erp/items")
def erp_list_items(request: Request, kind: str = "", q: str = "",
                   db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    query = db.query(models.DBItem).filter(models.DBItem.client_id == client.id)
    if kind:
        query = query.filter(models.DBItem.kind == kind.upper())
    if q:
        query = query.filter(or_(models.DBItem.item_code.ilike(f"%{q}%"),
                                 models.DBItem.item_name.ilike(f"%{q}%")))
    items = query.order_by(models.DBItem.id.desc()).limit(500).all()
    return {
        "items": [{"id": i.id, "kind": i.kind, "item_code": i.item_code,
                   "item_name": i.item_name, "description": i.description,
                   "category": i.category, "item_type": i.item_type,
                   "units_of_measure": i.units_of_measure, "hsn_code": i.hsn_code,
                   "item_tax_type": i.item_tax_type,
                   "last_rate": unit_rate(i.last_rate),
                   "reorder_level": money(i.reorder_level)} for i in items],
        "counts": {
            k: db.query(models.DBItem).filter(
                models.DBItem.client_id == client.id,
                models.DBItem.kind == k).count()
            for k in ITEM_KINDS
        },
    }


@router.post("/api/erp/bom/analyse")
async def erp_bom_analyse(request: Request, file: UploadFile = File(...),
                          work_order_id: int = Form(...), sheet: str = Form(""),
                          db: Session = Depends(get_db)):
    """Read a budget sheet against one work order, without saving anything."""
    client = require_workorder_access(request, db)
    wo = work_order_or_404(db, client.id, work_order_id)
    header, body = await read_sheet_rows(file, sheet)
    mapping, unmapped = map_headers_with(header, BOM_HEADER_ALIASES)
    if "rm_code" not in mapping.values():
        raise HTTPException(400, "No material code column found. Expected something "
                                 "headed 'RM Code' or 'Material Code'." + sheet_note())

    rm_master = {i.item_code.upper(): i for i in db.query(models.DBItem).filter(
        models.DBItem.client_id == client.id, models.DBItem.kind == "RM").all()}
    sold = {l.fg_code.upper(): l for l in db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == wo.id).all()}

    lines, repairs = [], []
    for row in rows_from(header, body, mapping):
        line = row["_line"]
        fg = (row.get("fg_code") or "").strip().upper()
        rm = (row.get("rm_code") or "").strip().upper()
        qty, rate = money(row.get("qty") or 0), unit_rate(row.get("rate") or 0)
        problems = []

        # A sheet with one sold line needs no FG column at all.
        if not fg and len(sold) == 1:
            fg = list(sold)[0]
            repairs.append({"line": line, "field": "fg_code", "from": "", "to": fg,
                            "note": "the only line on this order"})
        if not fg:
            problems.append({"field": "fg_code", "message": "Which sold line is this against?", "fix": None})
        elif fg not in sold:
            problems.append({"field": "fg_code",
                             "message": "Not on %s. Only sold lines can be budgeted." % wo.number,
                             "fix": list(sold)[0] if len(sold) == 1 else None})
        if not rm:
            problems.append({"field": "rm_code", "message": "A material code is required", "fix": None})
        elif rm not in rm_master:
            problems.append({"field": "rm_code",
                             "message": "Not in the item master. Add this raw material code first.",
                             "fix": None})
        if qty <= 0:
            problems.append({"field": "qty", "message": "Quantity must be more than zero", "fix": None})

        item = rm_master.get(rm)
        lines.append({"_line": line, "fg_code": fg, "rm_code": rm,
                      "rm_name": item.item_name if item else (row.get("rm_name") or ""),
                      "uom": item.units_of_measure if item else (row.get("uom") or ""),
                      "qty": qty, "rate": rate, "amount": money(qty * rate),
                      "_problems": problems})

    blocked = [l for l in lines if l["_problems"]]
    cost = money(sum(l["amount"] for l in lines if not l["_problems"]))
    value = money(wo.total_value or 0)
    return {
        "ok": not blocked,
        "mapping": mapping_report(header, mapping),
        "unmapped_headers": unmapped,
        "lines": lines, "repairs": repairs,
        "sold": [{"code": c, "name": l.item_name} for c, l in sold.items()],
        "materials": sorted([{"code": i.item_code, "name": i.item_name,
                              "uom": i.units_of_measure} for i in rm_master.values()],
                            key=lambda x: x["code"]),
        "summary": {"total": len(lines), "ready": len(lines) - len(blocked),
                    "blocked": len(blocked), "cost": cost, "value": value,
                    "margin": money(value - cost)},
    }


@router.get("/api/erp/bom/template")
def erp_bom_template(request: Request, db: Session = Depends(get_db)):
    require_workorder_access(request, db)
    return sheet_response(BOM_HEADERS,
                          [["FG0001", "RM0001", "20MM LMS PVC ISI CONDUIT", "5100", "Meters", "48.00"]],
                          "budget_bom_template.xlsx")


@router.post("/api/erp/bom/validate")
async def erp_bom_validate(request: Request, file: UploadFile = File(...),
                           work_order_id: int = Form(...), sheet: str = Form(""),
                           db: Session = Depends(get_db)):
    client = require_workorder_access(request, db)
    wo = work_order_or_404(db, client.id, work_order_id)
    rows = await parse_sheet(file, BOM_COLUMNS, BOM_HEADER_ALIASES, sheet)
    return validate_bom_sheet(db, client.id, rows, wo)


@router.post("/api/erp/bom")
async def erp_bom_upload(request: Request, file: UploadFile = File(...),
                         work_order_id: int = Form(...), sheet: str = Form(""),
                         db: Session = Depends(get_db)):
    client = require_workorder_access(request, db)
    wo = work_order_or_404(db, client.id, work_order_id)
    if (wo.approval_status or "none") == "pending":
        raise HTTPException(409, "This order is with an approver; its budget cannot change.")

    rows = await parse_sheet(file, BOM_COLUMNS, BOM_HEADER_ALIASES, sheet)
    result = validate_bom_sheet(db, client.id, rows, wo)
    if not result["ok"]:
        return {**result, "created": 0,
                "message": "Nothing was saved. Fix the errors and try again."}

    # A re-upload replaces the allocation rather than adding to it, so
    # budgeting twice does not silently double the cost of the job.
    db.query(models.DBBomLine).filter(models.DBBomLine.work_order_id == wo.id).delete()
    for a in result["lines"]:
        db.add(models.DBBomLine(client_id=client.id, work_order_id=wo.id, **a))

    log_audit(db, client.id, "work_order_budgeted", "work_order", wo.id, wo.number,
              f"{len(result['lines'])} material line(s), cost {result['total_cost']}", request)
    db.commit()
    return {**result, "created": len(result["lines"]),
            "message": f"Budget allocated for {wo.number}: "
                       f"{len(result['lines'])} material line(s)."}


@router.get("/api/erp/inquiry")
def erp_work_order_inquiry(request: Request, db: Session = Depends(get_db)):
    """The screen the flow ends on.

    Every order with what it is worth, whether its budget has been allocated,
    and where its approval has got to - which together are the three things
    somebody signing off a project needs on one line.
    """
    client = require_erp_read(request, db)
    orders = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.client_id == client.id).order_by(
            models.DBWorkOrder.id.desc()).limit(300).all()

    rows = [work_order_to_dict(db, w) for w in orders]
    for row in rows:
        row["bom_status"] = "Allocated" if row["budgeted"] else "Not allocated"
        row["md_approval"] = {"approved": "Approved", "rejected": "Rejected",
                              "pending": "Awaiting"}.get(row["approval_status"], "Not sent")
        row["can_place"] = row["status"] == "Draft"
        row["can_approve"] = row["budgeted"] and row["approval_status"] != "approved"
    return {
        "rows": rows,
        "summary": {
            "orders": len(rows),
            "awaiting_approval": len([r for r in rows if r["approval_status"] == "pending"]),
            "not_budgeted": len([r for r in rows if not r["budgeted"]]),
            "total_value": money(sum(r["total_value"] for r in rows)),
            "total_margin": money(sum(r["margin"] for r in rows if r["budgeted"])),
        },
    }


@router.post("/api/erp/inquiry/{wo_id}/md-approval")
def erp_md_approval(wo_id: int, body: MDDecision, request: Request,
                    db: Session = Depends(get_db)):
    """The managing director's own sign-off.

    The reporting chain exists for costs raised by staff. A project approval is
    one person's decision, so this records it directly rather than walking a
    ladder - but it is written to the same approval history, so a work order
    has one story regardless of which route the signature came by.
    """
    client = require_items_access(request, db, "workorders.approve")
    wo = work_order_or_404(db, client.id, wo_id)

    if body.approve and not db.query(models.DBBomLine).filter(
            models.DBBomLine.work_order_id == wo.id).count():
        raise HTTPException(
            409, "Allocate the budget first - there is no cost to approve against.")
    # Approving is what places an order, so a draft may be signed off directly.
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wo.approval_status = "approved" if body.approve else "rejected"
    wo.current_approval_step = 0
    set_approval_display_status(wo, "work_order", wo.approval_status)
    if not body.approve:
        wo.rejection_reason = (body.notes or "").strip()

    # Recorded on the same chain the staff route writes to, so the history
    # reads as one sequence however the decision was reached.
    db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == "work_order",
        models.DBApprovalChain.entity_id == wo.id,
        models.DBApprovalChain.status == "pending").update(
            {"status": "cancelled"}, synchronize_session=False)
    db.add(models.DBApprovalChain(
        client_id=client.id, entity_type="work_order", entity_id=wo.id,
        employee_id=wo.submitted_by, approver_id=None, level="MD", step=99,
        status=wo.approval_status, notes=(body.notes or "").strip() or "Managing Director",
        decided_at=now, created_at=now))

    log_audit(db, client.id, "work_order_md_" + wo.approval_status, "work_order",
              wo.id, wo.number, (body.notes or "").strip(), request)
    db.commit()
    db.refresh(wo)
    return {"ok": True, "work_order": work_order_to_dict(db, wo),
            "message": wo.number + " " + ("approved by the MD."
                                          if body.approve else "sent back.")}


# TAKING IT AWAY
#
# Every list somebody works from is one they will eventually be asked to send
# on, print, or check against a figure from somewhere else. Without an export
# that means re-keying it into a spreadsheet, which is the habit this system
# is meant to be replacing rather than feeding.
@router.get("/api/erp/items.xlsx")
def erp_items_xlsx(request: Request, kind: str = "", q: str = "",
                   db: Session = Depends(get_db)):
    """The item master, filtered the same way the screen filters it."""
    client = require_erp_read(request, db)
    query = db.query(models.DBItem).filter(models.DBItem.client_id == client.id)
    if kind:
        query = query.filter(models.DBItem.kind == kind.upper())
    if q:
        query = query.filter(or_(models.DBItem.item_code.ilike("%" + q + "%"),
                                 models.DBItem.item_name.ilike("%" + q + "%")))
    rows = query.order_by(models.DBItem.item_code).all()
    return sheet_response(
        ["Item Code", "Item Name", "Kind", "Description", "Type",
         "Units Of Measure", "HSN Code", "Item Tax Type", "Make"],
        [[i.item_code or "", i.item_name or "", i.kind or "", i.description or "",
          i.item_type or "", i.units_of_measure or "", i.hsn_code or "",
          i.item_tax_type or "", i.make or ""] for i in rows],
        "item_master.xlsx",
        preamble=[["Item Master", "", "", "", "", "", "", "", client.company_name or ""],
                  ["%d code(s)" % len(rows) +
                   (" - %s only" % kind.upper() if kind else "")],
                  []])
