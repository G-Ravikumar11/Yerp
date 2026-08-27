"""Work orders issued out to a subcontractor.

The document that commits the business to paying somebody. It is numbered the
way the site office files it, it cannot be signed off by the person who priced
it, and once it has been signed it stops being editable - it is amended
instead, and the original stays as it was signed.
"""
from conftest import make_employee

import main


PASSWORD = "Crew1234"


def staff(tenant, role):
    emp = make_employee(tenant, permission_role=role, password=PASSWORD)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    return emp


def sign_in(client, emp):
    res = client.post("/api/employee/auth/login",
                      json={"email": emp["email"], "password": PASSWORD})
    assert res.status_code == 200, res.text


_seq = [0]


def masters(tenant):
    """A business unit, a contractor and a project to hang an order on.

    The contractor is named per call: one is refused as a duplicate, which is
    correct behaviour and not what these tests are about.
    """
    _seq[0] += 1
    unit = tenant.post("/api/wo/business-units", json={
        "name": "Yalavarti Projects Pvt Ltd", "code": "YPPL",
        "gstin": "36AABCY1234H1ZX", "pan": "AABCY1234H"}).json()
    con = tenant.post("/api/wo/contractors", json={
        "company_name": "Sri Balaji Civil Works %d" % _seq[0], "pan": "AAAPB1234C",
        "gst_number": "36AAAPB1234C1Z5"}).json()
    job = tenant.post("/api/jobs", json={"name": "295 KLD STP",
                                         "customer_name": "L&T"}).json()
    return unit, con, job


def draft(tenant, department="STP", **over):
    unit, con, job = masters(tenant)
    body = {"business_unit_id": unit["id"], "contractor_id": con["id"],
            "job_id": job["id"], "department": department, "work_type": "Civil",
            "subject": "Work order for primary civil STP supply & commissioning "
                       "for 295 KLD plant",
            "commencement_date": "2026-05-01", "completion_date": "2026-11-30",
            "duration_months": 7, "defect_liability_months": 12,
            "gst_rate": 18, "tds_rate": 1}
    body.update(over)
    res = tenant.post("/api/wo/orders", json=body)
    assert res.status_code == 200, res.text
    return res.json()["order"]


BOQ = {"lines": [
    {"activity_no": "1.0", "item_code": "CIV-RMC-25",
     "item_description": "M25 Grade RMC pouring, cube strength 25 MPa, 14-day curing",
     "uom": "cum", "quantity": 250, "unit_rate": 6800},
    {"activity_no": "2.0", "item_code": "CIV-STL",
     "item_description": "Fe500D reinforcement steel, cut, bent and placed",
     "uom": "MT", "quantity": 18.5, "unit_rate": 68000},
]}


def priced(tenant, **over):
    order = draft(tenant, **over)
    res = tenant.put("/api/wo/orders/%d/boq" % order["id"], json=BOQ)
    assert res.status_code == 200, res.text
    return res.json()["order"]


# --- The number -------------------------------------------------------------

def test_the_number_says_the_year_and_the_discipline(tenant):
    """WO/2026-27/STP/001 is how the site office files it.

    A number that does not match the file it is filed in is worse than no
    number at all.
    """
    order = draft(tenant, department="STP", commencement_date="2026-05-01")
    assert order["wo_number"] == "WO/2026-27/STP/001"


def test_the_serial_runs_separately_per_discipline(tenant):
    assert draft(tenant, department="STP")["wo_number"].endswith("/STP/001")
    assert draft(tenant, department="Civil")["wo_number"].endswith("/CIVIL/001")
    assert draft(tenant, department="STP")["wo_number"].endswith("/STP/002")


def test_the_financial_year_runs_april_to_march(tenant):
    assert main.financial_year_label("2026-03-31") == "2025-26"
    assert main.financial_year_label("2026-04-01") == "2026-27"


