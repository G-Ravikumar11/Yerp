"""The rules and workings behind the head office endpoints.

Head office is two people - HO QS and HO Coordinator - who look after every site at once. HO QS is the
only one in the business (with the Master) who opens vendor codes, work orders and BOQs; the coordinator
sees the same and follows up whatever is waiting. The HO portal is their front page: what is open, what
is stuck and on whom, and what HO QS has still to open.
"""
from app import models

from app.constants.head_office import HO_FOLLOW_UP_SKIPS, HO_LIST_LIMIT, HO_QUIET_JOB_STATUSES
from app.core.currency import money
from app.core.permissions import HO_QS_ONLY, PERMISSION_ROLES, employee_can
from app.core.queries import by_id, prime
from app.services.approvals import approval_inbox
from app.services.hr import employee_name


def ho_person(emp):
    """Who is looking, and what of head office's own work they may open."""
    if emp is None:
        return {"role": "owner", "role_label": "Master", "name": "",
                "may_create": {"vendors": True, "work_orders": True, "boq": True}}
    role = (emp.permission_role or "").lower()
    return {
        "role": role,
        "role_label": next((r["label"] for r in PERMISSION_ROLES if r["code"] == role), role),
        "name": employee_name(emp),
        "may_create": {"vendors": employee_can(emp, "vendors.create"),
                       "work_orders": employee_can(emp, "workorders.create"),
                       "boq": employee_can(emp, "boq.create")},
    }


def _count(rows, test):
    return len([r for r in rows if test(r)])


def ho_vendor_counts(db, client_id):
    statuses = [r[0] or "APPROVED" for r in db.query(models.DBContractor.registration_status).filter(
        models.DBContractor.client_id == client_id).all()]
    return {"registered": statuses.count("APPROVED"), "pending": statuses.count("PENDING"),
            "sent_back": statuses.count("REJECTED"), "total": len(statuses)}


def ho_subcontract_counts(db, client_id):
    rows = db.query(models.DBSubcontractOrder.status, models.DBSubcontractOrder.net_order_value).filter(
        models.DBSubcontractOrder.client_id == client_id).all()
    return {
        "draft": _count(rows, lambda r: r.status == "DRAFT"),
        "awaiting": _count(rows, lambda r: r.status == "PROVISIONAL"),
        "approved": _count(rows, lambda r: r.status in ("APPROVED", "EXECUTED")),
        "total": _count(rows, lambda r: r.status not in ("CANCELLED", "AMENDED")),
        "value": money(sum(r.net_order_value or 0 for r in rows if r.status not in ("CANCELLED", "AMENDED", "DRAFT"))),
    }


def ho_client_order_counts(db, client_id):
    rows = db.query(models.DBWorkOrder.status, models.DBWorkOrder.approval_status,
                    models.DBWorkOrder.total_value).filter(models.DBWorkOrder.client_id == client_id).all()
    return {
        "draft": _count(rows, lambda r: (r.status or "Draft") == "Draft" and r.approval_status != "pending"),
        "awaiting": _count(rows, lambda r: r.approval_status == "pending"),
        "placed": _count(rows, lambda r: (r.status or "Draft") != "Draft"),
        "total": len(rows),
        "value": money(sum(r.total_value or 0 for r in rows)),
    }


def ho_sub_bill_counts(db, client_id):
    rows = db.query(models.DBSubBill.status, models.DBSubBill.this_bill).filter(
        models.DBSubBill.client_id == client_id).all()
    return {
        "draft": _count(rows, lambda r: (r.status or "DRAFT") == "DRAFT"),
        "awaiting": _count(rows, lambda r: r.status == "SUBMITTED"),
        "certified": _count(rows, lambda r: r.status == "CERTIFIED"),
        "claimed": money(sum(r.this_bill or 0 for r in rows if (r.status or "DRAFT") != "CANCELLED")),
    }


