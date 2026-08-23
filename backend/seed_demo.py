"""Build a demo database for Y ERP with a realistic contracting firm in it.

Deliberately not part of the application. Run it to get something worth
clicking through; delete backend/demo_portal.db to start again.

    python backend/seed_demo.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(HERE, "demo_portal.db").replace("\\", "/")
os.environ.setdefault("SECRET_KEY", "demo-secret-not-for-production")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("SCHEDULER_ENABLED", "0")

import logging
logging.disable(logging.INFO)

from fastapi.testclient import TestClient          # noqa: E402
import database, main, models                      # noqa: E402

OWNER = ("owner@yprojects.co.in", "Passw0rdTest")
STAFF_PASSWORD = "Crew1234"
DOMAIN = "yprojects.co.in"


def main_seed():
    models.Base.metadata.create_all(bind=database.engine)
    with TestClient(main.app) as c:
        c.post("/api/client/register", json={
            "email": OWNER[0], "password": OWNER[1], "company_name": "Y Projects"})
        assert c.post("/api/client/login", json={
            "email": OWNER[0], "password": OWNER[1]}).status_code == 200
        c.post("/api/client/onboard", json={
            "company_name": "Y Projects Pvt. Ltd.", "contact_name": "Alan Doyle",
            "address": "Plot 14, Industrial Estate, Hyderabad", "industry": "Construction"})
        c.put("/api/hr/org-domain", json={"domain": DOMAIN})

        # A reporting line, so the approval chain has somewhere to go.
        def person(first, last, role, reports_to=None, rate=0):
            r = c.post("/api/employees", json={
                "first_name": first, "last_name": last,
                "email": "%s.%s@%s" % (first.lower(), last.lower(), DOMAIN),
                "password": STAFF_PASSWORD, "permission_role": role,
                "reports_to": reports_to, "salary": 45000, "hourly_rate": rate,
                "job_title": role.replace("_", " ").title()})
            emp = r.json()
            c.put("/api/employees/%d" % emp["id"], json={"status": "active"})
            return emp

        # The account holder gets their own record at the top of the tree.
        # An earlier version repointed the director's record at the owner's
        # address instead, which gave the owner somewhere to sit but quietly
        # took away the director's own login.
        top = c.post("/api/employees", json={
            "first_name": "Y", "last_name": "Owner", "email": OWNER[0],
            "password": OWNER[1], "permission_role": "owner",
            "salary": 0, "job_title": "Proprietor"}).json()
        c.put("/api/employees/%d" % top["id"], json={"status": "active"})

        director = person("Alan", "Doyle", "manager", top["id"])
        foreman = person("Priya", "Shah", "supervisor", director["id"], rate=320)
        person("Tom", "Reilly", "staff", foreman["id"], rate=260)
        finance = person("Nina", "Patel", "finance", director["id"])
        person("Meera", "Iyer", "hr_admin", director["id"])

        # Small costs approve themselves; large ones also need finance.
        c.put("/api/approval-rules", json={"auto_below": 2000, "finance_above": 200000})

        jobs = [
            c.post("/api/jobs", json={
                "name": "Fairview, plot 3", "customer_name": "Fairview Homes",
                "site_address": "Fairview Estate, Plot 3", "status": "in_progress",
                "quoted_value": 2500000, "budget": 1700000}).json(),
            c.post("/api/jobs", json={
                "name": "Sector 12 substation", "customer_name": "Aniprotech Infra",
                "site_address": "Sector 12", "status": "in_progress",
                "quoted_value": 900000, "budget": 640000}).json(),
            c.post("/api/jobs", json={
                "name": "Riverside phase 1", "customer_name": "Riverside Developers",
                "status": "quoting", "quoted_value": 4100000}).json(),
        ]

        # Codes are issued by the system; nothing here types one.
        made = c.post("/api/erp/items/bulk", json={"items": [
            {"kind": "RM", "item_name": "20MM LMS PVC ISI CONDUIT",
             "units_of_measure": "Meters", "hsn_code": "3917", "item_tax_type": "18%"},
            {"kind": "RM", "item_name": "25MM LMS PVC ISI CONDUIT",
             "units_of_measure": "Meters", "hsn_code": "3917", "item_tax_type": "18%"},
            {"kind": "RM", "item_name": "20MM PVC COUPLER",
             "units_of_measure": "Nos", "hsn_code": "3917", "item_tax_type": "18%"},
            {"kind": "RM", "item_name": "20MM PVC BEND",
             "units_of_measure": "Nos", "hsn_code": "3917", "item_tax_type": "18%"},
            {"kind": "FG", "item_name": "SUPPLY OF 20MM CONDUIT", "item_type": "Purchased",
             "units_of_measure": "Meters", "hsn_code": "3917", "item_tax_type": "18%"},
            {"kind": "FG", "item_name": "INSTALLATION OF 20MM CONDUIT", "item_type": "Service",
             "units_of_measure": "Meters", "hsn_code": "3917", "item_tax_type": "18%"},
            {"kind": "FG", "item_name": "TESTING AND COMMISSIONING", "item_type": "Service",
             "units_of_measure": "Meters", "hsn_code": "3917", "item_tax_type": "18%"},
        ]}).json()
        codes = made["codes"]
        fg = codes[4:]

        wo = c.post("/api/erp/work-orders/build", json={
            "job_id": jobs[0]["id"], "reference": "PO-7781",
            "lines": [{"code": fg[0], "qty": 5000, "rate": 62},
                      {"code": fg[1], "qty": 5000, "rate": 18},
                      {"code": fg[2], "qty": 5000, "rate": 6}]}).json()["work_order"]

        c.post("/api/erp/bom/build", json={
            "work_order_id": wo["id"],
            "lines": [{"fg_code": fg[0], "rm_code": codes[0], "qty": 5100, "rate": 46},
                      {"fg_code": fg[1], "rm_code": codes[2], "qty": 600, "rate": 12},
                      {"fg_code": fg[2], "rm_code": codes[3], "qty": 400, "rate": 18}]})

        # A little money moving, so no screen opens empty.
        c.post("/api/invoices", json={
            "contact": "Fairview Homes", "email": "accounts@fairviewhomes.in",
            "issue_date": "2026-08-01", "due_date": "2026-08-31",
            "job_id": jobs[0]["id"], "tax_type": "exclusive",
            "line_items": [{"description": "Groundworks and conduit, first run",
                            "qty": 1, "price": 850000, "tax_rate": "18% GST"}]})
        c.post("/api/bills", json={
            "number": "BILL-0001", "vendor_name": "Travis Perkins",
            "issue_date": "2026-08-04", "due_date": "2026-09-03",
            "amount": 234000, "tax_amount": 42120, "total": 276120,
            "job_id": jobs[0]["id"], "category": "materials"})

        board = c.get("/api/jobs-summary").json()
        items = c.get("/api/erp/items").json()

    print()
    print("  Y ERP demo ready")
    print("  " + "-" * 58)
    print("  %-34s %s" % ("OWNER  " + OWNER[0], OWNER[1]))
    for who, role in (("alan.doyle", "Manager / director"),
                      ("priya.shah", "Supervisor"),
                      ("tom.reilly", "Staff"),
                      ("nina.patel", "Finance"),
                      ("meera.iyer", "HR Admin")):
        print("  %-34s %-12s %s" % (who + "@" + DOMAIN, STAFF_PASSWORD, role))
    print("  " + "-" * 58)
    print("  %d item codes issued: %s" % (len(codes), ", ".join(codes)))
    print("  %s on %s, value %s" % (wo["number"], wo["job_name"], wo["total_value"]))
    print("  %d jobs on the board, %d item codes on file"
          % (len(board["jobs"]), items["counts"]["RM"] + items["counts"]["FG"]))
    print()


if __name__ == "__main__":
    main_seed()
