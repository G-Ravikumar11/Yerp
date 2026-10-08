"""Checks on what is entered for common."""
import os
import re

from fastapi import HTTPException

from app import models

from app.constants.invoicing import RECURRING_FREQUENCIES
from app.constants.projects import JOB_STATUSES
from app.constants.recruitment import REQUISITION_STATUSES, WORK_MODES
from app.constants.subcontract_orders import WO_RICH_TAGS, _WO_TAG
from app.constants.wallet_ai import TOPUP_MAX_MAJOR, TOPUP_MIN_MAJOR
from app.core.currency import currency_symbol, money, to_minor, unit_rate
from app.core.dates import _parse_date, parse_working_days
from app.core.gst import state_from_gstin
from app.core.units import CATEGORY_BY_KIND, ITEM_TYPES


def validate_email_address(email: str) -> bool:
    import re as _re
    if not email or not isinstance(email, str):
        return False
    pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
    return bool(_re.match(pattern, email.strip()))


def validate_line_items(line_items):
    """Reject payloads that would silently produce a nonsense invoice."""
    if not line_items:
        raise HTTPException(status_code=400, detail="An invoice needs at least one line item")
    if len(line_items) > 200:
        raise HTTPException(status_code=400, detail="An invoice cannot have more than 200 line items")
    for idx, item in enumerate(line_items, start=1):
        if (item.qty or 0) < 0:
            raise HTTPException(status_code=400, detail=f"Line {idx}: quantity cannot be negative")
        if (item.price or 0) < 0:
            raise HTTPException(status_code=400, detail=f"Line {idx}: price cannot be negative")
        disc = item.disc or 0
        if disc < 0 or disc > 100:
            raise HTTPException(status_code=400, detail=f"Line {idx}: discount must be between 0 and 100")


def validate_invoice_dates(issue_date, due_date):
    issue = _parse_date(issue_date)
    due = _parse_date(due_date)
    if issue_date and not issue:
        raise HTTPException(status_code=400, detail="Issue date must be in YYYY-MM-DD format")
    if due_date and not due:
        raise HTTPException(status_code=400, detail="Due date must be in YYYY-MM-DD format")
    if issue and due and due < issue:
        raise HTTPException(status_code=400, detail="Due date cannot be before the issue date")


def validate_job_status(status):
    status = (status or "quoting").strip().lower()
    if status not in JOB_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown job status '{status}'. Expected one of: {', '.join(JOB_STATUSES)}")
    return status


def validate_job_money(name, value):
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a number")
    if amount < 0:
        raise HTTPException(status_code=400, detail=f"{name} cannot be negative")
    if amount > 1_000_000_000:
        raise HTTPException(status_code=400, detail=f"{name} is unrealistically large")
    return money(amount)


def validate_items(db, client_id, rows, kind):
    """FG codes are unique; RM codes are reusable master stock.

    A duplicate FG code is a hard error - one code is one deliverable, so the
    ERP code has to change. A duplicate RM code is not a mistake at all: it is
    the same material being used on another job, so the row is skipped, the
    existing master kept, and the upload still goes through.
    """
    errors, warnings, seen = [], [], {}
    already = codes_in_use(db, [r.get("item_code") for r in rows])
    expected_cat, expected_sub = CATEGORY_BY_KIND[kind], kind

    for row in rows:
        line, code = row["_line"], (row.get("item_code") or "").strip().upper()

        def fail(field, message):
            errors.append({"line": line, "code": code, "field": field, "message": message})

        if not code:
            fail("Item Code", "Item Code is required")
            continue
        if code in seen:
            fail("Item Code", f"Duplicated in this file (also on line {seen[code]})")
            continue
        seen[code] = line
        if code in already:
            if kind == "FG":
                fail("Item Code", "Already exists. FG codes must be unique - change the ERP code.")
                continue
            warnings.append({"line": line, "code": code,
                             "message": "Already in the RM master. Row skipped, material reused."})
        if not (row.get("item_name") or "").strip():
            fail("Item Name", "Item Name is required")

        cat = (row.get("category") or "").strip().upper()
        if cat != expected_cat:
            fail("Category", f"Must be '{expected_cat}' for a {kind} upload")
        if (row.get("sub_category") or "").strip().upper() != expected_sub:
            fail("Sub Category", f"Must be '{expected_sub}' for a {kind} upload")

        itype = (row.get("item_type") or "").strip()
        if itype and itype not in ITEM_TYPES:
            fail("Item Type", f"Must be one of: {', '.join(ITEM_TYPES)}")

    skipped = {w["code"] for w in warnings}
    return {"ok": not errors, "kind": kind, "total_rows": len(rows),
            "errors": errors, "warnings": warnings,
            "importable": max(0, len(rows) - len(skipped) - len(errors))}


