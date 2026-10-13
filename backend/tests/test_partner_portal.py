"""The partner portal: a gang or a supplier signs in and sees their own
orders, bills, payments and statement - and nothing of anybody else's."""
from urllib.parse import urlparse, parse_qs

from fastapi.testclient import TestClient

import main
from test_subcontractor_bills import live_order, book, measure, raise_bill


def token_of(url):
    return parse_qs(urlparse(url).query)["invite"][0]


def invite(tenant, party_type, party_id, email):
    res = tenant.post("/api/portal-access", json={"party_type": party_type, "party_id": party_id,
                                                  "email": email, "name": "Babu"})
    assert res.status_code == 200, res.text
    return res.json()


def join(browser, url, password="Portal1234x"):
    res = browser.post("/api/portal/accept-invite", json={"token": token_of(url), "password": password})
    assert res.status_code == 200, res.text
    return browser


def gang_with_a_certified_bill(tenant):
    order = live_order(tenant, retention_percent=5)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    return order, tenant.get("/api/sub-bills/%d" % bill["id"]).json()


def test_a_gang_is_invited_sets_a_password_and_sees_its_own_work(tenant, portal):
    order, bill = gang_with_a_certified_bill(tenant)
    inv = invite(tenant, "contractor", order["contractor_id"], "Babu@SriBalaji.in")
    assert inv["user"]["email"] == "babu@sribalaji.in" and inv["user"]["invite_open"]
    greet = portal.get("/api/portal/invite", params={"token": token_of(inv["invite_url"])}).json()
    assert greet["party"].startswith("Sri Balaji")
    join(portal, inv["invite_url"])
    me = portal.get("/api/portal/me").json()
    assert me["party_type"] == "contractor" and me["party"].startswith("Sri Balaji")
    orders = portal.get("/api/portal/orders").json()["orders"]
    assert [o["number"] for o in orders] == [order["wo_number"]]
    lines = portal.get("/api/portal/orders/%d" % order["id"]).json()["lines"]
    assert lines and lines[0]["rate"] > 0
    bills = portal.get("/api/portal/bills").json()["bills"]
    assert bills[0]["number"] == bill["number"] and bills[0]["where"] == "passed for payment"
    assert bills[0]["left"] == bill["net_payable"]
    s = portal.get("/api/portal/summary").json()
    assert s["balance"] == bill["net_payable"] and s["retention_held"] == bill["retention_amount"]
    # The office pays; the gang sees it land.
    tenant.post("/api/money/entries", json={"doc_type": "sub_bill", "doc_id": bill["id"],
                                            "amount": bill["net_payable"], "mode": "NEFT", "reference": "UTR77"})
    pays = portal.get("/api/portal/payments").json()["payments"]
    assert pays[0]["amount"] == bill["net_payable"] and pays[0]["reference"] == "UTR77"
    st = portal.get("/api/portal/statement").json()
    assert st["closing"] == 0 and len(st["rows"]) >= 2
    assert portal.get("/api/portal/statement.xlsx").status_code == 200


def test_an_invite_link_works_once(tenant, portal):
    order, bill = gang_with_a_certified_bill(tenant)
    inv = invite(tenant, "contractor", order["contractor_id"], "once@gang.in")
    join(portal, inv["invite_url"])
    assert portal.post("/api/portal/accept-invite", json={"token": token_of(inv["invite_url"]),
                                                          "password": "Another123x"}).status_code == 410
    assert portal.get("/api/portal/invite", params={"token": "made-up"}).status_code == 410


def test_signing_in_and_out(tenant, portal):
    order, bill = gang_with_a_certified_bill(tenant)
    inv = invite(tenant, "contractor", order["contractor_id"], "login@gang.in")
    join(portal, inv["invite_url"])
    portal.post("/api/portal/logout")
    assert portal.get("/api/portal/me").status_code == 401
    assert portal.post("/api/portal/login", json={"email": "login@gang.in", "password": "wrong"}).status_code == 401
    assert portal.post("/api/portal/login", json={"email": "LOGIN@gang.in", "password": "Portal1234x"}).status_code == 200
    assert portal.get("/api/portal/me").status_code == 200


