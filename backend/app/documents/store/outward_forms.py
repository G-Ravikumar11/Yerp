"""Store module - printed outward forms: the material issue slip (to site or to a subcontractor) and the return slip, in the ruled,
boxed form the trade signs (app/documents/form_pdf.py draws them). Owned by P3."""
from datetime import datetime

from app import models
from app.documents import form_pdf
from app.documents.letterhead import letterhead
from app.models.store_core import DBStore, DBStoreBin, DBStoreStockLedger
from app.models.store_outward import DBStoreIndent, DBStoreIssue, DBStoreRecovery, ISSUE, SUBCONTRACTOR
from app.services import store_outward as svc

WATERMARK = {"DRAFT": "DRAFT - NOT POSTED", "SUBMITTED": "NOT YET APPROVED", "APPROVED": "NOT YET POSTED", "CANCELLED": "CANCELLED"}


def _n(x):
    return form_pdf.qty_text(x)


def _money(x):
    return form_pdf.plain_number(x, 2)


def _boq_text(db, boq_id):
    row = db.get(models.DBBoqLine, boq_id) if boq_id else None
    return ("%s %s" % (row.item_no or "", (row.description or "").split("\n")[0][:40])).strip() if row else ""


def _finish(db, client, doc, title, blocks, signs):
    blocks.append({"type": "signatures", "boxes": signs})
    company = letterhead(db, client)
    return {"title": "%s %s" % (title, doc.number), "author": company["name"], "watermark": WATERMARK.get(doc.status, ""), "blocks": blocks,
            "footer": "%s  |  %s  |  Printed %s" % (doc.number, company["name"], datetime.now().strftime("%d/%m/%Y %H:%M"))}


def _recovery_text(line, rec):
    """What the subcontractor is charged, in words: free of cost, or the rate and how it was set."""
    if not line.chargeable:
        return "Free of cost"
    if rec is None:
        return "%s%s" % ("Contract rate" if line.recovery_basis == "CONTRACT_RATE" else "Average cost", " + %s%%" % _n(line.handling_pct) if float(line.handling_pct or 0) else "")
    base = "contract" if rec.basis == "CONTRACT_RATE" else "avg cost"
    return "Rs %s (%s%s)" % (_money(rec.recovery_rate), base, " + %s%%" % _n(rec.handling_pct) if float(rec.handling_pct or 0) else "")


def issue_form(db, client, issue):
    lines = svc.issue_lines(db, issue)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}
    store = db.get(DBStore, issue.store_id)
    job = db.get(models.DBJob, issue.project_id)
    wo = db.get(models.DBWorkOrder, issue.work_order_id) if issue.work_order_id else None
    rates = {}
    if issue.status == "POSTED":
        for r in db.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == ISSUE, DBStoreStockLedger.ref_doc_id == issue.id, DBStoreStockLedger.reversal_of_id.is_(None)).all():
            rates[r.ref_line_id] = (float(r.rate), float(r.value))
    sub = issue.issue_type == SUBCONTRACTOR
    recs = {x.issue_line_id: x for x in db.query(DBStoreRecovery).filter(DBStoreRecovery.issue_line_id.in_([l.id for l in lines] or [0]), DBStoreRecovery.source == "ISSUE", DBStoreRecovery.status == "OPEN").all()}
    rows, total = [], 0
    for i, l in enumerate(lines, 1):
        it = items.get(l.item_id)
        rate, value = rates.get(l.id, (0, 0))
        total += value
        row = [str(i), it.item_code if it else "", it.item_name if it else "", svc.base_uom_of(db, it) if it else "", _n(l.qty), _boq_text(db, l.boq_item_id) or (l.cost_head or "").replace("_", " ").title() or "-"]
        if issue.status == "POSTED":
            row += [_money(rate), _money(value)]
        if sub:
            row.append(_recovery_text(l, recs.get(l.id)))
        rows.append(row)
    columns = [("#", 7, "C"), ("Item Code", 24, "L"), ("Item", 46, "L"), ("Unit", 11, "C"), ("Qty", 17, "R"), ("Charged to", 36, "L")]
    if issue.status == "POSTED":
        columns += [("Rate", 15, "R"), ("Value", 18, "R")]
    if sub:
        columns.append(("Recovery", 26, "R"))
    scale = 182.0 / sum(w for _t, w, _a in columns)
    columns = [(t, round(w * scale, 1), a) for t, w, a in columns]
    facts = [("Date", form_pdf.date_text(issue.issue_date)), ("Store", "%s - %s" % (store.code, store.name) if store else "")]
    pairs = [("Project", ("%s - %s" % (job.number, job.name)) if job else "-"), ("Work order", wo.number if wo else "-"),
             ("Received by", ("%s (%s)" % (issue.received_by_name, (issue.received_by_type or "").title())) if issue.received_by_name else (issue.holder_name or "-")),
             ("Indent", db.get(DBStoreIndent, issue.indent_id).number if issue.indent_id else ("Direct issue" if issue.direct else "-")), ("Purpose", issue.purpose or "-"), ("Remarks", issue.remarks or "-")]
    blocks = [{"type": "header", "company": letterhead(db, client), "title": "MATERIAL ISSUE TO SUBCONTRACTOR" if sub else "MATERIAL ISSUE NOTE", "facts": [("No", issue.number), *facts]},
              {"type": "pairs", "cols": 2, "rows": pairs},
              {"type": "table", "columns": columns, "rows": rows, "totals": [("VALUE AT AVERAGE COST", _money(total), True)] if issue.status == "POSTED" else []}]
    return _finish(db, client, issue, "Subcontractor Material Issue" if sub else "Material Issue", blocks, [("Issued by (Storekeeper)", ""), ("Approved by", ""), ("Received by", issue.received_by_name or issue.holder_name or "")])


