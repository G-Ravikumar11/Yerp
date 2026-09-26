"""Every workbook is also a PDF at the same address; the registers that had no
workbook now have one; and the field documents print in the ruled form."""
import io

import pytest

pypdf = pytest.importorskip("pypdf")

import main  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402


def text_of(res):
    assert res.status_code == 200, res.text[:300]
    assert res.headers["content-type"] == "application/pdf"
    return " ".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(res.content)).pages)


def test_every_workbook_has_a_pdf_twin():
    paths = {r.path for r in main.app.routes if isinstance(r, APIRoute)}
    missing = [p for p in paths if p.endswith(".xlsx") and "/api/sheets/" not in p
               and p[:-5] + ".pdf" not in paths]
    assert not missing, missing
    assert main.PDF_TWINS >= 30


def test_a_twin_draws_the_workbooks_own_rows(tenant):
    tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "RM", "item_name": "OPC 53 CEMENT", "units_of_measure": "Bags"}]})
    xlsx = tenant.get("/api/erp/items.xlsx")
    assert xlsx.status_code == 200
    text = text_of(tenant.get("/api/erp/items.pdf"))
    assert "OPC 53 CEMENT" in text


def test_the_registers_that_had_no_workbook_have_one(tenant):
    for path in ("/api/money/payables.xlsx", "/api/gst/inward.xlsx", "/api/registers/tds.xlsx",
                 "/api/registers/advances.xlsx", "/api/registers/guarantees.xlsx", "/api/money/entries.xlsx",
                 "/api/qc/inspections.xlsx", "/api/qc/cubes.xlsx", "/api/qc/ncrs.xlsx",
                 "/api/safety/incidents.xlsx", "/api/safety/permits.xlsx", "/api/safety/talks.xlsx"):
        res = tenant.get(path)
        assert res.status_code == 200, (path, res.text[:200])
        assert "spreadsheetml" in res.headers["content-type"], path
        assert tenant.get(path.replace(".xlsx", ".pdf")).status_code == 200, path


def test_the_field_documents_print(tenant):
    import main as m
    job = tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()
    inc = tenant.post("/api/safety/incidents", json={"job_id": job["id"], "kind": "Near miss",
                                                     "description": "Plank fell from level 3"}).json()["incident"]
    text = text_of(tenant.get("/api/safety/incidents/%d/document.pdf" % inc["id"]))
    assert "INCIDENT REPORT" in text and "Plank fell" in text
    from datetime import datetime, timedelta
    now = datetime.now()
    permit = tenant.post("/api/safety/permits", json={
        "job_id": job["id"], "kind": "Hot work", "location": "Tank roof", "receiver": "Welder Babu",
        "valid_from": now.strftime("%Y-%m-%d %H:%M"), "valid_to": (now + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M"),
        "precautions": [{"item": x, "done": True} for x in m.PERMIT_PRECAUTIONS["Hot work"]]}).json()["permit"]
    text = text_of(tenant.get("/api/safety/permits/%d/document.pdf" % permit["id"]))
    assert "PERMIT TO WORK" in text and "Welder Babu" in text and "PRECAUTIONS" in text
    ins = tenant.post("/api/qc/inspections", json={"job_id": job["id"], "checklist": next(iter(m.QC_CHECKLISTS)),
                                                   "location": "Raft"}).json()
    ins = ins.get("inspection", ins)
    text = text_of(tenant.get("/api/qc/inspections/%d/document.pdf" % ins["id"]))
    assert "INSPECTION REPORT" in text


def test_another_company_cannot_print_our_field_documents(tenant, second_tenant):
    job = tenant.post("/api/jobs", json={"name": "Site", "customer_name": "X"}).json()
    inc = tenant.post("/api/safety/incidents", json={"job_id": job["id"], "kind": "Near miss",
                                                     "description": "x"}).json()["incident"]
    assert second_tenant.get("/api/safety/incidents/%d/document.pdf" % inc["id"]).status_code == 404
