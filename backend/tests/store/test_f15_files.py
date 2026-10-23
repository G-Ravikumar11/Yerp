"""Photos and papers kept against store records, with the Store's own rights: added by someone who may create in that slice and works in that store,
refused for another company's record, and kept as evidence once the document is posted."""
import uuid
from datetime import date

from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82")


def _grn(t, central, w):
    po_id, po_line = w["pos"][0]
    return ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "lines": [{"po_line_id": po_line, "qty": "10", "uom": "bag"}]}))


def _upload(t, kind, rid, name="challan.png", data=PNG):
    return t.post("/api/files", data={"attached_type": kind, "attached_id": str(rid), "caption": "Delivery challan"}, files={"file": (name, data, "image/png")})


def test_a_challan_photo_is_kept_against_a_receipt_and_stays_after_posting(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    grn = _grn(t, central, w)
    res = _upload(t, "store_grn", grn["id"])
    assert res.status_code == 200, res.text
    fid = res.json()["file"]["id"]
    listed = ok(t.get("/api/files", params={"attached_type": "store_grn", "attached_id": grn["id"]}))
    assert [f["id"] for f in listed["files"]] == [fid] and listed["locked"] is False

    # A line of the receipt takes a certificate too.
    line = ok(t.get("/api/store/inward/grn/%d" % grn["id"]))["lines"][0]
    assert _upload(t, "store_grn_line", line["id"], "mill-cert.png").status_code == 200

    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    assert ok(t.get("/api/files", params={"attached_type": "store_grn", "attached_id": grn["id"]}))["locked"] is True
    assert t.get("/api/files/%d" % fid).status_code == 200


def test_unknown_or_foreign_records_are_refused(account, second_tenant):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    grn = _grn(t, central, w)
    assert _upload(t, "store_nothing", grn["id"]).status_code in (400, 404)
    assert _upload(t, "store_grn", 999999).status_code == 404
    assert _upload(second_tenant, "store_grn", grn["id"]).status_code in (403, 404)                  # another company's receipt


def test_a_rejection_and_a_tool_take_files(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id,
                                                    "lines": [{"po_line_id": po_line, "qty": "10", "uom": "bag", "rejected_qty": "2", "reject_reason": "Wet"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    [rej] = ok(t.get("/api/store/rejections"))["items"]
    assert _upload(t, "store_rejection", rej["id"], "wet-bags.png").status_code == 200
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "TOOL", "base_uom": "kg"}))
    tool = ok(t.post("/api/store/tools", json={"item_id": w["item"], "store_id": central["id"], "serial_no": "T-1"}))
    assert _upload(t, "store_tool", tool["id"], "service-sheet.png").status_code == 200
