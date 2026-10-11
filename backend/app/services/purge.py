"""Taking a record away with everything that hangs off it. The Master's delete, for every kind of record and for a project.

What points at a record is read from the live database's own foreign keys, so a link an older release left behind - or
one a model never mentioned - cannot stop a delete on Postgres. For each pointer there are two answers:
  - the row belongs to the record (a bill's lines, an invoice's payments, an order's measurements): it goes too, and so
    does whatever hangs off it;
  - the row is a document that merely names the record (a bill that names its purchase order, a measurement that names
    the RA bill it was billed on): it stays and the pointer is cleared, so the history is not lost.
Records that point at it by a type and a number instead of a key (payments, photos, approvals, alerts) are cleared too.
"""
from sqlalchemy import text, bindparam

from app import models
from app.core.audit import log_audit
from app.core.files import drop_files_of
from app.services.subcontract_orders import _fk_map, drop_alerts_about, sweep_referrers

# Rows that belong to the record they point at, even though the column may be left empty.
OWNED = {
    ("purchase_order_line_items", "order_id"), ("goods_receipt_lines", "goods_receipt_id"), ("bill_line_items", "bill_id"),
    ("line_items", "invoice_id"), ("quote_line_items", "quote_id"), ("estimate_items", "estimate_id"),
    ("rate_analyses", "estimate_item_id"), ("diary_labour", "site_diary_id"), ("diary_plant", "site_diary_id"),
    ("stock_issue_lines", "stock_issue_id"), ("ra_bill_lines", "ra_bill_id"), ("ra_bill_lines", "line_id"),
    ("variation_lines", "variation_order_id"), ("variation_lines", "line_id"), ("work_order_lines", "work_order_id"),
    ("sub_bill_lines", "sub_bill_id"), ("subcontract_items", "order_id"), ("subcontract_approvals", "order_id"),
    ("subcontract_terms", "order_id"), ("order_access", "order_id"),
    ("measurements", "work_order_id"), ("measurements", "line_id"),
    ("measurement_dimensions", "measurement_id"), ("measurement_dimensions", "sub_measurement_id"),
    ("ra_bills", "work_order_id"), ("retention_releases", "work_order_id"),
}

# What the Master can delete one at a time: kind -> (table, model, what it is called, the column that names it).
KINDS = {
    "purchase_order": ("purchase_orders", "DBPurchaseOrder", "purchase order", "number"),
    "grn": ("goods_receipts", "DBGoodsReceipt", "goods receipt", "number"),
    "rfq": ("rfqs", "DBRfq", "enquiry", "number"),
    "supplier_bill": ("bills", "DBBill", "supplier bill", "number"),
    "invoice": ("invoices", "DBInvoice", "invoice", "number"),
    "quote": ("quotes", "DBQuote", "quote", "number"),
    "estimate": ("estimates", "DBEstimate", "estimate", "number"),
    "lead": ("leads", "DBLead", "tender", "number"),
    "ra_bill": ("ra_bills", "DBRABill", "RA bill", "number"),
    "variation_order": ("variation_orders", "DBVariationOrder", "variation order", "number"),
    "boq_variation": ("boq_variations", "DBBoqVariation", "BOQ variation", "number"),
    "boq": ("boqs", "DBBoq", "BOQ", "number"),
    "budget": ("project_budgets", "DBProjectBudget", "budget", "name"),
    "drawing": ("drawings", "DBDrawing", "drawing", "number"),
    "diary": ("site_diaries", "DBSiteDiary", "site diary day", "diary_date"),
    "inspection": ("qc_inspections", "DBInspection", "inspection", "number"),
    "cube_set": ("qc_cube_sets", "DBCubeSet", "cube set", "number"),
    "ncr": ("qc_ncrs", "DBNcr", "NCR", "number"),
    "incident": ("safety_incidents", "DBSafetyIncident", "incident", "number"),
    "toolbox": ("toolbox_talks", "DBToolboxTalk", "toolbox talk", "topic"),
    "permit": ("work_permits", "DBWorkPermit", "permit", "number"),
    "equipment": ("assets", "DBAsset", "equipment", "name"),
    "activity": ("schedule_activities", "DBScheduleActivity", "activity", "name"),
    "stock_issue": ("stock_issues", "DBStockIssue", "stock issue", "number"),
    "eway": ("eway_bills", "DBEwayBill", "e-way bill", "number"),
    "payment": ("money_entries", "DBMoneyEntry", "payment or receipt", "number"),
    "thread": ("project_threads", "DBProjectThread", "chat thread", "title"),
    "retention_release": ("retention_releases", "DBRetentionRelease", "retention release", "number"),
    "attendance": ("attendance", "DBAttendance", "timesheet entry", "id"),
    "supplier": ("suppliers", "DBSupplier", "supplier", "name"),
    "item": ("erp_items", "DBItem", "item", "item_code"),
}

