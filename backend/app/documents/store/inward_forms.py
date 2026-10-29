"""Store module - printed inward forms: the goods receipt note, the purchase return, the client-supply receipt and the opening
stock sheet, in the ruled, boxed form the trade signs (app/documents/form_pdf.py draws them). Owned by P2."""
from datetime import datetime

from app import models
from app.documents import form_pdf
from app.documents.letterhead import letterhead
from app.models.store_core import DBStore
from app.models.store_inward import DBStoreGrn
from app.services import store_inward as svc

SIGNATURES = [("Prepared by (Storekeeper)", ""), ("Checked by", ""), ("Approved by", ""), ("Received by", "")]
WATERMARK = {"DRAFT": "DRAFT - NOT POSTED", "SUBMITTED": "NOT YET APPROVED", "APPROVED": "NOT YET POSTED", "CANCELLED": "CANCELLED"}


def _n(x):
    return form_pdf.qty_text(x)


def _money(x):
    return form_pdf.plain_number(x, 2)


def _lookup(db, doc, lines):
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines] or [0])).all()}
    store = db.get(DBStore, doc.store_id)
    return items, store


def _head(db, client, doc, title, facts, store):
    return {"type": "header", "company": letterhead(db, client), "title": title,
            "facts": [("No", doc.number), *facts, ("Store", "%s - %s" % (store.code, store.name) if store else "")]}


def _finish(db, client, doc, title, blocks, extra_sign=None):
    blocks.append({"type": "signatures", "boxes": extra_sign or SIGNATURES})
    company = letterhead(db, client)
    return {"title": "%s %s" % (title, doc.number), "author": company["name"], "watermark": WATERMARK.get(doc.status, ""), "blocks": blocks,
            "footer": "%s  |  %s  |  Printed %s" % (doc.number, company["name"], datetime.now().strftime("%d/%m/%Y %H:%M"))}


def grn_form(db, client, grn):
    lines = svc.grn_lines(db, grn)
    items, store = _lookup(db, grn, lines)
    po = db.get(models.DBPurchaseOrder, grn.po_id) if grn.po_id else None
    job = db.get(models.DBJob, grn.project_id) if grn.project_id else None
    rows, total = [], 0
    for i, l in enumerate(lines, 1):
        it = items.get(l.item_id)
        amount = float(l.accepted_qty or 0) * float(l.rate or 0)
        total += amount
        rows.append([str(i), it.item_code if it else "", it.item_name if it else "", svc.base_uom_of(db, it) if it else "", _n(l.received_qty), _n(l.accepted_qty),
                     _n(l.rejected_qty), _money(l.rate), _money(amount), (l.qc_status or "").replace("_", " ").title() if l.qc_status != "NOT_REQUIRED" else "-"])
    blocks = [
        _head(db, client, grn, "GOODS RECEIPT NOTE", [("Date", form_pdf.date_text(grn.grn_date)), ("PO No", po.number if po else "-")], store),
        {"type": "pairs", "cols": 2, "rows": [("Supplier", grn.supplier_name or "-"), ("Challan / Invoice", grn.challan_no or "-"),
                                              ("Challan date", form_pdf.date_text(grn.challan_date) if grn.challan_date else "-"), ("Vehicle", grn.vehicle_no or "-"),
                                              ("Project", ("%s - %s" % (job.number, job.name)) if job else "-"), ("Remarks", grn.remarks or "-")]},
        {"type": "table", "columns": [("#", 7, "C"), ("Item Code", 22, "L"), ("Item", 44, "L"), ("Unit", 11, "C"), ("Received", 17, "R"), ("Accepted", 17, "R"),
                                      ("Rejected", 16, "R"), ("Rate", 17, "R"), ("Amount", 22, "R"), ("QC", 13, "C")],
         "rows": rows, "totals": [("VALUE OF ACCEPTED GOODS", _money(total), True)]},
    ]
    rejected = [l for l in lines if float(l.rejected_qty or 0) > 0]
    if rejected:
        blocks.append({"type": "band", "text": "Rejected goods"})
        blocks.append({"type": "terms", "rows": [(items[l.item_id].item_name if l.item_id in items else "", "%s - %s" % (_n(l.rejected_qty), l.reject_reason or "")) for l in rejected], "label_width": 60})
    return _finish(db, client, grn, "Goods Receipt Note", blocks)


