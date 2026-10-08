"""The rules and workings behind the approvals endpoints."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import or_

from app import models

from app.constants.approvals import (
    APPROVAL_MODELS,
    APPROVE_RIGHT,
    AUTO_BELOW_KEY,
    BILL_APPROVED_FOR_PAYMENT,
    BILL_AWAITING_APPROVAL,
    BILL_REJECTED,
    CHAIN_KIND,
    FINANCE_ABOVE_KEY,
    GONE_STATUSES,
    PO_APPROVED,
    PO_AWAITING_APPROVAL,
    PO_REJECTED,
    SUB_BILL_OWNER_SIGNS_KEY,
    WO_APPROVED,
    WO_AWAITING_APPROVAL,
    WO_OWNER_SIGNS_KEY,
    WO_REJECTED,
)
from app.core.audit import log_audit
from app.core.currency import formatted_money, inr, money
from app.core.permissions import employee_can, role_rank
from app.core.queries import by_id, prime, prime_chains
from app.core.tenant_settings import tenant_setting


def build_approval_chain(employee_id, client_id, db):
    """Walk the reports_to chain from the given employee upward. Returns a list
    of {employee_id, level, role} sorted by step number (1 = first approver).
    Skips duplicate levels and stops after 8 steps max. A person still onboarding counts: an
    employee the owner has added with a login is somebody to report to, active or not; only
    those who have left are passed over."""
    chain = []
    visited = set()
    current_id = employee_id
    for _ in range(8):
        if not current_id or current_id in visited:
            break
        visited.add(current_id)
        emp = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == current_id,
            models.DBEmployee.client_id == client_id,
            or_(models.DBEmployee.status.is_(None), models.DBEmployee.status.notin_(GONE_STATUSES))
        ).first()
        if not emp:
            break
        # The manager is the person this employee reports to
        if not emp.reports_to:
            break  # reached top of chain
        manager = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == emp.reports_to,
            models.DBEmployee.client_id == client_id,
            or_(models.DBEmployee.status.is_(None), models.DBEmployee.status.notin_(GONE_STATUSES))
        ).first()
        if not manager:
            break
        chain.append({
            "employee_id": manager.id,
            "level": manager.level or "",
            "role": manager.role or "employee",
            "name": f"{manager.first_name} {manager.last_name}".strip(),
        })
        # Continue from the manager, not from the manager's own manager. The
        # latter skipped a generation on every pass, so a three-deep reporting
        # line produced one approver instead of two and the director above them
        # was never asked.
        current_id = manager.id
    return chain


def get_approval_chain_history(entity_type, entity_id, db):
    """Return the full approval chain history for a document, with employee details."""
    steps = db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == entity_type,
        models.DBApprovalChain.entity_id == entity_id,
    ).order_by(models.DBApprovalChain.step).all()
    result = []
    for s in steps:
        approver = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == s.approver_id).first()
        submitter = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == s.employee_id).first()
        result.append({
            "id": s.id,
            "step": s.step,
            "status": s.status,
            "notes": s.notes or "",
            "decided_at": s.decided_at or "",
            "approver_name": f"{approver.first_name} {approver.last_name}".strip() if approver
                             else ("Master" if s.approver_id is None else "Unknown"),
            "approver_level": s.level,
            "approver_role": approver.role if approver else "",
            "submitter_name": f"{submitter.first_name} {submitter.last_name}".strip() if submitter else "",
        })
    return result


def approval_doc(db, entity_type, entity_id, client_id=None):
    model = APPROVAL_MODELS.get(entity_type)
    if not model:
        return None
    query = db.query(model).filter(model.id == entity_id)
    if client_id is not None:
        query = query.filter(model.client_id == client_id)
    return query.first()


def approval_thresholds(db, client_id):
    """The two numbers that make a chain practical.

    Below the first, a cost is not worth anybody's signature. Above the second,
    one manager's word is not enough and finance has to see it too. Zero on
    either means the rule is off, which is how every existing tenant behaves
    until somebody sets one.
    """
    def amount(key):
        try:
            return max(0.0, float(tenant_setting(db, client_id, key, "") or 0))
        except (TypeError, ValueError):
            return 0.0
    return amount(AUTO_BELOW_KEY), amount(FINANCE_ABOVE_KEY)


def set_approval_display_status(doc, entity_type, outcome):
    """Mirror where a document has got to onto its own status.

    Finance should not have to read an approval chain to know whether a bill
    may be paid; the status on the document says so.
    """
    labels = {
        "bill": {"pending": BILL_AWAITING_APPROVAL,
                 "approved": BILL_APPROVED_FOR_PAYMENT,
                 "rejected": BILL_REJECTED},
        "purchase_order": {"pending": PO_AWAITING_APPROVAL,
                           "approved": PO_APPROVED,
                           "rejected": PO_REJECTED},
        "work_order": {"pending": WO_AWAITING_APPROVAL,
                       "approved": WO_APPROVED,
                       "rejected": WO_REJECTED},
    }
    # Invoices keep their own Draft/Sent/Paid lifecycle; approval is recorded
    # alongside it rather than overwriting it.
    if entity_type in labels:
        doc.status = labels[entity_type][outcome]
    if hasattr(doc, "rejection_reason") and outcome != "rejected":
        doc.rejection_reason = ""


def bill_exceeds_its_order(db, doc, entity_type):
    """A bill that came in higher than the order it settles.

    This is exactly the case a spending limit must not wave through: the point
    of agreeing a price beforehand is that somebody looks when it is not met.
    """
    if entity_type != "bill":
        return False
    order_id = getattr(doc, "purchase_order_id", None)
    if not order_id:
        return False
    order = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == order_id).first()
    if not order:
        return False
    return money(doc.total or 0) > money(order.total or 0) + 0.005


def finance_approver_for(db, client_id, exclude_ids):
    """Somebody whose access lets them release payment, for the extra rung on
    a large cost. Returns None when nobody holds that access, in which case the
    chain is simply the reporting line."""
    for emp in db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client_id,
        models.DBEmployee.status == "active",
    ).order_by(models.DBEmployee.id).all():
        if emp.id in exclude_ids:
            continue
        if employee_can(emp, "bills.pay"):
            return emp
    return None


def finish_approval(db, client_id, doc, entity_type, submitted_by, request, actor, reason):
    """Approve without a chain, recording why nobody was asked."""
    doc.approval_status = "approved"
    doc.submitted_by = submitted_by
    doc.current_approval_step = 0
    set_approval_display_status(doc, entity_type, "approved")
    log_audit(db, client_id, f"{entity_type}_auto_approved", entity_type, doc.id,
              getattr(doc, "number", str(doc.id)), reason, request, user_name=actor)
    db.commit()
    return {"ok": True, "status": "approved", "chain": [], "message": reason}


def owner_confirms_own(db, client_id, doc, entity_type, request, actor=""):
    """The owner's own client work order is not waved through: it waits in
    the owner's Approvals as one step, and is placed when the owner signs it -
    a deliberate second look at prices about to be committed to a client."""
    if doc.approval_status == "pending":
        raise HTTPException(status_code=409, detail="Already pending approval")
    if doc.approval_status == "approved":
        raise HTTPException(status_code=409, detail="Already approved")
    db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == entity_type,
        models.DBApprovalChain.entity_id == doc.id).delete()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.add(models.DBApprovalChain(client_id=client_id, entity_type=entity_type, entity_id=doc.id,
                                  employee_id=doc.submitted_by, approver_id=None, level="owner",
                                  step=1, status="pending", created_at=now))
    doc.approval_status = "pending"
    doc.current_approval_step = 1
    set_approval_display_status(doc, entity_type, "pending")
    log_audit(db, client_id, f"{entity_type}_submitted_for_approval", entity_type, doc.id,
              getattr(doc, "number", str(doc.id)), "Raised by the Master - waits for the Master's own sign-off",
              request, user_name=actor)
    db.commit()
    # No bell for it: the owner has just sent it, and it is in their Approvals.
    return {"ok": True, "status": "pending", "chain_length": 1, "next_approver": owner_label(db, client_id),
            "message": "Waiting for your own approval - approve it on the order or in Approvals to place it."}


def start_approval(db, client_id, doc, entity_type, submitted_by, request, actor=""):
    """Put a document into the workflow and return what happened.

    Shared by the owner's console and the employee portal so the two can never
    disagree about what submitting means.
    """
    if doc.approval_status == "pending":
        raise HTTPException(status_code=409, detail="Already pending approval")
    if doc.approval_status == "approved":
        raise HTTPException(status_code=409, detail="Already approved")

    doc.submitted_by = submitted_by
    # A resubmission must not be judged against the previous round's decisions.
    db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == entity_type,
        models.DBApprovalChain.entity_id == doc.id,
    ).delete()

    total = money(getattr(doc, "total", 0) or 0)
    auto_below, finance_above = approval_thresholds(db, client_id)
    over_order = bill_exceeds_its_order(db, doc, entity_type)

    if auto_below and total and total < auto_below and not over_order:
        return finish_approval(
            db, client_id, doc, entity_type, submitted_by, request, actor,
            f"Approved automatically: under the {formatted_money(db, client_id, auto_below)} "
            "sign-off limit.")

    if entity_type == "work_order":
        # A work order climbs the whole hierarchy, as a subcontract order does:
        # the manager set for the raiser, each rank above, then the owner.
        chain = hierarchy_chain(db, client_id, submitted_by, APPROVE_RIGHT["work_order"],
                                getattr(doc, "job_id", None), owner_signs=wo_owner_signs(db, client_id))
        if not chain:
            return owner_confirms_own(db, client_id, doc, entity_type, request, actor)
    else:
        # Bills and purchase orders climb the hierarchy too: the manager set
        # for the raiser, then one approver at each rank above that may
        # approve them. The owner is asked only when nobody on the staff is
        # above - not as a shortcut past the people who are.
        if raised_by_owner(db, client_id, submitted_by):
            return finish_approval(db, client_id, doc, entity_type, submitted_by, request, actor,
                                   "Approved: raised by the Master.")
        chain = hierarchy_chain(db, client_id, submitted_by, APPROVE_RIGHT.get(entity_type, "bills.approve"),
                                getattr(doc, "job_id", None), owner_signs=False)
    if not chain:
        # Nobody set as this person's manager - which is most people, since
        # nobody fills that field in. Rather than wave the paper through, it
        # goes up the departments: the nearest rank above them that may
        # approve this kind of document, and from the top of the staff to the
        # owner. Only the owner raising their own paper needs nobody.
        if raised_by_owner(db, client_id, submitted_by):
            return finish_approval(
                db, client_id, doc, entity_type, submitted_by, request, actor,
                "Approved: raised by the Master.")
        up = ladder_approver(db, client_id, submitted_by, entity_type,
                             getattr(doc, "job_id", None))
        chain = [chain_rung(up)] if up else []

    # A large cost gets an extra rung, if there is anybody who can hold it.
    if finance_above and total >= finance_above:
        already = {step["employee_id"] for step in chain} | {submitted_by}
        purse = finance_approver_for(db, client_id, already)
        if purse:
            # Before the owner's final signature, where the owner signs last.
            if chain and chain[-1]["employee_id"] is None:
                chain.insert(len(chain) - 1, chain_rung(purse))
            else:
                chain.append(chain_rung(purse))

    if not chain:
        # Nobody on the staff above them: the owner signs.
        chain = [chain_rung(None, db, client_id)]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for i, step in enumerate(chain):
        db.add(models.DBApprovalChain(
            client_id=client_id, entity_type=entity_type, entity_id=doc.id,
            employee_id=submitted_by, approver_id=step["employee_id"],
            level=step["level"], step=i + 1, status="pending", created_at=now,
        ))

    doc.approval_status = "pending"
    doc.current_approval_step = 1
    set_approval_display_status(doc, entity_type, "pending")

    notify_employee(db, client_id, chain[0]["employee_id"],
                    "Approval needed",
                    f"{getattr(doc, 'number', 'A document')} is waiting for your approval.",
                    link="/next/approvals")

    log_audit(db, client_id, f"{entity_type}_submitted_for_approval", entity_type, doc.id,
              getattr(doc, "number", str(doc.id)),
              f"Submitted by employee #{submitted_by}, chain length: {len(chain)}"
              + (" (over its purchase order)" if over_order else ""),
              request, user_name=actor)
    db.commit()
    if chain[0]["employee_id"] is None:
        tell_owner_approval(db, client_id, doc, entity_type)
    message = f"Sent to {chain[0]['name']} for approval."
    if over_order:
        message += " This is more than the order it settles, so it needs a look."
    return {"ok": True, "status": "pending", "chain_length": len(chain),
            "next_approver": chain[0]["name"], "over_order": over_order,
            "message": message}


def decide_approval_step(db, step, action, notes, request, client_id, actor=""):
    """Record one approver's decision and move the document on.

    Rejection stops the chain and hands the document back to whoever raised it,
    with the reason attached, so it can be corrected and sent again.
    """
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")
    notes = (notes or "").strip()
    if not notes:
        raise HTTPException(status_code=400, detail="Please say why, so the person who raised it knows.")
    if step.status != "pending":
        raise HTTPException(status_code=409, detail=f"This step was already {step.status}")

    doc = approval_doc(db, step.entity_type, step.entity_id, client_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Approvals are a ladder, not a set. Without this an approver further up
    # could sign off before the people below them had seen it.
    if doc.current_approval_step and step.step != doc.current_approval_step:
        raise HTTPException(
            status_code=409,
            detail=f"This is waiting at step {doc.current_approval_step}, not step {step.step}.",
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    step.status = "approved" if action == "approve" else "rejected"
    step.notes = notes
    step.decided_at = now
    number = getattr(doc, "number", str(doc.id))

    if action == "reject":
        doc.approval_status = "rejected"
        doc.current_approval_step = 0
        set_approval_display_status(doc, step.entity_type, "rejected")
        if hasattr(doc, "rejection_reason"):
            doc.rejection_reason = notes
        # Everyone below this rung is now moot; leaving them pending would put
        # a dead item in their queue forever.
        db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == step.entity_type,
            models.DBApprovalChain.entity_id == step.entity_id,
            models.DBApprovalChain.step > step.step,
            models.DBApprovalChain.status == "pending",
        ).update({"status": "cancelled"}, synchronize_session=False)
        notify_employee(db, client_id, doc.submitted_by, "Sent back to you",
                        f"{number} was not approved: {notes}")
        log_audit(db, client_id, f"{step.entity_type}_rejected", step.entity_type, doc.id,
                  number, f"Rejected at step {step.step}: {notes}", request, user_name=actor)
        db.commit()
        return {"ok": True, "status": "rejected", "reason": notes}

    next_step = db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == step.entity_type,
        models.DBApprovalChain.entity_id == step.entity_id,
        models.DBApprovalChain.step == step.step + 1,
        models.DBApprovalChain.status == "pending",
    ).first()

    if next_step:
        doc.current_approval_step = next_step.step
        notify_employee(db, client_id, next_step.approver_id, "Approval needed",
                        f"{number} is waiting for your approval.", link="/next/approvals")
        log_audit(db, client_id, f"{step.entity_type}_approved_step", step.entity_type,
                  doc.id, number,
                  f"Approved step {step.step}, escalated to step {next_step.step}",
                  request, user_name=actor)
        db.commit()
        if next_step.approver_id is None:
            tell_owner_approval(db, client_id, doc, step.entity_type)
        return {"ok": True, "status": "pending", "next_step": next_step.step}

    doc.approval_status = "approved"
    doc.current_approval_step = 0
    # Approval clears a bill for payment; it does not move the money. Someone in
    # finance still has to pay it, which is the point of the separation.
    set_approval_display_status(doc, step.entity_type, "approved")
    notify_employee(db, client_id, doc.submitted_by, "Approved",
                    f"{number} has been approved"
                    + (" and can be sent to the supplier."
                       if step.entity_type == "purchase_order"
                       else " and is with finance for payment."))
    log_audit(db, client_id, f"{step.entity_type}_fully_approved", step.entity_type,
              doc.id, number, f"Fully approved after step {step.step}", request,
              user_name=actor)
    db.commit()
    return {"ok": True, "status": "approved", "next_step": 0}


def sub_bill_owner_signs(db, client_id):
    return (tenant_setting(db, client_id, SUB_BILL_OWNER_SIGNS_KEY, "1") or "1") != "0"


def holders_of(db, client_id, permission, exclude=()):
    """Every active member of staff whose access includes this right - by
    their department or by what HR ticked for them on top of it, less what
    was withheld. Asked of the person rather than of the preset: a right
    granted to one project manager is as real as one that came with a title."""
    skip = {e for e in (exclude or ()) if e}
    # Anybody who can sign in counts - staff added and never moved off
    # "onboarding" were left off every route, so approvals skipped them.
    return [e for e in db.query(models.DBEmployee).filter(
                models.DBEmployee.client_id == client_id).order_by(models.DBEmployee.id).all()
            if (e.status or "active") not in GONE_STATUSES and e.id not in skip and employee_can(e, permission)]


def raised_by_owner(db, client_id, employee_id):
    """The owner's own staff record - theirs is the last word anyway."""
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == employee_id).first()
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not emp or not client:
        return False
    return ((emp.permission_role or "") == "owner"
            or (emp.email or "").strip().lower() == (client.email or "").strip().lower())


