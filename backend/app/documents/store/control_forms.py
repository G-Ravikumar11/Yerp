"""Store module - printed control forms. Owned by P4.

  Transfer note / delivery challan (TRF), count sheet (CNT, blind until approved), variance statement (VAR), adjustment voucher (ADJ),
  write-off note (WOF) and scrap sale note (SCR). Each builder returns a description for app.documents.form_pdf.build_form_pdf (the
  repo's ruled-box layout).
"""
from app.documents.letterhead import letterhead
from app.services import store_control as svc


def _dmy(iso):
    return ".".join(reversed(iso.split("-"))) if iso else ""


def _mark(status):
    return "" if status == "POSTED" else "CANCELLED" if status == "CANCELLED" else "DRAFT"


def _label(code):
    return (code or "").replace("_", " ").lower()


def _spec(db, client, d, title, facts, blocks, landscape=False):
    return {"title": "%s %s" % (title.title(), d["number"]), "author": d["created_by"], "watermark": _mark(d["status"]), "landscape": landscape,
            "footer": "%s · %s" % (d["number"], d["status"]), "blocks": [{"type": "header", "company": letterhead(db, client), "title": title, "facts": facts}] + blocks}


def transfer_form_spec(db, client, t):
    d = svc.transfer_dict(db, t)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["qty"], l["rate"], l["value"], l["received_qty"] if l["received_qty"] is not None else "",
             ("%s (%s)" % (l["loss_qty"], _label(l["loss_reason"]))) if float(l["loss_qty"]) else ""] for i, l in enumerate(d["lines"], 1)]
    return _spec(db, client, d, "TRANSFER NOTE / DELIVERY CHALLAN", [("TRF No.", d["number"]), ("Date", _dmy(d["trf_date"])), ("From", d["store_code"]), ("To", d["to_store_code"])], [
        {"type": "pairs", "cols": 2, "rows": [("From store", "%s - %s" % (d["store_code"], d["store_name"])), ("To store", "%s - %s" % (d["to_store_code"], d["to_store_name"])),
                                               ("Challan no.", d["challan_no"]), ("Challan date", _dmy(d["challan_date"])), ("Vehicle", d["vehicle_no"]), ("Driver", d["driver_name"]),
                                               ("Inter-project", "Yes" if d["inter_project"] else "No"), ("Status", d["transit"] or d["status"])]},
        {"type": "table", "columns": [("#", 8, "C"), ("Item", 62, "L"), ("Qty sent", 20, "R"), ("Rate", 18, "R"), ("Value", 22, "R"), ("Qty received", 22, "R"), ("Lost in transit", 28, "L")], "rows": rows,
         "totals": [("Value dispatched", d["total_value"], True)] + ([("Lost in transit", d["loss_value"], False)] if float(d["loss_value"]) else [])},
        {"type": "signatures", "boxes": [("Dispatched by", d["created_by"]), ("Driver", d["driver_name"]), ("Received by", d["received_by"]), ("Approved by", "")]}])


def count_form_spec(db, client, c):
    d = svc.count_dict(db, c, reveal=False)
    cols = [("#", 8, "C"), ("Item", 80, "L"), ("Counted", 28, "R"), ("Recount", 26, "R")] + ([("Books", 24, "R"), ("Difference", 24, "R"), ("Value", 22, "R")] if d["revealed"] else [("Remarks", 36, "L")])
    rows = []
    for i, l in enumerate(d["lines"], 1):
        row = [str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["counted_qty"] if l["counted_qty"] is not None else "", "recount" if l["recount"] else (l["first_count_qty"] or "")]
        rows.append(row + ([l["system_qty"], l["variance_qty"], l["variance_value"]] if d["revealed"] else [l["remarks"]]))
    scope = ", ".join(filter(None, [("categories: " + ", ".join(_label(x) for x in d["categories"])) if d["categories"] else "", ("bin " + d["bin_code"]) if d["bin_code"] else ""])) or "whole store"
    return _spec(db, client, d, "STOCK COUNT SHEET", [("Count No.", d["number"]), ("Date", _dmy(d["count_date"])), ("Store", d["store_code"]), ("Status", d["status"])], [
        {"type": "pairs", "cols": 2, "rows": [("Store", "%s - %s" % (d["store_code"], d["store_name"])), ("Scope", scope), ("Recount rounds", str(d["recount_rounds"])), ("Remarks", d["remarks"])]},
        {"type": "table", "columns": cols, "rows": rows},
        {"type": "signatures", "boxes": [("Counted by", d["created_by"]), ("Checked by", ""), ("Store in-charge", ""), ("Approved by", "")]}])


