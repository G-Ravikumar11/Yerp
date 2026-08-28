"""The sheets the business actually sends, rather than the ones we hand out.

Taken from a live set: a raw material master of 1,567 codes, a work order of
1,943 priced lines and the budget behind it. Every case here is something one
of those three files did that stopped it being read - a heading spelt the way
the person who made the template spelt it, a row of guidance for the typist
left under the header, a grand total sitting at the foot of the sheet, and a
budget that heads two different columns with the same two words.
"""
import io

import openpyxl

import main


XL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def book(rows):
    """Those rows as a real .xlsx, which is what arrives."""
    wb = openpyxl.Workbook()
    for row in rows:
        wb.active.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def send(tenant, url, rows, **form):
    return tenant.post(url, files={"file": ("sheet.xlsx", book(rows), XL)}, data=form)


# Their headings, transcribed exactly - including "Discription".
WO_HEADER = ["Product Code", "Product Name", "Product Discription", "Quantity",
             "Price", "Discount Percentage", "Payment Type", "Payment", "Serial No"]
WO_HINTS = ["Without Spaces", "", "", "Without comma (,) only num",
            "Without comma (,) only num", "Without comma (,) only num"]

# The budget sheet heads the ordered item and the material it consumes with
# the same words, and puts the unit before the quantity.
BOM_HEADER = ["Product Code", "Product Code", "Product Name", "Units", "Quantity",
              "Payment Type", "Payment", "Serial No", "", "", "RATE", "FINAL RATE",
              "AMOUNT"]

ITEM_HINTS = ["", "", "", "", "Please Select Option From Dropdown",
              "Please Select Option From Dropdown", "", "Please Select Option From Dropdown",
              "Please Select Option From Dropdown", "Please Select Option From Dropdown", ""]


def item_rows(*codes):
    head = [main.ITEM_HEADERS, ITEM_HINTS]
    return head + [[c, "1.5SQMM FRLS WIRE RED", "YPPL", "1.5SQMM FRLS WIRE RED",
                    "RAW MATERIAL" if c.startswith("RM") else "FINISHED GOOD",
                    "RM" if c.startswith("RM") else "FG", "995461", 0.18,
                    "Service", "Meters", "Make List"] for c in codes]


def load_master(tenant, *codes):
    kind = "RM" if codes[0].startswith("RM") else "FG"
    res = send(tenant, "/api/erp/items/upload", item_rows(*codes), kind=kind)
    assert res.status_code == 200, res.text
    return res.json()


def project(tenant):
    return tenant.post("/api/jobs", json={"name": "Common Central Secretariat",
                                          "customer_name": "L&T"}).json()


# --- The row of guidance under the header -----------------------------------

def test_the_typists_instructions_are_not_read_as_an_item(tenant):
    """The row that says "Please Select Option From Dropdown" is not a part.

    It is left in the sheet on purpose, because it is what tells the person
    filling it in what to enter. Read as data it became an item with no code
    that failed every check, on every upload, for ever.
    """
    body = load_master(tenant, "RMRT141", "RMRT142")
    assert body["created"] == 2
    assert not body["errors"]


def test_the_instructions_are_not_read_as_an_order_line(tenant):
    load_master(tenant, "FG12801")
    res = send(tenant, "/api/erp/work-orders",
               [WO_HEADER, WO_HINTS, ["FG12801", "WIRING", "Supply", 7443, 765.75]],
               job_id=project(tenant)["id"])
    assert res.status_code == 200, res.text
    assert not res.json()["errors"], res.json()["errors"]
    assert len(res.json()["lines"]) == 1


def test_a_real_line_that_reads_like_guidance_is_still_a_line(tenant):
    """One instruction-shaped cell does not condemn the row.

    The test that keeps the rule honest: descriptions in this trade say things
    like "do not exceed", and dropping the row it sat in would lose a priced
    line silently, which is worse than the problem being solved.
    """
    load_master(tenant, "FG12801")
    res = send(tenant, "/api/erp/work-orders",
               [WO_HEADER, ["FG12801", "Do not exceed 3m drop", "Supply", 10, 5.0]],
               job_id=project(tenant)["id"])
    assert res.status_code == 200, res.text
    assert len(res.json()["lines"]) == 1
    assert res.json()["lines"][0]["qty"] == 10


# --- Their work order template ----------------------------------------------

