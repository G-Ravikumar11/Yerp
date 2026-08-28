"""Work orders issued out to a subcontractor.

The document that commits the business to paying somebody. It is numbered the
way the site office files it, it cannot be signed off by the person who priced
it, and once it has been signed it stops being editable - it is amended
instead, and the original stays as it was signed.
"""
from conftest import as_owner, make_employee

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


# --- The printed document ---------------------------------------------------

def test_the_order_downloads_as_a_pdf(tenant):
    """The signed copy. It is attached to bills and produced in disputes, so it
    is rendered on the server rather than by whatever the browser happens to
    do with the screen."""
    order = priced(tenant)
    res = tenant.get("/api/wo/orders/%d/document.pdf" % order["id"])
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert len(res.content) > 3000


def test_the_pdf_is_named_after_the_order(tenant):
    order = priced(tenant)
    res = tenant.get("/api/wo/orders/%d/document.pdf" % order["id"])
    assert "WO_2026_27_STP_001" in res.headers.get("content-disposition", "")


def test_the_pdf_runs_to_more_than_one_page(tenant):
    """The letter, the schedule, the clauses and the signatures do not fit on
    one sheet, and each of them starts on its own."""
    import wo_pdf
    order = priced(tenant)
    tenant.put("/api/wo/orders/%d/terms" % order["id"], json={"terms": [
        {"clause_category": "Mode of Measurement", "clause_text": "As per IS 1200."}]})
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    pdf = wo_pdf.build_work_order_pdf(doc)
    assert pdf.startswith(b"%PDF-")
    assert pdf.count(b"/Page") >= 3


def test_a_provisional_order_can_still_be_printed(tenant):
    """The provisional copy is what goes round for approval, so it has to be
    printable. It is the watermark that stops it being acted on."""
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.get("/api/wo/orders/%d/document.pdf" % order["id"])
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


def test_a_draft_is_watermarked_as_not_issued(tenant):
    order = priced(tenant)
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert doc["watermark"] == "DRAFT - NOT ISSUED"


def test_the_document_names_who_approved_it(tenant, client):
    """A signature block printed with the approver's name already on it is the
    difference between recording who committed the business and leaving a
    blank anybody could fill in."""
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    head = staff(tenant, "manager")
    sign_in(client, head)
    assert client.post("/api/wo/orders/%d/approve" % order["id"],
                       json={}).status_code == 200

    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    approved = [s for s in doc["signatures"] if s["role"] == "Approved by"][0]
    assert head["first_name"] in approved["name"]


def test_amounts_are_grouped_the_way_they_are_read():
    """Lakhs and crores. Western grouping on the same number reads as a
    different amount at a glance, on a document somebody signs."""
    import wo_pdf
    assert wo_pdf.inr(1234567.5) == "12,34,567.50"
    assert wo_pdf.inr(100) == "100.00"
    assert wo_pdf.inr(-45000) == "(45,000.00)"
    assert wo_pdf.inr(12.2222, 4) == "12.2222"


def test_dates_print_the_way_a_site_reads_them():
    import wo_pdf
    assert wo_pdf._date("2026-09-01") == "01/09/2026"
    assert wo_pdf._date("") == ""


# --- What the project is allowed to spend -----------------------------------

def allocate(tenant, job_id, name="Civil - substructure", amount=1000000):
    res = tenant.post("/api/wo/projects/%d/budgets" % job_id,
                      json={"name": name, "allocated_amount": amount})
    assert res.status_code == 200, res.text
    return res.json()


def budgeted(tenant, allocation=5000000):
    """A priced order whose whole schedule is against one cost centre."""
    order = draft(tenant)
    budget = allocate(tenant, order["job_id"], amount=allocation)
    lines = [dict(line, budget_id=budget["id"]) for line in BOQ["lines"]]
    res = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": lines})
    assert res.status_code == 200, res.text
    return res.json()["order"], budget


