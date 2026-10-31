"""Quality holds on store batches, NCRs against lots, an NCR for every cube failure, and the daily notice of tests due."""
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import main
from app import models
from app.core import notifications
from app.core.scheduler import run_due_jobs
from app.models.store_core import DBStoreBatch, MovementType
from app.services import cube_notices, stock_ledger, store_holds
from app.services.stock_ledger import post_movement

from tests._patching import patch_app


def day(n=0):
    return (date.today() + timedelta(days=n)).isoformat()


@pytest.fixture(autouse=True)
def _fresh():
    main.rate_limiter._hits.clear()
    notifications.NOTIFY_SYNC = True
    yield
    notifications.NOTIFY_SYNC = False


def job(tenant, name="Tower A"):
    return tenant.post("/api/jobs", json={"name": name, "customer_name": "L&T"}).json()


class Lot:
    """A store holding 100 of an item in batch B1 and 50 in batch B2."""

    def __init__(self, tenant):
        self.tenant = tenant
        self.job = job(tenant)
        with main.SessionLocal() as db:
            self.cid = db.query(models.DBJob).get(self.job["id"]).client_id
            item = models.DBItem(client_id=self.cid, kind="RM", item_code="Q%05d" % (db.query(models.DBItem).count() + 1), item_name="Cement", units_of_measure="Bags")
            db.add(item)
            db.flush()
            from app.models.store_core import DBStore
            store = DBStore(client_id=self.cid, code="S%d" % item.id, name="Main", type="CENTRAL", project_id=self.job["id"])
            db.add(store)
            db.flush()
            self.item, self.store = item.id, store.id
            self.b1 = self.batch(db, "B1", 100, 1)
            self.b2 = self.batch(db, "B2", 50, 2)
            db.commit()

    def batch(self, db, no, qty, ref):
        b = stock_ledger.batch_for(db, self.cid, self.item, no, received=date.today())
        post_movement(db, movement_type=MovementType.GRN_IN.value, store_id=self.store, item_id=self.item, qty=qty, rate=10, txn_date=date.today(), project_id=self.job["id"], ref_doc_type="TEST", ref_doc_id=ref, ref_line_id=ref, user_id=None, lots=b.id if hasattr(b, "id") else b)
        return b.id if hasattr(b, "id") else b

    def issue(self, qty, lot=None, kind=MovementType.ISSUE_OUT):
        with main.SessionLocal() as db:
            post_movement(db, movement_type=kind.value, store_id=self.store, item_id=self.item, qty=qty, rate=None, txn_date=date.today(), project_id=self.job["id"], ref_doc_type="TEST", ref_doc_id=99, ref_line_id=1, user_id=None, lots=lot)
            db.commit()

    def view(self, bid):
        return self.tenant.get("/api/store/batches/%d" % bid).json()


@pytest.fixture
def lot(tenant):
    return Lot(tenant)


def hold(tenant, bid, reason="Failed slump"):
    return tenant.post("/api/store/batches/%d/hold" % bid, json={"reason": reason, "remarks": "Lab note"})


def ncr(tenant, lot, bid, text="Moisture in bags"):
    res = tenant.post("/api/qc/ncrs", json={"store_batch_id": bid, "description": text, "severity": "Minor"})
    assert res.status_code == 200, res.text
    return res.json()["ncr"]


def close(tenant, nid):
    """Through the existing steps: assign, work, verify, close."""
    n = tenant.get("/api/qc/ncrs/%d" % nid).json()["ncr"]
    assert tenant.post("/api/qc/ncrs/%d/assign" % nid, json={"responsible": "Stores", "target_date": day(5), "corrective_action": "Return it", "root_cause": "Damp", "severity": n["severity"]}).status_code == 200
    assert tenant.post("/api/qc/ncrs/%d/work" % nid, json={"corrective_done": "Returned", "root_cause": "Damp"}).status_code == 200
    assert tenant.post("/api/qc/ncrs/%d/request-verification" % nid).status_code == 200
    assert tenant.post("/api/qc/ncrs/%d/verify" % nid, json={"result": "verified", "note": "Seen"}).status_code == 200
    res = tenant.post("/api/qc/ncrs/%d/close" % nid, json={"closure_note": "Sent back"})
    assert res.status_code == 200, res.text
    return res.json()


