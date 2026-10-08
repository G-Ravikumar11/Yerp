"""The approvals endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.approvals import (
    APPROVAL_MODELS,
    AUTO_BELOW_KEY,
    CHAIN_KIND,
    FINANCE_ABOVE_KEY,
    SUB_BILL_OWNER_SIGNS_KEY,
    WO_OWNER_SIGNS_KEY,
)
from app.core.audit import log_audit
from app.core.auth import get_client_user, session_person
from app.core.currency import DEFAULT_CURRENCY, money
from app.core.permissions import PERMISSION_ROLES, employee_can, role_rank
from app.core.tenant_settings import put_setting
from app.routers.boq import act_on_boq_variation
from app.routers.client_billing import act_on_variation
from app.routers.subcontract_billing import act_on_sub_bill
from app.routers.subcontract_orders import decide_contractor_registration, wo_approve, wo_reject
from app.schemas.approvals import ApprovalDecisionIn
from app.schemas.client_billing import RAActionIn
from app.schemas.subcontract_orders import WoActionIn
from app.services.approvals import (
    _party_of,
    _person,
    approval_doc,
    approval_inbox,
    approval_thresholds,
    decide_approval_step,
    finance_approver_for,
    get_approval_chain_history,
    holders_of,
    owner_label,
    owner_signs_own,
    start_approval,
    sub_bill_owner_signs,
    wo_owner_signs,
)
from app.services.client_billing import _ra_action
from app.services.employee_portal import decide_leave
from app.services.hr import employee_name
from app.services.subcontract_orders import wo_waiting_names


router = APIRouter()


@router.post("/api/approvals/submit")
def submit_for_approval(body: dict, request: Request, db: Session = Depends(get_db)):
    """Submit an invoice or bill for hierarchical approval."""
    client = get_client_user(request, db)
    entity_type = body.get("entity_type", "")
    entity_id = body.get("entity_id")
    submitted_by = body.get("submitted_by")  # employee_id of who submitted

    if entity_type not in ("invoice", "bill"):
        raise HTTPException(status_code=400, detail="entity_type must be 'invoice' or 'bill'")
    if not entity_id:
        raise HTTPException(status_code=400, detail="entity_id is required")

    doc = approval_doc(db, entity_type, entity_id, client.id)
    if not doc:
        raise HTTPException(status_code=404,
                            detail="Invoice not found" if entity_type == "invoice" else "Bill not found")

    # If no employee specified, try to find one matching the client email
    if not submitted_by:
        emp = db.query(models.DBEmployee).filter(
            models.DBEmployee.client_id == client.id,
            models.DBEmployee.email == client.email
        ).first()
        if emp:
            submitted_by = emp.id

    if not submitted_by:
        return owner_signs_own(db, client.id, doc, entity_type, request,
                               client.contact_name or client.email)

    return start_approval(db, client.id, doc, entity_type, submitted_by, request,
                          actor=client.contact_name or client.email)


@router.get("/api/approvals/pending")
def get_pending_approvals(request: Request, db: Session = Depends(get_db)):
    """Get all documents pending approval by the current user's employees."""
    client = get_client_user(request, db)

    # Find all employees belonging to this client
    employee_ids = [e.id for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        models.DBEmployee.status == "active"
    ).all()]

    # Every pending step: those addressed to staff, and those addressed to
    # the owner, which carry no employee at all.
    steps = db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.client_id == client.id,
        models.DBApprovalChain.status == "pending",
    ).all()

    result = []
    for s in steps:
        # Every kind of document on the chain, not only invoices and bills -
        # this read orders and work orders as bills, and so lost them.
        doc = approval_doc(db, s.entity_type, s.entity_id, client.id)
        if not doc or doc.approval_status != "pending" or \
                (doc.current_approval_step or 0) != s.step:
            continue

        approver = db.query(models.DBEmployee).filter(models.DBEmployee.id == s.approver_id).first()
        submitter = db.query(models.DBEmployee).filter(models.DBEmployee.id == s.employee_id).first()

        # Get total chain length
        total_steps = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == s.entity_type,
            models.DBApprovalChain.entity_id == s.entity_id,
        ).count()

        approved_steps = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == s.entity_type,
            models.DBApprovalChain.entity_id == s.entity_id,
            models.DBApprovalChain.status == "approved",
        ).count()

        doc_number = getattr(doc, 'number', str(doc.id))
        doc_total = getattr(doc, 'total', 0) or getattr(doc, 'amount', 0) or 0

        result.append({
            "step_id": s.id,
            "entity_type": s.entity_type,
            "entity_id": s.entity_id,
            "entity_number": doc_number,
            "entity_total": doc_total,
            "entity_status": doc.status,
            "step": s.step,
            "total_steps": total_steps,
            "approved_steps": approved_steps,
            "approver_name": f"{approver.first_name} {approver.last_name}".strip() if approver
                             else ("Master" if s.approver_id is None else "Unknown"),
            "approver_level": s.level,
            "submitter_name": f"{submitter.first_name} {submitter.last_name}".strip() if submitter else "Unknown",
            "created_at": s.created_at,
        })

    return {"pending": result}


