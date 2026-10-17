"""Store module - printed outward forms: material requisition, issue slip and issue return note. Owned by P3.

Each builder returns a description for app.documents.form_pdf.build_form_pdf (the repo's ruled-box layout).
"""
from app.documents.letterhead import letterhead
from app.services import store_outward as svc


def _dmy(iso):
    return ".".join(reversed(iso.split("-"))) if iso else ""


def _mark(status, final=("POSTED",)):
    return "" if status in final else "CANCELLED" if status == "CANCELLED" else "DRAFT"


def _where_rows(d):
    return [("Project", d.get("project_name", "")), ("Work order", d.get("work_order_number", "")), ("Cost head", d.get("cost_head") or "")]


def requisition_form_spec(db, client, req):
    d = svc.requisition_dict(db, req)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["uom"], l["entered_qty"], l["qty"], l["issued_qty"], l["remarks"]] for i, l in enumerate(d["lines"], 1)]
    return {"title": "Material Requisition %s" % d["number"], "author": d["created_by"], "watermark": _mark(d["status"], ("APPROVED",)),
            "footer": "%s · %s" % (d["number"], d["status"]),
            "blocks": [
                {"type": "header", "company": letterhead(db, client), "title": "MATERIAL REQUISITION",
                 "facts": [("MRQ No.", d["number"]), ("Date", _dmy(d["req_date"])), ("Required by", _dmy(d["required_by"])), ("Status", d["status"])]},
                {"type": "pairs", "cols": 2, "rows": [("Store", "%s - %s" % (d["store_code"], d["store_name"])), ("Purpose", d["purpose"])] + _where_rows(d)},
                {"type": "table", "columns": [("#", 8, "C"), ("Item", 70, "L"), ("Unit", 14, "C"), ("Asked (unit)", 20, "R"), ("Asked (base)", 20, "R"), ("Issued", 18, "R"), ("Remarks", 32, "L")], "rows": rows},
                {"type": "signatures", "boxes": [("Requested by", d["created_by"]), ("Site engineer", ""), ("Store in-charge", ""), ("Approved by", "")]}]}


def issue_form_spec(db, client, issue):
    d = svc.issue_dict(db, issue)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["uom"], l["entered_qty"], l["qty"], l["rate"], l["value"], "Yes" if l["returnable"] else ""]
            for i, l in enumerate(d["lines"], 1)]
    to = d["subcontractor_name"] if d["issue_type"] == "SUBCONTRACTOR" else "Site use"
    return {"title": "Material Issue %s" % d["number"], "author": d["created_by"], "watermark": _mark(d["status"]), "footer": "%s · %s" % (d["number"], d["status"]),
            "blocks": [
                {"type": "header", "company": letterhead(db, client), "title": "MATERIAL ISSUE SLIP",
                 "facts": [("Issue No.", d["number"]), ("Date", _dmy(d["issue_date"])), ("Store", d["store_code"]), ("Status", d["status"])]},
                {"type": "pairs", "cols": 2, "rows": [("Issued to", to), ("Requisition", d["requisition_number"] or "Direct issue"), ("Held by", d["holder_name"]),
                                                       ("Expected back", _dmy(d["expected_return_date"])), ("Purpose", d["purpose"])] + _where_rows(d)},
                {"type": "table", "columns": [("#", 8, "C"), ("Item", 64, "L"), ("Unit", 14, "C"), ("Qty (unit)", 18, "R"), ("Qty (base)", 18, "R"), ("Rate", 16, "R"), ("Value", 20, "R"), ("Returnable", 16, "C")],
                 "rows": rows, "totals": [("Total value", d["total_value"], True)]},
                {"type": "signatures", "boxes": [("Issued by", d["created_by"]), ("Received by", d["holder_name"]), ("Store in-charge", ""), ("Approved by", "")]}]}


def return_form_spec(db, client, rtn):
    d = svc.return_dict(db, rtn)
    rows = [[str(i), "%s\n%s" % (l["item_code"], l["item_name"]), l["base_uom"], l["qty"], l["lost_qty"], l["rate"], l["value"], l["remarks"]] for i, l in enumerate(d["lines"], 1)]
    return {"title": "Issue Return %s" % d["number"], "author": d["created_by"], "watermark": _mark(d["status"]), "footer": "%s · %s" % (d["number"], d["status"]),
            "blocks": [
                {"type": "header", "company": letterhead(db, client), "title": "MATERIAL RETURN NOTE",
                 "facts": [("Return No.", d["number"]), ("Date", _dmy(d["return_date"])), ("Store", d["store_code"]), ("Status", d["status"])]},
                {"type": "pairs", "cols": 2, "rows": [("Against issue", d["issue_number"]), ("Returned by", d["holder_name"])]},
                {"type": "table", "columns": [("#", 8, "C"), ("Item", 62, "L"), ("Unit", 14, "C"), ("Returned", 20, "R"), ("Lost", 18, "R"), ("Rate", 16, "R"), ("Value", 20, "R"), ("Remarks", 30, "L")],
                 "rows": rows, "totals": [("Value returned", d["total_value"], True)]},
                {"type": "signatures", "boxes": [("Returned by", d["holder_name"]), ("Received by", d["created_by"]), ("Store in-charge", ""), ("Approved by", "")]}]}


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}]."""
    return [{"code": "MRQ", "title": "Material Requisition", "build": requisition_form_spec},
            {"code": "ISSUE", "title": "Material Issue Slip", "build": issue_form_spec},
            {"code": "RTN", "title": "Material Return Note", "build": return_form_spec}]
