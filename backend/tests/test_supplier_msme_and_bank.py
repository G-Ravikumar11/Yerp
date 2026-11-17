"""MSME status and bank details asked of the supplier, not typed by hand: on the enquiry reply link and on the partner
portal. The MSME badge shows on purchase orders and on the comparison sheet. Bank details on file are never changed
from the portal."""
from test_comparative_statement import rfq
from test_partner_portal import invite as portal_invite, join, supplier_setup
from test_rfq_vendor_quotes import invite, send, token_of


def rates(r, cem=380, stl=61000):
    return [{"rfq_line_id": r["lines"][0]["rfq_line_id"], "rate": cem, "tax_percent": 28},
            {"rfq_line_id": r["lines"][1]["rfq_line_id"], "rate": stl, "tax_percent": 18}]


def supplier(tenant, name):
    return next(s for s in tenant.get("/api/suppliers").json()["suppliers"] if s["name"] == name)


# --- the enquiry reply link -----------------------------------------------------------------------------------------

def test_a_supplier_says_he_is_msme_on_his_reply_and_the_comparison_shows_it(tenant, client):
    tenant.post("/api/suppliers", json={"name": "Sri Ram Traders"})
    r = rfq(tenant)
    inv = invite(tenant, r, "Sri Ram Traders")
    page = client.get("/api/vendor-quote/%s" % token_of(inv)).json()
    assert page["msme"] == {"type": "", "udyam_no": ""}, "not answered yet"

    bad = send(client, token_of(inv), rates(r), msme_type="small", udyam_no="")
    assert bad.status_code == 400 and "Udyam" in bad.json()["detail"]
    assert send(client, token_of(inv), rates(r), msme_type="maybe").status_code == 400
    ok = send(client, token_of(inv), rates(r), msme_type="small", udyam_no="udyam-ts-02-0012345")
    assert ok.status_code == 200, ok.text

    # The master was blank, so it takes his answer; the comparison shows the badge.
    s = supplier(tenant, "Sri Ram Traders")
    assert (s["msme_type"], s["udyam_no"]) == ("small", "UDYAM-TS-02-0012345")
    st = tenant.get("/api/rfqs/%d/statement" % r["rfq"]["id"]).json()
    assert st["suppliers"][0]["msme"] == {"type": "small", "udyam": "UDYAM-TS-02-0012345", "source": "master"}
    assert client.get("/api/vendor-quote/%s" % token_of(inv)).json()["msme"]["type"] == "small"


def test_a_reply_never_overwrites_what_the_office_holds(tenant, client):
    tenant.post("/api/suppliers", json={"name": "Balaji Steels", "msme_type": "micro", "udyam_no": "UDYAM-TS-01-0000001"})
    r = rfq(tenant)
    inv = invite(tenant, r, "Balaji Steels")
    assert client.get("/api/vendor-quote/%s" % token_of(inv)).json()["msme"]["type"] == "micro", "starts from the master"
    assert send(client, token_of(inv), rates(r), msme_type="medium", udyam_no="UDYAM-TS-01-0000002").status_code == 200
    s = supplier(tenant, "Balaji Steels")
    assert (s["msme_type"], s["udyam_no"]) == ("micro", "UDYAM-TS-01-0000001")


def test_a_supplier_not_in_the_master_still_shows_msme_on_the_comparison(tenant, client):
    r = rfq(tenant)
    inv = invite(tenant, r, "New Cement Co")
    assert send(client, token_of(inv), rates(r), msme_type="micro", udyam_no="UDYAM-AP-05-0099999").status_code == 200
    none = invite(tenant, r, "Big Steel Ltd")
    assert send(client, token_of(none), rates(r, 390, 60000), msme_type="none").status_code == 200
    st = tenant.get("/api/rfqs/%d/statement" % r["rfq"]["id"]).json()
    by = {s["supplier_name"]: s["msme"] for s in st["suppliers"]}
    assert by["New Cement Co"] == {"type": "micro", "udyam": "UDYAM-AP-05-0099999", "source": "declared"}
    assert by["Big Steel Ltd"] is None