def check_item_row(row, kind, seen, taken):
    """What is left wrong after the repairs, and what could be done about it."""
    problems = []
    line = row.get("_line")
    code = (row.get("item_code") or "").strip().upper()

    if not code:
        pass                    # issued on upload, like everywhere else
    elif code in seen:
        problems.append({"field": "item_code",
                         "message": f"Also on line {seen[code]} of this file",
                         "fix": suggest_free_code(code, set(taken) | set(seen))})
    elif code in taken and kind == "FG":
        problems.append({"field": "item_code",
                         "message": "Already used. FG codes identify one deliverable each.",
                         "fix": suggest_free_code(code, taken)})

    if not (row.get("item_name") or "").strip():
        problems.append({"field": "item_name", "message": "An item name is required", "fix": None})
    if (row.get("item_type") or "") not in ITEM_TYPES:
        problems.append({"field": "item_type",
                         "message": f"Must be {' or '.join(ITEM_TYPES)}", "fix": "Purchased"})
    return problems


def validate_work_order_sheet(db, client_id, rows):
    """Every FG code must already be in the item master.

    This is the gate the whole item-upload step exists to satisfy: pricing a
    line against a code nobody has defined produces an order that cannot be
    costed, delivered or reconciled.
    """
    errors, lines, seen = [], [], {}
    master = {i.item_code.upper(): i for i in db.query(models.DBItem).filter(
        models.DBItem.client_id == client_id, models.DBItem.kind == "FG").all()}

    for row in rows:
        line, code = row["_line"], (row.get("fg_code") or "").strip().upper()

        def fail(field, message):
            errors.append({"line": line, "code": code, "field": field, "message": message})

        if not code:
            fail("FG Code", "FG Code is required")
            continue
        if code not in master:
            fail("FG Code", "Not in the item master. Upload this FG code first.")
            continue
        if code in seen:
            fail("FG Code", f"Repeated on line {seen[code]}. Combine the quantities.")
            continue
        seen[code] = line

        qty, rate = money(row.get("qty") or 0), unit_rate(row.get("rate") or 0)
        if qty <= 0:
            fail("Qty", "Quantity must be greater than zero")
        if rate < 0:
            fail("Rate", "Rate cannot be negative")

        item = master[code]
        # The unit belongs to the code, not to the sheet quoting it. Their
        # files write the same unit three ways - "Meter", "Meters", "Mtr" -
        # and taking whichever spelling arrived would leave one item measured
        # differently on every order. The preview path already read it this
        # way round; this is the direct upload agreeing with it.
        lines.append({"fg_code": code,
                      "item_name": (row.get("item_name") or item.item_name).strip(),
                      "description": (row.get("description") or item.description).strip(),
                      "qty": qty, "uom": (item.units_of_measure or row.get("uom") or "").strip(),
                      "rate": rate, "amount": money(qty * rate)})

    return {"ok": not errors, "errors": errors, "lines": lines,
            "total_rows": len(rows), "total_value": money(sum(l["amount"] for l in lines))}


