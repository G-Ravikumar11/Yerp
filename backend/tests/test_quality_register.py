"""Registering an inspection that has been carried out: saved to the database, checked on the server, final results only
from whoever signs off, and the same record found again afterwards."""
import io
from datetime import date, timedelta

from test_site_access import signed_in
from test_quality import job


def day(n=0):
    return (date.today() + timedelta(days=n)).isoformat()


def filled(tenant, j, checklist="Plastering", result="ok", bad=()):
    """The checklist's own items, each ticked."""
    items = tenant.get("/api/qc/checklists", params={"job_id": j["id"]}).json()["templates"]
    items = next(t for t in items if t["name"] == checklist)["items"]
    return [{"item": x["item"], "criteria": x.get("criteria", ""), "result": "not ok" if n in bad else result, "remark": ""} for n, x in enumerate(items)]


def body(tenant, j, **over):
    b = {"job_id": j["id"], "work_activity": "Internal plaster, 2nd floor", "checklist": "Plastering", "inspected_on": day(-1),
         "inspector": "R. Kumar", "location": "Block A", "items": filled(tenant, j), "result": "Pass", "status": "Passed", "defects": ""}
    b.update(over)
    return b


def register(tenant, j, **over):
    return tenant.post("/api/qc/inspections/register", json=body(tenant, j, **over))


def test_a_registered_inspection_is_saved_and_found_again(tenant):
    j = job(tenant)
    res = register(tenant, j)
    assert res.status_code == 200, res.text
    i = res.json()["inspection"]
    assert i["number"] == "INS-0001" and i["result"] == "PASSED" and i["result_label"] == "Passed"
    assert i["work_activity"] == "Internal plaster, 2nd floor" and i["inspected_by"] == "R. Kumar" and i["inspected_on"] == day(-1)
    # It is in the database: the list, the record itself and its trail all have it.
    listed = tenant.get("/api/qc/inspections", params={"job_id": j["id"]}).json()["inspections"]
    assert [x["number"] for x in listed] == ["INS-0001"]
    got = tenant.get("/api/qc/inspections/%d" % i["id"]).json()
    assert got["inspection"]["checked"] == len(got["inspection"]["items"]) > 0
    assert [h["action"] for h in got["history"]][::-1][0] == "qc.inspection.registered"
    assert tenant.get("/api/qc/summary").json()["inspections_failed"] == 0


def test_a_failed_registration_counts_and_keeps_the_defect(tenant):
    j = job(tenant)
    i = register(tenant, j, items=filled(tenant, j, bad=(1,)), result="Fail", status="Failed", defects="Thickness 8 mm, 12 mm specified").json()["inspection"]
    assert i["result"] == "FAILED" and i["failed_items"] == 1 and "Thickness 8 mm" in i["remarks"]
    assert tenant.get("/api/qc/summary").json()["inspections_failed"] == 1
    assert any(a["kind"] == "qc_failed" for a in tenant.get("/api/alerts").json()["alerts"])
    # A fail described only in words becomes a not-ok check of its own.
    j2 = job(tenant)
    w = register(tenant, j2, result="Fail", status="Failed", defects="Hollow sound on tapping").json()["inspection"]
    assert w["failed_items"] == 1 and any(x["item"] == "Defect found" and x["remark"] == "Hollow sound on tapping" for x in w["items"])


def test_the_required_fields_are_checked_on_the_server(tenant):
    j = job(tenant)
    for bad, why in (({"work_activity": " "}, "activity"), ({"inspector": ""}, "inspection"), ({"inspected_on": ""}, "inspection date"),
                     ({"inspected_on": day(3)}, "future"), ({"inspected_on": "soon"}, "date"), ({"status": "Done"}, "Status"),
                     ({"result": "Maybe"}, "Pass or Fail"), ({"checklist": "Nonsense", "items": None}, "checklist"), ({"items": []}, "nothing")):
        res = register(tenant, j, **bad)
        assert res.status_code == 400, (bad, res.text)
    assert register(tenant, {"id": 99999}).status_code == 404
    assert tenant.get("/api/qc/inspections").json()["total"] == 0          # nothing half-saved


def test_the_result_must_agree_with_the_checks(tenant):
    j = job(tenant)
    assert register(tenant, j, items=filled(tenant, j, bad=(0,))).status_code == 409                     # Pass with a check not ok
    assert register(tenant, j, result="Fail", status="Failed", defects="").status_code == 400            # Fail, nothing said
    unlooked = filled(tenant, j)
    unlooked[0]["result"] = ""
    assert register(tenant, j, items=unlooked).status_code == 409                                        # a check not looked at
    assert register(tenant, j, status="Failed").status_code == 409                                       # status against result
    assert register(tenant, j, result="", status="Passed").status_code == 400                            # a status with no result
    assert tenant.get("/api/qc/inspections").json()["total"] == 0


def test_pending_and_awaiting_approval(tenant, portal):
    j = job(tenant)
    pend = register(tenant, j, work_activity="Pending one", items=None, result="", status="Pending").json()["inspection"]
    assert pend["result"] == "OPEN" and pend["approval_status"] == "" and pend["checked"] == 0
    wait = register(tenant, j, work_activity="Waiting one", status="Awaiting Approval").json()["inspection"]
    assert wait["result"] == "OPEN" and wait["approval_status"] == "submitted" and not wait["editable"]
    assert tenant.get("/api/qc/summary").json()["inspections_awaiting_approval"] == 1
    # The approver decides it, as for any inspection.
    assert tenant.post("/api/qc/inspections/%d/close" % wait["id"]).json()["inspection"]["result"] == "PASSED"


def test_only_those_who_sign_off_record_a_final_result(tenant, portal):
    j = job(tenant)
    signed_in(tenant, portal, "staff")
    final = portal.post("/api/qc/inspections/register", json=body(tenant, j))
    assert final.status_code == 403 and "Awaiting Approval" in final.json()["detail"]
    ok = portal.post("/api/qc/inspections/register", json=body(tenant, j, status="Awaiting Approval"))
    assert ok.status_code == 200 and ok.json()["inspection"]["approval_status"] == "submitted"
    # And the staff member cannot approve their own.
    assert portal.post("/api/qc/inspections/%d/close" % ok.json()["inspection"]["id"]).status_code == 403


def test_the_same_registration_twice_is_one_record_and_another_company_cannot_use_it(tenant, second_tenant):
    j = job(tenant)
    assert register(tenant, j).status_code == 200
    again = register(tenant, j)
    assert again.status_code == 409 and "INS-0001" in again.json()["detail"]
    assert tenant.get("/api/qc/inspections").json()["total"] == 1
    assert second_tenant.post("/api/qc/inspections/register", json=body(tenant, j)).status_code == 404
    assert second_tenant.get("/api/qc/inspections").json()["total"] == 0


def test_attachments_go_with_the_registered_inspection(tenant):
    j = job(tenant)
    i = register(tenant, j).json()["inspection"]
    up = tenant.post("/api/files", files={"file": ("plaster.jpg", io.BytesIO(b"\xff\xd8\xff" + b"0" * 400), "image/jpeg")},
                     data={"attached_type": "inspection", "attached_id": str(i["id"])})
    assert up.status_code == 200, up.text
    files = tenant.get("/api/files", params={"attached_type": "inspection", "attached_id": i["id"]})
    assert files.status_code == 200 and "plaster.jpg" in files.text
