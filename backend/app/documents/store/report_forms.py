"""Store module - printed report forms (PDF twins of the Excel exports). Owned by P5.

One builder serves every report: the table the report service returns becomes a ruled-box page in the repo's form layout,
landscape when there are many columns.
"""
from app.documents.letterhead import letterhead
from app.services.store_reports import REPORTS


def report_form_spec(db, client, rep: dict) -> dict:
    cols = rep["columns"]
    weight = {"text": 3, "qty": 2, "money": 2.4}
    widths = [max(10, weight.get(c["kind"], 2) * (9 if c["key"] in ("item", "supplier", "holder", "boq") else 6)) for c in cols]
    rows = [[str(r.get(c["key"], "")) for c in cols] for r in rep["rows"]]
    if rep["totals"]:
        rows.append([str(rep["totals"].get(c["key"], "")) for c in cols])
    params = "  ".join("%s: %s" % (k, v) for k, v in rep["params"].items()) or "All records"
    return {"title": rep["title"], "author": "", "landscape": len(cols) > 6, "footer": "%s · %s" % (rep["title"], rep["generated_at"]),
            "blocks": [{"type": "header", "company": letterhead(db, client), "title": "STORE REPORT", "facts": [("Report", rep["title"][:30]), ("Run", rep["generated_at"].replace("T", " "))]},
                       {"type": "band", "text": rep["title"]},
                       {"type": "text", "text": params, "style": "small"},
                       {"type": "table", "columns": [(c["label"], w, c["align"]) for c, w in zip(cols, widths)], "rows": rows}]}


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}] - one per report, built from the table the report returns."""
    return [{"code": code, "title": title, "build": report_form_spec} for code, (_fn, title, _p) in REPORTS.items()]
