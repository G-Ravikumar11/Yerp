"""Blocks checked in the grid are recorded together with the hold the sheet puts on them; books imported the old
way - the hold written as a line inside each block - are put right without changing what is billed."""
from test_delete_work_order import book, live_order


def line(tenant, order, item):
    return next(l for l in book(tenant, order["id"])["lines"] if l["item_id"] == item)


def setup(tenant):
    order = live_order(tenant, pay_advance=False)
    return order, book(tenant, order["id"])["lines"][0]["item_id"]


def dims(per_block):
    return [{"particulars": "Wall", "nos": 1, "length": per_block, "breadth": 1}]


def test_several_blocks_and_their_hold_go_in_together(tenant):
    order, item = setup(tenant)
    res = tenant.post("/api/sub-mb/%d/entries/batch" % order["id"], json={
        "item_id": item, "measured_on": "2026-11-10", "mb_ref": "Demo Bill / MB-1",
        "entries": [{"location": "Block B19", "multiplier": 2, "dimensions": dims(50), "group": "g4"},
                    {"location": "Block C26", "multiplier": 1, "dimensions": dims(40), "group": "g5"}],
        "holds": [{"group": "g4", "quantity": 55, "reason": "Release Putty 40% & Primer 10% - 55% held"}]})
    assert res.status_code == 200, res.text
    l = line(tenant, order, item)
    assert l["measured_to_date"] == 140 and l["held"] == 55 and l["unbilled"] == 85
    entries = book(tenant, order["id"])["entries"]
    hold = next(e for e in entries if e["kind"] == "hold")
    b19 = next(e for e in entries if e["location"] == "Block B19")
    assert hold["group_ref"] == b19["group_ref"] and hold["group_ref"].endswith("-g4")
    assert not any(str(d["particulars"]).startswith("Held back") for e in entries for d in e["dimensions"])


def test_the_batch_is_all_or_nothing(tenant):
    order, item = setup(tenant)
    ceiling = line(tenant, order, item)["max_quantity"]
    res = tenant.post("/api/sub-mb/%d/entries/batch" % order["id"], json={
        "item_id": item, "entries": [{"location": "A", "dimensions": dims(10)},
                                     {"location": "B", "dimensions": dims(ceiling)}]})
    assert res.status_code == 409 and "nothing was recorded" in res.json()["detail"]
    assert book(tenant, order["id"])["entries"] == []
    res = tenant.post("/api/sub-mb/%d/entries/batch" % order["id"], json={
        "item_id": item, "entries": [{"location": "A", "dimensions": dims(10)}],
        "holds": [{"group": "", "quantity": 50, "reason": "too much"}]})
    assert res.status_code == 409
    assert book(tenant, order["id"])["entries"] == []


def test_the_printed_bill_shows_the_blocks_as_measured_and_the_hold_once(tenant):
    import io
    import re
    import pypdf
    order, item = setup(tenant)
    tenant.post("/api/sub-mb/%d/entries/batch" % order["id"], json={
        "item_id": item, "entries": [{"location": "Block B19, B21, B23 & B24", "multiplier": 4, "dimensions": dims(25), "group": "g"}],
        "holds": [{"group": "g", "quantity": 55, "reason": "Release Putty Two coats - 40% & Primer - 10% - 55% held"}]})
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    pdf = tenant.get("/api/sub-bills/%d/document.pdf" % bill["id"])
    flat = re.sub(r"\s+", " ", " ".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(pdf.content)).pages))
    assert re.search(r"Total Quantity for one Block Total Quantity 25", flat)
    assert re.search(r"Total Quantity for 4 Blocks 100", flat), "four blocks print as measured"
    assert flat.count("Release Putty Two coats") == 1, "the hold prints once, under the group"
    assert re.search(r"Total Qty To be paid[^0-9]{0,30}45", flat)
    got = tenant.get("/api/sub-bills/%d" % bill["id"]).json()
    assert [l["this_bill_qty"] for l in (got.get("bill") or got)["lines"]] == [45]


