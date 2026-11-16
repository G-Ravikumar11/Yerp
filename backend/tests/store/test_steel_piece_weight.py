"""Steel counted in Numbers: what one piece weighs is kept on the item, every steel quantity becomes kilograms in one place, and a steel item that
cannot be weighed is never skipped - it is reported by name, id and unit, an issue of it is refused, and the schedule is not approved meanwhile."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import db as database, models
from app.models.store_core import DBStoreItemSettings, MovementType
from app.services import steel_allowance as steel
from app.services.stock_ledger import get_balance, post_movement
from store.test_p3_outward import API, _leave_no_stock_behind, issue_body, staff, world  # noqa: F401
from store.test_steel_allowance import BBS_KG, with_steel

D = Decimal
NAME = "TMT Fe500D 12 mm"


def body(name=NAME, unit="Nos", **extra):
    return {"kind": "RM", "item_name": name, "item_type": "Purchased", "units_of_measure": unit, **extra}


def make(tenant, **kw):
    return tenant.post("/api/items", json=body(**kw))


def detail(tenant, item_id):
    return tenant.get("/api/items/%d" % item_id).json()["item"]


class It:
    """Just enough of an item for the conversion."""
    def __init__(self, weight=None, unit="Nos"):
        self.item_name, self.description, self.segment, self.category, self.item_category, self.kind = NAME, "", "", "", "", "RM"
        self.weight_per_piece_kg, self.units_of_measure = weight, unit


# --- the conversion --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("unit,qty,weight,kg,status", [
    ("kg", "250", None, "250", steel.WEIGHED),
    ("Kgs", "250.5", None, "250.5", steel.WEIGHED),
    ("MT", "2", None, "2000", steel.WEIGHED),                          # once x 1000, not twice
    ("tonne", "0.5", None, "500", steel.WEIGHED),
    ("Quintal", "3", None, "300", steel.WEIGHED),
    ("Nos", "100", "10.67", "1067.00", steel.WEIGHED),
    ("pcs", "100", "10.67", "1067.00", steel.WEIGHED),
    ("Nos", "100", None, None, steel.MISSING_WEIGHT),
    ("Nos", "100", "0", None, steel.MISSING_WEIGHT),
    ("Nos", "100", "-1", None, steel.MISSING_WEIGHT),
    ("Bags", "100", "10.67", None, steel.UNSUPPORTED_UNIT),             # a weight per piece is applied to a count, nothing else
    ("cum", "5", None, None, steel.UNSUPPORTED_UNIT),
    ("", "5", "10", None, steel.UNSUPPORTED_UNIT),
    ("kg", "abc", None, None, steel.CALC_ERROR),
])
def test_every_steel_quantity_becomes_kilograms_in_one_place_or_is_said_not_to(unit, qty, weight, kg, status):
    got, st, why = steel.weigh(It(weight), qty, unit)
    assert st == status and (got is None) == (kg is None) and (kg is None or got == D(kg))
    assert bool(why) == (status != steel.WEIGHED)
    if status == steel.MISSING_WEIGHT:
        assert "Weight per piece" in why and "item master" in why


def test_a_weight_per_piece_is_cleaned_to_four_places_and_refused_when_it_makes_no_sense():
    assert steel.clean_piece_weight("10.67") == (D("10.6700"), "") and steel.clean_piece_weight(None) == (None, "") and steel.clean_piece_weight("  ") == (None, "")
    for bad in ("0", "-2", "abc", "nan", "inf", "100001", "0.00001"):
        w, why = steel.clean_piece_weight(bad)
        assert w is None and why, bad


# --- the item master ---------------------------------------------------------------------------------------------------------

def test_steel_in_kg_or_mt_needs_no_weight_per_piece_and_any_given_is_not_kept(tenant):
    for unit, name in (("Kgs", NAME), ("MT", "TMT Fe500D 16 mm"), ("kg", "TMT Fe500D 20 mm")):
        res = make(tenant, name=name, unit=unit, weight_per_piece_kg=7.5)
        assert res.status_code == 200, res.text
        got = detail(tenant, res.json()["item"]["id"])
        assert got["weight_per_piece_kg"] is None and got["is_steel"] is True and got["weight_status"] == "NA"


def test_steel_in_numbers_needs_a_positive_weight_per_piece(tenant):
    ok = make(tenant, weight_per_piece_kg=10.67)
    assert ok.status_code == 200, ok.text
    got = detail(tenant, ok.json()["item"]["id"])
    assert (got["weight_per_piece_kg"], got["weight_status"], got["is_steel"]) == ("10.6700", "OK", True)
    for i, (value, words) in enumerate(((None, "required"), (0, "more than zero"), (-3, "more than zero"), (1000000, "100,000"))):
        extra = {} if value is None else {"weight_per_piece_kg": value}
        res = make(tenant, name="TMT Fe500D %d mm" % (16, 20, 25, 28)[i], **extra)
        assert res.status_code == 400 and words in res.json()["detail"], (value, res.text)
        assert "TMT Fe500D" in res.json()["detail"]
    assert make(tenant, name="TMT Fe500D 32 mm", weight_per_piece_kg="abc").status_code == 422                 # not a number at all


def test_other_items_in_numbers_are_not_asked_for_a_weight(tenant):
    for name, kw in (("Safety Helmet", {}), ("Shuttering Plate", {"weight_per_piece_kg": 4})):
        res = make(tenant, name=name, **kw)
        assert res.status_code == 200, res.text
        got = detail(tenant, res.json()["item"]["id"])
        assert got["weight_per_piece_kg"] is None and got["weight_status"] == "NA" and got["is_steel"] is False
    work = tenant.post("/api/items", json={"kind": "FG", "item_name": "Steel fixing 12 mm", "units_of_measure": "Nos", "item_type": "Work"})
    assert work.status_code == 200, work.text                                                                 # a work item is not a stock of steel
    cat = tenant.post("/api/items/categories", json={"name": "Steel"})
    if cat.status_code == 200:                                                                                  # filed under a Steel category, with no diameter in its name
        res = make(tenant, name="Binding wire coil", item_category="Steel")
        assert res.status_code == 400 and "Weight Per Piece" in res.json()["detail"]


def test_changing_the_unit_to_numbers_needs_the_weight_and_back_clears_it(tenant):
    made = make(tenant, unit="Kgs").json()["item"]
    url = "/api/items/%d" % made["id"]
    put = lambda **kw: tenant.put(url, json=body(**kw))
    refused = put(unit="Nos")                                                                                    # kg -> Numbers, no weight
    assert refused.status_code == 400 and "Weight Per Piece" in refused.json()["detail"]
    assert detail(tenant, made["id"])["units_of_measure"] == "Kgs"                                                # nothing changed
    assert put(unit="Nos", weight_per_piece_kg=10.67).status_code == 200
    assert (detail(tenant, made["id"])["units_of_measure"], detail(tenant, made["id"])["weight_per_piece_kg"]) == ("Nos", "10.6700")
    assert put(unit="Nos", name="TMT Fe500D 12 mm", remarks="edited").status_code == 200                           # an edit that leaves it out keeps it
    assert detail(tenant, made["id"])["weight_per_piece_kg"] == "10.6700"
    assert put(unit="Kgs", weight_per_piece_kg=10.67).status_code == 200                                          # Numbers -> kg: the old figure is gone
    got = detail(tenant, made["id"])
    assert got["weight_per_piece_kg"] is None and got["weight_status"] == "NA"
    with database.SessionLocal() as s:
        assert s.get(models.DBItem, made["id"]).weight_per_piece_kg is None
    assert put(unit="MT").status_code == 200


def test_a_bulk_change_to_numbers_is_refused_for_steel_and_a_change_away_clears_the_weight(tenant):
    a = make(tenant, name="TMT Fe500D 8 mm", unit="Kgs").json()["item"]["id"]
    b = make(tenant, name="TMT Fe500D 10 mm", weight_per_piece_kg=6.2).json()["item"]["id"]
    helmet = make(tenant, name="Safety Helmet").json()["item"]["id"]
    res = tenant.post("/api/items/bulk-update", json={"ids": [a, helmet], "units_of_measure": "Nos"})
    assert res.status_code == 400 and "TMT Fe500D 8 mm" in res.json()["detail"] and "Weight Per Piece" in res.json()["detail"]
    assert detail(tenant, helmet)["units_of_measure"] == "Nos" and detail(tenant, a)["units_of_measure"] == "Kgs"
    assert tenant.post("/api/items/bulk-update", json={"ids": [b], "units_of_measure": "Kgs"}).status_code == 200
    assert detail(tenant, b)["weight_per_piece_kg"] is None


def test_steel_in_numbers_with_no_weight_is_listed_for_correction_and_never_given_one(tenant, account):
    w = world(account)
    with database.SessionLocal() as s:
        old = models.DBItem(client_id=w.client_id, kind="RM", item_code="OLD-TMT", item_name="TMT Fe500D 25 mm", units_of_measure="Nos")
        fine = models.DBItem(client_id=w.client_id, kind="RM", item_code="OLD-OK", item_name="TMT Fe500D 28 mm", units_of_measure="Nos", weight_per_piece_kg=D("38"))
        kgs = models.DBItem(client_id=w.client_id, kind="RM", item_code="OLD-KG", item_name="TMT Fe500D 32 mm", units_of_measure="Kgs")
        s.add_all([old, fine, kgs])
        s.commit()
        old_id = old.id
    listed = tenant.get("/api/items/steel-weights/missing").json()["items"]
    assert [i["id"] for i in listed] == [old_id] and "Update the item master" in listed[0]["reason"]
    assert detail(tenant, old_id)["weight_per_piece_kg"] is None and detail(tenant, old_id)["weight_status"] == "MISSING"        # flagged, not invented
    assert tenant.put("/api/items/%d" % old_id, json=body(name="TMT Fe500D 25 mm", weight_per_piece_kg=33.5)).status_code == 200
    assert tenant.get("/api/items/steel-weights/missing").json()["items"] == []


# --- the BBS ------------------------------------------------------------------------------------------------------------------

def steel_item(w, name, unit, base, qty, weight=None, code=None):
    """A steel item in the store with `qty` of it (in its base unit) and what one piece weighs, if counted."""
    with database.SessionLocal() as s:
        it = models.DBItem(client_id=w.client_id, kind="RM", item_code=code or ("ST-%d-%s" % (w.project, unit)), item_name=name, units_of_measure=unit,
                           weight_per_piece_kg=None if weight is None else D(str(weight)))
        s.add(it)
        s.flush()
        s.add(DBStoreItemSettings(item_id=it.id, category="CONSUMABLE", base_uom=base))
        post_movement(s, movement_type=MovementType.OPENING_IN, store_id=w.central, item_id=it.id, qty=D(str(qty)), rate=D("62"), txn_date=date.today() - timedelta(days=30),
                      project_id=None, ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        s.commit()
        return it.id


def big_schedule(w):
    """An approved schedule large enough that nothing here is past its allowance: 1000 bars of 12 mm x 12 m = 10,667 kg."""
    with database.SessionLocal() as s:
        e = s.query(models.DBBbsEntry).filter(models.DBBbsEntry.job_id == w.project).first()
        e.num_bars = 1000
        s.commit()


def line(item_id, qty, uom, w):
    return {"item_id": item_id, "qty": str(qty), "uom": uom, "boq_item_id": w.boq[0]}


def test_the_bbs_adds_up_kg_mt_and_numbers_together(account):
    tenant = account["client"]
    w = with_steel(account)
    big_schedule(w)
    kg = steel_item(w, "TMT Fe500D 12 mm (loose)", "Kgs", "kg", 5000)
    mt = steel_item(w, "TMT Fe500D 12 mm (tonnes)", "MT", "MT", 10)
    nos = steel_item(w, "TMT Fe500D 12 mm (bars)", "Nos", "nos", 500, weight="10.67")
    for item_id, qty, uom in ((kg, "1000", "kg"), (mt, "1", "MT"), (nos, "100", "nos")):
        res = tenant.post(API + "/issue/direct", json=issue_body(w, lines=[line(item_id, qty, uom, w)]))
        assert res.status_code == 200 and res.json()["status"] == "POSTED", res.text
    rec = tenant.get("/api/bbs/steel?job_id=%d" % w.project).json()
    [row] = [r for r in rec["rows"] if r["diameter_mm"] == 12]
    assert row["issued_kg"] == 1000 + 1000 + 1067                                                               # 1000 kg + 1 MT x 1000 + 100 x 10.67
    assert rec["blocked"] is False and rec["problems"] == [] and rec["unweighed"] == [] and row["status"] == "OK"
    by_name = {i["item_name"]: i for i in rec["items"]}
    assert all(i["status"] == "WEIGHED" for i in rec["items"]) and len(rec["items"]) == 3
    bars = by_name["TMT Fe500D 12 mm (bars)"]
    assert (bars["unit"], bars["quantity"], bars["weight_per_piece_kg"], bars["total_kg"], bars["diameter_mm"]) == ("nos", 100, 10.67, pytest.approx(1067.0), 12)
    assert by_name["TMT Fe500D 12 mm (tonnes)"]["total_kg"] == 1000 and by_name["TMT Fe500D 12 mm (loose)"]["weight_per_piece_kg"] is None
    with database.SessionLocal() as s:                                                                          # the store counts what it always counted
        assert get_balance(s, w.central, nos).qty == D("400") and get_balance(s, w.central, mt).qty == D("9") and get_balance(s, w.central, kg).qty == D("4000")


def test_steel_that_cannot_be_weighed_blocks_the_check_and_the_approval_until_it_is_corrected(account):
    tenant = account["client"]
    w = with_steel(account, bbs=False)
    with database.SessionLocal() as s:
        s.add(models.DBBbsEntry(client_id=w.client_id, job_id=w.project, entry_key="k-draft-%d" % w.project, element="Column", bar_mark="C9", diameter_mm=12,
                                num_bars=100, cutting_length_mm=12000, status="Draft"))
        s.commit()
    legacy = steel_item(w, "TMT Fe500D 12 mm (old bars)", "Nos", "nos", 300, weight=None, code="LEG-1")                 # made before weights were kept
    # Issued before there was a schedule to check it against - the project had none, so nothing was held.
    assert tenant.post(API + "/issue/direct", json=issue_body(w, lines=[line(legacy, 50, "nos", w)])).status_code == 200
    rec = tenant.get("/api/bbs/steel?job_id=%d" % w.project).json()
    assert rec["blocked"] is True and rec["unweighed"] == ["TMT Fe500D 12 mm (old bars)"]
    [p] = rec["problems"]
    assert (p["item_id"], p["item_name"], p["unit"], p["status"], p["quantity"]) == (legacy, "TMT Fe500D 12 mm (old bars)", "nos", "MISSING_WEIGHT_PER_PIECE", 50)
    assert "Update the item master" in p["reason"]
    assert rec["items"][0]["total_kg"] is None and rec["rows"] == []                                              # not shown as weighed; no weight invented
    with database.SessionLocal() as s:
        entry = s.query(models.DBBbsEntry).filter(models.DBBbsEntry.job_id == w.project, models.DBBbsEntry.status == "Draft").one()
        ids = [entry.id]
    refused = tenant.post("/api/bbs/approve", json={"ids": ids})
    assert refused.status_code == 409 and "cannot be approved yet" in refused.json()["detail"] and str(legacy) in refused.json()["detail"]
    with database.SessionLocal() as s:
        assert s.get(models.DBBbsEntry, ids[0]).status == "Draft"
    # Corrected in the item master: it weighs, and the schedule can be approved.
    assert tenant.put("/api/items/%d" % legacy, json=body(name="TMT Fe500D 12 mm (old bars)", weight_per_piece_kg=10.67)).status_code == 200
    rec = tenant.get("/api/bbs/steel?job_id=%d" % w.project).json()
    assert rec["blocked"] is False and rec["items"][0]["total_kg"] == pytest.approx(533.5) and rec["rows"][0]["issued_kg"] == 533.5
    assert tenant.post("/api/bbs/approve", json={"ids": ids}).json()["approved"] == 1


def test_an_issue_of_steel_that_cannot_be_weighed_is_refused_where_there_is_a_schedule(account):
    tenant = account["client"]
    w = with_steel(account)
    legacy = steel_item(w, "TMT Fe500D 12 mm (old bars)", "Nos", "nos", 300, weight=None, code="LEG-2")
    res = tenant.post(API + "/issue/direct", json=issue_body(w, lines=[line(legacy, 10, "nos", w)]))
    assert res.status_code == 409 and "cannot be weighed" in res.json()["detail"] and "TMT Fe500D 12 mm (old bars)" in res.json()["detail"] and "unit nos" in res.json()["detail"]
    assert str(legacy) in res.json()["detail"] and "Weight per piece is missing" in res.json()["detail"]
    draft = tenant.post(API + "/issue", json=issue_body(w, lines=[line(legacy, 10, "nos", w)]))
    assert draft.status_code == 409                                                                             # not even a draft
    with database.SessionLocal() as s:
        assert get_balance(s, w.central, legacy).qty == D("300")
    # No schedule on another project: nothing to check against, so nothing held.
    with database.SessionLocal() as s:
        s.query(models.DBBbsEntry).filter(models.DBBbsEntry.job_id == w.project).delete()
        s.commit()
    assert tenant.post(API + "/issue/direct", json=issue_body(w, lines=[line(legacy, 10, "nos", w)])).status_code == 200


def test_the_allowance_is_the_same_whatever_unit_the_steel_is_counted_in(account, portal):
    """BBS 1,066.7 kg + 2% = 1,088 kg may be drawn. 100 bars at 10.67 kg is 1,067 kg: inside. 100 more is not, and waits for approval - as kg would."""
    tenant = account["client"]
    w = with_steel(account)
    nos = steel_item(w, "TMT Fe500D 12 mm (bars)", "Nos", "nos", 500, weight="10.67")
    first = tenant.post(API + "/issue/direct", json=issue_body(w, lines=[line(nos, 100, "nos", w)]))
    assert first.status_code == 200 and first.json()["status"] == "POSTED"
    assert BBS_KG < 1067 < BBS_KG * 1.02
    staff(account, portal, ["store.outward.direct_issue"], [w.central])
    more = portal.post(API + "/issue/direct", json=issue_body(w, lines=[line(nos, 100, "nos", w)]))
    assert more.status_code == 200, more.text
    got = more.json()
    assert got["held_for_steel"] is True and got["status"] == "SUBMITTED" and "12 mm" in got["steel_over"][0] and "2,134 kg" in got["steel_over"][0]
    rec = tenant.get("/api/bbs/steel?job_id=%d" % w.project).json()
    assert rec["rows"][0]["issued_kg"] == 1067 and rec["blocked"] is False
    with database.SessionLocal() as s:
        assert get_balance(s, w.central, nos).qty == D("400")                                                   # the held issue moved no stock


def test_wastage_loss_weighs_steel_counted_in_numbers_too(account):
    tenant = account["client"]
    w = with_steel(account)
    nos = steel_item(w, "TMT Fe500D 12 mm (bars)", "Nos", "nos", 500, weight="10.67")
    assert tenant.post(API + "/issue/direct", json=issue_body(w, lines=[line(nos, 150, "nos", w)])).status_code == 200      # 1,600.5 kg against 1,088 allowed
    got = tenant.get("/api/jobs/%d/wastage-loss" % w.project).json()
    [row] = [r for r in got["rows"] if r["item"] == "Steel 12 mm"]
    assert row["used"] == 1600.5 and row["over"] == round(1600.5 - round(BBS_KG * 1.02, 1), 1) and row["value"] > 0