def test_the_price_column_is_read_as_the_price(tenant):
    """The one that quietly mispriced a contract.

    Their fifth column is a price where our template's fifth is a unit, and
    the sheet was read by position. So the price was banked as the unit of
    measure and the discount percentage - nearly always zero - as the rate,
    and an order for millions came out costing nothing. Nothing about it
    looked like an error.
    """
    load_master(tenant, "FG12801")
    res = send(tenant, "/api/erp/work-orders",
               [WO_HEADER, ["FG12801", "WIRING", "Supply of wiring", 7443, 765.75, 0,
                            "Supply", 75, 1]],
               job_id=project(tenant)["id"])
    assert res.status_code == 200, res.text
    line = res.json()["lines"][0]
    assert line["rate"] == 765.75
    assert line["qty"] == 7443
    assert line["amount"] == 5699477.25
    assert line["uom"] == "Meters", "the unit comes from the item master, not the price"


def test_their_spelling_of_description_still_reaches_the_order(tenant):
    """"Product Discription" is the heading on the file in circulation."""
    load_master(tenant, "FG12801")
    res = send(tenant, "/api/erp/work-orders",
               [WO_HEADER, ["FG12801", "WIRING", "Supply of wiring for light point",
                            10, 5.0]],
               job_id=project(tenant)["id"])
    assert res.json()["lines"][0]["description"] == "Supply of wiring for light point"


def test_the_sheets_own_totals_do_not_sink_the_order(tenant):
    """A sheet off a real desk ends in its own totals.

    A number alone in a column we never read, under nineteen hundred priced
    lines. It has no code, so it failed - and because nothing is saved unless
    every line passes, three stray totals threw away the whole order.
    """
    load_master(tenant, "FG12801", "FG12802")
    totals = ["", "", "", "", "", "", "", "", "", "", "", "", 470000001]
    res = send(tenant, "/api/erp/work-orders",
               [WO_HEADER,
                ["FG12801", "WIRING", "Supply", 7443, 765.75],
                ["FG12802", "WIRING", "Installation", 7443, 153.15],
                totals],
               job_id=project(tenant)["id"])
    assert res.status_code == 200, res.text
    assert not res.json()["errors"], res.json()["errors"]
    assert len(res.json()["lines"]) == 2
    assert res.json()["total_value"] == 6839372.7


def test_a_workbook_is_read_as_a_workbook(tenant):
    """The template we hand out is .xlsx, so that is what comes back.

    It used to be decoded as latin-1 and handed to the csv reader, which made
    rows out of the wreckage of a zip file rather than refusing it - so the
    failure arrived as a page of unreadable codes instead of as an error.
    """
    load_master(tenant, "FG12801")
    res = send(tenant, "/api/erp/work-orders/validate",
               [WO_HEADER, ["FG12801", "WIRING", "Supply", 7443, 765.75]])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"], body["errors"]
    assert body["lines"][0]["fg_code"] == "FG12801"


# --- Their budget sheet -----------------------------------------------------

def bom_lines(tenant):
    load_master(tenant, "FG12801")
    load_master(tenant, "RMRT141")
    wo = send(tenant, "/api/erp/work-orders",
              [WO_HEADER, ["FG12801", "WIRING", "Supply", 7443, 765.75]],
              job_id=project(tenant)["id"]).json()["work_order"]
    res = send(tenant, "/api/erp/bom/analyse",
               [BOM_HEADER,
                ["FG12801", "RMRT141", "1.5SQMM FRLS WIRE RED", "Meters", 12405,
                 "SUPPLY", 100, 1, "", "", 12.22, 12.22, 151589.1]],
               work_order_id=wo["id"])
    assert res.status_code == 200, res.text
    return res.json()


def test_a_budget_sheet_that_heads_two_columns_the_same_is_read(tenant):
    """Their budget names the ordered item and its material both "Product Code".

    Neither word was in the budget vocabulary at all, so the whole file was
    refused with "no material code column found" - the step simply could not
    be completed with the sheet the business produces.
    """
    body = bom_lines(tenant)
    line = body["lines"][0]
    assert line["fg_code"] == "FG12801", "the left one is the item being sold"
    assert line["rm_code"] == "RMRT141", "the right one is what it consumes"
    assert not line["_problems"], line["_problems"]


def test_the_unit_column_is_not_read_as_the_quantity(tenant):
    """Their budget puts "Units" before "Quantity", and both matched quantity.

    Whichever field was written first in our vocabulary won, so the quantity
    column was the word "Meters" - which is nothing - and the real quantity
    was dropped. Every budgeted cost came out as zero.
    """
    line = bom_lines(tenant)["lines"][0]
    assert line["qty"] == 12405
    assert line["uom"] == "Meters"
    assert line["rate"] == 12.22
    assert line["amount"] == 151589.1


