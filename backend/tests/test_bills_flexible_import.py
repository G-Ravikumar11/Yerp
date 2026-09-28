"""A workbook with its own headings and order can be read into bills."""
import io
import pytest


def workbook(header, *rows):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def test_a_differently_ordered_workbook_is_read(tenant):
    # Not the template's order or wording: Ref before Supplier, "Invoice Amt".
    data = workbook(["Invoice No", "Supplier", "Invoice Amt", "GST", "Invoice Date"],
                    ["INV-77", "Sri Sai Steels", "50000", "9000", "2026-09-01"])
    res = tenant.post("/api/sheets/bills/read", files={"file": ("b.xlsx", data,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert res.status_code == 200, res.text
    rows = res.json()["rows"]
    assert len(rows) == 1 and rows[0]["vendor_name"] == "Sri Sai Steels" and rows[0]["amount"] == 50000

    made = tenant.post("/api/sheets/bills/import", json={"rows": rows})
    assert made.status_code == 200, made.text
    assert made.json()["count"] == 1
    bills = tenant.get("/api/bills").json()
    assert any(b["vendor_name"] == "Sri Sai Steels" and b["status"] == "Draft" for b in bills)


def test_a_row_with_no_vendor_is_not_created(tenant):
    res = tenant.post("/api/sheets/bills/import", json={"rows": [{"vendor_name": "", "amount": 100}]})
    assert res.status_code == 200 and res.json()["count"] == 0
