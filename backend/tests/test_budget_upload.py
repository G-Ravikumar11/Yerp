"""The budget filled in Excel and uploaded back by the Master: only lines not yet budgeted are filled, a line budgeted in
the app is never changed or entered twice, a bad figure is listed and skipped, and uploading the same sheet again adds nothing."""
import io

import openpyxl

from test_budgeting import RCC_ITEMS, keyed, put_line, row_of
from test_subcontract_orders import sign_in, staff


def download(tenant, jid):
    res = tenant.get("/api/jobs/%d/budget.xlsx" % jid)
    assert res.status_code == 200, res.text
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    ws = wb.active
    head = next(r for r in ws.iter_rows() if [c.value for c in r][:2] == ["Item", "Description"])
    cols = {c.value: c.column for c in head}
    lines = {}
    for r in ws.iter_rows(min_row=head[0].row + 1):
        if r[0].value == "Total":
            break
        lines[r[1].value] = r[0].row
    return wb, ws, cols, lines


def fill(ws, cols, lines, description, material=None, labour=None, other=None):
    at = lines[description]
    for heading, v in (("Material per unit", material), ("Labour per unit", labour), ("Plant & other per unit", other)):
        if v is not None:
            ws.cell(at, cols[heading]).value = v


def as_file(wb):
    buf = io.BytesIO()
    wb.save(buf)
    return {"file": ("budget.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def descriptions(tenant, jid):
    b = tenant.get("/api/jobs/%d/budget" % jid).json()
    return {r["key"]: r["description"] for r in b["rows"]}


def test_only_the_lines_not_yet_budgeted_are_filled_and_the_rest_are_left_as_they_are(tenant):
    jid, k = keyed(tenant)
    put_line(tenant, jid, k["RCC"], RCC_ITEMS)                            # half done in the app before the download
    words = descriptions(tenant, jid)
    wb, ws, cols, lines = download(tenant, jid)
    fill(ws, cols, lines, words[k["EXC"]], labour=180, other=40)
    fill(ws, cols, lines, words[k["RCC"]], material=1, labour=1)            # changed in Excel, but already budgeted in the app
    fill(ws, cols, lines, words[k["MAS"]], material="abc")                  # not a number
    # FWK left empty for later

    p = tenant.post("/api/jobs/%d/budget/upload/preview" % jid, files=as_file(wb))
    assert p.status_code == 200, p.text
    by = {r["key"]: r for r in p.json()["rows"] if r["key"]}
    assert by[k["EXC"]]["status"] == "add" and by[k["RCC"]]["status"] == "kept" and by[k["FWK"]]["status"] == "empty"
    assert p.json()["counts"] == {"add": 1, "kept": 1, "empty": 1, "error": 1}
    assert "other figures" in by[k["RCC"]]["message"]
    assert "not a number" in next(r for r in p.json()["rows"] if r["status"] == "error")["message"]
    assert tenant.get("/api/jobs/%d/budget" % jid).json()["total"]["lines_budgeted"] == 1, "a preview saves nothing"

    res = tenant.post("/api/jobs/%d/budget/upload" % jid, files=as_file(wb))
    assert res.status_code == 200, res.text
    assert res.json()["added"] == 1
    b = res.json()["budget"]
    exc = row_of(b, k["EXC"])
    assert (exc["unit_labour"], exc["unit_other"], exc["unit_material"]) == (180, 40, 0)
    rcc = row_of(b, k["RCC"])
    assert (rcc["unit_material"], rcc["unit_labour"]) == (5000, 800), "the app's budget is kept, not the sheet's"
    assert [i["description"] for i in rcc["items"]] == ["Ready-mix M25", "Mason and helpers"]
    assert not row_of(b, k["FWK"])["budgeted"] and not row_of(b, k["MAS"])["budgeted"]

    again = tenant.post("/api/jobs/%d/budget/upload" % jid, files=as_file(wb))
    assert again.json()["added"] == 0, "the same sheet twice enters nothing twice"
    assert row_of(again.json()["budget"], k["EXC"])["items"] == exc["items"]


def test_amounts_for_the_whole_line_are_worked_back_to_one_unit(tenant):
    jid, k = keyed(tenant)
    words = descriptions(tenant, jid)
    wb, ws, cols, lines = download(tenant, jid)
    ws.cell(lines[words[k["RCC"]]], cols["Material"]).value = 600000         # 120 cum
    res = tenant.post("/api/jobs/%d/budget/upload" % jid, files=as_file(wb))
    assert res.status_code == 200, res.text
    assert row_of(res.json()["budget"], k["RCC"])["unit_material"] == 5000


def test_a_row_not_in_the_boq_is_listed_and_not_the_wrong_sheet(tenant):
    jid, k = keyed(tenant)
    wb, ws, cols, lines = download(tenant, jid)
    at = max(lines.values())
    ws.insert_rows(at + 1)
    ws.cell(at + 1, 1).value, ws.cell(at + 1, 2).value = "9.9", "Waterproofing not in the BOQ"
    ws.cell(at + 1, cols["Material per unit"]).value = 50
    rows = tenant.post("/api/jobs/%d/budget/upload/preview" % jid, files=as_file(wb)).json()["rows"]
    assert any(r["status"] == "error" and "not in the project's BOQ" in r["message"] for r in rows)

    other = openpyxl.Workbook()
    other.active.append(["Name", "Amount"])
    res = tenant.post("/api/jobs/%d/budget/upload/preview" % jid, files=as_file(other))
    assert res.status_code == 400 and "not the budget sheet" in res.json()["detail"]


def test_only_the_master_uploads_a_budget(tenant):
    import main
    from fastapi.testclient import TestClient
    jid, k = keyed(tenant)
    wb, ws, cols, lines = download(tenant, jid)
    qs = staff(tenant, "ho_qs")                                            # may edit the budget line by line, not upload
    with TestClient(main.app) as q:
        sign_in(q, qs)
        assert q.post("/api/jobs/%d/budget/upload/preview" % jid, files=as_file(wb)).status_code == 403
        assert q.post("/api/jobs/%d/budget/upload" % jid, files=as_file(wb)).status_code == 403
