"""Budget against actual by BOQ line and heading, with earned value: what the budget says, what the plan has done by today (PV),
what is actually done (EV), what it has cost (AC: store issues and subcontract work measured), CPI and SPI. A heading costing more
than its budget times the share done goes on "What needs you"."""
import uuid
from datetime import date, timedelta

from app import models
from app.db import SessionLocal
from test_boq import make_boq, saved


def d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def budget(tenant, jid, key, kind, rate):
    res = tenant.put("/api/jobs/%d/budget/lines/%s" % (jid, key), json={"items": [{"kind": kind, "description": kind, "uom": "", "coefficient": 1, "rate": rate}]})
    assert res.status_code == 200, res.text


def project(tenant):
    """The sample BOQ: excavation 500 cum and RCC 120 cum under SUBSTRUCTURE, masonry under SUPERSTRUCTURE; two lines budgeted,
    and a programme drawn line by line."""
    jid, boq = make_boq(tenant, "EV Towers %s" % uuid.uuid4().hex[:4])
    lines = {l["description"]: l for l in saved(tenant, boq)["lines"] if l["kind"] == "item"}
    exc, rcc = lines["Excavation in all types of soil"]["key"], lines["M25 grade RCC in raft"]["key"]
    budget(tenant, jid, exc, "LABOUR", 150)       # 500 x 150 = 75,000
    budget(tenant, jid, rcc, "MATERIAL", 7000)    # 120 x 7,000 = 840,000
    res = tenant.post("/api/jobs/%d/schedule/from-boq" % jid, json={"start": d(-10), "finish": d(30), "by": "item"})
    assert res.status_code == 200, res.text
    acts = {a["name"]: a for a in tenant.get("/api/jobs/%d/schedule" % jid).json()["activities"]}
    return jid, boq["id"], exc, rcc, acts


def issue(jid, boq_id, key, value):
    """Material worth `value` issued from a store against a BOQ line."""
    with SessionLocal() as db:
        job = db.get(models.DBJob, jid)
        line = db.query(models.DBBoqLine).filter(models.DBBoqLine.boq_id == boq_id, models.DBBoqLine.key == key).first()
        store = models.DBStore(client_id=job.client_id, code="S%s" % uuid.uuid4().hex[:4], name="Site store", type="SITE")
        item = models.DBItem(client_id=job.client_id, kind="RM", item_code="CEM-%s" % uuid.uuid4().hex[:6], item_name="Cement")
        db.add_all([store, item])
        db.flush()
        db.add(models.DBStoreStockLedger(txn_date=date.today(), store_id=store.id, item_id=item.id, movement_type="ISSUE_OUT", qty_out=10, rate=value / 10,
                                         value=value, ref_doc_type="ISSUE", ref_doc_id=1, project_id=jid, boq_item_id=line.id))
        db.commit()


def measured(jid, key, qty, rate):
    """A subcontractor's work on a BOQ line, measured in the order's book."""
    with SessionLocal() as db:
        job = db.get(models.DBJob, jid)
        o = models.DBSubcontractOrder(client_id=job.client_id, job_id=jid, status="APPROVED")
        db.add(o)
        db.flush()
        i = models.DBSubcontractItem(order_id=o.id, item_description="Excavation", uom="cum", quantity=500, unit_rate=rate, boq_key=key)
        db.add(i)
        db.flush()
        db.add(models.DBSubMeasurement(client_id=job.client_id, order_id=o.id, item_id=i.id, quantity=qty, measured_on=d(0)))
        db.commit()


def ev(tenant, jid):
    res = tenant.get("/api/jobs/%d/budget/earned-value" % jid)
    assert res.status_code == 200, res.text
    return res.json()


def test_planned_earned_and_actual_by_line_and_heading(tenant):
    jid, boq_id, exc, rcc, acts = project(tenant)
    exc_act = next(a for a in acts.values() if a["name"].startswith("Excavation"))
    assert tenant.post("/api/schedule/activities/%d/progress" % exc_act["id"], json={"percent": 50}).status_code == 200
    issue(jid, boq_id, rcc, 50000)
    measured(jid, exc, 300, 160)              # 300 cum at 160 = 48,000

    v = ev(tenant, jid)
    line = {l["key"]: l for l in v["lines"]}
    e, r = line[exc], line[rcc]
    assert e["budget"] == 75000 and e["done_percent"] == 50 and e["ev"] == 37500 and e["progress_from"] == "line"
    assert e["subcontract"] == 48000 and e["ac"] == 48000 and e["overrun"] is True and e["cpi"] == round(37500 / 48000, 2)
    assert r["material"] == 50000 and r["ac"] == 50000 and r["ev"] == 0
    assert e["pv"] == round(75000 * e["planned_percent"] / 100, 2) and e["planned_percent"] > 0

    sub = next(h for h in v["headings"] if h["description"] == "SUBSTRUCTURE")
    assert sub["budget"] == 915000 and sub["ac"] == 98000 and sub["ev"] == 37500 and sub["overrun"] and sub["over_by"] == 60500
    sup = next(h for h in v["headings"] if h["description"] == "SUPERSTRUCTURE")
    assert sup["budget"] == 0 and not sup["overrun"], "a heading with no budget is not called over it"

    t = v["total"]
    assert t["budget"] == 915000 and t["ev"] == 37500 and t["ac"] == 98000
    assert t["cpi"] == round(37500 / 98000, 2) and t["spi"] == round(t["ev"] / t["pv"], 2) and t["eac"] == round(915000 / t["cpi"], 2)
    assert t["overruns"] == 1

    # On "What needs you" (and so the morning digest).
    att = tenant.get("/api/attention").json()
    items = att if isinstance(att, list) else att.get("items", [])
    over = next(i for i in items if i["kind"] == "budget_overrun")
    assert "SUBSTRUCTURE" in over["detail"] and over["count"] == 1

    # The workbook.
    x = tenant.get("/api/jobs/%d/budget/earned-value.xlsx" % jid)
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_work_ahead_of_its_cost_is_not_an_overrun(tenant):
    jid, boq_id, exc, rcc, acts = project(tenant)
    exc_act = next(a for a in acts.values() if a["name"].startswith("Excavation"))
    tenant.post("/api/schedule/activities/%d/progress" % exc_act["id"], json={"percent": 80})     # worth 60,000
    measured(jid, exc, 300, 160)                                                                    # cost 48,000
    v = ev(tenant, jid)
    e = next(l for l in v["lines"] if l["key"] == exc)
    assert not e["overrun"] and e["cpi"] == round(60000 / 48000, 2)
    assert not any(h["overrun"] for h in v["headings"])
    items = tenant.get("/api/attention").json()
    items = items if isinstance(items, list) else items.get("items", [])
    assert not any(i["kind"] == "budget_overrun" for i in items)


def test_cost_not_against_a_line_is_counted_apart(tenant):
    jid, boq_id, exc, rcc, acts = project(tenant)
    measured(jid, "", 10, 100)
    v = ev(tenant, jid)
    assert v["not_against_a_line"]["subcontract"] == 1000 and v["total"]["ac"] == 1000 and v["total"]["ac_on_lines"] == 0


def test_a_project_with_no_programme_or_budget_still_answers(tenant):
    jid, boq = make_boq(tenant, "Bare site")
    saved(tenant, boq)
    v = ev(tenant, jid)
    assert v["total"]["budget"] == 0 and v["total"]["cpi"] is None and v["total"]["spi"] is None
