"""Store module - material norms brought in by the sheet, or copied from another project. Owned by P5.

A norm says how much of a stock item one unit of a BOQ item consumes (`DBStoreMaterialNorm`). Typing them one by one is what
left most BOQ items without one, so the wastage report had nothing to measure against. Two quicker ways in:

    the sheet   BOQ item | Material | Qty Per Unit | Wastage %, one row per pair, read against the chosen project's current BOQ
                and the company's item master. Every row is checked and shown before anything is saved; saving checks it again.
    a project   the norms of another project of the company, each carried to the BOQ item of this project that is the same
                work. A BOQ item id is never reused: lines are matched by number and description, and a line that could be
                more than one is offered for a person to choose, never guessed.
    work items  the company's norms on the work item each BOQ item is (Item Master; the Item sheet can name the work item
                where the BOQ does not). Taken only where the BOQ item and the work item count in the same unit.

Either way it goes in together or not at all, and the audit log says who did it, from where, and what it changed.
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from app import models
from app.core.sheets import sheet_note
from app.models.store_core import DBStoreItemSettings
from app.models.store_reports import DBStoreMaterialNorm

MAX_ROWS = 2000
QTY_HIGH = Decimal("999999")
QTY_STEP = Decimal("0.000001")
MODES = ("add", "update")            # the sheet: add new norms only, or also change the ones already set
COPY_MODES = ("add", "replace")      # a project: copy the missing ones only, or also overwrite the matching ones

TEMPLATE_HEADERS = ["BOQ Item", "Material", "Qty Per Unit", "Wastage %"]
TEMPLATE_SAMPLE = [["Brickwork", "Cement", 0.25, 5], ["Brickwork", "Sand", 0.05, 7], ["Plastering", "Cement", 0.12, 5], ["Plastering", "Sand", 0.025, 7]]

# Headings as people write them, squeezed to letters and digits ("Wastage %" -> "wastage").
HEADERS = {
    "boq": ("boqitem", "boq", "boqline", "boqitemno", "boqno", "boqdescription", "workitem"),
    "material": ("material", "materialcode", "materialname", "itemcode", "itemname", "item", "rawmaterial", "rm"),
    "qty": ("qtyperunit", "quantityperunit", "qtyunit", "perunit", "consumptionperunit", "norm", "consumption", "qty", "quantity"),
    "wastage": ("wastage", "wastagepct", "wastagepercent", "wastagepercentage", "wastageallowance", "allowance"),
}
LABELS = {"boq": "BOQ Item", "material": "Material", "qty": "Qty Per Unit", "wastage": "Wastage %"}


def squeeze(text) -> str:
    return " ".join(str(text or "").lower().split())


def _key(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def first_line(text) -> str:
    return (text or "").split("\n")[0].strip()


def boq_label(line) -> str:
    return ("%s %s" % (line.item_no or "", first_line(line.description)[:80])).strip()


# --- what a project has to match against ----------------------------------------------------------------------------------

def priced_lines(db, client_id, job_id):
    """The priced lines (items and sub-items) of the project's current BOQ revision - the ones a norm may be set on."""
    boq = db.query(models.DBBoq).filter(models.DBBoq.job_id == job_id, models.DBBoq.client_id == client_id).first()
    if boq is None:
        return []
    return (db.query(models.DBBoqLine).join(models.DBBoqRevision, models.DBBoqRevision.id == models.DBBoqLine.revision_id)
            .filter(models.DBBoqLine.boq_id == boq.id, models.DBBoqRevision.rev_no == boq.current_rev, models.DBBoqLine.kind.in_(["item", "sub"]))
            .order_by(models.DBBoqLine.display_order, models.DBBoqLine.id).all())