def test_a_portal_session_reaches_no_office_screen(tenant, portal):
    order, bill = gang_with_a_certified_bill(tenant)
    inv = invite(tenant, "contractor", order["contractor_id"], "nosy@gang.in")
    join(portal, inv["invite_url"])
    for path in ("/api/jobs", "/api/sub-bills", "/api/money/payables", "/api/ledger/parties",
                 "/api/portal-access", "/api/client/me"):
        assert portal.get(path).status_code in (401, 403), path
    assert portal.post("/api/portal-access", json={"party_type": "contractor", "party_id": order["contractor_id"],
                                                   "email": "x@y.in"}).status_code in (401, 403)


def test_one_gang_never_sees_another(tenant, portal):
    mine, my_bill = gang_with_a_certified_bill(tenant)
    theirs, their_bill = gang_with_a_certified_bill(tenant)
    assert mine["contractor_id"] != theirs["contractor_id"]
    inv = invite(tenant, "contractor", mine["contractor_id"], "mine@gang.in")
    join(portal, inv["invite_url"])
    assert [b["number"] for b in portal.get("/api/portal/bills").json()["bills"]] == [my_bill["number"]]
    assert portal.get("/api/portal/orders/%d" % theirs["id"]).status_code == 404


def test_another_company_cannot_invite_to_ours(tenant, second_tenant):
    order, bill = gang_with_a_certified_bill(tenant)
    res = second_tenant.post("/api/portal-access", json={"party_type": "contractor",
                                                         "party_id": order["contractor_id"], "email": "a@b.in"})
    assert res.status_code == 404
    assert second_tenant.get("/api/portal-access").json()["users"] == []


def test_switching_a_login_off_ends_it(tenant, portal):
    order, bill = gang_with_a_certified_bill(tenant)
    inv = invite(tenant, "contractor", order["contractor_id"], "off@gang.in")
    join(portal, inv["invite_url"])
    tenant.post("/api/portal-access/%d/disable" % inv["user"]["id"])
    assert portal.get("/api/portal/me").status_code == 401
    assert portal.post("/api/portal/login", json={"email": "off@gang.in", "password": "Portal1234x"}).status_code == 403
    tenant.post("/api/portal-access/%d/enable" % inv["user"]["id"])
    assert portal.post("/api/portal/login", json={"email": "off@gang.in", "password": "Portal1234x"}).status_code == 200


def test_a_new_link_replaces_the_old(tenant, portal):
    order, bill = gang_with_a_certified_bill(tenant)
    inv = invite(tenant, "contractor", order["contractor_id"], "again@gang.in")
    again = tenant.post("/api/portal-access/%d/reinvite" % inv["user"]["id"]).json()
    assert portal.get("/api/portal/invite", params={"token": token_of(inv["invite_url"])}).status_code == 410
    join(portal, again["invite_url"])


def test_one_email_one_login(tenant):
    order, bill = gang_with_a_certified_bill(tenant)
    invite(tenant, "contractor", order["contractor_id"], "dup@gang.in")
    assert tenant.post("/api/portal-access", json={"party_type": "contractor", "party_id": order["contractor_id"],
                                                   "email": "DUP@gang.in"}).status_code == 409
    assert tenant.post("/api/portal-access", json={"party_type": "contractor", "party_id": order["contractor_id"],
                                                   "email": "not an email"}).status_code == 400


def supplier_setup(tenant):
    s = tenant.post("/api/suppliers", json={"name": "ACC Ltd", "gstin": "36AAACA1234C1Z5",
                                            "payment_days": 45}).json()
    s = s.get("supplier") or s
    job = tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()
    po = tenant.post("/api/purchase-orders", json={
        "supplier_name": "ACC Ltd", "job_id": job["id"], "amount": 30000,
        "line_items": [{"description": "OPC 53 cement", "qty": 100, "price": 300}]}).json()
    res = tenant.put("/api/purchase-orders/%d" % po["id"], json={
        "supplier_name": "ACC Ltd", "job_id": job["id"], "status": "Approved",
        "line_items": [{"description": "OPC 53 cement", "qty": 100, "price": 300}]})
    assert res.status_code == 200 and res.json()["status"] == "Approved", res.text
    tenant.post("/api/purchase-orders", json={"supplier_name": "UltraTech", "amount": 5000,
                                              "line_items": [{"description": "Cement", "qty": 1, "price": 5000}]})
    return s, po


