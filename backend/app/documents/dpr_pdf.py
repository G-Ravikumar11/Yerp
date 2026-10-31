"""The daily progress report, on the company's letterhead.

What a client's engineer expects in the evening: the day's weather, who and what was on site, the plan for the day against what was
done, what held the work up, the photographs, and who signed the record off - with any change made after sign-off shown, since a
diary that was quietly rewritten is worth nothing later. Money stays out: the report goes to the client, the costs do not.
"""
from datetime import date, datetime

from app import models
from app.core.files import file_bytes
from app.documents import form_pdf
from app.documents.letterhead import letterhead

MAX_PHOTOS = 9


def _n(value):
    return form_pdf.qty_text(round(float(value or 0), 1))


def hindrances_on(db, client_id, job_id, on):
    """The hindrances holding the site up on a day: begun by then and not over before it."""
    rows = db.query(models.DBHindrance).filter(models.DBHindrance.client_id == client_id, models.DBHindrance.job_id == job_id,
                                               models.DBHindrance.from_date <= on).order_by(models.DBHindrance.from_date).all()
    return [h for h in rows if (not h.to_date or h.to_date >= on) and (h.status or "") != "Rejected"]


def dpr_spec(db, client, d):
    from app.services.projects import diary_dict, job_or_404, schedule_day
    row = diary_dict(db, d, detail=True)
    job = job_or_404(db, client.id, d.job_id)
    company = letterhead(db, client)
    on = row["diary_date"]
    day = datetime.strptime(on, "%Y-%m-%d").date() if on else date.today()
    plan = schedule_day(db, client.id, job, day)
    signed = row["status"] == "SUBMITTED"

    blocks = [
        {"type": "header", "company": company, "title": "DAILY PROGRESS REPORT",
         "facts": [("Date", form_pdf.date_text(on)), ("Project", job.number or ""), ("Status", "Signed off" if signed else "Draft")]},
        {"type": "party", "label": "Project", "name": job.name or "", "address": job.site_address or "",
         "facts": [("Client", job.customer_name or "-"), ("Work order", row["work_order"] or "-")]},
        {"type": "pairs", "cols": 2, "rows": [
            ("Weather", row["weather"]), ("Rain", "%s hours" % _n(row["rain_hours"])),
            ("Working hours", _n(row["working_hours"])), ("Labour on site", "%s mandays" % _n(row["total_mandays"])),
            ("Done to date", "%s%% (planned %s%%)" % (_n(plan["summary"]["done_percent"]), _n(plan["summary"]["planned_percent"]))),
            ("Prepared by", row["prepared_by_name"] or "-")]},
        {"type": "band", "text": "Work done"},
        {"type": "text", "text": row["work_done"] or "-"},
    ]

    # The plan for the day against the work: what was running or overdue, where the plan had it, where it is, what moved today.
    acts = plan["today"] + plan["overdue"]
    moved = [r for r in plan["others"] + plan["soon"] if r.get("done_today")]
    rows = []
    for r in acts + moved:
        state = ("%d days late" % r["days_late"]) if r.get("days_late") else ("done" if r["actual_percent"] >= 100 else
                                                                           "behind" if r["planned_percent"] - r["actual_percent"] > 10 else "on plan")
        rows.append(["%s %s" % (r["code"], r["name"]), "%s%%" % _n(r["target_today"]), "%s%%" % _n(r["done_today"]),
                     "%s%%" % _n(r["planned_percent"]), "%s%%" % _n(r["actual_percent"]), state])
    blocks += [{"type": "band", "text": "Planned against actual for the day"},
               {"type": "table", "columns": [("Activity", 70, "L"), ("Planned today", 20, "R"), ("Done today", 20, "R"),
                                             ("Planned to date", 22, "R"), ("Done to date", 22, "R"), ("", 28, "C")], "rows": rows}]

    blocks += [{"type": "band", "text": "Labour"},
               {"type": "table", "columns": [("Trade", 50, "L"), ("Agency", 70, "L"), ("Number", 30, "R"), ("Hours", 30, "R")],
                "rows": [[l["trade"] + (" - " + ", ".join(w["name"] for w in l["workers"]) if l["workers"] else ""), l["agency"],
                          _n(l["headcount"]), _n(l["hours"])] for l in row["labour"]],
                "foot": [["Mandays", "", "", _n(row["total_mandays"])]] if row["labour"] else []}]
    if row["plant"]:
        blocks += [{"type": "band", "text": "Plant and equipment"},
                   {"type": "table", "columns": [("Plant", 60, "L"), ("Worked hours", 28, "R"), ("Idle hours", 28, "R"), ("Remarks", 66, "L")],
                    "rows": [[p["plant"], _n(p["worked_hours"]), _n(p["idle_hours"]), p["remarks"] or ""] for p in row["plant"]]}]

    held = hindrances_on(db, client.id, job.id, on)
    blocks += [{"type": "band", "text": "Hindrances"}]
    if row["holdups"]:
        blocks.append({"type": "terms", "rows": [("Held up today by", row["holdups"])], "label_width": 40})
    blocks.append({"type": "table", "columns": [("No.", 14, "C"), ("Cause", 44, "L"), ("What happened", 64, "L"), ("Since", 20, "C"),
                                                ("Whose risk", 24, "L"), ("Status", 16, "C")],
                   "rows": [[h.number or "", h.cause or "", h.description or "", form_pdf.date_text(h.from_date), h.responsibility or "-",
                             h.status or ""] for h in held]})

    notes = [(label, row[key]) for label, key in (("Instructions received", "instructions"), ("Visitors", "visitors"), ("Safety", "safety_note")) if row[key]]
    if notes:
        blocks += [{"type": "band", "text": "Instructions, visitors and safety"}, {"type": "terms", "rows": notes, "label_width": 40}]

    files = db.query(models.DBFile).filter(models.DBFile.client_id == client.id, models.DBFile.attached_type == "diary",
                                           models.DBFile.attached_id == d.id).order_by(models.DBFile.id).all()
    pictures = [f for f in files if (f.content_type or "").startswith("image/")][:MAX_PHOTOS]
    if pictures:
        blocks += [{"type": "band", "text": "Photographs"},
                   {"type": "photos", "items": [(file_bytes(db, f), f.caption or f.name or "") for f in pictures]}]

    if row["amendments"]:
        blocks += [{"type": "band", "text": "Changed after it was signed off"}, {"type": "numbered", "items": row["amendments"]}]
    blocks.append({"type": "signatures", "boxes": [
        ("Prepared by", row["prepared_by_name"] or ""),
        ("Signed off by", ("%s\n%s" % (row["submitted_by_name"] or "", form_pdf.date_text(row["submitted_at"][:10]) + " " + row["submitted_at"][11:16]))
         if signed else "Not yet signed off"),
        ("For the client", job.customer_name or "")]})
    name = "DPR %s %s" % (job.number or job.name or "", on)
    return {"title": name, "author": company["name"], "watermark": "" if signed else "DRAFT - NOT SIGNED OFF", "blocks": blocks,
            "footer": "%s  |  %s  |  Printed %s" % (name, company["name"], datetime.now().strftime("%d/%m/%Y %H:%M"))}


def dpr_pdf(db, client, d):
    """(PDF bytes, file name)."""
    spec = dpr_spec(db, client, d)
    return form_pdf.build_form_pdf(spec), "%s.pdf" % spec["title"].replace("/", "-").replace(" ", "_")