def validate_bom_sheet(db, client_id, rows, wo):
    errors, allocations = [], []
    rm_master = {i.item_code.upper(): i for i in db.query(models.DBItem).filter(
        models.DBItem.client_id == client_id, models.DBItem.kind == "RM").all()}
    sold = {l.fg_code.upper() for l in db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == wo.id).all()}

    for row in rows:
        line = row["_line"]
        fg = (row.get("fg_code") or "").strip().upper()
        rm = (row.get("rm_code") or "").strip().upper()

        def fail(field, message):
            errors.append({"line": line, "code": f"{fg}/{rm}", "field": field,
                           "message": message})

        if not fg or not rm:
            fail("FG/RM Code", "Both an FG Code and an RM Code are required")
            continue
        # Budgeting a line that was never sold is how a job quietly ends up
        # costing more than it was ever worth.
        if fg not in sold:
            fail("FG Code", f"Not on {wo.number}. Only sold lines can be budgeted.")
            continue
        if rm not in rm_master:
            fail("RM Code", "Not in the item master. Upload this RM code first.")
            continue

        qty, rate = money(row.get("qty") or 0), unit_rate(row.get("rate") or 0)
        if qty <= 0:
            fail("Qty", "Quantity must be greater than zero")

        item = rm_master[rm]
        allocations.append({"fg_code": fg, "rm_code": rm,
                            "rm_name": (row.get("rm_name") or item.item_name).strip(),
                            "qty": qty, "uom": (item.units_of_measure or row.get("uom") or "").strip(),
                            "rate": rate, "amount": money(qty * rate)})

    return {"ok": not errors, "errors": errors, "lines": allocations,
            "total_rows": len(rows),
            "total_cost": money(sum(a["amount"] for a in allocations))}


def validate_recurring(body):
    if body.frequency not in RECURRING_FREQUENCIES:
        raise HTTPException(
            status_code=400,
            detail="Frequency must be one of: " + ", ".join(RECURRING_FREQUENCIES))
    if not _parse_date(body.next_run):
        raise HTTPException(status_code=400, detail="First issue date must be in YYYY-MM-DD format")
    if body.end_date and not _parse_date(body.end_date):
        raise HTTPException(status_code=400, detail="End date must be in YYYY-MM-DD format")
    if body.end_date and _parse_date(body.end_date) < _parse_date(body.next_run):
        raise HTTPException(status_code=400, detail="End date cannot be before the first issue date")
    try:
        terms = int(body.payment_terms_days if body.payment_terms_days is not None else 14)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Payment terms must be a whole number of days")
    if terms < 0 or terms > 365:
        raise HTTPException(status_code=400, detail="Payment terms must be between 0 and 365 days")
    return terms


def validate_tax_rate(name, percent):
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Every tax rate needs a name")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="Tax rate names must be 60 characters or fewer")
    try:
        pct = float(percent)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"'{name}' needs a numeric percentage")
    # Same bound as payroll: a rate above 100 produces a negative total.
    if pct < 0 or pct > 100:
        raise HTTPException(status_code=400,
                            detail=f"'{name}' must be between 0 and 100 percent")
    return name, round(pct, 4)


def valid_hex_colour(value: str, fallback: str = "#4F46E5") -> str:
    """Accept #rgb or #rrggbb only. This string is written straight into a PDF
    and into inline CSS in the preview, so it must never carry anything else."""
    v = (value or "").strip()
    if re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", v):
        return v.lower()
    return fallback


def validate_quote_dates(issue_date, expiry_date):
    issue = _parse_date(issue_date)
    expiry = _parse_date(expiry_date)
    if issue_date and not issue:
        raise HTTPException(status_code=400, detail="Issue date must be in YYYY-MM-DD format")
    if expiry_date and not expiry:
        raise HTTPException(status_code=400, detail="Expiry date must be in YYYY-MM-DD format")
    if issue and expiry and expiry < issue:
        raise HTTPException(status_code=400, detail="Expiry date cannot be before the issue date")


def clean_working_days(raw):
    """Normalise for storage, keeping the days in order."""
    if isinstance(raw, (list, tuple, set)):
        raw = ",".join(str(x) for x in raw)
    return ",".join(str(d) for d in sorted(parse_working_days(raw)))


def validate_job_payload(body, db, client_id):
    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="A job title is required")
    status = (body.status or "draft").strip().lower()
    if status not in REQUISITION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {', '.join(REQUISITION_STATUSES)}")
    mode = (body.work_mode or "onsite").strip().lower()
    if mode not in WORK_MODES:
        raise HTTPException(status_code=400, detail=f"Work mode must be one of: {', '.join(WORK_MODES)}")
    # `or 1` would quietly turn an explicit 0 into 1 instead of rejecting it.
    try:
        openings = int(body.openings if body.openings is not None else 1)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Openings must be a whole number")
    if openings < 1 or openings > 999:
        raise HTTPException(status_code=400, detail="Openings must be between 1 and 999")
    lo, hi = float(body.salary_min or 0), float(body.salary_max or 0)
    if lo < 0 or hi < 0:
        raise HTTPException(status_code=400, detail="Salary cannot be negative")
    if lo and hi and lo > hi:
        raise HTTPException(status_code=400, detail="Minimum salary cannot exceed the maximum")
    if body.department_id:
        dept = db.query(models.DBDepartment).filter(
            models.DBDepartment.id == body.department_id,
            models.DBDepartment.client_id == client_id,
        ).first()
        if not dept:
            raise HTTPException(status_code=400, detail="Department not found")
    if body.hiring_manager_id:
        mgr = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == body.hiring_manager_id,
            models.DBEmployee.client_id == client_id,
        ).first()
        if not mgr:
            raise HTTPException(status_code=400, detail="Hiring manager not found")
    return status, mode, openings, validate_level(body.level)