# What is kept about a record under a type name instead of a link.
POLY = {
    "bills": {"money": ["supplier_bill"], "entity": ["bill"], "alert": ["supplier_bill"], "files": ["bill"]},
    "purchase_orders": {"entity": ["purchase_order"]},
    "invoices": {"entity": ["invoice"]},
    "ra_bills": {"money": ["ra_bill"], "alert": ["ra_bill"]},
    "sub_bills": {"money": ["sub_bill"], "entity": ["sub_bill"], "alert": ["sub_bill"], "files": ["sub_bill_scan"]},
    "subcontract_orders": {"money": ["sub_advance"], "entity": ["subcontract_order"], "alert": ["subcontract_order"], "files": ["subcontract_order"]},
    "retention_releases": {"money": ["retention_release"], "alert": ["retention_release"]},
    "work_orders": {"entity": ["work_order"]},
    "boq_variations": {"entity": ["boq_variation"], "alert": ["boq_variation"], "files": ["variation"]},
    "variation_orders": {"alert": ["variation"], "files": ["variation"]},
    "measurements": {"files": ["measurement"]},
    "sub_measurements": {"files": ["sub_measurement"]},
    "site_diaries": {"files": ["diary"]},
    "drawings": {"files": ["drawing"]},
    "project_threads": {"files": ["thread"], "alert": ["thread"]},
    "qc_inspections": {"alert": ["inspection"]}, "qc_ncrs": {"alert": ["ncr"]},
    "safety_incidents": {"alert": ["incident"]}, "qc_cube_sets": {"alert": ["cube_set"]},
    "money_entries": {"alert": ["money"]},
}

# Kept, with the link to the project cleared, when a project goes: they exist before and apart from it.
PROJECT_UNLINK = [("assets", "current_job_id"), ("leads", "job_id"), ("estimates", "job_id")]


def _in(db, sql, ids):
    return db.execute(text(sql).bindparams(bindparam("ids", expanding=True)), {"ids": list(ids)})


def _poly(db, table, ids, counts):
    p = POLY.get(table)
    if not p:
        return
    for t in p.get("money", []):
        n = _in(db, "DELETE FROM money_entries WHERE doc_type = '%s' AND doc_id IN :ids" % t, ids).rowcount
        if n:
            counts["payments"] = counts.get("payments", 0) + n
    for t in p.get("entity", []):
        _in(db, "DELETE FROM approval_chains WHERE entity_type = '%s' AND entity_id IN :ids" % t, ids)
    for t in p.get("alert", []):
        drop_alerts_about(db, t, ids)
    for t in p.get("files", []):
        drop_files_of(db, t, ids)


def purge(db, table, ids, counts=None, _depth=0):
    """Remove these rows and whatever belongs to them. `counts` collects what went, by table."""
    ids = sorted(set(ids))
    counts = {} if counts is None else counts
    if not ids or _depth > 10:
        return counts
    for child, col, nullable, pk in _fk_map(db).get(table, []):
        if child == table:
            if nullable:
                _in(db, "UPDATE %s SET %s = NULL WHERE %s IN :ids" % (child, col, col), ids)
            continue
        if nullable and (child, col) not in OWNED:
            _in(db, "UPDATE %s SET %s = NULL WHERE %s IN :ids" % (child, col, col), ids)
            continue
        if pk == ["id"]:
            kids = [r[0] for r in _in(db, "SELECT %s FROM %s WHERE %s IN :ids" % (pk[0], child, col), ids).fetchall()]
            if kids:
                purge(db, child, kids, counts, _depth + 1)
                counts[child] = counts.get(child, 0) + len(kids)
                continue                                  # the recursive call already deleted them
        _in(db, "DELETE FROM %s WHERE %s IN :ids" % (child, col), ids)
    _poly(db, table, ids, counts)
    _in(db, "DELETE FROM %s WHERE id IN :ids" % table, ids)
    return counts


def explain(db, table, ids):
    """What a delete would take with it, without taking it: run it and roll it back."""
    counts = purge(db, table, ids)
    db.rollback()
    return {k: v for k, v in counts.items() if v}


LABELS = {
    "purchase_order_line_items": "purchase order lines", "goods_receipt_lines": "goods receipt lines", "bill_line_items": "bill lines",
    "line_items": "invoice lines", "payments": "payments", "money_entries": "payments", "sub_bills": "contractor bills",
    "ra_bills": "RA bills", "measurements": "measurements", "sub_measurements": "measurements", "work_orders": "client work orders",
    "subcontract_orders": "work orders", "purchase_orders": "purchase orders", "goods_receipts": "goods receipts", "bills": "supplier bills",
    "invoices": "invoices", "quotes": "quotes", "rfqs": "enquiries", "rfq_quotes": "supplier quotes", "boqs": "BOQs", "drawings": "drawings",
    "site_diaries": "site diary days", "qc_inspections": "inspections", "qc_cube_sets": "cube sets", "qc_ncrs": "NCRs",
    "safety_incidents": "incidents", "toolbox_talks": "toolbox talks", "work_permits": "permits", "schedule_activities": "activities",
    "stock_issues": "stock issues", "stock_movements": "stock movements", "eway_bills": "e-way bills", "project_threads": "chat threads",
    "project_messages": "chat messages", "project_budgets": "budgets", "project_files": "photos and files", "attendance": "timesheet entries",
    "variation_orders": "variation orders", "boq_variations": "BOQ variations", "retention_releases": "retention releases",
    "back_charges": "back-charges", "asset_logs": "equipment logs", "asset_services": "equipment services", "employee_sites": "staff assignments",
    "site_geofences": "site fences", "material_recoveries": "material recoveries", "diary_labour": "labour lines", "diary_plant": "plant lines",
    "assets": "equipment", "leads": "tenders", "estimates": "estimates",
    "subcontract_items": "schedule lines", "boq_lines": "BOQ lines", "work_order_lines": "work order lines", "ra_bill_lines": "RA bill lines",
}


