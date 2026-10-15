"""The programme printed on A3 landscape: the sheet's header block, its columns, and the bar chart fitted to the page
width, with the column headings repeated on every page. The browser cannot do this - the screen's grid only holds the
rows in view - so it is drawn here from the same worked-out rows the screen shows."""
import io
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = landscape(A3)
MARGIN = 28
ROW_H = 14.5
HEAD_H = 30
# (title, width, align) for SL.NO, V.NO, the item, Start, End, days, U.O.M, quantity, labour, predecessor, % done
COLUMNS = [("SL.NO", 40, "l"), ("V.NO", 52, "l"), ("ITEMS / ACTIVITY", 232, "l"), ("Start", 54, "c"), ("End", 54, "c"),
           ("Days", 32, "r"), ("U.O.M", 36, "c"), ("Quantity", 56, "r"), ("Labour", 36, "r"), ("Predecessor", 74, "l"),
           ("% Done", 38, "r")]
ORANGE, DARK, GREY, RED = colors.HexColor("#F4A261"), colors.HexColor("#B5651D"), colors.HexColor("#595959"), colors.HexColor("#E63946")


def _d(s):
    return date.fromisoformat(s) if s else None


def _short(c, text, width, font, size):
    text = str(text or "")
    while text and c.stringWidth(text, font, size) > width:
        text = text[:-1]
    return text


