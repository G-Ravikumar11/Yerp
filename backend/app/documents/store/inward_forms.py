"""Store module - printed inward forms. Owned by P2.

Each form is built from the dictionaries the inward routes already send (grn_dict / return_dict), so the paper and the
screen never disagree: GRN, QC report, rejection memo, and purchase return with its debit note.
"""
from app.documents import form_pdf


def _qty(v, uom=""):
    return ("%s %s" % (form_pdf.qty_text(float(v)), uom)).strip() if v not in (None, "") else ""


def _money(v):
    return form_pdf.plain_number(float(v or 0), 2)


def _date(v):
    return form_pdf.date_text(v) if v else "-"


def _head(d):
    rows = [("Store", "%s - %s" % (d["store_code"], d["store_name"]))]
    if d.get("po_number"):
        rows.append(("Purchase order", d["po_number"]))
    if d.get("work_order"):
        rows.append(("Client work order", d["work_order"]))
    rows += [("Supplier", d["vendor_name"] or "-"), ("Challan", "%s %s" % (d["challan_no"] or "-", _date(d["challan_date"]) if d["challan_date"] else "")),
             ("Invoice", "%s %s" % (d["invoice_no"] or "-", _date(d["invoice_date"]) if d["invoice_date"] else ""))]
    if d.get("gate"):
        g = d["gate"]
        rows.append(("Gate entry", "%s, vehicle %s, weighbridge %s: net %s kg" % (g["number"], g["vehicle_no"] or "-",
                                                                                  g["weighbridge_slip_no"] or "-", g["net_weight"] or "-")))
    if d.get("reason"):
        rows.append(("Reason (no PO)", d["reason"]))
    return {"type": "pairs", "rows": rows, "label_width": 36}


def grn_spec(db, client, d):
    from app.documents.forms import _field_doc
    rows = []
    for l in d["lines"]:
        steel = l.get("steel")
        note = []
        if l["batch_no"]:
            note.append("Batch/heat %s, MTC %s" % (l["batch_no"], l["mtc_ref"] or "-"))
        if steel:
            note.append("%s nos x %s mm: %s kg theoretical, %s kg weighed" % (l["nos"], l["dia_mm"], steel["theoretical_kg"], steel["actual_kg"] or "-"))
        if l["qc_status"] == "QC_PENDING":
            note.append("QC pending")
        rows.append([str(l["line_no"]), "%s %s%s" % (l["item_code"], l["item_name"], ("\n" + "; ".join(note)) if note else ""),
                     _qty(l["received_qty"], l["uom"]), _qty(l["accepted_qty"], l["uom"]), _qty(l["rejected_qty"], l["uom"]),
                     _qty(l["shortage_qty"], l["uom"]), _money(l["landed_rate"]), _money(l["stock_value"])])
    charges = "Freight %s, loading %s, other %s; GST %s" % (_money(d["freight"]), _money(d["loading"]), _money(d["other_charges"]),
                                                           "recoverable (not in stock value)" if d["gst_recoverable"] else "not recoverable (in stock value)")
    blocks = [_head(d), {"type": "table", "columns": [("#", 8, "C"), ("Item", 70, "L"), ("Received", 22, "R"), ("Accepted", 22, "R"),
                                                     ("Rejected", 22, "R"), ("Short", 18, "R"), ("Landed rate", 22, "R"), ("Value", 26, "R")],
                                       "rows": rows, "totals": [("Stock value", _money(d["stock_value"]), True)]},
              {"type": "pairs", "rows": [("Charges", charges), ("Remarks", d["remarks"] or "-")], "label_width": 30}]
    by = {t["to"]: t["by"] for t in d["trail"]}
    sig = [("Received by", d["created_by"]), ("Approved by", by.get("APPROVED", "")), ("Posted by", by.get("POSTED", ""))]
    title = "CLIENT SUPPLY RECEIPT" if d["kind"] == "CLIENT_SUPPLY" else "GOODS RECEIVED NOTE"
    return _field_doc(db, client, title, [("No.", d["number"]), ("Date", _date(d["grn_date"])), ("Status", d["status"])], blocks, sig,
                      d["number"], "CANCELLED" if d["status"] == "CANCELLED" else ("DRAFT - NOT POSTED" if d["status"] != "POSTED" else ""))


