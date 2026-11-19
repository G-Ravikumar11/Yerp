"""An expense voucher is chosen taxable or non taxable; a taxable one is local or non local."""
from test_finance_ledger import money_in


def spend(tenant, **kw):
    return money_in(tenant, doc_type="expense", head="Rent", party_name="Landlord", amount=1500, mode="Cash", **kw)


def test_non_taxable_is_complete_on_its_own(tenant):
    res = spend(tenant, tax="non_taxable", supply="local")
    assert res.status_code == 200, res.text
    e = res.json()["entry"]
    assert e["tax"] == "non_taxable" and e["supply"] == ""


def test_taxable_is_local_or_non_local_from_a_state(tenant):
    local = spend(tenant, tax="taxable", supply="local", supply_state="29").json()["entry"]
    assert (local["tax"], local["supply"], local["supply_state"]) == ("taxable", "local", "")
    far = spend(tenant, tax="taxable", supply="non_local", supply_state="29").json()["entry"]
    assert (far["tax"], far["supply"], far["supply_state"]) == ("taxable", "non_local", "29")
    rows = tenant.get("/api/money/entries").json()["entries"]
    assert {(r["tax"], r["supply"], r["supply_state"]) for r in rows} == {("taxable", "local", ""), ("taxable", "non_local", "29")}


def test_non_local_needs_a_real_state(tenant):
    assert spend(tenant, tax="taxable", supply="non_local").status_code == 400
    assert spend(tenant, tax="taxable", supply="non_local", supply_state="99").status_code == 400


def test_the_heads_list_every_state(tenant):
    states = tenant.get("/api/money/heads").json()["states"]
    names = [s["label"] for s in states]
    assert len(states) == 36 and names == sorted(names)        # 28 states and 8 union territories
    assert {"Karnataka", "Telangana", "Andhra Pradesh", "Delhi", "Maharashtra", "Tamil Nadu"} <= set(names)


def test_taxable_without_a_supply_or_with_an_unknown_choice_is_refused(tenant):
    assert spend(tenant, tax="taxable").status_code == 400
    assert spend(tenant, tax="taxable", supply="abroad").status_code == 400
    assert spend(tenant, tax="maybe").status_code == 400


def test_left_blank_it_stays_blank(tenant):
    e = spend(tenant).json()["entry"]
    assert e["tax"] == "" and e["supply"] == "" and e["supply_state"] == ""


def test_a_request_keeps_the_choice_to_the_payment(tenant):
    assert tenant.put("/api/payment-requests/rules", json={"on": True, "free_below": 100, "md_above": 1000000}).status_code == 200
    asked = tenant.post("/api/payment-requests", json={"doc_type": "expense", "head": "Rent", "party_name": "Landlord", "amount": 25000, "tax": "taxable", "supply": "non_local", "supply_state": "27"})
    assert asked.status_code == 200, asked.text
    req = asked.json()["request"]
    assert (req["tax"], req["supply"], req["supply_state"]) == ("taxable", "non_local", "27")
    assert tenant.post("/api/payment-requests/%d/decide" % req["id"], json={"decision": "approve"}).status_code == 200
    assert tenant.post("/api/payment-requests/%d/pay" % req["id"], json={"mode": "Bank transfer"}).status_code == 200
    entry = [e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "expense"][0]
    assert (entry["tax"], entry["supply"], entry["supply_state"]) == ("taxable", "non_local", "27")


def test_the_tax_inside_a_taxable_amount_is_worked_out_for_the_supply(tenant):
    # Rs 11,800 paid, 18% inside it: 10,000 and 1,800. Another state's supply is IGST; a local one is half CGST and half SGST.
    far = money_in(tenant, doc_type="expense", head="Rent", party_name="Landlord", amount=11800, mode="Cash",
                   tax="taxable", supply="non_local", supply_state="29", gst_rate=18).json()["entry"]
    assert far["gst_rate"] == 18 and far["gst"] == {"base": 10000.0, "tax": 1800.0, "igst": 1800.0, "cgst": 0.0, "sgst": 0.0}
    near = money_in(tenant, doc_type="expense", head="Rent", party_name="Landlord", amount=11800, mode="Cash",
                    tax="taxable", supply="local", gst_rate=18).json()["entry"]
    assert near["gst"] == {"base": 10000.0, "tax": 1800.0, "igst": 0.0, "cgst": 900.0, "sgst": 900.0}
    # No rate, or non taxable: nothing to work out.
    assert money_in(tenant, doc_type="expense", head="Rent", party_name="L", amount=500, mode="Cash", tax="non_taxable", gst_rate=18).json()["entry"]["gst"] is None
    assert money_in(tenant, doc_type="expense", head="Rent", party_name="L", amount=500, mode="Cash", tax="taxable", supply="local").json()["entry"]["gst"] is None


def test_the_rate_is_one_of_the_gst_rates(tenant):
    res = money_in(tenant, doc_type="expense", head="Rent", party_name="L", amount=500, mode="Cash", tax="taxable", supply="local", gst_rate=17)
    assert res.status_code == 400 and "percent" in res.json()["detail"]


def test_a_request_keeps_the_rate_to_the_payment(tenant):
    assert tenant.put("/api/payment-requests/rules", json={"on": True, "free_below": 100, "md_above": 1000000}).status_code == 200
    req = tenant.post("/api/payment-requests", json={"doc_type": "expense", "head": "Rent", "party_name": "Landlord", "amount": 11800, "tax": "taxable",
                                                     "supply": "non_local", "supply_state": "27", "gst_rate": 18}).json()["request"]
    assert req["gst_rate"] == 18
    assert tenant.post("/api/payment-requests/%d/decide" % req["id"], json={"decision": "approve"}).status_code == 200
    assert tenant.post("/api/payment-requests/%d/pay" % req["id"], json={"mode": "Bank transfer"}).status_code == 200
    entry = [e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "expense"][0]
    assert entry["gst_rate"] == 18 and entry["gst"]["igst"] == 1800.0