@router.get("/api/approvals/my-submissions")
def get_my_submissions(request: Request, db: Session = Depends(get_db)):
    """Get all documents the current user's employees have submitted for approval."""
    client = get_client_user(request, db)

    employee_ids = [e.id for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        models.DBEmployee.status == "active"
    ).all()]

    if not employee_ids:
        return {"submissions": []}

    # Find documents submitted by these employees
    invoices = db.query(models.DBInvoice).filter(
        models.DBInvoice.client_id == client.id,
        models.DBInvoice.submitted_by.in_(employee_ids),
        models.DBInvoice.approval_status.in_(["pending", "approved", "rejected"]),
    ).order_by(models.DBInvoice.id.desc()).limit(100).all()

    bills = db.query(models.DBBill).filter(
        models.DBBill.client_id == client.id,
        models.DBBill.submitted_by.in_(employee_ids),
        models.DBBill.approval_status.in_(["pending", "approved", "rejected"]),
    ).order_by(models.DBBill.id.desc()).limit(100).all()

    result = []
    for doc in invoices:
        submitter = db.query(models.DBEmployee).filter(models.DBEmployee.id == doc.submitted_by).first()
        total_steps = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == "invoice",
            models.DBApprovalChain.entity_id == doc.id,
        ).count()
        approved_steps = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == "invoice",
            models.DBApprovalChain.entity_id == doc.id,
            models.DBApprovalChain.status == "approved",
        ).count()
        result.append({
            "entity_type": "invoice",
            "entity_id": doc.id,
            "entity_number": doc.number,
            "entity_total": doc.due or 0,
            "approval_status": doc.approval_status or "none",
            "status": doc.status,
            "current_step": doc.current_approval_step or 0,
            "total_steps": total_steps,
            "approved_steps": approved_steps,
            "submitter_name": f"{submitter.first_name} {submitter.last_name}".strip() if submitter else "Unknown",
        })

    for doc in bills:
        submitter = db.query(models.DBEmployee).filter(models.DBEmployee.id == doc.submitted_by).first()
        total_steps = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == "bill",
            models.DBApprovalChain.entity_id == doc.id,
        ).count()
        approved_steps = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == "bill",
            models.DBApprovalChain.entity_id == doc.id,
            models.DBApprovalChain.status == "approved",
        ).count()
        result.append({
            "entity_type": "bill",
            "entity_id": doc.id,
            "entity_number": doc.number,
            "entity_total": doc.total or 0,
            "approval_status": doc.approval_status or "none",
            "status": doc.status,
            "current_step": doc.current_approval_step or 0,
            "total_steps": total_steps,
            "approved_steps": approved_steps,
            "submitter_name": f"{submitter.first_name} {submitter.last_name}".strip() if submitter else "Unknown",
        })

    return {"submissions": result}


@router.get("/api/approvals/history/{entity_type}/{entity_id}")
def get_approval_history(entity_type: str, entity_id: int, request: Request, db: Session = Depends(get_db)):
    """Get the full approval chain history for a document."""
    client = get_client_user(request, db)
    chain = get_approval_chain_history(entity_type, entity_id, db)
    return {"history": chain}


