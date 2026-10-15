"""The site diary, and the project profit it finally makes real.

On a civil contract the diary is the document that settles a delay claim two
years later. It is also the only place the labour standing on site is written
down, so until it existed a job's cost was material and nothing else - which
is how a project looks profitable right up to the day somebody counts the
store and pays the contractors.
"""
import uuid

from test_goods_receipt import order, receipt, set_lines, post
from conftest import make_invoice
from test_stock_control import rm_item


def project(tenant, name="Fairview plot 3"):
    return tenant.post("/api/jobs", json={
        "name": name, "customer_name": "L&T Construction"}).json()


def diary(tenant, job, on="2026-09-01", **extra):
    body = {"job_id": job["id"], "diary_date": on, "work_done": "Slab to Block A"}
    body.update(extra)
    res = tenant.post("/api/diary", json=body)
    assert res.status_code == 200, res.text
    return res.json()["diary"]


# --- One diary per site per day ----------------------------------------------

def test_a_day_opens_with_the_site_and_the_date(tenant):
    d = diary(tenant, project(tenant))
    assert d["diary_date"] == "2026-09-01"
    assert d["status"] == "DRAFT"
    assert d["weather"] == "Clear"
    assert d["working_hours"] == 8


def test_a_second_diary_for_the_same_day_is_refused(tenant):
    """Two records for one day is how a delay claim gets thrown out."""
    job = project(tenant)
    diary(tenant, job)
    res = tenant.post("/api/diary", json={
        "job_id": job["id"], "diary_date": "2026-09-01", "work_done": "again"})
    assert res.status_code == 409
    assert "already a diary" in res.json()["detail"].lower()


def test_the_same_day_on_another_site_is_fine(tenant):
    a, b = project(tenant, "Site A"), project(tenant, "Site B")
    diary(tenant, a)
    assert diary(tenant, b)["diary_date"] == "2026-09-01"


def test_a_diary_needs_a_site(tenant):
    assert tenant.post("/api/diary", json={"diary_date": "2026-09-01"}).status_code == 400


# --- Labour, and what a manday means -----------------------------------------

def test_a_full_day_is_one_manday_each(tenant):
    d = diary(tenant, project(tenant), labour=[
        {"trade": "Mason", "headcount": 6, "hours": 8, "rate": 900},
        {"trade": "Helper", "headcount": 10, "hours": 8, "rate": 600}])
    assert d["total_mandays"] == 16
    assert d["labour_cost"] == 6 * 900 + 10 * 600


def test_half_a_day_is_half_a_manday(tenant):
    """Comparable across weeks where the site worked different hours."""
    d = diary(tenant, project(tenant), labour=[
        {"trade": "Mason", "headcount": 6, "hours": 4, "rate": 900}])
    assert d["total_mandays"] == 3
    assert d["labour_cost"] == 2700


def test_overtime_reads_as_more_than_one_manday(tenant):
    d = diary(tenant, project(tenant), labour=[
        {"trade": "Mason", "headcount": 10, "hours": 12, "rate": 900}])
    assert d["total_mandays"] == 15
    assert d["labour_cost"] == 13500


def test_a_ten_hour_site_measures_its_own_day(tenant):
    """A manday is a head for this site's working day, not a clock hour."""
    d = diary(tenant, project(tenant), working_hours=10, labour=[
        {"trade": "Mason", "headcount": 5, "hours": 10, "rate": 1000}])
    assert d["total_mandays"] == 5


def test_labour_with_nobody_on_it_is_dropped(tenant):
    d = diary(tenant, project(tenant), labour=[
        {"trade": "Mason", "headcount": 0, "rate": 900},
        {"trade": "Helper", "headcount": 4, "rate": 600}])
    assert len(d["labour"]) == 1
    assert d["total_mandays"] == 4


# --- Plant, including what stood still ---------------------------------------

def test_idle_plant_is_charged_too(tenant):
    """Plant that stood all day still costs money."""
    d = diary(tenant, project(tenant), plant=[
        {"plant": "JCB 3DX", "worked_hours": 3, "idle_hours": 5, "rate": 800}])
    assert d["plant_cost"] == 8 * 800
    assert d["day_cost"] == 6400


