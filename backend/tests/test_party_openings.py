"""Opening balances for parties: what a client, supplier or contractor owed on the day the books begin.

One line at the head of the party's ledger, so the Parties list, the statement of account, the balance sheet and the trial
balance have it without being told; one journal in Tally against a single offset ledger; and none of it is income or cost.
"""
import xml.etree.ElementTree as ET
from datetime import date

from conftest import make_employee
from test_finance_ledger import money_in, supplier_bill

ON = "2026-04-01"
TODAY = date.today().isoformat()


def opening(tenant, **kw):
    body = {"party_type": "supplier", "party_name": "ACC Ltd", "side": "owed", "amount": 50000, "as_on": ON, **kw}
    return tenant.post("/api/ledger/openings", json=body)


def party(tenant, kind, name):
    return next((p for p in tenant.get("/api/ledger/parties").json()["parties"] if p["party_type"] == kind and p["party"] == name), None)


def vouchers(tenant):
    return tenant.get("/api/tally/vouchers?date_from=2020-01-01&date_to=2030-12-31").json()["vouchers"]


def job(tenant, name="Opening site"):
    j = tenant.post("/api/jobs", json={"name": name, "customer_name": "Opening Client"}).json()
    return j.get("id") or j["job"]["id"]


def test_a_supplier_we_owe_is_in_the_ledger_from_the_first_day(tenant):
    res = opening(tenant)
    assert res.status_code == 200, res.text
    o = res.json()["opening"]
    assert o["number"] == "OB-%04d" % o["id"] and o["means"] == "We owe them" and o["balance"] == 50000
    p = party(tenant, "supplier", "ACC Ltd")
    assert p["billed"] == 50000 and p["moved"] == 0 and p["balance"] == 50000
    s = tenant.get("/api/ledger/parties").json()["summary"]
    assert s["we_owe"] == 50000 and s["owed_to_us"] == 0


def test_every_side_of_every_party(tenant):
    opening(tenant, party_type="client", party_name="Kokapet LLP", amount=120000)                       # they owe us
    opening(tenant, party_type="client", party_name="Gachibowli Ltd", side="advance", amount=30000)    # they paid ahead
    opening(tenant, party_type="contractor", party_name="Sri Ram Works", amount=80000)                 # we owe them
    opening(tenant, party_type="supplier", party_name="ACC Ltd", side="advance", amount=15000)         # we paid ahead
    assert party(tenant, "client", "Kokapet LLP")["balance"] == 120000
    assert party(tenant, "client", "Gachibowli Ltd")["balance"] == -30000
    assert party(tenant, "contractor", "Sri Ram Works")["balance"] == 80000
    assert party(tenant, "supplier", "ACC Ltd")["balance"] == -15000
    s = tenant.get("/api/ledger/parties").json()["summary"]
    assert (s["owed_to_us"], s["advances_in"], s["we_owe"], s["advances_out"]) == (120000, 30000, 80000, 15000)
    listed = tenant.get("/api/ledger/openings").json()
    assert listed["summary"] == {"count": 4, "owed_to_us": 120000, "we_owe": 80000}
    assert {r["means"] for r in listed["openings"]} == {"They owe us", "They paid us ahead", "We owe them", "We paid them ahead"}


def test_it_adds_to_what_the_bills_say_and_is_settled_by_what_is_paid(tenant):
    opening(tenant, amount=50000)
    supplier_bill(tenant, vendor="ACC Ltd", amount=10000, tax=1800)                                    # 11,800 more
    assert party(tenant, "supplier", "ACC Ltd")["balance"] == 61800
    # Paid on account, it comes off the opening just the same.
    paid = money_in(tenant, direction="OUT", doc_type="on_account", party_type="supplier", party_name="ACC Ltd", amount=20000, mode="Cash")
    assert paid.status_code == 200, paid.text
    assert party(tenant, "supplier", "ACC Ltd")["balance"] == 41800
    # The name is read the way every other ledger reads it: case and spacing do not make two suppliers.
    assert len([p for p in tenant.get("/api/ledger/parties").json()["parties"] if p["party_type"] == "supplier"]) == 1


def test_the_statement_starts_from_it(tenant):
    opening(tenant, amount=50000)
    supplier_bill(tenant, vendor="ACC Ltd", amount=10000, tax=1800)
    st = tenant.get("/api/ledger/statement", params={"party_type": "supplier", "party": "ACC Ltd"}).json()
    first = st["rows"][0]
    assert first["kind"] == "Opening balance" and first["date"] == ON and first["balance"] == 50000 and st["closing"] == 61800
    # A statement for a later period carries it as the balance brought forward.
    later = tenant.get("/api/ledger/statement", params={"party_type": "supplier", "party": "ACC Ltd", "date_from": "2026-05-01"}).json()
    assert later["opening"] == 50000 and all(r["kind"] != "Opening balance" for r in later["rows"])


