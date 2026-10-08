"""Storing, serving and removing attached files and photos."""
import hashlib
import io
import os
import re

from fastapi import HTTPException
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import defer

from app import models


# The application form is public, so uploads are the one place an anonymous
# visitor can put bytes in the database. Everything is bounded.
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024      # 5 MB per file

ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/png", "image/jpeg", "image/webp",
    "text/plain",
}
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".txt"}


def decoded_size(data_uri_or_b64: str) -> int:
    """Byte size of a base64 payload without materialising it."""
    if not data_uri_or_b64:
        return 0
    raw = data_uri_or_b64.split(",", 1)[-1]
    padding = raw[-2:].count("=") if len(raw) >= 2 else 0
    return max(0, (len(raw) * 3) // 4 - padding)


def drop_files_of(db, attached_type, ids):
    """Photos, drawings and documents kept against these records - and the drawing revisions that point at them."""
    ids = list(ids)
    if not ids:
        return
    file_ids = [x.id for x in db.query(models.DBFile.id).filter(
        models.DBFile.attached_type == attached_type, models.DBFile.attached_id.in_(ids)).all()]
    if file_ids:
        sweep_referrers(db, {"project_files": file_ids})
        db.query(models.DBFile).filter(models.DBFile.id.in_(file_ids)).delete(synchronize_session=False)


# PROJECT FILES: SITE PHOTOS AND THE DRAWINGS REGISTER
#
# A measurement is argued over with a photograph, a variation with the drawing
# it came from, a rained-off day with a picture of the flooded trench. They
# are kept against the record they prove - the diary day, the measurement,
# the variation - and in the project's drawings register, where every
# revision is kept and the one to build to is always plain.
FILE_MAX_BYTES = 15 * 1024 * 1024
FILE_IMAGE_IN_MAX_BYTES = 40 * 1024 * 1024      # a photo as the camera took it, before it is made smaller
INLINE_SAFE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf")


def served_type(content_type):
    """The type a stored file is served as. A file that says it is a page or a vector picture (which can carry
    a script) is served as plain bytes, so opening it can never run anything in the app."""
    c = (content_type or "").split(";")[0].strip().lower()
    return c if c in INLINE_SAFE_TYPES else "application/octet-stream"


def file_headers(media):
    h = {"X-Content-Type-Options": "nosniff"}
    if media != "application/pdf":
        h["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return h


FILE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf",
              "image/vnd.dwg", "application/acad", "application/dxf", "image/vnd.dxf",
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "application/octet-stream")
FILE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".dwg", ".dxf", ".xlsx", ".docx")


def file_dict(f):
    return {"id": f.id, "job_id": f.job_id, "kind": f.kind, "attached_type": f.attached_type,
            "attached_id": f.attached_id, "name": f.name or "", "content_type": f.content_type or "",
            "size": f.size or 0, "caption": f.caption or "", "taken_on": f.taken_on or "",
            "uploaded_by_name": f.uploaded_by_name or "", "created_at": f.created_at or "",
            "is_image": (f.content_type or "").startswith("image/"),
            "url": "/api/files/%d" % f.id,
            "thumb_url": "/api/files/%d/thumb" % f.id if f.thumb or (f.content_type or "").startswith("image/") else ""}


