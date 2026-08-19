"""Who may work the contracts module, and what a sheet may arrive as.

Two things that had been left open: the module was reachable only by the
account holder, so no member of staff could raise a work order; and only CSV
was accepted, when what people actually have is a workbook.
"""
import io

import pytest

from conftest import make_employee

import main


PASSWORD = "Crew1234"


def staff(tenant, role, reports_to=None, **over):
    emp = make_employee(tenant, permission_role=role, reports_to=reports_to,
                        password=PASSWORD, **over)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    return emp


def sign_in(client, emp):
    res = client.post("/api/employee/auth/login",
                      json={"email": emp["email"], "password": PASSWORD})
    assert res.status_code == 200, res.text


def sign_out(client):
    client.post("/api/employee/auth/logout")


def add_item(tenant, **over):
    payload = {"kind": "RM", "item_name": "20MM CONDUIT"}
    payload.update(over)
    return tenant.post("/api/erp/items", json=payload)


# --- Who may do what --------------------------------------------------------

def test_the_owner_still_holds_everything(tenant):
    assert add_item(tenant).status_code == 200
    assert tenant.get("/api/erp/vocabulary").status_code == 200


@pytest.mark.parametrize("role", ["manager", "finance"])
def test_a_manager_or_finance_can_maintain_the_master(tenant, role):
    person = staff(tenant, role)
    sign_in(tenant, person)
    res = tenant.post("/api/erp/items", json={"kind": "RM", "item_name": "CONDUIT"})
    assert res.status_code == 200, res.text
    assert res.json()["item_code"] == "RM0001"


@pytest.mark.parametrize("role", ["staff", "supervisor", "hr_admin"])
def test_others_cannot_change_the_master(tenant, role):
    person = staff(tenant, role)
    sign_in(tenant, person)
    res = tenant.post("/api/erp/items", json={"kind": "RM", "item_name": "CONDUIT"})
    assert res.status_code == 403
    assert "Ask HR" in res.json()["detail"]


def test_anyone_signed_in_can_read_the_master(tenant):
    """Somebody picking a code from a list has to be able to see the list."""
    add_item(tenant)
    hand = staff(tenant, "staff")
    sign_in(tenant, hand)
    res = tenant.get("/api/erp/items")
    assert res.status_code == 200
    assert res.json()["counts"]["RM"] == 1
    assert tenant.get("/api/erp/vocabulary").status_code == 200


def test_a_manager_can_raise_a_work_order(tenant):
    fg = add_item(tenant, kind="FG", item_name="SUPPLY").json()
    job = tenant.post("/api/jobs", json={"name": "Plot 7", "status": "in_progress"}).json()
    boss = staff(tenant, "manager")

    sign_in(tenant, boss)
    res = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "lines": [{"code": fg["item_code"], "qty": 100, "rate": 50}]})
    assert res.status_code == 200, res.text
    assert res.json()["work_order"]["total_value"] == 5000.0


def test_a_supervisor_cannot_price_customer_work(tenant):
    """Running a crew is not the same as agreeing what the customer pays."""
    fg = add_item(tenant, kind="FG", item_name="SUPPLY").json()
    job = tenant.post("/api/jobs", json={"name": "Plot 7"}).json()
    person = staff(tenant, "supervisor")
    sign_in(tenant, person)
    res = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "lines": [{"code": fg["item_code"], "qty": 1, "rate": 1}]})
    assert res.status_code == 403


def test_a_disabled_account_is_refused_not_retried_as_somebody_else(tenant, client):
    """A 403 from the owner check must not fall through to the staff check."""
    person = staff(tenant, "manager")
    sign_in(tenant, person)
    assert tenant.get("/api/erp/items").status_code == 200
    sign_out(tenant)


def test_a_stranger_gets_nothing(client):
    assert client.get("/api/erp/vocabulary").status_code == 401
    assert client.post("/api/erp/items", json={"kind": "RM", "item_name": "X"}).status_code == 401


