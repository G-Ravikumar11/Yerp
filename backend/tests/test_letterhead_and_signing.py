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
    # Words, not lines: a phrase that wraps in the PDF is still the phrase.
    return " ".join(" ".join((p.extract_text() or "").split()) for p in reader.pages)


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
    # Placed by the owner, it waits for the owner's own sign-off.
    assert tenant.post("/api/erp/work-orders/%d/decide" % wo["id"],
                       json={"decision": "approve"}).json()["status"] == "approved"
    res = tenant.post("/api/mb/%d/entries" % wo["id"], json={"line_id": line_of(tenant, wo["id"]), "quantity": 5})
    assert res.status_code == 200, res.text


def test_another_company_cannot_edit_our_letterhead_or_gangs(tenant, second_tenant):
    _, unit, con = an_order(tenant)
    assert second_tenant.put("/api/wo/business-units/%d" % unit["id"], json={"name": "X"}).status_code == 404
    assert second_tenant.put("/api/wo/contractors/%d" % con["id"], json={"company_name": "X"}).status_code == 404


# --- The other party's particulars, on every document ------------------------------

def test_a_customer_has_a_pan_and_a_checked_gstin(tenant):
    res = tenant.post("/api/customers", json={"name": "Aparna Constructions", "gstin": "36aaeca1234k1z2"})
    assert res.status_code == 200, res.text
    assert res.json()["pan"] == "AAECA1234K" and res.json()["state"] == "Telangana"
    bad = tenant.post("/api/customers", json={"name": "Bad One", "gstin": "36XYZ"})
    assert bad.status_code == 400


def test_the_client_bill_names_the_client_with_pan_gstin_and_contact(tenant):
    from test_measurement_and_ra_bills import placed_order, measure, line_of, raise_bill
    wo = placed_order(tenant)
    # The project named the client, which put them on the customer list;
    # their particulars are filled in on that entry.
    cust = [c for c in tenant.get("/api/customers").json()["customers"] if c["name"] == "L&T"][0]
    res = tenant.put("/api/customers/%d" % cust["id"], json={
        "name": "L&T", "gstin": "36AAACL1234H1Z5", "contact_person": "R. Menon", "phone_number": "9876500000",
        "address": "Manapakkam", "city": "Chennai", "pincode": "600089"})
    assert res.status_code == 200, res.text
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 100)
    bill = raise_bill(tenant, wo["id"]).json()["bill"]
    body = text(pdf_of(tenant.get("/api/ra-bills/%d/document.pdf" % bill["id"])))
    for words in ("AAACL1234H", "36AAACL1234H1Z5", "R. Menon", "9876500000", "Manapakkam", "Telangana"):
        assert words in body, words


def test_the_purchase_order_names_the_supplier_with_pan_gstin_and_state(tenant):
    tenant.post("/api/suppliers", json={"name": "Sri Sai Steels", "gstin": "37AABCS1234E1Z9",
                                        "contact_person": "M. Rao", "phone": "9440012345", "address": "Autonagar, Vijayawada"})
    order = tenant.post("/api/purchase-orders", json={"supplier_name": "Sri Sai Steels", "amount": 50000.0,
                                                      "tax_amount": 9000.0}).json()
    body = text(pdf_of(tenant.get("/api/purchase-orders/%d/document.pdf" % order["id"])))
    for words in ("AABCS1234E", "37AABCS1234E1Z9", "Andhra Pradesh", "M. Rao", "9440012345", "Autonagar"):
        assert words in body, words
    assert "50,000" in body                     # a lump-sum order prints its figure, not a nought


def test_a_statement_names_the_party_with_its_particulars(tenant):
    order, _, con = an_order(tenant)
    tenant.put("/api/wo/contractors/%d" % con["id"], json={
        "company_name": "Rani Labour Contractors", "gst_number": "36AAAPR1234C1Z5", "address": "Kukatpally"})
    res = tenant.get("/api/ledger/statement.pdf?party_type=contractor&party=Rani%20Labour%20Contractors")
    body = text(pdf_of(res))
    assert "AAAPR1234C" in body and "36AAAPR1234C1Z5" in body and "Kukatpally" in body


# --- The work order, as the sample reads ----------------------------------------------

def test_the_general_conditions_are_written_for_this_company(tenant):
    order, unit, _ = an_order(tenant)
    tenant.put("/api/wo/business-units/%d" % unit["id"], json={
        "name": "Yalavarti Projects Pvt Ltd", "code": "YPPL", "gstin": "36AABCY1234H1ZX",
        "address": "Plot 12, Madhapur\nHyderabad, Telangana 500081"})
    body = text(pdf_of(tenant.get("/api/wo/orders/%d/document.pdf" % order["id"])))
    assert "{company}" not in body and "{city}" not in body
    assert "payment to the contractor for all bills" in body and "YPPL" in body
    assert "City Civil Court, Hyderabad" in body
    assert "child labour" in body
    lib = tenant.get("/api/wo/terms/library").json()["library"]
    assert not any("{company}" in t["clause_text"] for t in lib)


def test_the_town_for_the_courts_is_read_off_the_letterhead():
    import main
    assert main.jurisdiction_city("31-15-29, Katuri vari Street,\nMachavaram Down,\nVijayawada - 520004.") == "Vijayawada"
    assert main.jurisdiction_city("Plot 12, Madhapur, Hyderabad 500081") == "Hyderabad"
    assert main.jurisdiction_city("Plot 12, Madhapur\nHyderabad, Telangana 500081") == "Hyderabad"
    assert main.jurisdiction_city("", "36AABCY1234H1ZX") == "Telangana"
