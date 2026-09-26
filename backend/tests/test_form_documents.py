"""Documents in the trade's ruled form: the work order and the RA bill, with
the company's own signatories in the signature row."""
import io

import pytest

pypdf = pytest.importorskip("pypdf")

from test_subcontractor_bills import live_order  # noqa: E402
from test_measurement_and_ra_bills import placed_order, measure, line_of, raise_bill  # noqa: E402


def pdf_text(res):
    assert res.status_code == 200, res.text[:300]
    assert res.headers["content-type"] == "application/pdf"
    reader = pypdf.PdfReader(io.BytesIO(res.content))
    return len(reader.pages), " ".join((p.extract_text() or "") for p in reader.pages)


def test_the_work_order_prints_in_the_ruled_form_with_its_conditions(tenant):
    order = live_order(tenant, retention_percent=5)
    pages, text = pdf_text(tenant.get("/api/wo/orders/%d/document.pdf" % order["id"]))
    assert pages >= 2
    for words in ("WORK ORDER", "Sub Contractor Name", "TOTAL AMOUNT", "TAXES AND DUTIES",
                  "Payment Terms", "FSD (Retention)", "GENERAL CONTRACT CONDITIONS", "Authorized Signatory",
                  order["wo_number"]):
        assert words in text, words
    assert "₹" not in text, "the rupee sign does not print in the built-in font"


def test_the_old_letter_layout_is_still_there(tenant):
    order = live_order(tenant)
    pages, text = pdf_text(tenant.get("/api/wo/orders/%d/document.pdf?style=letter" % order["id"]))
    assert "Annexure" in text


def test_the_signatories_set_in_settings_sign_the_documents(tenant):
    res = tenant.put("/api/documents/signatories", json={
        "prepared": {"name": "S Bhaskara Rao", "title": "QS"},
        "authorised": {"name": "G Ravi Kumar", "title": "Director"}})
    assert res.status_code == 200, res.text
    assert res.json()["signatories"]["prepared"]["name"] == "S Bhaskara Rao"
    order = live_order(tenant)
    _, text = pdf_text(tenant.get("/api/wo/orders/%d/document.pdf" % order["id"]))
    assert "S Bhaskara Rao" in text and "G Ravi Kumar" in text


def test_the_ra_bill_prints_in_the_same_form(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 1000)
    bill = raise_bill(tenant, wo["id"], retention_percent=5, tax_percent=18, tds_percent=1).json()["bill"]
    pages, text = pdf_text(tenant.get("/api/ra-bills/%d/document.pdf" % bill["id"]))
    for words in ("RA BILL", "Bill To", "VALUE OF WORK IN THIS BILL", "retention @ 5%", "NET AMOUNT PAYABLE",
                  "1,11,100.00", "DRAFT"):
        assert words in text, words


def test_another_company_cannot_print_ours(tenant, second_tenant):
    order = live_order(tenant)
    assert second_tenant.get("/api/wo/orders/%d/document.pdf" % order["id"]).status_code == 404