def qc_spec(db, client, d):
    from app.documents.forms import _field_doc
    rows = [[str(l["line_no"]), "%s %s" % (l["item_code"], l["item_name"]), _qty(l["received_qty"], l["uom"]),
             _qty(l["qc"]["accepted_qty"], l["uom"]) if l["qc"] else "", _qty(l["qc"]["rejected_qty"], l["uom"]) if l["qc"] else "",
             ("%s %s" % (l["qc"]["test_type"], l["qc"]["test_ref"])).strip() if l["qc"] else "Pending",
             l["qc"]["remarks"] if l["qc"] else "", l["qc"]["inspector"] if l["qc"] else ""]
            for l in d["lines"] if l["qc_status"] != "NOT_REQUIRED"]
    blocks = [_head(d), {"type": "table", "columns": [("#", 8, "C"), ("Item", 56, "L"), ("Received", 22, "R"), ("Accepted", 22, "R"),
                                                     ("Rejected", 22, "R"), ("Test", 34, "L"), ("Remarks", 34, "L"), ("Inspector", 26, "L")],
                                       "rows": rows}]
    return _field_doc(db, client, "QUALITY INSPECTION REPORT", [("GRN", d["number"]), ("Date", _date(d["grn_date"]))], blocks,
                      [("Inspected by", ""), ("Store in-charge", "")], "QC-" + d["number"])


def rejection_spec(db, client, d):
    from app.documents.forms import _field_doc
    rows = [[str(l["line_no"]), "%s %s" % (l["item_code"], l["item_name"]), _qty(l["received_qty"], l["uom"]),
             _qty(l["rejected_qty"], l["uom"]), (l["qc"]["remarks"] if l["qc"] else l["remarks"]) or "-"]
            for l in d["lines"] if float(l["rejected_qty"] or 0) > 0]
    blocks = [_head(d), {"type": "table", "columns": [("#", 8, "C"), ("Item", 70, "L"), ("Received", 24, "R"), ("Rejected", 24, "R"),
                                                     ("Reason", 60, "L")], "rows": rows},
              {"type": "pairs", "rows": [("Note", "The material above does not meet the order and is held for you to collect, or "
                                                  "is being returned. Please send replacement or a credit note.")], "label_width": 20}]
    return _field_doc(db, client, "REJECTION MEMO", [("No.", d["rejection_memo"]), ("GRN", d["number"]), ("Date", _date(d["grn_date"]))],
                      blocks, [("Store in-charge", ""), ("Supplier's acknowledgement", "")], d["rejection_memo"])


def return_spec(db, client, d):
    from app.documents.forms import _field_doc
    n = d["debit_note"]
    rows = [[str(i), "%s %s" % (l["item_code"], l["item_name"]), "Rejected" if l["source"] == "REJECTED" else "From stock",
             _qty(l["qty"], l["uom"]), _money(l["rate"]), _money(l["taxable_value"]), "%s%%" % l["gst_pct"], _money(l["gst"]),
             _money(l["total"])] for i, l in enumerate(n["lines"], 1)]
    blocks = [{"type": "pairs", "rows": [("Supplier", "%s %s" % (n["vendor"], ("GSTIN " + n["vendor_gstin"]) if n["vendor_gstin"] else "")),
                                         ("Against", "GRN %s%s%s" % (n["grn_number"], (", PO " + n["po_number"]) if n["po_number"] else "",
                                                                     (", invoice " + n["invoice_no"]) if n["invoice_no"] else "")),
                                         ("Reason", d["reason"] or "-"), ("Vehicle", d["vehicle_no"] or "-")], "label_width": 30},
              {"type": "table", "columns": [("#", 8, "C"), ("Item", 56, "L"), ("What", 20, "L"), ("Qty", 22, "R"), ("Rate", 20, "R"),
                                            ("Taxable", 24, "R"), ("GST", 12, "R"), ("GST amt", 20, "R"), ("Total", 24, "R")],
               "rows": rows, "totals": [("Taxable value", _money(n["taxable_value"]), False), ("GST", _money(n["gst"]), False),
                                        ("Debit note total", _money(n["total"]), True)]}]
    return _field_doc(db, client, "PURCHASE RETURN / DEBIT NOTE", [("No.", d["number"]), ("Date", _date(d["return_date"])),
                                                                    ("Status", d["status"])], blocks,
                      [("Prepared by", d["created_by"]), ("Authorised by", ""), ("Received by supplier", "")], d["number"],
                      "CANCELLED" if d["status"] == "CANCELLED" else "")


FORMS = {"GRN": ("Goods received note", grn_spec), "QC": ("Quality inspection report", qc_spec),
         "REJECTION": ("Rejection memo", rejection_spec), "RETURN": ("Purchase return / debit note", return_spec)}


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}]."""
    return [{"code": code, "title": title, "build": build} for code, (title, build) in FORMS.items()]


def build(code, db, client, data):
    """(spec, file name) for form `code` from its route's dictionary."""
    _title, fn = FORMS[code]
    spec = fn(db, client, data)
    name = {"GRN": data.get("number"), "QC": "QC-%s" % data.get("number"), "REJECTION": data.get("rejection_memo"),
            "RETURN": data.get("number")}[code] or code
    return spec, name.replace("/", "-")