class BoqIndex:
    """A project's priced BOQ lines, findable by what a person would write for one: its number, its description, or both."""

    def __init__(self, lines):
        self.lines = {l.id: l for l in lines}
        self.by_label, self.by_no, self.by_first, self.by_full = {}, {}, {}, {}
        for l in lines:
            for index, key in ((self.by_label, squeeze(boq_label(l))), (self.by_no, squeeze(l.item_no)),
                               (self.by_first, squeeze(first_line(l.description))), (self.by_full, squeeze(l.description))):
                if key:
                    index.setdefault(key, []).append(l)

    def find(self, text):
        """The lines the text names: the first way of reading it that names any."""
        key = squeeze(text)
        if not key:
            return []
        for index in (self.by_label, self.by_no, self.by_first, self.by_full):
            if index.get(key):
                return index[key]
        return []

    def same_work(self, source):
        """Where a line of another project's BOQ lands here: (kind, [candidates]).
        exact        same number and same description - one line, taken as it is
        description  same description, different number - one line, taken as it is
        number       same number, description differs - one line, but a person must confirm it
        ambiguous    more than one line could be it - a person must choose
        none         nothing here is that work - skipped"""
        no, first, full = squeeze(source.item_no), squeeze(first_line(source.description)), squeeze(source.description)
        by_desc = self.by_full.get(full) or self.by_first.get(first) or []
        exact = [l for l in by_desc if no and squeeze(l.item_no) == no]
        if len(exact) == 1:
            return "exact", exact
        if len(by_desc) == 1:
            return "description", by_desc
        if len(by_desc) > 1:
            return "ambiguous", by_desc
        by_no = self.by_no.get(no, []) if no else []
        if len(by_no) == 1:
            return "number", by_no
        if len(by_no) > 1:
            return "ambiguous", by_no
        return "none", []


class ItemIndex:
    """The company's stock (RM) items, by code and by name."""

    def __init__(self, db, client_id):
        self.items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.kind == "RM").all()}
        self.by_code, self.by_name = {}, {}
        for i in self.items.values():
            self.by_code.setdefault(squeeze(i.item_code), []).append(i)
            self.by_name.setdefault(squeeze(i.item_name), []).append(i)

    def find(self, text):
        key = squeeze(text)
        return (self.by_code.get(key) or self.by_name.get(key) or []) if key else []


def base_uoms(db, items):
    settings = {s.item_id: s.base_uom for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_([i.id for i in items] or [0])).all()}
    return {i.id: (settings.get(i.id) or i.units_of_measure or "") for i in items}


def existing_norms(db, client_id, boq_ids):
    """{(boq_item_id, item_id): norm} already set on these BOQ lines."""
    rows = db.query(DBStoreMaterialNorm).filter(DBStoreMaterialNorm.client_id == client_id, DBStoreMaterialNorm.boq_item_id.in_(list(boq_ids) or [0])).all()
    return {(n.boq_item_id, n.item_id): n for n in rows}


def same_figures(norm, qty, wastage) -> bool:
    return Decimal(str(norm.qty_per_unit)) == qty and Decimal(str(norm.wastage_pct or 0)) == wastage


# --- numbers --------------------------------------------------------------------------------------------------------------

def _number(raw):
    text = str(raw if raw is not None else "").strip().replace(",", "").rstrip("%").strip()
    if not text:
        return None, "blank"
    try:
        d = Decimal(text)
    except InvalidOperation:
        return None, "not a number"
    if not d.is_finite():
        return None, "not a number"
    return d, ""


def check_qty(raw):
    """(quantity, problem). More than zero, at most 999999, kept to six places."""
    d, why = _number(raw)
    if d is None:
        return None, "Qty Per Unit is %s." % ("missing" if why == "blank" else "not a number")
    if d <= 0:
        return None, "Qty Per Unit must be more than zero."
    if d > QTY_HIGH:
        return None, "Qty Per Unit is more than 999999."
    d = d.quantize(QTY_STEP)
    if d <= 0:
        return None, "Qty Per Unit is too small: at least 0.000001."
    return d, ""


def check_wastage(raw):
    """(percent, problem). Required (0 when there is none), from 0 to 100. No default is assumed."""
    d, why = _number(raw)
    if d is None:
        return None, "Wastage %% is %s (write 0 when there is none)." % ("missing" if why == "blank" else "not a number")
    if d < 0:
        return None, "Wastage % cannot be negative."
    if d > 100:
        return None, "Wastage % cannot be more than 100."
    return d.quantize(Decimal("0.01")), ""


# --- the sheet --------------------------------------------------------------------------------------------------------------

