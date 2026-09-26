"""What the e-invoice portal gives back - the IRN, the acknowledgement and
the signed QR - kept against the bill, checked against it, and printed on it."""
import base64
import json
from datetime import datetime, timedelta

import database
import models
from test_einvoice import ready_bill


def b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def signed_qr(payload, **over):
    """A QR shaped as the portal signs it: a JWT whose payload's "data" is
    the registered invoice's summary."""
    data = {"SellerGstin": "36AABCY1234H1ZX", "BuyerGstin": payload["BuyerDtls"]["Gstin"],
            "DocNo": payload["DocDtls"]["No"], "DocTyp": "INV", "DocDt": payload["DocDtls"]["Dt"],
            "TotInvVal": payload["ValDtls"]["TotInvVal"], "ItemCnt": len(payload["ItemList"]),
            "MainHsnCode": "9954", "Irn": IRN, "IrnDt": "2026-09-26 11:02:00"}
    data.update(over)
    return b64({"alg": "RS256", "typ": "JWT"}) + "." + b64({"data": json.dumps(data), "iss": "NIC"}) + ".c2lnbmF0dXJl"


IRN = "a" * 60 + "1b2c"


def portal_response(payload, **over):
    return {"AckNo": 172610098765432, "AckDt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Irn": IRN, "SignedInvoice": "eyJ...", "SignedQRCode": signed_qr(payload, **over),
            "Status": "ACT", "EwbNo": None}


def status(tenant, bill):
    return tenant.get("/api/einvoice/ra_bill/%d" % bill["id"]).json()


def test_the_portals_response_pasted_whole_is_recorded_and_printed(tenant):
    bill = ready_bill(tenant)
    s = status(tenant, bill)
    assert s["ready"] and s["irn"] is None
    res = tenant.post("/api/einvoice/ra_bill/%d/irn" % bill["id"],
                      json={"response": json.dumps(portal_response(s["payload"]))})
    assert res.status_code == 200, res.text
    irn = res.json()["irn"]
    assert irn["irn"] == IRN and irn["ack_no"] == "172610098765432" and irn["cancellable"]
    assert irn["registered"]["doc_no"] == s["payload"]["DocDtls"]["No"]
    # On the bill as it prints, with its QR.
    printed = tenant.get("/api/ra-bills/%d" % bill["id"]).json()["bill"]["einvoice"]
    assert printed["irn"] == IRN
    qr = tenant.get(printed["qr_url"])
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")
    assert qr.text.startswith("<svg") and len(qr.text) < 120000
    # And in the GST register.
    out = tenant.get("/api/gst/outward").json()
    assert [r["irn"] for r in out["supplies"] if r["number"] == bill["number"]] == [IRN]
    assert out["summary"]["without_irn"] == 0


def test_the_fields_can_be_typed_in(tenant):
    bill = ready_bill(tenant)
    p = status(tenant, bill)["payload"]
    res = tenant.post("/api/einvoice/ra_bill/%d/irn" % bill["id"], json={
        "irn": IRN.upper(), "ack_no": "172610098765432", "ack_date": "26/09/2026 11:02:00",
        "signed_qr": signed_qr(p)})
    assert res.status_code == 200, res.text
    assert res.json()["irn"]["irn"] == IRN and res.json()["irn"]["ack_date"] == "2026-09-26 11:02:00"


def test_a_qr_from_another_bill_is_refused_with_what_differs(tenant):
    bill = ready_bill(tenant)
    p = status(tenant, bill)["payload"]
    for over, words in (({"DocNo": "RA-99"}, "RA-99"), ({"TotInvVal": 1.0}, "is for"),
                        ({"SellerGstin": "29AAAAA0000A1Z5"}, "29AAAAA0000A1Z5"),
                        ({"Irn": "f" * 64}, "different IRN")):
        res = tenant.post("/api/einvoice/ra_bill/%d/irn" % bill["id"],
                          json={"response": portal_response(p, **over)})
        assert res.status_code == 409 and words in res.json()["detail"], (over, res.text)