def test_changing_the_discipline_on_a_draft_reissues_the_number(tenant):
    """The discipline is in the number, so it cannot quietly disagree with it."""
    order = draft(tenant, department="STP")
    res = tenant.put("/api/wo/orders/%d" % order["id"],
                     json={"department": "Electrical", "subject": order["subject"]})
    assert res.json()["order"]["wo_number"].split("/")[2] == "ELECTR"


# --- What it is worth -------------------------------------------------------

def test_gst_is_added_and_tds_is_withheld(tenant):
    """They pull in opposite directions and are not two halves of one number.

    Netting them against each other is the error this guards: GST is charged
    on top of the gross, TDS is deducted out of it.
    """
    order = priced(tenant)
    assert order["gross_amount"] == 2958000.0        # 250x6800 + 18.5x68000
    assert order["gst_amount"] == 532440.0           # 18%
    assert order["tds_amount"] == 29580.0            # 1%
    assert order["net_order_value"] == 3460860.0     # gross + gst - tds


def test_each_schedule_line_carries_its_own_amount(tenant):
    order = priced(tenant)
    first = order["items"][0]
    assert first["uom"] == "cum"
    assert first["total_amount"] == 1700000.0
    assert order["items"][1]["total_amount"] == 1258000.0


def test_the_value_is_stated_in_words_for_the_signatories(tenant):
    assert main.amount_in_words(3460860) == (
        "Rupees Thirty Four Lakh Sixty Thousand Eight Hundred and Sixty Only")
    assert main.amount_in_words(0) == "Rupees Zero Only"


# --- Asking somebody to sign it --------------------------------------------

def test_a_draft_may_be_incomplete_but_may_not_be_submitted(tenant):
    """A draft is allowed to be half finished - that is what a draft is for.

    It is asking somebody to approve it that requires a complete document.
    """
    order = draft(tenant)                                  # no BOQ yet
    res = tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert res.status_code == 400
    assert "schedule item" in res.json()["detail"]


def test_submitting_makes_it_provisional(tenant):
    order = priced(tenant)
    res = tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert res.status_code == 200, res.text
    assert res.json()["order"]["status"] == "PROVISIONAL"


def test_a_provisional_order_is_watermarked(tenant):
    """It must not be able to be printed as though it were signed."""
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert doc["watermark"] == "PROVISIONAL - NOT VALID FOR EXECUTION"


