"""However a measurement book states its hold, the quantity read is the quantity the sheet pays for.

Sheets write the hold many ways: "Hold 10 %" over "Total payable quantity"; "Total Qty To be paid"; "Release 45%";
"Retention 5%" over "Net quantity"; or rows with no telltale words at all, where the payable is simply the total
less the hold. The reader works from the sheet's figures, not from one phrase, and says so when the sheet
disagrees with itself."""
import io
import os
import random
import shutil

import pytest

openpyxl = pytest.importorskip("openpyxl")

import sheet_forms
from test_delete_work_order import book, live_order

HEADERS = ["S.No", "Description", "UoM", "No's", "NoM", "Length", "Width", "Height", "Total Quantity", "Remarks"]
HERE = os.path.dirname(os.path.abspath(__file__))


def sheet(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MB-1"
    ws.append(["Name of the Work:", "Test"])
    ws.append([])
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    return wb


def lines(n, base=10.0):
    """n lines of one length each, so the block comes to n * base * 2."""
    return [[None, "Wall %d" % i, "sqm", 1, 1, base, 2.0, None, base * 2.0, None] for i in range(n)]


def read(rows):
    wb = sheet(rows)
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    loaded = openpyxl.load_workbook(out, data_only=False)
    # the reader takes values and formulas; these sheets have plain values for both
    return sheet_forms.read_measurement_book(loaded["MB-1"], loaded["MB-1"])


def payable(b):
    """What the sheet pays: the measurement less what it holds back."""
    return round(sum(e["payable"] for i in b["items"] for e in i["entries"]), 3)


def no_line_written_into_the_measurement(b):
    return not any(d.get("holdback") or str(d.get("particulars") or "").lower().startswith("held back")
                   for i in b["items"] for e in i["entries"] for d in e["dims"])


def block(name, n, tail):
    total = n * 20.0
    return [[None, name]] + lines(n) + [[None, "Total Quantity", None, None, None, None, None, None, total]] + tail(total)


def test_hold_over_total_payable_and_two_blocks_under_one_item():
    """The shape of Demo Bill-1: no letters, no 'for N blocks', a hold row and a 'Total payable quantity' row."""
    rows = [["I", "Internal Hole Packing"]]
    rows += block("365 SFT-Block", 5, lambda t: [[None, "Hold 10 % for handing over", None, None, None, None, None, None, t * 0.1],
                                                  [None, "Total payable quantity", None, None, None, None, None, None, t * 0.9]])
    rows += block("430 SFT-Block", 8, lambda t: [[None, "Hold 10 % for handing over", None, None, None, None, None, None, t * 0.1],
                                                  [None, "Total payable quantity", None, None, None, None, None, None, t * 0.9]])
    b = read(rows)
    entries = b["items"][0]["entries"]
    assert [e["location"] for e in entries] == ["365 SFT-Block", "430 SFT-Block"]
    assert [round(e["quantity"], 3) for e in entries] == [100.0, 160.0]          # measured, as the sheet wrote it
    assert [e["held_back"] for e in entries] == [10.0, 16.0]
    assert [e["payable"] for e in entries] == [90.0, 144.0]
    assert [h["percent"] for h in b["holds"]] == [10.0, 10.0]
    assert no_line_written_into_the_measurement(b)
    assert not b["warnings"]


@pytest.mark.parametrize("hold_label,pay_label", [
    ("Hold 5 % for Finishes & Handing over", "Total Qty To be paid"),
    ("Retention 5%", "Net quantity"),
    ("Held back 5%", "Billable quantity"),
    ("Withheld", "Quantity payable now"),
    ("less: 5% to be kept back", "Net payable"),
])
def test_the_hold_is_read_whatever_it_is_called(hold_label, pay_label):
    rows = [["1", "Slab"]] + block("Block A", 4, lambda t: [[None, hold_label, None, None, None, None, None, None, t * 0.05],
                                                          [None, pay_label, None, None, None, None, None, None, t * 0.95]])
    b = read(rows)
    assert payable(b) == round(80 * 0.95, 3), (hold_label, pay_label, b["warnings"])


def test_a_payable_with_no_telltale_words_is_found_by_the_arithmetic():
    rows = [["1", "Slab"]] + block("Block A", 4, lambda t: [[None, "Kept back", None, None, None, None, None, None, t * 0.1],
                                                          [None, "Quantity for this bill", None, None, None, None, None, None, t * 0.9]])
    b = read(rows)
    assert payable(b) == 72.0
    assert b["items"][0]["entries"][0]["held_back"] == 8.0


def test_the_label_saying_five_percent_over_a_ten_percent_figure_is_said():
    rows = [["1", "Slab"]] + block("Block A", 4, lambda t: [[None, "Hold 5 % for Finishes", None, None, None, None, None, None, t * 0.10],
                                                          [None, "Total payable quantity", None, None, None, None, None, None, t * 0.90]])
    b = read(rows)
    assert payable(b) == 72.0                                   # the figures win
    assert any("5%" in w and "10%" in w for w in b["warnings"]), b["warnings"]


def test_a_sheet_whose_total_ignores_a_line_is_said_and_the_sheets_hold_percent_is_applied_to_the_lines():
    rows = [["1", "Slab"], [None, "Block A"]] + lines(4)
    rows[-1][8] = "`"                                          # a corrupted total cell on the last line (20 sqm)
    rows += [[None, "Total Quantity", None, None, None, None, None, None, 60.0],     # the sheet left that line out
             [None, "Hold 10 %", None, None, None, None, None, None, 6.0],
             [None, "Total payable quantity", None, None, None, None, None, None, 54.0]]
    b = read(rows)
    assert payable(b) == 72.0                                  # 10% held of the 80 the lines come to
    joined = " ".join(b["warnings"])
    assert "not a figure" in joined and "totals 60" in joined, b["warnings"]


def test_the_hold_is_kept_apart_from_the_blocks_so_their_totals_match_the_sheet():
    rows = [["1", "Slab"], ["a", "Block B19"]] + lines(5) + [
        [None, "Total Quantity for one Block", None, None, None, None, None, None, 100.0],
        [None, "Total Quantity for 4 Blocks", None, None, None, None, None, None, 400.0],
        [None, "Total Quantity before holding back", None, None, None, None, None, None, 400.0],
        [None, "Hold for Finishes", None, None, None, None, None, None, 220.0],
        [None, "Total Qty To be paid", None, None, None, None, None, None, 180.0]]
    b = read(rows)
    e = b["items"][0]["entries"][0]
    assert e["one"] == 100.0 and e["quantity"] == 400.0                    # one block and four blocks, as the sheet says
    assert no_line_written_into_the_measurement(b)
    assert abs(e["payable"] - 180.0) < 0.01 and abs(e["held_back"] - 220.0) < 0.01
    h = b["holds"][0]
    assert h["percent"] == 55.0 and "Hold for Finishes" in h["reason"] and abs(h["held"] - 220.0) < 0.01


@pytest.mark.parametrize("seed", range(25))
def test_random_books_pay_what_their_sheet_pays(seed):
    rnd = random.Random(seed)
    rows, expected, blocks = [["1", "Works"]], 0.0, 0
    for b in range(rnd.randint(1, 4)):
        n = rnd.randint(1, 6)
        pct = rnd.choice([2.5, 5, 10, 15, 25, 40, 55])
        style = rnd.choice(["hold_payable", "to_be_paid", "arith", "retention"])
        total = n * 20.0
        held = round(total * pct / 100.0, 6)
        pay = round(total - held, 6)
        rows.append([None, "Block %d" % b])
        rows += lines(n)
        rows.append([None, "Total Quantity", None, None, None, None, None, None, total])
        if style == "hold_payable":
            rows += [[None, "Hold %g %% for handing over" % pct, None, None, None, None, None, None, held],
                     [None, "Total payable quantity", None, None, None, None, None, None, pay]]
        elif style == "to_be_paid":
            rows += [[None, "Total Qty To be paid - %g%%" % (100 - pct), None, None, None, None, None, None, pay]]
        elif style == "retention":
            rows += [[None, "Retention %g%%" % pct, None, None, None, None, None, None, held],
                     [None, "Net quantity", None, None, None, None, None, None, pay]]
        else:
            rows += [[None, "Kept back", None, None, None, None, None, None, held],
                     [None, "For this bill", None, None, None, None, None, None, pay]]
        expected += pay
        blocks += 1
    b = read(rows)
    assert len(b["items"][0]["entries"]) == blocks
    assert abs(payable(b) - expected) < 0.01 * blocks, (seed, payable(b), expected, b["warnings"])
    assert not b["warnings"], b["warnings"]


def test_the_demo_bill_that_lost_its_hold_now_pays_what_the_sheet_pays(tenant):
    """Demo Bill-1: two blocks, each with 'Hold 10 % for handing over' and 'Total payable quantity'."""
    fixture = os.path.join(HERE, "data", "demo_bill_1.xlsx")
    if not os.path.exists(fixture):
        pytest.skip("fixture not present")
    wb = openpyxl.load_workbook(fixture, data_only=True, keep_links=False)
    wf = openpyxl.load_workbook(fixture, keep_links=False)
    b = sheet_forms.read_measurement_book(wb["MB-1"], wf["MB-1"])
    entries = b["items"][0]["entries"]
    assert [e["location"] for e in entries] == ["365 SFT-Block", "430 SFT-Block"]
    assert abs(entries[0]["quantity"] - 7059.4) < 0.01                        # measured, as the sheet wrote it
    assert abs(entries[0]["payable"] - 6353.46) < 0.01                        # the sheet's own payable
    assert abs(entries[1]["payable"] - 7902.115) < 0.01                       # 10% held of what its lines come to
    assert any("not a figure" in w for w in b["warnings"])                     # row 224's '`'
    # and through the whole import into an order
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]
    res = tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": ("bill.xlsx", open(fixture, "rb").read())},
                      data={"commit": "0"})
    assert res.status_code == 200, res.text
    sec = res.json()["sections"][0]
    assert [round(x["payable"], 1) for x in sec["entries"]] == [6353.5, 7902.1]
    assert [round(x["quantity"], 1) for x in sec["entries"]] == [7059.4, 8780.1]
    assert item


