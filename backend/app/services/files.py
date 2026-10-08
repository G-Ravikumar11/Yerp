"""The rules and workings behind the files endpoints."""
import csv
import io
from datetime import datetime

from fastapi import HTTPException

from app import models

from app.constants.common import IMPORT_SHEETS
from app.core.dates import financial_year_label
from app.core.sheets import (
    BOM_HEADER_ALIASES,
    HEADER_ALIASES,
    WO_HEADER_ALIASES,
    cell_text,
    is_hint_row,
    looks_like_xlsx,
    mapping_report,
    match_headers,
    open_workbook,
    pick_sheet,
)


# What a sheet looks like it is, so the file can say so itself rather than
# the person having to know before they upload.
SHEET_KINDS = [
    ("items", "Item master", lambda h: match_headers(h, HEADER_ALIASES)[0]),
    ("work_order", "Work order", lambda h: match_headers(h, WO_HEADER_ALIASES)[0]),
    ("bom", "Budget / BOM", lambda h: match_headers(h, BOM_HEADER_ALIASES)[0]),
]


def guess_sheet_kind(header):
    """Which importer this sheet's headings look like they belong to.

    Scored by how many columns each vocabulary recognises, because a sheet
    that is nobody's format matches nothing and should say so plainly rather
    than being pushed at whichever importer was tried first.
    """
    best, scores = None, {}
    for key, label, match in SHEET_KINDS:
        fields = set(match(header).values())
        # A code column is what makes a sheet importable at all; without one
        # the rest is a coincidence of common words like "Quantity".
        anchor = {"items": "item_code", "work_order": "fg_code", "bom": "rm_code"}[key]
        scores[key] = len(fields) if anchor in fields else 0
        if scores[key] and (best is None or scores[key] > scores[best[0]]):
            best = (key, label)
    return {"kind": best[0] if best else "", "label": best[1] if best else "",
            "scores": scores}


def find_header_row(rows, limit: int = 15):
    """Which row is the headings, when it is not the first one.

    A sheet off a real desk opens with a title, a company name, a project and
    a blank line before it gets to naming its columns. Taking row one on faith
    reads "SCHEDULE" as the entire header and everything under it as data.

    A row scores for being recognised by one of our vocabularies, and failing
    that for simply being the widest thing near the top - a heading row names
    every column, where a title fills one cell and a total fills two.
    """
    best_index, best_score = 0, -1
    for index, row in enumerate(rows[:limit]):
        filled = [c for c in row if str(c or "").strip()]
        if len(filled) < 2:
            continue
        known = max(len(set(match_headers(row, aliases)[0].values()))
                    for aliases in (HEADER_ALIASES, WO_HEADER_ALIASES, BOM_HEADER_ALIASES))
        # Recognised columns count for far more than width, so a genuine
        # header beats a long row of dates sitting above it.
        score = known * 10 + len(filled)
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def sheet_overview(raw: bytes, sheet: str = "", preview_rows: int = 25):
    """Every tab in the workbook, and a look at one of them."""
    if not looks_like_xlsx(raw):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        table = list(csv.reader(io.StringIO(text, newline="")))
        sheets = [{"name": "(the file)", "rows": len(table),
                   "columns": max([len(r) for r in table] or [0])}]
        chosen, grid = "(the file)", table
    else:
        book = open_workbook(raw)
        try:
            sheets = [{"name": n, "rows": book[n].max_row or 0,
                       "columns": book[n].max_column or 0} for n in book.sheetnames]
            worksheet, chosen = pick_sheet(book, sheet)
            grid = [[cell_text(c) for c in row]
                    for row in worksheet.iter_rows(values_only=True)]
        finally:
            book.close()

    filled = [r for r in grid if any((c or "").strip() for c in r)]
    header_at = find_header_row(filled) if filled else 0
    header = filled[header_at] if filled else []
    body = filled[header_at + 1:]
    if body and is_hint_row(body[0]):
        body = body[1:]

    # Wide sheets are usually wide for a reason that is not data - a Gantt
    # chart carries a column per day - so the preview is capped rather than
    # sending two hundred columns of dates to a browser.
    width = min(max([len(r) for r in filled] or [0]), 40)

    def row_out(values):
        return [(values[i] if i < len(values) else "") for i in range(width)]

    guess = guess_sheet_kind(header) if header else {"kind": "", "label": "", "scores": {}}
    columns = match_headers(header, {
        "items": HEADER_ALIASES, "work_order": WO_HEADER_ALIASES,
        "bom": BOM_HEADER_ALIASES}[guess["kind"]])[0] if guess["kind"] else {}
    return {
        "sheets": sheets,
        "sheet": chosen,
        "header_row": header_at + 1,
        "header": row_out(header),
        # By position, not by heading text. A budget sheet heads two different
        # columns "Product Code", and a lookup by what the heading says would
        # label both of them whatever the first one turned out to be.
        "fields": [columns.get(i, "") for i in range(width)],
        "rows": [row_out(r) for r in body[:preview_rows]],
        "total_rows": len(body),
        "columns": width,
        "truncated_columns": max([len(r) for r in filled] or [0]) > width,
        "guess": guess,
        "mapping": mapping_report(header, match_headers(
            header, {"items": HEADER_ALIASES, "work_order": WO_HEADER_ALIASES,
                     "bom": BOM_HEADER_ALIASES}.get(guess["kind"], HEADER_ALIASES))[0])
        if guess["kind"] else {},
    }


# THE REGISTERS THE ACCOUNTANT KEPT BY HAND
#
# Three sheets every contractor's office maintains beside whatever system it
# has: the TDS deducted this quarter (for the 26Q), the bank guarantees and
# when each one lapses, and the advances given out and how much has come
# back. Every figure on them is already in the app; the sheets existed
# because nothing here laid the figures out the way the return, the bank
# and the site accountant want them.
def fy_quarter(on_date):
    """The Indian financial quarter a date falls in: 2026-27 Q1 is Apr-Jun."""
    try:
        d = datetime.strptime(str(on_date or "")[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return "", ""
    q = ((d.month - 4) % 12) // 3 + 1
    return financial_year_label(on_date), "Q%d" % q


def _sheet_kind(kind):
    spec = IMPORT_SHEETS.get(kind)
    if not spec:
        raise HTTPException(404, "Unknown kind of sheet")
    return spec


def _check_sheet_rows(db, client_id, kind, rows):
    """{row index: [problems]} - what the grid shows beside each row."""
    problems = {}
    master = {}
    if kind == "po_lines":
        master = {i.item_code.upper(): i for i in db.query(models.DBItem).filter(
            models.DBItem.client_id == client_id, models.DBItem.kind == "RM").all()}
    seen = set()
    for i, r in enumerate(rows):
        p = []
        if kind == "po_lines":
            code = (r.get("item_code") or "").upper()
            if code and code not in master:
                p.append("%s is not in the item master - it will go on as a line without a code" % code)
            if not (r.get("description") or code):
                p.append("what is being bought?")
            if (r.get("qty") or 0) <= 0:
                p.append("quantity must be more than nought")
            if (r.get("price") or 0) < 0:
                p.append("rate cannot be negative")
        if kind == "bills":
            if not (r.get("vendor_name") or "").strip():
                p.append("who is this owed to?")
            if (r.get("amount") or 0) <= 0:
                p.append("amount must be more than nought")
        if kind == "subcontract_orders":
            if not (r.get("subject") or "").strip():
                p.append("what is the work?")
            if not (r.get("contractor") or "").strip():
                p.append("which contractor is this for?")
        if p:
            problems[i] = p
    return problems