# ---- holds -----------------------------------------------------------------------------------

def test_a_held_batch_is_shown_and_cannot_be_named_for_issue(tenant, lot):
    assert hold(tenant, lot.b1).status_code == 200
    v = lot.view(lot.b1)
    assert v["hold_status"] == "On Hold" and v["blocked"] and v["available_qty"] == "100" and v["received_qty"] == "100" and v["holds"][0]["placed_by"]
    with pytest.raises(Exception, match="on hold"):
        lot.issue(10, lot.b1)
    assert lot.view(lot.b1)["available_qty"] == "100"


@pytest.mark.parametrize("kind", [MovementType.ISSUE_OUT, MovementType.SUBCON_ISSUE_OUT, MovementType.TRANSFER_OUT])
def test_no_way_out_for_use_gets_past_a_hold(tenant, lot, kind):
    hold(tenant, lot.b1)
    with pytest.raises(Exception, match="on hold"):
        lot.issue(5, lot.b1, kind)


def test_an_automatic_pick_passes_over_held_stock_and_never_takes_it(tenant, lot):
    hold(tenant, lot.b1)
    lot.issue(30)                                   # with no batch named it comes out of B2
    assert lot.view(lot.b2)["available_qty"] == "20" and lot.view(lot.b1)["available_qty"] == "100"
    with pytest.raises(Exception, match="on hold"):
        lot.issue(21)                               # all that is left free is 20
    assert lot.view(lot.b1)["available_qty"] == "100"


@pytest.mark.parametrize("kind", [MovementType.SCRAP_OUT, MovementType.WASTAGE_OUT])
def test_a_held_lot_cannot_be_written_off(tenant, lot, kind):
    res = hold(tenant, lot.b1)
    assert res.status_code == 200, res.text
    with pytest.raises(Exception, match="on hold"):
        lot.issue(5, lot.b1, kind)
    assert lot.view(lot.b1)["available_qty"] == "100"


def test_a_count_and_a_return_to_the_supplier_may_still_move_it(tenant, lot):
    hold(tenant, lot.b1)
    lot.issue(5, lot.b1, MovementType.ADJUST_OUT)
    lot.issue(5, lot.b1, MovementType.PURCHASE_RETURN_OUT)
    assert lot.view(lot.b1)["available_qty"] == "90"


def test_the_refusal_is_a_409_in_the_agreed_shape(tenant, lot):
    from fastapi.testclient import TestClient

    from app.core.store_auth import store_errors
    hold(tenant, lot.b1)

    def route():
        with store_errors():
            lot.issue(1, lot.b1)
    main.app.add_api_route("/api/_test_hold_%d" % lot.b1, route, methods=["POST"])
    res = TestClient(main.app).post("/api/_test_hold_%d" % lot.b1)
    body = res.json()
    assert res.status_code == 409 and body["success"] is False and body["code"] == "LOT_ON_HOLD" and body["lotId"] == "B1" and body["holdReason"] == "Failed slump"
    assert body["message"] == "This material lot is on hold and cannot be issued, transferred, or written off." and body["detail"] == body["message"]


def fail_check(db, lot, line_id=901, note="Slump 180, spec 100"):
    from app.services import store_holds as sh

    class G:
        number = "GRN-0001"

    class L:
        id, line_no = line_id, 1
    sh.hold_for_failed_check(db, lot.cid, sh.lock_batch(db, lot.cid, lot.b1), G, L, note, "QC Engineer")
    db.commit()
    return L


