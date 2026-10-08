"""A measurement book arrives in every shape the site can send it. It is read, or it is refused with a reason a
person can act on - never a server error, never a half-recorded book, never a block recorded twice."""
import io
import zipfile

import pytest

openpyxl = pytest.importorskip("openpyxl")

from app.validators import import_guard
from app.documents import sheet_forms
from test_delete_work_order import book, live_order


def template():
    return openpyxl.load_workbook(io.BytesIO(sheet_forms.build_mb_template()))


def dump(wb):
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def commit(tenant, order, raw, name="mb.xlsx", **form):
    return tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": (name, raw)}, data=dict({"commit": "1"}, **form))


def quantity_in_book(tenant, order):
    return round(sum(e["quantity"] for e in book(tenant, order["id"])["entries"]), 3)


def an_order(tenant):
    order = live_order(tenant, pay_advance=False)
    return order


def match_first_item(tenant, order):
    """The template section is for 'Shuttering ...'; map section 0 to the order's first item."""
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    return {"mapping": '{"0": %d}' % item}


def test_blank_rows_above_the_headings_are_no_problem(tenant):
    order = an_order(tenant)
    wb = template()
    wb.active.insert_rows(1, 12)
    res = commit(tenant, order, dump(wb), **match_first_item(tenant, order))
    assert res.status_code == 200, res.text
    assert quantity_in_book(tenant, order) == 114.4


def test_the_book_is_found_among_other_sheets_whatever_it_is_called(tenant):
    order = an_order(tenant)
    wb = template()
    wb.active.title = "Final measurement"
    wb.create_sheet("Cover", 0).append(["Bill 3", "Rani Labour Contractors"])
    wb.create_sheet("Notes", 0).append(["Nothing here"])
    res = commit(tenant, order, dump(wb), **match_first_item(tenant, order))
    assert res.status_code == 200, res.text
    assert quantity_in_book(tenant, order) == 114.4


def test_formulas_that_were_never_calculated_are_worked_out(tenant):
    """A workbook written by a program has no cached results; the figures have to come from the formulas."""
    order = an_order(tenant)
    wb = template()
    ws = wb.active
    ws["F8"] = "=6+6.5"
    ws["G8"] = "=4*2"
    ws["I10"] = "=SUM(I8:I9)"
    for ref in ("F8", "G8", "I10"):
        ws[ref].data_type = "f"             # real formulas, as a person's own workbook has - the app never writes one
    res = commit(tenant, order, dump(wb), **match_first_item(tenant, order))
    assert res.status_code == 200, res.text
    assert quantity_in_book(tenant, order) == 114.4


def test_figures_typed_as_text_are_read(tenant):
    order = an_order(tenant)
    wb = template()
    ws = wb.active
    ws["F8"] = "12,5"
    ws["G8"] = " 8 "
    ws["D9"] = "4"
    ws["F9"] = "6.0"
    res = commit(tenant, order, dump(wb), **match_first_item(tenant, order))
    assert res.status_code == 200, res.text
    assert quantity_in_book(tenant, order) == 114.4


def test_merged_headings_and_hidden_rows_do_not_confuse_the_reader(tenant):
    order = an_order(tenant)
    wb = template()
    ws = wb.active
    ws.merge_cells("A1:E1")
    ws.merge_cells("B7:D7")
    ws.row_dimensions[4].hidden = True
    ws.column_dimensions["J"].hidden = True
    res = commit(tenant, order, dump(wb), **match_first_item(tenant, order))
    assert res.status_code == 200, res.text
    assert quantity_in_book(tenant, order) == 114.4


def test_the_same_file_twice_records_the_block_once(tenant):
    order = an_order(tenant)
    raw = dump(template())
    opts = match_first_item(tenant, order)
    first = commit(tenant, order, raw, **opts)
    assert first.status_code == 200, first.text
    second = commit(tenant, order, raw, **opts)
    assert second.status_code in (200, 409), second.text
    assert quantity_in_book(tenant, order) == 114.4


