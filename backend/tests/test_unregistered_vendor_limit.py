"""A sub contractor with no GST registration may not be given an order worth more than 19,50,000."""
from test_subcontract_orders import priced, draft, fund_order, BOQ


def contractor(tenant, name, gst=""):
    body = {"company_name": name, "pan": "AAAPB1234C"}
    if gst:
        body["gst_number"] = gst
    res = tenant.post("/api/wo/contractors", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_without_gst_a_big_order_cannot_be_sent_or_approved(tenant):
    con = contractor(tenant, "No GST Works")
    order = priced(tenant, contractor_id=con["id"])           # priced at about 29.6 lakh: a draft may be any figure
    sent = tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert sent.status_code == 409
    assert "19,50,000" in sent.json()["detail"] and "No GST Works" in sent.json()["detail"]


def test_without_gst_an_order_within_the_limit_goes_through(tenant):
    con = contractor(tenant, "Small No GST Works")
    small = {"lines": [dict(BOQ["lines"][0], quantity=100)]}          # 100 x 6,800 = 6.8 lakh
    order = draft(tenant, contractor_id=con["id"])
    order = tenant.put("/api/wo/orders/%d/boq" % order["id"], json=small).json()["order"]
    fund_order(tenant, order)
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).status_code == 200


def test_with_gst_any_order_goes_through(tenant):
    con = contractor(tenant, "Registered Works", gst="36AAAPB1234C1Z5")
    order = priced(tenant, contractor_id=con["id"])
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).status_code == 200


def test_the_cap_is_met_the_moment_gst_is_added(tenant):
    con = contractor(tenant, "Later Registered Works")
    order = priced(tenant, contractor_id=con["id"])
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 409
    assert tenant.put("/api/wo/contractors/%d" % con["id"], json={
        "company_name": "Later Registered Works", "pan": "AAAPB1234C", "gst_number": "36AAAPB1234C1Z5"}).status_code == 200
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