def programme_pdf(view):
    """The programme_view as a PDF (bytes)."""
    rows = view["rows"]
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Programme - %s" % (view["job"].get("name") or ""))
    table_w = sum(w for _, w, _ in COLUMNS)
    gantt_x = MARGIN + table_w
    gantt_w = PAGE_W - MARGIN - gantt_x
    begin, finish = _d(view.get("start")), _d(view.get("finish"))
    today = date.today()
    if begin is None or finish is None:
        begin, finish = today, today + timedelta(days=30)
    begin, finish = min(begin, today) - timedelta(days=1), max(finish, today) + timedelta(days=1)
    span = max((finish - begin).days + 1, 1)
    per_day = gantt_w / span
    x_of = lambda d: gantt_x + (d - begin).days * per_day
    cal = view["calendar"]
    off = set(cal.get("weekly_off") or []) if not cal.get("calendar_days") else set()
    holidays = {h["date"] for h in (cal.get("holidays") or [])}

    top_block = 110
    first_page_rows = int((PAGE_H - 2 * MARGIN - top_block - HEAD_H) // ROW_H)
    later_rows = int((PAGE_H - 2 * MARGIN - HEAD_H) // ROW_H)
    pages, start = [], 0
    for size in [first_page_rows] + [later_rows] * (len(rows) // max(later_rows, 1) + 1):
        pages.append(rows[start:start + size])
        start += size
        if start >= len(rows):
            break
    if not pages:
        pages = [[]]

    def header(page, y_top):
        """The column headings and the month strip, at y_top; returns the y the rows start at."""
        c.setFillColor(colors.HexColor("#404040"))
        c.rect(MARGIN, y_top - HEAD_H, PAGE_W - 2 * MARGIN, HEAD_H, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        x = MARGIN
        for title, w, align in COLUMNS:
            tx = x + 3 if align == "l" else (x + w / 2 if align == "c" else x + w - 3)
            {"l": c.drawString, "c": c.drawCentredString, "r": c.drawRightString}[align](tx, y_top - 19, title)
            x += w
        # the months, and a tick a week when there is room
        c.setFont("Helvetica-Bold", 7)
        d, last_month = begin, None
        while d <= finish:
            if (d.year, d.month) != last_month:
                last_month = (d.year, d.month)
                c.drawString(x_of(d) + 1, y_top - 11, d.strftime("%b %Y") if per_day * 28 > 36 else d.strftime("%b"))
            d += timedelta(days=1)
        if per_day >= 2.2:
            c.setFont("Helvetica", 5.5)
            d = begin - timedelta(days=begin.weekday())
            while d <= finish:
                if d >= begin:
                    c.drawString(x_of(d) + 0.5, y_top - 25, str(d.day))
                d += timedelta(days=7)
        return y_top - HEAD_H

    for index, chunk in enumerate(pages):
        if index == 0:
            y = PAGE_H - MARGIN
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(MARGIN, y - 14, view.get("company") or "")
            c.setFont("Helvetica-Bold", 14)
            c.drawString(MARGIN, y - 34, "SCHEDULE")
            c.setFont("Helvetica-Bold", 10)
            job = view["job"]
            c.drawString(MARGIN, y - 52, "Name of the work :- %s %s" % (job.get("number") or "", job.get("name") or ""))
            c.drawString(MARGIN, y - 66, "Location : %s" % (job.get("location") or ""))
            duration = None
            if view.get("start") and view.get("finish"):
                duration = (_d(view["finish"]) - _d(view["start"])).days + 1
            c.drawString(MARGIN + 330, y - 34, "TIME DURATION IN DAYS : %s" % (duration if duration is not None else ""))
            c.setFont("Helvetica", 9)
            bits = ["Done %s%%" % view.get("percent", 0), "Planned %s%%" % view.get("planned_percent", 0), "As on %s" % view.get("as_of", "")]
            if view.get("baseline"):
                bits.append("Baseline: %s" % view["baseline"]["label"])
            c.drawString(MARGIN + 330, y - 52, "   |   ".join(bits))
            y_rows = header(index, y - top_block + HEAD_H)
        else:
            y_rows = header(index, PAGE_H - MARGIN)
        body_top = y_rows
        # weekends / holidays shaded behind the bars, then the grid lines, then the bars
        if off or holidays:
            d = begin
            while d <= finish:
                if d.isoweekday() in off or d.isoformat() in holidays:
                    c.setFillColor(colors.HexColor("#E6E6E6"))
                    c.rect(x_of(d), body_top - len(chunk) * ROW_H, per_day, len(chunk) * ROW_H, stroke=0, fill=1)
                d += timedelta(days=1)
        for k, r in enumerate(chunk):
            y0 = body_top - (k + 1) * ROW_H
            if k % 2:
                c.setFillColor(colors.HexColor("#F7F7F7"))
                c.rect(MARGIN, y0, table_w, ROW_H, stroke=0, fill=1)
            c.setStrokeColor(colors.HexColor("#D0D0D0"))
            c.setLineWidth(0.3)
            c.line(MARGIN, y0, PAGE_W - MARGIN, y0)
            bold = r["summary"]
            font = "Helvetica-Bold" if bold else "Helvetica"
            c.setFillColor(colors.black)
            c.setFont(font, 7.5)
            x = MARGIN
            cells = [r["wbs"], r["boq_ref"], r["name"],
                     r["start"] and _d(r["start"]).strftime("%d-%b-%y") or "", r["end"] and _d(r["end"]).strftime("%d-%b-%y") or "",
                     "" if r["days"] is None else r["days"], r["uom"],
                     ("%g" % r["quantity"]) if r["quantity"] else "", ("%g" % r["labour_required"]) if r["labour_required"] else "",
                     r["predecessors"], "%d%%" % round(r["percent"] or 0)]
            for (title, w, align), text in zip(COLUMNS, cells):
                indent = min(r["level"], 8) * 7 if title.startswith("ITEMS") else 0
                shown = _short(c, text, w - 6 - indent, font, 7.5)
                ty = y0 + 4.2
                if align == "l":
                    c.drawString(x + 3 + indent, ty, shown)
                elif align == "c":
                    c.drawCentredString(x + w / 2, ty, shown)
                else:
                    c.drawRightString(x + w - 3, ty, shown)
                x += w
            s, e = _d(r["start"]), _d(r["end"])
            if s and e:
                x0, x1 = x_of(s), x_of(e) + per_day
                late = (e < today and (r["percent"] or 0) < 100 and not bold)
                if bold:
                    c.setFillColor(GREY)
                    c.rect(x0, y0 + 5.2, max(x1 - x0, 1), 3.6, stroke=0, fill=1)
                else:
                    c.setFillColor(RED if late else ORANGE)
                    c.rect(x0, y0 + 3, max(x1 - x0, 1.2), ROW_H - 6, stroke=0, fill=1)
                    done = (r["percent"] or 0) / 100.0
                    if done > 0:
                        c.setFillColor(DARK)
                        c.rect(x0, y0 + 3, max((x1 - x0) * min(done, 1), 0.8), ROW_H - 6, stroke=0, fill=1)
                    if r.get("critical"):
                        c.setStrokeColor(RED)
                        c.setLineWidth(0.8)
                        c.rect(x0, y0 + 3, max(x1 - x0, 1.2), ROW_H - 6, stroke=1, fill=0)
        # the table's vertical lines
        c.setStrokeColor(colors.HexColor("#BFBFBF"))
        c.setLineWidth(0.3)
        x = MARGIN
        bottom = body_top - max(len(chunk), 1) * ROW_H
        for _, w, _ in COLUMNS:
            c.line(x, body_top, x, bottom)
            x += w
        c.line(x, body_top, x, bottom)
        c.line(PAGE_W - MARGIN, body_top, PAGE_W - MARGIN, bottom)
        # the today line
        if begin <= today <= finish:
            c.setStrokeColor(RED)
            c.setLineWidth(1)
            c.line(x_of(today) + per_day / 2, body_top, x_of(today) + per_day / 2, bottom)
        c.setFillColor(colors.HexColor("#666666"))
        c.setFont("Helvetica", 7)
        c.drawRightString(PAGE_W - MARGIN, MARGIN - 12, "Page %d of %d" % (index + 1, len(pages)))
        c.showPage()
    c.save()
    return out.getvalue()
