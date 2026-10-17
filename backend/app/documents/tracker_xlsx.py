"""The invoice tracker as a workbook people can print and send.

One sheet each for the summary, the supplier invoices, every trade's received materials, the ready-mix register and the
physical stock. The tables start on row 1 so the figures are the first thing seen; who issued it, for which project and
at what GST and markup follows the data at the end of each sheet. The company logo sits faded across the data like a
watermark, so it is on the page without competing with the figures.
"""
import io
import re
from datetime import datetime

from app.core import identity as ident
from app.services.invoice_tracker import is_rmc_name

INK = "1F2937"
HEAD = "3730A3"            # the indigo the app uses for table headings
BAND = "EEF2FF"
LINE = "D1D5DB"
BAD = "FEE2E2"
GOOD = "DCFCE7"
WARN = "FEF3C7"
MONEY = '#,##0.00;[Red]-#,##0.00;"-"'
QTY = '#,##0.##;[Red]-#,##0.##;"-"'
WATERMARK_OPACITY = 0.10
WATERMARK_WIDTH = 460          # pixels, before Excel scales it to the zoom


def faded_logo(raw, opacity=WATERMARK_OPACITY, width=WATERMARK_WIDTH):
    """The logo as PNG bytes with its colour drawn back to `opacity`, so it reads as a watermark. None if it will not load."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        if img.width < 1 or img.height < 1:
            return None
        scale = width / float(img.width)
        img = img.resize((width, max(1, int(img.height * scale))), Image.LANCZOS)
        alpha = img.getchannel("A").point(lambda a: int(a * opacity))
        img.putalpha(alpha)
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()
    except Exception:
        return None


def _sheet_name(raw, taken):
    base = re.sub(r"[\[\]\*\?/\\:]", " ", str(raw or "Sheet")).strip()[:28] or "Sheet"
    name, n = base, 2
    while name.lower() in taken:
        name = "%s %d" % (base[:26], n)
        n += 1
    taken.add(name.lower())
    return name


def build_workbook(t, company, job_label, gst, markup, who=""):
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter as col
    from openpyxl.utils.units import pixels_to_EMU

    thin = Side(style="thin", color=LINE)
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    top_rule = Border(left=thin, right=thin, top=Side(style="medium", color=INK), bottom=thin)
    head_fill = PatternFill("solid", fgColor=HEAD)
    band_fill = PatternFill("solid", fgColor=BAND)
    base = Font(name="Calibri", size=10, color=INK)
    bold = Font(name="Calibri", size=10, color=INK, bold=True)
    white = Font(name="Calibri", size=10, color="FFFFFF", bold=True)
    muted = Font(name="Calibri", size=9, color="6B7280")
    logo = faded_logo(ident.logo_bytes(company)) if company else None
    stamp = datetime.now().strftime("%d-%m-%Y %H:%M")

    book = openpyxl.Workbook()
    book.remove(book.active)
    taken = set()

    def new_sheet(title, widths, landscape=True, paper=9):
        ws = book.create_sheet(_sheet_name(title, taken))
        ws.sheet_view.showGridLines = False
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[col(i)].width = w
        ws.page_setup.orientation = "landscape" if landscape else "portrait"
        ws.page_setup.paperSize = paper                 # 8 = A3, 9 = A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_options.horizontalCentered = True
        ws.page_margins.left = ws.page_margins.right = 0.4
        ws.oddFooter.center.text = "Page &P of &N"
        ws.oddFooter.right.text = "Generated " + stamp
        return ws

    def put(ws, r, c, value, font=base, fmt=None, fill=None, align="left", border=box, wrap=False):
        cell = ws.cell(row=r, column=c, value=value)
        cell.font, cell.border = font, border
        if fmt:
            cell.number_format = fmt
        if fill:
            cell.fill = fill
        cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
        return cell

    def heading(ws, r, labels, aligns=None):
        for i, label in enumerate(labels, start=1):
            put(ws, r, i, label, white, fill=head_fill, align=(aligns or {}).get(i, "center"), wrap=True)
        ws.row_dimensions[r].height = 30

    def details(ws, r, report):
        """Who issued the sheet, for what and when - after the data, not before it."""
        r += 2
        ws.cell(row=r, column=1, value="REPORT DETAILS").font = bold
        lines = [("Company", (company or {}).get("name") or ""), ("Address", ident.address_line(company)),
                 ("Tax numbers", ident.tax_line(company)), ("Report", report), ("Project", job_label),
                 ("GST", "%g%%" % gst), ("Markup on basic rate", "%g%%" % markup), ("Generated", stamp)]
        if who:
            lines.append(("Generated by", who))
        for label, value in lines:
            if not value:
                continue
            r += 1
            ws.cell(row=r, column=1, value=label).font = muted
            ws.cell(row=r, column=2, value=value).font = base
        return r

    def watermark(ws, last_row, last_col, first_data_row=2):
        """The faded logo across the middle of the data. Image bytes are shared by every sheet."""
        if not logo:
            return
        try:
            img = XLImage(io.BytesIO(logo))
            w, h = img.width, img.height
            # Centre it on the data block: the nearer of the block's middle and a sensible place for a short table.
            mid_col = max(0, min(last_col // 2 - 1, 6))
            mid_row = max(first_data_row, min(first_data_row + (last_row - first_data_row) // 2 - 4, 40))
            img.anchor = OneCellAnchor(_from=AnchorMarker(col=mid_col, row=mid_row),
                                       ext=XDRPositiveSize2D(pixels_to_EMU(w), pixels_to_EMU(h)))
            ws.add_image(img)
        except Exception:
            pass

    # ---- Summary -------------------------------------------------------------------------------------------------
    ws = new_sheet("Summary", [6, 34, 20, 20, 20, 44], paper=9)
    heading(ws, 1, ["S.no", "Description", "Purchase amount", "WO amount", "Difference", "Remarks"])
    r = 1
    for n, row in enumerate(t["summary"]["rows"], start=1):
        r += 1
        fill = band_fill if n % 2 == 0 else None
        put(ws, r, 1, n, fill=fill, align="center")
        put(ws, r, 2, row["category"], bold, fill=fill)
        put(ws, r, 3, row["purchase_amount"], fmt=MONEY, fill=fill, align="right")
        put(ws, r, 4, row["wo_amount"], fmt=MONEY, fill=fill, align="right")
        put(ws, r, 5, row["difference"], fmt=MONEY, fill=PatternFill("solid", fgColor=WARN) if row["difference"] < 0 else fill, align="right")
        note = row["remarks"] or ("From work orders" if row.get("wo_source") == "work orders" else "")
        put(ws, r, 6, note, fill=fill, wrap=True)
    r += 1
    put(ws, r, 1, "", border=top_rule)
    put(ws, r, 2, "Total amount", bold, border=top_rule)
    for c, key in ((3, "purchase_amount"), (4, "wo_amount"), (5, "difference")):
        put(ws, r, c, t["summary"][key], bold, fmt=MONEY, align="right", border=top_rule)
    put(ws, r, 6, "", border=top_rule)
    ws.freeze_panes = "A2"
    ws.print_title_rows = "1:1"
    watermark(ws, r, 6)
    details(ws, r, "Invoice Tracker - Summary")

    # ---- Invoices ------------------------------------------------------------------------------------------------
    heads = ["S.no", "Supplier", "Invoice no", "Invoice date", "GRN", "PO number", "Vehicle", "Amount",
             "GST %g%%" % gst, "Freight", "Insurance", "Hamali", "Total", "Invoice amount", "Difference", "Status", "Remarks"]
    ws = new_sheet("Invoices", [6, 30, 18, 13, 12, 18, 15, 15, 14, 12, 12, 12, 16, 16, 14, 14, 36], paper=8)
    heading(ws, 1, heads)
    r = 1
    for n, i in enumerate(t["invoices"], start=1):
        r += 1
        diff = i["difference"]
        status, tint = (("Not checked", WARN) if diff is None else ("Matches", GOOD) if abs(diff) < 1 else ("Mismatch", BAD))
        fill = band_fill if n % 2 == 0 else None
        values = [n, i["supplier"], i["invoice_number"], i["invoice_date"] or i["received_on"], i["grn"], i["po_number"],
                  i["vehicle"], i["amount"], i["gst"], i["freight"], i["insurance"], i["hamali"], i["total"],
                  i["invoice_amount"], diff]
        for c, v in enumerate(values, start=1):
            money = c >= 8
            put(ws, r, c, "" if v is None else v, bold if c == 13 else base, fmt=MONEY if money else None,
                fill=(PatternFill("solid", fgColor=tint) if c == 15 and diff is not None and abs(diff) >= 1 else fill),
                align="right" if money else ("center" if c in (1, 4) else "left"))
        put(ws, r, 16, status, bold, fill=PatternFill("solid", fgColor=tint), align="center")
        put(ws, r, 17, i["remark"], fill=fill, wrap=True)
    r += 1
    tot = t["totals"]
    for c in range(1, 18):
        put(ws, r, c, "", bold, border=top_rule)
    put(ws, r, 2, "Total", bold, border=top_rule)
    for c, key in ((8, "amount"), (9, "gst"), (10, "freight"), (11, "insurance"), (12, "hamali"), (13, "total")):
        put(ws, r, c, tot[key], bold, fmt=MONEY, align="right", border=top_rule)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = "A1:Q%d" % max(2, r - 1)
    ws.print_title_rows = "1:1"
    watermark(ws, r, 17)
    details(ws, r, "Invoice Tracker - Supplier invoices")

    # ---- Received materials, one sheet per trade -----------------------------------------------------------------
    # The layout of the received-materials list people already keep: SL NO, material and UOM down the left; across the
    # top each supplier invoice (supplier, date, number, PO) over Qty | Rate | Amount; then the totals, the working rate
    # and the physical store stock. The totals and the bill's own check sit under each invoice.
    by_id = {i["grn_id"]: i for i in t["invoices"]}
    for cat in t["categories"]:
        if is_rmc_name(cat["name"]):
            continue                                 # ready-mix has its register, not a materials list
        invs = [by_id[g] for g in cat["invoice_ids"] if g in by_id]
        n_inv = len(invs)
        first_total = 4 + 3 * n_inv                   # Total qty | Total rate | Total amount | Working rate | Working amount | Physical
        last_col = first_total + 5
        ws = new_sheet(cat["name"], [6, 40, 8] + [11, 11, 15] * n_inv + [12, 13, 16, 13, 16, 17], paper=8)
        head_rows = 5
        for c, label in ((1, "SL NO"), (2, "MATERIAL DESCRIPTION"), (3, "UOM")):
            put(ws, 1, c, label, white, fill=head_fill, align="center", wrap=True)
            for rr in range(2, head_rows + 1):
                put(ws, rr, c, None, white, fill=head_fill)
            ws.merge_cells(start_row=1, start_column=c, end_row=head_rows, end_column=c)
        for k, inv in enumerate(invs):
            c0 = 4 + 3 * k
            top = (inv["supplier"], inv["invoice_date"] or inv["received_on"], inv["invoice_number"] or inv["grn"], inv["po_number"])
            for rr, text in enumerate(top, start=1):
                put(ws, rr, c0, text, white, fill=head_fill, align="center", wrap=True)
                for cc in (c0 + 1, c0 + 2):
                    put(ws, rr, cc, None, white, fill=head_fill)
                ws.merge_cells(start_row=rr, start_column=c0, end_row=rr, end_column=c0 + 2)
            for off, label in enumerate(("Qty", "Rate", "Amount")):
                put(ws, head_rows, c0 + off, label, white, fill=head_fill, align="center")
        for off, label in enumerate(("Total qty", "Total rate", "Total amount", "Working rate", "Working amount", "Physical store stock")):
            c = first_total + off
            put(ws, 1, c, label, white, fill=head_fill, align="center", wrap=True)
            for rr in range(2, head_rows + 1):
                put(ws, rr, c, None, white, fill=head_fill)
            ws.merge_cells(start_row=1, start_column=c, end_row=head_rows, end_column=c)
        ws.row_dimensions[1].height = 30
        ws.row_dimensions[2].height = ws.row_dimensions[3].height = ws.row_dimensions[4].height = 18
        r = head_rows
        for n, m in enumerate(cat["materials"], start=1):
            r += 1
            fill = band_fill if n % 2 == 0 else None
            put(ws, r, 1, m["sl"], fill=fill, align="center")
            put(ws, r, 2, m["description"] + ("  (%s)" % m["item_code"] if m["item_code"] else ""), fill=fill, wrap=True)
            put(ws, r, 3, m["uom"], fill=fill, align="center")
            cells = {c["grn_id"]: c for c in m["cells"]}
            for k, inv in enumerate(invs):
                c0, cell = 4 + 3 * k, cells.get(inv["grn_id"])
                put(ws, r, c0, cell["qty"] if cell else None, fmt=QTY, fill=fill, align="right")
                put(ws, r, c0 + 1, cell["rate"] if cell else None, fmt=MONEY, fill=fill, align="right")
                put(ws, r, c0 + 2, cell["amount"] if cell else None, fmt=MONEY, fill=fill, align="right")
            got = bool(m["cells"])
            for off, (v, f) in enumerate(((m["total_qty"] if got else None, QTY), (m["total_rate"] if got else None, MONEY),
                                          (m["total_amount"] if got else None, MONEY), (m["working_rate"], MONEY),
                                          (m["working_amount"], MONEY), (m["on_hand"] if m["counted"] else None, QTY))):
                put(ws, r, first_total + off, v, bold if off in (0, 2) else base, fmt=f, fill=fill, align="right")
        foot = {f["grn_id"]: f for f in cat["footer"]}
        rows = (("AMOUNT", "amount", True), ("GST %g%%" % gst, "gst", False), ("FREIGHT CHARGES", "freight", False),
                ("INSURANCE", "insurance", False), ("HAMALI", "hamali", False), ("TOTAL AMOUNT", "total", True),
                ("INVOICE AMOUNT", "invoice_amount", False), ("DIFFERENT AMOUNT", "difference", False))
        for label, key, strong in rows:
            r += 1
            font = bold if strong else base
            edge = top_rule if label == "AMOUNT" else box
            put(ws, r, 1, None, border=edge)
            put(ws, r, 2, label, font, align="right", border=edge)
            put(ws, r, 3, None, border=edge)
            total = 0.0
            for k, inv in enumerate(invs):
                c0 = 4 + 3 * k
                v = (foot.get(inv["grn_id"]) or {}).get(key)
                for cc in (c0 + 1, c0 + 2):
                    put(ws, r, cc, None, border=edge)
                put(ws, r, c0, "" if v is None else v, font, fmt=MONEY, align="right", border=edge,
                    fill=PatternFill("solid", fgColor=BAD) if key == "difference" and v is not None and abs(v) >= 1 else None)
                ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=c0 + 2)
                total += v or 0
            for off in range(6):
                put(ws, r, first_total + off, None, border=edge)
            put(ws, r, first_total + 2, round(total, 2), font, fmt=MONEY, align="right", border=edge)
            if key == "amount":
                put(ws, r, first_total + 4, cat["working_total"] or None, bold, fmt=MONEY, align="right", border=edge)
        r += 1
        put(ws, r, 1, None)
        put(ws, r, 2, "REMARKS", bold, align="right")
        put(ws, r, 3, None)
        for k, inv in enumerate(invs):
            c0 = 4 + 3 * k
            for cc in (c0 + 1, c0 + 2):
                put(ws, r, cc, None)
            put(ws, r, c0, inv["remark"], base, wrap=True)
            ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=c0 + 2)
        if any(i["remark"] for i in invs):
            ws.row_dimensions[r].height = 42
        r += 1
        put(ws, r, 1, "Installation + Consumables + Wastage + Over Head & Profits on Basic rate @ %g%%" % markup, base, align="right")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=first_total + 1)
        put(ws, r, first_total + 2, cat["markup"], base, fmt=MONEY, align="right")
        r += 1
        put(ws, r, 1, "%s total with markup (before GST)" % cat["name"], bold, align="right")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=first_total + 1)
        put(ws, r, first_total + 2, cat["with_markup"], bold, fmt=MONEY, align="right")
        if cat["note"]:
            r += 1
            put(ws, r, 1, "Note: " + cat["note"], bold, align="left", border=Border())
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=first_total + 2)
        ws.freeze_panes = "D%d" % (head_rows + 1)
        ws.print_title_rows = "1:%d" % head_rows
        watermark(ws, r, last_col, first_data_row=head_rows)
        details(ws, r, "Invoice Tracker - Received materials: " + cat["name"])

    # ---- Ready-mix register --------------------------------------------------------------------------------------
    rmc = t["rmc"]
    ws = new_sheet("Ready-mix", [6, 13, 28, 18, 15, 17, 8, 11, 13, 16, 16], paper=9)
    heading(ws, 1, ["S.no", "Date", "Supplier", "PO number", "Vehicle", "Invoice no", "Grade", "Qty (cum)",
                    "Unit price", "Amount", "Block"])
    r = 1
    for n, row in enumerate(rmc["rows"], start=1):
        r += 1
        fill = band_fill if n % 2 == 0 else None
        for c, (v, f, a) in enumerate(((n, None, "center"), (row["invoice_date"], None, "center"), (row["supplier"], None, "left"),
                                       (row["po_number"], None, "left"), (row["vehicle"], None, "left"),
                                       (row["invoice_number"], None, "left"), (row["grade"], None, "center"),
                                       (row["qty"], QTY, "right"), (row["rate"], MONEY, "right"),
                                       (row["amount"], MONEY, "right"), (row["block"], None, "left")), start=1):
            put(ws, r, c, v, fmt=f, fill=fill, align=a)
    r += 1
    for c in range(1, 12):
        put(ws, r, c, "", bold, border=top_rule)
    put(ws, r, 3, "Total", bold, border=top_rule)
    put(ws, r, 8, rmc["qty"], bold, fmt=QTY, align="right", border=top_rule)
    put(ws, r, 10, rmc["amount"], bold, fmt=MONEY, align="right", border=top_rule)
    for label, value in (("GST %g%%" % gst, rmc["gst"]), ("Grand total", rmc["total"])):
        r += 1
        put(ws, r, 3, label, bold if label == "Grand total" else base, align="right")
        put(ws, r, 10, value, bold if label == "Grand total" else base, fmt=MONEY, align="right")
    ws.freeze_panes = "A2"
    ws.print_title_rows = "1:1"
    r += 2
    heading(ws, r, ["", "Block", "", "Loads", "Qty (cum)", "Amount"])
    for b in rmc["blocks"]:
        r += 1
        put(ws, r, 2, b["block"], bold)
        put(ws, r, 3, None)
        put(ws, r, 4, b["loads"], align="center")
        put(ws, r, 5, b["qty"], fmt=QTY, align="right")
        put(ws, r, 6, b["amount"], fmt=MONEY, align="right")
    watermark(ws, r, 11)
    details(ws, r, "Invoice Tracker - Ready-mix register")

    book.properties.title = "Invoice Tracker"
    book.properties.creator = (company or {}).get("name") or "Y ERP"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