def map_columns(header):
    """{field: column index} from the sheet's heading row. Refuses a sheet missing any of the four."""
    keys = [_key(h) for h in header]
    found = {}
    for field, names in HEADERS.items():
        for name in names:
            hits = [i for i, k in enumerate(keys) if k == name and i not in found.values()]
            if hits:
                found[field] = hits[0]
                break
    missing = [LABELS[f] for f in HEADERS if f not in found]
    if missing:
        raise HTTPException(400, "The sheet has no %s column. Its headings must be: %s. Download the template to start from.%s"
                            % (" or ".join(missing), ", ".join(TEMPLATE_HEADERS), sheet_note()))
    return found


def classify(db, client_id, job_id, header, body, mode):
    """Every row of the sheet, checked, with what saving it would do. Writes nothing.
    A row: {line, boq_text, material_text, qty_text, wastage_text, boq_item_id, boq_item, item_id, item_code, item_name, base_uom, qty_per_unit,
            wastage_pct, valid, action, errors, flags, current}
    action: insert | update | unchanged | skip (already set, and the mode adds new ones only) | error"""
    if mode not in MODES:
        raise HTTPException(400, "Choose to add new norms or to update existing ones.")
    if len(body) > MAX_ROWS:
        raise HTTPException(400, "The sheet has %d rows; import at most %d at once." % (len(body), MAX_ROWS))
    cols = map_columns(header)
    lines = priced_lines(db, client_id, job_id)
    if not lines:
        raise HTTPException(400, "This project has no BOQ items to set norms on. Its BOQ comes first.")
    boqs, items = BoqIndex(lines), ItemIndex(db, client_id)
    uoms = base_uoms(db, items.items.values())

    def cell(row, field):
        i = cols[field]
        return str(row[i] if i < len(row) and row[i] is not None else "").strip()

    rows = []
    for line_no, raw in body:
        r = {"line": line_no, "boq_text": cell(raw, "boq"), "material_text": cell(raw, "material"), "qty_text": cell(raw, "qty"), "wastage_text": cell(raw, "wastage"),
             "boq_item_id": None, "boq_item": "", "item_id": None, "item_code": "", "item_name": "", "base_uom": "", "qty_per_unit": None, "wastage_pct": None,
             "errors": [], "flags": [], "current": None}
        if not r["boq_text"]:
            r["errors"].append("BOQ Item is missing.")
            r["flags"].append("missing_boq")
        else:
            found = boqs.find(r["boq_text"])
            if len(found) == 1:
                r["boq_item_id"], r["boq_item"] = found[0].id, boq_label(found[0])
            elif found:
                r["errors"].append("'%s' could be %d BOQ items (%s): write the item number." % (r["boq_text"], len(found), ", ".join(boq_label(l)[:30] for l in found[:3])))
                r["flags"].append("missing_boq")
            else:
                r["errors"].append("'%s' is not a BOQ item of this project." % r["boq_text"][:60])
                r["flags"].append("missing_boq")
        if not r["material_text"]:
            r["errors"].append("Material is missing.")
            r["flags"].append("missing_material")
        else:
            found = items.find(r["material_text"])
            if len(found) == 1:
                it = found[0]
                r["item_id"], r["item_code"], r["item_name"], r["base_uom"] = it.id, it.item_code, it.item_name, uoms.get(it.id, "")
            elif found:
                r["errors"].append("'%s' is the name of %d items (%s): write the item code." % (r["material_text"], len(found), ", ".join(i.item_code for i in found[:3])))
                r["flags"].append("missing_material")
            else:
                r["errors"].append("'%s' is not a stock item in the item master." % r["material_text"][:60])
                r["flags"].append("missing_material")
        qty, why = check_qty(r["qty_text"])
        if why:
            r["errors"].append(why)
            r["flags"].append("invalid_qty")
        wastage, why = check_wastage(r["wastage_text"])
        if why:
            r["errors"].append(why)
            r["flags"].append("invalid_wastage")
        r["qty_per_unit"], r["wastage_pct"] = qty, wastage
        rows.append(r)

    # The same BOQ item and material twice: neither is taken, since which one was meant cannot be told.
    seen = {}
    for r in rows:
        if r["boq_item_id"] and r["item_id"]:
            seen.setdefault((r["boq_item_id"], r["item_id"]), []).append(r)
    for pair, group in seen.items():
        if len(group) > 1:
            for r in group:
                others = [str(o["line"]) for o in group if o is not r]
                r["errors"].append("The same BOQ item and material are on line%s %s too." % ("s" if len(others) > 1 else "", ", ".join(others)))
                r["flags"].append("duplicate")

    have = existing_norms(db, client_id, {r["boq_item_id"] for r in rows if r["boq_item_id"]})
    for r in rows:
        r["valid"] = not r["errors"]
        if not r["valid"]:
            r["action"] = "error"
            continue
        current = have.get((r["boq_item_id"], r["item_id"]))
        if current is None:
            r["action"] = "insert"
        else:
            r["current"] = {"id": current.id, "qty_per_unit": Decimal(str(current.qty_per_unit)), "wastage_pct": Decimal(str(current.wastage_pct or 0))}
            r["action"] = "skip" if mode == "add" else ("unchanged" if same_figures(current, r["qty_per_unit"], r["wastage_pct"]) else "update")
    return rows


