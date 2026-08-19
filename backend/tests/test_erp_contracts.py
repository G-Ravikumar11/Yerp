"""Item master, work orders and BOM, hung off the existing job.

The chain these enforce: a code has to exist before it can be sold, a line has
to be sold before it can be budgeted, and an order has to be budgeted before
anyone can approve it. Each link is one of these tests.
"""
import uuid

from conftest import make_employee


PASSWORD = "Crew1234"

ITEM_HEADER = ("Item Code,Item Name,Segment,Description,Category,Sub Category,"
               "HSN Code,Item Tax Type,Item Type,Units Of Measure,Make\r\n")
WO_HEADER = "FG Code,Item Name,Description,Qty,UOM,Rate\r\n"
BOM_HEADER = "FG Code,RM Code,RM Name,Qty,UOM,Rate\r\n"


def sheet(header, *rows):
    """CRLF line endings, exactly as Excel writes them."""
    return (header + "".join(r + "\r\n" for r in rows)).encode("utf-8-sig")


def item_row(code, name, kind, itype="Purchased", uom="Meters"):
    cat = "RAW MATERIAL" if kind == "RM" else "FINISHED GOOD"
    return f"{code},{name},YPPL,{name},{cat},{kind},3917,18%,{itype},{uom},Make List"


def upload_items(tenant, kind, *rows):
    return tenant.post("/api/erp/items/upload",
                       files={"file": ("i.csv", sheet(ITEM_HEADER, *rows), "text/csv")},
                       data={"kind": kind})


