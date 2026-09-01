"""The site diary, and the project profit it finally makes real.

On a civil contract the diary is the document that settles a delay claim two
years later. It is also the only place the labour standing on site is written
down, so until it existed a job's cost was material and nothing else - which
is how a project looks profitable right up to the day somebody counts the
store and pays the gangs.
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

def test_labour_history_adds_up_by_trade_and_by_gang(tenant):
    job = project(tenant)
    diary(tenant, job, on="2026-09-01", labour=[
        {"trade": "Mason", "headcount": 6, "rate": 900, "agency": "Own"},
        {"trade": "Helper", "headcount": 8, "rate": 600, "agency": "Raju gang"}])
    diary(tenant, job, on="2026-09-02", labour=[
        {"trade": "Mason", "headcount": 4, "rate": 900, "agency": "Own"}])

    h = tenant.get("/api/diary-labour/%d" % job["id"]).json()
    masons = [t for t in h["by_trade"] if t["trade"] == "Mason"][0]
    assert masons["mandays"] == 10
    assert masons["cost"] == 9000
    assert h["summary"]["mandays"] == 18
    assert h["summary"]["days_recorded"] == 2
    assert h["summary"]["average_gang"] == 9.0
    assert {a["agency"] for a in h["by_agency"]} == {"Own", "Raju gang"}


def test_a_rained_off_day_does_not_drag_the_average_gang_down(tenant):
    job = project(tenant)
    diary(tenant, job, on="2026-09-01", labour=[
        {"trade": "Mason", "headcount": 10, "rate": 900}])
    diary(tenant, job, on="2026-09-02", weather="Heavy rain", rain_hours=8)
    h = tenant.get("/api/diary-labour/%d" % job["id"]).json()
    assert h["summary"]["days_recorded"] == 2
    assert h["summary"]["days_worked"] == 1
    assert h["summary"]["average_gang"] == 10.0


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