def test_nonsense_is_refused_plainly(tenant):
    bill = ready_bill(tenant)
    p = status(tenant, bill)["payload"]
    url = "/api/einvoice/ra_bill/%d/irn" % bill["id"]
    assert tenant.post(url, json={"response": "not json"}).status_code == 400
    assert tenant.post(url, json={"irn": "short", "ack_no": "1", "ack_date": "x", "signed_qr": "y"}).status_code == 400
    bad_qr = dict(portal_response(p), SignedQRCode="nodots")
    assert "could not be read" in tenant.post(url, json={"response": bad_qr}).json()["detail"]


def test_one_live_irn_per_bill_and_per_irn(tenant):
    bill = ready_bill(tenant)
    p = status(tenant, bill)["payload"]
    url = "/api/einvoice/ra_bill/%d/irn" % bill["id"]
    assert tenant.post(url, json={"response": portal_response(p)}).status_code == 200
    assert tenant.post(url, json={"response": portal_response(p)}).status_code == 409


def test_a_registered_bill_is_not_cancelled_until_its_irn_is(tenant):
    bill = ready_bill(tenant)
    p = status(tenant, bill)["payload"]
    irn = tenant.post("/api/einvoice/ra_bill/%d/irn" % bill["id"],
                      json={"response": portal_response(p)}).json()["irn"]
    res = tenant.post("/api/ra-bills/%d/cancel" % bill["id"], json={"comments": "wrong rate"})
    assert res.status_code == 409 and "IRN" in res.json()["detail"]
    assert tenant.post("/api/einvoice/irns/%d/cancel" % irn["id"], json={}).status_code == 400
    done = tenant.post("/api/einvoice/irns/%d/cancel" % irn["id"], json={"reason": "Data entry mistake"})
    assert done.status_code == 200 and done.json()["irn"]["status"] == "CANCELLED"
    assert tenant.post("/api/ra-bills/%d/cancel" % bill["id"], json={"comments": "wrong rate"}).status_code == 200


def test_after_a_day_the_portal_will_not_cancel_and_neither_will_we(tenant):
    bill = ready_bill(tenant)
    p = status(tenant, bill)["payload"]
    irn = tenant.post("/api/einvoice/ra_bill/%d/irn" % bill["id"],
                      json={"response": portal_response(p)}).json()["irn"]
    s = database.SessionLocal()
    try:
        s.query(models.DBEinvoiceIrn).filter(models.DBEinvoiceIrn.id == irn["id"]).update(
            {"ack_date": (datetime.now() - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")})
        s.commit()
    finally:
        s.close()
    res = tenant.post("/api/einvoice/irns/%d/cancel" % irn["id"], json={"reason": "late"})
    assert res.status_code == 409 and "credit note" in res.json()["detail"]


def test_a_retention_release_is_e_invoiced_too(tenant):
    bill = ready_bill(tenant)
    # Retention on the bill; release half of it.
    pos = [p for p in tenant.get("/api/retention").json()["positions"] if p["side"] == "client"][0]
    rel = tenant.post("/api/retention/releases", json={"side": "client", "order_id": pos["order_id"],
                                                       "amount": pos["balance"] / 2,
                                                       "stage": "Practical completion"}).json()["release"]
    s = tenant.get("/api/einvoice/retention_release/%d" % rel["id"]).json()
    assert s["ready"], s["missing"]
    item = s["payload"]["ItemList"][0]
    assert item["AssAmt"] == rel["amount"] and s["payload"]["ValDtls"]["TotInvVal"] == rel["net_amount"]
    assert tenant.get("/api/einvoice/retention_release/%d/json" % rel["id"]).status_code == 200
    got = tenant.post("/api/einvoice/retention_release/%d/irn" % rel["id"],
                      json={"response": portal_response(s["payload"], Irn="b" * 64) | {"Irn": "b" * 64}})
    assert got.status_code == 200, got.text
    res = tenant.post("/api/retention/releases/%d/cancel" % rel["id"], json={"reason": "early"})
    assert res.status_code == 409


def test_another_company_sees_no_registration(tenant, second_tenant):
    bill = ready_bill(tenant)
    p = status(tenant, bill)["payload"]
    irn = tenant.post("/api/einvoice/ra_bill/%d/irn" % bill["id"],
                      json={"response": portal_response(p)}).json()["irn"]
    assert second_tenant.get(irn["qr_url"]).status_code == 404
    assert second_tenant.post("/api/einvoice/irns/%d/cancel" % irn["id"], json={"reason": "x"}).status_code == 404
    assert second_tenant.get("/api/einvoice/irns").json()["irns"] == []