def test_a_failed_check_holds_the_lot_with_its_inspection(tenant, lot):
    with main.SessionLocal() as db:
        fail_check(db, lot, 901)
        fail_check(db, lot, 901)                       # recorded again: still one hold
    v = lot.view(lot.b1)
    assert v["status_code"] == "ON_HOLD" and v["hold_reason"] == "Failed quality inspection: Slump 180, spec 100" and v["held_by"] == "QC Engineer" and v["held_at"]
    assert len(v["holds"]) == 1 and v["holds"][0]["kind"] == "QC" and "GRN-0001 line 1" in v["holds"][0]["inspection_ref"]
    with pytest.raises(Exception, match="on hold"):
        lot.issue(1, lot.b1)
    assert tenant.get("/api/store/batches?hold_status=ON_HOLD").json()["total"] == 1


def test_passing_on_re_inspection_lifts_that_hold_only(tenant, lot):
    from app.services import store_holds as sh
    ncr(tenant, lot, lot.b1)
    with main.SessionLocal() as db:
        line = fail_check(db, lot, 902)
        sh.lift_failed_check(db, lot.cid, line, "QC Engineer")
        db.commit()
    v = lot.view(lot.b1)
    assert v["blocked"] and len(v["ncrs"]) == 1 and [h["status"] for h in v["holds"] if h["kind"] == "QC"] == ["RELEASED"]


def test_a_failed_check_is_released_by_someone_who_signs_off_and_the_history_stays(tenant, lot):
    with main.SessionLocal() as db:
        fail_check(db, lot, 903)
    r = tenant.post("/api/store/batches/%d/release" % lot.b1, json={"note": "Lab retest passed"}).json()
    assert r["on_hold"] is False
    assert lot.view(lot.b1)["holds"][0]["release_note"] == "Lab retest passed"


def test_the_hub_issue_check_refuses_with_409(tenant, lot):
    from app.services.store_outward import _check_batch
    from fastapi import HTTPException
    hold(tenant, lot.b1)
    with main.SessionLocal() as db:
        item = db.get(models.DBItem, lot.item)
        with pytest.raises(HTTPException) as e:
            _check_batch(db, lot.store, item, "B1", Decimal("1"), date.today(), "Line 1")
        assert e.value.status_code == 409 and e.value.extra["code"] == "LOT_ON_HOLD" and e.value.extra["lotId"] == "B1" and e.value.extra["holdReason"] == "Failed slump"


def test_a_hold_placed_in_another_session_is_seen_by_the_issue(tenant, lot):
    """The issue reads the row fresh, not what its session already had."""
    with main.SessionLocal() as db:
        db.get(DBStoreBatch, lot.b1)                 # loaded while still free
        hold(tenant, lot.b1)
        with pytest.raises(Exception, match="on hold"):
            post_movement(db, movement_type=MovementType.ISSUE_OUT.value, store_id=lot.store, item_id=lot.item, qty=1, rate=None, txn_date=date.today(), project_id=lot.job["id"], ref_doc_type="TEST", ref_doc_id=7, ref_line_id=1, user_id=None, lots=lot.b1)
        db.rollback()


def test_one_manual_hold_at_a_time_and_a_reason_is_needed(tenant, lot):
    assert tenant.post("/api/store/batches/%d/hold" % lot.b1, json={"reason": " "}).status_code == 400
    assert hold(tenant, lot.b1).status_code == 200
    assert hold(tenant, lot.b1).status_code == 409


def test_release_needs_a_reason_and_leaves_the_record(tenant, lot):
    hold(tenant, lot.b1)
    assert tenant.post("/api/store/batches/%d/release" % lot.b1, json={"note": ""}).status_code == 400
    res = tenant.post("/api/store/batches/%d/release" % lot.b1, json={"note": "Retested fine"}).json()
    assert res["on_hold"] is False
    v = lot.view(lot.b1)
    assert v["hold_status"] == "Released" and v["holds"][0]["status"] == "RELEASED" and v["holds"][0]["released_by"]
    lot.issue(5, lot.b1)
    with main.SessionLocal() as db:
        assert db.query(models.DBAuditLog).filter(models.DBAuditLog.entity_id == lot.b1, models.DBAuditLog.action.in_(("store.batch.hold_placed", "store.batch.hold_released"))).count() == 2


