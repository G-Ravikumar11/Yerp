"""Rate contracts: a supplier's agreed rates for chosen items, for a year; an order to them picks those rates; and
purchasing is told before a contract runs out."""
from datetime import date, datetime, timedelta

import main
from app import db as database, models


def contract(tenant, **body):
    body.setdefault("supplier_name", "ACC Cement")
    body.setdefault("items", [{"item_code": "CEM53", "rate": 390}, {"item_code": "CEM43", "rate": 360}])
    res = tenant.post("/api/rate-contracts", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_a_contract_holds_chosen_items_for_a_year(tenant):
    out = contract(tenant, valid_from="2026-04-01")
    assert out["contract_no"] == "RC-0001" and "2027-03-31" in out["message"]
    [c] = tenant.get("/api/rate-contracts/by-contract").json()["contracts"]
    assert (c["contract_no"], c["supplier_name"], c["valid_to"]) == ("RC-0001", "ACC Cement", "2027-03-31")
    assert sorted((i["item_code"], i["rate"]) for i in c["items"]) == [("CEM43", 360), ("CEM53", 390)]
    assert contract(tenant)["contract_no"] == "RC-0002"


def test_an_order_to_the_supplier_picks_the_contract_rates(tenant):
    contract(tenant)
    assert tenant.get("/api/rate-contracts/active", params={"supplier": "acc cement"}).json()["rates"] == {"CEM53": 390, "CEM43": 360}
    assert tenant.get("/api/rate-contracts/active", params={"supplier": "UltraTech"}).json()["rates"] == {}
    # An expired contract sets nothing.
    contract(tenant, supplier_name="Old Co", valid_from="2024-01-01", valid_to="2024-12-31", items=[{"item_code": "X", "rate": 1}])
    assert tenant.get("/api/rate-contracts/active", params={"supplier": "Old Co"}).json()["rates"] == {}


def test_a_contract_needs_its_supplier_and_rates(tenant):
    assert tenant.post("/api/rate-contracts", json={"supplier_name": "ACC", "items": []}).status_code == 400
    assert tenant.post("/api/rate-contracts", json={"supplier_name": "ACC", "items": [{"item_code": "A", "rate": 1}, {"item_code": "A", "rate": 2}]}).status_code == 400


def test_purchasing_is_told_30_and_7_days_before_it_ends(tenant):
    end = date.today() + timedelta(days=25)
    contract(tenant, valid_from=(end - timedelta(days=300)).isoformat(), valid_to=end.isoformat())

    def run(day):
        with database.SessionLocal() as db:
            db.query(models.DBJobRun).filter(models.DBJobRun.job_name == "rate_contract_expiry").delete()
            db.commit()
        main.run_due_jobs(now=datetime.combine(day, datetime.min.time()).replace(hour=9), only="rate_contract_expiry")

    def told():
        return [a["title"] for a in tenant.get("/api/alerts").json()["alerts"] if a["kind"] == "rate_contract_expiring"]
    run(date.today())                                                    # 25 days left: the 30-day notice, once for the contract
    assert len(told()) == 1 and "RC-0001" in told()[0]
    run(date.today() + timedelta(days=1))
    assert len(told()) == 1
    run(end - timedelta(days=6))                                         # 6 days left: the 7-day notice
    assert len(told()) == 2
