"""What the stores hand the books: material moved between two projects goes to Tally as a journal between their cost
centres, and goods sent back to a supplier are raised as a debit note off the bill."""
import uuid
import xml.etree.ElementTree as ET
from datetime import date

from app import db as database, models
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()


def test_an_adjusted_cross_charge_is_a_journal_between_cost_centres(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    _hub(t, w, tag)
    with database.SessionLocal() as s:
        other = models.DBJob(client_id=w["client_id"], number="Q-" + tag, name="Tower B")
        s.add(other)
        s.commit()
        other_id = other.id
    a = ok(t.post("/api/store/masters/stores", json={"code": "SA" + tag[:3].upper(), "name": "Site A", "type": "SITE", "project_id": w["job"]}))
    b = ok(t.post("/api/store/masters/stores", json={"code": "SB" + tag[:3].upper(), "name": "Site B", "type": "SITE", "project_id": other_id}))
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": a["id"], "grn_date": TODAY, "po_id": po_id, "project_id": w["job"], "lines": [{"po_line_id": po_line, "qty": "40", "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    doc = ok(t.post("/api/store/control/transfer", json={"store_id": a["id"], "to_store_id": b["id"], "transfer_date": TODAY, "lines": [{"item_id": w["item"], "qty": "10", "uom": "bag"}]}))
    walk(t, "control", "transfer", doc["id"], "submit", "approve", "post")
    ok(t.post("/api/store/control/transfer/%d/receive" % doc["id"]))
    [c] = ok(t.get("/api/store/accounts/cross-charges"))["items"]

    def journal():
        root = ET.fromstring(t.get("/api/tally/vouchers.xml").content)
        return next((v for v in root.iter("VOUCHER") if (v.findtext("VOUCHERNUMBER") or "").startswith("XC-")), None)
    assert journal() is None                                          # not until accounts adjust it
    assert any(x["what"] == "Material moved between sites" for x in ok(t.get("/api/tally/summary"))["left_out"])
    ok(t.post("/api/store/accounts/cross-charges/%d/adjust" % c["id"], json={"note": "JV"}))
    v = journal()
    assert v is not None and v.findtext("VOUCHERTYPENAME") == "Journal"
    amounts = sorted(float(e.findtext("AMOUNT")) for e in v.findall("ALLLEDGERENTRIES.LIST"))
    assert amounts == [-3500.0, 3500.0]
    centres = [x.findtext("NAME") for x in v.iter("COSTCENTREALLOCATIONS.LIST")]
    assert any("Tower B" in n for n in centres) and any("Tower A" in n for n in centres)


def test_goods_sent_back_are_raised_as_a_debit_note_off_the_supplier_s_bill(account):
    from store.test_f16_accounts import _bill, _receive
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    grn = _receive(t, central, w, 100)                                   # 100 bags at 350
    _bill(w, 35000)
    lines = ok(t.get("/api/store/inward/grn/%d" % grn["id"]))["lines"]
    ret = ok(t.post("/api/store/inward/returns", json={"grn_id": grn["id"], "return_date": TODAY, "reason": "Set hard",
                                                        "lines": [{"grn_line_id": lines[0]["id"], "qty": "10", "uom": "bag"}]}))
    walk(t, "inward", "returns", ret["id"], "submit", "approve", "post")
    got = ok(t.get("/api/supplier-debit-notes"))
    [r] = [x for x in got["returns"] if x["id"] == ret["id"]]
    assert r["taxable"] == 3500 and len(r["bills"]) == 1
    n = ok(t.post("/api/supplier-debit-notes", json={"purchase_return_id": r["id"], "bill_id": r["bills"][0]["id"], "reason": "Goods returned",
                                                     "taxable": r["taxable"], "tax": r["tax"]}))
    assert n["purchase_return_id"] == ret["id"] and n["job_id"] == w["job"]
    assert not [x for x in ok(t.get("/api/supplier-debit-notes"))["returns"] if x["id"] == ret["id"]]
    again = t.post("/api/supplier-debit-notes", json={"purchase_return_id": r["id"], "reason": "Twice", "taxable": 1})
    assert again.status_code == 409
    bill = next(b for b in ok(t.get("/api/money/payables"))["bills"] if b["id"] == r["bills"][0]["id"])
    assert bill["outstanding"] == 35000 - n["total"]
