"""The subcontract work order as the document that actually gets signed.

A work order leaves the office on paper. It is read by a site engineer with a
tape, argued over by a contractor's accountant, and eventually attached to a
running account bill - so the printed copy is the deliverable, and the screen
is only where it was assembled.

Laid out the way the trade reads one:

    page 1     the covering letter - who is issuing it, to whom, for what,
               on what dates, and what it is worth
    Annexure I the schedule of work, priced line by line
    Annexure II the terms, numbered so a clause can be cited in a dispute
    last       the signature blocks, kept whole on one page

ReportLab rather than WeasyPrint on purpose: it is a pure-Python wheel, so it
installs the same on the Windows laptop this is developed on and on the Linux
container it is deployed to. WeasyPrint would want GTK, Pango and Cairo
present as system packages, which is a different problem in each of those two
places and neither of them is this module's problem.

The whole thing is a function of one dictionary - the payload
/api/wo/orders/{id}/document already returns - so the layout can be exercised
in a test without a database, a request or a login.
"""

import io
import re

# Deliberately not imported at module load. If the wheel is missing the rest
# of the platform must still start; only the download should fail, and it
# should fail saying so.
_IMPORT_ERROR = None
try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether,
                                    PageBreak, PageTemplate, Paragraph,
                                    Spacer, Table, TableStyle)
except ImportError as exc:  # pragma: no cover - exercised by not having it
    _IMPORT_ERROR = exc
    # The unit, so the page constants below still evaluate and the module
    # still imports. Everything else here is only reached while rendering,
    # which is refused outright without the library.
    mm = 72.0 / 25.4


PDF_AVAILABLE = _IMPORT_ERROR is None


# --- House style -----------------------------------------------------------
# Ink, not decoration. A work order is photocopied, faxed and scanned back in;
# anything that depends on colour to be legible does not survive that trip.

INK = "#111827"
MUTED = "#6b7280"
RULE = "#9ca3af"
BAND = "#f3f4f6"
EDGE = "#d1d5db"

PAGE_MARGIN = 16 * mm
TOP_MARGIN = 15 * mm
BOTTOM_MARGIN = 20 * mm


def _styles():
    """Built per call rather than at import: ParagraphStyle objects are
    mutable, and a stylesheet shared between two concurrent requests is a bug
    that only shows up under load."""
    base = ParagraphStyle(
        "base", fontName="Helvetica", fontSize=9, leading=12.5,
        textColor=colors.HexColor(INK))
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7.6, leading=10,
                                textColor=colors.HexColor(MUTED)),
        "body": ParagraphStyle("body", parent=base, alignment=TA_JUSTIFY,
                               spaceAfter=5),
        "letterhead": ParagraphStyle("letterhead", parent=base, fontSize=15.5,
                                     leading=18, fontName="Helvetica-Bold"),
        "letterhead_sub": ParagraphStyle("letterhead_sub", parent=base,
                                         fontSize=8, leading=11,
                                         textColor=colors.HexColor(MUTED)),
        "doctitle": ParagraphStyle("doctitle", parent=base, fontSize=13,
                                   leading=16, alignment=TA_CENTER,
                                   fontName="Helvetica-Bold"),
        "section": ParagraphStyle("section", parent=base, fontSize=10,
                                  leading=13, spaceBefore=8, spaceAfter=5,
                                  fontName="Helvetica-Bold"),
        "label": ParagraphStyle("label", parent=base, fontSize=7.6, leading=10,
                                textColor=colors.HexColor(MUTED)),
        "value": ParagraphStyle("value", parent=base, fontSize=9, leading=12),
        "value_bold": ParagraphStyle("value_bold", parent=base, fontSize=9,
                                     leading=12, fontName="Helvetica-Bold"),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.2, leading=10.5),
        "cell_head": ParagraphStyle("cell_head", parent=base, fontSize=7.5,
                                    leading=9.5, fontName="Helvetica-Bold",
                                    textColor=colors.white),
        "cell_right": ParagraphStyle("cell_right", parent=base, fontSize=8.2,
                                     leading=10.5, alignment=TA_RIGHT),
        "clause": ParagraphStyle("clause", parent=base, fontSize=8.4,
                                 leading=11.5, alignment=TA_JUSTIFY),
        "clause_head": ParagraphStyle("clause_head", parent=base, fontSize=8.6,
                                      leading=11.5,
                                      fontName="Helvetica-Bold"),
        "sign": ParagraphStyle("sign", parent=base, fontSize=8, leading=11),
        "words": ParagraphStyle("words", parent=base, fontSize=8.6, leading=12,
                                fontName="Helvetica-Bold"),
    }