def ladder_approver(db, client_id, submitted_by, entity_type, job_id=None):
    """Who signs when nobody is set as the raiser's manager.

    The holders of the right to approve this kind of paper who rank above the
    person who raised it: somebody on the same site first (anyone not tied to
    particular sites counts as on every site), then the nearest rank, then
    whoever was set up first. None means nobody on the staff is above them,
    and the owner signs.
    """
    right = APPROVE_RIGHT.get(entity_type, "bills.approve")
    me = db.query(models.DBEmployee).filter(models.DBEmployee.id == submitted_by).first()
    mine = role_rank(me) if me else 0
    my_sites = (employee_site_ids(db, me) if me else None) or set()
    if job_id:
        my_sites = set(my_sites) | {job_id}
    best = None
    for emp in holders_of(db, client_id, right, exclude={submitted_by}):
        rank = role_rank(emp)
        if rank <= mine:
            continue
        theirs = employee_site_ids(db, emp)
        same_site = theirs is None or not my_sites or bool(theirs & my_sites)
        key = (0 if same_site else 1, rank, emp.id)
        if best is None or key < best[0]:
            best = (key, emp)
    return best[1] if best else None


def owner_label(db, client_id):
    client = by_id(db, models.DBClient, client_id)
    name = ((client.contact_name or "").strip() or (client.email or "").strip()) if client else ""
    return "%s (Master)" % name if name else "the Master"