def validate_topup_amount(amount, currency):
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Amount must be a number")
    if amount < TOPUP_MIN_MAJOR:
        raise HTTPException(status_code=400, detail=f"Minimum top-up is {currency_symbol(currency)}{TOPUP_MIN_MAJOR:.2f}")
    if amount > TOPUP_MAX_MAJOR:
        raise HTTPException(status_code=400, detail=f"Maximum top-up is {currency_symbol(currency)}{TOPUP_MAX_MAJOR:.2f}")
    return to_minor(amount, currency)


def validate_candidate_document(doc, index=1):
    name = (doc.file_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail=f"Document {index}: a file name is required")
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"'{name}' is not an accepted file type. Allowed: "
                   + ", ".join(sorted(ALLOWED_DOCUMENT_EXTENSIONS)),
        )
    mime = (doc.file_type or "").split(";")[0].strip().lower()
    if mime and mime not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"'{name}' has an unsupported content type ({mime})")
    size = decoded_size(doc.file_data)
    if size == 0:
        raise HTTPException(status_code=400, detail=f"'{name}' appears to be empty")
    if size > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"'{name}' is {size / 1048576:.1f} MB; the limit is "
                   f"{MAX_DOCUMENT_BYTES // 1048576} MB per file",
        )
    return size


def clean_rich_text(value):
    """Keep the formatting, drop everything else.

    An allow-list rather than a block-list: the tags worth keeping are few and
    known, and every list of dangerous tags anybody has ever written has been
    incomplete. Unknown tags lose their brackets and keep their words, so text
    pasted out of a browser arrives readable rather than gutted.
    """
    text = str(value or "")
    if "<" not in text:
        return text.strip()

    def keep(match):
        tag = match.group(1).lower()
        if tag not in WO_RICH_TAGS:
            return ""
        closing = match.group(0).lstrip().startswith("</")
        if tag == "br":
            return "<br/>"
        return "</%s>" % tag if closing else "<%s>" % tag

    cleaned = _WO_TAG.sub(keep, text)
    # Anything still angled after that was never a tag - a dimension written
    # as <150 mm, most likely - and has to survive as the character it is.
    cleaned = re.sub(r"<(?![/a-zA-Z])", "&lt;", cleaned)
    return cleaned.strip()


def clean_tax_ids(gstin, pan):
    """A GSTIN and a PAN as the forms want them, or a plain reason why not.
    The PAN is inside the GSTIN, so one given without the other is filled in,
    and two that disagree are refused - they would print two different
    businesses on one document."""
    gstin = re.sub(r"\s", "", gstin or "").upper()
    pan = re.sub(r"\s", "", pan or "").upper()
    if gstin and (len(gstin) != 15 or not state_from_gstin(gstin)
                  or not re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$", gstin)):
        raise HTTPException(400, "A GSTIN is fifteen characters: a state code, the PAN, then three more "
                                 "(for example 36AABCY1234H1ZX).")
    if pan and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan):
        raise HTTPException(400, "A PAN is five letters, four digits and a letter (for example AABCY1234H).")
    if gstin and not pan:
        pan = gstin[2:12]
    if gstin and pan and gstin[2:12] != pan:
        raise HTTPException(400, "The PAN %s is not the one inside the GSTIN %s." % (pan, gstin))
    return gstin, pan


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.core.files import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_DOCUMENT_TYPES,
    MAX_DOCUMENT_BYTES,
    decoded_size,
)
from app.services.items import codes_in_use, suggest_free_code
from app.validators.hr import validate_level
