"""A bill with hundreds of measurement lines prints quickly, and its sheet's heading comes at the top of each page - never in the
middle of one."""
import io
import time

import pytest

pypdf = pytest.importorskip("pypdf")

from conftest import fund_order
from test_subcontract_orders import draft


def test_a_long_measurement_sheet_keeps_its_heading_to_the_top_of_pages_and_prints_fast(tenant):
    order = draft(tenant, department="Civil")
    lines = [{"activity_no": "%d.0" % i, "item_description": "Item number %d finishing work" % i, "uom": "sqm",
              "quantity": 5000, "unit_rate": 100 + i} for i in range(1, 31)]
    order = fund_order(tenant, tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": lines}).json()["order"])
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    order = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).json()["order"]
    items = [l["item_id"] for l in tenant.get("/api/sub-mb/%d" % order["id"]).json()["lines"] if not l.get("is_header")]
    for n in range(120):
        res = tenant.post("/api/sub-mb/%d/entries" % order["id"], json={
            "item_id": items[n % len(items)], "location": "Block %d" % n, "multiplier": 2,
            "dimensions": [{"particulars": "L%d" % k, "nos": 2, "length": 3.5, "breadth": 1.2 + k} for k in range(5)]})
        assert res.status_code == 200, res.text
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    started = time.time()
    pdf = tenant.get("/api/sub-bills/%d/document.pdf" % bill["id"])
    assert pdf.status_code == 200
    assert time.time() - started < 20
    reader = pypdf.PdfReader(io.BytesIO(pdf.content))
    mb_pages = [p.extract_text() or "" for p in reader.pages if "Total Quantity for one Block" in (p.extract_text() or "")]
    assert len(mb_pages) >= 4
    for text in mb_pages:
        assert text.count("S.No") == 1, "the heading must be once on each page, at its top"