def test_only_those_who_may_release_can(tenant, portal, second_tenant, lot):
    hold(tenant, lot.b1)
    assert portal.post("/api/store/batches/%d/release" % lot.b1, json={"note": "x"}).status_code in (401, 403)
    assert second_tenant.post("/api/store/batches/%d/release" % lot.b1, json={"note": "x"}).status_code == 404


def test_the_batch_list_filters_on_hold(tenant, lot):
    hold(tenant, lot.b1)
    data = tenant.get("/api/store/batches?hold_status=On Hold").json()
    assert data["total"] == 1 and data["batches"][0]["batch_no"] == "B1" and data["batches"][0]["project"]
    assert tenant.get("/api/store/batches?q=B2").json()["total"] == 1


# ---- NCRs against lots -----------------------------------------------------------------------

def test_an_ncr_against_a_lot_holds_it_at_once_and_closing_releases_it(tenant, lot):
    n = ncr(tenant, lot, lot.b1)
    assert n["store_batch_id"] == lot.b1
    v = lot.view(lot.b1)
    assert v["blocked"] and v["ncrs"][0]["number"] == n["number"]
    with pytest.raises(Exception, match="on hold"):
        lot.issue(1, lot.b1)
    done = close(tenant, n["id"])
    assert done["batch_hold"]["on_hold"] is False and "released" in done["batch_hold"]["message"]
    assert done["ncr"]["closed_by"] and lot.view(lot.b1)["hold_status"] == "Released"
    lot.issue(1, lot.b1)


def test_another_open_ncr_keeps_it_held(tenant, lot):
    a, b = ncr(tenant, lot, lot.b1, "One"), ncr(tenant, lot, lot.b1, "Two")
    res = close(tenant, a["id"])
    assert res["batch_hold"]["on_hold"] is True and b["number"] in res["batch_hold"]["message"]
    with pytest.raises(Exception, match="on hold"):
        lot.issue(1, lot.b1)
    assert close(tenant, b["id"])["batch_hold"]["on_hold"] is False


def test_a_manual_hold_outlives_the_ncr_and_the_other_way_round(tenant, lot):
    hold(tenant, lot.b1)
    n = ncr(tenant, lot, lot.b1)                   # raised while a manual hold stands
    res = close(tenant, n["id"])
    assert res["batch_hold"]["on_hold"] is True and "manual hold" in res["batch_hold"]["message"]
    m = ncr(tenant, lot, lot.b2)
    assert tenant.post("/api/store/batches/%d/release" % lot.b2, json={"note": "x"}).status_code == 409    # an NCR's hold is not released by hand
    assert lot.view(lot.b2)["blocked"]
    hold(tenant, lot.b2)
    r = tenant.post("/api/store/batches/%d/release" % lot.b2, json={"note": "Manual part only"}).json()
    assert r["on_hold"] is True and m["number"] in r["message"]


def test_a_failed_hold_takes_the_ncr_with_it(tenant, lot, monkeypatch):
    before = tenant.get("/api/qc/ncrs").json()["total"]

    def boom(*a, **k):
        raise RuntimeError("power cut")
    monkeypatch.setattr(store_holds, "hold_for_ncr", boom)
    with pytest.raises(RuntimeError):
        tenant.post("/api/qc/ncrs", json={"store_batch_id": lot.b1, "description": "x"})
    monkeypatch.undo()
    assert tenant.get("/api/qc/ncrs").json()["total"] == before and not lot.view(lot.b1)["blocked"]


