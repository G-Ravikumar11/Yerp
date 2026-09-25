"""Site photos kept against what they prove, and the drawings register with
every revision kept and the one to build to plain."""
import io

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2048 + b"\xff\xd9"
PDF = b"%PDF-1.4\n" + b"0" * 4096 + b"\n%%EOF"


def job(tenant, name="Vanya City STP"):
    return tenant.post("/api/jobs", json={"name": name, "customer_name": "Arabtec"}).json()


def diary_day(tenant, j):
    res = tenant.post("/api/diary", json={"job_id": j["id"], "diary_date": "2026-09-20",
                                          "work_done": "Raft shuttering", "labour": [], "plant": []})
    assert res.status_code == 200, res.text
    body = res.json()
    return body.get("diary", body)


def upload(tenant, attached_type, attached_id, data=JPEG, name="site.jpg", ctype="image/jpeg", **form):
    files = {"file": (name, io.BytesIO(data), ctype)}
    body = {"attached_type": attached_type, "attached_id": str(attached_id)}
    body.update(form)
    return tenant.post("/api/files", files=files, data=body)


def test_a_photo_is_kept_against_the_diary_day(tenant):
    j = job(tenant)
    d = diary_day(tenant, j)
    res = upload(tenant, "diary", d["id"], caption="Trench flooded at 11am")
    assert res.status_code == 200, res.text
    f = res.json()["file"]
    assert f["kind"] == "photo" and f["job_id"] == j["id"] and f["is_image"]
    listed = tenant.get("/api/files?attached_type=diary&attached_id=%d" % d["id"]).json()["files"]
    assert [x["caption"] for x in listed] == ["Trench flooded at 11am"]
    got = tenant.get(f["url"])
    assert got.status_code == 200 and got.content == JPEG


def test_the_project_gallery_says_what_each_photo_was_of(tenant):
    j = job(tenant)
    d = diary_day(tenant, j)
    upload(tenant, "diary", d["id"])
    upload(tenant, "job", j["id"], name="gate.jpg")
    photos = tenant.get("/api/jobs/%d/photos" % j["id"]).json()["photos"]
    assert {p["of"] for p in photos} == {"Diary 2026-09-20", "Project"}


def test_a_photo_on_a_signed_off_day_stays(tenant):
    j = job(tenant)
    d = diary_day(tenant, j)
    f = upload(tenant, "diary", d["id"]).json()["file"]
    res = tenant.post("/api/diary/%d/submit" % d["id"], json={})
    if res.status_code != 200:
        res = tenant.post("/api/diary/%d/sign" % d["id"], json={})
    assert res.status_code == 200, res.text
    gone = tenant.delete("/api/files/%d" % f["id"])
    assert gone.status_code == 409 and "signed-off" in gone.json()["detail"]
    # and more can still be added to it
    assert upload(tenant, "diary", d["id"]).status_code == 200


def test_what_is_not_a_photo_or_a_drawing_is_refused(tenant):
    j = job(tenant)
    res = upload(tenant, "job", j["id"], data=b"MZ\x90", name="setup.exe", ctype="application/x-msdownload")
    assert res.status_code == 400


def test_the_register_keeps_every_revision_and_supersedes_the_old(tenant):
    j = job(tenant)
    d = tenant.post("/api/jobs/%d/drawings" % j["id"], json={"number": "str-101", "title": "Raft reinforcement",
                                                             "discipline": "Structural"}).json()["drawing"]
    assert d["number"] == "STR-101"
    r0 = tenant.post("/api/drawings/%d/revisions" % d["id"],
                     files={"file": ("STR-101-R0.pdf", io.BytesIO(PDF), "application/pdf")},
                     data={"revision": "R0", "status": "For approval", "received_from": "Consultant"})
    assert r0.status_code == 200, r0.text
    r1 = tenant.post("/api/drawings/%d/revisions" % d["id"],
                     files={"file": ("STR-101-R1.pdf", io.BytesIO(PDF + b"1"), "application/pdf")},
                     data={"revision": "R1", "status": "Good for construction"}).json()["drawing"]
    assert r1["current_revision"] == "R1" and r1["good_for_construction"]
    hist = {h["revision"]: h for h in r1["history"]}
    assert hist["R0"]["status"] == "Superseded" and hist["R1"]["current"]
    again = tenant.post("/api/drawings/%d/revisions" % d["id"],
                        files={"file": ("x.pdf", io.BytesIO(PDF), "application/pdf")}, data={"revision": "r1"})
    assert again.status_code == 409
    reg = tenant.get("/api/jobs/%d/drawings" % j["id"]).json()
    assert reg["summary"]["gfc"] == 1
    # an issued revision is not deleted out of the register
    assert tenant.delete("/api/files/%d" % hist["R1"]["file_id"]).status_code == 409


def test_one_drawing_number_once_per_project(tenant):
    j = job(tenant)
    tenant.post("/api/jobs/%d/drawings" % j["id"], json={"number": "ARC-01"})
    assert tenant.post("/api/jobs/%d/drawings" % j["id"], json={"number": "arc-01"}).status_code == 409


def test_another_tenant_cannot_see_the_files(tenant, second_tenant):
    j = job(tenant)
    f = upload(tenant, "job", j["id"]).json()["file"]
    assert second_tenant.get(f["url"]).status_code == 404
    assert upload(second_tenant, "job", j["id"]).status_code == 404