def ho_boq_summary(db, client_id):
    """Every BOQ, and the live projects that have none yet - the next ones HO QS has to open."""
    boqs = db.query(models.DBBoq).filter(models.DBBoq.client_id == client_id).all()
    open_revs = {r[0] for r in db.query(models.DBBoqRevision.boq_id).filter(
        models.DBBoqRevision.boq_id.in_([b.id for b in boqs] or [0]),
        models.DBBoqRevision.status == "OPEN").all()}
    with_boq = {b.job_id for b in boqs}
    jobs = db.query(models.DBJob).filter(models.DBJob.client_id == client_id).order_by(models.DBJob.id.desc()).all()
    without = [{"id": j.id, "number": j.number or "", "name": j.name or "", "status": j.status or ""}
               for j in jobs if j.id not in with_boq and (j.status or "") not in HO_QUIET_JOB_STATUSES]
    return {"count": len(boqs), "being_priced": len([b for b in boqs if b.id in open_revs]),
            "projects_without": len(without)}, without[:HO_LIST_LIMIT]


def ho_follow_up(db, client):
    """Everything in the business waiting on somebody to decide, and on whom - the coordinator's list.
    The same list the Master's approvals inbox shows, less what is nobody's business but HR's."""
    rows = [r for r in approval_inbox(db, client, None) if r.get("kind") not in HO_FOLLOW_UP_SKIPS]
    rows.sort(key=lambda r: r.get("since") or "")
    return rows[:HO_LIST_LIMIT]


def ho_drafts(db, client_id):
    """Orders opened and not yet sent for approval: the work head office has in hand."""
    out = []
    subs = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.client_id == client_id,
        models.DBSubcontractOrder.status == "DRAFT").order_by(models.DBSubcontractOrder.id.desc()).limit(HO_LIST_LIMIT).all()
    prime(db, models.DBContractor, [o.contractor_id for o in subs])
    prime(db, models.DBJob, [o.job_id for o in subs])
    prime(db, models.DBEmployee, [o.submitted_by for o in subs])
    for o in subs:
        con, job = by_id(db, models.DBContractor, o.contractor_id), by_id(db, models.DBJob, o.job_id)
        out.append({"kind": "subcontract_order", "kind_label": "Sub contractor work order", "id": o.id,
                    "number": o.wo_number or "", "party": (con.company_name if con else "") or "",
                    "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
                    "subject": o.subject or "", "amount": money(o.net_order_value or o.gross_amount or 0),
                    "raised_by": employee_name(by_id(db, models.DBEmployee, o.submitted_by)) or "Master",
                    "since": o.updated_at or o.created_at or "",
                    "href": "/subcontractors/work-orders/%d" % o.id})
    clients = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.client_id == client_id, models.DBWorkOrder.status == "Draft",
        models.DBWorkOrder.approval_status != "pending").order_by(models.DBWorkOrder.id.desc()).limit(HO_LIST_LIMIT).all()
    prime(db, models.DBJob, [w.job_id for w in clients])
    for w in clients:
        job = by_id(db, models.DBJob, w.job_id)
        out.append({"kind": "work_order", "kind_label": "Client work order", "id": w.id,
                    "number": w.number or "", "party": (job.customer_name if job else "") or "",
                    "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
                    "subject": w.reference or "", "amount": money(w.total_value or 0),
                    "raised_by": employee_name(by_id(db, models.DBEmployee, w.submitted_by)) or "",
                    "since": w.created_at or "", "href": "/clients/work-orders"})
    out.sort(key=lambda d: d["since"], reverse=True)
    return out[:HO_LIST_LIMIT]


def ho_overview(db, client, emp):
    """The HO portal's front page, in one answer."""
    boq, without_boq = ho_boq_summary(db, client.id)
    return {
        "person": ho_person(emp),
        "company": client.company_name or "",
        "reserved": sorted(HO_QS_ONLY),
        "vendors": ho_vendor_counts(db, client.id),
        "subcontract_orders": ho_subcontract_counts(db, client.id),
        "client_orders": ho_client_order_counts(db, client.id),
        "boqs": boq,
        "sub_bills": ho_sub_bill_counts(db, client.id),
        "projects_without_boq": without_boq,
        "waiting": ho_follow_up(db, client),
        "drafts": ho_drafts(db, client.id),
    }