def test_importing_the_demo_bill_gives_a_bill_that_holds_what_the_sheet_holds(tenant):
    """From the file to the printed bill: both blocks, each holding 10%, and the PDF says what it took it from."""
    import pypdf
    from conftest import fund_order
    from test_subcontract_orders import draft
    fixture = os.path.join(HERE, "data", "demo_bill_1.xlsx")
    if not os.path.exists(fixture):
        pytest.skip("fixture not present")
    order = draft(tenant, department="Civil")
    res = tenant.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": [
        {"activity_no": "1.0", "item_description": "Internal hole packing", "uom": "Sqm", "quantity": 20000, "unit_rate": 100}]})
    order = fund_order(tenant, res.json()["order"])
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    order = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).json()["order"]
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    done = tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": ("bill.xlsx", open(fixture, "rb").read())},
                       data={"commit": "1", "mapping": '{"0": %d}' % item})
    assert done.status_code == 200, done.text
    line = book(tenant, order["id"])["lines"][0]
    assert abs(line["measured_to_date"] - 15839.528) < 0.01, line["measured_to_date"]   # measured
    assert abs(line["held"] - 1583.953) < 0.02 and abs(line["unbilled"] - 14255.575) < 0.02   # held, and what can be billed
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    pdf = tenant.get("/api/sub-bills/%d/document.pdf" % bill["id"])
    text = " ".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(pdf.content)).pages)
    text = " ".join(text.split())
    # the blocks print as the sheet measured them; the hold once under each, in the sheet's words
    assert "7,059.4" in text and "8,780.13" in text, text[:400]
    assert text.count("I INTERNAL HOLE PACKING") == 1, "a section heading prints once, not before every block"
    assert text.count("Hold 10 % for hsnding over") == 2, text[text.find("Hold"):text.find("Hold") + 300]
    assert "Total Qty To be paid" in text and "6,353.46" in text
