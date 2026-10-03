"""Shake the measurement book: random records, holds, releases, edits, deletes and bills, and after every
step the book must still add up and nothing may fail with a server error."""
import random

import pytest

from test_delete_work_order import book, live_order


def check_book(tenant, order, step):
    data = book(tenant, order["id"])
    entries = data["entries"]
    for line in data["lines"]:
        if line.get("is_header"):
            continue
        mine = [e for e in entries if e["item_id"] == line["item_id"]]
        gross = round(sum(e["quantity"] for e in mine if not e["kind"]), 2)
        holds = sum(-e["quantity"] for e in mine if e["kind"] == "hold")
        releases = sum(e["quantity"] for e in mine if e["kind"] == "release")
        held = round(max(0.0, holds - releases), 2)
        where = "step %s item %s" % (step, line["item_id"])
        assert abs(line["measured_to_date"] - gross) < 0.02, (where, line["measured_to_date"], gross)
        assert abs(line["held"] - held) < 0.02, (where, line["held"], held)
        assert line["held"] >= -0.001, where
        assert abs(line["unbilled"] - (gross - held - line["billed_to_date"])) < 0.03, (where, line)
    return data


@pytest.mark.parametrize("seed", list(range(1, 9)))
def test_the_book_always_adds_up(tenant, seed):
    rnd = random.Random(seed)
    order = live_order(tenant, pay_advance=False)
    items = [l["item_id"] for l in book(tenant, order["id"])["lines"] if not l.get("is_header")]
    for step in range(45):
        data = book(tenant, order["id"])
        entries = data["entries"]
        action = rnd.choice(["measure", "measure", "dims", "hold", "release", "delete", "edit", "bill", "advance", "cancel"])
        item = rnd.choice(items)
        res = None
        if action == "measure":
            res = tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": rnd.choice([3, 10, 25.5, -2]), "measured_on": "2026-11-10"})
        elif action == "dims":
            res = tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "multiplier": rnd.choice([1, 2, 3]), "location": "Block %d" % step, "dimensions": [
                {"particulars": "A", "nos": rnd.randint(1, 4), "length": 2.5, "breadth": 1.2}, {"particulars": "Hole", "nos": 1, "length": 0.5, "breadth": 0.5, "deduct": True}]})
        elif action == "hold":
            body = {"item_id": item, "reason": "test"}
            body.update(rnd.choice([{"percent": rnd.choice([5, 10, 50, 100])}, {"quantity": rnd.choice([1, 4, 40])}]))
            res = tenant.post("/api/sub-mb/%d/holds" % order["id"], json=body)
        elif action == "release":
            held = [e for e in entries if e["kind"] == "hold" and e["held_remaining"] > 0]
            if held:
                h = rnd.choice(held)
                res = tenant.post("/api/sub-mb/holds/%d/release" % h["id"], json=rnd.choice([{}, {"quantity": 1}, {"quantity": 999}]))
        elif action == "delete" and entries:
            res = tenant.delete("/api/sub-mb/entries/%d" % rnd.choice(entries)["id"])
        elif action == "edit":
            plain = [e for e in entries if not e["kind"]]
            if plain:
                res = tenant.put("/api/sub-mb/entries/%d" % rnd.choice(plain)["id"], json={"item_id": item, "quantity": rnd.choice([2, 7, 60])})
        elif action == "bill":
            res = tenant.post("/api/sub-bills", json={"order_id": order["id"]})
            if res.status_code == 200:
                bill = res.json()["bill"]
                tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
                res = tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
        elif action == "advance":
            res = None
        elif action == "cancel":
            bills = tenant.get("/api/sub-bills?order_id=%d" % order["id"]).json()["bills"]
            open_ = [b for b in bills if b["status"] in ("DRAFT", "SUBMITTED")]
            if open_:
                res = tenant.post("/api/sub-bills/%d/cancel" % open_[0]["id"], json={"comments": "walk"})
        if res is not None:
            assert res.status_code < 500, (step, action, res.status_code, res.text[:300])
        check_book(tenant, order, "%s:%s" % (step, action))
