"""Drawings and photos kept against a work order, stored as small as they
can be and found again by filtering.

A work order is issued with its drawings, and the gang's work is proved by
photographs. Both are kept against the order itself. A phone photo is made
smaller before it is stored, a drawing photographed on site keeps enough
pixels to be read, and a sheet attached to four orders is stored once.
"""
import io

from PIL import Image

from test_project_files import JPEG, PDF, job, upload
from test_subcontract_orders import priced
from test_measurement_and_ra_bills import placed_order


def picture(w=2800, h=1900, fmt="PNG"):
    """A large, noisy picture - the kind a phone camera produces."""
    import random
    rnd = random.Random(7)
    im = Image.new("RGB", (w, h))
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(w * h)])
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def test_a_subcontract_work_order_keeps_its_drawings_and_photos(tenant):
    order = priced(tenant)
    res = upload(tenant, "subcontract_order", order["id"], data=PDF, name="STR-101 R2.pdf",
                 ctype="application/pdf", kind="drawing", caption="Raft reinforcement")
    assert res.status_code == 200, res.text
    assert res.json()["file"]["kind"] == "drawing"
    assert res.json()["file"]["job_id"] == order["job_id"]
    upload(tenant, "subcontract_order", order["id"], name="gate.jpg")
    listed = tenant.get("/api/wo/orders").json()["orders"]
    mine = next(o for o in listed if o["id"] == order["id"])
    assert mine["files"] == {"files": 2, "drawings": 1, "photos": 1}


def test_a_client_work_order_keeps_them_too(tenant):
    wo = placed_order(tenant, qty=10, rate=100)
    res = upload(tenant, "work_order", wo["id"], data=PDF, name="GA.pdf", ctype="application/pdf", kind="drawing")
    assert res.status_code == 200, res.text
    row = next(w for w in tenant.get("/api/erp/work-orders").json()["work_orders"] if w["id"] == wo["id"])
    assert row["files"]["drawings"] == 1


def test_another_company_s_order_takes_nothing(tenant, second_tenant):
    order = priced(tenant)
    res = upload(second_tenant, "subcontract_order", order["id"])
    assert res.status_code == 404


def test_a_phone_photo_is_stored_small(tenant):
    order = priced(tenant)
    raw = picture()
    f = upload(tenant, "subcontract_order", order["id"], data=raw, name="IMG_2231.png", ctype="image/png").json()["file"]
    assert f["content_type"] == "image/jpeg" and f["name"] == "IMG_2231.jpg"
    assert f["size"] < len(raw) / 4
    stored = Image.open(io.BytesIO(tenant.get(f["url"]).content))
    assert max(stored.size) == 1600
    thumb = Image.open(io.BytesIO(tenant.get(f["thumb_url"]).content))
    assert max(thumb.size) <= 320


def test_a_photographed_drawing_keeps_enough_to_read(tenant):
    order = priced(tenant)
    f = upload(tenant, "subcontract_order", order["id"], data=picture(), name="sheet.png",
               ctype="image/png", kind="drawing").json()["file"]
    assert max(Image.open(io.BytesIO(tenant.get(f["url"]).content)).size) == 2400


def test_a_sheet_on_four_orders_is_stored_once(tenant):
    orders = [priced(tenant) for _ in range(3)]
    first = upload(tenant, "subcontract_order", orders[0]["id"], data=PDF, name="STR-101.pdf",
                   ctype="application/pdf", kind="drawing").json()["file"]
    others = [upload(tenant, "subcontract_order", o["id"], data=PDF, name="STR-101.pdf",
                     ctype="application/pdf", kind="drawing").json()["file"] for o in orders[1:]]
    for f in others:
        assert tenant.get(f["url"]).content == PDF
    listed = tenant.get("/api/files?attached_type=subcontract_order&kind=drawing").json()
    assert listed["summary"]["stored_bytes"] == len(PDF), "three orders, one copy"
    # Removing the copy the others read from hands it on; nothing is lost.
    assert tenant.delete("/api/files/%d" % first["id"]).status_code == 200
    for f in others:
        assert tenant.get(f["url"]).content == PDF
    # Added twice to one order, it is still stored once.
    again = upload(tenant, "subcontract_order", orders[1]["id"], data=PDF, name="copy.pdf", ctype="application/pdf")
    assert again.status_code == 200 and again.json()["file"]["size"] == len(PDF)
    listed = tenant.get("/api/files?attached_type=subcontract_order").json()
    assert listed["summary"]["stored_bytes"] == len(PDF)


def test_files_are_found_by_type_words_date_and_who(tenant):
    order = priced(tenant)
    oid = order["id"]
    upload(tenant, "subcontract_order", oid, data=PDF, name="STR-101.pdf", ctype="application/pdf",
           kind="drawing", caption="Raft reinforcement", taken_on="2026-09-01")
    upload(tenant, "subcontract_order", oid, name="pour.jpg", caption="Raft pour", taken_on="2026-09-10")
    upload(tenant, "subcontract_order", oid, data=JPEG + b"x", name="curing.jpg", caption="Curing", taken_on="2026-09-20")

    def names(**params):
        q = "&".join("%s=%s" % kv for kv in params.items())
        return sorted(f["name"] for f in tenant.get(
            "/api/files?attached_type=subcontract_order&attached_id=%d&%s" % (oid, q)).json()["files"])

    assert names(kind="drawing") == ["STR-101.pdf"]
    assert names(kind="photo") == ["curing.jpg", "pour.jpg"]
    assert names(q="raft") == ["STR-101.pdf", "pour.jpg"]
    assert names(date_from="2026-09-05", date_to="2026-09-15") == ["pour.jpg"]
    assert names(by="nobody") == []
    s = tenant.get("/api/files?attached_type=subcontract_order&attached_id=%d" % oid).json()["summary"]
    assert (s["count"], s["drawings"], s["photos"]) == (3, 1, 2)


def test_the_project_shows_what_came_from_its_work_orders(tenant):
    order = priced(tenant)
    upload(tenant, "subcontract_order", order["id"], data=PDF, name="STR-101.pdf", ctype="application/pdf", kind="drawing")
    upload(tenant, "job", order["job_id"], name="gate.jpg")
    everything = tenant.get("/api/jobs/%d/photos?kind=photo,drawing,document" % order["job_id"]).json()
    assert {p["of"] for p in everything["photos"]} == {"Work order %s" % order["wo_number"], "Project"}
    only_orders = tenant.get("/api/jobs/%d/photos?kind=photo,drawing,document&source=subcontract_order,work_order"
                             % order["job_id"]).json()["photos"]
    assert [p["name"] for p in only_orders] == ["STR-101.pdf"]