# --- Weather -----------------------------------------------------------------

def test_a_rained_off_day_is_flagged(tenant):
    d = diary(tenant, project(tenant), weather="Heavy rain", rain_hours=6)
    assert d["lost_to_weather"] is True


def test_a_shower_is_not_a_lost_day(tenant):
    d = diary(tenant, project(tenant), weather="Rain", rain_hours=1)
    assert d["lost_to_weather"] is False


def test_an_unknown_weather_falls_back_rather_than_failing(tenant):
    d = diary(tenant, project(tenant), weather="Monsoon apocalypse")
    assert d["weather"] == "Clear"


# --- Signing it off -----------------------------------------------------------

def test_signing_off_needs_a_record_of_the_work(tenant):
    job = project(tenant)
    d = tenant.post("/api/diary", json={
        "job_id": job["id"], "diary_date": "2026-09-02"}).json()["diary"]
    res = tenant.post("/api/diary/%d/submit" % d["id"])
    assert res.status_code == 400
    assert "say what was done" in res.json()["detail"].lower()


def test_a_signed_off_day_cannot_be_rewritten(tenant):
    """A diary that can be changed afterwards is worth nothing in a claim."""
    d = diary(tenant, project(tenant))
    tenant.post("/api/diary/%d/submit" % d["id"])
    res = tenant.put("/api/diary/%d" % d["id"], json={"work_done": "something else"})
    assert res.status_code == 409
    assert tenant.delete("/api/diary/%d" % d["id"]).status_code == 409


def test_a_draft_can_still_be_corrected(tenant):
    d = diary(tenant, project(tenant))
    out = tenant.put("/api/diary/%d" % d["id"], json={
        "holdups": "No power from 11am", "labour": [
            {"trade": "Mason", "headcount": 4, "rate": 900}]}).json()["diary"]
    assert out["holdups"] == "No power from 11am"
    assert out["total_mandays"] == 4


# --- The history a manager actually asks for ----------------------------------

def test_labour_history_adds_up_by_trade_and_by_contractor(tenant):
    job = project(tenant)
    diary(tenant, job, on="2026-09-01", labour=[
        {"trade": "Mason", "headcount": 6, "rate": 900, "agency": "Own"},
        {"trade": "Helper", "headcount": 8, "rate": 600, "agency": "Raju contractor"}])
    diary(tenant, job, on="2026-09-02", labour=[
        {"trade": "Mason", "headcount": 4, "rate": 900, "agency": "Own"}])

    h = tenant.get("/api/diary-labour/%d" % job["id"]).json()
    masons = [t for t in h["by_trade"] if t["trade"] == "Mason"][0]
    assert masons["mandays"] == 10
    assert masons["cost"] == 9000
    assert h["summary"]["mandays"] == 18
    assert h["summary"]["days_recorded"] == 2
    assert h["summary"]["average_crew"] == 9.0
    assert {a["agency"] for a in h["by_agency"]} == {"Own", "Raju contractor"}


def test_a_rained_off_day_does_not_drag_the_average_crew_down(tenant):
    job = project(tenant)
    diary(tenant, job, on="2026-09-01", labour=[
        {"trade": "Mason", "headcount": 10, "rate": 900}])
    diary(tenant, job, on="2026-09-02", weather="Heavy rain", rain_hours=8)
    h = tenant.get("/api/diary-labour/%d" % job["id"]).json()
    assert h["summary"]["days_recorded"] == 2
    assert h["summary"]["days_worked"] == 1
    assert h["summary"]["average_crew"] == 10.0


def test_the_day_downloads_as_a_report(tenant):
    d = diary(tenant, project(tenant), labour=[
        {"trade": "Mason", "headcount": 6, "rate": 900}])
    res = tenant.get("/api/diary/%d/export.xlsx" % d["id"])
    assert res.status_code == 200
    assert res.content[:2] == b"PK"


