"""The first subcontract order used to need a "business unit" invented
before it could be raised; the picker opened empty. The company is the unit
its own orders are issued by, so it is there from the start."""


def units(tenant):
    return tenant.get("/api/wo/business-units").json()["business_units"]


def test_a_new_company_finds_itself_on_the_list(tenant):
    rows = units(tenant)
    assert [u["name"] for u in rows] == ["Acme Ltd"]


def test_it_carries_the_gstin_pan_and_address_given_later(tenant):
    units(tenant)
    tenant.put("/api/gst/settings", json={"gstin": "36AABCY1234H1ZX"})
    tenant.post("/api/settings", json={"company_address": "Plot 12, Madhapur, Hyderabad 500081"})
    u = units(tenant)[0]
    assert u["gstin"] == "36AABCY1234H1ZX" and u["pan"] == "AABCY1234H"
    assert "500081" in u["address"]


def test_it_is_made_once_and_others_can_be_added(tenant):
    units(tenant)
    units(tenant)
    tenant.post("/api/wo/business-units", json={"name": "Acme Infra JV"})
    assert sorted(u["name"] for u in units(tenant)) == ["Acme Infra JV", "Acme Ltd"]


def test_a_gstin_typed_on_the_unit_is_not_overwritten(tenant):
    tenant.post("/api/wo/business-units", json={"name": "Acme Ltd", "gstin": "29AABCY1234H1ZX"})
    tenant.put("/api/gst/settings", json={"gstin": "36AABCY1234H1ZX"})
    assert units(tenant)[0]["gstin"] == "29AABCY1234H1ZX"