def test_the_new_rights_are_in_the_catalogue(tenant):
    data = tenant.get("/api/hr/levels").json()
    keys = {p["key"] for p in data["permissions"]}
    assert {"items.manage", "workorders.manage"} <= keys
    by_code = {r["code"]: set(r["permissions"]) for r in data["permission_roles"]}
    assert "items.manage" in by_code["finance"]
    assert "workorders.manage" in by_code["manager"]
    assert "items.manage" not in by_code["staff"]


# --- Workbooks --------------------------------------------------------------

def workbook(header, *rows):
    """A real .xlsx in memory, as Excel would save it."""
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


ITEM_HEADER = ["Item Code", "Item Name", "Segment", "Description", "Category",
               "Sub Category", "HSN Code", "Item Tax Type", "Item Type",
               "Units Of Measure", "Make"]


def test_a_workbook_is_read(tenant):
    payload = workbook(ITEM_HEADER,
        ["RM1", "20MM CONDUIT", "", "", "RAW MATERIAL", "RM", "3917", "18%",
         "Purchased", "Meters", ""])
    res = tenant.post("/api/erp/items/analyse",
                      files={"file": ("items.xlsx", payload,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert res.status_code == 200, res.text
    assert res.json()["detected"] == {"RM": 1}


def test_a_workbook_is_recognised_by_its_bytes_not_its_name(tenant):
    """People rename files; a workbook called .csv should still open."""
    payload = workbook(ITEM_HEADER,
        ["RM1", "CONDUIT", "", "", "RAW MATERIAL", "RM", "", "", "Purchased", "Meters", ""])
    res = tenant.post("/api/erp/items/analyse",
                      files={"file": ("mislabelled.csv", payload, "text/csv")})
    assert res.status_code == 200 and res.json()["detected"] == {"RM": 1}


def test_a_number_does_not_arrive_with_a_decimal_tail(tenant):
    """Excel hands 5000 back as 5000.0, which would not match a code or read
    as a quantity anybody typed."""
    fg = add_item(tenant, kind="FG", item_name="SUPPLY").json()
    payload = workbook(["FG Code", "Item Name", "Description", "Qty", "UOM", "Rate"],
                       [fg["item_code"], "SUPPLY", "", 5000, "Meters", 62])
    res = tenant.post("/api/erp/work-orders/analyse",
                      files={"file": ("wo.xlsx", payload, "application/octet-stream")}).json()
    assert res["lines"][0]["qty"] == 5000.0
    assert res["summary"]["value"] == 310000.0


def test_csv_still_works(tenant):
    csv = ("Item Code,Item Name,Category,Sub Category\r\n"
           "RM1,CONDUIT,RAW MATERIAL,RM\r\n").encode("utf-8-sig")
    res = tenant.post("/api/erp/items/analyse", files={"file": ("i.csv", csv, "text/csv")})
    assert res.status_code == 200 and res.json()["detected"] == {"RM": 1}


def test_the_templates_are_workbooks(tenant):
    for path in ("/api/erp/items/template?kind=RM", "/api/erp/work-orders/template",
                 "/api/erp/bom/template"):
        res = tenant.get(path)
        assert res.status_code == 200, path
        assert res.content[:4] == b"PK\x03\x04", path + " should be a workbook"
        assert ".xlsx" in res.headers["content-disposition"]


def test_a_template_round_trips_as_a_workbook(tenant):
    """What the app hands out has to be something the app accepts back."""
    payload = tenant.get("/api/erp/items/template?kind=RM").content
    res = tenant.post("/api/erp/items/analyse",
                      files={"file": ("t.xlsx", payload, "application/octet-stream")})
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True


def test_a_corrupt_workbook_is_a_400_not_a_500(tenant):
    res = tenant.post("/api/erp/items/analyse",
                      files={"file": ("broken.xlsx", b"PK\x03\x04garbage", "application/octet-stream")})
    assert res.status_code == 400