def test_old_imports_are_put_right_without_changing_what_is_billed(tenant):
    order, item = setup(tenant)
    # the old way: the hold written as a line in each block, the block coming to the payable
    old = tenant.post("/api/sub-mb/%d/entries" % order["id"], json={
        "item_id": item, "multiplier": 2, "location": "Block B", "group_ref": "0-1",
        "dimensions": dims(100) + [{"particulars": "Held back for finishes and handing over (55% of 100)", "nos": 55, "deduct": True}]})
    assert old.status_code == 200, old.text
    before = line(tenant, order, item)
    assert before["measured_to_date"] == 90
    res = tenant.post("/api/sub-mb/convert-old-holds")
    assert res.status_code == 200 and res.json()["converted"] == 1, res.text
    after = line(tenant, order, item)
    assert after["measured_to_date"] == 200 and after["held"] == 110 and after["unbilled"] == before["unbilled"] == 90
    entries = book(tenant, order["id"])["entries"]
    block = next(e for e in entries if e["location"] == "Block B")
    assert not any(str(d["particulars"]).startswith("Held back") for d in block["dimensions"])
    hold = next(e for e in entries if e["kind"] == "hold")
    assert hold["group_ref"] == block["group_ref"] and "55%" in hold["remarks"]
    # a second run finds nothing to do
    assert tenant.post("/api/sub-mb/convert-old-holds").json()["converted"] == 0


def test_an_old_import_on_a_sent_bill_is_left_as_it_was(tenant):
    order, item = setup(tenant)
    tenant.post("/api/sub-mb/%d/entries" % order["id"], json={
        "item_id": item, "location": "Block S", "dimensions": dims(100) + [
            {"particulars": "Held back for finishes and handing over (10% of 100)", "nos": 10, "deduct": True}]})
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    out = tenant.post("/api/sub-mb/convert-old-holds").json()
    assert out["converted"] == 0 and bill["number"] in out["left_on_sent_bills"]
    assert line(tenant, order, item)["measured_to_date"] == 90


def test_a_measurement_cannot_be_changed_below_what_is_held_on_it(tenant):
    order, item = setup(tenant)
    tenant.post("/api/sub-mb/%d/entries/batch" % order["id"], json={
        "item_id": item, "entries": [{"location": "A", "dimensions": dims(100), "group": "g"}],
        "holds": [{"group": "g", "quantity": 60, "reason": "held"}]})
    entry = next(e for e in book(tenant, order["id"])["entries"] if not e["kind"])
    res = tenant.put("/api/sub-mb/entries/%d" % entry["id"], json={"item_id": item, "dimensions": dims(40)})
    assert res.status_code == 409 and "held back" in res.json()["detail"]
    assert tenant.put("/api/sub-mb/entries/%d" % entry["id"], json={"item_id": item, "dimensions": dims(80)}).status_code == 200


def test_clearing_entries_with_their_hold_works_in_any_order(tenant):
    order, item = setup(tenant)
    tenant.post("/api/sub-mb/%d/entries/batch" % order["id"], json={
        "item_id": item, "entries": [{"location": "A", "dimensions": dims(100), "group": "g"}],
        "holds": [{"group": "g", "quantity": 60, "reason": "held"}]})
    ids = [e["id"] for e in sorted(book(tenant, order["id"])["entries"], key=lambda e: e["kind"] or "")]   # the measurement first
    out = tenant.post("/api/sub-mb/entries/bulk-delete", json={"ids": ids}).json()
    assert out["deleted"] == 2 and not out["failed"], out


def test_only_billing_staff_and_the_master_record_a_hold_with_the_blocks(tenant, portal):
    from test_sub_contractor_certificate import share, sign_in, staff
    order, item = setup(tenant)
    site = staff(tenant, "staff")
    share(tenant, order, site)
    sign_in(portal, site)
    body = {"item_id": item, "entries": [{"location": "A", "dimensions": dims(100), "group": "g"}]}
    refused = portal.post("/api/sub-mb/%d/entries/batch" % order["id"], json=dict(body, holds=[{"group": "g", "quantity": 10, "reason": "held"}]))
    assert refused.status_code in (401, 403), refused.text
    assert book(tenant, order["id"])["entries"] == []
    assert portal.post("/api/sub-mb/%d/entries/batch" % order["id"], json=body).status_code == 200


def test_deleting_contractor_measurements_leaves_client_measurement_photos_alone(tenant):
    import database
    import models
    order, item = setup(tenant)
    tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": 5})
    entry = book(tenant, order["id"])["entries"][0]
    cid = tenant.get("/api/client/me").json()["id"]
    with database.SessionLocal() as db:
        db.add(models.DBFile(client_id=cid, kind="photo", attached_type="measurement", attached_id=entry["id"],
                             name="client.jpg", content_type="image/jpeg", size=3, data=b"abc"))
        db.commit()
    assert tenant.delete("/api/sub-mb/entries/%d" % entry["id"]).status_code == 200
    with database.SessionLocal() as db:
        assert db.query(models.DBFile).filter(models.DBFile.attached_type == "measurement",
                                              models.DBFile.attached_id == entry["id"]).count() == 1
