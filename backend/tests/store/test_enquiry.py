"""P1 stock enquiry over HTTP: balances by store, item and project with value; the item ledger card with its drill-down
to the document behind each movement; and where else an item is held. Only the stores a person works in."""
from datetime import date, timedelta
from decimal import Decimal

from app.models.store_core import MovementType
from app.services.stock_ledger import post_movement, reverse_document
from store.fixtures import db, store_world  # noqa: F401  (fixtures)
from store.test_masters import ok, sign_in, world  # noqa: F401  (fixtures)

D = Decimal
TODAY = date.today()
E = "/api/store/enquiry"


def move(db, w, mtype, qty, rate=None, store=None, item="cement", doc=("GRN", 1), **kw):
    e = post_movement(db, movement_type=mtype, store_id=store or w.central_id, item_id=w.item[item], qty=D(str(qty)),
                      rate=None if rate is None else D(str(rate)), txn_date=kw.pop("day", TODAY),
                      project_id=kw.pop("project_id", None), ref_doc_type=doc[0], ref_doc_id=doc[1], ref_line_id=1,
                      user_id=kw.pop("user_id", None), **kw)
    db.commit()
    return e


def test_balances_by_store_item_and_project(world, sign_in, db):
    w, owner = world, sign_in("owner")
    out = move(db, w, MovementType.TRANSFER_OUT, 100, doc=("TRANSFER", 1))
    move(db, w, MovementType.TRANSFER_IN, 100, out.rate, store=w.site_id, doc=("TRANSFER", 1))
    by_store = ok(owner.get(E + "/balances"))
    rows = {(r["store_code"], r["item_name"]): r for r in by_store["rows"]}
    assert len(rows) == 11
    cs = rows[("CS01", "Cement OPC 53")]
    assert (cs["qty"], cs["value"], cs["avg_rate"], cs["base_uom"], cs["below_reorder"]) == ("4900.000", "34300.00", "7.0000", "kg", False)
    assert rows[("ST01", "Cement OPC 53")]["project"].endswith("Tower A")
    total_opening = sum(D(q) * D(r) for q, r in ((5000, 7), (2000, 62), (3000, 62), (100, 1800), (80, 1500), (20000, 8),
                                                 (200, 85), (150, 450), (60, 180), (1000, 92)))
    assert by_store["summary"]["total_value"] == "%.2f" % total_opening and by_store["summary"]["stores"] == 2

    by_item = {r["item_name"]: r for r in ok(owner.get(E + "/balances?group=item"))["rows"]}
    assert (by_item["Cement OPC 53"]["qty"], by_item["Cement OPC 53"]["stores"]) == ("5000.000", ["CS01", "ST01"])
    by_project = {(r["project"], r["item_name"]): r for r in ok(owner.get(E + "/balances?group=project"))["rows"]}
    assert by_project[("Not on a project", "Cement OPC 53")]["qty"] == "4900.000"
    assert next(v for (p, n), v in by_project.items() if p.endswith("Tower A") and n == "Cement OPC 53")["qty"] == "100.000"

    only_site = ok(owner.get(E + "/balances?project_id=%d" % w.project_id))["rows"]
    assert [(r["store_code"], r["item_name"]) for r in only_site] == [("ST01", "Cement OPC 53")]
    assert [r["item_name"] for r in ok(owner.get(E + "/balances?q=tmt"))["rows"]] == ["TMT Steel 12mm", "TMT Steel 16mm"]
    assert {r["item_name"] for r in ok(owner.get(E + "/balances?category=returnable"))["rows"]} == {"Shuttering Plate"}
    assert owner.get(E + "/balances?group=colour").status_code == 400
    assert len(ok(owner.get(E))["items"]) == 11


def test_below_the_reorder_level_is_flagged(world, sign_in, db):
    w, owner = world, sign_in("owner")
    move(db, w, MovementType.ISSUE_OUT, 55, item="helmet", doc=("ISSUE", 2))
    helmet = next(r for r in ok(owner.get(E + "/balances?q=helmet"))["rows"])
    assert (helmet["qty"], helmet["reorder_level"], helmet["below_reorder"]) == ("5.000", "10.000", True)
    assert ok(owner.get(E + "/balances"))["summary"]["below_reorder"] == 1


def test_only_the_stores_a_person_works_in(world, sign_in, db):
    w = world
    out = move(db, w, MovementType.TRANSFER_OUT, 100, doc=("TRANSFER", 3))
    move(db, w, MovementType.TRANSFER_IN, 100, out.rate, store=w.site_id, doc=("TRANSFER", 3))
    site = sign_in("site_keeper")
    assert {r["store_code"] for r in ok(site.get(E + "/balances"))["rows"]} == {"ST01"}
    assert site.get(E + "/balances?store_id=%d" % w.central_id).status_code == 403
    assert site.get(E + "/items/%d/card?store_id=%d" % (w.item["cement"], w.central_id)).status_code == 403
    assert [s["store_code"] for s in ok(site.get(E + "/items/%d/availability" % w.item["cement"]))["stores"]] == ["ST01"]
    assert sign_in("viewer").get(E + "/balances").status_code == 403                 # no store.enquiry.view
    admin = sign_in("admin")
    assert {r["store_code"] for r in ok(admin.get(E + "/balances"))["rows"]} == {"CS01", "ST01"}