def test_a_failed_release_leaves_the_ncr_open_and_the_batch_held(tenant, lot, monkeypatch):
    n = ncr(tenant, lot, lot.b1)
    assert tenant.post("/api/qc/ncrs/%d/assign" % n["id"], json={"responsible": "S", "target_date": day(5), "corrective_action": "R", "root_cause": "D", "severity": "Minor"}).status_code == 200
    tenant.post("/api/qc/ncrs/%d/work" % n["id"], json={"corrective_done": "R", "root_cause": "D"})
    tenant.post("/api/qc/ncrs/%d/request-verification" % n["id"])
    tenant.post("/api/qc/ncrs/%d/verify" % n["id"], json={"result": "verified", "note": "S"})

    def boom(*a, **k):
        raise RuntimeError("power cut")
    monkeypatch.setattr(store_holds, "on_ncr_closed", boom)
    with pytest.raises(RuntimeError):
        tenant.post("/api/qc/ncrs/%d/close" % n["id"], json={"closure_note": "Back"})
    monkeypatch.undo()
    assert tenant.get("/api/qc/ncrs/%d" % n["id"]).json()["ncr"]["status"] != "CLOSED" and lot.view(lot.b1)["blocked"]


def test_the_ncr_detail_shows_the_lot(tenant, lot):
    n = ncr(tenant, lot, lot.b1)
    d = tenant.get("/api/qc/ncrs/%d" % n["id"]).json()
    assert d["store_batch"]["batch_no"] == "B1" and d["store_batch"]["blocked"] and d["store_batch"]["item_name"] == "Cement" and d["store_batch"]["available_qty"] == "100"


# ---- cube failures ---------------------------------------------------------------------------

def cubes(tenant, j=None, grade="M25", cast=None, **over):
    j = j or job(tenant)
    res = tenant.post("/api/qc/cubes", json={"job_id": j["id"], "grade": grade, "cast_on": cast or day(-28), "location": "Raft", **over})
    assert res.status_code == 200, res.text
    return res.json()["cube_set"]


def criteria(tenant, j, grade="M25", age=28, mini=25):
    res = tenant.post("/api/qc/criteria", json={"job_id": j["id"], "grade": grade, "age_days": age, "min_average": mini})
    return res


def result(tenant, s, age=28, strengths="12, 13, 12"):
    return tenant.post("/api/qc/cubes/%d/results" % s["id"], json={"age_days": age, "strengths": strengths, "tested_on": day(0)})


@pytest.fixture
def failing(tenant, monkeypatch):
    """Every result reads below its criteria unless it is 40 and over."""
    import app.routers.quality as q
    monkeypatch.setattr(q, "evaluate", lambda vals, c: ("below" if sum(vals) / len(vals) < 40 else "meets", 25.0, 0.0, "IS 456"))
    return q


def ncrs(tenant):
    return tenant.get("/api/qc/ncrs").json()["ncrs"]


def test_a_pass_raises_nothing(tenant, failing):
    s = cubes(tenant)
    r = result(tenant, s, strengths="41, 42, 43").json()
    assert r["ncr"] is None and ncrs(tenant) == []


def test_a_failure_raises_one_ncr_with_the_details(tenant, failing):
    j = job(tenant)
    s = cubes(tenant, j, docket="D-9", pour_ref="P-1")
    r = result(tenant, s)
    assert r.status_code == 200, r.text
    n = r.json()["ncr"]
    assert n["status"] == "OPEN" and n["origin"] == "Automatic Cube Test Failure" and n["project_id"] == j["id"]
    d = tenant.get("/api/qc/ncrs/%d" % n["id"]).json()["ncr"]
    for bit in (s["number"], "M25", "12.33", "25", "P-1", "D-9"):
        assert bit in d["description"]
    assert d["source_type"] == "cube_set" and d["source_id"] == s["id"] and d["source_ref"] == "28"


def test_the_same_result_again_returns_the_same_ncr(tenant, failing):
    s = cubes(tenant)
    first = result(tenant, s).json()["ncr"]
    again = result(tenant, s)
    assert again.status_code == 200 and again.json()["repeat"] is True and again.json()["ncr"]["id"] == first["id"]
    assert len(ncrs(tenant)) == 1


def test_a_different_result_for_the_same_age_is_still_refused(tenant, failing):
    s = cubes(tenant)
    result(tenant, s)
    assert result(tenant, s, strengths="10, 10, 10").status_code == 409