# --- Numbers ---------------------------------------------------------------

def inr(value, places=2):
    """1234567.5 -> 12,34,567.50.

    Indian grouping, because the signatories check the figure against a
    document written in lakhs and crores. Western grouping on the same number
    reads as a different amount at a glance, which on a legal document is the
    kind of confusion that gets one signed for the wrong sum.
    """
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    negative = number < 0
    text = ("%%.%df" % places) % abs(number)
    whole, _, frac = text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        # Everything above the last three digits is grouped in twos.
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = head + "," + tail
    out = whole + ("." + frac if frac else "")
    return ("(" + out + ")") if negative else out


def _rate(value):
    """Rates print to four places only when they need them - 12.2220 in a
    column of round numbers reads as a typo, and 12.22 where the rate really
    is 12.222 is a figure the contractor's own spreadsheet will not match."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0.00"
    return inr(number, 4 if round(number, 2) != round(number, 4) else 2)


def _date(value):
    """2026-09-01 -> 01/09/2026. Stored ISO because that sorts; printed the way
    it is read on a site in India, where 01/09 is never the first of September
    being mistaken for the ninth of January."""
    text = str(value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    return "%s/%s/%s" % (match.group(3), match.group(2), match.group(1)) if match else text


def _rich(value):
    """Text that is allowed to carry its formatting.

    The scope of work is written in an editor, and the markup it produces has
    already been narrowed to a known set on the way into the database. Bare
    ampersands still have to be escaped - a scope reading "steel & cement"
    would otherwise fail to parse and take the page with it - but the tags
    themselves are passed through, because they are the point.
    """
    text = str(value if value is not None else "")
    text = re.sub(r"&(?!(?:[a-zA-Z]+|#\d+);)", "&amp;", text)
    text = re.sub(r"</?\s*(?:p|ul|ol)\s*>", "<br/>", text)
    text = re.sub(r"<\s*li\s*>", "<br/>&nbsp;&nbsp;&bull;&nbsp;", text)
    text = re.sub(r"</\s*li\s*>", "", text)
    text = text.replace("\n", "<br/>")
    # Runs of breaks left by the substitutions above read as blank paragraphs.
    text = re.sub(r"(?:<br/>\s*){3,}", "<br/><br/>", text)
    # A leading break is the opening <p> the editor wrapped everything in, and
    # it prints as an empty first line. Stripped as a tag, not as characters:
    # lstrip would eat the b and the r off a scope that begins "brick work".
    text = re.sub(r"^(?:\s*<br/>)+", "", text)
    return text.strip()


def _text(value):
    """Anything user-typed is going into a Paragraph, which parses markup."""
    return (str(value if value is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _lines(value):
    """A typed address keeps the line breaks it was typed with."""
    parts = [p.strip() for p in re.split(r"[\r\n]+", str(value or "")) if p.strip()]
    return "<br/>".join(_text(p) for p in parts)


# --- Page furniture --------------------------------------------------------

def _draw_watermark(canvas, page_width, page_height, text):
    """Across the page, behind the text.

    Drawn here rather than into the flow so that it cannot be omitted by
    rendering the document a different way: a provisional order carries the
    band on every page, including the one somebody photographs and forwards.
    """
    if not text:
        return
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 46 if len(text) < 24 else 30)
    canvas.setFillColor(colors.HexColor("#dc2626"))
    try:
        canvas.setFillAlpha(0.11)
    except AttributeError:      # pragma: no cover - very old reportlab
        canvas.setFillColor(colors.HexColor("#f3d3d3"))
    canvas.translate(page_width / 2.0, page_height / 2.0)
    canvas.rotate(38)
    canvas.drawCentredString(0, 0, text)
    canvas.restoreState()


def _draw_footer(canvas, doc, meta):
    canvas.saveState()
    y = BOTTOM_MARGIN - 6 * mm
    canvas.setStrokeColor(colors.HexColor(EDGE))
    canvas.setLineWidth(0.5)
    canvas.line(PAGE_MARGIN, y + 5 * mm, doc.pagesize[0] - PAGE_MARGIN, y + 5 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor(MUTED))
    canvas.drawString(PAGE_MARGIN, y, meta.get("footer_left", ""))
    canvas.drawCentredString(doc.pagesize[0] / 2.0, y, meta.get("footer_centre", ""))
    canvas.restoreState()


def _numbered_canvas(meta):
    """Page X of Y needs Y, which is only known once the last page is laid out.

    So pages are held back, counted, and only then written - the standard
    two-pass trick. The page number is stamped in the second pass, over empty
    footer space; the watermark stays in the first, underneath the text.
    """

    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.saveState()
                self.setFont("Helvetica", 7)
                self.setFillColor(colors.HexColor(MUTED))
                self.drawRightString(
                    A4[0] - PAGE_MARGIN, BOTTOM_MARGIN - 6 * mm,
                    "Page %d of %d" % (self._pageNumber, total))
                self.restoreState()
                super().showPage()
            super().save()

    return NumberedCanvas


# --- The parts of the document ---------------------------------------------

def _logo(value, max_height=16 * mm):
    """The letterhead mark, if there is one and it travels with the document.

    Only a data: URI is drawn. A logo held at an http address would have to be
    fetched from here to be printed - which makes rendering a work order into
    a request this server makes to a URL somebody typed into a form, and turns
    a slow or hostile host into a work order that never prints. The screen can
    show a remote logo perfectly well; the PDF prints without one.
    """
    if not value or not str(value).startswith("data:image"):
        return None
    try:
        import base64
        head, _, payload = str(value).partition(",")
        raw = base64.b64decode(payload, validate=False)
        reader = ImageReader(io.BytesIO(raw))
        width, height = reader.getSize()
        if not width or not height:
            return None
        scale = min(max_height / float(height), (46 * mm) / float(width))
        return Image(reader, width=width * scale, height=height * scale)
    except Exception:
        # A logo that will not decode is a cosmetic problem. Printing the
        # order without it beats refusing to print the order.
        return None


def _letterhead(doc, st):
    unit = doc.get("business_unit_detail") or {}
    name = unit.get("name") or doc.get("company") or ""
    tax_bits = []
    if unit.get("gstin"):
        tax_bits.append("GSTIN: " + _text(unit["gstin"]))
    if unit.get("pan"):
        tax_bits.append("PAN: " + _text(unit["pan"]))

    left = []
    mark = _logo(unit.get("logo_url"))
    if mark is not None:
        left += [mark, Spacer(1, 4)]
    left.append(Paragraph(_text(name), st["letterhead"]))
    if unit.get("address"):
        left.append(Paragraph(_lines(unit["address"]), st["letterhead_sub"]))
    if tax_bits:
        left.append(Paragraph("&nbsp;&nbsp;|&nbsp;&nbsp;".join(tax_bits),
                              st["letterhead_sub"]))

    right = [Paragraph("WORK ORDER", ParagraphStyle(
        "wo", parent=st["doctitle"], alignment=TA_RIGHT, fontSize=14)),
        Paragraph(_text(doc.get("wo_number", "")), ParagraphStyle(
            "won", parent=st["value_bold"], alignment=TA_RIGHT, fontSize=10.5))]
    if doc.get("amendment_no"):
        right.append(Paragraph(
            "Amendment %d - supersedes the order it revises" % doc["amendment_no"],
            ParagraphStyle("amd", parent=st["small"], alignment=TA_RIGHT)))

    table = Table([[left, right]], colWidths=[112 * mm, 66 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 1.1, colors.HexColor(INK)),
    ]))
    return table


def _fact_grid(pairs, st, col_widths=(30 * mm, 59 * mm)):
    """Label over value, in two columns. Reads as a form, which is what the
    people checking it are used to checking."""
    rows = []
    for i in range(0, len(pairs), 2):
        chunk = pairs[i:i + 2]
        cells = []
        for label, value in chunk:
            cells.append(Paragraph(_text(label).upper(), st["label"]))
            cells.append(Paragraph(_text(value) or "&mdash;", st["value"]))
        while len(cells) < 4:
            cells.append("")
        rows.append(cells)
    table = Table(rows, colWidths=list(col_widths) * 2)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _pair_stack(pairs, st, label_width, value_width):
    """Label beside value, one pair to a row. Used where the block has to fit
    a fixed width - a grid two pairs wide would overrun it."""
    rows = [[Paragraph(_text(label).upper(), st["label"]),
             Paragraph(_text(value) or "&mdash;", st["value"])]
            for label, value in pairs]
    table = Table(rows, colWidths=[label_width, value_width])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


def _parties(doc, st):
    con = doc.get("contractor_detail") or {}
    lines = ["<b>" + _text(con.get("company_name") or doc.get("contractor") or "") + "</b>"]
    if con.get("contact_person"):
        lines.append("Kind attn: " + _text(con["contact_person"]))
    if con.get("address"):
        lines.append(_lines(con["address"]))
    tax = [b for b in ("GSTIN: " + _text(con["gst_number"]) if con.get("gst_number") else "",
                       "PAN: " + _text(con["pan"]) if con.get("pan") else "",
                       "Vendor code: " + _text(con["vendor_code"]) if con.get("vendor_code") else "") if b]
    if tax:
        lines.append("&nbsp;&nbsp;|&nbsp;&nbsp;".join(tax))

    to_block = [Paragraph("TO", st["label"]),
                Paragraph("<br/>".join(lines), st["value"])]

    right_pairs = [
        ("Date", doc.get("printed_at", "").split("  ")[0]),
        ("Financial year", doc.get("financial_year", "")),
        ("Project", doc.get("project", "")),
        ("Department", doc.get("department", "")),
        ("Work type", doc.get("work_type", "")),
        ("Status", doc.get("status", "")),
    ]

    table = Table([[to_block, _pair_stack(right_pairs, st, 26 * mm, 52 * mm)]],
                  colWidths=[92 * mm, 86 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _money_summary(doc, st, width=178 * mm):
    """What it is worth, stated once in figures and once in words.

    GST is added and TDS is withheld, so they are shown on separate lines with
    the withholding bracketed. Netting them into one 'tax' line is how an
    order goes out committing the business to a number nobody meant.
    """
    rows = [
        ["Gross order value", inr(doc.get("gross_amount"))],
        ["Add: GST @ %s%%" % _trim(doc.get("gst_rate")), inr(doc.get("gst_amount"))],
        ["Less: TDS @ %s%% (withheld at source)" % _trim(doc.get("tds_rate")),
         "(" + inr(doc.get("tds_amount")) + ")"],
        ["Net order value payable", inr(doc.get("net_order_value"))],
    ]
    data = [[Paragraph(_text(label), st["cell"]),
             Paragraph(_text(value), st["cell_right"])] for label, value in rows]
    table = Table(data, colWidths=[width - 42 * mm, 42 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, colors.HexColor(EDGE)),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor(EDGE)),
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor(BAND)),
        ("LINEABOVE", (0, 3), (-1, 3), 0.9, colors.HexColor(INK)),
        ("LINEBELOW", (0, 3), (-1, 3), 0.9, colors.HexColor(INK)),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
    ]))
    # Retention and the advance are stated under the value, not inside it.
    # They change when the money moves, not what it comes to, and a contractor
    # who reads 5% retention as 5% off the price prices the next job for it.
    payment_notes = []
    if doc.get("retention_percent"):
        payment_notes.append(
            "Retention of %s%% (%s) shall be withheld from each certified bill "
            "and released in accordance with the retention clause."
            % (_trim(doc["retention_percent"]), "Rs. " + inr(doc.get("retention_amount"))))
    if doc.get("mobilization_advance_percent"):
        recovery = doc.get("advance_recovery_percent") or 0
        payment_notes.append(
            "A mobilization advance of %s%% (%s) is payable against an "
            "equivalent bank guarantee%s."
            % (_trim(doc["mobilization_advance_percent"]),
               "Rs. " + inr(doc.get("mobilization_advance_amount")),
               ", recovered at %s%% of each Running Account bill" % _trim(recovery)
               if recovery else ""))

    words = Table([[Paragraph(
        "<b>In words:</b> " + _text(doc.get("amount_in_words", "")), st["words"])]],
        colWidths=[width])
    words.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(EDGE)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
    ]))
    flow = [table, Spacer(1, 4), words]
    for note in payment_notes:
        flow += [Spacer(1, 3), Paragraph(note, st["small"])]
    return flow


def _trim(value):
    """18.0 prints as 18; 2.5 stays 2.5."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    return ("%g" % number)


