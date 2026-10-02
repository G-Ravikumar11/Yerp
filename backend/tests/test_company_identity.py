"""One company identity heads everything: every PDF, every Excel export, and the app asks what is missing."""
import io

import pytest

pypdf = pytest.importorskip("pypdf")
openpyxl = pytest.importorskip("openpyxl")

from test_letterhead_and_signing import an_order, pdf_of, pictures, png, text
from test_delete_work_order import live_order, raise_a_bill


def with_letterhead(tenant):
    order, unit, con = an_order(tenant)
    tenant.put("/api/wo/business-units/%d" % unit["id"], json={
        "name": "Yalavarti Projects Pvt Ltd", "code": "YPPL", "gstin": "36AABCY1234H1ZX",
        "address": "Plot 12, Madhapur\nHyderabad 500081", "logo_url": png()})
    return order, con


def images(res):
    book = openpyxl.load_workbook(io.BytesIO(res.content))
    return [len(ws._images) for ws in book.worksheets], book


def test_the_app_says_what_company_details_are_still_missing(tenant):
    ident = tenant.get("/api/company/identity")
    assert ident.status_code == 200
    assert "logo" in ident.json()["missing"]
    with_letterhead(tenant)
    now = tenant.get("/api/company/identity").json()
    assert now["name"] == "Yalavarti Projects Pvt Ltd" and now["logo_url"].startswith("data:image")
    assert "logo" not in now["missing"] and "GSTIN" not in now["missing"] and "PAN" not in now["missing"]


def test_the_gang_bill_and_the_registration_form_carry_the_logo_in_pdf_and_excel(tenant):
    order = live_order(tenant, pay_advance=False)
    unit = tenant.get("/api/wo/business-units").json()["business_units"][0]
    tenant.put("/api/wo/business-units/%d" % unit["id"], json={
        "name": "Yalavarti Projects Pvt Ltd", "gstin": "36AABCY1234H1ZX", "address": "Plot 12, Madhapur", "logo_url": png()})
    con = {"id": order["contractor_id"]}
    bill = raise_a_bill(tenant, order)
    pdf = pdf_of(tenant.get("/api/sub-bills/%d/document.pdf" % bill["id"]))
    assert all(pictures(pdf, n) >= 1 for n in range(min(3, len(pdf.pages))))      # Top Sheet, AB-1, MB-1
    assert "36AABCY1234H1ZX" in text(pdf)
    xl, _ = images(tenant.get("/api/sub-bills/%d/export.xlsx" % bill["id"]))
    assert xl and all(n >= 1 for n in xl)
    reg = pdf_of(tenant.get("/api/wo/contractors/%d/registration.pdf" % con["id"]))
    assert pictures(reg) >= 1
    rx, _ = images(tenant.get("/api/wo/contractors/%d/registration.xlsx" % con["id"]))
    assert rx[0] >= 1


def test_a_register_in_excel_is_headed_with_the_company_but_a_template_is_not(tenant):
    order, _ = with_letterhead(tenant)
    res = tenant.get("/api/wo/orders.xlsx")
    n, book = images(res)
    ws = book.worksheets[0]
    assert n[0] == 1
    assert ws["A1"].value == "YALAVARTI PROJECTS PVT LTD" and "36AABCY1234H1ZX" in " ".join(str(c.value) for c in ws["A"][:4])
    template = tenant.get("/api/sub-mb/template.xlsx")
    assert images(template)[0] == [0]
    tmpl = tenant.get("/api/erp/work-orders/template")
    assert images(tmpl)[0] == [0]
    csvs = tenant.get("/api/sheets/items/template.xlsx")
    assert csvs.status_code in (200, 404)


def test_the_pdf_twin_of_a_register_carries_the_logo(tenant):
    with_letterhead(tenant)
    pdf = pdf_of(tenant.get("/api/wo/orders.pdf"))
    assert pictures(pdf) >= 1