def return_form(db, client, ret):
    lines = svc.return_lines(db, ret)
    issue = db.get(DBStoreIssue, ret.issue_id)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}
    store = db.get(DBStore, ret.store_id)
    bins = {b.id: b.code for b in db.query(DBStoreBin).filter(DBStoreBin.id.in_([l.bin_id for l in lines if l.bin_id] or [0])).all()}
    rows = [[str(i), items[l.item_id].item_code, items[l.item_id].item_name, svc.base_uom_of(db, items[l.item_id]), _n(l.qty_returned), _n(l.qty_lost),
             ("Damaged - bin %s" % bins.get(l.bin_id, "?")) if l.condition == "DAMAGED" else "Good", l.reason or ""] for i, l in enumerate(lines, 1)]
    blocks = [{"type": "header", "company": letterhead(db, client), "title": "MATERIAL RETURN NOTE",
               "facts": [("No", ret.number), ("Date", form_pdf.date_text(ret.return_date)), ("Against", issue.number if issue else ""), ("Store", "%s - %s" % (store.code, store.name) if store else "")]},
              {"type": "pairs", "cols": 2, "rows": [("Returned by", issue.holder_name if issue and issue.holder_name else "Site"), ("Remarks", ret.remarks or "-")]},
              {"type": "table", "columns": [("#", 7, "C"), ("Item Code", 26, "L"), ("Item", 56, "L"), ("Unit", 12, "C"), ("Returned", 18, "R"), ("Lost", 14, "R"), ("Condition", 26, "L"), ("Remarks", 23, "L")], "rows": rows}]
    return _finish(db, client, ret, "Material Return", blocks, [("Returned by", ""), ("Received by (Storekeeper)", ""), ("Approved by", "")])


def indent_form(db, client, indent):
    lines = svc.indent_lines(db, indent)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}
    done = svc.indent_fulfilled(db, indent)
    store = db.get(DBStore, indent.store_id)
    job = db.get(models.DBJob, indent.project_id)
    wo = db.get(models.DBWorkOrder, indent.work_order_id) if indent.work_order_id else None
    boq = db.get(models.DBBoqLine, indent.boq_item_id) if indent.boq_item_id else None
    approved = indent.status not in ("DRAFT", "SUBMITTED", "CANCELLED")
    rows = []
    for i, l in enumerate(lines, 1):
        row = [str(i), items[l.item_id].item_code, items[l.item_id].item_name, svc.base_uom_of(db, items[l.item_id]), _n(l.qty)]
        if approved:
            row += [_n(l.approved_qty or 0), _n(done.get(l.id, 0)), _n(max(0, float(l.approved_qty or 0) - float(done.get(l.id, 0))))]
        row.append(l.purpose or "")
        rows.append(row)
    columns = [("#", 7, "C"), ("Item Code", 24, "L"), ("Item", 50, "L"), ("Unit", 11, "C"), ("Asked", 17, "R")]
    columns += [("Approved", 17, "R"), ("Issued", 15, "R"), ("Pending", 15, "R")] if approved else []
    columns.append(("Purpose", 42 if not approved else 26, "L"))
    scale = 182.0 / sum(w for _t, w, _a in columns)
    columns = [(t, round(w * scale, 1), a) for t, w, a in columns]
    blocks = [{"type": "header", "company": letterhead(db, client), "title": "MATERIAL INDENT", "facts": [("No", indent.number), ("Date", form_pdf.date_text(indent.indent_date)),
                                                                                                      ("Required by", form_pdf.date_text(indent.required_by) if indent.required_by else "-"), ("Store", "%s - %s" % (store.code, store.name) if store else "")]},
              {"type": "pairs", "cols": 2, "rows": [("Project", ("%s - %s" % (job.number, job.name)) if job else "-"), ("Work order", wo.number if wo else "-"),
                                                    ("BOQ item", ("%s %s" % (boq.item_no or "", (boq.description or "").split("\n")[0][:50])).strip() if boq else "-"), ("Activity", indent.activity or "-"),
                                                    ("Requested by", indent.requested_by_name or "-"), ("Approved by", (indent.approved_by_name or "-") + (" - " + indent.approver_remarks if indent.approver_remarks else "")),
                                                    ("Remarks", indent.remarks or "-")]},
              {"type": "table", "columns": columns, "rows": rows}]
    status = {"DRAFT": "DRAFT - NOT SUBMITTED", "SUBMITTED": "AWAITING APPROVAL", "CANCELLED": "CANCELLED"}.get(indent.status, "")
    blocks.append({"type": "signatures", "boxes": [("Requested by (Site engineer)", indent.requested_by_name or ""), ("Approved by (Project manager)", indent.approved_by_name or ""), ("Store", "")]})
    company = letterhead(db, client)
    return {"title": "Material Indent %s" % indent.number, "author": company["name"], "watermark": status, "blocks": blocks,
            "footer": "%s  |  %s  |  Printed %s" % (indent.number, company["name"], datetime.now().strftime("%d/%m/%Y %H:%M"))}


