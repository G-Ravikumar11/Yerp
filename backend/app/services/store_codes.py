"""Codes on a construction store's floor, and what scanning one finds.

Sand, aggregate and steel in the yard carry no label, so the codes go where the material is kept and on the paper that
moves it:
- a rack or yard-bay tag (a bin), whose QR reads BIN:<store code>:<bin code>;
- a rack label for an item, whose QR is the item code itself, so a handheld scanner reading it types the code;
- the maker's barcode printed on packaged goods (admixture cans, adhesive, paint, fittings, fasteners), kept on the
  item's store settings;
- the number of a store document - a gate pass at the gate, an issue or a goods receipt - printed as a QR on the form.
"""
import io

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.models.store_core import DBStore, DBStoreBin, DBStoreItemSettings
from app.models.store_inward import DBStoreGrn
from app.models.store_outward import DBStoreGatePass, DBStoreIssue

BIN_PREFIX = "BIN:"


def bin_tag(store, bin_row) -> str:
    return "%s%s:%s" % (BIN_PREFIX, store.code, bin_row.code)


def resolve(db, client_id, code, may_use_store):
    """What a scanned or typed code is: {"kind": "item"|"bin"|"document", ...}. `may_use_store(store_id)` says whether this
    person works in a store; a bin or document of a store they do not is refused. 404 when nothing has the code."""
    code = (code or "").strip()
    if not code:
        raise HTTPException(400, "Nothing was scanned.")
    if code.upper().startswith(BIN_PREFIX):
        store_code, _, bin_code = code[len(BIN_PREFIX):].partition(":")
        store = db.query(DBStore).filter(DBStore.client_id == client_id, func.lower(DBStore.code) == store_code.strip().lower()).first()
        bin_row = db.query(DBStoreBin).filter(DBStoreBin.store_id == store.id, func.lower(DBStoreBin.code) == bin_code.strip().lower()).first() if store else None
        if bin_row is None:
            raise HTTPException(404, "No bin %s in store %s." % (bin_code or "?", store_code or "?"))
        if not may_use_store(store.id):
            raise HTTPException(403, "Bin %s is in store %s, which you do not work in." % (bin_row.code, store.code))
        return {"kind": "bin", "store": {"id": store.id, "code": store.code, "name": store.name, "type": store.type, "project_id": store.project_id},
                "bin": {"id": bin_row.id, "code": bin_row.code}}
    item = (db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.kind == "RM", models.DBItem.is_active.is_(True),
                                           func.lower(models.DBItem.item_code) == code.lower()).first()
            or db.query(models.DBItem).join(DBStoreItemSettings, DBStoreItemSettings.item_id == models.DBItem.id).filter(
                models.DBItem.client_id == client_id, models.DBItem.kind == "RM", models.DBItem.is_active.is_(True),
                DBStoreItemSettings.barcode == code).first())
    if item is not None:
        return {"kind": "item", "item_id": item.id}
    for kind, model, path in (("gate-pass", DBStoreGatePass, "outward/gate-pass"), ("issue", DBStoreIssue, "outward/issue"), ("grn", DBStoreGrn, "inward/grn")):
        doc = db.query(model).filter(model.client_id == client_id, func.lower(model.number) == code.lower()).first()
        if doc is not None:
            if not may_use_store(doc.store_id):
                raise HTTPException(403, "%s belongs to a store you do not work in." % doc.number)
            return {"kind": "document", "doc": kind, "id": doc.id, "number": doc.number, "status": doc.status, "path": "/store/hub/%s/%d" % (path, doc.id)}
    raise HTTPException(404, "Nothing has the code %s - no item, maker's barcode, bin or store document. A maker's barcode is linked to its "
                             "item under Store Hub > Masters > Item settings." % code)


def check_barcode(db, client_id, item_id, barcode):
    """A maker's barcode names one item: refuse one already given to another."""
    if not barcode:
        return
    other = db.query(models.DBItem.item_code).join(DBStoreItemSettings, DBStoreItemSettings.item_id == models.DBItem.id).filter(
        models.DBItem.client_id == client_id, DBStoreItemSettings.barcode == barcode, models.DBItem.id != item_id).first()
    if other:
        raise HTTPException(409, "Barcode %s is already linked to item %s." % (barcode, other[0]))


def labels_pdf(title, labels):
    """A sheet of sticky labels, A4, three across and eight down (70 x 37 mm): each a QR with its code in large type and a
    line or two beneath. `labels` is [(qr text, big text, small text)]."""
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title)
    cols, rows, w, h = 3, 8, 70 * mm, 37 * mm
    left, top = (A4[0] - cols * w) / 2, A4[1] - (A4[1] - rows * h) / 2
    q = 31 * mm
    for n, (data, big, small) in enumerate(labels):
        if n and n % (cols * rows) == 0:
            c.showPage()
        slot = n % (cols * rows)
        x, y = left + (slot % cols) * w, top - (slot // cols + 1) * h
        c.setLineWidth(0.3)
        c.setStrokeGray(0.75)
        c.rect(x, y, w, h)
        widget = QrCodeWidget(data)
        b = widget.getBounds()
        d = Drawing(q, q, transform=[q / (b[2] - b[0]), 0, 0, q / (b[3] - b[1]), 0, 0])
        d.add(widget)
        renderPDF.draw(d, c, x + 3 * mm, y + (h - q) / 2)
        tx, room = x + q + 5 * mm, w - q - 7 * mm
        c.setFillGray(0)
        size = 13
        while size > 7 and c.stringWidth(big, "Helvetica-Bold", size) > room:
            size -= 1
        c.setFont("Helvetica-Bold", size)
        c.drawString(tx, y + h - 11 * mm, big)
        c.setFont("Helvetica", 7.5)
        line, lines = "", []
        for word in (small or "").split():
            if c.stringWidth((line + " " + word).strip(), "Helvetica", 7.5) > room:
                lines.append(line)
                line = word
            else:
                line = (line + " " + word).strip()
        lines.append(line)
        for i, text in enumerate([l for l in lines if l][:4]):
            c.drawString(tx, y + h - 17 * mm - i * 3.4 * mm, text)
    if not labels:
        c.setFont("Helvetica", 11)
        c.drawString(20 * mm, A4[1] - 30 * mm, "Nothing to label.")
    c.save()
    return buf.getvalue()
