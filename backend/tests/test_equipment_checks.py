"""The company's equipment checklists: grinder, breaking machine, hammer drill, fire extinguisher and electrical board.

Every item is answered, a fault is found from the answers, the next inspection falls due, and the client / PMC
review is Accepted or Rejected - never Accepted on an inspection that found a fault.
"""
from datetime import date, timedelta

from conftest import make_employee


def job(tenant):
    return tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()


def forms(tenant):
    return {f["key"]: f for f in tenant.get("/api/safety/checks").json()["forms"]}


def answers(tpl, **over):
    """Every item of the form answered the good way, except those in `over` (key -> answer)."""
    rows = []
    for i in tpl["items"]:
        good = "no" if i["bad_if_yes"] else "yes"
        rows.append({"key": i["key"], "answer": over.get(i["key"], "" if i["optional"] else good), "remarks": ""})
    return rows


def record(tenant, j, form, tpl, **over):
    body = {"job_id": j["id"], "form_type": form, "equipment_no": "GR-01", "location": "Tower A",
            "inspection_date": date.today().isoformat(),
            "next_inspection_date": (date.today() + timedelta(days=30)).isoformat(),
            "items": answers(tpl, **over.pop("marks", {})), "readings": {}}
    if form == "grinder":
        body["readings"] = {"wheel_rpm": 11000, "machine_rpm": 10000}
    if form == "extinguisher":
        body["extinguisher_type"] = "ABC type"
    body.update(over)
    return tenant.post("/api/safety/checks", json=body)


# --- the five forms ---------------------------------------------------------------------------------------------------

def test_the_five_company_forms_are_there_with_their_items(tenant):
    f = forms(tenant)
    assert set(f) == {"grinder", "breaking", "drill", "extinguisher", "electrical"}
    assert [len(f[k]["items"]) for k in ("grinder", "breaking", "drill", "extinguisher", "electrical")] == [9, 10, 7, 10, 32]
    assert f["grinder"]["doc_ref"] == "YIP-03/HSE/REV00/Dec-2024" and f["drill"]["doc_ref"] == "YIP-02/HSE/REV00/Dec-2024"
    assert f["extinguisher"]["doc_ref"] == "YIP-01-2024" and f["electrical"]["doc_ref"] == "YIP-05/HSE/REV00/Dec-2024"
    assert [r["key"] for r in f["grinder"]["readings"]] == ["wheel_rpm", "machine_rpm"]
    assert f["extinguisher"]["extinguisher_types"] == ["ABC type", "Water type", "CO2 type"]
    assert [s["role"] for s in f["electrical"]["signoffs"]] == ["inspected_by", "reviewed_by"]
    assert {i["section"] for i in f["electrical"]["items"]} >= {"C. Power panel", "F. Earthing", "H. Miscellaneous"}


def test_a_grinder_inspection_is_recorded_and_passes(tenant):
    j = job(tenant)
    res = record(tenant, j, "grinder", forms(tenant)["grinder"])
    assert res.status_code == 200, res.text
    c = res.json()["check"]
    assert c["number"] == "CHK-0001" and c["result"] == "pass" and c["failed"] == []
    assert c["current"] and c["due_state"] == "ok" and c["has_review"] and c["decision"] == ""
    assert c["readings"] == {"wheel_rpm": 11000.0, "machine_rpm": 10000.0}


def test_a_no_on_a_good_item_is_a_fault_and_a_yes_on_a_bad_one_is_too(tenant):
    j = job(tenant)
    f = forms(tenant)
    g = record(tenant, j, "grinder", f["grinder"], marks={"3": "no"}).json()["check"]      # wheel with a crack
    assert g["result"] == "fail" and g["failed"] == ["3"]
    e = record(tenant, j, "extinguisher", f["extinguisher"], equipment_no="FE-1", marks={"2": "yes"}).json()["check"]
    assert e["result"] == "fail" and e["failed"] == ["2"]                                  # "is it corroded" - yes
    ok = record(tenant, j, "extinguisher", f["extinguisher"], equipment_no="FE-2", marks={"2": "no", "8": "na"}).json()["check"]
    assert ok["result"] == "pass", "N/A is neither a fault nor a pass to count against"


def test_a_wheel_rated_below_the_machine_speed_is_a_fault(tenant):
    j = job(tenant)
    c = record(tenant, j, "grinder", forms(tenant)["grinder"], readings={"wheel_rpm": 8000, "machine_rpm": 10000}).json()["check"]
    assert c["result"] == "fail" and c["rpm_wrong"] and c["failed"] == []


def test_the_grinder_needs_both_rpm_readings(tenant):
    j = job(tenant)
    assert record(tenant, j, "grinder", forms(tenant)["grinder"], readings={"wheel_rpm": 11000}).status_code == 400