def test_a_sheet_name_that_is_not_there_falls_back_to_the_book(tenant):
    order = an_order(tenant)
    res = commit(tenant, order, dump(template()), sheet="No such sheet", **match_first_item(tenant, order))
    assert res.status_code == 200, res.text


@pytest.mark.parametrize("blob,name,words", [
    (b"", "mb.xlsx", "empty"),
    (import_guard.OLE_SIGNATURE + b"\x00" * 600, "mb.xls", "old Excel"),
    (import_guard.OLE_SIGNATURE + b"\x00" * 600, "mb.xlsx", "password"),
    (b"PK\x03\x04" + b"\x00" * 40, "mb.xlsx", "readable|damaged|not an Excel"),
    (b"just words", "mb.xlsx", "readable|damaged|not an Excel"),
])
def test_files_that_cannot_be_read_say_why(tenant, blob, name, words):
    import re
    order = an_order(tenant)
    for commit_flag in ("0", "1"):
        res = tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": (name, blob)}, data={"commit": commit_flag})
        assert res.status_code == 400, (res.status_code, res.text[:200])
        assert re.search(words, res.json()["detail"], re.I), res.json()["detail"]


def test_a_workbook_that_is_far_too_large_is_refused_before_it_is_opened(tenant):
    order = an_order(tenant)
    res = tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": ("mb.xlsx", b"\x00" * (16 * 1024 * 1024))})
    assert res.status_code == 400 and "limit" in res.json()["detail"]


def test_a_zip_that_unpacks_into_gigabytes_is_refused(tenant):
    order = an_order(tenant)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        with z.open("xl/worksheets/sheet1.xml", "w") as out:
            chunk = b"\x00" * (1024 * 1024)
            for _ in range(260):
                out.write(chunk)
    res = tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": ("mb.xlsx", buf.getvalue())})
    assert res.status_code == 400, res.text[:200]
    assert "unpacks" in res.json()["detail"]


def test_a_csv_is_told_to_be_a_workbook(tenant):
    order = an_order(tenant)
    res = tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": ("mb.csv", b"S.No,Description\n1,Slab\n")})
    assert res.status_code == 400 and res.json()["detail"]


def test_a_failed_import_leaves_the_book_as_it_was(tenant):
    order = an_order(tenant)
    item = book(tenant, order["id"])["lines"][0]
    wb = template()
    wb.active["I10"] = None
    wb.active["F8"] = 999999        # past what the order allows: nothing at all is recorded
    wb.active["G8"] = 999999
    before = len(book(tenant, order["id"])["entries"])
    res = commit(tenant, order, dump(wb), mapping='{"0": %d}' % item["item_id"])
    assert res.status_code in (200, 400, 409)
    if res.status_code != 200:
        assert len(book(tenant, order["id"])["entries"]) == before


@pytest.mark.parametrize("blob,name,words", [
    (b"", "boq.xlsx", "empty|no rows|could not"),
    (import_guard.OLE_SIGNATURE + b"\x00" * 600, "boq.xls", "old Excel"),
    (import_guard.OLE_SIGNATURE + b"\x00" * 600, "boq.xlsx", "password"),
    (b"PK\x03\x04" + b"\x00" * 40, "boq.xlsx", "readable|damaged|not an Excel|could not"),
])
def test_the_schedule_import_refuses_what_it_cannot_read_in_plain_words(tenant, blob, name, words):
    import re
    from test_subcontract_orders import draft
    order = draft(tenant, department="Civil")
    res = tenant.post("/api/wo/orders/%d/boq/import" % order["id"], files={"file": (name, blob)})
    assert 400 <= res.status_code < 500, (res.status_code, res.text[:200])
    assert re.search(words, res.json()["detail"], re.I), res.json()["detail"]


def test_the_registration_forms_import_refuses_a_damaged_workbook(tenant):
    res = tenant.post("/api/wo/contractors/import", files={"file": ("forms.xlsx", b"PK\x03\x04" + b"\x00" * 40)})
    assert 400 <= res.status_code < 500, (res.status_code, res.text[:200])