def make_job(tenant, **over):
    payload = {"name": "Fairview plot 3", "customer_name": "Fairview Homes",
               "status": "in_progress"}
    payload.update(over)
    r = tenant.post("/api/jobs", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def seed_codes(tenant):
    upload_items(tenant, "RM", item_row("RM1", "20MM CONDUIT", "RM"),
                 item_row("RM2", "20MM COUPLER", "RM", uom="Nos"))
    upload_items(tenant, "FG", item_row("FG1", "20MM CONDUIT SUPPLY", "FG"),
                 item_row("FG2", "INSTALLATION", "FG", itype="Service"))


# --- Item master ------------------------------------------------------------

def test_a_template_round_trips(tenant):
    """The sheet the app hands out has to be one the app accepts back."""
    for kind in ("RM", "FG"):
        tpl = tenant.get(f"/api/erp/items/template?kind={kind}").content
        # Templates go out as real workbooks now, and a workbook is a zip.
        assert tpl[:4] == b"PK", "the template should be a workbook"
        r = tenant.post("/api/erp/items/validate",
                        files={"file": ("t.xlsx", tpl, "application/octet-stream")},
                        data={"kind": kind})


def test_codes_upload(tenant):
    r = upload_items(tenant, "RM", item_row("RM1", "20MM CONDUIT", "RM"))
    assert r.status_code == 200 and r.json()["created"] == 1, r.text
    assert tenant.get("/api/erp/items").json()["counts"]["RM"] == 1


def test_a_duplicate_fg_code_is_refused(tenant):
    upload_items(tenant, "FG", item_row("FG1", "SUPPLY", "FG"))
    r = upload_items(tenant, "FG", item_row("FG1", "SUPPLY AGAIN", "FG")).json()
    assert r["created"] == 0
    assert "unique" in r["errors"][0]["message"]


def test_a_duplicate_rm_code_is_reused_not_refused(tenant):
    upload_items(tenant, "RM", item_row("RM1", "20MM CONDUIT", "RM"))
    r = upload_items(tenant, "RM", item_row("RM1", "20MM CONDUIT", "RM"),
                     item_row("RM9", "90MM CONDUIT", "RM")).json()
    assert r["ok"] is True
    assert r["created"] == 1, "the existing material is reused, the new one created"
    assert "reused" in r["warnings"][0]["message"]


def test_a_code_repeated_inside_one_sheet_is_refused(tenant):
    r = upload_items(tenant, "RM", item_row("RM1", "A", "RM"), item_row("RM1", "B", "RM")).json()
    assert r["created"] == 0
    assert "Duplicated in this file" in r["errors"][0]["message"]


def test_the_wrong_category_for_the_kind_is_refused(tenant):
    bad = item_row("FG1", "MISLABELLED", "RM")  # RAW MATERIAL on an FG upload
    r = upload_items(tenant, "FG", bad).json()
    assert r["created"] == 0
    assert "FINISHED GOOD" in r["errors"][0]["message"]


def test_a_sheet_that_is_not_a_sheet_is_a_400_not_a_500(tenant):
    r = tenant.post("/api/erp/items/upload",
                    files={"file": ("x.csv", b"", "text/csv")}, data={"kind": "RM"})
    assert r.status_code == 400, r.text


def test_codes_are_per_business(client):
    def register():
        email = f"user-{uuid.uuid4().hex[:10]}@example.com"
        client.post("/api/client/register", json={"email": email, "password": "Passw0rdTest"})
        client.post("/api/client/login", json={"email": email, "password": "Passw0rdTest"})

    register()
    upload_items(client, "FG", item_row("FG1", "THEIRS", "FG"))
    register()
    # The same code is free for another business to use.
    assert upload_items(client, "FG", item_row("FG1", "OURS", "FG")).json()["created"] == 1


# --- Work orders ------------------------------------------------------------

def test_a_work_order_prices_the_sold_scope(tenant):
    seed_codes(tenant)
    job = make_job(tenant)
    r = tenant.post("/api/erp/work-orders",
                    files={"file": ("wo.csv", sheet(WO_HEADER,
                           "FG1,20MM CONDUIT SUPPLY,supply,5000,Meters,62",
                           "FG2,INSTALLATION,install,5000,Meters,18"), "text/csv")},
                    data={"job_id": job["id"]}).json()
    assert r["work_order"]["total_value"] == 400000.0
    assert r["work_order"]["line_count"] == 2
    assert r["work_order"]["job_name"].startswith(job["number"])


def test_an_unknown_fg_code_is_the_gate(tenant):
    """The whole point of the item-upload step."""
    seed_codes(tenant)
    job = make_job(tenant)
    r = tenant.post("/api/erp/work-orders",
                    files={"file": ("wo.csv", sheet(WO_HEADER,
                           "FGNOPE,GHOST,x,10,Nos,5"), "text/csv")},
                    data={"job_id": job["id"]}).json()
    assert r["work_order"] is None
    assert "Upload this FG code first" in r["errors"][0]["message"]


def test_an_rm_code_cannot_be_sold(tenant):
    seed_codes(tenant)
    job = make_job(tenant)
    r = tenant.post("/api/erp/work-orders",
                    files={"file": ("wo.csv", sheet(WO_HEADER, "RM1,RAW,x,10,Meters,5"), "text/csv")},
                    data={"job_id": job["id"]}).json()
    assert r["work_order"] is None, "raw material is not a deliverable"


# --- Budget / BOM -----------------------------------------------------------

def order_with_budget(tenant):
    seed_codes(tenant)
    job = make_job(tenant)
    wo = tenant.post("/api/erp/work-orders",
                     files={"file": ("wo.csv", sheet(WO_HEADER,
                            "FG1,SUPPLY,supply,5000,Meters,62"), "text/csv")},
                     data={"job_id": job["id"]}).json()["work_order"]
    tenant.post("/api/erp/bom",
                files={"file": ("b.csv", sheet(BOM_HEADER,
                       "FG1,RM1,20MM CONDUIT,5100,Meters,46"), "text/csv")},
                data={"work_order_id": wo["id"]})
    return job, wo


def test_the_budget_gives_the_order_a_margin(tenant):
    job, wo = order_with_budget(tenant)
    after = tenant.get(f"/api/erp/work-orders/{wo['id']}").json()
    assert after["total_value"] == 310000.0
    assert after["budget_cost"] == 234600.0
    assert after["margin"] == 75400.0
    assert after["budgeted"] is True


def test_budgeting_a_line_that_was_never_sold_is_refused(tenant):
    job, wo = order_with_budget(tenant)
    r = tenant.post("/api/erp/bom",
                    files={"file": ("b.csv", sheet(BOM_HEADER,
                           "FG2,RM1,X,10,Meters,5"), "text/csv")},
                    data={"work_order_id": wo["id"]}).json()
    assert r["created"] == 0
    assert "Only sold lines can be budgeted" in r["errors"][0]["message"]


def test_re_uploading_replaces_rather_than_doubles(tenant):
    job, wo = order_with_budget(tenant)
    tenant.post("/api/erp/bom",
                files={"file": ("b.csv", sheet(BOM_HEADER,
                       "FG1,RM1,20MM CONDUIT,1000,Meters,10"), "text/csv")},
                data={"work_order_id": wo["id"]})
    after = tenant.get(f"/api/erp/work-orders/{wo['id']}").json()
    assert after["budget_cost"] == 10000.0, "the second upload replaces the first"


def test_an_unknown_rm_code_is_refused(tenant):
    job, wo = order_with_budget(tenant)
    r = tenant.post("/api/erp/bom",
                    files={"file": ("b.csv", sheet(BOM_HEADER,
                           "FG1,RMNOPE,GHOST,10,Meters,5"), "text/csv")},
                    data={"work_order_id": wo["id"]}).json()
    assert "Upload this RM code first" in r["errors"][0]["message"]


# --- Approval and job costing ----------------------------------------------

def test_an_unbudgeted_order_cannot_be_sent_for_approval(tenant):
    seed_codes(tenant)
    job = make_job(tenant)
    wo = tenant.post("/api/erp/work-orders",
                     files={"file": ("wo.csv", sheet(WO_HEADER,
                            "FG1,SUPPLY,supply,10,Meters,5"), "text/csv")},
                     data={"job_id": job["id"]}).json()["work_order"]
    r = tenant.post(f"/api/erp/work-orders/{wo['id']}/submit")
    assert r.status_code == 409
    assert "budget" in r.json()["detail"].lower()


def test_a_budgeted_order_goes_up_the_same_chain_as_everything_else(tenant):
    boss = make_employee(tenant, permission_role="manager", password=PASSWORD)
    tenant.put(f"/api/employees/{boss['id']}", json={"status": "active"})
    me = make_employee(tenant, reports_to=boss["id"], password=PASSWORD,
                       email=tenant.get("/api/client/me").json()["email"])
    tenant.put(f"/api/employees/{me['id']}", json={"status": "active"})

    job, wo = order_with_budget(tenant)
    r = tenant.post(f"/api/erp/work-orders/{wo['id']}/submit")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"

    after = tenant.get(f"/api/erp/work-orders/{wo['id']}").json()
    assert after["status"] == "Awaiting Approval"
    assert after["approval_status"] == "pending"
    # It is a step on the same chain that bills and purchase orders use.
    assert len(after["approval_history"]) == 1


def test_the_job_shows_what_was_sold_and_what_it_should_cost(tenant):
    job, wo = order_with_budget(tenant)
    costing = tenant.get(f"/api/jobs/{job['id']}").json()["costing"]
    assert costing["ordered"] == 310000.0
    assert costing["budgeted"] == 234600.0
    assert costing["expected_margin"] == 75400.0
    assert costing["counts"]["work_orders"] == 1


def test_an_approved_order_cannot_be_deleted(tenant):
    job, wo = order_with_budget(tenant)
    # No reporting line, so submitting approves it outright.
    me = make_employee(tenant, password=PASSWORD,
                       email=tenant.get("/api/client/me").json()["email"])
    tenant.put(f"/api/employees/{me['id']}", json={"status": "active"})
    tenant.post(f"/api/erp/work-orders/{wo['id']}/submit")
    assert tenant.delete(f"/api/erp/work-orders/{wo['id']}").status_code == 409


def test_a_stranger_gets_nothing(client):
    assert client.get("/api/erp/items").status_code == 401
    assert client.get("/api/erp/work-orders").status_code == 401