def test_every_item_has_to_be_answered_but_the_optional_one_may_stay_blank(tenant):
    j = job(tenant)
    tpl = forms(tenant)["breaking"]
    rows = answers(tpl)
    rows[0]["answer"] = ""
    res = record(tenant, j, "breaking", tpl, items=rows)
    assert res.status_code == 400 and "Not answered: 1" in res.json()["detail"]
    assert record(tenant, j, "breaking", tpl).status_code == 200            # "Other" left blank
    bad = answers(tpl)
    bad[0]["answer"] = "maybe"
    assert record(tenant, j, "breaking", tpl, items=bad).status_code == 400
    assert record(tenant, j, "breaking", tpl, items=answers(tpl) + [{"key": "99", "answer": "yes"}]).status_code == 400


def test_the_header_of_the_form_is_checked(tenant):
    j = job(tenant)
    f = forms(tenant)
    assert record(tenant, j, "grinder", f["grinder"], equipment_no="  ").status_code == 400
    assert record(tenant, j, "grinder", f["grinder"], next_inspection_date="").status_code == 400
    assert record(tenant, j, "grinder", f["grinder"], next_inspection_date=date.today().isoformat()).status_code == 400
    assert record(tenant, j, "grinder", f["grinder"], inspection_date=(date.today() + timedelta(days=2)).isoformat(),
                  next_inspection_date=(date.today() + timedelta(days=9)).isoformat()).status_code == 400
    assert record(tenant, j, "extinguisher", f["extinguisher"], extinguisher_type="Foam").status_code == 400
    assert record(tenant, j, "nonsense", f["grinder"]).status_code == 400
    assert tenant.post("/api/safety/checks", json={"job_id": 99999, "form_type": "grinder", "equipment_no": "x",
                                                   "items": []}).status_code == 404


def test_the_electrical_form_does_not_need_a_next_date_and_keeps_the_earth_reading(tenant):
    j = job(tenant)
    tpl = forms(tenant)["electrical"]
    res = record(tenant, j, "electrical", tpl, equipment_no="DB-3", next_inspection_date="", board_type="Distribution panel",
                 readings={"earth_resistance": 1.8})
    assert res.status_code == 200, res.text
    c = res.json()["check"]
    assert c["board_type"] == "Distribution panel" and c["readings"] == {"earth_resistance": 1.8}
    assert c["has_review"] is False and c["due_state"] == ""


# --- signatures and the client / PMC review ----------------------------------------------------------------------------

def test_the_form_is_signed_by_name_and_date_and_reviewed(tenant):
    j = job(tenant)
    c = record(tenant, j, "grinder", forms(tenant)["grinder"],
               signoffs={"contractor_officer": {"name": "Anil Kumar", "date": date.today().isoformat()}}).json()["check"]
    assert c["signoffs"]["contractor_officer"]["name"] == "Anil Kumar"
    out = tenant.post("/api/safety/checks/%d/signoff" % c["id"], json={"role": "client_electrician", "name": "Ravi S"}).json()["check"]
    assert out["signoffs"]["client_electrician"] == {"name": "Ravi S", "date": date.today().isoformat()}
    rv = tenant.post("/api/safety/checks/%d/signoff" % c["id"], json={"role": "review", "name": "PMC Rao", "decision": "accepted"})
    assert rv.status_code == 200, rv.text
    assert rv.json()["check"]["decision"] == "accepted" and rv.json()["check"]["decision_by"] == "PMC Rao"


def test_a_signature_needs_a_name_and_a_role_on_the_form(tenant):
    j = job(tenant)
    c = record(tenant, j, "extinguisher", forms(tenant)["extinguisher"]).json()["check"]
    url = "/api/safety/checks/%d/signoff" % c["id"]
    assert tenant.post(url, json={"role": "contractor_officer", "name": " "}).status_code == 400
    assert tenant.post(url, json={"role": "client_electrician", "name": "X"}).status_code == 400   # not on this form
    assert tenant.post(url, json={"role": "review", "name": "X"}).status_code == 400               # no decision
    assert tenant.post(url, json={"role": "review", "name": "X", "decision": "maybe"}).status_code == 400


def test_an_inspection_that_found_a_fault_cannot_be_accepted(tenant):
    j = job(tenant)
    c = record(tenant, j, "drill", forms(tenant)["drill"], marks={"3": "no"}).json()["check"]
    url = "/api/safety/checks/%d/signoff" % c["id"]
    refused = tenant.post(url, json={"role": "review", "name": "PMC Rao", "decision": "accepted"})
    assert refused.status_code == 400 and "found a fault" in refused.json()["detail"]
    assert tenant.post(url, json={"role": "review", "name": "PMC Rao", "decision": "rejected"}).json()["check"]["decision"] == "rejected"


def test_the_electrical_form_has_no_client_review(tenant):
    j = job(tenant)
    c = record(tenant, j, "electrical", forms(tenant)["electrical"], equipment_no="DB-1").json()["check"]
    url = "/api/safety/checks/%d/signoff" % c["id"]
    assert tenant.post(url, json={"role": "review", "name": "X", "decision": "accepted"}).status_code == 400
    assert tenant.post(url, json={"role": "inspected_by", "name": "Safety Officer"}).status_code == 200


# --- when the next one is due ------------------------------------------------------------------------------------------