def _schedule(doc, st):
    """Annexure I. The priced schedule, which is the part that gets measured.

    The heading row repeats on every page it runs onto - a rate column with no
    heading two pages in is how a rate gets read as a quantity.
    """
    head = ["Activity", "Item code", "Description of work", "UOM",
            "Qty", "Rate", "Amount"]
    data = [[Paragraph(_text(h), st["cell_head"]) for h in head]]

    for index, item in enumerate(doc.get("items") or [], start=1):
        # The specification sits under the description in the same cell rather
        # than in a column of its own. It is read once, when the line is being
        # agreed; a column wide enough for it would take the width off the
        # description, which is read on every measurement.
        described = _text(item.get("item_description"))
        if (item.get("technical_spec") or "").strip():
            described += ('<br/><font size="7" color="#6b7280">'
                          + _lines(item["technical_spec"]) + "</font>")
        data.append([
            Paragraph(_text(item.get("activity_no") or index), st["cell"]),
            Paragraph(_text(item.get("item_code")), st["cell"]),
            Paragraph(described, st["cell"]),
            Paragraph(_text(item.get("uom")), st["cell"]),
            Paragraph(inr(item.get("quantity"), 3).rstrip("0").rstrip(".") or "0",
                      st["cell_right"]),
            Paragraph(_rate(item.get("unit_rate")), st["cell_right"]),
            Paragraph(inr(item.get("total_amount")), st["cell_right"]),
        ])

    if len(data) == 1:
        data.append([Paragraph("No items scheduled.", st["cell"]), "", "", "", "", "", ""])

    data.append([
        "", "", Paragraph("<b>Total</b>", st["cell_right"]), "", "", "",
        Paragraph("<b>" + inr(doc.get("gross_amount")) + "</b>", st["cell_right"])])

    # An amount that wraps onto a second line is a figure somebody has to
    # reassemble by eye, so the money columns are sized for the widest number
    # this trade actually writes - a crore, to the paisa - and the description
    # takes what is left.
    widths = [18 * mm, 25 * mm, 62 * mm, 10 * mm, 15 * mm, 20 * mm, 28 * mm]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (2, 0), (2, -1), 5),
        ("RIGHTPADDING", (2, 0), (2, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(EDGE)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2),
         [colors.white, colors.HexColor("#fbfbfb")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(BAND)),
        ("LINEABOVE", (0, -1), (-1, -1), 0.9, colors.HexColor(INK)),
        ("SPAN", (0, -1), (2, -1)),
    ]))
    return table


