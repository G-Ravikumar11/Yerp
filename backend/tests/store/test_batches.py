"""Shelf life, through the API: a receipt line carries its manufacturing and expiry dates (cement given only the first expires
ninety days on), the store lists what is left of each batch oldest first with the one to issue first marked, an expired
batch is not issued, and issuing uses the oldest lots up first."""
import uuid
from datetime import date, timedelta

from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today()


def _receive(t, central, item, batch, made, **line):
    body = {"store_id": central["id"], "grn_date": TODAY.isoformat(), "supplier_name": "Shree Traders",
            "lines": [dict({"item_id": item, "qty": "100", "uom": "bag", "rate": "350", "batch_no": batch,
                            "manufacturing_date": made.isoformat() if made else ""}, **line)]}
    grn = ok(t.post("/api/store/inward/grn", json=body))
    return walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")


def _issue(t, central, w, batch, qty="20"):
    return t.post("/api/store/outward/issue/direct", json={
        "store_id": central["id"], "issue_date": TODAY.isoformat(), "project_id": w["job"], "received_by_type": "FOREMAN", "received_by_name": "Suresh",
        "lines": [{"item_id": w["item"], "qty": qty, "uom": "bag", "cost_head": "OVERHEAD", "batch_no": batch}]})


def test_batches_are_listed_oldest_first_and_an_expired_one_is_not_issued(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)

    old = _receive(t, central, w["item"], "B-OLD", TODAY - timedelta(days=100))        # cement: expired ten days ago
    assert old["lines"][0]["expiry_date"] == (TODAY - timedelta(days=10)).isoformat() and old["lines"][0]["shelf_state"] == "EXPIRED"
    _receive(t, central, w["item"], "B-MID", TODAY - timedelta(days=80))               # expires in ten days
    _receive(t, central, w["item"], "B-NEW", TODAY - timedelta(days=5))

    lots = ok(t.get("/api/store/outward/batches", params={"store_id": central["id"], "item_id": w["item"]}))["batches"]
    assert [(b["batch_no"], b["qty"], b["state"], b["recommended"]) for b in lots] == [
        ("B-OLD", "5000.000", "EXPIRED", False), ("B-MID", "5000.000", "NEAR", True), ("B-NEW", "5000.000", "OK", False)]

    res = _issue(t, central, w, "B-OLD")
    assert res.status_code == 409 and "expired" in res.json()["detail"]
    assert _issue(t, central, w, "B-NONE").status_code == 409
    # A batch gives only what it holds: 120 bags is 6000 kg, and B-MID has 5000.
    res = _issue(t, central, w, "B-MID", qty="120")
    assert res.status_code == 409 and "only 5000" in res.json()["detail"].lower()
    issued = ok(_issue(t, central, w, "B-MID", qty="80"))                              # 4000 kg, all of it from B-MID
    assert issued["lines"][0]["batch_no"] == "B-MID"
    lots = ok(t.get("/api/store/outward/batches", params={"store_id": central["id"], "item_id": w["item"]}))["batches"]
    assert [(b["batch_no"], b["qty"]) for b in lots] == [("B-OLD", "5000.000"), ("B-MID", "1000.000"), ("B-NEW", "5000.000")]

    # With no batch named, the earliest expiry that has not expired goes first; the expired lot is left for writing off.
    issued = ok(_issue(t, central, w, "", qty="40"))                                   # 2000 kg: B-MID's 1000, then 1000 of B-NEW
    assert issued["lines"][0]["batch_no"] == "B-MID, B-NEW"
    lots = ok(t.get("/api/store/outward/batches", params={"store_id": central["id"], "item_id": w["item"]}))["batches"]
    assert [(b["batch_no"], b["qty"], b["recommended"]) for b in lots] == [("B-OLD", "5000.000", False), ("B-NEW", "4000.000", True)]
    # What has not expired is all that can go out unnamed.
    res = _issue(t, central, w, "", qty="100")                                         # 5000 kg, but only 4000 kg is fit
    assert res.status_code == 409 and "has not expired" in res.json()["detail"]


def test_receipt_dates_are_checked(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    body = {"store_id": central["id"], "grn_date": TODAY.isoformat(), "supplier_name": "Shree Traders",
            "lines": [{"item_id": w["item"], "qty": "10", "uom": "bag", "rate": "350", "manufacturing_date": TODAY.isoformat(),
                       "expiry_date": (TODAY - timedelta(days=1)).isoformat()}]}
    res = t.post("/api/store/inward/grn", json=body)
    assert res.status_code == 400 and "before the manufacturing date" in res.json()["detail"]
    # A date given by hand is kept, not replaced by the cement rule.
    body["lines"][0]["expiry_date"] = (TODAY + timedelta(days=30)).isoformat()
    assert ok(t.post("/api/store/inward/grn", json=body))["lines"][0]["expiry_date"] == (TODAY + timedelta(days=30)).isoformat()
