"""Opening a file before deciding what it is.

Every other upload asks you to declare a file's purpose before it will open
it, so a file that is not what you assumed is refused with a message about a
missing column - on a sheet you never chose, in a workbook with eight tabs.
These cover looking first: every tab listed, any tab readable, the headings
found wherever they actually start, and a plain answer when the file is not
something this system imports at all.
"""
import io

import openpyxl


XL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def workbook(sheets):
    """A real .xlsx of {name: rows}, in the order given."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def inspect(tenant, sheets, sheet=""):
    return tenant.post("/api/erp/sheets/inspect",
                       files={"file": ("book.xlsx", workbook(sheets), XL)},
                       data={"sheet": sheet})


ITEM_ROWS = [
    ["Item Code", "Item Name", "Segment", "Description", "Category",
     "Sub Category", "HSN Code", "Item Tax Type", "Item Type",
     "Units Of Measure", "Make"],
    ["RMRT141", "1.5SQMM WIRE RED", "YPPL", "1.5SQMM WIRE RED", "RAW MATERIAL",
     "RM", "995461", 0.18, "Purchased", "Meters", "Make List"],
]

# A programme: a title, a company, a project, and only then the headings.
SCHEDULE_ROWS = [
    ["SCHEDULE"],
    ["", "", "TIME DURATION IN DAYS", "", 259],
    ["YALAVARTI INFRA PROJECTS Ltd."],
    ["PROJECT - Proposed Construction"],
    ["SL.NO", "ITEMES / ACTIVITY", "Start", "End", "No of working Days", "U.O.M", "Quantity"],
    [1, "Footings - PCC", "2026-06-29", "2026-07-03", 4],
    [2, "Footings - Steel", "2026-07-04", "2026-07-10", 6],
]


# --- Every tab, not just the first ------------------------------------------

def test_every_sheet_in_the_workbook_is_listed(tenant):
    """A workbook off a real desk is rarely one sheet.

    A programme arrives with a Gantt chart, two revisions of it and a manpower
    tab. Reading whichever was saved first judges the file on a sheet nobody
    meant to send.
    """
    res = inspect(tenant, [("GH", SCHEDULE_ROWS), ("Items", ITEM_ROWS),
                           ("Manpower", [["Trade", "Count"], ["Painter", 20]])])
    assert res.status_code == 200, res.text
    body = res.json()
    assert [s["name"] for s in body["sheets"]] == ["GH", "Items", "Manpower"]
    assert body["sheet"] == "GH", "the first is shown until another is asked for"


def test_a_later_sheet_can_be_asked_for_by_name(tenant):
    body = inspect(tenant, [("GH", SCHEDULE_ROWS), ("Items", ITEM_ROWS)],
                   sheet="Items").json()
    assert body["sheet"] == "Items"
    assert body["guess"]["kind"] == "items"
    assert body["rows"][0][0] == "RMRT141"


def test_a_sheet_can_be_asked_for_by_position(tenant):
    body = inspect(tenant, [("GH", SCHEDULE_ROWS), ("Items", ITEM_ROWS)],
                   sheet="1").json()
    assert body["sheet"] == "Items"


def test_asking_for_a_sheet_that_is_not_there_says_what_is(tenant):
    """The message has to carry the way forward, not just the refusal."""
    res = inspect(tenant, [("GH", SCHEDULE_ROWS), ("Items", ITEM_ROWS)], sheet="Nope")
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "'GH'" in detail and "'Items'" in detail


# --- Finding the headings ---------------------------------------------------

def test_headings_are_found_below_a_title_block(tenant):
    """Real sheets open with a title, a company and a project.

    Taking row one on faith reads "SCHEDULE" as the entire header and
    everything under it as data.
    """
    body = inspect(tenant, [("GH", SCHEDULE_ROWS)]).json()
    assert body["header_row"] == 5
    assert body["header"][:2] == ["SL.NO", "ITEMES / ACTIVITY"]
    assert body["total_rows"] == 2
    assert body["rows"][0][1] == "Footings - PCC"


def test_a_sheet_headed_on_its_first_row_is_left_alone(tenant):
    """The detection must not go looking for a better header than the real one."""
    body = inspect(tenant, [("Items", ITEM_ROWS)]).json()
    assert body["header_row"] == 1
    assert body["header"][0] == "Item Code"


# --- Saying what the sheet is -----------------------------------------------

def test_a_sheet_we_know_is_named_as_such(tenant):
    body = inspect(tenant, [("Items", ITEM_ROWS)]).json()
    assert body["guess"]["kind"] == "items"
    assert body["guess"]["label"] == "Item master"


def test_a_sheet_we_do_not_know_says_so_rather_than_guessing(tenant):
    """A programme is not an item master, and should not be offered as one.

    It has a quantity and a unit column, which is enough to look like several
    things. Without a code column it is none of them.
    """
    body = inspect(tenant, [("GH", SCHEDULE_ROWS)]).json()
    assert body["guess"]["kind"] == ""
    # Still one entry per column, so the grid stays aligned - just no column
    # claimed by any importer.
    assert not any(body["fields"])


def test_the_columns_are_reported_by_position_not_by_heading(tenant):
    """A budget sheet heads two different columns "Product Code".

    Reported by heading text the second lands on top of the first, and the
    grid labels both of them whatever the first turned out to be.
    """
    rows = [["Product Code", "Product Code", "Product Name", "Units", "Quantity",
             "Payment Type", "RATE"],
            ["FG12801", "RMRT141", "1.5SQMM WIRE RED", "Meters", 12405, "SUPPLY", 12.222]]
    body = inspect(tenant, [("Sheet1", rows)]).json()
    assert body["guess"]["kind"] == "bom"
    assert body["fields"][0] == "fg_code"
    assert body["fields"][1] == "rm_code", "the second one is the material"
    assert body["fields"][3] == "uom" and body["fields"][4] == "qty"


# --- What it does not do ----------------------------------------------------

def test_looking_at_a_file_saves_nothing(tenant):
    before = tenant.get("/api/erp/items").json()["items"]
    inspect(tenant, [("Items", ITEM_ROWS)])
    assert tenant.get("/api/erp/items").json()["items"] == before


def test_a_csv_is_opened_the_same_way(tenant):
    csv = (b"Item Code,Item Name,Category,Sub Category,Units Of Measure\r\n"
           b"RMRT141,1.5SQMM WIRE RED,RAW MATERIAL,RM,Meters\r\n")
    res = tenant.post("/api/erp/sheets/inspect",
                      files={"file": ("s.csv", csv, "text/csv")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["sheets"]) == 1
    assert body["guess"]["kind"] == "items"
    assert body["rows"][0][0] == "RMRT141"


# --- Choosing the sheet on the way in ---------------------------------------

def import_items(tenant, sheets, sheet=""):
    return tenant.post("/api/erp/items/analyse",
                       files={"file": ("book.xlsx", workbook(sheets), XL)},
                       data={"sheet": sheet})


def test_an_import_reads_the_sheet_it_was_given(tenant):
    """The picker is pointless if the importer ignores it.

    The codes are on the second tab here, behind a programme. Reading whichever
    was saved first refuses the file over a column that is one tab away.
    """
    res = import_items(tenant, [("GH", SCHEDULE_ROWS), ("Items", ITEM_ROWS)],
                       sheet="Items")
    assert res.status_code == 200, res.text
    assert res.json()["rows"][0]["item_code"] == "RMRT141"


def test_without_a_choice_the_first_sheet_is_still_read(tenant):
    res = import_items(tenant, [("GH", SCHEDULE_ROWS), ("Items", ITEM_ROWS)])
    assert res.status_code == 400, "the programme has no item codes on it"


def test_a_refusal_names_the_sheet_it_read_and_the_others(tenant):
    """Being told a column is missing is no use when the file has eight tabs.

    The message has to say which one it was looking at, or the person cannot
    tell a wrong file from a wrongly-chosen sheet.
    """
    res = import_items(tenant, [("GH", SCHEDULE_ROWS), ("Items", ITEM_ROWS)])
    detail = res.json()["detail"]
    assert "'GH'" in detail, "the sheet it actually read"
    assert "'Items'" in detail, "and the one it did not"


def test_a_single_sheet_file_is_not_nagged_about_sheets(tenant):
    """Nothing to choose between, so the refusal stays short."""
    res = import_items(tenant, [("GH", SCHEDULE_ROWS)])
    assert res.status_code == 400
    assert "sheet" not in res.json()["detail"].lower()


def test_a_work_order_can_be_read_off_a_chosen_sheet(tenant):
    wo_rows = [["Product Code", "Product Name", "Product Discription", "Quantity", "Price"],
               ["FG0001", "WIRING", "Supply", 100, 60]]
    tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "WIRING", "units_of_measure": "Meters"}]})
    res = tenant.post("/api/erp/work-orders/analyse",
                      files={"file": ("b.xlsx", workbook(
                          [("GH", SCHEDULE_ROWS), ("Order", wo_rows)]), XL)},
                      data={"sheet": "Order"})
    assert res.status_code == 200, res.text
    assert res.json()["lines"][0]["qty"] == 100
