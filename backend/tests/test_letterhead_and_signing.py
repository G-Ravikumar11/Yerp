"""What prints on a work order is only as good as what is on file.

The company's letterhead (logo, GSTIN, PAN, address), the gang's particulars,
the company's own general conditions and the signatures and seal can all be
kept up; a signature prints only once the paper has earned it; every order
spends a budget; and only an approved order is billed.
"""
import base64
import io

import pytest

from conftest import fund_order, make_employee

pypdf = pytest.importorskip("pypdf")
PIL = pytest.importorskip("PIL.Image")

PASSWORD = "Crew1234"


def png(colour=(20, 40, 160), size=(120, 40)):
    buf = io.BytesIO()
    PIL.new("RGB", size, colour).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def pdf_of(res):
    assert res.status_code == 200, res.text[:300]
    return pypdf.PdfReader(io.BytesIO(res.content))


def text(reader):
    return " ".join((p.extract_text() or "") for p in reader.pages)


def pictures(reader, page=0):
    res = reader.pages[page].get("/Resources") or {}
    xo = res.get("/XObject") or {}
    return len([k for k in xo if xo[k].get_object().get("/Subtype") == "/Image"])


def an_order(tenant):
    units = tenant.get("/api/wo/business-units").json()["business_units"]
    unit = units[0] if units else tenant.post("/api/wo/business-units", json={"name": "Yalavarti Projects"}).json()
    con = tenant.post("/api/wo/contractors", json={"company_name": "Rani Labour Contractors"}).json()
    job = tenant.post("/api/jobs", json={"name": "Kokapet Towers", "customer_name": "Aparna"}).json()
    order = tenant.post("/api/wo/orders", json={
        "business_unit_id": unit["id"], "contractor_id": con["id"], "job_id": job["id"],
        "department": "Civil", "work_type": "Civil", "subject": "Shuttering, tower B",
        "commencement_date": "2026-10-01", "completion_date": "2027-03-31"}).json()["order"]
    order = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": [
        {"item_description": "Shuttering", "uom": "sqm", "quantity": 100, "unit_rate": 185}]}).json()["order"]
    return fund_order(tenant, order), unit, con


# --- The letterhead and the gang's particulars ----------------------------------

def test_the_letterhead_can_be_corrected_and_prints(tenant):
    order, unit, _ = an_order(tenant)
    res = tenant.put("/api/wo/business-units/%d" % unit["id"], json={
        "name": "Yalavarti Projects Pvt Ltd", "code": "YPPL", "gstin": "36aabcy1234h1zx",
        "address": "Plot 12, Madhapur\nHyderabad 500081", "logo_url": png()})
    assert res.status_code == 200, res.text
    saved = [u for u in tenant.get("/api/wo/business-units").json()["business_units"] if u["id"] == unit["id"]][0]
    assert saved["gstin"] == "36AABCY1234H1ZX" and saved["pan"] == "AABCY1234H"    # the PAN is inside the GSTIN
    reader = pdf_of(tenant.get("/api/wo/orders/%d/document.pdf" % order["id"]))
    body = text(reader)
    assert "AABCY1234H" in body and "36AABCY1234H1ZX" in body and "Madhapur" in body
    assert pictures(reader) >= 1                                                   # the logo


def test_a_bad_gstin_or_a_pan_that_does_not_match_is_refused(tenant):
    _, unit, con = an_order(tenant)
    bad = tenant.put("/api/wo/business-units/%d" % unit["id"], json={"name": "Y", "gstin": "36ABC"})
    assert bad.status_code == 400 and "fifteen" in bad.json()["detail"]
    clash = tenant.put("/api/wo/contractors/%d" % con["id"], json={
        "company_name": "Rani Labour Contractors", "gst_number": "36AAAPR1234C1Z5", "pan": "AAAPX9999Z"})
    assert clash.status_code == 400 and "inside the GSTIN" in clash.json()["detail"]
    notpic = tenant.put("/api/wo/business-units/%d" % unit["id"], json={"name": "Y", "logo_url": "data:text/html;base64,PGI+"})
    assert notpic.status_code == 400


def test_the_gangs_particulars_can_be_filled_in_later(tenant):
    order, _, con = an_order(tenant)
    res = tenant.put("/api/wo/contractors/%d" % con["id"], json={
        "company_name": "Rani Labour Contractors", "contact_person": "K. Rani", "phone_number": "9848012345",
        "gst_number": "36AAAPR1234C1Z5", "address": "Kukatpally, Hyderabad",
        "bank_name": "SBI", "bank_account": "3012 3456 789", "bank_ifsc": "sbin0001234"})
    assert res.status_code == 200, res.text
    body = text(pdf_of(tenant.get("/api/wo/orders/%d/document.pdf" % order["id"])))
    assert "36AAAPR1234C1Z5" in body and "AAAPR1234C" in body and "9848012345" in body and "Kukatpally" in body


# --- The company's own terms -----------------------------------------------------

