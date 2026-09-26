"""Documents in the ruled, boxed form the trade signs.

A work order, an RA bill, a purchase order - on a site in India they arrive
as one printed form: a grid of boxes, the company and its GSTIN top left, the
document's number and dates in a box top right, the party with their PAN and
GSTIN underneath, the schedule ruled line by line, the total stated in figures
and in words, the taxes and the payment terms in their own boxes, and a row of
signatures across the bottom. Contractors, clients and gangs read that layout
without looking for anything; a document laid out any other way gets queried.

So there is one engine and every document is a description handed to it: a
list of blocks, top to bottom, each drawn as a ruled box the full width of the
page, butted against the one above. A new document is a new description, not
new drawing code.

    {"type": "header", "company": {...}, "title": "WORK ORDER", "facts": [(label, value)]}
    {"type": "party", "label": ..., "name": ..., "address": ..., "facts": [(label, value)]}
    {"type": "pairs", "rows": [(label, value), ...], "cols": 1 | 2}
    {"type": "band", "text": ...}                      a shaded title bar
    {"type": "table", "columns": [(title, width_mm, "L"|"C"|"R")], "rows": [[...]],
                      "totals": [(label, value, bold)]}
    {"type": "words", "label": "Rupees", "text": ...}
    {"type": "text", "text": ..., "style": "body" | "small" | "bold"}
    {"type": "terms", "rows": [(label, value)], "label_width": mm}
    {"type": "sums", "rows": [(label, amount, bold)]}  figures down the right
    {"type": "qr", "data": ..., "lines": [...]}        e-invoice registration
    {"type": "signatures", "boxes": [(role, name)]}
    {"type": "numbered", "items": [...]}               conditions, numbered
    {"type": "page_break"}

The page is A4, the grid black, the type Helvetica - it prints the same on the
office laser and a site photocopier, and a photocopy of a photocopy is still
legible, which is what happens to these.
"""
import io
import re

from wo_pdf import (PDF_AVAILABLE, _IMPORT_ERROR, _draw_watermark, _logo, inr,  # noqa: F401
                    _date)

if PDF_AVAILABLE:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                    PageTemplate, Paragraph, Table, TableStyle)
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.barcode.qr import QrCodeWidget
else:  # pragma: no cover
    mm = 72.0 / 25.4

MARGIN = 14 * mm
WIDTH = 182 * mm            # A4 less the two margins
GRID = 0.6                  # line weight of the ruling
SHADE = "#d9d9d9"           # the grey of a band or a table head


def _esc(value):
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _br(value):
    return "<br/>".join(_esc(x) for x in str(value or "").splitlines())