def test_an_allocation_starts_wholly_available(tenant):
    order = draft(tenant)
    allocate(tenant, order["job_id"], amount=1000000)
    row = tenant.get("/api/wo/projects/%d/budgets"
                     % order["job_id"]).json()["budgets"][0]
    assert row["allocated"] == 1000000
    assert row["committed"] == 0
    assert row["available"] == 1000000


def test_a_draft_has_not_committed_anything(tenant):
    """Pricing something up is how you find out it is too big. A draft that
    held budget would stop anybody finding out."""
    order, _ = budgeted(tenant)
    row = tenant.get("/api/wo/projects/%d/budgets"
                     % order["job_id"]).json()["budgets"][0]
    assert row["committed"] == 0


def test_submitting_commits_the_money(tenant):
    order, _ = budgeted(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    row = tenant.get("/api/wo/projects/%d/budgets"
                     % order["job_id"]).json()["budgets"][0]
    assert row["committed"] == 2958000.0
    assert row["available"] == 5000000 - 2958000.0


def test_the_order_reports_its_own_share_separately(tenant):
    """So the wizard can say "this order takes the last of it" while it is
    still being priced, rather than once it is too late to change."""
    order, _ = budgeted(tenant)
    row = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["budgets"][0]
    assert row["this_order"] == 2958000.0
    assert row["committed"] == 0


def test_an_order_that_overruns_cannot_simply_be_approved(tenant):
    order, _ = budgeted(tenant, allocation=1000000)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 409
    assert "overruns" in res.json()["detail"]
    assert tenant.get("/api/wo/orders/%d" % order["id"]).json()[
        "order"]["status"] == "PROVISIONAL"


def test_an_overrun_can_be_approved_deliberately_and_is_recorded(tenant):
    order, _ = budgeted(tenant, allocation=1000000)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"],
                      json={"override": True,
                            "comments": "Scope grew after the soil report"})
    assert res.status_code == 200, res.text
    assert res.json()["order"]["status"] == "APPROVED"

    history = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["history"]
    approval = [h for h in history if h["action"] == "APPROVE"][0]
    assert "Budget override" in approval["comments"]
    assert "soil report" in approval["comments"]


def test_an_overrun_has_to_be_explained(tenant):
    order, _ = budgeted(tenant, allocation=1000000)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"],
                      json={"override": True, "comments": "  "})
    assert res.status_code == 400


def test_the_overrun_is_stated_before_anybody_clicks_approve(tenant):
    order, _ = budgeted(tenant, allocation=1000000)
    detail = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    assert detail["budget_warnings"], "the review has to say so first"
    assert "allocated" in detail["budget_warnings"][0]


def test_an_unallocated_cost_centre_does_not_block_anything(tenant):
    """Nought allocated means nobody has set it, not that it is fully spent."""
    order, _ = budgeted(tenant, allocation=0)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 200, res.text


def test_cancelling_gives_the_money_back(tenant):
    order, _ = budgeted(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/cancel" % order["id"],
                json={"comments": "Contractor withdrew"})
    row = tenant.get("/api/wo/projects/%d/budgets"
                     % order["job_id"]).json()["budgets"][0]
    assert row["committed"] == 0
    assert row["available"] == 5000000


def test_an_allocation_cannot_be_cut_below_what_is_committed(tenant):
    order, budget = budgeted(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.put("/api/wo/projects/budgets/%d" % budget["id"],
                     json={"name": "Civil - substructure", "allocated_amount": 100000})
    assert res.status_code == 409
    assert "already committed" in res.json()["detail"]


def test_a_line_cannot_spend_another_projects_allocation(tenant):
    """Dropped rather than refused: the picker empties when the project
    changes, and one stale line should not reject two hundred good ones."""
    order, _ = budgeted(tenant)
    other = draft(tenant)
    stray = allocate(tenant, other["job_id"], name="Another project's money")
    res = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={
        "lines": [dict(BOQ["lines"][0], budget_id=stray["id"])]})
    assert res.status_code == 200, res.text
    assert res.json()["order"]["items"][0]["budget_id"] is None


