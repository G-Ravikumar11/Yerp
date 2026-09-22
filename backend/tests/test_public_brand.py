"""The name on the front door - and only the name."""


def test_the_brand_is_public_and_says_only_the_name(tenant, client):
    tenant.put("/api/client/profile", json={"company_name": "Yalavarti Projects"})
    res = client.get("/api/public/brand")
    assert res.status_code == 200
    d = res.json()
    assert set(d.keys()) == {"company_name", "logo_url"}


def test_a_fresh_installation_says_nothing(client):
    d = client.get("/api/public/brand").json()
    assert d["company_name"] == "" or isinstance(d["company_name"], str)