def chain_rung(emp, db=None, client_id=None):
    """One step on the chain. No employee means the owner."""
    if emp is None:
        return {"employee_id": None, "level": "owner", "role": "owner",
                "name": owner_label(db, client_id)}
    return {"employee_id": emp.id, "level": emp.level or "",
            "role": emp.role or "employee", "name": employee_name(emp)}


def tell_owner_approval(db, client_id, doc, entity_type):
    kind = {"bill": "Bill", "purchase_order": "Purchase order", "work_order": "Work order",
            "invoice": "Invoice"}.get(entity_type, "A document")
    notify(db, client_id, "approval_needed",
           "%s %s is waiting for your approval" % (kind, getattr(doc, "number", "") or ""),
           "Nobody on the staff ranks above the person who raised it.",
           view="approvals-view", ref_type=entity_type, ref_id=doc.id, severity="action")


def owner_signs_own(db, client_id, doc, entity_type, request, actor):
    """The owner raising paper with no staff record: approved as raised."""
    if doc.approval_status == "pending":
        raise HTTPException(status_code=409, detail="Already pending approval")
    if doc.approval_status == "approved":
        raise HTTPException(status_code=409, detail="Already approved")
    return finish_approval(db, client_id, doc, entity_type, None, request, actor,
                           "Approved: raised by the Master.")


