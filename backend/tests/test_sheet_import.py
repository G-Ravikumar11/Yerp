"""Lines read off a sheet come back to be fixed in the app - every row, with
what is wrong beside it - and nothing is saved by reading."""
import io

import openpyxl


def book(rows, header=("Item Code", "Material", "Unit", "Quantity", "Rate")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read(tenant, data, name="quote.xlsx"):
    return tenant.post("/api/sheets/po_lines/read",
                       files={"file": (name, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


def test_the_template_downloads(tenant):
    res = tenant.get("/api/sheets/po_lines/template.xlsx")
    assert res.status_code == 200
    ws = openpyxl.load_workbook(io.BytesIO(res.content)).active
    assert [c.value for c in ws[1]][:5] == ["Item Code", "Description", "UOM", "Qty", "Rate"]


def test_every_row_comes_back_with_what_is_wrong_and_the_total_row_is_left_out(tenant):
    tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "RM", "item_name": "OPC 53 CEMENT", "units_of_measure": "Bags"}]})
    code = tenant.get("/api/erp/items?kind=RM").json()["items"][0]["item_code"]
    res = read(tenant, book([
        (code, "", "", "400", "385"),                 # known code: name and unit filled in
        ("", "20mm aggregate", "cum", "30", "1,450"),  # grouped figure read as a number
        ("RM9999", "Sand", "cum", "", "900"),          # unknown code, no quantity
        ("", "", "", "", "1,88,000"),                  # the sheet's own grand total
    ]))
    assert res.status_code == 200, res.text
    out = res.json()
    assert len(out["rows"]) == 3 and out["skipped"] == 1
    first = out["rows"][0]
    assert first["description"] == "OPC 53 CEMENT" and first["uom"] == "Bags" and first["qty"] == 400
    assert out["rows"][1]["price"] == 1450
    assert "0" not in out["problems"] and "1" not in out["problems"]
    probs = " ".join(out["problems"]["2"])
    assert "RM9999" in probs and "quantity" in probs


def test_rows_fixed_in_the_grid_are_checked_again(tenant):
    res = tenant.post("/api/sheets/po_lines/check", json={"rows": [
        {"item_code": "", "description": "Sand", "uom": "cum", "qty": 0, "price": 900},
        {"item_code": "", "description": "Sand", "uom": "cum", "qty": 12, "price": 900}]})
    assert res.status_code == 200
    assert list(res.json()["problems"].keys()) == ["0"]


def test_a_sheet_with_no_columns_it_knows_is_refused_plainly(tenant):
    res = read(tenant, book([("x", "y")], header=("Foo", "Bar")))
    assert res.status_code == 400 and "template" in res.json()["detail"]


def test_a_csv_reads_too(tenant):
    csv = b"Description,Qty,Rate,UOM\nBinding wire,50,82,kg\n"
    res = tenant.post("/api/sheets/po_lines/read", files={"file": ("list.csv", csv, "text/csv")})
    assert res.status_code == 200, res.text
    assert res.json()["rows"][0]["description"] == "Binding wire"


def test_nothing_is_read_without_signing_in(client):
    assert client.post("/api/sheets/po_lines/read", files={"file": ("x.csv", b"a", "text/csv")}).status_code in (401, 403)