def test_an_amendment_carries_the_cost_centres_across(tenant):
    order, budget = budgeted(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    revision = tenant.post("/api/wo/orders/%d/amend" % order["id"],
                           json={}).json()["order"]
    assert all(i["budget_id"] == budget["id"] for i in revision["items"])


def test_one_tenant_cannot_allocate_against_anothers_project(tenant, second_tenant):
    order = draft(tenant)
    res = second_tenant.post("/api/wo/projects/%d/budgets" % order["job_id"],
                             json={"name": "Theirs", "allocated_amount": 100})
    assert res.status_code == 404


# --- Telling somebody it is their move --------------------------------------

def test_submitting_tells_the_people_who_can_approve(tenant, client):
    """An order that sits in a queue nobody is told about is an order that
    sits in a queue."""
    head = staff(tenant, "manager")
    order = priced(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})

    sign_in(client, head)
    titles = [n["title"] for n in
              client.get("/api/employee/notifications").json()["notifications"]]
    assert any("awaiting approval" in t for t in titles), titles


def test_the_engineer_hears_back_when_it_is_decided(tenant, client):
    engineer = staff(tenant, "manager")
    order = priced(tenant)
    # Submitted by the engineer, so the decision comes back to them.
    sign_in(client, engineer)
    assert client.post("/api/wo/orders/%d/submit" % order["id"],
                       json={}).status_code == 200

    as_owner(tenant)
    tenant.post("/api/wo/orders/%d/reject" % order["id"],
                json={"comments": "Rate on line 2 is above the last order"})

    sign_in(client, engineer)
    rows = client.get("/api/employee/notifications").json()["notifications"]
    assert any("sent back" in n["title"] for n in rows), rows


def test_nobody_is_told_about_their_own_move(tenant, client):
    """Being told about your own submission is the noise that gets
    notifications turned off. A manager may approve as well as raise, so they
    are in the list this would otherwise notify."""
    engineer = staff(tenant, "manager")
    order = priced(tenant)
    sign_in(client, engineer)
    client.post("/api/wo/orders/%d/submit" % order["id"], json={})

    rows = client.get("/api/employee/notifications").json()["notifications"]
    assert not any("awaiting approval" in n["title"] for n in rows), rows


# --- Retention and the mobilization advance ---------------------------------

def test_retention_and_advance_are_worked_out_from_the_gross(tenant):
    order = draft(tenant, retention_percent=5, mobilization_advance_percent=10,
                  advance_recovery_percent=20)
    order = tenant.put("/api/wo/orders/%d/boq" % order["id"],
                       json=BOQ).json()["order"]
    assert order["gross_amount"] == 2958000.0
    assert order["retention_amount"] == 147900.0
    assert order["mobilization_advance_amount"] == 295800.0
    assert order["advance_recovery_percent"] == 20


def test_neither_is_taken_off_the_order_value(tenant):
    """Retention is held back and given back; the advance is paid early and
    taken back. Both are timing, not price - a contractor who reads 5%
    retention as 5% off the price prices the next job for it."""
    plain = priced(tenant)
    withheld = draft(tenant, retention_percent=5, mobilization_advance_percent=10)
    withheld = tenant.put("/api/wo/orders/%d/boq" % withheld["id"],
                          json=BOQ).json()["order"]
    assert withheld["net_order_value"] == plain["net_order_value"]


def test_the_deductions_are_stated_on_the_document(tenant):
    import wo_pdf
    order = draft(tenant, retention_percent=5, mobilization_advance_percent=10,
                  advance_recovery_percent=20)
    tenant.put("/api/wo/orders/%d/boq" % order["id"], json=BOQ)
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert doc["retention_percent"] == 5
    assert wo_pdf.build_work_order_pdf(doc).startswith(b"%PDF-")