# --- The profit it makes real -------------------------------------------------

def test_labour_and_material_now_land_in_the_project_cost(tenant):
    """The hole this closes: a job used to cost only what suppliers billed."""
    job = project(tenant)
    code = rm_item(tenant)
    po = order(tenant, job=job, lines=[{"description": "cement", "item_code": code,
                                        "uom": "Nos", "qty": 100, "price": 50}])
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": 100, "rejected_qty": 0}])
    post(tenant, grn)

    # Material reaches a job through the work order it was drawn for, so the
    # issue has to name one - an issue against nothing costs nobody anything.
    fg = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "SLAB %s" % uuid.uuid4().hex[:6],
         "units_of_measure": "Nos"}]}).json()["codes"][0]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "lines": [{"code": fg, "qty": 1, "rate": 100000}]
    }).json()["work_order"]
    tenant.post("/api/erp/work-orders/%d/place-order" % wo["id"])

    issue = tenant.post("/api/stock-issues", json={
        "work_order_id": wo["id"],
        "lines": [{"item_code": code, "quantity": 40}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})

    diary(tenant, job, labour=[{"trade": "Mason", "headcount": 6, "rate": 900}],
          plant=[{"plant": "JCB", "worked_hours": 4, "rate": 800}])

    p = tenant.get("/api/jobs/%d/pnl" % job["id"]).json()
    assert p["cost"]["labour"] == 5400
    assert p["cost"]["plant"] == 3200
    assert p["result"]["mandays"] == 6
    assert p["cost"]["material_from_store"] == 40 * 50
    assert p["cost"]["incurred"] == 5400 + 3200 + 2000


def test_revenue_counts_what_was_certified_not_what_was_hoped_for(tenant):
    job = project(tenant)
    p = tenant.get("/api/jobs/%d/pnl" % job["id"]).json()
    assert p["earned"]["revenue"] == 0
    assert p["result"]["margin"] == 0
    assert p["result"]["margin_percent"] == 0


def test_a_job_running_on_labour_alone_shows_the_loss(tenant):
    job = project(tenant)
    diary(tenant, job, labour=[{"trade": "Mason", "headcount": 10, "rate": 1000}])
    p = tenant.get("/api/jobs/%d/pnl" % job["id"]).json()
    assert p["cost"]["incurred"] == 10000
    assert p["result"]["margin"] == -10000
    assert p["result"]["cost_per_manday"] == 1000


def test_the_portfolio_puts_the_worst_job_first(tenant):
    fine = project(tenant, "Quiet site")
    bad = project(tenant, "Bleeding site")
    diary(tenant, bad, labour=[{"trade": "Mason", "headcount": 20, "rate": 1000}])
    diary(tenant, fine, labour=[{"trade": "Mason", "headcount": 1, "rate": 500}])

    out = tenant.get("/api/jobs-pnl").json()
    assert out["projects"][0]["name"] == "Bleeding site"
    assert out["projects"][0]["losing"] is True
    assert out["summary"]["losing_money"] == 2
    assert out["summary"]["incurred"] == 20500


def test_the_pnl_downloads_as_a_workbook(tenant):
    job = project(tenant)
    diary(tenant, job, labour=[{"trade": "Mason", "headcount": 2, "rate": 900}])
    res = tenant.get("/api/jobs/%d/pnl.xlsx" % job["id"])
    assert res.status_code == 200
    assert res.content[:2] == b"PK"


def test_another_tenant_sees_none_of_it(tenant, second_tenant):
    job = project(tenant)
    d = diary(tenant, job)
    assert second_tenant.get("/api/diary/%d" % d["id"]).status_code == 404
    assert second_tenant.get("/api/jobs/%d/pnl" % job["id"]).status_code == 404
    assert second_tenant.get("/api/diary").json()["diaries"] == []


def test_an_invoice_on_the_job_becomes_revenue(tenant):
    """The path no test walked until a 500 on the real screen found it.

    An invoice carries what is paid and what is still due rather than a total,
    so reading a total straight off it threw - and every project with an
    invoice on it returned a 500 while every test still passed.
    """
    job = project(tenant)
    make_invoice(tenant, job_id=job["id"], status="Sent", line_items=[
        {"description": "RA 1", "qty": 1, "price": 500000, "tax_rate": "0%"}])

    p = tenant.get("/api/jobs/%d/pnl" % job["id"])
    assert p.status_code == 200, p.text
    out = p.json()
    assert out["earned"]["invoiced"] == 500000
    assert out["earned"]["outstanding"] == 500000
    assert out["earned"]["revenue"] == 500000
    assert out["result"]["margin"] == 500000


def test_a_draft_invoice_is_not_revenue_yet(tenant):
    job = project(tenant)
    make_invoice(tenant, job_id=job["id"], status="Draft", line_items=[
        {"description": "RA 1", "qty": 1, "price": 500000, "tax_rate": "0%"}])
    out = tenant.get("/api/jobs/%d/pnl" % job["id"]).json()
    assert out["earned"]["invoiced"] == 0


def test_the_portfolio_survives_a_job_carrying_an_invoice(tenant):
    job = project(tenant)
    make_invoice(tenant, job_id=job["id"], status="Sent", line_items=[
        {"description": "RA 1", "qty": 1, "price": 100000, "tax_rate": "0%"}])
    res = tenant.get("/api/jobs-pnl")
    assert res.status_code == 200, res.text
    assert res.json()["summary"]["revenue"] == 100000


# --- Editing a signed-off day: reopened with a reason, and it says so ------------------------------------------------

def signed_off(tenant, **extra):
    d = diary(tenant, project(tenant), **extra)
    assert tenant.post("/api/diary/%d/submit" % d["id"]).status_code == 200
    return d


def test_a_signed_off_day_can_be_reopened_with_a_reason_and_edited_then_signed_again(tenant):
    d = signed_off(tenant)
    res = tenant.post("/api/diary/%d/reopen" % d["id"], json={"reason": "Wrong headcount entered"})
    assert res.status_code == 200, res.text
    out = res.json()["diary"]
    assert out["status"] == "DRAFT" and out["submitted_at"] == "" and out["editable"] is True
    assert len(out["amendments"]) == 1 and "Wrong headcount entered" in out["amendments"][0]
    fixed = tenant.put("/api/diary/%d" % d["id"], json={"labour": [{"trade": "Mason", "headcount": 6, "rate": 900}]})
    assert fixed.status_code == 200 and fixed.json()["diary"]["total_mandays"] == 6
    assert tenant.post("/api/diary/%d/submit" % d["id"]).status_code == 200
    again = tenant.get("/api/diary/%d" % d["id"]).json()
    assert again["status"] == "SUBMITTED" and again["amendments"] == out["amendments"], "the trail is kept after it is signed again"


def test_every_reopening_is_kept(tenant):
    d = signed_off(tenant)
    tenant.post("/api/diary/%d/reopen" % d["id"], json={"reason": "First correction"})
    tenant.post("/api/diary/%d/submit" % d["id"])
    tenant.post("/api/diary/%d/reopen" % d["id"], json={"reason": "Second correction"})
    notes = tenant.get("/api/diary/%d" % d["id"]).json()["amendments"]
    assert len(notes) == 2 and "First correction" in notes[0] and "Second correction" in notes[1]


def test_reopening_needs_a_reason_and_a_signed_off_day(tenant):
    d = signed_off(tenant)
    assert tenant.post("/api/diary/%d/reopen" % d["id"], json={"reason": ""}).status_code == 400
    assert tenant.post("/api/diary/%d/reopen" % d["id"], json={"reason": "  "}).status_code == 400
    assert tenant.get("/api/diary/%d" % d["id"]).json()["status"] == "SUBMITTED"
    draft = diary(tenant, project(tenant, "Second site"))
    res = tenant.post("/api/diary/%d/reopen" % draft["id"], json={"reason": "No need"})
    assert res.status_code == 409 and "not signed off" in res.json()["detail"]


def test_a_signed_off_day_still_cannot_be_rewritten_without_reopening_it(tenant):
    d = signed_off(tenant)
    assert tenant.put("/api/diary/%d" % d["id"], json={"work_done": "changed quietly"}).status_code == 409


def test_only_those_who_can_sign_a_day_off_can_reopen_it(tenant, portal):
    from test_jobs_and_orders import sign_in, staff
    d = signed_off(tenant)
    hand = staff(tenant)                                   # plain staff: may record, may not sign off
    sign_in(portal, hand)
    assert portal.post("/api/diary/%d/reopen" % d["id"], json={"reason": "Trying"}).status_code == 403
    assert tenant.get("/api/diary/%d" % d["id"]).json()["status"] == "SUBMITTED"


def test_one_company_cannot_reopen_anothers_diary(tenant, second_tenant):
    d = signed_off(tenant)
    assert second_tenant.post("/api/diary/%d/reopen" % d["id"], json={"reason": "Not mine"}).status_code == 404
    assert tenant.get("/api/diary/%d" % d["id"]).json()["status"] == "SUBMITTED"


# --- A worker screened in Workers & Safety is named on the diary, not retyped --------------------------------------

def screen(tenant, job, name="Ravi Kumar", trade="Mason helper", age=30):
    res = tenant.post("/api/workers", json={"job_id": job["id"], "name": name, "age": age, "trade": trade})
    assert res.status_code == 200, res.text
    return res.json()["worker"]


def test_a_labour_line_can_name_the_worker_it_is_for(tenant):
    j = project(tenant)
    w = screen(tenant, j)
    d = diary(tenant, j, labour=[{"trade": w["trade"], "agency": "Own", "headcount": 0, "hours": 8, "rate": 700,
                                  "worker_ids": [w["id"]]}])
    detail = tenant.get("/api/diary/%d" % d["id"]).json()
    assert len(detail["labour"]) == 1
    line = detail["labour"][0]
    # The headcount always matches how many are named - the posted 0 is not trusted over the real list.
    assert line["headcount"] == 1 and line["worker_ids"] == [w["id"]]
    assert line["workers"] == [{"id": w["id"], "name": "Ravi Kumar", "trade": w["trade"]}]


def test_a_line_with_no_named_workers_is_still_a_plain_headcount(tenant):
    j = project(tenant)
    d = diary(tenant, j, labour=[{"trade": "Mason", "agency": "Own", "headcount": 4, "hours": 8, "rate": 700}])
    line = tenant.get("/api/diary/%d" % d["id"]).json()["labour"][0]
    assert line["headcount"] == 4 and line["worker_ids"] == [] and line["workers"] == []


def test_two_workers_named_on_one_line_both_come_back_by_name(tenant):
    j = project(tenant)
    a, b = screen(tenant, j, "Ravi Kumar", "Mason helper"), screen(tenant, j, "Suresh", "Carpenter")
    d = diary(tenant, j, labour=[{"trade": "Mixed", "agency": "Own", "headcount": 0, "hours": 8, "rate": 0,
                                  "worker_ids": [a["id"], b["id"]]}])
    line = tenant.get("/api/diary/%d" % d["id"]).json()["labour"][0]
    assert line["headcount"] == 2
    assert {w["name"] for w in line["workers"]} == {"Ravi Kumar", "Suresh"}


def test_another_companys_worker_cannot_be_named_on_this_diary(tenant, second_tenant):
    j = project(tenant)
    theirs = screen(tenant, j)
    other_job = second_tenant.post("/api/jobs", json={"name": "Rival site", "customer_name": "X"}).json()
    d = diary(second_tenant, other_job, labour=[{"trade": "Mason", "agency": "Own", "headcount": 0, "hours": 8,
                                                 "rate": 0, "worker_ids": [theirs["id"]]}])
    line = second_tenant.get("/api/diary/%d" % d["id"]).json()["labour"][0]
    # Headcount still honours a worker id that was sent, but the name never crosses tenants to show it.
    assert line["headcount"] == 1 and line["workers"] == []