def summarise(rows):
    count = lambda a: sum(1 for r in rows if r["action"] == a)
    return {"total": len(rows), "valid": sum(1 for r in rows if r["valid"]), "invalid": count("error"), "insert": count("insert"), "update": count("update"),
            "unchanged": count("unchanged"), "skip": count("skip"),
            "missing_boq": sum(1 for r in rows if "missing_boq" in r["flags"]), "missing_material": sum(1 for r in rows if "missing_material" in r["flags"]),
            "duplicate": sum(1 for r in rows if "duplicate" in r["flags"]), "invalid_qty": sum(1 for r in rows if "invalid_qty" in r["flags"] or "invalid_wastage" in r["flags"])}


def commit_sheet(db, client_id, rows, who):
    """Save the good rows of a classified sheet. The caller commits (or rolls back) - all of them or none."""
    have = existing_norms(db, client_id, {r["boq_item_id"] for r in rows if r["valid"]})
    now = datetime.now()
    for r in rows:
        if r["action"] == "insert":
            db.add(DBStoreMaterialNorm(client_id=client_id, boq_item_id=r["boq_item_id"], item_id=r["item_id"], qty_per_unit=r["qty_per_unit"],
                                       wastage_pct=r["wastage_pct"], notes="", updated_by_name=who, updated_at=now))
        elif r["action"] == "update":
            n = have[(r["boq_item_id"], r["item_id"])]
            n.qty_per_unit, n.wastage_pct, n.updated_by_name, n.updated_at = r["qty_per_unit"], r["wastage_pct"], who, now
    db.flush()
    s = summarise(rows)
    return {"inserted": s["insert"], "updated": s["update"], "unchanged": s["unchanged"], "skipped_existing": s["skip"], "invalid": s["invalid"], "total": s["total"]}


# --- another project ------------------------------------------------------------------------------------------------------------

def source_norms(db, client_id, job_id):
    """[(norm, its BOQ line)] of a project - whichever revision the line is on."""
    return (db.query(DBStoreMaterialNorm, models.DBBoqLine).join(models.DBBoqLine, models.DBBoqLine.id == DBStoreMaterialNorm.boq_item_id)
            .join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id)
            .filter(DBStoreMaterialNorm.client_id == client_id, models.DBBoq.job_id == job_id, models.DBBoq.client_id == client_id)
            .order_by(models.DBBoqLine.display_order, models.DBBoqLine.id, DBStoreMaterialNorm.id).all())


