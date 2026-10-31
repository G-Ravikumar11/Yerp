"""A project's money: supplier bills cost what they cost before GST (the GST is input credit), and a part-billed order
keeps its unbilled balance as committed."""
from test_goods_receipt import order, project


def bill(tenant, job, po, amount, tax=0.18, **extra):
    res = tenant.post("/api/bills", json={"number": "SB-%d" % amount, "vendor_name": "Steel Co", "job_id": job["id"], "purchase_order_id": po["id"],
                                          "amount": amount, "tax_amount": round(amount * tax, 2), "total": round(amount * (1 + tax), 2),
                                          "status": "Awaiting Payment", **extra})
    assert res.status_code == 200, res.text
    return res.json()


def money_of(tenant, job):
    res = tenant.get("/api/costs/by-project/%d" % job["id"])
    assert res.status_code == 200, res.text
    return res.json()


def test_a_part_billed_order_keeps_its_unbilled_balance_committed(tenant):
    job = project(tenant)
    po = order(tenant, job=job, lines=[{"description": "Steel", "uom": "MT", "qty": 10, "price": 60000, "tax_rate": "18%"}])   # 6,00,000 before GST
    assert money_of(tenant, job)["committed"] == 600000
    bill(tenant, job, po, 200000)
    assert money_of(tenant, job)["committed"] == 400000            # the 4,00,000 not yet billed is still promised
    bill(tenant, job, po, 400000)
    assert money_of(tenant, job)["committed"] == 0


def test_a_cancelled_bill_gives_the_commitment_back(tenant):
    job = project(tenant)
    po = order(tenant, job=job, lines=[{"description": "Steel", "uom": "MT", "qty": 10, "price": 60000, "tax_rate": "18%"}])
    bill(tenant, job, po, 600000, status="Cancelled")
    assert money_of(tenant, job)["committed"] == 600000


def test_costs_by_heading_are_before_gst(tenant):
    job = project(tenant)
    po = order(tenant, job=job, lines=[{"description": "Steel", "uom": "MT", "qty": 10, "price": 60000, "tax_rate": "18%"}])
    bill(tenant, job, po, 200000, category="materials")
    m = money_of(tenant, job)
    # 2,00,000 billed (not 2,36,000 with GST) and 4,00,000 still committed.
    assert {c["key"]: c["amount"] for c in m["categories"]}["materials"] == 600000