def human(counts):
    """{"table": n} as {"what it is": n}, the things a person would name."""
    out = {}
    for k, v in counts.items():
        if k in LABELS and v:
            out[LABELS[k]] = out.get(LABELS[k], 0) + v
    return out


def kind_or_404(kind):
    from fastapi import HTTPException
    if kind not in KINDS:
        raise HTTPException(404, "That kind of record cannot be deleted here")
    return KINDS[kind]


def record(db, client_id, kind, rec_id):
    from fastapi import HTTPException
    table, model, noun, col = kind_or_404(kind)
    cls = getattr(models, model)
    row = db.query(cls).filter(cls.id == rec_id, cls.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "%s not found" % noun.capitalize())
    return row, table, noun, str(getattr(row, col, "") or "") or "#%d" % row.id


def delete_one(db, request, client, kind, rec_id):
    row, table, noun, label = record(db, client.id, kind, rec_id)
    counts = purge(db, table, [row.id])
    note = ", ".join("%d %s" % (n, k) for k, n in sorted(human(counts).items()))
    log_audit(db, client.id, "master_deleted", kind, rec_id, label, "Deleted with %s" % note if note else "Deleted", request)
    db.commit()
    return "%s %s deleted%s." % (noun.capitalize(), label, (", with " + note) if note else "")


# --- a project ----------------------------------------------------------------------------------------------------

def project_owned(db):
    """(table, column) for every table that holds a row about a project, read from the database: a table added later
    that points at a project is covered without being listed here."""
    skip = {t for t, _ in PROJECT_UNLINK}
    return [(t, c) for t, c, _nullable, _pk in _fk_map(db).get("jobs", []) if t not in skip]


def delete_project(db, request, client, job):
    counts = {}
    # A gang's work orders first, each with everything its own delete takes (its bills, measurements, payments).
    from app.services.subcontract_orders import wo_delete_order_now
    for o in db.query(models.DBSubcontractOrder.id).filter(
            models.DBSubcontractOrder.client_id == client.id, models.DBSubcontractOrder.job_id == job.id).all():
        if db.query(models.DBSubcontractOrder.id).filter(models.DBSubcontractOrder.id == o.id).first():
            wo_delete_order_now(o.id, request, db)
            counts["subcontract_orders"] = counts.get("subcontract_orders", 0) + 1
    # Then every other record that is about the project. Children before their parents: a bill before the order it names.
    order = {t.name: i for i, t in enumerate(models.Base.metadata.sorted_tables)}
    for table, col in sorted(project_owned(db), key=lambda tc: -order.get(tc[0], 0)):
        ids = [r[0] for r in _in(db, "SELECT id FROM %s WHERE %s IN :ids" % (table, col), [job.id]).fetchall()] \
            if _has_id(db, table) else []
        if ids:
            purge(db, table, ids, counts)
            counts[table] = counts.get(table, 0) + len(ids)
        else:
            _in(db, "DELETE FROM %s WHERE %s IN :ids" % (table, col), [job.id])
    for table, col in PROJECT_UNLINK:
        _in(db, "UPDATE %s SET %s = NULL WHERE %s IN :ids" % (table, col, col), [job.id])
    # Photos and money filed against the project by its number alone.
    _in(db, "DELETE FROM project_files WHERE job_id IN :ids", [job.id])
    sweep_referrers(db, {"jobs": [job.id]})
    _in(db, "DELETE FROM jobs WHERE id IN :ids", [job.id])
    note = ", ".join("%d %s" % (n, k) for k, n in sorted(human(counts).items()))
    log_audit(db, client.id, "job_deleted", "job", job.id, job.number, "Deleted with %s" % note if note else "Deleted", request)
    db.commit()
    return counts


def _has_id(db, table):
    from sqlalchemy import inspect
    return any(c["name"] == "id" for c in inspect(db.get_bind()).get_columns(table))


def project_report(db, client, job):
    """What deleting the project would take, counted from the project's own records."""
    counts = {}
    for table, col in project_owned(db):
        n = _in(db, "SELECT COUNT(*) FROM %s WHERE %s IN :ids" % (table, col), [job.id]).scalar() or 0
        if n:
            counts[table] = n
    unlinked = {}
    for table, col in PROJECT_UNLINK:
        n = _in(db, "SELECT COUNT(*) FROM %s WHERE %s IN :ids" % (table, col), [job.id]).scalar() or 0
        if n:
            unlinked[table] = n
    return {"counts": human(counts), "kept": human(unlinked) or {}, "unlinked": unlinked}