def attachment_target(db, client_id, attached_type, attached_id):
    """(job_id, locked) for what a file is being kept against - refused if
    it is not this company's."""
    t = attached_type or "job"
    if t == "job":
        job = job_or_404(db, client_id, attached_id)
        return job.id, False
    if t == "diary":
        d = db.query(models.DBSiteDiary).filter(models.DBSiteDiary.id == attached_id,
                                                models.DBSiteDiary.client_id == client_id).first()
        if not d:
            raise HTTPException(404, "Diary day not found")
        return d.job_id, (d.status or "") != "DRAFT"
    if t == "measurement":
        m = db.query(models.DBMeasurement).filter(models.DBMeasurement.id == attached_id,
                                                  models.DBMeasurement.client_id == client_id).first()
        if not m:
            raise HTTPException(404, "Measurement not found")
        wo = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id == m.work_order_id).first()
        return (wo.job_id if wo else None), False
    if t == "variation":
        v = db.query(models.DBVariationOrder).filter(models.DBVariationOrder.id == attached_id,
                                                     models.DBVariationOrder.client_id == client_id).first()
        if not v:
            raise HTTPException(404, "Variation not found")
        return v.job_id, False
    if t == "inspection":
        i = db.query(models.DBInspection).filter(models.DBInspection.id == attached_id,
                                                 models.DBInspection.client_id == client_id).first()
        if not i:
            raise HTTPException(404, "Inspection not found")
        return i.job_id, False
    if t == "incident":
        x = db.query(models.DBSafetyIncident).filter(models.DBSafetyIncident.id == attached_id,
                                                     models.DBSafetyIncident.client_id == client_id).first()
        if not x:
            raise HTTPException(404, "Incident not found")
        return x.job_id, False
    if t == "ncr":
        n = db.query(models.DBNcr).filter(models.DBNcr.id == attached_id,
                                          models.DBNcr.client_id == client_id).first()
        if not n:
            raise HTTPException(404, "NCR not found")
        return n.job_id, False
    if t == "drawing":
        d = db.query(models.DBDrawing).filter(models.DBDrawing.id == attached_id,
                                              models.DBDrawing.client_id == client_id).first()
        if not d:
            raise HTTPException(404, "Drawing not found")
        return d.job_id, False
    if t == "thread":
        th = db.query(models.DBProjectThread).filter(models.DBProjectThread.id == attached_id,
                                                     models.DBProjectThread.client_id == client_id).first()
        if not th:
            raise HTTPException(404, "Thread not found")
        return th.job_id, False
    if t == "bill":
        b = db.query(models.DBBill).filter(models.DBBill.id == attached_id,
                                           models.DBBill.client_id == client_id).first()
        if not b:
            raise HTTPException(404, "Bill not found")
        return b.job_id, (b.status or "") not in ("Draft",)
    if t == "subcontract_order":
        o = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == attached_id,
                                                       models.DBSubcontractOrder.client_id == client_id).first()
        if not o:
            raise HTTPException(404, "Work order not found")
        return o.job_id, False
    if t == "work_order":
        w = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id == attached_id,
                                                models.DBWorkOrder.client_id == client_id).first()
        if not w:
            raise HTTPException(404, "Work order not found")
        return w.job_id, False
    raise HTTPException(400, "Files are kept against a project, a work order, a diary day, a measurement, "
                             "a variation, a drawing, an inspection or an NCR.")


# How far a picture is made smaller. A site photo reads at 1600 pixels; a
# photographed or scanned drawing keeps more, so its dimensions stay legible.
SLIM_PHOTO_PX, SLIM_PHOTO_QUALITY = 1600, 72
SLIM_DRAWING_PX, SLIM_DRAWING_QUALITY = 2400, 80
THUMB_PX, THUMB_QUALITY = 320, 60


def slim_image(data, ctype, kind):
    """A photo made as small as it can be and still do its job: turned the
    right way up, the camera's metadata dropped, at most 1600 pixels on its
    long side (2400 for a drawing) as a JPEG - kept only when that is smaller
    than what came in. Returns (data, content_type, thumbnail)."""
    if ctype not in ("image/jpeg", "image/png", "image/webp"):
        return data, ctype, None
    try:
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.split()[-1])
            im = flat
        else:
            im = im.convert("RGB")
        # A drawing or a document (a scanned invoice) has to stay legible.
        px, quality = (SLIM_DRAWING_PX, SLIM_DRAWING_QUALITY) if kind in ("drawing", "document") \
            else (SLIM_PHOTO_PX, SLIM_PHOTO_QUALITY)
        big = im.copy()
        big.thumbnail((px, px))
        out = io.BytesIO()
        big.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
        small = im.copy()
        small.thumbnail((THUMB_PX, THUMB_PX))
        t = io.BytesIO()
        small.save(t, "JPEG", quality=THUMB_QUALITY, optimize=True)
        slim = out.getvalue()
        if len(slim) < len(data):
            return slim, "image/jpeg", t.getvalue()
        return data, ctype, t.getvalue()
    except Exception:
        return data, ctype, None


def file_bytes(db, f, thumb=False):
    """A file's bytes - its own, or those of the copy it shares."""
    own = f.thumb if thumb else f.data
    if own or not getattr(f, "blob_of", None):
        return own
    origin = db.query(models.DBFile).filter(models.DBFile.id == f.blob_of).first()
    return (origin.thumb if thumb else origin.data) if origin else None