def test_it_reaches_the_balance_sheet_but_not_the_profit_and_loss(tenant):
    before = tenant.get("/api/reports/balance-sheet").json()
    pl_before = tenant.get("/api/reports/profit-loss").json()
    opening(tenant, amount=50000)
    opening(tenant, party_type="client", party_name="Kokapet LLP", amount=120000)
    after = tenant.get("/api/reports/balance-sheet").json()
    assert round(after["liabilities"]["accounts_payable"] - before["liabilities"]["accounts_payable"], 2) == 50000
    assert round(after["assets"]["accounts_receivable"] - before["assets"]["accounts_receivable"], 2) == 120000
    pl = tenant.get("/api/reports/profit-loss").json()
    assert pl["total_revenue"] == pl_before["total_revenue"] and pl["total_expenses"] == pl_before["total_expenses"]


def test_tally_gets_a_journal_against_one_offset_ledger(tenant):
    opening(tenant, party_type="client", party_name="Kokapet LLP", amount=120000, note="Bill 14 raised on paper")
    opening(tenant, party_type="client", party_name="Gachibowli Ltd", side="advance", amount=30000)
    opening(tenant, party_type="supplier", party_name="ACC Ltd", amount=50000)
    opening(tenant, party_type="supplier", party_name="Sri Sai Steel", side="advance", amount=15000)
    by = {v["narration"].split(":")[0].replace("Opening balance - ", ""): v for v in vouchers(tenant) if v["type"] == "Journal"}
    side = lambda v: {l["ledger"]: (l["debit"], l["credit"]) for l in v["lines"]}
    # A client who owes us, and a supplier we paid ahead, are debits to the party; the other two are credits.
    assert side(by["Kokapet LLP"]) == {"Kokapet LLP": (120000, 0), "Opening Balance Adjustment": (0, 120000)}
    assert side(by["Gachibowli Ltd"]) == {"Gachibowli Ltd": (0, 30000), "Opening Balance Adjustment": (30000, 0)}
    assert side(by["ACC Ltd"]) == {"ACC Ltd": (0, 50000), "Opening Balance Adjustment": (50000, 0)}
    assert side(by["Sri Sai Steel"]) == {"Sri Sai Steel": (15000, 0), "Opening Balance Adjustment": (0, 15000)}
    assert all(v["date"] == ON and v["number"].startswith("OB-") for v in by.values())
    assert "Bill 14 raised on paper" in by["Kokapet LLP"]["narration"]
    # The masters create the offset ledger under Suspense, and the parties under their usual groups.
    root = ET.fromstring(tenant.get("/api/tally/masters.xml?date_from=2020-01-01&date_to=2030-12-31").content)
    groups = {l.get("NAME"): l.findtext("PARENT") for l in root.iter("LEDGER")}
    assert groups["Opening Balance Adjustment"] == "Suspense A/c"
    assert groups["Kokapet LLP"] == "Sundry Debtors" and groups["ACC Ltd"] == "Sundry Creditors"
    # Each voucher opens (or advances) a bill reference for the party.
    xml = tenant.get("/api/tally/vouchers.xml?date_from=2020-01-01&date_to=2030-12-31").text
    assert "<NAME>Opening balance</NAME><BILLTYPE>New Ref</BILLTYPE>" in xml and "<NAME>Opening advance</NAME><BILLTYPE>Advance</BILLTYPE>" in xml


def test_only_the_period_it_falls_in_goes_across(tenant):
    opening(tenant, as_on="2026-04-01")
    assert not [v for v in tenant.get("/api/tally/vouchers?date_from=2026-05-01&date_to=2026-12-31").json()["vouchers"] if v["number"].startswith("OB-")]
    assert [v for v in tenant.get("/api/tally/vouchers?date_from=2026-04-01&date_to=2026-04-30").json()["vouchers"] if v["number"].startswith("OB-")]


def test_the_trial_balance_balances_with_it_and_shows_the_offset(tenant):
    opening(tenant, party_type="client", party_name="Kokapet LLP", amount=120000)
    opening(tenant, party_type="supplier", party_name="ACC Ltd", amount=50000)
    tb = tenant.get("/api/reports/trial-balance?date_from=2020-01-01&date_to=2030-12-31").json()
    rows = {r["ledger"]: r for r in tb["ledgers"]}
    assert tb["balanced"] is True and tb["warnings"] == []
    assert rows["Kokapet LLP"]["closing_dr"] == 120000 and rows["ACC Ltd"]["closing_cr"] == 50000
    assert rows["Opening Balance Adjustment"]["group"] == "Suspense A/c" and rows["Opening Balance Adjustment"]["closing_cr"] == 70000
    # With the period starting after it, it is the opening column.
    later = {r["ledger"]: r for r in tenant.get("/api/reports/trial-balance?date_from=2026-05-01&date_to=2026-12-31").json()["ledgers"]}
    assert later["Kokapet LLP"]["opening_dr"] == 120000 and later["Kokapet LLP"]["debit"] == 0