def _styles():
    base = dict(fontName="Helvetica", fontSize=8.6, leading=10.6, textColor=colors.black)
    return {
        "body": ParagraphStyle("body", **base),
        "small": ParagraphStyle("small", **dict(base, fontSize=7.4, leading=9.2)),
        "bold": ParagraphStyle("bold", **dict(base, fontName="Helvetica-Bold")),
        "label": ParagraphStyle("label", **dict(base, fontName="Helvetica-Bold")),
        "right": ParagraphStyle("right", **dict(base, alignment=TA_RIGHT)),
        "rightbold": ParagraphStyle("rightbold", **dict(base, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        "centre": ParagraphStyle("centre", **dict(base, alignment=TA_CENTER)),
        "centrebold": ParagraphStyle("centrebold", **dict(base, fontName="Helvetica-Bold", alignment=TA_CENTER)),
        "title": ParagraphStyle("title", **dict(base, fontName="Helvetica-Bold", fontSize=13.5,
                                                 leading=16, alignment=TA_CENTER)),
        "band": ParagraphStyle("band", **dict(base, fontName="Helvetica-Bold", fontSize=10,
                                                leading=12.5, alignment=TA_CENTER)),
        "company": ParagraphStyle("company", **dict(base, fontName="Helvetica-Bold", fontSize=10.5,
                                                      leading=13)),
    }


def _box(data, widths, extra=None, pad=3):
    """A ruled box the width of the page."""
    t = Table(data, colWidths=widths)
    style = [("BOX", (0, 0), (-1, -1), GRID, colors.black),
             ("INNERGRID", (0, 0), (-1, -1), GRID, colors.black),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
             ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    t.setStyle(TableStyle(style + list(extra or [])))
    return t


def _pairs_table(rows, st, label_w, value_w, shade_labels=False):
    data = [[Paragraph(_esc(k) + (" :" if k and not str(k).endswith(":") else ""), st["label"]),
             Paragraph(_br(v), st["body"])] for k, v in rows]
    extra = [("BACKGROUND", (0, 0), (0, -1), colors.HexColor(SHADE))] if shade_labels else []
    return _box(data, [label_w, value_w], extra)


def _header(block, st):
    c = block.get("company") or {}
    lines = [Paragraph(_esc(c.get("name", "")).upper(), st["company"])]
    for line in (c.get("address") or "").splitlines():
        if line.strip():
            lines.append(Paragraph(_esc(line.strip()), st["body"]))
    for label, key in (("GSTIN No.", "gstin"), ("PAN No.", "pan"), ("STATE", "state")):
        if c.get(key):
            lines.append(Paragraph("%s : %s" % (label, _esc(c[key])), st["body"]))
    logo = _logo(c.get("logo_url"), max_height=20 * mm)
    facts = [[Paragraph(_esc(block.get("title", "")), st["title"]), ""]]
    for k, v in block.get("facts") or []:
        facts.append([Paragraph(_esc(k) + " :", st["label"]), Paragraph(_esc(v), st["body"])])
    right = Table(facts, colWidths=[24 * mm, 42 * mm])
    right.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)), ("LINEBELOW", (0, 0), (-1, -1), GRID, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 0, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    flush = [("LEFTPADDING", (-1, 0), (-1, 0), 0), ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
             ("TOPPADDING", (-1, 0), (-1, 0), 0), ("BOTTOMPADDING", (-1, 0), (-1, 0), 0),
             ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if not logo:
        # No mark on file: the company takes the width rather than leave an empty box.
        return _box([[lines, right]], [116 * mm, 66 * mm], flush)
    return _box([[lines, logo, right]], [78 * mm, 38 * mm, 66 * mm],
                flush + [("ALIGN", (1, 0), (1, 0), "CENTER"), ("VALIGN", (1, 0), (1, 0), "MIDDLE")])


def _party(block, st):
    left = [Paragraph("<b>%s :</b> %s" % (_esc(block.get("label", "")), _esc(block.get("name", ""))), st["body"])]
    if block.get("address"):
        left.append(Paragraph(_br(block["address"]), st["body"]))
    facts = block.get("facts") or []
    right = _pairs_table(facts, st, 24 * mm, 42 * mm) if facts else ""
    if facts:
        right.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0, colors.white),
                                   ("LINEBEFORE", (1, 0), (1, -1), 0, colors.white)]))
    return _box([[left, right]], [116 * mm, 66 * mm],
                [("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0),
                 ("TOPPADDING", (1, 0), (1, 0), 0), ("BOTTOMPADDING", (1, 0), (1, 0), 0)])


def _pairs(block, st):
    rows = block.get("rows") or []
    if block.get("cols", 1) == 2:
        data, pair = [], None
        for k, v in rows:
            cell = [Paragraph(_esc(k) + " :", st["label"]), Paragraph(_br(v), st["body"])]
            if pair is None:
                pair = cell
            else:
                data.append(pair + cell)
                pair = None
        if pair is not None:
            data.append(pair + ["", ""])
        return _box(data, [30 * mm, 61 * mm, 30 * mm, 61 * mm])
    lw = (block.get("label_width") or 42) * mm
    return _pairs_table(rows, st, lw, WIDTH - lw)


def _table(block, st):
    cols = block["columns"]
    widths = [w * mm for _, w, _ in cols]
    scale = WIDTH / float(sum(widths))
    widths = [w * scale for w in widths]
    align = {"L": st["body"], "C": st["centre"], "R": st["right"]}
    head = [Paragraph(_esc(t), st["centrebold"]) for t, _, _ in cols]
    data = [head]
    for row in block.get("rows") or []:
        data.append([Paragraph(_br(v), align[a]) for v, (_, _, a) in zip(row, cols)])
    if not block.get("rows"):
        data.append([Paragraph("-", st["centre"])] + [""] * (len(cols) - 1))
    extra = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(SHADE)), ("VALIGN", (0, 1), (-1, -1), "TOP")]
    for label, value, bold in block.get("totals") or []:
        data.append([Paragraph(_esc(label), st["rightbold"] if bold else st["right"])] + [""] * (len(cols) - 2)
                    + [Paragraph(_esc(value), st["rightbold"] if bold else st["right"])])
        r = len(data) - 1
        extra.append(("SPAN", (0, r), (len(cols) - 2, r)))
    t = _box(data, widths, extra)
    t.repeatRows = 1
    return t


def _sums(block, st):
    data = [[Paragraph(_esc(label), st["rightbold"] if bold else st["right"]),
             Paragraph(_esc(value), st["rightbold"] if bold else st["right"])]
            for label, value, bold in block.get("rows") or []]
    return _box(data, [WIDTH - 40 * mm, 40 * mm])


