"""Store module - printed report forms (PDF twins of the Excel exports). Owned by P5.

Every report the reports slice builds is a table ({columns, rows, totals}), so one builder prints them all, landscape,
under the company's heading, with the filters it was run with.
"""


def _width(col):
    return {"L": 34, "C": 18, "R": 22}.get(col["align"], 24)


def report_spec(db, client, rep):
    """A report dictionary (services/store_reports.report) -> a form_pdf spec."""
    from app.documents.forms import _field_doc
    f = rep.get("filters") or {}
    facts = [(k.replace("_", " ").capitalize(), str(v)) for k, v in f.items() if v]
    cols = rep["columns"]
    rows = [[str(r.get(c["key"], "") if r.get(c["key"]) is not None else "") for c in cols] for r in rep["rows"]]
    blocks = [{"type": "table", "columns": [(c["label"], _width(c), c["align"]) for c in cols], "rows": rows}]
    if rep.get("totals"):
        blocks.append({"type": "pairs", "rows": [(k.replace("_", " ").capitalize(), v) for k, v in rep["totals"].items()], "label_width": 40})
    for note in rep.get("notes") or []:
        blocks.append({"type": "pairs", "rows": [("Note", note)], "label_width": 16})
    spec = _field_doc(db, client, rep["title"].upper(), facts or [("Filters", "none")], blocks, [], rep["code"])
    spec["landscape"] = True
    return spec


def list_forms() -> list:
    """The forms this slice can print: [{code, title, build}] - every report, through the one builder."""
    from app.services.store_reports import REPORTS
    return [{"code": code, "title": title, "build": report_spec} for code, (title, _fn) in REPORTS.items()]
