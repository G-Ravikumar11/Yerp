"""NCRs, incidents and work permits have an owner on the staff and a due date, and the owner is reminded every day
from the day before it is due until it is closed; the bell is told once when one goes overdue."""
from datetime import date, datetime, timedelta

import main
from app import db as database, models
from conftest import make_employee
from test_safety import job, permit_body


def run(day, hour=9):
    with database.SessionLocal() as db:
        db.query(models.DBJobRun).filter(models.DBJobRun.job_name == "quality_safety_follow_up").delete()
        db.commit()
    return main.run_due_jobs(now=datetime.combine(day, datetime.min.time()).replace(hour=hour), only="quality_safety_follow_up")


def notices(emp_id):
    with database.SessionLocal() as db:
        return [n.title for n in db.query(models.DBNotification).filter(models.DBNotification.employee_id == emp_id)
                .order_by(models.DBNotification.id).all()]


def ncr(tenant, j, due):
    res = tenant.post("/api/qc/ncrs", json={"job_id": j["id"], "description": "Honeycombing on column C4", "location": "Tower A",
                                            "target_date": due})
    assert res.status_code == 200, res.text
    return res.json()["ncr"]


def test_an_ncr_owner_is_told_at_once_then_reminded_from_the_day_before(tenant):
    j, emp = job(tenant), make_employee(tenant)
    today = date.today()
    n = ncr(tenant, j, (today + timedelta(days=3)).isoformat())
    res = tenant.put("/api/follow-up/ncr/%d" % n["id"], json={"owner_id": emp["id"]})
    assert res.status_code == 200, res.text
    assert notices(emp["id"]) == ["NCR %s is yours to see through" % n["number"]]
    assert tenant.get("/api/qc/ncrs/%d" % n["id"]).json()["ncr"]["owner_id"] == emp["id"]

    run(today)                                                   # three days out: nothing yet
    assert len(notices(emp["id"])) == 1
    run(today + timedelta(days=2))                               # the day before
    run(today + timedelta(days=2))                               # once a day, however often the job runs
    run(today + timedelta(days=3))                               # the day
    run(today + timedelta(days=4))                               # overdue: reminded, and the bell told once
    run(today + timedelta(days=5))
    got = notices(emp["id"])[1:]
    assert got == ["NCR %s: due tomorrow" % n["number"], "NCR %s: due today" % n["number"],
                   "NCR %s: overdue since %s" % (n["number"], (today + timedelta(days=3)).isoformat()),
                   "NCR %s: overdue since %s" % (n["number"], (today + timedelta(days=3)).isoformat())]
    late = [a for a in tenant.get("/api/alerts").json()["alerts"] if a["title"] == "NCR %s is overdue" % n["number"]]
    assert len(late) == 1


def test_a_closed_ncr_is_not_chased(tenant):
    j, emp = job(tenant), make_employee(tenant)
    n = ncr(tenant, j, date.today().isoformat())
    tenant.put("/api/follow-up/ncr/%d" % n["id"], json={"owner_id": emp["id"]})
    with database.SessionLocal() as db:
        db.query(models.DBNcr).filter(models.DBNcr.id == n["id"]).update({"status": "CLOSED"})
        db.commit()
    run(date.today())
    assert len(notices(emp["id"])) == 1, "only the hand-over"


def test_an_incident_gets_an_owner_and_a_due_date(tenant):
    j, emp = job(tenant), make_employee(tenant)
    i = tenant.post("/api/safety/incidents", json={"job_id": j["id"], "kind": "Near miss", "description": "Plank fell"}).json()["incident"]
    past = tenant.put("/api/follow-up/incident/%d" % i["id"], json={"owner_id": emp["id"], "due_date": "2020-01-01"})
    assert past.status_code == 400
    due = (date.today() + timedelta(days=1)).isoformat()
    assert tenant.put("/api/follow-up/incident/%d" % i["id"], json={"owner_id": emp["id"], "due_date": due}).status_code == 200
    got = [x for x in tenant.get("/api/safety").json()["incidents"] if x["id"] == i["id"]][0]
    assert (got["owner_id"], got["due_date"], got["overdue"]) == (emp["id"], due, False)
    run(date.today())
    assert notices(emp["id"])[-1] == "Incident %s: due tomorrow" % i["number"]


def test_a_permit_past_its_time_and_still_open_is_chased(tenant):
    j, emp = job(tenant), make_employee(tenant)
    p = tenant.post("/api/safety/permits", json=permit_body(j)).json()["permit"]
    assert tenant.put("/api/follow-up/permit/%d" % p["id"], json={"owner_id": emp["id"]}).status_code == 200
    ends = datetime.strptime(p["valid_to"], "%Y-%m-%d %H:%M")
    run(ends.date(), hour=max(ends.hour - 1, 0))
    assert len(notices(emp["id"])) == 1, "live: nothing to chase"
    run(ends.date() + timedelta(days=1))
    assert notices(emp["id"])[-1].startswith("Permit %s: still open" % p["number"])


def test_only_somebody_on_the_staff_and_only_an_open_item(tenant, second_tenant):
    j = job(tenant)
    n = ncr(tenant, j, date.today().isoformat())
    stranger = make_employee(second_tenant)
    assert tenant.put("/api/follow-up/ncr/%d" % n["id"], json={"owner_id": stranger["id"]}).status_code == 400
    assert tenant.put("/api/follow-up/bridge/%d" % n["id"], json={}).status_code == 404
    assert second_tenant.put("/api/follow-up/ncr/%d" % n["id"], json={}).status_code == 404
    people = tenant.get("/api/follow-up/people").json()["people"]
    assert all(p["id"] != stranger["id"] for p in people)