def return_form(db, client, ret):
    lines = svc.return_lines(db, ret)
    items, store = _lookup(db, ret, lines)
    grn = db.get(DBStoreGrn, ret.grn_id)
    # The debit note: what the supplier owes back, at the rate on the receipt, with the order's GST.
    rows = [[str(i), items[l.item_id].item_name + ((" - " + l.reason) if l.reason else ""), svc.base_uom_of(db, items[l.item_id]), _n(l.qty), _money(l.rate or 0),
             _money(l.value or 0), "%s%%" % svc.s2(l.tax_pct or 0), _money(l.tax_value or 0)] for i, l in enumerate(lines, 1)]
    debit, tax = float(ret.debit_value or 0), float(ret.tax_value or 0)
    po = db.get(models.DBPurchaseOrder, grn.po_id) if grn is not None and grn.po_id else None
    blocks = [
        _head(db, client, ret, "DEBIT NOTE (PURCHASE RETURN)", [("Date", form_pdf.date_text(ret.return_date)), ("Against GRN", grn.number if grn else "")], store),
        {"type": "pairs", "cols": 2, "rows": [("Supplier", ret.supplier_name or "-"), ("Purchase order", po.number if po else "-"), ("Challan", (grn.challan_no if grn else "") or "-"),
                                              ("Reason", ret.reason or "-"), ("Remarks", ret.remarks or "-")]},
        {"type": "table", "columns": [("#", 7, "C"), ("Item", 60, "L"), ("Unit", 13, "C"), ("Qty", 20, "R"), ("Rate", 20, "R"), ("Value", 24, "R"), ("GST", 12, "R"), ("GST amt", 26, "R")],
         "rows": rows, "totals": [("VALUE", _money(debit), False), ("GST", _money(tax), False), ("DEBIT NOTE TOTAL", _money(debit + tax), True)]},
    ]
    return _finish(db, client, ret, "Purchase Return", blocks, [("Prepared by (Storekeeper)", ""), ("Approved by", ""), ("Supplier's receipt", "")])


def supply_form(db, client, doc):
    lines = svc.supply_lines(db, doc)
    items, store = _lookup(db, doc, lines)
    job = db.get(models.DBJob, doc.project_id)
    rows = [[str(i), items[l.item_id].item_code, items[l.item_id].item_name, svc.base_uom_of(db, items[l.item_id]), _n(l.qty), _money(l.rate), _money(float(l.qty) * float(l.rate))]
            for i, l in enumerate(lines, 1)]
    blocks = [
        _head(db, client, doc, "CLIENT SUPPLIED MATERIAL RECEIPT", [("Date", form_pdf.date_text(doc.supply_date)), ("Client ref", doc.client_ref or "-")], store),
        {"type": "pairs", "cols": 2, "rows": [("Project", ("%s - %s" % (job.number, job.name)) if job else "-"), ("Remarks", doc.remarks or "-")]},
        {"type": "table", "columns": [("#", 7, "C"), ("Item Code", 28, "L"), ("Item", 66, "L"), ("Unit", 14, "C"), ("Qty", 22, "R"), ("Rate", 22, "R"), ("Value", 23, "R")], "rows": rows},
    ]
    return _finish(db, client, doc, "Client Supply", blocks, [("Prepared by (Storekeeper)", ""), ("Approved by", ""), ("Client's representative", "")])


def opening_form(db, client, doc):
    lines = svc.opening_lines(db, doc)
    items, store = _lookup(db, doc, lines)
    rows, total = [], 0
    for i, l in enumerate(lines, 1):
        amount = float(l.qty) * float(l.rate)
        total += amount
        rows.append([str(i), items[l.item_id].item_code, items[l.item_id].item_name, svc.base_uom_of(db, items[l.item_id]), _n(l.qty), _money(l.rate), _money(amount)])
    blocks = [
        _head(db, client, doc, "OPENING STOCK", [("As on", form_pdf.date_text(doc.as_on_date))], store),
        {"type": "pairs", "cols": 1, "rows": [("Remarks", doc.remarks or "-")]},
        {"type": "table", "columns": [("#", 7, "C"), ("Item Code", 28, "L"), ("Item", 66, "L"), ("Unit", 14, "C"), ("Qty", 22, "R"), ("Rate", 22, "R"), ("Value", 23, "R")],
         "rows": rows, "totals": [("TOTAL VALUE", _money(total), True)]},
    ]
    return _finish(db, client, doc, "Opening Stock", blocks, [("Counted by", ""), ("Checked by", ""), ("Approved by", "")])


FORMS = {"grn": ("Goods Receipt Note", grn_form), "returns": ("Purchase Return", return_form), "client-supply": ("Client Supply Receipt", supply_form),
         "opening": ("Opening Stock", opening_form)}


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}]. build(db, client, doc) -> the description form_pdf.build_form_pdf draws."""
    return [{"code": code, "title": title, "build": build} for code, (title, build) in FORMS.items()]