def test_an_amendment_keeps_the_commercial_terms(tenant):
    order = draft(tenant, retention_percent=5, mobilization_advance_percent=10,
                  advance_recovery_percent=20)
    tenant.put("/api/wo/orders/%d/boq" % order["id"], json=BOQ)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    revision = tenant.post("/api/wo/orders/%d/amend" % order["id"],
                           json={}).json()["order"]
    assert revision["retention_percent"] == 5
    assert revision["mobilization_advance_percent"] == 10
    assert revision["advance_recovery_percent"] == 20


# --- The work types an order may be raised for ------------------------------

def test_the_trade_s_own_work_types_are_there_to_start_with(tenant):
    """An empty required dropdown on the first screen of the first order is a
    dead end with nothing on the screen saying where to go instead."""
    types = tenant.get("/api/wo/work-types").json()["work_types"]
    assert types, "a new account should not open on an empty list"
    assert any("Civil" in t["name"] for t in types)


def test_an_administrator_adds_a_type_outright(tenant):
    res = tenant.post("/api/wo/work-types", json={
        "name": "Piling - bored cast in situ", "code": "CIV-PIL",
        "department": "Civil"})
    assert res.status_code == 200, res.text
    assert res.json()["work_type"]["status"] == "active"


def test_an_engineer_can_only_ask_for_one(tenant, client):
    """A list anybody may add to is free text with extra steps, and the same
    trade ends up filed under four spellings."""
    engineer = staff(tenant, "manager")
    sign_in(client, engineer)
    res = client.post("/api/wo/work-types", json={
        "name": "Shotcreting", "request_reason": "Tunnel lining on the bypass"})
    assert res.status_code == 200, res.text
    assert res.json()["work_type"]["status"] == "requested"
    assert "approves" in res.json()["message"]

    # and it is not offered for use until somebody decides on it
    offered = client.get("/api/wo/work-types").json()
    assert not any(t["name"] == "Shotcreting" for t in offered["work_types"])
    assert any(t["name"] == "Shotcreting" for t in offered["requested"])


def test_an_administrator_approves_the_request(tenant, client):
    engineer = staff(tenant, "manager")
    sign_in(client, engineer)
    asked = client.post("/api/wo/work-types", json={
        "name": "Shotcreting"}).json()["work_type"]

    # Back to the account holder's own screens, as a second browser would be:
    # signing in as staff ends the owner's session, which is the point.
    as_owner(tenant)
    res = tenant.post("/api/wo/work-types/%d/decide?approve=true" % asked["id"])
    assert res.status_code == 200, res.text
    assert res.json()["work_type"]["status"] == "active"
    assert any(t["name"] == "Shotcreting"
               for t in tenant.get("/api/wo/work-types").json()["work_types"])


def test_a_request_can_be_declined(tenant, client):
    engineer = staff(tenant, "manager")
    sign_in(client, engineer)
    asked = client.post("/api/wo/work-types", json={
        "name": "Miscellaneous"}).json()["work_type"]
    as_owner(tenant)
    res = tenant.post("/api/wo/work-types/%d/decide?approve=false" % asked["id"])
    assert res.json()["work_type"]["status"] == "declined"


def test_an_engineer_cannot_decide_their_own_request(tenant, client):
    engineer = staff(tenant, "manager")
    sign_in(client, engineer)
    asked = client.post("/api/wo/work-types", json={
        "name": "Shotcreting"}).json()["work_type"]
    assert client.post("/api/wo/work-types/%d/decide" % asked["id"]).status_code == 403


def test_the_same_work_type_is_not_added_twice(tenant):
    tenant.post("/api/wo/work-types", json={"name": "Shotcreting"})
    again = tenant.post("/api/wo/work-types", json={"name": "SHOTCRETING"})
    assert again.status_code == 409


def test_a_decided_request_is_not_decided_again(tenant, client):
    engineer = staff(tenant, "manager")
    sign_in(client, engineer)
    asked = client.post("/api/wo/work-types", json={
        "name": "Shotcreting"}).json()["work_type"]
    as_owner(tenant)
    tenant.post("/api/wo/work-types/%d/decide" % asked["id"])
    assert tenant.post("/api/wo/work-types/%d/decide"
                       % asked["id"]).status_code == 409


