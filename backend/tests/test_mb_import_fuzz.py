"""A measurement book that arrives damaged - odd cells, blanks, text where numbers belong, a file that is not
a workbook at all - is answered with a reason, never with a server error, and records nothing it cannot read."""
import io
import random

import pytest

openpyxl = pytest.importorskip("openpyxl")

import sheet_forms
from test_delete_work_order import book, live_order

ODD = [None, "", "abc", "=1/0", "#DIV/0!", 1e308, -5, 0, "12,5", " ", "5%", "x" * 400, True, 3.14159, "1/2", "(10)", "0.0.1"]


def damaged(rnd, hits):
    wb = openpyxl.load_workbook(io.BytesIO(sheet_forms_template()))
    ws = wb.active
    for _ in range(hits):
        r, c = rnd.randint(1, ws.max_row + 2), rnd.randint(1, ws.max_column + 1)
        try:
            ws.cell(row=r, column=c).value = rnd.choice(ODD)
        except Exception:
            pass
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def sheet_forms_template():
    return sheet_forms.build_mb_template()


@pytest.mark.parametrize("seed", list(range(12)))
def test_a_damaged_workbook_never_breaks_the_import(tenant, seed):
    rnd = random.Random(seed)
    order = live_order(tenant, pay_advance=False)
    raw = damaged(rnd, rnd.randint(1, 12))
    preview = tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": ("mb.xlsx", raw)})
    assert preview.status_code < 500, preview.text[:300]
    before = len(book(tenant, order["id"])["entries"])
    res = tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": ("mb.xlsx", raw)}, data={"commit": "1"})
    assert res.status_code < 500, res.text[:300]
    after = book(tenant, order["id"])
    if res.status_code != 200:
        assert len(after["entries"]) == before
    for e in after["entries"]:
        assert e["quantity"] == e["quantity"] and abs(e["quantity"]) < 1e9    # no NaN or overflow reached the book


@pytest.mark.parametrize("blob,name", [(b"", "mb.xlsx"), (b"not a workbook", "mb.xlsx"), (b"PK\x03\x04junk", "mb.xlsx"), (b"a,b\n1,2\n", "mb.csv")])
def test_a_file_that_is_not_a_workbook_is_refused_plainly(tenant, blob, name):
    order = live_order(tenant, pay_advance=False)
    res = tenant.post("/api/sub-mb/%d/import" % order["id"], files={"file": (name, blob)})
    assert 400 <= res.status_code < 500, (res.status_code, res.text[:200])
    assert res.json().get("detail")
