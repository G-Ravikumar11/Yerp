"""Setup check: what is not yet set that the business's controls rely on, each with the screen that puts it right.

Every control in Y ERP - approval routes, budget-first work orders, documents carrying the company's GSTIN - works only
when its setting is filled in; left blank, it falls back to the Master. This lists what is still blank, for the Master's
home screen, so nothing silently falls back."""
from datetime import datetime

from app import models
from app.constants.approvals import GONE_STATUSES


def _item(key, title, detail, count, link, fix):
    return {"key": key, "title": title, "detail": detail, "count": count, "link": link, "fix": fix, "ok": count == 0}


def setup_check(db, client):
    from app.core.permissions import employee_can
    from app.core.tenant_settings import tenant_setting
    from app.services.approvals import raised_by_owner
    from app.services.biometric import LAST_SYNC
    from app.services.settings import company_identity

    items = []

    # 1. The company's own details, which every work order, bill and export is headed with.
    missing = company_identity(db, client).get("missing") or []
    items.append(_item("company", "Company details on every document",
                       ("Missing: %s - work orders, bills and exports go out without them." % ", ".join(missing)) if missing
                       else "Name, address, GSTIN, PAN and logo are all set.", len(missing), "/settings", "Complete company details"))

    staff = [e for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id).all()
             if (e.status or "active") not in GONE_STATUSES]

    # 2. Reporting lines: anybody who reports to nobody sends everything straight to the Master.
    loose = [e for e in staff if not e.reports_to and not raised_by_owner(db, client.id, e.id)]
    items.append(_item("reports_to", "Everybody reports to somebody",
                       ("%d %s no Reports to, so what they send for approval comes straight to you." %
                        (len(loose), "person has" if len(loose) == 1 else "people have")) if loose
                       else "Every approval climbs its reporting line before it reaches you.",
                       len(loose), "/people/employees?no_manager=1", "Set their Reports to"))

    # 3. Somebody besides the Master who may set budgets - else every budget waits for the Master.
    setters = [e for e in staff if employee_can(e, "budget.edit")]
    items.append(_item("budget_people", "Somebody sets the budgets",
                       "Only you can set project budgets. Give \"Edit project budgets\" to whoever prices them (HO QS, say)."
                       if not setters else "%d %s set budgets." % (len(setters), "person can" if len(setters) == 1 else "people can"),
                       0 if setters else 1, "/people/employees", "Give the right"))

    # 4. HO QS budget: every applicable BOQ line of every live project budgeted - no work order on a project goes out
    #    until its whole BOQ is (services/budget_control.py, the same figures the work-order check reads).
    from app.services.budget_control import BUDGETED, budget_lines, live_projects, summary
    projects = live_projects(db, client.id)
    totals = summary([])
    totals.pop("status", None)                     # a word for one project, not for all of them added up
    need = []
    lines_left = 0
    for p in projects:
        sm = p["summary"]
        for k in ("lines", "budgeted", "partial", "unbudgeted"):
            totals[k] += sm[k]
        totals["approved_value"] += sm["approved_value"]
        totals["budgeted_value"] += sm["budgeted_value"]
        left = sm["partial"] + sm["unbudgeted"]
        if left:
            lines_left += left
            rows = [r for r in budget_lines(db, client.id, p["job_id"]) if r["status"] != BUDGETED]
            need.append({"job_id": p["job_id"], "code": p["code"], "name": p["name"], "lines": [
                {"key": r["key"], "item_no": r["item_no"], "description": r["description"][:120], "unit": r["unit"], "status": r["status"],
                 "quantity": r["approved_qty"], "value": r["approved_value"]} for r in rows]})
    totals["approved_value"] = round(totals["approved_value"], 2)
    totals["budgeted_value"] = round(totals["budgeted_value"], 2)
    totals["remaining_value"] = round(totals["approved_value"] - totals["budgeted_value"], 2)
    totals["completion_percent"] = round(totals["budgeted"] / totals["lines"] * 100, 1) if totals["lines"] else 100.0
    totals["value_percent"] = round(totals["budgeted_value"] / totals["approved_value"] * 100, 1) if totals["approved_value"] else 100.0
    budgets = _item("budgets", "Every BOQ line is budgeted",
                    ("%d of %d BOQ line%s on %d live project%s %s still to budget (%d partly, %d not at all) - no work order on those projects "
                     "is sent until they are. %s%% budgeted." % (lines_left, totals["lines"], "" if totals["lines"] == 1 else "s", len(need),
                                                                "" if len(need) == 1 else "s", "is" if lines_left == 1 else "are",
                                                                totals["partial"], totals["unbudgeted"], totals["completion_percent"]))
                    if lines_left else "Every live project's BOQ is budgeted.", lines_left, "/projects/budgeting", "Budget them")
    budgets["budget"] = {"totals": totals, "projects": need}
    items.append(budgets)

    # 5. Sub contractors waiting to be taken on - or whose changed bank details wait - and so not paid.
    waiting = db.query(models.DBContractor).filter(models.DBContractor.client_id == client.id,
                                                   models.DBContractor.registration_status == "PENDING").count()
    items.append(_item("contractors", "Sub contractors approved",
                       ("%d sub contractor%s %s waiting for approval - no order or payment goes to them until then." %
                        (waiting, "" if waiting == 1 else "s", "is" if waiting == 1 else "are")) if waiting
                       else "No registration or bank change is waiting.", waiting, "/approvals", "Approve them"))

    # 6. The biometric sync, once set up, still sending.
    last = tenant_setting(db, client.id, LAST_SYNC, "")
    if last:
        try:
            hours = int((datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).total_seconds() // 3600)
        except ValueError:
            hours = 0
        items.append(_item("biometric", "Biometric attendance arriving",
                           ("The office sync program has been silent for %s - punches are not reaching Y ERP." %
                            ("%d days" % (hours // 24) if hours >= 48 else "%d hours" % hours)) if hours >= 24
                           else "The office sync program is sending.", 1 if hours >= 24 else 0,
                           "/people/attendance?tab=biometric", "See the sync"))

    items.sort(key=lambda i: i["ok"])
    return {"items": items, "to_do": sum(1 for i in items if not i["ok"]), "total": len(items)}
