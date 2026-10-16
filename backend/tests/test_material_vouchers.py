"""Store > Material Issue Voucher: the printed voucher kept field for field, numbered in sequence, printable and
downloadable as a register."""


def _job(tenant):
    return tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()


def _voucher(tenant, job, **over):
    body = {"job_id": job["id"], "voucher_on": "2026-10-16", "indented_by": "Ravi (site engineer)", "issued_by": "Store - Suresh",
            "issued_for": "Block A slab", "lines": [
                {"description": "Cement OPC 53", "uom": "Bag", "issued_qty": 50, "returned_qty": 2, "remarks": "2 bags back damp"},
                {"description": "TMT 12 mm", "uom": "MT", "issued_qty": 1.5, "returned_qty": 0, "remarks": ""}]}
    body.update(over)
    return tenant.post("/api/material-vouchers", json=body)


def test_vouchers_are_kept_in_sequence_with_every_field(tenant):
    j = _job(tenant)
    first = _voucher(tenant, j)
    assert first.status_code == 200, first.text
    second = _voucher(tenant, j, issued_for="Block B footing")
    assert (first.json()["voucher"]["number"], second.json()["voucher"]["number"]) == (1, 2)
    listed = tenant.get("/api/material-vouchers?job_id=%d" % j["id"]).json()
    assert [v["number"] for v in listed["vouchers"]] == [1, 2] and listed["summary"]["lines"] == 4
    v = listed["vouchers"][0]
    assert (v["indented_by"], v["issued_by"], v["issued_for"], v["voucher_on"]) == (
        "Ravi (site engineer)", "Store - Suresh", "Block A slab", "2026-10-16")
    assert v["lines"][0] == {"description": "Cement OPC 53", "uom": "Bag", "issued_qty": 50, "returned_qty": 2,
                             "remarks": "2 bags back damp"}
    assert v["project"].endswith("Vanya City STP")


def test_a_voucher_needs_an_item_and_cannot_return_more_than_issued(tenant):
    j = _job(tenant)
    assert _voucher(tenant, j, lines=[]).status_code == 400
    assert _voucher(tenant, j, lines=[{"description": "Sand", "uom": "Cum", "issued_qty": 0}]).status_code == 400
    assert _voucher(tenant, j, lines=[{"description": "Sand", "uom": "Cum", "issued_qty": 5, "returned_qty": 6}]).status_code == 400


def test_each_voucher_prints_and_the_register_downloads(tenant):
    j = _job(tenant)
    vid = _voucher(tenant, j).json()["voucher"]["id"]
    pdf = tenant.get("/api/material-vouchers/%d/document.pdf" % vid)
    assert pdf.status_code in (200, 503)               # 503 only where the PDF library is not installed
    if pdf.status_code == 200:
        assert pdf.content[:4] == b"%PDF"
    sheet = tenant.get("/api/material-vouchers.xlsx?job_id=%d" % j["id"])
    assert sheet.status_code == 200 and sheet.content[:2] == b"PK"   # an Excel workbook


def test_a_removed_voucher_never_gives_its_sl_no_again(tenant):
    j = _job(tenant)
    first = _voucher(tenant, j).json()["voucher"]
    second = _voucher(tenant, j).json()["voucher"]
    assert tenant.delete("/api/material-vouchers/%d" % second["id"]).status_code == 200
    third = _voucher(tenant, j).json()["voucher"]
    assert (first["number"], third["number"]) == (1, 3)
    assert [v["number"] for v in tenant.get("/api/material-vouchers").json()["vouchers"]] == [1, 3]
