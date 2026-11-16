"""A cross-charge that is adjusted and then reversed goes to Tally twice: its journal, and an exact opposite one dated the day it was reversed.

Before, an adjustment whose transfer was cancelled became REVERSE and then - once accounts put it back - VOID with its adjustment date wiped, so
Tally kept the original journal and never heard of the reversal. The reversal now keeps everything the adjustment had, notes when it happened
(reversed_on) and is exported as its own voucher, with its own identity, so an export made again gives Tally the same two vouchers."""
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from app import db as database, models
from app.models.store_extras import DBStoreCrossCharge
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()
BASE = "/api/store/accounts/cross-charges"


def transfer(account, qty="10"):
    """Two projects, a transfer of `qty` bags (350 each, kg-based so 3,500 for 10) from one site's store to the other's, received. Returns the
    pieces a test needs."""
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag, orders=2)
    _hub(t, w, tag)
    with database.SessionLocal() as s:
        other = models.DBJob(client_id=w["client_id"], number="Q-" + tag, name="Tower B")
        s.add(other)
        s.commit()
        other_id = other.id
    a = ok(t.post("/api/store/masters/stores", json={"code": "SA" + tag[:3].upper(), "name": "Site A", "type": "SITE", "project_id": w["job"]}))
    b = ok(t.post("/api/store/masters/stores", json={"code": "SB" + tag[:3].upper(), "name": "Site B", "type": "SITE", "project_id": other_id}))
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": a["id"], "grn_date": TODAY, "po_id": po_id, "project_id": w["job"], "lines": [{"po_line_id": po_line, "qty": "80", "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    w.update(a=a, b=b)
    return t, w, tag


def send(t, w, qty="10"):
    doc = ok(t.post("/api/store/control/transfer", json={"store_id": w["a"]["id"], "to_store_id": w["b"]["id"], "transfer_date": TODAY, "lines": [{"item_id": w["item"], "qty": qty, "uom": "bag"}]}))
    walk(t, "control", "transfer", doc["id"], "submit", "approve", "post")
    ok(t.post("/api/store/control/transfer/%d/receive" % doc["id"]))
    return doc


def charges(t):
    return {c["id"]: c for c in ok(t.get(BASE))["items"]}


def adjusted(t, w, qty="10"):
    doc = send(t, w, qty)
    [c] = [c for c in charges(t).values() if c["transfer_number"] == doc["number"]]
    ok(t.post("%s/%d/adjust" % (BASE, c["id"]), json={"note": "JV"}))
    return doc, c["id"]


def reverse(t, doc):
    ok(t.post("/api/store/control/transfer/%d/cancel" % doc["id"], json={"reason": "Sent in error"}))


def vouchers(t, **params):
    root = ET.fromstring(t.get("/api/tally/vouchers.xml", params=params).content)
    out = {}
    for v in root.iter("VOUCHER"):
        number = v.findtext("VOUCHERNUMBER") or ""
        if number.startswith(("XC-", "XCR-")):
            out.setdefault(number, []).append({"date": v.findtext("DATE"), "guid": v.findtext("GUID"), "type": v.findtext("VOUCHERTYPENAME"), "narration": v.findtext("NARRATION") or "",
                                               "by_centre": {e.find("CATEGORYALLOCATIONS.LIST/COSTCENTREALLOCATIONS.LIST/NAME").text: float(e.findtext("AMOUNT")) for e in v.findall("ALLLEDGERENTRIES.LIST")}})
    return out


def row(cid):
    with database.SessionLocal() as s:
        return s.get(DBStoreCrossCharge, cid)


def set_dates(cid, adjusted_on=None, reversed_on="keep"):
    with database.SessionLocal() as s:
        r = s.get(DBStoreCrossCharge, cid)
        if adjusted_on is not None:
            r.adjusted_on = adjusted_on
        if reversed_on != "keep":
            r.reversed_on = reversed_on
        s.commit()


def num(d):
    return d.strftime("%Y%m%d")


# --- the reversal is recorded -----------------------------------------------------------------------------------------------