# --- purchase orders ------------------------------------------------------------------------------------------------

def test_purchase_orders_carry_the_suppliers_msme_badge(tenant):
    tenant.post("/api/suppliers", json={"name": "ACC Ltd", "msme_type": "small", "udyam_no": "UDYAM-TS-02-0012345"})
    tenant.post("/api/purchase-orders", json={"supplier_name": "acc ltd.", "amount": 100,
                                              "line_items": [{"description": "Cement", "qty": 1, "price": 100}]})
    tenant.post("/api/purchase-orders", json={"supplier_name": "UltraTech", "amount": 100,
                                              "line_items": [{"description": "Cement", "qty": 1, "price": 100}]})
    by = {o["supplier_name"]: o["msme"] for o in tenant.get("/api/purchase-orders").json()["orders"]}
    assert by["acc ltd."] == {"type": "small", "udyam": "UDYAM-TS-02-0012345"}
    assert by["UltraTech"] is None


# --- the partner portal ---------------------------------------------------------------------------------------------

def test_a_supplier_gives_msme_and_bank_details_on_the_portal(tenant, portal):
    s, _ = supplier_setup(tenant)
    join(portal, portal_invite(tenant, "supplier", s["id"], "msme.ap@acc.in")["invite_url"])
    d = portal.get("/api/portal/details").json()
    assert d["msme_type"] == "" and d["bank"]["on_file"] is False

    assert portal.put("/api/portal/details", json={"msme_type": "micro", "udyam_no": "bad"}).status_code == 400
    assert portal.put("/api/portal/details", json={"bank_account": "12ab", "bank_ifsc": "HDFC0001234"}).status_code == 400
    assert portal.put("/api/portal/details", json={"bank_account": "50100012345678", "bank_ifsc": "HDFC123"}).status_code == 400
    res = portal.put("/api/portal/details", json={"msme_type": "micro", "udyam_no": "UDYAM-TS-02-0012345",
                                                  "bank_name": "HDFC Bank", "bank_account": "5010 0012 345678",
                                                  "bank_ifsc": "hdfc0001234"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["bank"] == {"on_file": True, "bank_name": "HDFC Bank", "ifsc": "HDFC0001234", "account_ending": "5678"}
    assert "50100012345678" not in res.text, "the whole number is never shown back"
    m = supplier(tenant, "ACC Ltd")
    assert (m["msme_type"], m["bank_account"], m["bank_ifsc"]) == ("micro", "50100012345678", "HDFC0001234")
    alerts = tenant.get("/api/alerts").json()
    assert any("ACC Ltd gave their details" in (a.get("title") or "") for a in (alerts.get("alerts") or alerts))


def test_bank_details_on_file_are_not_changed_from_the_portal(tenant, portal):
    s, _ = supplier_setup(tenant)
    tenant.put("/api/suppliers/%d" % s["id"], json={"name": "ACC Ltd", "bank_account": "111122223333", "bank_ifsc": "SBIN0000001"})
    join(portal, portal_invite(tenant, "supplier", s["id"], "msme.bank@acc.in")["invite_url"])
    res = portal.put("/api/portal/details", json={"bank_account": "999988887777", "bank_ifsc": "ICIC0000001"})
    assert res.status_code == 409 and "3333" in res.json()["detail"]
    assert supplier(tenant, "ACC Ltd")["bank_account"] == "111122223333"
    # The same account again is not a change.
    assert portal.put("/api/portal/details", json={"bank_account": "111122223333", "bank_ifsc": "SBIN0000001"}).status_code == 200
    # Saying "not registered" clears what they said before.
    portal.put("/api/portal/details", json={"msme_type": "small", "udyam_no": "UDYAM-TS-02-0012345"})
    portal.put("/api/portal/details", json={"msme_type": "none"})
    assert supplier(tenant, "ACC Ltd")["msme_type"] == ""