def variance_form_spec(db, client, c):
    """The variance statement: books, count, difference in quantity and value, only for lines that differ, with a net total."""
    d = svc.count_dict(db, c, reveal=True)
    diff = [l for l in d["lines"] if l["variance_qty"] not in (None, "0.000", "0")]
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["system_qty"], l["counted_qty"] or "", l["variance_qty"], l["variance_value"], l["first_count_qty"] or ""] for i, l in enumerate(diff, 1)]
    return _spec(db, client, d, "STOCK VARIANCE STATEMENT", [("Count No.", d["number"]), ("Date", _dmy(d["count_date"])), ("Store", d["store_code"]), ("Status", d["status"])], [
        {"type": "pairs", "cols": 2, "rows": [("Store", "%s - %s" % (d["store_code"], d["store_name"])), ("Lines counted", str(d["line_count"])), ("Lines with a difference", str(len(diff))),
                                               ("Recount rounds", str(d["recount_rounds"]))]},
        {"type": "table", "columns": [("#", 8, "C"), ("Item", 74, "L"), ("Books", 24, "R"), ("Counted", 24, "R"), ("Difference", 24, "R"), ("Value", 26, "R"), ("First count", 24, "R")], "rows": rows,
         "totals": [("Net difference in value", d["variance_value"] or "0.00", True)]},
        {"type": "signatures", "boxes": [("Counted by", d["created_by"]), ("Store in-charge", ""), ("Approved by", ""), ("Accounts", "")]}])


def adjustment_form_spec(db, client, a):
    d = svc.adjustment_dict(db, a)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["direction"], l["qty"], l["rate"], l["value"], l["remarks"]] for i, l in enumerate(d["lines"], 1)]
    return _spec(db, client, d, "STOCK ADJUSTMENT VOUCHER", [("ADJ No.", d["number"]), ("Date", _dmy(d["adj_date"])), ("Store", d["store_code"]), ("Status", d["status"])], [
        {"type": "pairs", "cols": 2, "rows": [("Kind", d["kind"].title()), ("Reason code", _label(d["reason_code"])), ("Remark", d["reason"]), ("Supporting paper", d["attachment_ref"]),
                                               ("Charged to", d["project_name"]), ("Cost head", _label(d["cost_head"]))]},
        {"type": "table", "columns": [("#", 8, "C"), ("Item", 60, "L"), ("In/Out", 14, "C"), ("Qty", 20, "R"), ("Rate", 18, "R"), ("Value", 22, "R"), ("Remarks", 40, "L")], "rows": rows,
         "totals": [("Total value", d["total_value"], True)]},
        {"type": "signatures", "boxes": [("Prepared by", d["created_by"]), ("Store in-charge", ""), ("Approved by", ""), ("Accounts", "")]}])


def writeoff_form_spec(db, client, a):
    """The write-off note for wastage, damage and lost returnables."""
    d = svc.adjustment_dict(db, a)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["qty"], l["rate"], l["value"], l["remarks"]] for i, l in enumerate(d["lines"], 1)]
    return _spec(db, client, d, "WRITE-OFF NOTE", [("Note No.", d["number"]), ("Date", _dmy(d["adj_date"])), ("Store", d["store_code"]), ("Status", d["status"])], [
        {"type": "pairs", "cols": 2, "rows": [("Reason", _label(d["reason_code"])), ("Remark", d["reason"]), ("Supporting paper", d["attachment_ref"]), ("Charged to", d["project_name"] or _label(d["cost_head"]))]},
        {"type": "table", "columns": [("#", 8, "C"), ("Item", 70, "L"), ("Qty written off", 24, "R"), ("Rate", 20, "R"), ("Value", 24, "R"), ("Remarks", 40, "L")], "rows": rows,
         "totals": [("Total written off", d["total_value"], True)]},
        {"type": "signatures", "boxes": [("Store in-charge", d["created_by"]), ("Site engineer", ""), ("Project manager", ""), ("Accounts", "")]}])


def scrap_form_spec(db, client, s):
    d = svc.scrap_dict(db, s)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), _label(l["scrap_class"]), l["qty"], l["book_value"], l["realised_value"], l["difference"]] for i, l in enumerate(d["lines"], 1)]
    return _spec(db, client, d, "SCRAP SALE NOTE", [("Scrap No.", d["number"]), ("Date", _dmy(d["scrap_date"])), ("Store", d["store_code"]), ("Status", d["status"])], [
        {"type": "pairs", "cols": 2, "rows": [("Sold / disposed to", d["buyer"]), ("Gate pass no.", d["gate_pass_no"]), ("Project", d["project_name"]), ("Reason", d["reason"])]},
        {"type": "table", "columns": [("#", 8, "C"), ("Item", 60, "L"), ("Class", 32, "L"), ("Qty", 18, "R"), ("Book value", 22, "R"), ("Realised", 22, "R"), ("Gain / (loss)", 22, "R")], "rows": rows,
         "totals": [("Book value", d["book_value"], False), ("Realised", d["realised_value"], False), ("Gain / (loss)", d["difference"], True)]},
        {"type": "signatures", "boxes": [("Prepared by", d["created_by"]), ("Store in-charge", ""), ("Approved by", ""), ("Buyer", d["buyer"])]}])


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}]."""
    return [{"code": "TRF", "title": "Transfer Note / Delivery Challan", "build": transfer_form_spec}, {"code": "CNT", "title": "Stock Count Sheet", "build": count_form_spec},
            {"code": "VAR", "title": "Stock Variance Statement", "build": variance_form_spec}, {"code": "ADJ", "title": "Stock Adjustment Voucher", "build": adjustment_form_spec},
            {"code": "WOF", "title": "Write-off Note", "build": writeoff_form_spec}, {"code": "SCR", "title": "Scrap Sale Note", "build": scrap_form_spec}]