def copy_preview(db, client_id, source_id, dest_id, mode):
    """Each norm of the source project, with the BOQ item of this project it would go to and what copying it would do. Writes nothing.
    status: insert | update | unchanged | skip (already set here) | choose (more than one line could be it) | no_boq (no line here is that
            work) | no_material (the item is no longer a stock item). needs_confirmation: the line was found by its number alone, or is
            one of several, so a person must say which line it is before it is copied."""
    if mode not in COPY_MODES:
        raise HTTPException(400, "Choose to add the missing norms or to replace the matching ones.")
    lines = priced_lines(db, client_id, dest_id)
    here, items = BoqIndex(lines), ItemIndex(db, client_id)
    found = source_norms(db, client_id, source_id)
    uoms = base_uoms(db, [items.items[n.item_id] for n, _l in found if n.item_id in items.items])
    have = existing_norms(db, client_id, here.lines)
    rows = []
    for n, line in found:
        kind, candidates = here.same_work(line)
        it = items.items.get(n.item_id)
        r = {"source_norm_id": n.id, "source_boq_item_id": line.id, "source_boq_item": boq_label(line), "source_boq_uom": line.uom or "",
             "item_id": n.item_id, "item_code": it.item_code if it else "", "item_name": it.item_name if it else "(item no longer in the master)",
             "base_uom": uoms.get(n.item_id, ""), "qty_per_unit": Decimal(str(n.qty_per_unit)), "wastage_pct": Decimal(str(n.wastage_pct or 0)),
             "match": kind, "candidates": [{"id": l.id, "label": boq_label(l), "uom": l.uom or ""} for l in candidates[:10]],
             "boq_item_id": candidates[0].id if len(candidates) == 1 else None, "boq_item": boq_label(candidates[0]) if len(candidates) == 1 else "", "current": None}
        if it is None:
            r["status"] = "no_material"
        elif kind == "none":
            r["status"] = "no_boq"
        elif kind == "ambiguous":
            r["status"] = "choose"
        else:
            r["status"] = _copy_action(have.get((r["boq_item_id"], n.item_id)), r, mode)
        # Matched on the number alone, or one of several: copied only once a person has said which line it is.
        r["needs_confirmation"] = kind in ("number", "ambiguous")
        rows.append(r)
    return rows


def _copy_action(current, r, mode):
    if current is None:
        return "insert"
    r["current"] = {"id": current.id, "qty_per_unit": Decimal(str(current.qty_per_unit)), "wastage_pct": Decimal(str(current.wastage_pct or 0))}
    if mode == "add":
        return "skip"
    return "unchanged" if same_figures(current, r["qty_per_unit"], r["wastage_pct"]) else "update"


def copy_commit(db, client_id, source_id, dest_id, mode, mappings, who):
    """Copy the norms a person confirmed, each to the BOQ line of this project they chose for it. Every pairing is checked again here;
    one that does not hold refuses the whole copy. The caller commits."""
    if mode not in COPY_MODES:
        raise HTTPException(400, "Choose to add the missing norms or to replace the matching ones.")
    if not mappings:
        raise HTTPException(400, "Nothing was chosen to copy.")
    if len(mappings) > MAX_ROWS:
        raise HTTPException(400, "Copy at most %d norms at once." % MAX_ROWS)
    lines = {l.id: l for l in priced_lines(db, client_id, dest_id)}
    if not lines:
        raise HTTPException(400, "This project has no BOQ items to copy norms to. Its BOQ comes first.")
    found = {n.id: (n, l) for n, l in source_norms(db, client_id, source_id)}
    items = ItemIndex(db, client_id).items
    have = existing_norms(db, client_id, lines)
    targets, plan = {}, []
    for m in mappings:
        src = found.get(m["source_norm_id"])
        if src is None:
            raise HTTPException(400, "A norm chosen to copy is not one of the source project's.")
        n, _line = src
        if m["boq_item_id"] not in lines:
            raise HTTPException(400, "A BOQ item chosen to copy to is not a priced item of this project's current BOQ.")
        if n.item_id not in items:
            raise HTTPException(400, "A material chosen to copy is no longer a stock item of the company.")
        pair = (m["boq_item_id"], n.item_id)
        if pair in targets:
            raise HTTPException(409, "Two norms of %s were chosen for the same BOQ item (%s). Keep one." % (items[n.item_id].item_name, boq_label(lines[pair[0]])))
        targets[pair] = n
        plan.append((pair, n))
    now = datetime.now()
    inserted = updated = skipped = unchanged = 0
    for (boq_id, item_id), n in plan:
        qty, wastage = Decimal(str(n.qty_per_unit)), Decimal(str(n.wastage_pct or 0))
        current = have.get((boq_id, item_id))
        if current is None:
            db.add(DBStoreMaterialNorm(client_id=client_id, boq_item_id=boq_id, item_id=item_id, qty_per_unit=qty, wastage_pct=wastage,
                                       notes=n.notes or "", updated_by_name=who, updated_at=now))
            inserted += 1
        elif mode == "add":
            skipped += 1
        elif same_figures(current, qty, wastage):
            unchanged += 1
        else:
            current.qty_per_unit, current.wastage_pct, current.updated_by_name, current.updated_at = qty, wastage, who, now
            updated += 1
    db.flush()
    return {"copied": inserted, "updated": updated, "unchanged": unchanged, "skipped_existing": skipped, "not_chosen": len(found) - len(plan), "source_norms": len(found)}