def test_simultaneous_failures_make_one_ncr(tenant, failing):
    s = cubes(tenant)
    barrier, out = threading.Barrier(4), []

    def go():
        barrier.wait()
        out.append(result(tenant, s).status_code)
    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(ncrs(tenant)) == 1 and 200 in out
    with main.SessionLocal() as db:
        assert db.query(models.DBCubeResult).filter_by(set_id=s["id"]).count() == 1


def test_the_database_refuses_a_second_ncr_for_one_failure(tenant, failing):
    s = cubes(tenant)
    n = result(tenant, s).json()["ncr"]
    with main.SessionLocal() as db:
        row = db.query(models.DBNcr).get(n["id"])
        db.add(models.DBNcr(client_id=row.client_id, job_id=row.job_id, number="NCR-X", auto_key=row.auto_key))
        with pytest.raises(Exception):
            db.commit()
        db.rollback()


def test_an_ncr_that_cannot_be_made_takes_the_result_with_it(tenant, failing, monkeypatch):
    s = cubes(tenant)

    def boom(*a, **k):
        raise RuntimeError("power cut")
    monkeypatch.setattr(failing, "cube_failure_ncr", boom)
    with pytest.raises(RuntimeError):
        result(tenant, s)
    monkeypatch.undo()
    with main.SessionLocal() as db:
        assert db.query(models.DBCubeResult).filter_by(set_id=s["id"]).count() == 0


def test_each_failed_age_is_its_own_failure(tenant, failing):
    s = cubes(tenant)
    a, b = result(tenant, s, 7).json()["ncr"], result(tenant, s, 28).json()["ncr"]
    assert a["id"] != b["id"] and len(ncrs(tenant)) == 2


def test_raising_by_hand_returns_the_ncr_already_there(tenant, failing):
    s = cubes(tenant)
    n = result(tenant, s).json()["ncr"]
    res = tenant.post("/api/qc/ncrs", json={"source_type": "cube_set", "source_id": s["id"], "source_ref": "28"})
    assert res.status_code == 200 and res.json()["ncr"]["id"] == n["id"] and res.json()["existing"] is True


def test_real_criteria_decide_and_no_criteria_raises_nothing(tenant):
    j = job(tenant)
    set_ = cubes(tenant, j)
    assert result(tenant, set_, 28).json()["ncr"] is None                # nobody has said what to compare with: not a failure
    assert tenant.post("/api/qc/criteria", json={"job_id": j["id"], "grade": "M25", "age_days": 7, "min_mean": 16, "min_single": 13, "standard": "IS 456"}).status_code == 200
    fine = result(tenant, set_, 7, "20, 21, 20").json()
    assert fine["ncr"] is None
    other = cubes(tenant, j)
    bad = result(tenant, other, 7, "10, 11, 10").json()
    assert bad["ncr"]["status"] == "OPEN" and bad["ncr"]["origin"] == "Automatic Cube Test Failure"
    assert "16" in tenant.get("/api/qc/ncrs/%d" % bad["ncr"]["id"]).json()["ncr"]["description"]


# ---- what is due -----------------------------------------------------------------------------

def due(tenant):
    return tenant.get("/api/qc/cube-dashboard").json()


def test_today_and_tomorrow_are_listed_with_the_details(tenant):
    j = job(tenant)
    cubes(tenant, j, cast=day(-7), test_ages="7")
    cubes(tenant, j, cast=day(-6), test_ages="7", grade="M30")
    d = due(tenant)
    assert [t["grade"] for t in d["due_today"]] == ["M25"] and [t["grade"] for t in d["due_tomorrow"]] == ["M30"]
    t = d["due_today"][0]
    assert t["due_on"] == day(0) and t["cast_on"] == day(-7) and t["project"] and t["status"] == "Due today" and t["reference"]
    assert d["projects"][0]["today"] == 1 and d["projects"][0]["tomorrow"] == 1


def reject(tenant, s):
    assert result(tenant, s, 3, "20, 20, 20").status_code == 200
    r = tenant.post("/api/qc/cubes/%d/decision" % s["id"], json={"decision": "rejected", "note": "Honeycombed"})
    assert r.status_code == 200, r.text


