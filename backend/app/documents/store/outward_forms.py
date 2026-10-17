"""Store module - printed outward forms: the material issue slip (to site or to a subcontractor) and the return slip, in the ruled,
boxed form the trade signs (app/documents/form_pdf.py draws them). Owned by P3."""
from datetime import datetime

from app import models
from app.documents import form_pdf
from app.documents.letterhead import letterhead
from app.models.store_core import DBStore, DBStoreStockLedger
from app.models.store_outward import DBStoreIssue, ISSUE, SUBCONTRACTOR
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
    rows, total = [], 0
    for i, l in enumerate(lines, 1):
        it = items.get(l.item_id)
        rate, value = rates.get(l.id, (0, 0))
        total += value
        row = [str(i), it.item_code if it else "", it.item_name if it else "", svc.base_uom_of(db, it) if it else "", _n(l.qty), _boq_text(db, l.boq_item_id) or (l.cost_head or "").replace("_", " ").title() or "-"]
        if issue.status == "POSTED":
            row += [_money(rate), _money(value)]
        if sub:
            row.append(("Rs %s" % _money(l.recovery_rate)) if l.chargeable else "No")
        rows.append(row)
    columns = [("#", 7, "C"), ("Item Code", 24, "L"), ("Item", 46, "L"), ("Unit", 11, "C"), ("Qty", 17, "R"), ("Charged to", 36, "L")]
    if issue.status == "POSTED":
        columns += [("Rate", 15, "R"), ("Value", 18, "R")]
    if sub:
        columns.append(("Recover", 16, "R"))
    scale = 182.0 / sum(w for _t, w, _a in columns)
    columns = [(t, round(w * scale, 1), a) for t, w, a in columns]
    facts = [("Date", form_pdf.date_text(issue.issue_date)), ("Store", "%s - %s" % (store.code, store.name) if store else "")]
    pairs = [("Project", ("%s - %s" % (job.number, job.name)) if job else "-"), ("Work order", wo.number if wo else "-"),
             ("Issued to", issue.holder_name or "Site use"), ("Purpose", issue.purpose or "-"), ("Remarks", issue.remarks or "-")]
    blocks = [{"type": "header", "company": letterhead(db, client), "title": "MATERIAL ISSUE TO SUBCONTRACTOR" if sub else "MATERIAL ISSUE NOTE", "facts": [("No", issue.number), *facts]},
              {"type": "pairs", "cols": 2, "rows": pairs},
              {"type": "table", "columns": columns, "rows": rows, "totals": [("VALUE AT AVERAGE COST", _money(total), True)] if issue.status == "POSTED" else []}]
    return _finish(db, client, issue, "Material Issue", blocks, [("Issued by (Storekeeper)", ""), ("Approved by", ""), ("Received by", issue.holder_name or "")])


def return_form(db, client, ret):
    lines = svc.return_lines(db, ret)
    issue = db.get(DBStoreIssue, ret.issue_id)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}
    store = db.get(DBStore, ret.store_id)
    rows = [[str(i), items[l.item_id].item_code, items[l.item_id].item_name, svc.base_uom_of(db, items[l.item_id]), _n(l.qty_returned), _n(l.qty_lost), l.reason or ""]
            for i, l in enumerate(lines, 1)]
    blocks = [{"type": "header", "company": letterhead(db, client), "title": "MATERIAL RETURN NOTE",
               "facts": [("No", ret.number), ("Date", form_pdf.date_text(ret.return_date)), ("Against", issue.number if issue else ""), ("Store", "%s - %s" % (store.code, store.name) if store else "")]},
              {"type": "pairs", "cols": 2, "rows": [("Returned by", issue.holder_name if issue and issue.holder_name else "Site"), ("Remarks", ret.remarks or "-")]},
              {"type": "table", "columns": [("#", 7, "C"), ("Item Code", 26, "L"), ("Item", 56, "L"), ("Unit", 12, "C"), ("Returned", 20, "R"), ("Lost / damaged", 24, "R"), ("Remarks", 37, "L")], "rows": rows}]
    return _finish(db, client, ret, "Material Return", blocks, [("Returned by", ""), ("Received by (Storekeeper)", ""), ("Approved by", "")])


FORMS = {"issue": ("Material Issue Note", issue_form), "returns": ("Material Return Note", return_form)}


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}]. build(db, client, doc) -> the description form_pdf.build_form_pdf draws."""
    return [{"code": code, "title": title, "build": build} for code, (title, build) in FORMS.items()]
