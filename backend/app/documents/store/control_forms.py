"""Store module - printed control forms: transfer note, count sheet, adjustment voucher, scrap note. Owned by P4.

Each builder returns a description for app.documents.form_pdf.build_form_pdf (the repo's ruled-box layout). The count sheet
prints the books only for a count that has been approved - a counter's sheet stays blind.
"""
from app.documents.letterhead import letterhead
from app.services import store_control as svc


def _dmy(iso):
    return ".".join(reversed(iso.split("-"))) if iso else ""


def _mark(status):
    return "" if status == "POSTED" else "CANCELLED" if status == "CANCELLED" else "DRAFT"


def _spec(db, client, d, title, facts, blocks):
    return {"title": "%s %s" % (title.title(), d["number"]), "author": d["created_by"], "watermark": _mark(d["status"]), "footer": "%s · %s" % (d["number"], d["status"]),
            "blocks": [{"type": "header", "company": letterhead(db, client), "title": title, "facts": facts}] + blocks}


def transfer_form_spec(db, client, t):
    d = svc.transfer_dict(db, t)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["qty"], l["rate"], l["value"], l["received_qty"] if l["received_qty"] is not None else ""] for i, l in enumerate(d["lines"], 1)]
    return _spec(db, client, d, "STORE TRANSFER NOTE", [("TRF No.", d["number"]), ("Date", _dmy(d["trf_date"])), ("From", d["store_code"]), ("To", d["to_store_code"])], [
        {"type": "pairs", "cols": 2, "rows": [("From store", "%s - %s" % (d["store_code"], d["store_name"])), ("To store", "%s - %s" % (d["to_store_code"], d["to_store_name"])),
                                               ("Vehicle", d["vehicle_no"]), ("Inter-project", "Yes" if d["inter_project"] else "No"), ("Status", d["transit"] or d["status"])]},
        {"type": "table", "columns": [("#", 8, "C"), ("Item", 72, "L"), ("Qty sent", 22, "R"), ("Rate", 20, "R"), ("Value", 24, "R"), ("Qty received", 24, "R")], "rows": rows,
         "totals": [("Value dispatched", d["total_value"], True)]},
        {"type": "signatures", "boxes": [("Dispatched by", d["created_by"]), ("Driver", ""), ("Received by", d["received_by"]), ("Approved by", "")]}])


def count_form_spec(db, client, c):
    d = svc.count_dict(db, c, reveal=False)
    cols = [("#", 8, "C"), ("Item", 80, "L"), ("Counted", 30, "R")] + ([("Books", 26, "R"), ("Difference", 26, "R"), ("Value", 24, "R")] if d["revealed"] else [("Remarks", 40, "L")])
    rows = []
    for i, l in enumerate(d["lines"], 1):
        row = [str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["counted_qty"] if l["counted_qty"] is not None else ""]
        rows.append(row + ([l["system_qty"], l["variance_qty"], l["variance_value"]] if d["revealed"] else [l["remarks"]]))
    return _spec(db, client, d, "STOCK COUNT SHEET", [("Count No.", d["number"]), ("Date", _dmy(d["count_date"])), ("Store", d["store_code"]), ("Status", d["status"])], [
        {"type": "pairs", "cols": 2, "rows": [("Store", "%s - %s" % (d["store_code"], d["store_name"])), ("Remarks", d["remarks"])]},
        {"type": "table", "columns": cols, "rows": rows},
        {"type": "signatures", "boxes": [("Counted by", d["created_by"]), ("Checked by", ""), ("Store in-charge", ""), ("Approved by", "")]}])


def adjustment_form_spec(db, client, a):
    d = svc.adjustment_dict(db, a)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["direction"], l["qty"], l["rate"], l["value"], l["remarks"]] for i, l in enumerate(d["lines"], 1)]
    return _spec(db, client, d, "STOCK ADJUSTMENT VOUCHER", [("ADJ No.", d["number"]), ("Date", _dmy(d["adj_date"])), ("Store", d["store_code"]), ("Status", d["status"])], [
        {"type": "pairs", "cols": 2, "rows": [("Kind", d["kind"]), ("Reason", d["reason"]), ("Charged to", d["project_name"]), ("Cost head", d["cost_head"] or "")]},
        {"type": "table", "columns": [("#", 8, "C"), ("Item", 60, "L"), ("In/Out", 14, "C"), ("Qty", 20, "R"), ("Rate", 18, "R"), ("Value", 22, "R"), ("Remarks", 40, "L")], "rows": rows,
         "totals": [("Total value", d["total_value"], True)]},
        {"type": "signatures", "boxes": [("Prepared by", d["created_by"]), ("Store in-charge", ""), ("Approved by", ""), ("Accounts", "")]}])


def scrap_form_spec(db, client, s):
    d = svc.scrap_dict(db, s)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["qty"], l["book_value"], l["realised_value"], l["remarks"]] for i, l in enumerate(d["lines"], 1)]
    return _spec(db, client, d, "SCRAP NOTE", [("Scrap No.", d["number"]), ("Date", _dmy(d["scrap_date"])), ("Store", d["store_code"]), ("Status", d["status"])], [
        {"type": "pairs", "cols": 2, "rows": [("Project", d["project_name"]), ("Buyer", d["buyer"]), ("Reason", d["reason"])]},
        {"type": "table", "columns": [("#", 8, "C"), ("Item", 70, "L"), ("Qty", 20, "R"), ("Book value", 24, "R"), ("Realised", 24, "R"), ("Remarks", 36, "L")], "rows": rows,
         "totals": [("Book value", d["book_value"], False), ("Realised", d["realised_value"], True)]},
        {"type": "signatures", "boxes": [("Prepared by", d["created_by"]), ("Store in-charge", ""), ("Approved by", ""), ("Buyer", d["buyer"])]}])


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}]."""
    return [{"code": "TRF", "title": "Store Transfer Note", "build": transfer_form_spec}, {"code": "CNT", "title": "Stock Count Sheet", "build": count_form_spec},
            {"code": "ADJ", "title": "Stock Adjustment Voucher", "build": adjustment_form_spec}, {"code": "SCR", "title": "Scrap Note", "build": scrap_form_spec}]
