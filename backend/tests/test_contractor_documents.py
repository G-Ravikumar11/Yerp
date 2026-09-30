"""A document uploaded against the registration form is kept and can be read back."""
import base64

TINY_PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def registered(tenant, **form):
    body = {"company_name": "M/s Arathi Malik %s" % len(form), "pan": "AFVPF9080M"}
    body.update(form)
    res = tenant.post("/api/wo/contractors", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_an_uploaded_document_is_kept_and_read_back(tenant):
    con = registered(tenant, company_name="Rani Labour Contractors")
    res = tenant.put("/api/wo/contractors/%s" % con["id"], json={
        "company_name": "Rani Labour Contractors",
        "document_files": {"pan": {"name": "pan-card.png", "data": TINY_PNG}},
    })
    assert res.status_code == 200, res.text

    listed = next(c for c in tenant.get("/api/wo/contractors").json()["contractors"] if c["id"] == con["id"])
    assert listed["document_files"] == {"pan": "pan-card.png"}

    got = tenant.get("/api/wo/contractors/%s/documents/pan" % con["id"])
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert b"fake" in got.content


def test_a_document_that_is_not_there_is_a_clean_404(tenant):
    con = registered(tenant, company_name="No Documents Yet")
    res = tenant.get("/api/wo/contractors/%s/documents/gst" % con["id"])
    assert res.status_code == 404


def test_an_oversized_upload_is_refused(tenant):
    con = registered(tenant, company_name="Big File Co")
    huge = "data:image/png;base64," + ("A" * 7_000_001)
    res = tenant.put("/api/wo/contractors/%s" % con["id"], json={
        "company_name": "Big File Co",
        "document_files": {"pan": {"name": "big.png", "data": huge}},
    })
    assert res.status_code == 400


def test_a_garbage_pan_or_gstin_is_refused_at_registration(tenant):
    bad_pan = tenant.post("/api/wo/contractors", json={"company_name": "vvaa", "pan": "SDFGHJK%^&*"})
    assert bad_pan.status_code == 400
    bad_gst = tenant.post("/api/wo/contractors", json={"company_name": "vvaa", "gst_number": "!@#$%^&*()_123456789"})
    assert bad_gst.status_code == 400
    ok = tenant.post("/api/wo/contractors", json={"company_name": "vvaa", "gst_number": "36bnqpa8703a1za"})
    assert ok.status_code == 200, ok.text
    listed = next(c for c in tenant.get("/api/wo/contractors").json()["contractors"] if c["company_name"] == "vvaa")
    assert listed["pan"] == "BNQPA8703A", "the PAN is read out of the GSTIN"
