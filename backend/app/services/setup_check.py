"""Setup check: what is not yet set that the business's controls rely on, each with the screen that puts it right.

Every control in Y ERP - approval routes, budget-first work orders, documents carrying the company's GSTIN - works only
when its setting is filled in; left blank, it falls back to the Master. This lists what is still blank, for the Master's
home screen, so nothing silently falls back."""
from datetime import datetime

from app import models
from app.constants.boq import BOQ_PRICED
from app.constants.approvals import GONE_STATUSES


def _item(key, title, detail, count, link, fix):
    return {"key": key, "title": title, "detail": detail, "count": count, "link": link, "fix": fix, "ok": count == 0}


def setup_check(db, client):
    from app.core.permissions import employee_can
    from app.core.tenant_settings import tenant_setting
    from app.services.approvals import raised_by_owner
    from app.services.biometric import LAST_SYNC
    from app.services.boq import boq_lines_of_job, boq_of_job
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

    # 4. BOQ lines with no budget: no work order can be sent for them.
    projects, lines_left = 0, 0
    for job in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all():
        if (job.status or "") in ("complete", "cancelled") or boq_of_job(db, client.id, job.id) is None:
            continue
        budgeted = {k for (k,) in db.query(models.DBBoqBudgetItem.boq_key).filter(
            models.DBBoqBudgetItem.client_id == client.id, models.DBBoqBudgetItem.job_id == job.id).distinct().all()}
        left = [l for l in boq_lines_of_job(db, client.id, job.id) if l.kind in BOQ_PRICED and l.key not in budgeted]
        if left:
            projects += 1
            lines_left += len(left)
    items.append(_item("budgets", "Every BOQ line is budgeted",
                       ("%d BOQ line%s on %d project%s %s no budget - work orders for them cannot be sent." % (lines_left, "" if lines_left == 1 else "s", projects,
                                                                   "" if projects == 1 else "s", "has" if lines_left == 1 else "have"))
                       if lines_left else "Every live project's BOQ is budgeted.", lines_left, "/projects/budgeting", "Budget them"))

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
