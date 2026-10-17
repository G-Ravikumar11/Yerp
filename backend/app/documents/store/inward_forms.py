"""Store module - printed inward forms: the goods received note and the purchase return (debit-note advice). Owned by P2.

Each builder returns a description for app.documents.form_pdf.build_form_pdf, the same ruled-box layout the work order
and purchase order use. `list_forms()` names them so a screen can offer them.
"""
from app.documents.letterhead import letterhead
from app.services import store_inward as svc


def _dmy(iso):
    return ".".join(reversed(iso.split("-"))) if iso else ""


def _status_mark(status):
    return "" if status == "POSTED" else "DRAFT" if status in ("DRAFT", "SUBMITTED", "APPROVED") else "CANCELLED"


def grn_form_spec(db, client, grn):
    d = svc.grn_dict(db, grn)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["uom"], l["entered_qty"], l["received_qty"], l["accepted_qty"],
             l["rejected_qty"], l["rate"], "%s" % (l["batch_no"] or "")] for i, l in enumerate(d["lines"], 1)]
    return {
        "title": "Goods Received Note %s" % d["number"], "author": d["created_by"], "watermark": _status_mark(d["status"]),
        "footer": "%s · %s" % (d["number"], d["status"]),
        "blocks": [
            {"type": "header", "company": letterhead(db, client), "title": "GOODS RECEIVED NOTE",
             "facts": [("GRN No.", d["number"]), ("Date", _dmy(d["grn_date"])), ("Store", d["store_code"]), ("Status", d["status"])]},
            {"type": "pairs", "cols": 2, "rows": [("Supplier", d["supplier_name"]), ("Purchase order", d["po_number"]),
                                                   ("Challan no.", d["challan_no"]), ("Challan date", _dmy(d["challan_date"])),
                                                   ("Vehicle no.", d["vehicle_no"]), ("Store", "%s - %s" % (d["store_code"], d["store_name"]))]},
            {"type": "table", "columns": [("#", 8, "C"), ("Item", 56, "L"), ("Unit", 14, "C"), ("Received (unit)", 20, "R"), ("Received (base)", 20, "R"),
                                          ("Accepted", 18, "R"), ("Rejected", 18, "R"), ("Rate/base", 18, "R"), ("Batch", 18, "L")], "rows": rows,
             "totals": [("Value accepted", d["total_value"], True)]},
            {"type": "text", "text": "Remarks: %s" % (d["remarks"] or "-"), "style": "small"},
            {"type": "signatures", "boxes": [("Received by", d["created_by"]), ("Quality check", ""), ("Store in-charge", ""), ("Approved by", "")]},
        ],
    }


def prn_form_spec(db, client, prn):
    d = svc.return_dict(db, prn)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["base_uom"], l["qty"], l["value"], l["remarks"]] for i, l in enumerate(d["lines"], 1)]
    return {
        "title": "Purchase Return %s" % d["number"], "author": d["created_by"], "watermark": _status_mark(d["status"]),
        "footer": "%s · %s" % (d["number"], d["status"]),
        "blocks": [
            {"type": "header", "company": letterhead(db, client), "title": "PURCHASE RETURN",
             "facts": [("Return No.", d["number"]), ("Date", _dmy(d["return_date"])), ("Store", d["store_code"]), ("Status", d["status"])]},
            {"type": "pairs", "cols": 2, "rows": [("Supplier", d["supplier_name"]), ("Against GRN", d["grn_number"]), ("Reason", d["reason"]),
                                                   ("Store", "%s - %s" % (d["store_code"], d["store_name"]))]},
            {"type": "table", "columns": [("#", 8, "C"), ("Item", 70, "L"), ("Unit", 16, "C"), ("Quantity", 22, "R"), ("Value", 24, "R"), ("Remarks", 40, "L")],
             "rows": rows, "totals": [("Total value", d["total_value"], True)]},
            {"type": "text", "text": "Remarks: %s" % (d["remarks"] or "-"), "style": "small"},
            {"type": "signatures", "boxes": [("Prepared by", d["created_by"]), ("Store in-charge", ""), ("Approved by", ""), ("Received by supplier", "")]},
        ],
    }


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}]."""
    return [{"code": "GRN", "title": "Goods Received Note", "build": grn_form_spec},
            {"code": "PRN", "title": "Purchase Return", "build": prn_form_spec}]