def _party_of(doc):
    for attr in ("vendor_name", "supplier_name", "customer_name", "to_contact", "contact"):
        v = getattr(doc, attr, None)
        if v:
            return v
    return ""


def _person(db, emp_id):
    if not emp_id:
        return ""
    e = by_id(db, models.DBEmployee, emp_id)
    return employee_name(e) if e else ""


def _job_of(db, job_id):
    return by_id(db, models.DBJob, job_id)


def _row(kind, label, id, number, amount, **more):
    row = {"key": "%s:%s" % (kind, id), "kind": kind, "kind_label": label, "id": id,
           "number": number or "", "amount": money(amount or 0), "party": "", "project": "",
           "raised_by": "", "since": "", "what": "", "view": "", "pdf": "",
           "approve_label": "Approve", "reject_label": "Send back",
           "note_to_approve": False, "mine": True, "waiting_on": "", "warnings": []}
    row.update(more)
    return row


def approval_inbox(db, client, emp):
    """Everything waiting on this person to decide - or, for the owner,
    everything waiting on anybody, marked with whose it is."""
    items = []
    can = (lambda p: True) if emp is None else (lambda p: employee_can(emp, p))

    # 1. The reporting-line chain.
    q = db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.client_id == client.id,
        models.DBApprovalChain.status == "pending")
    if emp is not None:
        q = q.filter(models.DBApprovalChain.approver_id == emp.id)
    for s in q.order_by(models.DBApprovalChain.id).all():
        doc = approval_doc(db, s.entity_type, s.entity_id, client.id)
        if not doc or doc.approval_status != "pending" or (doc.current_approval_step or 0) != s.step:
            continue
        label, view = CHAIN_KIND.get(s.entity_type, (s.entity_type, ""))
        total_steps = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == s.entity_type,
            models.DBApprovalChain.entity_id == s.entity_id).count()
        items.append(_row(
            "step", label, s.id, getattr(doc, "number", "") or str(doc.id),
            getattr(doc, "total", None) or getattr(doc, "due", 0) or 0,
            party=_party_of(doc), project=job_label_for(db, getattr(doc, "job_id", None)),
            raised_by=_person(db, s.employee_id), since=s.created_at or "",
            what=((getattr(doc, "notes", "") or "")[:200]
                  + (" - Step %d of %d." % (s.step, total_steps) if total_steps > 1 else "")).strip(" -"),
            view=view, doc_type=s.entity_type, doc_id=doc.id,
            pdf=("/api/purchase-orders/%d/document.pdf" % doc.id) if s.entity_type == "purchase_order" else "",
            note_to_approve=True,
            mine=emp is not None or s.approver_id is None,
            waiting_on=owner_label(db, client.id) if s.approver_id is None else _person(db, s.approver_id),
            warnings=["More than the order it settles"] if bill_exceeds_its_order(db, doc, s.entity_type) else []))

    # 2. Subcontract work orders waiting for approval.
    if can("subcontracts.approve"):
        waiting = db.query(models.DBSubcontractOrder).filter(
            models.DBSubcontractOrder.client_id == client.id,
            models.DBSubcontractOrder.status == "PROVISIONAL").order_by(models.DBSubcontractOrder.id).all()
        prime_chains(db, "subcontract_order", [o.id for o in waiting])
        prime(db, models.DBContractor, [o.contractor_id for o in waiting])
        prime(db, models.DBJob, [o.job_id for o in waiting])
        for o in waiting:
            ensure_wo_chain(db, client, o)
            step = wo_current_step(db, o)
            if emp is not None and (step is None or step.approver_id != emp.id):
                continue
            route = wo_chain_rows(db, o.id)
            con = by_id(db, models.DBContractor, o.contractor_id)
            job = _job_of(db, o.job_id)
            sent = db.query(models.DBSubcontractApproval).filter(
                models.DBSubcontractApproval.order_id == o.id,
                models.DBSubcontractApproval.action == "SUBMIT").order_by(
                models.DBSubcontractApproval.id.desc()).first()
            try:
                over = wo_budget_breaches(db, client, o)
            except Exception:
                over = []
            notes = ["Over the project allocation: " + "; ".join(over)] if over else []
            notes += wo_revision_blockers(db, o)
            if o.supersedes_id:
                prev = db.query(models.DBSubcontractOrder).filter(
                    models.DBSubcontractOrder.id == o.supersedes_id).first()
                n_bills = db.query(models.DBSubBill).filter(
                    models.DBSubBill.order_id == o.supersedes_id,
                    models.DBSubBill.status != "CANCELLED").count()
                n_mb = db.query(models.DBSubMeasurement).filter(
                    models.DBSubMeasurement.order_id == o.supersedes_id).count()
                if prev and (n_bills or n_mb):
                    notes.append("Amends %s - its %d measurement%s and %d RA bill%s move to this order on approval"
                                 % (prev.wo_number, n_mb, "" if n_mb == 1 else "s",
                                    n_bills, "" if n_bills == 1 else "s"))
            items.append(_row(
                "subcontract_order", "Subcontract work order", o.id, o.wo_number, o.net_order_value or o.gross_amount,
                party=(("%s (%s)" % (con.company_name, con.vendor_code) if con.vendor_code else con.company_name) if con else ""),
                project=(("%s %s" % (job.number or "", job.name or "")).strip() if job else ""),
                raised_by=_person(db, o.submitted_by) or (sent.actor_name if sent else ""),
                since=(sent.created_at if sent else o.updated_at) or "",
                what=((o.subject or "")[:200] + (" - Step %d of %d." % (step.step, len(route))
                                                    if step is not None and len(route) > 1 else "")).strip(" -"),
                view="subcontracts-view",
                pdf="/api/wo/orders/%d/document.pdf" % o.id,
                mine=emp is not None or step is None or step.approver_id is None,
                waiting_on=wo_step_name(db, step),
                warnings=notes,
                overrun=bool(over), budget=wo_budget_summary(db, o)))

    # 3. RA bills to the client, waiting to be certified.
    if can("subcontracts.approve"):
        for b in db.query(models.DBRABill).filter(
                models.DBRABill.client_id == client.id,
                models.DBRABill.status == "SUBMITTED").order_by(models.DBRABill.id).all():
            if emp is not None and b.submitted_by == emp.id:
                continue
            job = _job_of(db, b.job_id)
            past = [l.fg_code or "a line" for l in db.query(models.DBRABillLine).filter(
                models.DBRABillLine.ra_bill_id == b.id).all()
                    if money(l.measured_to_date) > money(l.ordered_qty) + 0.0001]
            items.append(_row(
                "ra_bill", "RA bill", b.id, b.number, b.this_bill,
                warnings=(["Claims past the ordered quantity on %s - no variation agreed for it yet"
                           % ", ".join(past[:5])] if past else []),
                party=(job.customer_name if job else "") or "",
                project=(("%s %s" % (job.number or "", job.name or "")).strip() if job else ""),
                raised_by=_person(db, b.submitted_by),
                since=getattr(b, "submitted_at", "") or getattr(b, "updated_at", "") or "",
                what="Work claimed this bill.", view="measurement-view",
                pdf="/api/ra-bills/%d/document.pdf" % b.id, approve_label="Certify"))

    # 4. Subcontractor bills, climbing their route to be certified.
    if can("subcontracts.approve"):
        sent = db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client.id,
            models.DBSubBill.status == "SUBMITTED").order_by(models.DBSubBill.id).all()
        prime_chains(db, "sub_bill", [b.id for b in sent])
        prime(db, models.DBContractor, [b.contractor_id for b in sent])
        prime(db, models.DBJob, [b.job_id for b in sent])
        prime(db, models.DBEmployee, [r.approver_id for b in sent for r in sub_bill_chain_rows(db, b.id)]
              + [b.submitted_by for b in sent])
        for b in sent:
            ensure_sub_bill_chain(db, b)
            step = sub_bill_current_step(db, b)
            if emp is not None and (step is None or step.approver_id != emp.id):
                continue
            route = sub_bill_chain_rows(db, b.id)
            con = by_id(db, models.DBContractor, b.contractor_id)
            job = _job_of(db, b.job_id)
            items.append(_row(
                "sub_bill", "Subcontractor bill", b.id, b.number, b.this_bill,
                party=(("%s (%s)" % (con.company_name, con.vendor_code) if con.vendor_code else con.company_name) if con else ""),
                project=(("%s %s" % (job.number or "", job.name or "")).strip() if job else ""),
                raised_by=getattr(b, "submitted_by_name", "") or "",
                since=getattr(b, "submitted_at", "") or getattr(b, "updated_at", "") or "",
                what=("Net payable %s after deductions." % inr(b.net_payable or 0)) +
                     (" Step %d of %d." % (step.step, len(route)) if step is not None and len(route) > 1 else ""),
                view="subbills-view", pdf="/api/sub-bills/%d/document.pdf" % b.id,
                scan=("/api/sub-bills/%d/hardcopy" % b.id) if b.scan_file_id else "",
                warnings=(["The hard copy says %s of work; this bill claims %s" % (inr(b.scan_amount), inr(b.this_bill))]
                          if b.scan_amount is not None and abs((b.this_bill or 0) - b.scan_amount) > 0.5 else []),
                mine=emp is not None or step is None or step.approver_id is None,
                waiting_on=sub_bill_step_name(db, step),
                approve_label="Certify" if step is None or step.step == len(route) else "Sign and pass on"))

    # 4b. Sub contractors registered on site, waiting to be taken on.
    if can("subcontracts.approve"):
        for c in db.query(models.DBContractor).filter(
                models.DBContractor.client_id == client.id,
                models.DBContractor.registration_status == "PENDING").order_by(models.DBContractor.id).all():
            if emp is not None and c.registered_by == emp.id:
                continue
            items.append(_row(
                "contractor", "Sub contractor registration", c.id, c.vendor_code or c.company_name, 0,
                party=c.company_name or "", project=c.registered_project or "",
                raised_by=c.registered_by_name or "", since=c.created_at or "",
                what=", ".join(x for x in (c.nature_of_work or "", ("PAN " + c.pan) if c.pan else "PAN not given",
                                           ("GST " + c.gst_number) if c.gst_number else "") if x),
                view="vendors-view", pdf="/api/wo/contractors/%d/registration.pdf" % c.id,
                warnings=[w for w in (("No bank account on the form" if not c.bank_account else ""),) if w]))

    # 4b. Variations to the BOQ, climbing their route.
    if can("subcontracts.approve"):
        sent = db.query(models.DBBoqVariation).filter(
            models.DBBoqVariation.client_id == client.id, models.DBBoqVariation.status == "SUBMITTED").order_by(models.DBBoqVariation.id).all()
        prime_chains(db, "boq_variation", [v.id for v in sent])
        for v in sent:
            step = bv_current_step(db, v)
            if emp is not None and (step is None or step.approver_id != emp.id):
                continue
            job = _job_of(db, v.job_id)
            items.append(_row(
                "boq_variation", "BOQ variation", v.id, v.number, v.value,
                party=(job.customer_name if job else "") or "",
                project=(("%s %s" % (job.number or "", job.name or "")).strip() if job else ""),
                raised_by=v.raised_by_name or "", since=v.updated_at or "", what=(v.reason or "")[:200], view="boq-view",
                doc_type="boq_variation", doc_id=v.boq_id,
                mine=emp is not None or step is None or step.approver_id is None,
                waiting_on=sub_bill_step_name(db, step)))

    # 5. Variations waiting to be agreed.
    if can("subcontracts.approve"):
        for v in db.query(models.DBVariationOrder).filter(
                models.DBVariationOrder.client_id == client.id,
                models.DBVariationOrder.status == "SUBMITTED").order_by(models.DBVariationOrder.id).all():
            job = _job_of(db, v.job_id)
            items.append(_row(
                "variation", "Variation", v.id, v.number, v.value,
                party=(job.customer_name if job else "") or "",
                project=(("%s %s" % (job.number or "", job.name or "")).strip() if job else ""),
                raised_by=v.raised_by_name or "", since=getattr(v, "updated_at", "") or "",
                what=(getattr(v, "description", "") or getattr(v, "reason", "") or "")[:200],
                view="measurement-view"))

    # 6. Leave.
    if can("leave.approve"):
        q = db.query(models.DBLeaveRequest).filter(
            models.DBLeaveRequest.client_id == client.id,
            models.DBLeaveRequest.status == "pending")
        if emp is not None:
            q = q.filter(models.DBLeaveRequest.employee_id != emp.id)
            if not employee_can(emp, "people.manage"):
                team = [e.id for e in db.query(models.DBEmployee.id).filter(
                    models.DBEmployee.client_id == client.id,
                    models.DBEmployee.reports_to == emp.id).all()]
                q = q.filter(models.DBLeaveRequest.employee_id.in_(team or [0]))
        for lv in q.order_by(models.DBLeaveRequest.id).all():
            who = _person(db, lv.employee_id)
            items.append(_row(
                "leave", "Leave", lv.id, "Leave", 0, party=who, raised_by=who,
                since=lv.created_at or "",
                what="%s leave, %s to %s (%g day%s)%s" % (
                    (lv.leave_type or "").title(), lv.start_date, lv.end_date, lv.days or 0,
                    "" if (lv.days or 0) == 1 else "s", (": " + lv.reason) if lv.reason else ""),
                view="leave-view"))

    items.sort(key=lambda r: (not r["mine"], r["since"] or ""))
    return items


