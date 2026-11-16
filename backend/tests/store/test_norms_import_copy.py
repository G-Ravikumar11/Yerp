"""Material norms brought in by the sheet or copied from another project, and wastage shown where no norm has been set.

Most BOQ items had no norm, because norms were typed one at a time, so the wastage report had nothing to measure against and said
"None" even where the store had written material off. The sheet and the copy fill norms in quickly; the report now shows recorded
wastage either way, and compares it with the norm only where one exists."""
import io
import uuid

import openpyxl

from app import db as database, models
from app.models.store_core import MovementType
from app.models.store_reports import DBStoreMaterialNorm

from conftest import make_employee
from test_p5_reports import _leave_no_stock_behind, put, staff, world  # noqa: F401  (the fixture empties the stock after each test)

API = "/api/store/reports"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def sheet(*rows, header=("BOQ Item", "Material", "Qty Per Unit", "Wastage %")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(client, step, project, data, mode="add"):
    return client.post("%s/norms/import/%s" % (API, step), files={"file": ("norms.xlsx", data, XLSX)}, data={"project_id": str(project), "mode": mode})


def codes(w):
    with database.SessionLocal() as s:
        return {k: s.get(models.DBItem, i).item_code for k, i in w.item.items()}


def norms_of(client, project):
    return {(n["boq_item_id"], n["item_id"]): n for n in client.get(API + "/norms", params={"project_id": project}).json()["items"]}


def test_the_template_has_the_four_columns_and_lists_the_projects_boq_and_materials(account):
    tenant = account["client"]
    w = world(account)
    res = tenant.get(API + "/norms/template", params={"project_id": w.proj})
    assert res.status_code == 200 and "spreadsheetml" in res.headers["content-type"]
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    assert [c.value for c in wb["Norms"][1]] == ["BOQ Item", "Material", "Qty Per Unit", "Wastage %"]
    assert wb["Norms"].max_row == 5                                                  # the four example rows
    assert [r[1] for r in wb["BOQ items"].iter_rows(min_row=2, values_only=True)] == ["RCC M25 in columns", "Brick masonry"]
    assert "Cement OPC" in [r[1] for r in wb["Materials"].iter_rows(min_row=2, values_only=True)]


def test_a_valid_sheet_is_previewed_then_imported_together(account):
    tenant = account["client"]
    w = world(account)
    c = codes(w)
    data = sheet(("1", c["cement"], 50, 5), ("Brick masonry", "Cement OPC", "0.3", "2%"), ("2 Brick masonry", "TMT 12mm", 1.5, 0))
    pre = upload(tenant, "preview", w.proj, data)
    assert pre.status_code == 200, pre.text
    body = pre.json()
    assert body["summary"]["insert"] == 3 and body["summary"]["invalid"] == 0
    assert [r["boq_item_id"] for r in body["rows"]] == [w.boq[0], w.boq[1], w.boq[1]]
    assert norms_of(tenant, w.proj) == {}                                            # a preview writes nothing
    done = upload(tenant, "commit", w.proj, data)
    assert done.status_code == 200, done.text
    assert (done.json()["inserted"], done.json()["updated"]) == (3, 0)
    have = norms_of(tenant, w.proj)
    assert (have[(w.boq[0], w.item["cement"])]["qty_per_unit"], have[(w.boq[0], w.item["cement"])]["wastage_pct"]) == ("50.000000", "5.000")
    assert have[(w.boq[1], w.item["cement"])]["wastage_pct"] == "2.000" and have[(w.boq[1], w.item["cement"])]["updated_at"]
    with database.SessionLocal() as s:
        log = s.query(models.DBAuditLog).filter(models.DBAuditLog.action == "store_norms_imported", models.DBAuditLog.entity_id == w.proj).one()
        assert "3 added" in log.details


def test_bad_rows_are_shown_apart_left_out_of_the_import_and_listed_in_the_error_report(account):
    tenant = account["client"]
    w = world(account)
    c = codes(w)
    data = sheet(("1", c["cement"], 50, 5),                     # good
                 ("Roofing", c["cement"], 1, 0),                 # no such BOQ item
                 ("1", "Unobtanium", 1, 0),                      # no such material
                 ("2", c["cement"], -1, 0),                      # quantity below zero
                 ("2", c["steel"], 1, ""),                       # wastage left blank: no default is assumed
                 ("2", c["plate"], 1, 0), ("2", c["plate"], 2, 0))   # the same pair twice
    body = upload(tenant, "preview", w.proj, data).json()
    rows = {r["line"]: r for r in body["rows"]}
    assert rows[2]["valid"] and rows[2]["action"] == "insert"
    assert "missing_boq" in rows[3]["flags"] and "missing_material" in rows[4]["flags"] and "invalid_qty" in rows[5]["flags"]
    assert "invalid_wastage" in rows[6]["flags"] and "duplicate" in rows[7]["flags"] and "duplicate" in rows[8]["flags"]
    assert (body["summary"]["valid"], body["summary"]["invalid"], body["summary"]["duplicate"]) == (1, 6, 2)
    done = upload(tenant, "commit", w.proj, data).json()
    assert (done["inserted"], done["invalid"]) == (1, 6) and list(norms_of(tenant, w.proj)) == [(w.boq[0], w.item["cement"])]
    report = upload(tenant, "errors", w.proj, data)
    assert report.status_code == 200 and "spreadsheetml" in report.headers["content-type"]
    lines = [r[0] for r in openpyxl.load_workbook(io.BytesIO(report.content)).active.iter_rows(min_row=2, values_only=True)]
    assert lines == [3, 4, 5, 6, 7, 8]
    # A sheet with nothing good in it saves nothing.
    assert upload(tenant, "commit", w.proj, sheet(("Roofing", "Unobtanium", 1, 0))).status_code == 422


def test_a_sheet_without_the_columns_or_that_is_not_a_sheet_is_refused(account):
    tenant = account["client"]
    w = world(account)
    res = upload(tenant, "preview", w.proj, sheet(("1", "x", 1), header=("BOQ Item", "Material", "Qty Per Unit")))
    assert res.status_code == 400 and "Wastage %" in res.json()["detail"]
    junk = tenant.post(API + "/norms/import/preview", files={"file": ("n.xlsx", b"PK\x03\x04 not really a workbook", XLSX)}, data={"project_id": str(w.proj)})
    assert junk.status_code == 400
    assert upload(tenant, "preview", 0, sheet(("1", "x", 1, 0))).status_code == 400
    assert upload(tenant, "preview", w.proj, sheet(("1", "x", 1, 0)), mode="sideways").status_code == 400


def test_existing_norms_are_kept_when_adding_and_changed_when_updating(account):
    tenant = account["client"]
    w = world(account)
    c = codes(w)
    assert upload(tenant, "commit", w.proj, sheet(("1", c["cement"], 50, 5))).status_code == 200
    again = sheet(("1", c["cement"], 55, 4), ("2", c["cement"], 0.3, 2))
    added = upload(tenant, "commit", w.proj, again, mode="add").json()
    assert (added["inserted"], added["updated"], added["skipped_existing"]) == (1, 0, 1)
    assert norms_of(tenant, w.proj)[(w.boq[0], w.item["cement"])]["qty_per_unit"] == "50.000000"     # kept
    pre = upload(tenant, "preview", w.proj, again, mode="update").json()
    assert [r["action"] for r in pre["rows"]] == ["update", "unchanged"] and pre["rows"][0]["current"]["qty_per_unit"] == "50.000000"
    changed = upload(tenant, "commit", w.proj, again, mode="update").json()
    assert (changed["inserted"], changed["updated"], changed["unchanged"]) == (0, 1, 1)
    n = norms_of(tenant, w.proj)[(w.boq[0], w.item["cement"])]
    assert (n["qty_per_unit"], n["wastage_pct"]) == ("55.000000", "4.000")
    with database.SessionLocal() as s:                                               # one row per pair, never two
        assert s.query(DBStoreMaterialNorm).filter(DBStoreMaterialNorm.boq_item_id == w.boq[0], DBStoreMaterialNorm.item_id == w.item["cement"]).count() == 1


def _other_boq(w, *lines):
    """Add priced lines to the other project's BOQ: (item_no, description, quantity)."""
    with database.SessionLocal() as s:
        first = s.get(models.DBBoqLine, w.other_boq)
        ids = []
        for n, (no, desc, qty) in enumerate(lines, 2):
            l = models.DBBoqLine(boq_id=first.boq_id, revision_id=first.revision_id, key="x%d" % n, kind="item", item_no=no, description=desc, uom="cum", quantity=qty, display_order=n)
            s.add(l)
            s.flush()
            ids.append(l.id)
        s.commit()
    return ids


def test_norms_are_copied_to_the_same_work_in_another_project_and_never_to_a_guess(account):
    tenant = account["client"]
    w = world(account)
    c = codes(w)
    upload(tenant, "commit", w.proj, sheet(("1", c["cement"], 50, 5), ("2", c["steel"], 3, 1), ("2", c["plate"], 0.1, 0)))
    with database.SessionLocal() as s:                                               # the plate is no longer a stock item
        s.get(models.DBItem, w.item["plate"]).kind = "FG"
        s.commit()
    sources = {p["id"]: p for p in tenant.get(API + "/norms/copy/sources", params={"project_id": w.other_proj}).json()["items"]}
    assert sources[w.proj]["norms"] == 3 and w.other_proj not in sources
    preview = lambda mode="add": tenant.get(API + "/norms/copy/preview", params={"source_project_id": w.proj, "project_id": w.other_proj, "mode": mode}).json()
    # Nothing in the other BOQ is that work yet. Its "1 Elsewhere" shares only the number with "1 RCC M25 in columns": offered, but only
    # to be confirmed by a person; "2" is nowhere at all.
    first = {r["item_id"]: r for r in preview()["rows"]}
    assert (first[w.item["cement"]]["match"], first[w.item["cement"]]["needs_confirmation"]) == ("number", True)
    assert (first[w.item["steel"]]["status"], first[w.item["plate"]]["status"]) == ("no_boq", "no_material")
    rcc, brick = _other_boq(w, ("7", "RCC M25 in columns", 4), ("2", "Brickwork in CM 1:6", 8))
    rows = {r["item_id"]: r for r in preview()["rows"]}
    assert (rows[w.item["cement"]]["match"], rows[w.item["cement"]]["boq_item_id"], rows[w.item["cement"]]["needs_confirmation"]) == ("description", rcc, False)
    assert (rows[w.item["steel"]]["match"], rows[w.item["steel"]]["boq_item_id"], rows[w.item["steel"]]["needs_confirmation"]) == ("number", brick, True)
    assert rows[w.item["plate"]]["status"] == "no_material"
    # A source BOQ id is never taken as it is: it is not this project's line.
    bad = tenant.post(API + "/norms/copy", json={"source_project_id": w.proj, "project_id": w.other_proj, "mappings": [{"source_norm_id": rows[w.item["cement"]]["source_norm_id"], "boq_item_id": w.boq[0]}]})
    assert bad.status_code == 400
    # Copy only the sure one; the one matched by number alone waits for a person to confirm it.
    done = tenant.post(API + "/norms/copy", json={"source_project_id": w.proj, "project_id": w.other_proj, "mode": "add",
                                                  "mappings": [{"source_norm_id": rows[w.item["cement"]]["source_norm_id"], "boq_item_id": rcc}]})
    assert done.status_code == 200, done.text
    assert (done.json()["copied"], done.json()["not_chosen"]) == (1, 2)
    assert (norms_of(tenant, w.other_proj)[(rcc, w.item["cement"])]["qty_per_unit"]) == "50.000000"
    assert len(norms_of(tenant, w.proj)) == 3                                        # the source is untouched
    # The source changes; adding again keeps what is here, replacing takes the new figure, and nothing unrelated is removed.
    tenant.put("%s/norms/%d" % (API, norms_of(tenant, w.proj)[(w.boq[0], w.item["cement"])]["id"]),
               json={"boq_item_id": w.boq[0], "item_id": w.item["cement"], "qty_per_unit": "60", "wastage_pct": "5"})
    assert preview("add")["rows"][0]["status"] == "skip"
    pick = [{"source_norm_id": rows[w.item["cement"]]["source_norm_id"], "boq_item_id": rcc}, {"source_norm_id": rows[w.item["steel"]]["source_norm_id"], "boq_item_id": brick}]
    again = tenant.post(API + "/norms/copy", json={"source_project_id": w.proj, "project_id": w.other_proj, "mode": "replace", "mappings": pick}).json()
    assert (again["copied"], again["updated"]) == (1, 1)
    assert norms_of(tenant, w.other_proj)[(rcc, w.item["cement"])]["qty_per_unit"] == "60.000000" and len(norms_of(tenant, w.other_proj)) == 2
    # Two norms of one material onto one line: refused, not half done.
    twice = [{"source_norm_id": rows[w.item["cement"]]["source_norm_id"], "boq_item_id": rcc}] * 2
    assert tenant.post(API + "/norms/copy", json={"source_project_id": w.proj, "project_id": w.other_proj, "mappings": twice}).status_code == 409
    assert tenant.get(API + "/norms/copy/preview", params={"source_project_id": w.proj, "project_id": w.proj}).status_code == 400
    with database.SessionLocal() as s:
        logs = s.query(models.DBAuditLog).filter(models.DBAuditLog.action == "store_norms_copied", models.DBAuditLog.entity_id == w.other_proj).all()
        assert len(logs) == 2 and "From P-" in logs[0].details and logs[0].user_name


def test_staff_cannot_copy_from_a_project_they_are_not_on_or_import_without_the_right(account, portal):
    tenant = account["client"]
    w = world(account)
    c = codes(w)
    upload(tenant, "commit", w.proj, sheet(("1", c["cement"], 50, 5)))
    staff(account, portal, ["store.reports.view"], [w.central])
    assert upload(portal, "preview", w.proj, sheet(("1", c["cement"], 50, 5))).status_code == 403
    assert portal.get(API + "/norms/copy/preview", params={"source_project_id": w.proj, "project_id": w.other_proj}).status_code == 403
    # Put on the other project only: the first is out of reach as a source.
    email = "nm-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(tenant, email=email, password="Crew1234", permission_role="staff", status="active", site_ids=[w.other_proj])
    with database.SessionLocal() as s:
        s.get(models.DBEmployee, emp["id"]).extra_permissions = "store.reports.view,store.reports.create"
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
    assert portal.get(API + "/norms/copy/preview", params={"source_project_id": w.proj, "project_id": w.other_proj}).status_code == 404
    assert portal.post(API + "/norms/copy", json={"source_project_id": w.proj, "project_id": w.other_proj, "mappings": [{"source_norm_id": 1, "boq_item_id": w.other_boq}]}).status_code == 404
    assert w.proj not in {p["id"] for p in portal.get(API + "/norms/copy/sources").json()["items"]}


def test_wastage_recorded_without_a_norm_is_shown_and_not_called_a_loss_past_a_limit(account):
    tenant = account["client"]
    w = world(account)                                                               # 40 kg cement wasted, 10 kg steel scrapped; no norms
    got = tenant.get("/api/jobs/%d/wastage-loss" % w.proj).json()
    rows = {r["item"]: r for r in got["rows"]}
    assert (rows["Cement OPC"]["norm"], rows["Cement OPC"]["wasted"], rows["Cement OPC"]["basis"]) == ("NO_NORM", 40, "Norm not configured")
    assert (rows["Cement OPC"]["expected"], rows["Cement OPC"]["allowed"], rows["Cement OPC"]["over"]) == (None, None, None)
    assert rows["Cement OPC"]["wasted_value"] > 0 and rows["Cement OPC"]["used"] >= 40
    assert rows["TMT 12mm"]["wasted"] == 10                                          # no BBS on this project: steel scrap shows too
    assert got["total"] == 0 and got["wasted_value"] == got["unchecked_value"] > 0 and got["unchecked"] == 2
    every = tenant.get("/api/projects/wastage-loss").json()
    assert str(w.proj) not in every["by_job"] and every["detail"][str(w.proj)]["unchecked"] == got["unchecked_value"]


def test_with_a_norm_the_wastage_is_set_against_what_it_allows(account):
    tenant = account["client"]
    w = world(account)
    c = codes(w)
    # Brick masonry: 20 cum x 9 kg = 180 kg expected, 10% (18 kg) allowed. 200 kg went to a subcontractor on it, 30 kg more was wasted on it.
    upload(tenant, "commit", w.proj, sheet(("2", c["cement"], 9, 10)))
    with database.SessionLocal() as s:
        put(s, w, MovementType.WASTAGE_OUT, w.central, "cement", "30", doc=("SCRAP", 7), project_id=w.proj, boq_item_id=w.boq[1])
        s.commit()
    got = tenant.get("/api/jobs/%d/wastage-loss" % w.proj).json()
    row = next(r for r in got["rows"] if r.get("boq_item") and r["boq_item"].startswith("2 "))
    assert (row["norm"], row["expected"], row["used"], row["wasted"], row["allowed"], row["over"]) == ("OVER", 180, 230, 50, 18, 32)
    assert got["total"] == row["value"] > 0