def _terms(doc, st):
    """Annexure II. Numbered, because a clause exists to be cited."""
    flow = []
    terms = doc.get("terms") or []
    if not terms:
        flow.append(Paragraph("No additional terms were attached to this order.",
                              st["clause"]))
        return flow
    for index, term in enumerate(terms, start=1):
        heading = Paragraph(
            "%d.&nbsp;&nbsp;%s" % (index, _text(term.get("clause_category") or "Clause")),
            st["clause_head"])
        body = Paragraph(_text(term.get("clause_text")), st["clause"])
        # A heading orphaned at the foot of a page reads as if the clause above
        # it carries on, which is exactly the misreading a dispute turns on.
        flow.append(KeepTogether([heading, Spacer(1, 2), body, Spacer(1, 7)]))
    return flow


def _signatures(doc, st):
    """Four blocks: who priced it, who approved it, who issues it, who accepts.

    Kept together on one page. A signature block split across a page break is
    a document somebody can later say they signed only half of.
    """
    blocks = []
    for sig in doc.get("signatures") or []:
        name = sig.get("name") or ""
        blocks.append([
            Paragraph(_text(sig.get("role", "")).upper(), st["label"]),
            Spacer(1, 26),
            Paragraph("<b>%s</b>" % (_text(name) or "&nbsp;"), st["sign"]),
            Paragraph(_text(sig.get("for", "")), st["small"]),
        ])
    while blocks and len(blocks) % 2:
        blocks.append([Paragraph("&nbsp;", st["sign"])])

    parts = [Paragraph("Signatures", st["section"])]
    if blocks:
        # An empty grid is not a table with no rows, it is no table: a Table
        # built from nothing raises rather than drawing nothing, and would
        # take the whole document down with it.
        rows = [blocks[i:i + 2] for i in range(0, len(blocks), 2)]
        table = Table(rows, colWidths=[89 * mm, 89 * mm])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(EDGE)),
        ]))
        parts.append(table)
    return KeepTogether(parts + [
        Spacer(1, 6),
        Paragraph(
            "This work order is issued in duplicate. The Contractor shall return "
            "one copy duly signed and stamped in token of unconditional "
            "acceptance within seven days of receipt. Work commenced against "
            "this order shall be deemed acceptance of every term stated herein.",
            st["small"]),
    ])