def wo_owner_signs(db, client_id):
    return (tenant_setting(db, client_id, WO_OWNER_SIGNS_KEY, "1") or "1") != "0"


def hierarchy_chain(db, client_id, submitter_id, right, job_id=None, owner_signs=True):
    """The approvers a work order passes through, lowest rank first."""
    me = db.query(models.DBEmployee).filter(models.DBEmployee.id == submitter_id).first() \
        if submitter_id else None
    chain, seen = [], {submitter_id} if submitter_id else set()
    if me:
        for rung in build_approval_chain(me.id, client_id, db):
            boss = db.query(models.DBEmployee).filter(models.DBEmployee.id == rung["employee_id"]).first()
            if boss and boss.id not in seen and employee_can(boss, right):
                chain.append(boss)
                seen.add(boss.id)
    floor = max([role_rank(me) if me else 0] + [role_rank(e) for e in chain])
    sites = (employee_site_ids(db, me) if me else None) or set()
    if job_id:
        sites = set(sites) | {job_id}
    by_rank = {}
    for emp in holders_of(db, client_id, right, exclude=seen):
        rank = role_rank(emp)
        if rank <= floor:
            continue
        theirs = employee_site_ids(db, emp)
        same = theirs is None or not sites or bool(theirs & sites)
        key = (0 if same else 1, emp.id)
        if rank not in by_rank or key < by_rank[rank][0]:
            by_rank[rank] = (key, emp)
    chain += [by_rank[r][1] for r in sorted(by_rank)]
    rungs = [chain_rung(e) for e in chain]
    if owner_signs and not (submitter_id and raised_by_owner(db, client_id, submitter_id)):
        rungs.append(chain_rung(None, db, client_id))
    return rungs


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.core.notifications import notify, notify_employee
from app.services.boq import bv_current_step
from app.services.hr import employee_name, employee_site_ids
from app.services.projects import job_label_for
from app.services.subcontract_billing import (
    ensure_sub_bill_chain,
    sub_bill_chain_rows,
    sub_bill_current_step,
    sub_bill_step_name,
)
from app.services.subcontract_orders import (
    ensure_wo_chain,
    wo_budget_breaches,
    wo_budget_summary,
    wo_chain_rows,
    wo_current_step,
    wo_revision_blockers,
    wo_step_name,
)