def test_reversing_an_adjustment_notes_when_and_keeps_everything_the_adjustment_had(account):
    t, w, _tag = transfer(account)
    doc, cid = adjusted(t, w)
    assert row(cid).reversed_on is None and charges(t)[cid]["reversed"] is False
    before = charges(t)[cid]
    reverse(t, doc)
    got = charges(t)[cid]
    assert got["status"] == "REVERSE" and got["reversed"] is True
    r = row(cid)
    assert r.reversed_on is not None and abs((datetime.now() - r.reversed_on).total_seconds()) < 120          # when the transfer was cancelled
    assert (r.adjusted_on, r.amount, r.from_project_id, r.to_project_id) == (date.today(), before and r.amount, r.from_project_id, r.to_project_id)
    assert got["adjusted_on"] == TODAY and got["amount"] == before["amount"] == "3500.00" and got["transfer_number"] == doc["number"]
    assert (got["txn_date"], got["original_reference"], got["reversal_reference"], got["original_amount"], got["reversed_amount"]) == (
        TODAY, "XC-" + doc["number"], "XCR-" + doc["number"], "3500.00", "3500.00")
    # Listing again, or syncing again, changes nothing: it is reversed once.
    first = row(cid).reversed_on
    assert charges(t)[cid]["reversed_on"] == got["reversed_on"] and row(cid).reversed_on == first
    # Accounts put it back: it is history now, and the adjustment date is no longer wiped.
    assert ok(t.post("%s/%d/adjust" % (BASE, cid), json={}))["status"] == "VOID"
    r = row(cid)
    assert r.adjusted_on == date.today() and r.reversed_on == first and charges(t)[cid]["reversed"] is True
    assert t.post("%s/%d/adjust" % (BASE, cid), json={}).status_code == 409                                     # nothing more to do
    assert charges(t)[cid]["status"] == "VOID" and ok(t.get("/api/store/accounts/summary"))["cross_charges_open"] == 0


def test_a_charge_never_adjusted_is_not_reversed(account):
    t, w, _tag = transfer(account)
    doc = send(t, w)
    [c] = charges(t).values()
    reverse(t, doc)
    got = charges(t)[c["id"]]
    assert got["status"] == "VOID" and got["reversed"] is False and got["reversed_on"] == "" and got["reversal_reference"] == ""
    assert vouchers(t) == {}                                                                                      # nothing was ever adjusted: nothing to send or undo


# --- the journals ---------------------------------------------------------------------------------------------------------------

def test_the_adjusted_journal_goes_as_it_always_did_and_the_reversal_is_its_exact_opposite_on_its_own_date(account):
    t, w, _tag = transfer(account)
    doc, cid = adjusted(t, w)
    original = vouchers(t)["XC-" + doc["number"]][0]
    assert original["type"] == "Journal" and sorted(original["by_centre"].values()) == [-3500.0, 3500.0] and original["date"] == num(date.today())
    assert "XCR-" + doc["number"] not in vouchers(t)                                                              # not reversed yet
    reverse(t, doc)
    # Put the two dates well apart, so a reversal using the adjustment's day would show.
    adjusted_day, reversed_day = datetime.now() - timedelta(days=9), datetime.now() - timedelta(days=3)
    set_dates(cid, adjusted_on=adjusted_day.date(), reversed_on=reversed_day)
    got = vouchers(t)
    adj, rev = got["XC-" + doc["number"]][0], got["XCR-" + doc["number"]][0]
    assert adj["date"] == num(adjusted_day) and rev["date"] == num(reversed_day)                                   # each on its own day
    assert rev["type"] == "Journal" and "Reversal of XC-%s" % doc["number"] in rev["narration"] and adj["by_centre"].keys() == rev["by_centre"].keys()
    # What the original debited, the reversal credits - centre by centre, to the rupee - so the two together are nothing.
    assert {k: -v for k, v in adj["by_centre"].items()} == rev["by_centre"]
    assert {k: adj["by_centre"][k] + rev["by_centre"][k] for k in adj["by_centre"]} == {k: 0.0 for k in adj["by_centre"]}
    assert adj["guid"] != rev["guid"] and rev["guid"].endswith("-reversal") and adj["guid"] == "yerp-%d-crosscharge-%d" % (w["client_id"], cid)
    # The reversal is not another positive cross-charge: the sending project is debited, the receiving one credited.
    assert next(v for k, v in rev["by_centre"].items() if "Tower A" in k) == -3500.0 and next(v for k, v in rev["by_centre"].items() if "Tower B" in k) == 3500.0