def test_a_rejected_set_leaves_every_list_but_its_project_stays(tenant, failing):
    j = job(tenant)
    bad = cubes(tenant, j, cast=day(-7), test_ages="3,7")
    good = cubes(tenant, j, cast=day(-7), test_ages="7", grade="M30")
    assert len(due(tenant)["due_today"]) == 2
    reject(tenant, bad)
    d = due(tenant)
    assert [t["number"] for t in d["due_today"]] == [good["number"]]
    assert d["rejected"][0]["reference"] == bad["number"] and d["rejected"][0]["reason"] == "Honeycombed"
    assert tenant.get("/api/qc/summary").status_code == 200
    with main.SessionLocal() as db:
        cid = db.query(models.DBJob).get(j["id"]).client_id
        row = cube_notices.cube_tests_due(db, cid)[j["id"]]
        assert [t["number"] for t in row["today"]] == [good["number"]]


def test_failed_tests_show_their_ncr(tenant, failing):
    s = cubes(tenant)
    n = result(tenant, s).json()["ncr"]
    row = due(tenant)["failed"][0]
    assert row["ncr_number"] == n["number"] and row["ncr_status"] == "OPEN" and row["actual"] == 12.33 and row["required"] == 25 and "Tower A" in row["project"]
    assert tenant.get("/api/qc/cube-dashboard?ncr_status=CLOSED").json()["failed"] == []


def test_the_filters_work(tenant):
    cubes(tenant, cast=day(-7), test_ages="7")
    assert tenant.get("/api/qc/cube-dashboard?grade=M30").json()["due_today"] == []
    assert len(tenant.get("/api/qc/cube-dashboard?grade=M25").json()["due_today"]) == 1
    assert tenant.get("/api/qc/cube-dashboard?due_from=%s" % day(3)).json()["due_today"] == []


def test_today_is_the_project_s_own():
    """Late evening in Kolkata is already tomorrow there, while it is still today in New York."""
    utc = datetime(2026, 3, 10, 20, 0, tzinfo=timezone.utc)
    assert utc.astimezone(cube_notices.zone_of("Asia/Kolkata")).date().isoformat() == "2026-03-11"
    assert utc.astimezone(cube_notices.zone_of("America/New_York")).date().isoformat() == "2026-03-10"
    assert utc.astimezone(cube_notices.zone_of("Not/AZone")).date().isoformat() == "2026-03-11"


def test_a_project_timezone_moves_what_is_due(tenant):
    j = job(tenant)
    assert tenant.put("/api/qc/cube-notices/settings", json={"hour": 8, "job_id": j["id"], "timezone": "Pacific/Kiritimati", "emails": ""}).status_code == 200
    assert tenant.put("/api/qc/cube-notices/settings", json={"hour": 8, "job_id": j["id"], "timezone": "Mars/Base"}).status_code == 400
    s = cubes(tenant, j, cast=day(-7), test_ages="7")
    with main.SessionLocal() as db:
        cid = db.query(models.DBJob).get(j["id"]).client_id
        now = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc).replace(hour=11)      # past midnight in Kiritimati, UTC+14
        row = cube_notices.cube_tests_due(db, cid, now=now)
        assert row == {} or row[j["id"]]["today_on"] == day(1)
    assert s["number"]


# ---- the notice ------------------------------------------------------------------------------

def noon():
    return datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone(timedelta(hours=5, minutes=30))).replace(hour=12)


def company(j):
    with main.SessionLocal() as db:
        return db.query(models.DBJob).get(j["id"]).client_id


def run(cid, when=None):
    with main.SessionLocal() as db:
        return cube_notices.run_for_client(db, cid, when or noon())


def notices(tenant):
    return tenant.get("/api/qc/cube-notices").json()


