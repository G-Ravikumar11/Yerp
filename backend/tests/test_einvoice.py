"""The RA bill in the e-invoice schema - and never a file the portal would
reject: whatever is missing is named instead."""
from test_measurement_and_ra_bills import placed_order, book, measure


def ready_bill(tenant, site_state="36", buyer_gstin="36AAACL1234H1Z5", our_pin=True):
    tenant.put("/api/gst/settings", json={"gstin": "36AABCY1234H1ZX"})
    if our_pin:
        tenant.post("/api/settings", json={"company_name": "Yalavarti Projects",
                                           "company_address": "Plot 12, Madhapur, Hyderabad 500081"})
    contact = tenant.post("/api/contacts", json={
        "name": "L&T", "gstin": buyer_gstin, "address": "Mount Poonamallee Road, Manapakkam",
        "city": "Chennai", "state": "Tamil Nadu", "pincode": "600089"}).json()
    wo = placed_order(tenant, qty=1000, rate=100)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    job = tenant.get("/api/jobs/%d" % job_id).json()
    job["contact_id"] = contact.get("id")
    tenant.put("/api/jobs/%d" % job_id, json=job)
    if site_state:
        tenant.put("/api/jobs/%d/place-of-supply" % job_id, json={"state_code": site_state})
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 250)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    return tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]


def test_a_complete_bill_is_ready(tenant):
    b = ready_bill(tenant)
    chk = tenant.get("/api/ra-bills/%d/einvoice" % b["id"]).json()
    assert chk["ready"] is True, chk["missing"]
    p = chk["payload"]
    assert p["Version"] == "1.1" and p["TranDtls"]["SupTyp"] == "B2B"
    assert p["SellerDtls"]["Gstin"] == "36AABCY1234H1ZX" and p["SellerDtls"]["Pin"] == 500081
    assert p["BuyerDtls"]["Gstin"] == "36AAACL1234H1Z5" and p["BuyerDtls"]["Pin"] == 600089
    assert p["BuyerDtls"]["Pos"] == "36"
    assert len(p["DocDtls"]["No"]) <= 16


def test_the_values_are_the_bills_to_the_paisa(tenant):
    b = ready_bill(tenant)
    p = tenant.get("/api/ra-bills/%d/einvoice" % b["id"]).json()["payload"]
    taxable = round(b["this_bill"] - b["retention_amount"] - b["advance_recovery"] - b["other_deductions"], 2)
    v = p["ValDtls"]
    assert v["AssVal"] == taxable
    assert v["CgstVal"] == b["cgst_amount"] and v["SgstVal"] == b["sgst_amount"] and v["IgstVal"] == 0
    assert v["TotInvVal"] == round(taxable + b["tax_amount"], 2)
    item = p["ItemList"][0]
    assert item["TotAmt"] == b["this_bill"] and item["Discount"] == b["retention_amount"]
    assert item["HsnCd"] == "9954" and item["IsServc"] == "Y" and item["Unit"] == "MTR"


def test_a_site_across_the_border_is_igst_in_the_file(tenant):
    b = ready_bill(tenant, site_state="37")
    v = tenant.get("/api/ra-bills/%d/einvoice" % b["id"]).json()["payload"]["ValDtls"]
    assert v["IgstVal"] == b["igst_amount"] > 0 and v["CgstVal"] == 0


def test_whatever_is_missing_is_named(tenant):
    b = ready_bill(tenant, site_state="", buyer_gstin="", our_pin=False)
    chk = tenant.get("/api/ra-bills/%d/einvoice" % b["id"]).json()
    assert chk["ready"] is False and chk["payload"] is None
    joined = " ".join(chk["missing"])
    assert "PIN in our address" in joined
    assert "client's GSTIN" in joined
    assert "state the site is in" in joined
    res = tenant.get("/api/ra-bills/%d/einvoice.json" % b["id"])
    assert res.status_code == 409 and "still needed" in res.json()["detail"]


def test_the_file_downloads_as_the_portal_takes_it(tenant):
    b = ready_bill(tenant)
    res = tenant.get("/api/ra-bills/%d/einvoice.json" % b["id"])
    assert res.status_code == 200
    import json
    body = json.loads(res.content)
    assert isinstance(body, list) and body[0]["DocDtls"]["Typ"] == "INV"
    assert "attachment" in res.headers["content-disposition"]


def test_a_draft_is_not_invoiced(tenant):
    tenant.put("/api/gst/settings", json={"gstin": "36AABCY1234H1ZX"})
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 10)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    chk = tenant.get("/api/ra-bills/%d/einvoice" % b["id"]).json()
    assert chk["ready"] is False and "certified" in " ".join(chk["missing"])


def test_the_address_typed_in_settings_reaches_the_documents(tenant):
    """Settings > Company details used to stop at Settings; every bill read
    the company record and printed no address."""
    tenant.post("/api/settings", json={"company_address": "Plot 12, Madhapur, Hyderabad 500081"})
    b = ready_bill(tenant, our_pin=False)
    doc = tenant.get("/api/ra-bills/%d" % b["id"]).json()
    assert "500081" in str(doc)


def test_a_contact_keeps_what_the_customer_is_for_tax(tenant):
    c = tenant.post("/api/contacts", json={"name": "NCC", "gstin": "36aaacn1234h1z5",
                                           "address": "Madhapur", "pincode": "500081"}).json()
    assert c["gstin"] == "36AAACN1234H1Z5" and c["pincode"] == "500081"
    assert c["state"], "the state follows from the GSTIN when it is not given"
    listed = [x for x in tenant.get("/api/contacts").json() if x["id"] == c["id"]][0]
    assert listed["gstin"] == "36AAACN1234H1Z5"
    assert tenant.post("/api/contacts", json={"name": "X", "gstin": "12345"}).status_code == 400
    assert tenant.post("/api/contacts", json={"name": "Y", "pincode": "5000"}).status_code == 400


def test_editing_a_project_keeps_it_on_its_client(tenant):
    """The jobs screen sends the customer's name and no id; an edit used to
    unhook the project from the client record."""
    c = tenant.post("/api/contacts", json={"name": "NCC Ltd", "gstin": "36AAACN1234H1Z5"}).json()
    j = tenant.post("/api/jobs", json={"name": "Kokapet towers", "customer_name": "NCC Ltd"}).json()
    assert j["contact_id"] == c["id"]
    body = {k: v for k, v in j.items() if k != "contact_id"}
    body["description"] = "Two towers"
    after = tenant.put("/api/jobs/%d" % j["id"], json=body).json()
    assert after["contact_id"] == c["id"]