def test_both_columns_of_the_same_name_are_reported_back(tenant):
    """The mapping is shown to be checked, so it has to show both.

    Keyed by heading alone the second "Product Code" landed on top of the
    first, reporting one column where two were read, differently.
    """
    mapping = bom_lines(tenant)["mapping"]
    assert sorted(mapping.values()) == sorted(
        ["fg_code", "rm_code", "rm_name", "uom", "qty", "rate"])
    assert "Product Code" in mapping
    assert any(k.startswith("Product Code (column") for k in mapping)


def test_a_rate_quoted_past_the_paisa_is_kept(tenant):
    """Wire is quoted at 12.222 the metre, and 162 lines of this budget are.

    Rounded to 12.22 and taken across the metres actually being laid, the
    allocated budget drifts from the spreadsheet it was copied from - about
    six thousand rupees over this one project, on lines that each looked
    right. The amount is still money to the paisa; only the multiplier is
    held wider.
    """
    load_master(tenant, "FG12801")
    load_master(tenant, "RMRT141")
    wo = send(tenant, "/api/erp/work-orders",
              [WO_HEADER, ["FG12801", "WIRING", "Supply", 7443, 765.75]],
              job_id=project(tenant)["id"]).json()["work_order"]
    res = send(tenant, "/api/erp/bom/analyse",
               [BOM_HEADER,
                ["FG12801", "RMRT141", "1.5SQMM FRLS WIRE RED", "Meters", 12405,
                 "SUPPLY", 100, 1, "", "", 12.222, 12.222, 151613.91]],
               work_order_id=wo["id"])
    line = res.json()["lines"][0]
    assert line["rate"] == 12.222
    assert line["amount"] == 151613.91, "the figure the spreadsheet itself carries"


# --- Saying where the problem is --------------------------------------------

def test_a_complaint_names_the_row_somebody_can_scroll_to(tenant):
    """Line numbers are the whole value of the message on a 2,000 row sheet.

    Blank rows and the guidance row are dropped on the way in, and the count
    used to be taken after that - so the number in the message pointed at a
    row above the one that was actually wrong, by however many had been
    thrown away above it.
    """
    load_master(tenant, "FG12801")
    res = send(tenant, "/api/erp/work-orders",
               [WO_HEADER,
                WO_HINTS,                                    # sheet row 2
                ["FG12801", "WIRING", "Supply", 7443, 765.75],   # row 3
                [],                                          # row 4, blank
                ["FG99999", "WIRING", "Supply", 10, 5.0]],   # row 5, the bad one
               job_id=project(tenant)["id"])
    assert res.status_code == 200, res.text
    errors = res.json()["errors"]
    assert len(errors) == 1
    assert errors[0]["code"] == "FG99999"
    assert errors[0]["line"] == 5, "the row it is on in Excel"


# --- A subcontractor's own BOQ ----------------------------------------------
#
# The schedule usually arrives as the contractor's quotation with the rates
# already in it, headed however they head it. Retyping two hundred priced
# lines to make them match our template is how a rate gets typed wrong.

def wo_draft(tenant):
    unit = tenant.post("/api/wo/business-units", json={"name": "Y Projects"}).json()
    con = tenant.post("/api/wo/contractors",
                      json={"company_name": "Sri Balaji Civil Works"}).json()
    return tenant.post("/api/wo/orders", json={
        "business_unit_id": unit["id"], "contractor_id": con["id"],
        "job_id": project(tenant)["id"], "department": "Civil",
        "subject": "Civil works"}).json()["order"]


def import_boq(tenant, order, rows, **form):
    return tenant.post("/api/wo/orders/%d/boq/import" % order["id"],
                       files={"file": ("boq.xlsx", book(rows), XL)}, data=form)


BOQ_HEADER = ["Sl No", "Item Code", "Description of Work", "Specification",
              "Unit", "Quantity", "Rate"]


def test_a_contractors_own_boq_reads_without_being_retyped(tenant):
    order = wo_draft(tenant)
    res = import_boq(tenant, order, [
        BOQ_HEADER,
        ["1.0", "CIV-EXC", "Earthwork excavation up to 3 m depth",
         "Shoring and dewatering included", "cum", 2450, 312.5],
        ["2.0", "CIV-RMC", "M25 grade RMC pouring for raft",
         "Cube strength 25 MPa at 28 days", "cum", 840, 6420]])
    assert res.status_code == 200, res.text
    out = res.json()
    assert len(out["lines"]) == 2
    assert out["lines"][0]["item_description"].startswith("Earthwork")
    assert out["lines"][0]["technical_spec"].startswith("Shoring")
    assert out["lines"][1]["total_amount"] == 5392800.0
    assert out["gross_amount"] == 6158425.0