def test_each_journal_falls_in_the_period_of_its_own_date(account):
    t, w, _tag = transfer(account)
    doc, cid = adjusted(t, w)
    reverse(t, doc)
    set_dates(cid, adjusted_on=date(2026, 3, 20), reversed_on=datetime(2026, 4, 5, 10, 30))
    march = vouchers(t, date_from="2026-03-01", date_to="2026-03-31")
    april = vouchers(t, date_from="2026-04-01", date_to="2026-04-30")
    assert list(march) == ["XC-" + doc["number"]] and list(april) == ["XCR-" + doc["number"]]
    both = vouchers(t, date_from="2026-03-01", date_to="2026-04-30")
    assert sorted(both) == ["XC-" + doc["number"], "XCR-" + doc["number"]]


def test_a_reversal_with_no_date_is_not_sent_with_a_wrong_one_and_says_so(account):
    t, w, _tag = transfer(account)
    doc, cid = adjusted(t, w)
    reverse(t, doc)
    set_dates(cid, reversed_on=None)                                                                              # reversed before the date was kept
    got = vouchers(t)
    assert list(got) == ["XC-" + doc["number"]]                                                                   # the original still goes; no reversal, and no guessed date
    summary = ok(t.get("/api/tally/summary"))
    assert any("no reversal date" in x for x in summary["warnings"]) and "XC-" + doc["number"] in " ".join(summary["warnings"])
    c = charges(t)[cid]
    assert c["export"]["reversal"] == "NEEDS_DATE" and "reversal date" in c["export"]["error"]
    # Accounts give the date: bad ones are refused, a good one is kept once, and the journal appears under it.
    url = "%s/%d/reversal-date" % (BASE, cid)
    assert t.post(url, json={"reversed_on": "soon"}).status_code == 400
    assert t.post(url, json={"reversed_on": (date.today() + timedelta(days=1)).isoformat()}).status_code == 400
    assert t.post(url, json={"reversed_on": (date.today() - timedelta(days=1)).isoformat()}).status_code == 400      # before the adjustment (today)
    assert ok(t.post(url, json={"reversed_on": TODAY}))["reversed_on"].startswith(TODAY)
    assert t.post(url, json={"reversed_on": TODAY}).status_code == 409                                              # a date that is there is not changed
    assert sorted(vouchers(t)) == ["XC-" + doc["number"], "XCR-" + doc["number"]]
    assert t.post("%s/%d/reversal-date" % (BASE, 999999), json={"reversed_on": TODAY}).status_code == 404


def test_a_reversal_dated_before_its_adjustment_is_refused_not_exported(account):
    t, w, _tag = transfer(account)
    doc, cid = adjusted(t, w)
    reverse(t, doc)
    set_dates(cid, adjusted_on=date.today(), reversed_on=datetime.now() - timedelta(days=5))
    assert list(vouchers(t)) == ["XC-" + doc["number"]]
    assert any("before it was adjusted" in x for x in ok(t.get("/api/tally/summary"))["warnings"])
    assert charges(t)[cid]["export"]["reversal"] == "INVALID_DATE"


def test_a_reversal_is_only_for_an_adjustment_that_was_reversed(account):
    t, w, _tag = transfer(account)
    doc, cid = adjusted(t, w)
    assert t.post("%s/%d/reversal-date" % (BASE, cid), json={"reversed_on": TODAY}).status_code == 409           # not reversed
    pending = send(t, w, "5")
    [p] = [c for c in charges(t).values() if c["transfer_number"] == pending["number"]]
    assert t.post("%s/%d/reversal-date" % (BASE, p["id"]), json={"reversed_on": TODAY}).status_code == 409


# --- exporting again ---------------------------------------------------------------------------------------------------------------