def test_the_watermark_goes_once_it_is_approved(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert doc["watermark"] == ""


def test_a_submitted_order_cannot_be_edited(tenant):
    """The figures are what somebody is being asked to sign off, so they must
    not move underneath them."""
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert tenant.put("/api/wo/orders/%d" % order["id"],
                      json={"subject": "changed"}).status_code == 409
    assert tenant.put("/api/wo/orders/%d/boq" % order["id"],
                      json=BOQ).status_code == 409


# --- Who may do what --------------------------------------------------------

def test_the_engineer_who_priced_it_cannot_approve_it(tenant):
    """The whole point of the provisional state.

    A supervisor may raise and price an order; committing the business to it
    is somebody else's signature.
    """
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    engineer = staff(tenant, "supervisor")
    sign_in(tenant, engineer)
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 403
    tenant.post("/api/employee/auth/logout")


def test_a_manager_may_approve(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    head = staff(tenant, "manager")
    sign_in(tenant, head)
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"],
                      json={"comments": "Rates checked against budget"})
    assert res.status_code == 200, res.text
    assert res.json()["order"]["status"] == "APPROVED"
    tenant.post("/api/employee/auth/logout")


def test_one_tenant_cannot_see_anothers_order(tenant, second_tenant):
    order = priced(tenant)
    assert second_tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 404


# --- Sending it back --------------------------------------------------------

def test_a_rejection_must_say_why(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/reject" % order["id"], json={"comments": " "})
    assert res.status_code == 400


def test_a_rejection_returns_it_to_draft_with_the_reason(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/reject" % order["id"],
                      json={"comments": "Steel rate is above the budgeted figure"})
    back = res.json()["order"]
    assert back["status"] == "DRAFT"
    assert back["rejection_reason"] == "Steel rate is above the budgeted figure"
    assert back["editable"] is True


# --- The state machine itself ----------------------------------------------

def test_an_order_cannot_skip_approval(tenant):
    order = priced(tenant)
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 409, "a draft has not been submitted to anybody"


def test_an_order_is_not_approved_twice(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"],
                       json={}).status_code == 409


def test_it_is_executed_only_after_approval(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert tenant.post("/api/wo/orders/%d/execute" % order["id"],
                       json={}).status_code == 409
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/execute" % order["id"], json={})
    assert res.json()["order"]["status"] == "EXECUTED"


def test_every_move_is_written_to_the_history(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={"comments": "Go"})
    history = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["history"]
    assert [h["action"] for h in history] == ["CREATE", "SUBMIT", "APPROVE"]
    assert history[-1]["from_status"] == "PROVISIONAL"
    assert history[-1]["to_status"] == "APPROVED"
    assert history[-1]["comments"] == "Go"


# --- Amending ---------------------------------------------------------------

def test_an_amendment_supersedes_rather_than_edits(tenant):
    """The original was signed, so it stays as it was signed."""
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/amend" % order["id"], json={})
    assert res.status_code == 200, res.text
    revision = res.json()["order"]

    assert revision["wo_number"].endswith("-REV-01")
    assert revision["amendment_no"] == 1
    assert revision["status"] == "DRAFT"
    assert revision["supersedes_id"] == order["id"]
    # the schedule comes across so it can be edited rather than retyped
    assert revision["gross_amount"] == order["gross_amount"]
    assert len(revision["items"]) == 2

    original = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    assert original["status"] == "AMENDED"
    assert original["gross_amount"] == 2958000.0, "the signed figures are untouched"


def test_a_superseded_order_prints_as_superseded(tenant):
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/amend" % order["id"], json={})
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert doc["watermark"] == "SUPERSEDED"


# --- Masters ----------------------------------------------------------------

def test_a_contractor_is_numbered_in_one_series(tenant):
    first = tenant.post("/api/wo/contractors", json={"company_name": "One"}).json()
    second = tenant.post("/api/wo/contractors", json={"company_name": "Two"}).json()
    assert first["vendor_code"] == "SC-0001"
    assert second["vendor_code"] == "SC-0002"


def test_the_same_contractor_is_not_added_twice(tenant):
    tenant.post("/api/wo/contractors", json={"company_name": "Sri Balaji Civil Works"})
    again = tenant.post("/api/wo/contractors",
                        json={"company_name": "SRI BALAJI CIVIL WORKS"})
    assert again.status_code == 409


def test_the_clause_library_is_offered_to_start_from(tenant):
    library = tenant.get("/api/wo/terms/library").json()["library"]
    assert any(t["clause_category"] == "Mode of Measurement" for t in library)
    assert all(t["clause_text"].strip() for t in library)


def test_terms_are_saved_in_the_order_they_are_read(tenant):
    order = draft(tenant)
    res = tenant.put("/api/wo/orders/%d/terms" % order["id"], json={"terms": [
        {"clause_category": "Mode of Measurement", "clause_text": "As per IS 1200."},
        {"clause_category": "Defect Liability", "clause_text": "12 months."}]})
    terms = res.json()["order"]["terms"]
    assert [t["clause_category"] for t in terms] == [
        "Mode of Measurement", "Defect Liability"]


# --- The schedule as a workbook --------------------------------------------

def test_the_schedule_downloads_with_its_totals(tenant):
    order = priced(tenant)
    res = tenant.get("/api/wo/orders/%d/boq.xlsx" % order["id"])
    assert res.status_code == 200
    assert "work_order_" in res.headers.get("content-disposition", "")
    assert len(res.content) > 4000
