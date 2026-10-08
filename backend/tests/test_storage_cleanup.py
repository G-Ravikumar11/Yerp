"""Removing a file is quick and does not read it; the owner can see what is taking space and clear what is no use."""
from datetime import datetime, timedelta

from app import db as database
from app import models
from test_project_files import JPEG, PDF, diary_day, job, upload


def test_removing_a_file_never_reads_its_bytes(tenant):
    from sqlalchemy import event
    j = job(tenant)
    f = upload(tenant, "job", j["id"], data=PDF, name="plan.pdf", ctype="application/pdf").json()["file"]
    seen = []

    def watch(conn, cur, stmt, *a, **k):
        seen.append(stmt)
    event.listen(database.engine, "before_cursor_execute", watch)
    try:
        assert tenant.delete("/api/files/%d" % f["id"]).status_code == 200
    finally:
        event.remove(database.engine, "before_cursor_execute", watch)
    selects = [s for s in seen if s.lstrip().upper().startswith("SELECT") and "project_files" in s]
    assert selects and not any("project_files.data" in s for s in selects), selects


def test_the_same_file_kept_twice_survives_removing_the_first(tenant):
    j = job(tenant)
    a = upload(tenant, "job", j["id"], data=PDF, name="plan.pdf", ctype="application/pdf").json()["file"]
    d = diary_day(tenant, j)
    b = upload(tenant, "diary", d["id"], data=PDF, name="plan-again.pdf", ctype="application/pdf").json()["file"]
    listed = {x["id"]: x for x in tenant.get("/api/files").json()["files"]}
    assert listed[b["id"]]["shared"] is True
    assert tenant.delete("/api/files/%d" % a["id"]).status_code == 200
    got = tenant.get("/api/files/%d" % b["id"])
    assert got.status_code == 200 and got.content == PDF


def test_the_thumbnail_of_a_photo_still_comes(tenant):
    j = job(tenant)
    f = upload(tenant, "job", j["id"]).json()["file"]
    assert tenant.get(f["thumb_url"]).status_code == 200


def orphan(tenant, kind="diary"):
    """A file kept against a record that has since been deleted."""
    cid = tenant.get("/api/client/me").json()["id"]
    with database.SessionLocal() as db:
        row = models.DBFile(client_id=cid, kind="photo", attached_type=kind, attached_id=987654, name="lost.jpg",
                            content_type="image/jpeg", size=5000, data=b"x" * 5000)
        db.add(row)
        db.commit()
        return row.id


def test_the_owner_sees_and_clears_files_whose_record_is_gone(tenant):
    j = job(tenant)
    live = upload(tenant, "job", j["id"]).json()["file"]
    lost = orphan(tenant)
    report = tenant.get("/api/storage").json()
    entry = next(c for c in report["clean"] if c["key"] == "orphan_files")
    assert entry["count"] == 1 and entry["bytes"] == 5000
    res = tenant.post("/api/storage/clean", json={"keys": ["orphan_files"]})
    assert res.status_code == 200 and res.json()["removed"]["orphan_files"] == 1
    assert tenant.get("/api/files/%d" % lost).status_code == 404
    assert tenant.get("/api/files/%d" % live["id"]).status_code == 200            # what belongs to a live record stays
    assert next(c for c in tenant.get("/api/storage").json()["clean"] if c["key"] == "orphan_files")["count"] == 0


def test_a_file_a_living_one_reads_from_is_not_cleared_with_its_orphaned_origin(tenant):
    cid = tenant.get("/api/client/me").json()["id"]
    j = job(tenant)
    with database.SessionLocal() as db:
        origin = models.DBFile(client_id=cid, kind="photo", attached_type="diary", attached_id=987654, name="o.jpg",
                               content_type="image/jpeg", size=3000, data=b"y" * 3000)
        db.add(origin)
        db.flush()
        reader = models.DBFile(client_id=cid, job_id=j["id"], kind="photo", attached_type="job", attached_id=j["id"],
                               name="r.jpg", content_type="image/jpeg", size=3000, blob_of=origin.id)
        db.add(reader)
        db.commit()
        origin_id, reader_id = origin.id, reader.id
    tenant.post("/api/storage/clean", json={"keys": ["orphan_files"]})
    assert tenant.get("/api/files/%d" % reader_id).content == b"y" * 3000
    assert origin_id


def test_old_alerts_are_cleared_recent_ones_are_kept(tenant):
    cid = tenant.get("/api/client/me").json()["id"]
    old = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S")
    with database.SessionLocal() as db:
        db.add(models.DBAlert(client_id=cid, kind="x", title="old", created_at=old))
        db.add(models.DBAlert(client_id=cid, kind="x", title="new"))
        db.commit()
    assert next(c for c in tenant.get("/api/storage").json()["clean"] if c["key"] == "old_alerts")["count"] == 1
    tenant.post("/api/storage/clean", json={"keys": ["old_alerts"]})
    with database.SessionLocal() as db:
        titles = {a.title for a in db.query(models.DBAlert).filter(models.DBAlert.client_id == cid).all()}
    assert "new" in titles and "old" not in titles


def test_only_the_owner_can_see_or_clear_storage(tenant, portal):
    from test_sub_contractor_certificate import staff, sign_in
    emp = staff(tenant, "project_manager")
    sign_in(portal, emp)
    assert portal.get("/api/storage").status_code in (401, 403)
    assert portal.post("/api/storage/clean", json={"keys": ["orphan_files"]}).status_code in (401, 403)