@router.post("/api/approvals/{step_id}/action")
def approval_action(step_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    """Approve or reject a pending step, as the business owner.

    The owner can act on any step in their own tenancy; staff go through
    /api/employee/approvals/{step_id}/action, which only lets somebody decide
    the steps addressed to them.
    """
    client = get_client_user(request, db)
    step = db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.id == step_id,
        models.DBApprovalChain.client_id == client.id,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Approval step not found")
    return decide_approval_step(db, step, body.get("action", ""), body.get("notes", ""),
                                request, client.id,
                                actor=client.contact_name or client.email)


@router.get("/api/approval-rules")
def get_approval_rules(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    auto_below, finance_above = approval_thresholds(db, client.id)
    purse = finance_approver_for(db, client.id, set())
    return {
        "auto_below": auto_below,
        "finance_above": finance_above,
        "owner_signs_work_orders": wo_owner_signs(db, client.id),
        "owner_signs_sub_bills": sub_bill_owner_signs(db, client.id),
        "currency": client.currency or DEFAULT_CURRENCY,
        # Naming who would be added makes the rule checkable rather than
        # something that quietly does nothing because nobody holds the access.
        "finance_approver": employee_name(purse),
        "has_finance_approver": bool(purse),
    }


@router.put("/api/approval-rules")
def set_approval_rules(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Two numbers: what is too small to bother anybody with, and what is too
    large for one manager alone."""
    client = get_client_user(request, db)
    body = body or {}

    def clean(key, label):
        raw = body.get(key, None)
        if raw in (None, ""):
            return 0.0
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{label} must be a number")
        if value < 0:
            raise HTTPException(status_code=400, detail=f"{label} cannot be negative")
        if value > 100_000_000:
            raise HTTPException(status_code=400, detail=f"{label} is unrealistically large")
        return money(value)

    auto_below = clean("auto_below", "The sign-off limit")
    finance_above = clean("finance_above", "The finance limit")
    if auto_below and finance_above and finance_above <= auto_below:
        raise HTTPException(
            status_code=400,
            detail="The finance limit has to be above the sign-off limit, or every "
                   "cost would be caught by both rules at once.")

    if "owner_signs_work_orders" in body:
        put_setting(db, client.id, WO_OWNER_SIGNS_KEY, "1" if body.get("owner_signs_work_orders") else "0")
    if "owner_signs_sub_bills" in body:
        put_setting(db, client.id, SUB_BILL_OWNER_SIGNS_KEY, "1" if body.get("owner_signs_sub_bills") else "0")
    for key, value in ((AUTO_BELOW_KEY, auto_below), (FINANCE_ABOVE_KEY, finance_above)):
        setting = db.query(models.DBSettings).filter(
            models.DBSettings.client_id == client.id,
            models.DBSettings.key == key,
        ).first()
        if setting:
            setting.value = str(value)
        else:
            db.add(models.DBSettings(client_id=client.id, key=key, value=str(value),
                                     description="Approval threshold"))
    log_audit(db, client.id, "approval_rules_changed", "settings", None, "approval rules",
              f"Auto-approve below {auto_below}, finance above {finance_above}", request)
    db.commit()
    return {"auto_below": auto_below, "finance_above": finance_above,
            "message": "Approval rules saved"}


@router.get("/api/approvals/inbox")
def approvals_inbox(request: Request, db: Session = Depends(get_db)):
    client, emp = session_person(request, db)
    items = approval_inbox(db, client, emp)
    return {"items": items, "mine": len([i for i in items if i["mine"]]), "count": len(items),
            "owner": emp is None}


@router.post("/api/approvals/decide")
def approvals_decide(body: ApprovalDecisionIn, request: Request, db: Session = Depends(get_db)):
    """One door for every decision in the inbox. Each kind goes through its
    own route's rules, so deciding here and deciding on the document's own
    screen can never disagree."""
    client, emp = session_person(request, db)
    decision = (body.decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "Approve or send back?")
    note = (body.note or "").strip()
    if decision == "reject" and not note:
        raise HTTPException(400, "Say why it is going back, so it can be put right.")
    kind = body.kind

    if kind == "step":
        step = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.id == body.id,
            models.DBApprovalChain.client_id == client.id).first()
        if not step:
            raise HTTPException(404, "Approval step not found")
        if emp is not None and step.approver_id != emp.id:
            raise HTTPException(403, "This approval is addressed to somebody else")
        actor = employee_name(emp) if emp else (client.contact_name or client.email)
        return decide_approval_step(db, step, decision, note, request, client.id, actor=actor)
    if kind == "subcontract_order":
        args = WoActionIn(comments=note, override=bool(body.override))
        return (wo_approve if decision == "approve" else wo_reject)(body.id, args, request, db)
    if kind == "ra_bill":
        return _ra_action(body.id, "CERTIFY" if decision == "approve" else "REJECT",
                          RAActionIn(comments=note), request, db, "subcontracts.approve")
    if kind == "sub_bill":
        return act_on_sub_bill(body.id, "certify" if decision == "approve" else "reject",
                               request, {"comments": note}, db)
    if kind == "contractor":
        return decide_contractor_registration(body.id, "approve" if decision == "approve" else "reject",
                                              request, {"comments": note}, db)
    if kind == "boq_variation":
        return act_on_boq_variation(body.id, "approve" if decision == "approve" else "reject", request, {"comments": note}, db)
    if kind == "variation":
        return act_on_variation(body.id, decision, request, {"comments": note}, db)
    if kind == "leave":
        leave = db.query(models.DBLeaveRequest).filter(
            models.DBLeaveRequest.id == body.id,
            models.DBLeaveRequest.client_id == client.id).first()
        if not leave:
            raise HTTPException(404, "Leave request not found")
        if emp is not None:
            if not employee_can(emp, "leave.approve"):
                raise HTTPException(403, "Your access does not include approving leave.")
            if leave.employee_id == emp.id:
                raise HTTPException(403, "Your own leave is approved by somebody else.")
            if not employee_can(emp, "people.manage"):
                them = db.query(models.DBEmployee).filter(models.DBEmployee.id == leave.employee_id).first()
                if not them or them.reports_to != emp.id:
                    raise HTTPException(403, "Only their own manager or HR decides this leave.")
        who = employee_name(emp) if emp else (client.contact_name or "Master")
        return decide_leave(db, client.id, leave, decision, who, request)
    raise HTTPException(400, "Unknown kind of approval")


@router.get("/api/approvals/sent")
def approvals_sent(request: Request, db: Session = Depends(get_db)):
    """What this person has sent for approval and where each one is - or,
    for the owner, everything the staff have in flight."""
    client, emp = session_person(request, db)
    rows = []
    for entity_type, model in APPROVAL_MODELS.items():
        q = db.query(model).filter(model.client_id == client.id,
                                   model.approval_status.in_(["pending", "approved", "rejected"]))
        if emp is not None:
            q = q.filter(model.submitted_by == emp.id)
        else:
            q = q.filter(model.submitted_by.isnot(None))
        for doc in q.order_by(model.id.desc()).limit(60).all():
            label, view = CHAIN_KIND.get(entity_type, (entity_type, ""))
            waiting = ""
            if doc.approval_status == "pending":
                step = db.query(models.DBApprovalChain).filter(
                    models.DBApprovalChain.entity_type == entity_type,
                    models.DBApprovalChain.entity_id == doc.id,
                    models.DBApprovalChain.step == (doc.current_approval_step or 0)).first()
                if step:
                    waiting = owner_label(db, client.id) if step.approver_id is None \
                        else _person(db, step.approver_id)
            rows.append({"kind_label": label, "number": getattr(doc, "number", "") or str(doc.id),
                         "party": _party_of(doc), "amount": money(getattr(doc, "total", None) or getattr(doc, "due", 0) or 0),
                         "status": doc.approval_status, "waiting_on": waiting,
                         "raised_by": _person(db, doc.submitted_by),
                         "reason": getattr(doc, "rejection_reason", "") or "",
                         "view": view, "when": getattr(doc, "updated_at", "") or getattr(doc, "created_at", "") or ""})
    q = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.client_id == client.id,
        models.DBSubcontractOrder.submitted_by.isnot(None),
        models.DBSubcontractOrder.status.in_(["PROVISIONAL", "APPROVED", "EXECUTED", "DRAFT"]))
    if emp is not None:
        q = q.filter(models.DBSubcontractOrder.submitted_by == emp.id)
    for o in q.order_by(models.DBSubcontractOrder.id.desc()).limit(60).all():
        if o.status == "DRAFT" and not (o.rejection_reason or ""):
            continue
        con = db.query(models.DBContractor).filter(models.DBContractor.id == o.contractor_id).first() \
            if o.contractor_id else None
        status = {"PROVISIONAL": "pending", "DRAFT": "rejected"}.get(o.status, "approved")
        rows.append({"kind_label": "Subcontract work order", "number": o.wo_number or "", "party": con.company_name if con else "",
                     "amount": money(o.net_order_value or o.gross_amount or 0), "status": status,
                     "waiting_on": ", ".join(wo_waiting_names(db, client, o)) if status == "pending" else "",
                     "raised_by": _person(db, o.submitted_by), "reason": o.rejection_reason or "",
                     "view": "subcontracts-view", "when": o.updated_at or o.created_at or ""})
    rows.sort(key=lambda r: (r["status"] != "pending", "" if not r["when"] else r["when"]), reverse=False)
    pending = [r for r in rows if r["status"] == "pending"]
    done = sorted([r for r in rows if r["status"] != "pending"], key=lambda r: r["when"] or "", reverse=True)
    return {"items": pending + done[:60]}


@router.get("/api/approvals/who-approves")
def approvals_who(request: Request, db: Session = Depends(get_db)):
    """The routing, spelled out: who each kind of paper goes to when its
    raiser has no manager set. For the owner to check the set-up against."""
    client = get_client_user(request, db)
    out = []
    for right, label in (("subcontracts.approve", "Client and subcontract work orders, RA bills, subcontractor bills and variations"),
                         ("bills.approve", "Bills and purchase orders"),
                         ("bills.pay", "Paying approved bills"),
                         ("leave.approve", "Leave")):
        out.append({"right": right, "what": label,
                    "people": [{"name": employee_name(e),
                                "department": next((r["label"] for r in PERMISSION_ROLES
                                                    if r["code"] == (e.permission_role or "staff")), ""),
                                "rank": role_rank(e)}
                               for e in holders_of(db, client.id, right)]})
    return {"routes": out, "owner": owner_label(db, client.id)}
