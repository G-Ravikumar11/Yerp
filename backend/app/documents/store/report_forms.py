"""Store module - printed reports (PDF twins of the Excel exports). Owned by P5.

Every report is flattened to the same shape - a title, the filters it ran with, column headings, rows of text and a totals line - and that one
shape is drawn as a PDF (here, through app/documents/form_pdf.py) or written to Excel (in the router), so the two always say the same thing.
"""
from datetime import datetime
from decimal import Decimal

from app.documents import form_pdf
from app.documents.letterhead import letterhead

PAGE_WIDTH_MM = 269.0            # A4 landscape less the 14 mm margins


def _n(x, places=3):
    d = Decimal(str(x))
    return form_pdf.plain_number(d, 2) if places == 2 else form_pdf.qty_text(d)


def _col(title, align="L", weight=1.0, fmt=None):
    return {"title": title, "align": align, "weight": weight, "fmt": fmt}


def _qty(title, weight=1.0):
    return _col(title, "R", weight, _n)


def _money(title, weight=1.0):
    return _col(title, "R", weight, lambda x: _n(x, 2))


def flatten(report, data):
    """(title, subtitle, columns, rows, totals) for a report's result. Rows hold raw values; columns say how to show each."""
    if report == "valuation":
        cols = [_col("Store", "L", .7), _col("Item code", "L", 1.2), _col("Item", "L", 2.4), _col("Category", "L", 1), _col("Unit", "C", .6), _qty("Quantity"), _money("Avg rate"), _money("Value")]
        rows = [[r["store_code"], r["item_code"], r["item_name"], r["category"], r["base_uom"], r["qty"], r["avg_rate"], r["value"]] for r in data["rows"]]
        return "Stock valuation", "As on %s" % form_pdf.date_text(data["as_on"]), cols, rows, [("TOTAL VALUE", _n(data["total_value"], 2))]
    if report == "movement":
        cols = [_col("Store", "L", .6), _col("Item", "L", 2.2), _qty("Opening qty", .9), _money("Opening value", 1)]
        for b in data["buckets"]:
            cols.append(_money(b["label"], 1))
        cols += [_qty("Closing qty", .9), _money("Closing value", 1)]
        rows = []
        for r in data["rows"]:
            rows.append([r["store_code"], "%s  %s" % (r["item_code"], r["item_name"]), r["opening_qty"], r["opening_value"], *[r[b["key"] + "_value"] for b in data["buckets"]], r["closing_qty"], r["closing_value"]])
        t = data["totals"]
        return "Stock movement", "%s to %s (values: opening, net movement in each group, closing)" % (form_pdf.date_text(data["from"]), form_pdf.date_text(data["to"])), cols, rows, [("OPENING", _n(t.get("opening_value", 0), 2)), ("CLOSING", _n(t.get("closing_value", 0), 2))]
    if report == "consumption":
        names = {"project": "Project", "cost_head": "Cost head", "work_order": "Work order", "boq_item": "BOQ item", "item": "Item"}
        cols = [_col(names[data["group_by"]], "L", 2.5), _col("Item", "L", 2.5), _qty("Quantity"), _money("Value")]
        rows = []
        for g in data["groups"]:
            rows.append([g["name"], "All items", "", g["value"]])
            for i in g["items"]:
                rows.append(["", "%s  %s" % (i["item_code"], i["item_name"]), i["qty"], i["value"]])
        return "Material consumption", "Grouped by %s" % names[data["group_by"]].lower(), cols, rows, [("TOTAL CONSUMED", _n(data["total_value"], 2))]
    if report == "norm-variance":
        cols = [_col("BOQ item", "L", 2.2), _col("Item", "L", 2), _qty("BOQ qty", .8), _qty("Should use", 1), _qty("Used", 1), _qty("Difference", 1), _col("%", "R", .6, lambda x: "-" if x is None else "%s%%" % x), _col("", "C", .8)]
        rows = [[r["boq_item"], "%s  %s" % (r["item_code"], r["item_name"]), r["boq_qty"], r["theoretical_qty"], r["actual_qty"], r["variance_qty"], r["variance_pct"], r["status"]] for r in data["rows"]]
        return "Norms against actual use", "%d item%s over the norm" % (data["over"], "" if data["over"] == 1 else "s"), cols, rows, []
    if report == "slow-moving":
        cols = [_col("Store", "L", .7), _col("Item code", "L", 1.2), _col("Item", "L", 2.6), _qty("Quantity"), _money("Value"), _col("Last moved", "L", 1), _col("Days idle", "R", .8, lambda x: "never" if x is None else str(x))]
        rows = [[r["store_code"], r["item_code"], r["item_name"], r["qty"], r["value"], form_pdf.date_text(r["last_moved"]) if r["last_moved"] else "-", r["days_idle"]] for r in data["rows"]]
        return "Slow-moving stock", "Not moved for %d days or more" % data["days"], cols, rows, [("TIED UP", _n(data["total_value"], 2))]
    cols = [_col("Store", "L", .7), _col("Item code", "L", 1.2), _col("Item", "L", 2.6), _col("Unit", "C", .6), _qty("On hand"), _qty("Reorder level"), _qty("Minimum"), _qty("Order about")]
    rows = [[r["store_code"], r["item_code"], r["item_name"], r["base_uom"], r["qty"], r["reorder_level"], r["min_qty"], r["suggested_qty"]] for r in data["rows"]]
    return "Reorder", "Items at or below their reorder level", cols, rows, []


def shown(columns, rows):
    """Rows as the text a person reads."""
    return [[(c["fmt"](v) if c["fmt"] and v not in (None, "") else ("" if v is None else str(v))) for c, v in zip(columns, row)] for row in rows]


def report_pdf_spec(db, client, report, data, filters=""):
    title, subtitle, columns, rows, totals = flatten(report, data)
    total_weight = sum(c["weight"] for c in columns)
    table_cols = [(c["title"], round(PAGE_WIDTH_MM * c["weight"] / total_weight, 1), c["align"]) for c in columns]
    company = letterhead(db, client)
    blocks = [{"type": "header", "company": company, "title": title.upper(), "facts": [("Printed", datetime.now().strftime("%d/%m/%Y %H:%M"))]},
              {"type": "pairs", "cols": 1, "rows": [("Report", subtitle), *([("Filters", filters)] if filters else [])]},
              {"type": "table", "columns": table_cols, "rows": shown(columns, rows), "totals": [(label, value, True) for label, value in totals]}]
    return {"title": title, "author": company["name"], "landscape": True, "blocks": blocks, "footer": "%s  |  %s" % (title, company["name"])}


def list_forms() -> list:
    """The reports this slice can print: [{code, title, build}]. build(db, client, data, filters) -> the description form_pdf.build_form_pdf draws."""
    names = {"valuation": "Stock valuation", "movement": "Stock movement", "consumption": "Material consumption", "norm-variance": "Norms against actual use", "slow-moving": "Slow-moving stock", "reorder": "Reorder"}
    return [{"code": code, "title": title, "build": (lambda db, client, data, filters="", _c=code: report_pdf_spec(db, client, _c, data, filters))} for code, title in names.items()]