def gate_form(db, client, gp):
    lines = svc.gate_lines(db, gp)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}
    store = db.get(DBStore, gp.store_id)
    issue = db.get(DBStoreIssue, gp.issue_id)
    job = db.get(models.DBJob, issue.project_id) if issue else None
    rows = [[str(i), items[l.item_id].item_code, items[l.item_id].item_name, svc.base_uom_of(db, items[l.item_id]), _n(l.qty)] for i, l in enumerate(lines, 1)]
    pairs = [("Against issue", issue.number if issue else "-"), ("Project", ("%s - %s" % (job.number, job.name)) if job else "-"), ("Vehicle no.", gp.vehicle_no or "-"), ("Driver", gp.driver_name or "-"),
             ("Taking it to", gp.destination or "-"), ("Purpose", gp.purpose or "-"), ("Received by", (issue.received_by_name or issue.holder_name or "-") if issue else "-"), ("Authorised by", gp.authorised_by_name or "-")]
    if gp.returnable:
        pairs.insert(2, ("Due back", form_pdf.date_text(gp.expected_return_date) if gp.expected_return_date else "-"))
    blocks = [{"type": "header", "company": letterhead(db, client), "title": "RETURNABLE GATE PASS" if gp.returnable else "OUTWARD GATE PASS",
               "facts": [("No", gp.number), ("Date", form_pdf.date_text(gp.gate_date)), ("Store", "%s - %s" % (store.code, store.name) if store else "")]},
              {"type": "pairs", "cols": 2, "rows": pairs},
              {"type": "table", "columns": [("#", 8, "C"), ("Item Code", 30, "L"), ("Item", 90, "L"), ("Unit", 20, "C"), ("Qty", 34, "R")], "rows": rows},
              {"type": "qr", "data": gp.number, "lines": ["Security: scan this code in Y ERP (Store Hub > Scan) to check the pass "
                                                          "is genuine and still open, and that the material on the vehicle is what it lists.", gp.number]},
              {"type": "signatures", "boxes": [("Authorised by (Storekeeper)", gp.authorised_by_name or ""), ("Security (gate)", ""), ("Received by", "")]}]
    if gp.returnable:
        blocks.insert(3, {"type": "text", "text": "This material is to be returned to the store by the date above. Its return is recorded against the issue; an item not returned is charged or written off.", "style": "small"})
    company = letterhead(db, client)
    return {"title": "Gate Pass %s" % gp.number, "author": company["name"], "watermark": {"CANCELLED": "CANCELLED", "CLOSED": "MATERIAL RETURNED"}.get(gp.status, ""), "blocks": blocks,
            "footer": "%s  |  %s  |  Printed %s" % (gp.number, company["name"], datetime.now().strftime("%d/%m/%Y %H:%M"))}


FORMS = {"issue": ("Material Issue Note", issue_form), "returns": ("Material Return Note", return_form), "indent": ("Material Indent", indent_form), "gate-pass": ("Gate Pass", gate_form)}



def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}]. build(db, client, doc) -> the description form_pdf.build_form_pdf draws."""
    return [{"code": code, "title": title, "build": build} for code, (title, build) in FORMS.items()]