def test_the_company_writes_its_own_general_conditions(tenant):
    order, _, _ = an_order(tenant)
    res = tenant.put("/api/wo/terms/library", json={"terms": [
        {"clause_category": "Safety", "clause_text": "Helmets and harnesses at all times above ground level."},
        {"clause_category": "Payment", "clause_text": "Bills are certified by the 10th of the following month."}]})
    assert res.status_code == 200 and res.json()["custom"] is True
    lib = tenant.get("/api/wo/terms/library").json()
    assert lib["custom"] and lib["library"][0]["clause_category"] == "Safety"
    body = text(pdf_of(tenant.get("/api/wo/orders/%d/document.pdf" % order["id"])))
    assert "Helmets and harnesses" in body and "certified by the 10th" in body
    # Saving nothing goes back to the standard conditions.
    assert tenant.put("/api/wo/terms/library", json={"terms": []}).json()["custom"] is False


# --- Signatures and the seal ------------------------------------------------------

def test_signatures_print_only_once_the_order_is_approved(tenant):
    order, _, _ = an_order(tenant)
    res = tenant.put("/api/documents/signatories", json={
        "prepared": {"name": "Ravi Kumar", "image": png((0, 0, 0))},
        "authorised": {"name": "G. Ravi Kumar", "title": "Managing Director", "image": png((0, 0, 90))},
        "seal": png((150, 0, 0), (60, 60))})
    assert res.status_code == 200, res.text
    draft = pdf_of(tenant.get("/api/wo/orders/%d/document.pdf" % order["id"]))
    assert pictures(draft) == 0
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    sent = pdf_of(tenant.get("/api/wo/orders/%d/document.pdf" % order["id"]))
    assert pictures(sent) == 1                        # the preparer's, and nobody else's yet
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    signed = pdf_of(tenant.get("/api/wo/orders/%d/document.pdf" % order["id"]))
    assert pictures(signed) == 3                      # preparer, authorised signatory, seal
    assert "Managing Director" in text(signed)


def test_staff_are_not_handed_a_copy_of_the_signature(tenant, portal):
    tenant.put("/api/documents/signatories", json={"authorised": {"name": "G. Ravi Kumar", "image": png()}})
    assert tenant.get("/api/documents/signatories").json()["signatories"]["authorised"]["image"]
    emp = make_employee(tenant, permission_role="project_manager", password=PASSWORD)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": PASSWORD})
    got = portal.get("/api/documents/signatories").json()["signatories"]["authorised"]
    assert got["image"] == "" and got["has_image"] is True
    assert portal.put("/api/documents/signatories", json={"authorised": {"image": ""}}).status_code in (401, 403)


def test_a_signature_must_be_a_picture(tenant):
    res = tenant.put("/api/documents/signatories", json={"authorised": {"image": "https://example.com/sig.png"}})
    assert res.status_code == 400


# --- Budget and billing -----------------------------------------------------------

def test_the_approver_sees_the_budget_the_order_spends(tenant):
    order, _, _ = an_order(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    item = [i for i in tenant.get("/api/approvals/inbox").json()["items"] if i["kind"] == "subcontract_order"][0]
    assert item["budget"] and "Works: allocated" in item["budget"][0]


def test_a_client_order_is_billed_only_once_approved(tenant):
    from test_measurement_and_ra_bills import line_of
    job = tenant.post("/api/jobs", json={"name": "Fairview", "customer_name": "L&T"}).json()
    made = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "SUPPLY OF CONDUIT", "units_of_measure": "Meters"},
        {"kind": "RM", "item_name": "20MM CONDUIT", "units_of_measure": "Meters"}]}).json()
    fg, rm = made["codes"]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "reference": "PO-9", "lines": [{"code": fg, "qty": 100, "rate": 60}]}).json()["work_order"]
    tenant.post("/api/erp/bom/build", json={"work_order_id": wo["id"],
                                            "lines": [{"fg_code": fg, "rm_code": rm, "qty": 100, "rate": 40}]})
    tenant.post("/api/erp/work-orders/%d/place-order" % wo["id"])
    res = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]})
    assert res.status_code == 409 and "approved" in res.json()["detail"]
    res = tenant.post("/api/mb/%d/entries" % wo["id"], json={"line_id": line_of(tenant, wo["id"]), "quantity": 5})
    assert res.status_code == 409
    assert tenant.post("/api/erp/work-orders/%d/submit" % wo["id"]).json()["status"] == "approved"
    res = tenant.post("/api/mb/%d/entries" % wo["id"], json={"line_id": line_of(tenant, wo["id"]), "quantity": 5})
    assert res.status_code == 200, res.text


def test_another_company_cannot_edit_our_letterhead_or_gangs(tenant, second_tenant):
    _, unit, con = an_order(tenant)
    assert second_tenant.put("/api/wo/business-units/%d" % unit["id"], json={"name": "X"}).status_code == 404
    assert second_tenant.put("/api/wo/contractors/%d" % con["id"], json={"company_name": "X"}).status_code == 404