def test_a_supplier_sees_its_orders_and_sends_an_invoice(tenant, portal):
    s, po = supplier_setup(tenant)
    inv = invite(tenant, "supplier", s["id"], "accounts@acc.in")
    join(portal, inv["invite_url"])
    orders = portal.get("/api/portal/orders").json()["orders"]
    assert [o["number"] for o in orders] == [po["number"]]
    res = portal.post("/api/portal/invoices", data={"number": "ACC/991", "issue_date": "2026-09-20",
                                                     "amount": "30000", "tax_amount": "8400",
                                                     "po_number": po["number"]},
                      files={"file": ("acc-991.pdf", b"%PDF-1.4 invoice", "application/pdf")})
    assert res.status_code == 200, res.text
    # It is in Supplier Bills as a draft with the invoice attached, nothing payable yet.
    bill = [b for b in tenant.get("/api/bills").json() if (b.get("number") == "ACC/991")] \
        if isinstance(tenant.get("/api/bills").json(), list) else \
        [b for b in tenant.get("/api/bills").json().get("bills", []) if b.get("number") == "ACC/991"]
    assert bill and bill[0]["status"] == "Draft"
    files = tenant.get("/api/files", params={"attached_type": "bill", "attached_id": bill[0]["id"]}).json()["files"]
    assert files and files[0]["name"] == "acc-991.pdf"
    assert any(a["kind"] == "portal_invoice" for a in tenant.get("/api/alerts").json()["alerts"])
    mine = portal.get("/api/portal/bills").json()["bills"]
    assert mine[0]["where"] == "received - being checked" and mine[0]["left"] == 0
    # The same invoice twice is refused; so is somebody else's order number.
    again = portal.post("/api/portal/invoices", data={"number": "acc/991", "amount": "1"},
                        files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    assert again.status_code == 409


def test_a_supplier_invoice_must_be_a_pdf_or_photo_on_its_own_order(tenant, portal):
    s, po = supplier_setup(tenant)
    other = tenant.get("/api/purchase-orders").json()
    other = [p for p in (other if isinstance(other, list) else other.get("orders", other.get("purchase_orders", [])))
             if p.get("supplier_name") == "UltraTech"][0]
    inv = invite(tenant, "supplier", s["id"], "ap@acc.in")
    join(portal, inv["invite_url"])
    exe = portal.post("/api/portal/invoices", data={"number": "X1", "amount": "100"},
                      files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert exe.status_code == 400
    theirs = portal.post("/api/portal/invoices", data={"number": "X2", "amount": "100", "po_number": other["number"]},
                         files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert theirs.status_code == 404


def test_a_gang_cannot_send_invoices_in(tenant, portal):
    order, bill = gang_with_a_certified_bill(tenant)
    inv = invite(tenant, "contractor", order["contractor_id"], "claims@gang.in")
    join(portal, inv["invite_url"])
    res = portal.post("/api/portal/invoices", data={"number": "G1", "amount": "100"},
                      files={"file": ("g.pdf", b"%PDF", "application/pdf")})
    assert res.status_code == 403


def test_an_office_sign_in_ends_a_portal_session_in_the_same_browser(tenant, portal, account):
    order, bill = gang_with_a_certified_bill(tenant)
    inv = invite(tenant, "contractor", order["contractor_id"], "shared@gang.in")
    join(portal, inv["invite_url"])
    portal.post("/api/client/login", json={"email": account["email"], "password": account["password"]})
    assert portal.get("/api/portal/me").status_code == 401


def test_a_gang_sees_its_released_retention_as_passed_for_payment(tenant, portal):
    order, bill = gang_with_a_certified_bill(tenant)
    rel = tenant.post("/api/retention/releases", json={"side": "contractor", "order_id": order["id"],
                                                       "amount": bill["retention_amount"],
                                                       "stage": "Practical completion"}).json()["release"]
    inv = invite(tenant, "contractor", order["contractor_id"], "ret@gang.in")
    join(portal, inv["invite_url"])
    rows = [b for b in portal.get("/api/portal/bills").json()["bills"] if b["number"] == rel["number"]]
    assert rows and rows[0]["left"] == rel["net_amount"]
    assert portal.get("/api/portal/summary").json()["retention_held"] == 0