# --- A scope of work written in an editor -----------------------------------

def test_the_formatting_survives_and_the_rest_does_not(tenant):
    order = draft(tenant, scope_of_work=(
        "<p>Complete <b>civil works</b> for the <i>295 KLD</i> plant.</p>"
        "<script>alert(1)</script><div onclick='x'>Excavation</div>"))
    scope = order["scope_of_work"]
    assert "<b>civil works</b>" in scope
    assert "<i>295 KLD</i>" in scope
    assert "script" not in scope.lower()
    assert "onclick" not in scope.lower()
    assert "Excavation" in scope, "unknown tags lose their brackets, not their words"


def test_a_dimension_written_with_an_angle_bracket_survives(tenant):
    """Aggregate <20 mm is a specification, not a broken tag."""
    order = draft(tenant, scope_of_work="Aggregate <20 mm, graded.")
    assert "20 mm" in order["scope_of_work"]


def test_a_formatted_scope_still_prints(tenant):
    import wo_pdf
    order = draft(tenant, scope_of_work=(
        "<p>Steel &amp; cement issued free.</p><ul><li>Excavation</li>"
        "<li>Raft and walls</li></ul>"))
    tenant.put("/api/wo/orders/%d/boq" % order["id"], json=BOQ)
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert wo_pdf.build_work_order_pdf(doc).startswith(b"%PDF-")


def test_an_ampersand_does_not_break_the_page(tenant):
    import wo_pdf
    assert "&amp;" in wo_pdf._rich("steel & cement")
    assert wo_pdf._rich("steel &amp; cement").count("amp") == 1


def test_a_scope_beginning_with_b_or_r_keeps_its_letters(tenant):
    """The leading break is stripped as a tag, not as characters."""
    import wo_pdf
    assert wo_pdf._rich("<p>brick work</p>").startswith("brick work")


# --- The letterhead ---------------------------------------------------------

def test_the_business_unit_prints_its_own_letterhead(tenant):
    unit = tenant.post("/api/wo/business-units", json={
        "name": "Y Projects South", "logo_url": "data:image/png;base64,AAAA"}).json()
    order = draft(tenant, business_unit_id=unit["id"])
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert doc["business_unit_detail"]["logo_url"].startswith("data:image/png")


def test_a_logo_that_will_not_decode_does_not_stop_the_order_printing(tenant):
    import wo_pdf
    unit = tenant.post("/api/wo/business-units", json={
        "name": "Y Projects North",
        "logo_url": "data:image/png;base64,not-really-a-png"}).json()
    order = draft(tenant, business_unit_id=unit["id"])
    tenant.put("/api/wo/orders/%d/boq" % order["id"], json=BOQ)
    doc = tenant.get("/api/wo/orders/%d/document" % order["id"]).json()
    assert wo_pdf.build_work_order_pdf(doc).startswith(b"%PDF-")


def test_a_document_with_nothing_on_it_still_renders(tenant):
    """A Table built from no rows raises rather than drawing nothing, and took
    the whole document down with it."""
    import wo_pdf
    bare = {"wo_number": "WO/2026-27/GEN/001", "status": "DRAFT",
            "business_unit_detail": {}, "contractor_detail": {}, "contractor": "",
            "items": [], "terms": [], "signatures": [], "gross_amount": 0,
            "gst_rate": 18, "gst_amount": 0, "tds_rate": 1, "tds_amount": 0,
            "net_order_value": 0, "amount_in_words": "Zero", "printed_at": "",
            "watermark": ""}
    assert wo_pdf.build_work_order_pdf(bare).startswith(b"%PDF-")


def test_a_remote_logo_is_not_fetched_to_print_it(tenant):
    """Printing must not turn into a request this server makes to a URL
    somebody typed into a form."""
    import wo_pdf
    assert wo_pdf._logo("https://example.com/logo.png") is None
    assert wo_pdf._logo("") is None