def store_file(db, client_id, upload, data, *, job_id, attached_type, attached_id, kind,
               caption="", taken_on="", by="", thumb=None):
    name = (upload.filename or "file").strip()[:200]
    ctype = (upload.content_type or "application/octet-stream").lower()
    ext = os.path.splitext(name.lower())[1]
    if any(w in ctype for w in ("svg", "html", "xml", "javascript")) or ext in (".svg", ".html", ".htm", ".xml", ".js"):
        raise HTTPException(400, "A photo, a PDF, a drawing (DWG/DXF) or an Excel or Word file.")
    if ctype not in FILE_TYPES and ext not in FILE_EXTENSIONS:
        raise HTTPException(400, "A photo, a PDF, a drawing (DWG/DXF) or an Excel or Word file.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    original = len(data)
    # A camera's original may be large; it is made smaller first, and the
    # limit is on what is kept.
    if ctype.startswith("image/") and original <= FILE_IMAGE_IN_MAX_BYTES:
        data, ctype, made_thumb = slim_image(data, ctype, kind)
    else:
        made_thumb = None
    if len(data) > FILE_MAX_BYTES:
        raise HTTPException(413, "That file is over 15 MB. Save the drawing as a PDF, or send the "
                                 "photo from the camera - it is made smaller on the way up.")
    if ctype == "image/jpeg" and ext not in (".jpg", ".jpeg"):
        name = (os.path.splitext(name)[0] or "photo")[:195] + ".jpg"
    thumb = made_thumb or thumb
    sha = hashlib.sha256(data).hexdigest()
    same = db.query(models.DBFile.id).filter(models.DBFile.client_id == client_id, models.DBFile.sha256 == sha,
                                             models.DBFile.blob_of.is_(None)).first()
    f = models.DBFile(client_id=client_id, job_id=job_id, kind=kind, attached_type=attached_type,
                      attached_id=attached_id, name=name, content_type=ctype, size=len(data),
                      original_size=original, sha256=sha,
                      # Kept once: a second record holding the same file reads the first one's bytes.
                      data=None if same is not None else data,
                      blob_of=same[0] if same is not None else None,
                      thumb=None if same is not None else (thumb if thumb and len(thumb) < 400 * 1024 else None),
                      caption=(caption or "").strip()[:300], taken_on=(taken_on or "")[:10],
                      uploaded_by_name=by)
    db.add(f)
    db.flush()
    return f


def file_counts(db, client_id, attached_type, ids):
    """How many drawings and photos each record holds, in one query."""
    if not ids:
        return {}
    out = {}
    for aid, kind, n in db.query(models.DBFile.attached_id, models.DBFile.kind, sqlfunc.count(models.DBFile.id)).filter(
            models.DBFile.client_id == client_id, models.DBFile.attached_type == attached_type,
            models.DBFile.attached_id.in_(ids)).group_by(models.DBFile.attached_id, models.DBFile.kind).all():
        c = out.setdefault(aid, {"files": 0, "drawings": 0, "photos": 0})
        c["files"] += n
        if kind == "drawing":
            c["drawings"] += n
        elif kind == "photo":
            c["photos"] += n
    return out


def _file_or_404(db, client_id, fid, bytes_too=False):
    """A file's row. Its bytes - up to 15 MB, and its picture copy - are left on the database unless asked for:
    most things done to a file (removing it, listing it) never need them, and each one was fetched over the
    network for nothing."""
    q = db.query(models.DBFile).filter(models.DBFile.id == fid, models.DBFile.client_id == client_id)
    if not bytes_too:
        q = q.options(defer(models.DBFile.data), defer(models.DBFile.thumb))
    f = q.first()
    if not f:
        raise HTTPException(404, "File not found")
    return f


IMAGE_LIMIT = 900_000       # characters of data URL: a logo or a signature, not a photograph


def image_data_url(value, label, limit=IMAGE_LIMIT):
    """A PNG or JPEG carried in the page, or nothing. Only an image that
    travels with the document is printed (see wo_pdf._logo)."""
    value = (value or "").strip()
    if not value:
        return ""
    if not re.match(r"^data:image/(png|jpe?g);base64,[A-Za-z0-9+/=\s]+$", value[:80] + "="):
        raise HTTPException(400, "%s has to be a PNG or JPEG picture." % label)
    if len(value) > limit:
        raise HTTPException(400, "%s picture is too large. Use one under about 600 KB." % label)
    return value


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.projects import job_or_404
from app.services.subcontract_orders import sweep_referrers
