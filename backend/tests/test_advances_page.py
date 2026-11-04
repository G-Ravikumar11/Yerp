"""Advances: everything paid out ahead of a bill, in one place and site by site."""


def _job(tenant, name):
    j = tenant.post("/api/jobs", json={"name": name, "customer_name": "Kokapet LLP"}).json()
    return j.get("id") or j["job"]["id"]


def _on_account(tenant, party_type, party, amount, job_id=None, direction="OUT", mode="Bank transfer"):
    res = tenant.post("/api/money/entries", json={
        "doc_type": "on_account", "doc_id": None, "direction": direction, "party_type": party_type, "party_name": party,
        "amount": amount, "paid_on": "2026-11-01", "mode": mode, "reference": "", "note": "", "account_id": None,
        "job_id": job_id})
    assert res.status_code == 200, res.text


def test_a_supplier_paid_ahead_of_the_goods_is_an_advance_on_its_site(tenant):
    a, b = _job(tenant, "Kokapet"), _job(tenant, "Tellapur")
    _on_account(tenant, "supplier", "Sri Cement Traders", 50_000, job_id=a)
    got = tenant.get("/api/advances").json()
    row = next(r for r in got["on_account"] if r["party"] == "Sri Cement Traders")
    assert row["outstanding"] == 50_000 and row["party_type"] == "supplier"
    assert got["summary"]["suppliers"] == 50_000
    # Site by site: it is Kokapet's advance, not Tellapur's.
    assert any(r["party"] == "Sri Cement Traders" for r in tenant.get("/api/advances?job_id=%d" % a).json()["on_account"])
    assert not tenant.get("/api/advances?job_id=%d" % b).json()["on_account"]


def test_a_staff_advance_is_listed_until_it_comes_back(tenant):
    _on_account(tenant, "staff", "Ramesh K", 10_000)
    got = tenant.get("/api/advances").json()
    assert [r["outstanding"] for r in got["staff"]] == [10_000] and got["summary"]["staff"] == 10_000
    assert not got["on_account"]                       # staff are kept apart from suppliers and contractors
    # 4,000 taken from salary and the rest handed back in cash.
    _on_account(tenant, "staff", "Ramesh K", 4_000, direction="IN", mode="Adjustment")
    assert tenant.get("/api/advances").json()["staff"][0]["outstanding"] == 6_000
    _on_account(tenant, "staff", "Ramesh K", 6_000, direction="IN", mode="Cash")
    assert tenant.get("/api/advances").json()["staff"] == []


def test_the_staff_an_advance_can_go_to_are_listed_by_name(tenant):
    res = tenant.get("/api/advances/staff")
    assert res.status_code == 200 and isinstance(res.json()["staff"], list)


def test_another_company_sees_none_of_it(tenant, second_tenant):
    _on_account(tenant, "supplier", "Sri Cement Traders", 50_000)
    assert second_tenant.get("/api/advances").json()["on_account"] == []


def test_a_kept_screen_changes_the_moment_a_bill_is_paid(tenant):
    """Money to Pay is kept for a minute between saves: paying a bill has to take it off at once, not a minute later."""
    from test_subcontractor_bills import live_order, measure, raise_bill
    o = live_order(tenant, pay_advance=False)
    item = tenant.get("/api/sub-mb/%d" % o["id"]).json()["lines"][0]["item_id"]
    measure(tenant, o["id"], item, 1)
    bill = raise_bill(tenant, o["id"]).json()["bill"]
    assert tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).status_code == 200
    assert tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={}).status_code == 200
    rows = tenant.get("/api/money/payables").json()["bills"]
    row = next(r for r in rows if r["number"] == bill["number"])
    res = tenant.post("/api/money/entries", json={
        "doc_type": row["doc_type"], "doc_id": row["id"], "amount": row["outstanding"], "paid_on": "2026-11-01",
        "mode": "Bank transfer", "reference": "UTR1", "note": "", "account_id": None})
    assert res.status_code == 200, res.text
    assert not [r for r in tenant.get("/api/money/payables").json()["bills"] if r["number"] == bill["number"]]