def test_the_import_does_not_save_anything_by_itself(tenant):
    """The lines land in the grid to be read against the file they came from.
    An import that read a column wrongly should be something somebody
    notices, not something they discover on the order."""
    order = wo_draft(tenant)
    import_boq(tenant, order, [BOQ_HEADER,
                               ["1.0", "CIV-EXC", "Excavation", "", "cum", 10, 100]])
    after = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    assert after["items"] == []
    assert after["gross_amount"] == 0


def test_the_grand_total_at_the_foot_is_not_read_as_a_line(tenant):
    order = wo_draft(tenant)
    res = import_boq(tenant, order, [
        BOQ_HEADER,
        ["1.0", "CIV-EXC", "Excavation", "", "cum", 2450, 312.5],
        ["", "", "", "", "", "", 765625]])
    out = res.json()
    assert len(out["lines"]) == 1
    assert out["skipped_rows"] == 1
    assert "left out" in out["message"]


def test_a_rate_written_with_commas_is_still_a_rate(tenant):
    """Read strictly, "12,34,567.50" is not a number at all - and on a rate
    column that is a line silently priced at nought."""
    order = wo_draft(tenant)
    res = import_boq(tenant, order, [
        BOQ_HEADER,
        ["1.0", "CIV-RMC", "M25 RMC", "", "cum", "1,200", "6,420.00"]])
    line = res.json()["lines"][0]
    assert line["quantity"] == 1200
    assert line["unit_rate"] == 6420.0
    assert line["total_amount"] == 7704000.0


def test_a_rate_past_the_paisa_keeps_its_places(tenant):
    order = wo_draft(tenant)
    res = import_boq(tenant, order, [
        BOQ_HEADER, ["1.0", "CIV-WS", "PVC water stop", "", "rmt", 100, 12.222]])
    assert res.json()["lines"][0]["unit_rate"] == 12.222


def test_the_typists_guidance_row_is_not_a_boq_line(tenant):
    order = wo_draft(tenant)
    res = import_boq(tenant, order, [
        BOQ_HEADER,
        ["Without Spaces", "", "", "", "", "Without comma (,) only num", ""],
        ["1.0", "CIV-EXC", "Excavation", "", "cum", 10, 100]])
    lines = res.json()["lines"]
    assert len(lines) == 1
    assert lines[0]["item_description"] == "Excavation"


def test_a_sheet_with_no_description_column_is_refused_by_name(tenant):
    order = wo_draft(tenant)
    res = import_boq(tenant, order, [["Code", "Unit", "Qty", "Rate"],
                                     ["CIV-EXC", "cum", 10, 100]])
    assert res.status_code == 400
    assert "Description" in res.json()["detail"]


def test_a_sheet_with_no_rate_column_is_refused(tenant):
    order = wo_draft(tenant)
    res = import_boq(tenant, order, [["Description of Work", "Unit", "Quantity"],
                                     ["Excavation", "cum", 10]])
    assert res.status_code == 400
    assert "rate" in res.json()["detail"]


def test_the_import_says_which_heading_it_read_as_what(tenant):
    order = wo_draft(tenant)
    res = import_boq(tenant, order, [
        BOQ_HEADER, ["1.0", "CIV-EXC", "Excavation", "", "cum", 10, 100]])
    read_as = res.json()["read_as"]
    assert read_as["Description of Work"] == "item_description"
    assert read_as["Rate"] == "unit_rate"


def test_an_activity_number_is_supplied_where_the_sheet_has_none(tenant):
    order = wo_draft(tenant)
    res = import_boq(tenant, order, [
        ["Description of Work", "Unit", "Quantity", "Rate"],
        ["Excavation", "cum", 10, 100],
        ["Raft and walls", "cum", 20, 200]])
    assert [line["activity_no"] for line in res.json()["lines"]] == ["1.0", "2.0"]


def test_a_submitted_order_will_not_take_an_import(tenant):
    order = wo_draft(tenant)
    tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": [
        {"item_description": "Excavation", "quantity": 10, "unit_rate": 100}]})
    tenant.put("/api/wo/orders/%d" % order["id"], json={
        "commencement_date": "2026-05-01", "completion_date": "2026-11-30",
        "department": "Civil", "subject": "Civil works",
        "business_unit_id": order["business_unit_id"],
        "contractor_id": order["contractor_id"], "job_id": order["job_id"]})
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = import_boq(tenant, order, [
        BOQ_HEADER, ["1.0", "CIV-EXC", "Excavation", "", "cum", 10, 100]])
    assert res.status_code == 409