def test_another_company_sees_nothing(world, second_tenant):
    w = world
    assert second_tenant.get(E + "/balances").json()["rows"] == []
    assert second_tenant.get(E + "/items/%d/card?store_id=%d" % (w.item["cement"], w.central_id)).status_code == 404
    assert second_tenant.get(E + "/items/%d/availability" % w.item["cement"]).status_code == 404


def test_the_item_card_and_its_drill_down(world, sign_in, db):
    w, owner = world, sign_in("owner")
    grn = move(db, w, MovementType.GRN_IN, 1000, 8, doc=("GRN", 7), day=TODAY - timedelta(days=2))
    issue = move(db, w, MovementType.ISSUE_OUT, 600, doc=("ISSUE", 8), project_id=w.project_id, cost_head="SAFETY",
                 user_id=w.staff["central_keeper"], day=TODAY - timedelta(days=1))
    reverse_document(db, ref_doc_type="ISSUE", ref_doc_id=8, user_id=None, reason="wrong site")
    db.commit()

    card = ok(owner.get(E + "/items/%d/card?store_id=%d" % (w.item["cement"], w.central_id)))
    assert card["opening"] == {"qty": "0.000", "value": "0.00"}
    kinds = [(r["movement_type"], r["direction"], r["label"]) for r in card["rows"]]
    assert kinds == [("OPENING_IN", "IN", "Opening stock"), ("GRN_IN", "IN", "Goods received"), ("ISSUE_OUT", "OUT", "Issued"),
                     ("ISSUE_OUT", "IN", "Reversal: Issued")]
    opening_row, grn_row, issue_row, back = card["rows"]
    assert (grn_row["running_qty"], grn_row["running_value"], grn_row["avg_rate"]) == ("6000.000", "43000.00", "7.1667")
    assert grn_row["doc_number"] == "GRN #7" and grn_row["doc_path"] == "/store/hub/inward/grn/7"
    assert (issue_row["qty_out"], issue_row["value"], issue_row["signed_value"]) == ("600.000", "4300.02", "-4300.02")
    assert issue_row["reversed_by_id"] == back["id"] and back["reversal_of_id"] == issue.id
    assert issue_row["user"] == "Central Keeper Test" and issue_row["cost_head"] == "SAFETY" and issue_row["project"].endswith("Tower A")
    assert back["remarks"] == "Reversal: wrong site"
    assert card["closing"] == {"qty": "6000.000", "value": "43000.00"} and card["balance"]["qty"] == "6000.000"
    assert card["totals"] == {"qty_in": "6600.000", "qty_out": "600.000"}

    period = ok(owner.get(E + "/items/%d/card?store_id=%d&date_from=%s" % (w.item["cement"], w.central_id, TODAY - timedelta(days=1))))
    assert period["opening"] == {"qty": "6000.000", "value": "43000.00"}            # after the receipt, before the issue
    assert [r["id"] for r in period["rows"]] == [issue.id, back["id"]]
    upto = ok(owner.get(E + "/items/%d/card?store_id=%d&date_to=%s" % (w.item["cement"], w.central_id, TODAY - timedelta(days=2))))
    assert [r["id"] for r in upto["rows"]] == [opening_row["id"], grn.id] and upto["closing"]["qty"] == "6000.000"

    pdf = owner.get(E + "/items/%d/card.pdf?store_id=%d" % (w.item["cement"], w.central_id))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_the_card_links_an_opening_to_its_document(world, sign_in):
    w, owner = world, sign_in("owner")
    doc = ok(owner.post("/api/store/masters/opening", json={"store_id": w.site_id, "opening_date": str(TODAY),
                                                             "lines": [{"item_id": w.item["sand"], "qty": "4", "rate": "1800"}]}))
    for a in ("submit", "approve", "post"):
        ok(owner.post("/api/store/masters/opening/%d/%s" % (doc["id"], a), json={}))
    row = ok(owner.get(E + "/items/%d/card?store_id=%d" % (w.item["sand"], w.site_id)))["rows"][0]
    assert (row["doc_number"], row["doc_path"]) == (doc["number"], "/store/hub/masters/opening/%d" % doc["id"])


def test_where_else_an_item_is_held(world, sign_in, db):
    w, owner = world, sign_in("owner")
    out = move(db, w, MovementType.TRANSFER_OUT, 1200, item="bricks", doc=("TRANSFER", 9))
    move(db, w, MovementType.TRANSFER_IN, 1200, out.rate, store=w.site_id, item="bricks", doc=("TRANSFER", 9))
    got = ok(owner.get(E + "/items/%d/availability" % w.item["bricks"]))
    assert [(s["store_code"], s["qty"]) for s in got["stores"]] == [("CS01", "18800.000"), ("ST01", "1200.000")]
    assert got["total"] == {"qty": "20000.000", "value": "160000.00", "avg_rate": "8.0000"}
    none = ok(owner.get(E + "/items/%d/availability" % w.item["sand"]))
    assert [(s["store_code"], s["qty"]) for s in none["stores"]] == [("CS01", "100.000"), ("ST01", "0.000")]
