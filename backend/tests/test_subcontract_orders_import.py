"""A register of gangs and dates is read into subcontract work orders."""
def test_orders_come_in_as_drafts_matched_by_name(tenant):
    tenant.post("/api/wo/contractors", json={"company_name": "Rani Labour Contractors"})
    job = tenant.post("/api/jobs", json={"name": "Kokapet Towers", "customer_name": "X"}).json()
    rows = [{"contractor": "rani labour contractors", "project": "kokapet towers", "department": "Civil",
             "subject": "Shuttering, tower C", "commencement_date": "2026-11-01", "completion_date": "2027-03-31"},
            {"contractor": "Unknown Gang", "project": "", "department": "", "subject": "Painting", "commencement_date": "", "completion_date": ""}]
    res = tenant.post("/api/sheets/subcontract_orders/import", json={"rows": rows})
    assert res.status_code == 200, res.text
    assert res.json()["count"] == 2 and "Unknown Gang" in res.json()["message"]
    orders = tenant.get("/api/wo/orders").json()["orders"]
    a = [o for o in orders if o["subject"] == "Shuttering, tower C"][0]
    assert a["status"] == "DRAFT" and a["contractor"] == "Rani Labour Contractors" and a["job_id"] == job["id"]
    b = [o for o in orders if o["subject"] == "Painting"][0]
    assert b["contractor_id"] is None