def test_a_project_can_be_named_and_is_kept_with_it(tenant):
    jid = job(tenant)
    res = opening(tenant, job_id=jid)
    assert res.status_code == 200, res.text
    assert res.json()["opening"]["project"].endswith("Opening site")
    assert opening(tenant, job_id=999999).status_code == 404
    # The same party on another project is a separate balance; on the same one, it is the same balance.
    assert opening(tenant, job_id=job(tenant, "Second site")).status_code == 200
    assert opening(tenant, job_id=jid).status_code == 409
    assert opening(tenant, party_name="acc ltd.").status_code == 200                      # head office, no project: a third, separate balance
    assert opening(tenant).status_code == 409                                              # and a second head-office one is the same balance


def test_one_balance_a_party_not_two(tenant):
    assert opening(tenant).status_code == 200
    again = opening(tenant, party_name="  A.C.C.  ltd ", amount=70000)
    assert again.status_code == 409 and "already has an opening balance" in again.json()["detail"]
    assert party(tenant, "supplier", "ACC Ltd")["balance"] == 50000


def test_what_is_refused(tenant):
    assert opening(tenant, party_type="staff").status_code == 400
    assert opening(tenant, party_type="").status_code == 400
    assert opening(tenant, party_name="   ").status_code == 400
    assert opening(tenant, side="debit").status_code == 400
    assert opening(tenant, amount=0).status_code == 400
    assert opening(tenant, amount=-5).status_code == 400
    assert opening(tenant, amount=10 ** 12).status_code == 400
    assert opening(tenant, as_on="1 April").status_code == 400
    assert opening(tenant, as_on="2999-01-01").status_code == 400            # not a balance that has been
    assert opening(tenant, as_on="").status_code == 400
    assert tenant.get("/api/ledger/openings").json()["openings"] == []


def test_changing_and_taking_one_away(tenant):
    o = opening(tenant).json()["opening"]
    res = tenant.put("/api/ledger/openings/%d" % o["id"], json={"amount": 65000, "note": "Agreed with their accounts"})
    assert res.status_code == 200, res.text
    assert party(tenant, "supplier", "ACC Ltd")["balance"] == 65000
    assert tenant.put("/api/ledger/openings/%d" % o["id"], json={"side": "advance"}).status_code == 200
    assert party(tenant, "supplier", "ACC Ltd")["balance"] == -65000
    assert tenant.put("/api/ledger/openings/%d" % o["id"], json={"amount": 0}).status_code == 400
    assert tenant.delete("/api/ledger/openings/%d" % o["id"]).status_code == 200
    assert party(tenant, "supplier", "ACC Ltd") is None
    assert tenant.delete("/api/ledger/openings/%d" % o["id"]).status_code == 404
    assert tenant.put("/api/ledger/openings/999999", json={"amount": 1}).status_code == 404


def test_the_closed_books_are_not_reopened_by_it(tenant):
    o = opening(tenant, as_on="2026-03-31").json()["opening"]
    assert tenant.put("/api/money/lock", json={"locked_upto": "2026-04-30"}).status_code == 200
    shut = opening(tenant, party_name="Sri Sai Steel", as_on="2026-04-15")
    assert shut.status_code == 409 and "closed" in shut.json()["detail"]
    assert tenant.put("/api/ledger/openings/%d" % o["id"], json={"amount": 1}).status_code == 409
    assert tenant.delete("/api/ledger/openings/%d" % o["id"]).status_code == 409
    assert opening(tenant, party_name="Sri Sai Steel", as_on="2026-05-01").status_code == 200       # after the closed period


def test_only_accounts_may_enter_them_but_those_who_see_the_ledger_may_read(tenant, portal):
    opening(tenant)
    e = make_employee(tenant, password="Crew1234", permission_role="staff", emergency_contact="Asha", emergency_phone="9999999999")
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    assert portal.post("/api/employee/auth/login", json={"email": e["email"], "password": "Crew1234"}).status_code == 200
    assert portal.post("/api/ledger/openings", json={"party_type": "client", "party_name": "X", "side": "owed", "amount": 1, "as_on": ON}).status_code in (401, 403)
    assert portal.get("/api/ledger/openings").status_code in (401, 403)
    assert tenant.get("/api/ledger/openings").status_code == 200
