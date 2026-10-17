"""Store module - printed control forms: the transfer (challan) note, the stock-count sheet and the wastage / scrap voucher, in the ruled,
boxed form the trade signs (app/documents/form_pdf.py draws them). Owned by P4.

The count sheet is blank where the counter writes: it never prints the system quantity, so a printed sheet can be used for a blind count."""
from datetime import datetime

from app import models
from app.documents import form_pdf
from app.documents.letterhead import letterhead
from app.models.store_core import DBStore
from app.services import store_control as svc

WATERMARK = {"DRAFT": "DRAFT - NOT POSTED", "SUBMITTED": "NOT YET APPROVED", "APPROVED": "NOT YET POSTED", "CANCELLED": "CANCELLED"}


def _n(x):
    return form_pdf.qty_text(x)


def _money(x):
    return form_pdf.plain_number(x, 2)


def _items(db, lines):
    return {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}


def _finish(db, client, doc, title, blocks, signs, watermark=None):
    blocks.append({"type": "signatures", "boxes": signs})
    company = letterhead(db, client)
    return {"title": "%s %s" % (title, doc.number), "author": company["name"], "watermark": WATERMARK.get(doc.status, "") if watermark is None else watermark, "blocks": blocks,
            "footer": "%s  |  %s  |  Printed %s" % (doc.number, company["name"], datetime.now().strftime("%d/%m/%Y %H:%M"))}


def transfer_form(db, client, doc):
    lines = svc.transfer_lines(db, doc)
    items = _items(db, lines)
    src, dst = db.get(DBStore, doc.store_id), db.get(DBStore, doc.to_store_id)
    dispatched = bool(doc.receipt_status)
    rows, total = [], 0
    for i, l in enumerate(lines, 1):
        it = items.get(l.item_id)
        total += float(l.value or 0)
        row = [str(i), it.item_code if it else "", it.item_name if it else "", svc.base_uom_of(db, it) if it else "", _n(l.qty)]
        if dispatched:
            row += [_money(l.rate), _money(l.value)]
        rows.append(row)
    cols = [("#", 7, "C"), ("Item Code", 28, "L"), ("Item", 60, "L"), ("Unit", 14, "C"), ("Qty", 22, "R")]
    if dispatched:
        cols += [("Rate", 24, "R"), ("Value", 27, "R")]
    else:
        cols[2] = ("Item", 90, "L")
        cols[4] = ("Qty", 43, "R")
    blocks = [{"type": "header", "company": letterhead(db, client), "title": "STOCK TRANSFER NOTE",
               "facts": [("No", doc.number), ("Date", form_pdf.date_text(doc.transfer_date)), ("From", "%s - %s" % (src.code, src.name)), ("To", "%s - %s" % (dst.code, dst.name))]},
              {"type": "pairs", "cols": 2, "rows": [("Vehicle", doc.vehicle_no or "-"), ("Between projects", "Yes" if doc.inter_project else "No"),
                                                    ("Receipt", {"IN_TRANSIT": "In transit", "RECEIVED": "Received %s" % (form_pdf.date_text(doc.received_at) if doc.received_at else "")}.get(doc.receipt_status, "Not yet dispatched")),
                                                    ("Remarks", doc.remarks or "-")]},
              {"type": "table", "columns": cols, "rows": rows, "totals": [("VALUE", _money(total), True)] if dispatched else []}]
    return _finish(db, client, doc, "Stock Transfer", blocks, [("Sent by (Storekeeper)", ""), ("Approved by", ""), ("Driver", ""), ("Received by", "")])


def count_form(db, client, doc):
    lines = svc.count_lines(db, doc)
    items = _items(db, lines)
    store = db.get(DBStore, doc.store_id)
    rows = [[str(i), items[l.item_id].item_code, items[l.item_id].item_name, svc.base_uom_of(db, items[l.item_id]), "", "", ""] for i, l in enumerate(sorted(lines, key=lambda x: items[x.item_id].item_name), 1)]
    blocks = [{"type": "header", "company": letterhead(db, client), "title": "STOCK COUNT SHEET",
               "facts": [("No", doc.number), ("Date", form_pdf.date_text(doc.count_date)), ("Store", "%s - %s" % (store.code, store.name)), ("Type", doc.count_type.title())]},
              {"type": "pairs", "cols": 2, "rows": [("Started by", doc.started_by_name or "-"), ("Remarks", doc.remarks or "-")]},
              {"type": "table", "columns": [("#", 7, "C"), ("Item Code", 28, "L"), ("Item", 62, "L"), ("Unit", 14, "C"), ("Counted", 24, "R"), ("Recount", 21, "R"), ("Remarks", 26, "L")], "rows": rows}]
    return _finish(db, client, doc, "Stock Count", blocks, [("Counted by", ""), ("Checked by", ""), ("Approved by", "")])


def scrap_form(db, client, doc):
    lines = svc.scrap_lines(db, doc)
    items = _items(db, lines)
    store = db.get(DBStore, doc.store_id)
    job = db.get(models.DBJob, doc.project_id) if doc.project_id else None
    rows, total = [], 0
    for i, l in enumerate(lines, 1):
        total += float(l.realised_value or 0)
        rows.append([str(i), items[l.item_id].item_code, items[l.item_id].item_name, svc.base_uom_of(db, items[l.item_id]), _n(l.qty), l.disposal.title(), l.reason or "", _money(l.realised_value)])
    blocks = [{"type": "header", "company": letterhead(db, client), "title": "WASTAGE / SCRAP VOUCHER",
               "facts": [("No", doc.number), ("Date", form_pdf.date_text(doc.scrap_date)), ("Store", "%s - %s" % (store.code, store.name))]},
              {"type": "pairs", "cols": 2, "rows": [("Project", ("%s - %s" % (job.number, job.name)) if job else "-"), ("Buyer", doc.buyer or "-"), ("Gate pass / voucher", doc.reference or "-"), ("Remarks", doc.remarks or "-")]},
              {"type": "table", "columns": [("#", 7, "C"), ("Item Code", 24, "L"), ("Item", 40, "L"), ("Unit", 11, "C"), ("Qty", 16, "R"), ("Disposal", 17, "C"), ("Reason", 41, "L"), ("Realised", 26, "R")],
               "rows": rows, "totals": [("TOTAL REALISED", _money(total), True)]}]
    return _finish(db, client, doc, "Wastage / Scrap", blocks, [("Prepared by (Storekeeper)", ""), ("Approved by", ""), ("Received by (buyer)", "")])


FORMS = {"transfer": ("Stock Transfer Note", transfer_form), "count": ("Stock Count Sheet", count_form), "scrap": ("Wastage / Scrap Voucher", scrap_form)}


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}]. build(db, client, doc) -> the description form_pdf.build_form_pdf draws."""
    return [{"code": code, "title": title, "build": build} for code, (title, build) in FORMS.items()]