def test_exporting_again_sends_the_same_two_vouchers_and_the_status_follows_the_exports(account):
    t, w, _tag = transfer(account)
    doc, cid = adjusted(t, w)
    assert charges(t)[cid]["export"] == {"original": "PENDING_EXPORT", "reversal": "NONE", "error": ""}
    time.sleep(1.1)
    first = vouchers(t)                                                                                         # an export, logged
    assert charges(t)[cid]["export"]["original"] == "EXPORTED" and charges(t)[cid]["export"]["reversal"] == "NONE"
    time.sleep(1.1)
    reverse(t, doc)
    assert charges(t)[cid]["export"] == {"original": "EXPORTED", "reversal": "PENDING_EXPORT", "error": ""}       # the reversal has gone nowhere yet
    time.sleep(1.1)
    second, third = vouchers(t), vouchers(t)
    assert charges(t)[cid]["export"] == {"original": "EXPORTED", "reversal": "EXPORTED", "error": ""}
    # One voucher of each in every file, under the same identities each time: Tally recognises them, it does not double them.
    for got in (second, third):
        assert sorted(got) == ["XC-" + doc["number"], "XCR-" + doc["number"]] and all(len(v) == 1 for v in got.values())
    assert [v[0]["guid"] for k, v in sorted(second.items())] == [v[0]["guid"] for k, v in sorted(third.items())]
    assert second["XC-" + doc["number"]][0]["guid"] == first["XC-" + doc["number"]][0]["guid"]
    # Accounts putting it back later changes neither voucher.
    ok(t.post("%s/%d/adjust" % (BASE, cid), json={}))
    assert vouchers(t) == second


def test_separate_adjustments_and_reversals_are_independent(account):
    t, w, _tag = transfer(account)
    d1, c1 = adjusted(t, w, "10")
    d2, c2 = adjusted(t, w, "20")
    d3 = send(t, w, "5")                                                                                         # received, not adjusted
    reverse(t, d1)                                                                                               # only the first is reversed
    got = vouchers(t)
    assert sorted(got) == sorted(["XC-" + d1["number"], "XCR-" + d1["number"], "XC-" + d2["number"]])
    assert "XC-" + d3["number"] not in got
    assert max(abs(x) for x in got["XC-" + d1["number"]][0]["by_centre"].values()) == 3500.0
    assert max(abs(x) for x in got["XC-" + d2["number"]][0]["by_centre"].values()) == 7000.0
    reverse(t, d2)
    ok(t.post("%s/%d/adjust" % (BASE, c1), json={}))                                                             # c1 put back; c2 still waiting
    got = vouchers(t)
    assert sorted(got) == sorted(["XC-" + d1["number"], "XCR-" + d1["number"], "XC-" + d2["number"], "XCR-" + d2["number"]])
    assert charges(t)[c1]["status"] == "VOID" and charges(t)[c2]["status"] == "REVERSE"


def test_the_books_balance_after_a_reversal(account):
    """Add up what the two projects' cost centres carry in the vouchers: after the reversal each is back to nothing."""
    t, w, _tag = transfer(account)
    doc, cid = adjusted(t, w, "20")
    keep, _kept = adjusted(t, w, "10")
    reverse(t, doc)
    totals = {}
    for versions in vouchers(t).values():
        for v in versions:
            for centre, amount in v["by_centre"].items():
                totals[centre] = totals.get(centre, 0.0) + amount
    # The 20-bag move is gone; only the 10-bag one remains: 3,500 to Tower B (debit, negative in Tally) from Tower A.
    assert sorted(totals.values()) == [-3500.0, 3500.0] and keep and cid
    assert next(v for k, v in totals.items() if "Tower B" in k) == -3500.0

def test_an_adjustment_cancelled_before_reversals_were_recorded_is_still_reversed_in_the_export(account):
    """A row left at ADJUSTED whose transfer was cancelled (how it was before the cancellation recorded it): the export sees the reversal and dates it
    from when the transfer was cancelled - and writes nothing doing so."""
    t, w, _tag = transfer(account)
    doc, cid = adjusted(t, w)
    reverse(t, doc)
    with database.SessionLocal() as s:                                                                            # back to how an old row looks
        r = s.get(DBStoreCrossCharge, cid)
        r.status, r.reversed_on = "ADJUSTED", None
        s.commit()
    got = vouchers(t)
    assert sorted(got) == ["XC-" + doc["number"], "XCR-" + doc["number"]] and got["XCR-" + doc["number"]][0]["date"] == num(date.today())
    assert row(cid).status == "ADJUSTED" and row(cid).reversed_on is None                                          # the export did not write
    assert charges(t)[cid]["status"] == "REVERSE" and row(cid).reversed_on is not None                              # the list brings it up to date