# --- the work items' norms (Item Master) ----------------------------------------------------------------------------------------

def from_work_preview(db, client_id, job_id, mode):
    """For each priced BOQ item of the project, the norms of the work item it is, as this project's norms would take them. Writes
    nothing. (rows, lines): rows have status insert | update | unchanged | skip (already set here, kept) | unit (the BOQ item and the
    work item count in different units) | no_material (no longer a stock item); lines = {no_work, no_norms} counts."""
    from app.services.item_norms import norms_of, same_unit
    from app.services.item_sheet import line_works, sheet_of
    if mode not in COPY_MODES:
        raise HTTPException(400, "Choose to add the missing norms or to replace the matching ones.")
    lines = priced_lines(db, client_id, job_id)
    works = line_works(db, client_id, sheet_of(db, client_id, job_id), lines)
    norms = norms_of(db, client_id, [w.id for w, _src in works.values()])
    items = ItemIndex(db, client_id).items
    uoms = base_uoms(db, [items[n.material_id] for ns in norms.values() for n in ns if n.material_id in items])
    have = existing_norms(db, client_id, [l.id for l in lines])
    rows, counts = [], {"no_work": 0, "no_norms": 0}
    for l in lines:
        work = works.get(l.key, (None, ""))[0]
        if work is None:
            counts["no_work"] += 1
            continue
        if not norms.get(work.id):
            counts["no_norms"] += 1
            continue
        unit_ok = not l.uom or not work.units_of_measure or same_unit(l.uom, work.units_of_measure)
        for n in norms[work.id]:
            it = items.get(n.material_id)
            r = {"boq_item_id": l.id, "boq_item": boq_label(l), "boq_uom": l.uom or "", "work_item_id": work.id, "work_code": work.item_code,
                 "work_name": work.item_name, "work_uom": work.units_of_measure or "", "item_id": n.material_id,
                 "item_code": it.item_code if it else "", "item_name": it.item_name if it else "(no longer a stock item)", "base_uom": uoms.get(n.material_id, ""),
                 "qty_per_unit": Decimal(str(round(float(n.qty_per_unit or 0), 6))), "wastage_pct": Decimal(str(round(float(n.wastage_pct or 0), 3))), "current": None}
            if it is None or it.is_active is False or it.merged_into_id:
                r["status"] = "no_material"
            elif not unit_ok:
                r["status"] = "unit"
            else:
                r["status"] = _copy_action(have.get((l.id, n.material_id)), r, mode)
            rows.append(r)
    return rows, counts


def from_work_commit(db, client_id, job_id, mode, who):
    """Set the project's norms from its work items' norms, as the preview says. The caller commits."""
    rows, counts = from_work_preview(db, client_id, job_id, mode)
    if not any(r["status"] in ("insert", "update") for r in rows):
        raise HTTPException(400, "There is nothing to bring in: no BOQ item of this project has a work item with norms that are not set here already.")
    have = existing_norms(db, client_id, {r["boq_item_id"] for r in rows})
    now = datetime.now()
    done = {"inserted": 0, "updated": 0}
    for r in rows:
        if r["status"] == "insert":
            db.add(DBStoreMaterialNorm(client_id=client_id, boq_item_id=r["boq_item_id"], item_id=r["item_id"], qty_per_unit=r["qty_per_unit"],
                                       wastage_pct=r["wastage_pct"], notes="From the norms of work item %s" % r["work_code"], updated_by_name=who, updated_at=now))
            done["inserted"] += 1
        elif r["status"] == "update":
            n = have[(r["boq_item_id"], r["item_id"])]
            n.qty_per_unit, n.wastage_pct, n.updated_by_name, n.updated_at = r["qty_per_unit"], r["wastage_pct"], who, now
            done["updated"] += 1
    db.flush()
    count = lambda st: sum(1 for r in rows if r["status"] == st)
    return {**done, "unchanged": count("unchanged"), "skipped_existing": count("skip"), "unit": count("unit"), "no_material": count("no_material"), **counts}