def test_a_later_inspection_replaces_an_earlier_one_for_due_dates(tenant):
    j = job(tenant)
    tpl = forms(tenant)["extinguisher"]
    old = record(tenant, j, "extinguisher", tpl, equipment_no="FE-7",
                 inspection_date=(date.today() - timedelta(days=100)).isoformat(),
                 next_inspection_date=(date.today() - timedelta(days=10)).isoformat()).json()["check"]
    s = tenant.get("/api/safety/checks").json()
    assert s["summary"]["overdue"] == 1 and s["checks"][0]["due_state"] == "overdue" and s["checks"][0]["due_in_days"] == -10
    record(tenant, j, "extinguisher", tpl, equipment_no="FE-7")             # inspected again today, due in 30 days
    s = tenant.get("/api/safety/checks").json()
    assert s["summary"]["overdue"] == 0 and s["summary"]["equipment"] == 1 and s["summary"]["total"] == 2
    older = next(c for c in s["checks"] if c["id"] == old["id"])
    assert older["current"] is False and older["due_state"] == ""


def test_due_soon_and_failed_are_counted_for_the_latest_inspection_of_each_item(tenant):
    j = job(tenant)
    f = forms(tenant)
    record(tenant, j, "grinder", f["grinder"], equipment_no="G-1", next_inspection_date=(date.today() + timedelta(days=3)).isoformat())
    record(tenant, j, "drill", f["drill"], equipment_no="D-1", marks={"5": "no"})
    s = tenant.get("/api/safety/checks").json()["summary"]
    assert s["due_soon"] == 1 and s["failed"] == 1 and s["awaiting_review"] == 2 and s["equipment"] == 2


def test_the_list_can_be_narrowed_to_a_project_and_a_form(tenant):
    a, b = job(tenant), tenant.post("/api/jobs", json={"name": "Other site", "customer_name": "X"}).json()
    f = forms(tenant)
    record(tenant, a, "grinder", f["grinder"])
    record(tenant, b, "drill", f["drill"], equipment_no="D-9")
    assert len(tenant.get("/api/safety/checks").json()["checks"]) == 2
    assert [c["form_type"] for c in tenant.get("/api/safety/checks?job_id=%d" % b["id"]).json()["checks"]] == ["drill"]
    assert [c["form_type"] for c in tenant.get("/api/safety/checks?form_type=grinder").json()["checks"]] == ["grinder"]


# --- photos, paper copies, removing, and who may -----------------------------------------------------------------------

def test_a_photo_is_kept_against_the_item_it_shows(tenant):
    j = job(tenant)
    c = record(tenant, j, "grinder", forms(tenant)["grinder"]).json()["check"]
    up = tenant.post("/api/files", data={"attached_type": "equipment_check", "attached_id": str(c["id"]),
                                         "caption": "item:3", "kind": "photo"},
                     files={"file": ("wheel.jpg", b"\xff\xd8\xff\xe0 not really a jpeg", "image/jpeg")})
    assert up.status_code == 200, up.text
    got = tenant.get("/api/safety/checks").json()["checks"][0]
    assert got["photo_count"] == 1
    assert [len(i["photos"]) for i in got["items"] if i["key"] == "3"] == [1]
    assert [len(i["photos"]) for i in got["items"] if i["key"] == "4"] == [0]


def test_the_paper_form_and_the_register_download(tenant):
    j = job(tenant)
    c = record(tenant, j, "electrical", forms(tenant)["electrical"], equipment_no="DB-2").json()["check"]
    pdf = tenant.get("/api/safety/checks/%d/document.pdf" % c["id"])
    assert pdf.status_code in (200, 503)
    if pdf.status_code == 200:
        assert pdf.content.startswith(b"%PDF")
    xl = tenant.get("/api/safety/checks.xlsx")
    assert xl.status_code == 200 and xl.content[:2] == b"PK"


def test_removing_an_inspection_takes_its_photos_too(tenant):
    j = job(tenant)
    c = record(tenant, j, "drill", forms(tenant)["drill"]).json()["check"]
    tenant.post("/api/files", data={"attached_type": "equipment_check", "attached_id": str(c["id"]), "caption": "item:1", "kind": "photo"},
                files={"file": ("a.jpg", b"\xff\xd8\xff\xe0 x", "image/jpeg")})
    assert tenant.delete("/api/safety/checks/%d" % c["id"]).status_code == 200
    assert tenant.get("/api/safety/checks").json()["checks"] == []
    assert tenant.delete("/api/safety/checks/%d" % c["id"]).status_code == 404


def test_each_business_sees_only_its_own_inspections(tenant, second_tenant):
    j = job(tenant)
    c = record(tenant, j, "grinder", forms(tenant)["grinder"]).json()["check"]
    assert second_tenant.get("/api/safety/checks").json()["checks"] == []
    assert second_tenant.post("/api/safety/checks/%d/signoff" % c["id"], json={"role": "contractor_officer", "name": "X"}).status_code == 404
    assert second_tenant.delete("/api/safety/checks/%d" % c["id"]).status_code == 404