# --- Assembly --------------------------------------------------------------

def build_work_order_pdf(doc):
    """The whole order, as PDF bytes.

    `doc` is the payload from /api/wo/orders/{id}/document - nothing is read
    from the database here, so the layout is testable on a plain dictionary.
    """
    if _IMPORT_ERROR is not None:      # pragma: no cover
        raise RuntimeError(
            "reportlab is not installed, so the PDF cannot be produced. "
            "Install it with: pip install reportlab") from _IMPORT_ERROR

    st = _styles()
    buffer = io.BytesIO()
    watermark = doc.get("watermark") or ""
    meta = {
        "footer_left": "%s  |  %s" % (doc.get("wo_number", ""),
                                      (doc.get("business_unit_detail") or {}).get("name")
                                      or doc.get("company", "")),
        "footer_centre": "Printed %s" % doc.get("printed_at", ""),
    }

    def on_page(canvas, doc_template):
        _draw_watermark(canvas, A4[0], A4[1], watermark)
        _draw_footer(canvas, doc_template, meta)

    template = BaseDocTemplate(
        buffer, pagesize=A4,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
        topMargin=TOP_MARGIN, bottomMargin=BOTTOM_MARGIN,
        title="Work Order %s" % doc.get("wo_number", ""),
        author=(doc.get("business_unit_detail") or {}).get("name") or doc.get("company", ""),
        subject=doc.get("subject", ""))
    frame = Frame(PAGE_MARGIN, BOTTOM_MARGIN,
                  A4[0] - 2 * PAGE_MARGIN, A4[1] - TOP_MARGIN - BOTTOM_MARGIN,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    template.addPageTemplates([
        PageTemplate(id="order", frames=[frame], onPage=on_page)])

    flow = [_letterhead(doc, st), Spacer(1, 8), _parties(doc, st), Spacer(1, 10)]

    if doc.get("subject"):
        subject = Table([[Paragraph("<b>Sub:</b> " + _text(doc["subject"]), st["value"])]],
                        colWidths=[178 * mm])
        subject.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(BAND)),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(EDGE)),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        flow += [subject, Spacer(1, 10)]

    flow.append(Paragraph("Dear Sir,", st["body"]))
    flow.append(Paragraph(
        "With reference to your offer and the discussions held thereafter, we are "
        "pleased to place this work order on you for the work described below and "
        "scheduled in Annexure I, at the rates stated therein and subject to the "
        "terms and conditions at Annexure II, which form an integral part of this "
        "order.", st["body"]))

    if doc.get("scope_of_work"):
        flow.append(Paragraph("Scope of work", st["section"]))
        flow.append(Paragraph(_rich(doc["scope_of_work"]), st["body"]))

    flow.append(Paragraph("Programme and securities", st["section"]))
    flow.append(_fact_grid([
        ("Commencement", _date(doc.get("commencement_date"))),
        ("Completion", _date(doc.get("completion_date"))),
        ("Duration", ("%s months" % _trim(doc.get("duration_months")))
         if doc.get("duration_months") else ""),
        ("Defect liability", ("%s months" % doc.get("defect_liability_months"))
         if doc.get("defect_liability_months") else "Not applicable"),
        ("Bank guarantee", ("Rs. " + inr(doc.get("bank_guarantee_amount")))
         if doc.get("bank_guarantee_applicable") else "Not applicable"),
        ("BG valid until", _date(doc.get("bank_guarantee_validity"))
         if doc.get("bank_guarantee_applicable") else ""),
    ], st, (34 * mm, 55 * mm)))

    flow.append(Paragraph("Order value", st["section"]))
    flow += _money_summary(doc, st)
    flow.append(Spacer(1, 6))
    flow.append(Paragraph(
        "All amounts are in Indian Rupees. Rates are firm for the duration of "
        "this order and are inclusive of everything described in Annexure II "
        "save where expressly stated otherwise.", st["small"]))

    flow.append(PageBreak())
    flow.append(Paragraph("Annexure I &mdash; Schedule of work", st["doctitle"]))
    flow.append(Spacer(1, 8))
    flow.append(_schedule(doc, st))
    flow.append(Spacer(1, 8))
    flow.append(Paragraph(
        "Quantities are provisional and shall be paid for on the basis of work "
        "actually executed and jointly recorded in the Measurement Book. Rates "
        "shall hold for variation in quantity unless separately agreed in "
        "writing.", st["small"]))

    flow.append(PageBreak())
    flow.append(Paragraph("Annexure II &mdash; Terms and conditions", st["doctitle"]))
    flow.append(Spacer(1, 8))
    flow += _terms(doc, st)
    flow.append(Spacer(1, 10))
    flow.append(_signatures(doc, st))

    template.build(flow, canvasmaker=_numbered_canvas(meta))
    return buffer.getvalue()