def _qr(block, st):
    lines = [Paragraph(_br(x), st["small"]) for x in block.get("lines") or []]
    size = 30 * mm
    w = QrCodeWidget(block.get("data") or "")
    b = w.getBounds()
    d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
    d.add(w)
    return _box([[lines, d]], [WIDTH - 36 * mm, 36 * mm],
                [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "CENTER")])


def _signatures(block, st):
    boxes = block.get("boxes") or []
    if not boxes:
        return None
    w = WIDTH / len(boxes)
    cells = []
    for role, name in boxes:
        cells.append([Paragraph(_esc(role), st["centrebold"]), Paragraph("&nbsp;", st["body"]),
                      Paragraph("&nbsp;", st["body"]), Paragraph(_esc(name or ""), st["centre"])])
    return _box([cells], [w] * len(boxes), [("VALIGN", (0, 0), (-1, -1), "TOP"),
                                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4)])


def _numbered(block, st):
    data = [[Paragraph("%d. %s" % (i, _br(item)), st["body"])] for i, item in enumerate(block.get("items") or [], 1)]
    for extra in block.get("closing") or []:
        data.append([Paragraph(_br(extra), st["body"])])
    return _box(data or [[""]], [WIDTH], [("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])


def _flow(blocks, st):
    out = []
    for b in blocks:
        kind = b.get("type")
        if kind == "header":
            out.append(_header(b, st))
        elif kind == "party":
            out.append(_party(b, st))
        elif kind == "pairs":
            out.append(_pairs(b, st))
        elif kind == "band":
            out.append(_box([[Paragraph(_esc(b.get("text", "")), st["band"])]], [WIDTH],
                            [("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(SHADE))]))
        elif kind == "table":
            out.append(_table(b, st))
        elif kind == "words":
            out.append(_box([[Paragraph(_esc(b.get("label", "Rupees")), st["body"]),
                              Paragraph(_esc(b.get("text", "")), st["bold"])]], [24 * mm, WIDTH - 24 * mm]))
        elif kind == "text":
            out.append(_box([[Paragraph(_br(b.get("text", "")) if b.get("plain", True) else b.get("text", ""),
                                        st.get(b.get("style") or "body", st["body"]))]], [WIDTH]))
        elif kind == "terms":
            lw = (b.get("label_width") or 62) * mm
            out.append(_pairs_table(b.get("rows") or [], st, lw, WIDTH - lw))
        elif kind == "sums":
            out.append(_sums(b, st))
        elif kind == "qr" and b.get("data"):
            out.append(_qr(b, st))
        elif kind == "signatures":
            sig = _signatures(b, st)
            if sig is not None:
                out.append(KeepTogether([sig]))
        elif kind == "numbered":
            out.append(_numbered(b, st))
        elif kind == "page_break":
            out.append(PageBreak())
    return out


def build_form_pdf(spec):
    """The document as PDF bytes, from its description."""
    if _IMPORT_ERROR is not None:  # pragma: no cover
        raise RuntimeError("reportlab is not installed, so the PDF cannot be produced.") from _IMPORT_ERROR
    st = _styles()
    buf = io.BytesIO()
    footer = spec.get("footer") or ""
    watermark = spec.get("watermark") or ""

    class Numbered(pdfcanvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.saveState()
                self.setFont("Helvetica", 6.8)
                self.setFillColor(colors.HexColor("#555555"))
                self.drawString(MARGIN, 8 * mm, footer)
                self.drawRightString(A4[0] - MARGIN, 8 * mm, "Page %d of %d" % (self._pageNumber, total))
                self.restoreState()
                super().showPage()
            super().save()

    def on_page(canvas, _doc):
        _draw_watermark(canvas, A4[0], A4[1], watermark)

    template = BaseDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                               topMargin=12 * mm, bottomMargin=14 * mm,
                               title=spec.get("title", ""), author=spec.get("author", ""))
    frame = Frame(MARGIN, 14 * mm, WIDTH, A4[1] - 26 * mm,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    template.addPageTemplates([PageTemplate(id="form", frames=[frame], onPage=on_page)])
    template.build(_flow(spec.get("blocks") or [], st), canvasmaker=Numbered)
    return buf.getvalue()


def plain_number(value, places=0):
    """60000 -> 60,000 - the schedule prints whole rupees where the figure is
    whole, as the trade's forms do, and paise only where there are some."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0.0
    return inr(v, 2 if round(v, 2) != round(v, 0) or places else 0)


def qty_text(value):
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return str(value or "")
    return inr(v, 0) if v == int(v) else inr(v, 3).rstrip("0").rstrip(".")


def date_text(value):
    return _date(value)


def strip_tags(value):
    return re.sub(r"<[^>]+>", "", str(value or ""))