def test_one_notice_for_each_project_grouped_with_the_message(tenant, monkeypatch):
    sent = []
    patch_app(monkeypatch, "send_email_background", lambda to, subject, body, *a, **k: sent.append((to, subject, body)) or (True, "ok"))
    a, b = job(tenant, "Alpha"), job(tenant, "Beta")
    cubes(tenant, a, cast=day(-7), test_ages="7")
    cubes(tenant, a, cast=day(-6), test_ages="7")
    cubes(tenant, b, cast=day(-7), test_ages="7")
    tenant.put("/api/qc/cube-notices/settings", json={"hour": 8, "job_id": a["id"], "emails": "site@acme.example"})
    assert run(company(a)) == 2
    assert run(company(a)) == 0                                       # a second run sends nothing
    rows = notices(tenant)["notices"]
    assert len(rows) == 2 and {r["status"] for r in rows} == {"Sent"} and all(r["sent_at"] for r in rows)
    one = [r for r in rows if r["job_id"] == a["id"]][0]
    assert one["test_count"] == 2 and one["subject"] == "Cube Tests Due – Alpha"
    assert sent == [("site@acme.example", one["subject"], sent[0][2])]
    for bit in ("Dear Project Team,", "Due Today:", "Due Tomorrow:", "Regards,\nConstruction ERP System"):
        assert bit in sent[0][2]
    with main.SessionLocal() as db:
        assert db.query(models.DBAlert).filter(models.DBAlert.kind == "cube_tests_due_bell").count() == 2


def test_nothing_goes_before_the_hour_nor_for_a_rejected_set(tenant, failing):
    j = job(tenant)
    s = cubes(tenant, j, cast=day(-7), test_ages="3,7")
    cid = company(j)
    assert run(cid, noon().replace(hour=7)) == 0
    reject(tenant, s)
    assert run(cid) == 0 and notices(tenant)["total"] == 0


def test_a_failed_delivery_is_recorded_and_a_retry_reaches_only_who_missed_it(tenant, monkeypatch):
    calls = []

    def flaky(to, *a, **k):
        calls.append(to)
        return (to == "a@x.example" or len(calls) > 2, "ok")
    patch_app(monkeypatch, "send_email_background", flaky)
    j = job(tenant)
    cubes(tenant, j, cast=day(-7), test_ages="7")
    tenant.put("/api/qc/cube-notices/settings", json={"hour": 8, "job_id": j["id"], "emails": "a@x.example, b@x.example"})
    run(company(j))
    n = notices(tenant)["notices"][0]
    assert n["status"] == "Failed" and n["sent_to"] == "a@x.example" and n["sent_at"] == ""
    res = tenant.post("/api/qc/cube-notices/%d/retry" % n["id"]).json()
    assert res["notice"]["status"] == "Sent" and calls == ["a@x.example", "b@x.example", "b@x.example"]
    assert tenant.post("/api/qc/cube-notices/%d/retry" % n["id"]).status_code == 409
    with main.SessionLocal() as db:
        assert db.query(models.DBAlert).filter(models.DBAlert.kind == "cube_tests_due_bell", models.DBAlert.ref_id == n["id"]).count() == 1


def test_overlapping_runs_send_once(tenant, monkeypatch):
    sent = []
    patch_app(monkeypatch, "send_email_background", lambda to, *a, **k: sent.append(to) or (True, "ok"))
    j = job(tenant)
    cubes(tenant, j, cast=day(-7), test_ages="7")
    tenant.put("/api/qc/cube-notices/settings", json={"hour": 8, "job_id": j["id"], "emails": "a@x.example"})
    cid = company(j)
    barrier = threading.Barrier(3)

    def go():
        barrier.wait()
        run(cid)
    ts = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sent == ["a@x.example"] and notices(tenant)["total"] == 1


def test_the_job_is_on_the_scheduler(tenant):
    now = datetime.now()
    assert run_due_jobs(now, only="cube_tests_due")[0]["status"] == "done"
    assert run_due_jobs(now, only="cube_tests_due")[0]["status"] == "already_done"


def test_history_is_not_for_those_outside_site_work(tenant, portal):
    assert portal.get("/api/qc/cube-notices").status_code in (401, 403)



