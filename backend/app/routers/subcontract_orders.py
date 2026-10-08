"""The subcontract orders endpoints."""
import base64
import io
import json
import os
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func as sqlfunc, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.validators import import_guard
from app import models
from app.documents import sheet_forms
from app.db import get_db

from app.constants.approvals import GONE_STATUSES
from app.constants.boq import BOQ_HEADER_ALIASES, BOQ_PRICED
from app.constants.subcontract_orders import (
    REGISTRATION_DOCUMENTS,
    WIPE_PHRASE,
    WO_CLAUSE_CATEGORIES,
    WO_EDITABLE,
    WO_TRANSITIONS,
)
from app.core.audit import log_audit
from app.core.auth import (
    STAFF_VIEWER,
    get_client_user,
    require_erp_read,
    require_items_access,
    require_owner,
    wo_actor,
)
from app.core.config import logger
from app.core.currency import format_money_plain, inr, money, sheet_number, unit_rate
from app.core.dates import financial_year_label
from app.core.files import file_counts, file_headers, image_data_url, served_type
from app.core.gst import state_from_gstin
from app.core.notifications import notify, notify_employee
from app.core.queries import prime
from app.core.serials import next_wo_number
from app.core.sheets import (
    map_headers_with,
    mapping_report,
    read_sheet_rows,
    rows_from,
    sheet_note,
    sheet_response,
)
from app.core.tenant_settings import put_setting
from app.core.units import UNITS_OF_MEASURE
from app.documents.forms import (
    WO_STANDARD_TERMS,
    form_pdf_response,
    registration_form_spec,
    wo_document_payload,
    wo_form_spec,
)
from app.documents.letterhead import company_terms, fill_terms, letterhead
from app.routers.client_orders import erp_delete_work_order
from app.schemas.subcontract_orders import (
    BoqIn,
    BusinessUnitIn,
    ChargeBudgetIn,
    ContractorIn,
    ProjectBudgetIn,
    TermsIn,
    WoActionIn,
    WorkOrderHeadIn,
    WorkTypeIn,
)
from app.services.approvals import owner_label, raised_by_owner
from app.services.boq import boq_given_to_gangs, boq_over_allotments
from app.services.crm import norm_name
from app.services.subcontract_orders import (
    _vendor_or_404,
    _vendor_report,
    budget_breaks_vendor_limit,
    cascade_delete_referrers,
    contractor_dict,
    contractor_form_fields,
    contractor_or_404,
    ensure_company_unit,
    may_administer,
    next_vendor_code,
    prime_wo_item_counts,
    record_wo_action,
    recost_order,
    registration_form_data,
    run_bulk_delete,
    seed_work_types,
    wo_apply,
    wo_billing_cycle,
    wo_budget_rows,
    wo_chain_rows,
    wo_changes,
    wo_committed_by_budget,
    wo_copy_lines,
    wo_decide_step,
    wo_delete_order_now,
    wo_delete_report,
    wo_department_choices,
    wo_dict,
    wo_involved_ids,
    wo_matches,
    wo_or_404,
    wo_percent,
    wo_snapshot,
    wo_step_name,
    wo_valid_budget_id,
    work_type_dict,
)
from app.validators.common import clean_rich_text, clean_tax_ids


router = APIRouter()


@router.get("/api/wo/orders/{order_id}/access")
def wo_access_get(order_id: int, request: Request, db: Session = Depends(get_db)):
    """Who may see this order besides the owner: the one who made it, those who sign it, and whoever
    was let in. The owner and the maker choose the last."""
    client = require_erp_read(request, db)
    order = wo_or_404(db, client.id, order_id)
    viewer = STAFF_VIEWER.get()
    if viewer and order.submitted_by != viewer:
        raise HTTPException(403, "Only the Master, or whoever made the order, decides who sees it.")
    shared = {r[0] for r in db.query(models.DBOrderAccess.employee_id).filter(models.DBOrderAccess.order_id == order.id).all()}
    route = {r.approver_id for r in wo_chain_rows(db, order.id) if r.approver_id}
    people = []
    for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id).order_by(models.DBEmployee.first_name).all():
        if (e.status or "active") in GONE_STATUSES or e.id == order.submitted_by:
            continue
        people.append({"id": e.id, "name": ("%s %s" % (e.first_name or "", e.last_name or "")).strip(),
                       "department": getattr(e, "department", "") or "", "shared": e.id in shared, "on_route": e.id in route})
    return {"people": people}


@router.put("/api/wo/orders/{order_id}/access")
def wo_access_put(order_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    order = wo_or_404(db, client.id, order_id)
    viewer = STAFF_VIEWER.get()
    if viewer and order.submitted_by != viewer:
        raise HTTPException(403, "Only the Master, or whoever made the order, decides who sees it.")
    want = {int(i) for i in (body.get("employee_ids") or []) if str(i).isdigit() or isinstance(i, int)}
    valid = {r[0] for r in db.query(models.DBEmployee.id).filter(models.DBEmployee.client_id == client.id, models.DBEmployee.id.in_(list(want) or [0])).all()}
    db.query(models.DBOrderAccess).filter(models.DBOrderAccess.order_id == order.id).delete(synchronize_session=False)
    for emp_id in sorted(valid):
        db.add(models.DBOrderAccess(client_id=client.id, order_id=order.id, employee_id=emp_id))
    log_audit(db, client.id, "subcontract_shared", "subcontract_order", order.id, order.wo_number or "",
              "%d people" % len(valid), request)
    db.commit()
    return {"ok": True, "message": "%s is shared with %d %s." % (order.wo_number, len(valid), "person" if len(valid) == 1 else "people")}


@router.get("/api/wo/orders/{order_id}/document")
def wo_document(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return wo_document_payload(db, client, wo_or_404(db, client.id, order_id))


@router.get("/api/wo/orders/{order_id}/document.pdf")
def wo_document_pdf(order_id: int, request: Request, db: Session = Depends(get_db)):
    """The order as the document that gets signed.

    Rendered on the server rather than in the browser: this copy is attached
    to bills and produced in disputes, so what it looks like must not depend
    on which machine printed it or what was installed on it.
    """
    client = require_erp_read(request, db)
    order = wo_or_404(db, client.id, order_id)
    # The trade's ruled form is the default; the letter-style layout it
    # replaced stays one parameter away for anybody who preferred it.
    if request.query_params.get("style") != "letter":
        return form_pdf_response(wo_form_spec(db, client, order), order.wo_number or "work_order")
    doc = wo_document_payload(db, client, order)

    from app.documents import wo_pdf
    if not wo_pdf.PDF_AVAILABLE:
        raise HTTPException(
            503, "The PDF library is not installed on this server, so the "
                 "order cannot be produced as a PDF. The schedule is still "
                 "available as a workbook.")
    pdf = wo_pdf.build_work_order_pdf(doc)
    name = re.sub(r"[^A-Za-z0-9]+", "_", doc["wo_number"] or "work_order")
    # Streamed with its length declared, so a two-hundred-line schedule shows
    # a real progress bar on a site connection instead of an empty tab.
    return StreamingResponse(
        io.BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="%s.pdf"' % name,
                 "Content-Length": str(len(pdf))})


@router.get("/api/wo/orders/{order_id}/boq.xlsx")
def wo_boq_xlsx(order_id: int, request: Request, db: Session = Depends(get_db)):
    """The schedule as a workbook, which is where it gets checked."""
    client = require_erp_read(request, db)
    order = wo_or_404(db, client.id, order_id)
    doc = wo_dict(db, order, detail=True)
    doc["company"] = client.company_name or ""

    rows = [[i["activity_no"], i["item_code"], i["item_description"], i["uom"],
             i["quantity"], i["unit_rate"], i["total_amount"]] for i in doc["items"]]
    preamble = [
        ["Work Order", "", "", "", "", "", doc["company"]],
        ["No: " + doc["wo_number"] + ("  (" + doc["status"] + ")")],
        ["Contractor: " + doc["contractor"]],
        ["Project: " + doc["project"]],
        ["Subject: " + doc["subject"]],
        [],
    ]
    closing = [
        [],
        ["", "", "", "", "", "Gross", doc["gross_amount"]],
        ["", "", "", "", "", "GST @ %s%%" % doc["gst_rate"], doc["gst_amount"]],
        ["", "", "", "", "", "TDS @ %s%%" % doc["tds_rate"], -doc["tds_amount"]],
        ["", "", "", "", "", "Net order value", doc["net_order_value"]],
    ]
    return sheet_response(
        ["Activity", "Item Code", "Description", "UOM", "Quantity", "Rate", "Amount"],
        rows, "work_order_%s.xlsx" % re.sub(r"[^A-Za-z0-9]+", "_", doc["wo_number"]),
        preamble=preamble, closing=closing)


@router.get("/api/wo/business-units")
def wo_list_business_units(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    ensure_company_unit(db, client)
    rows = db.query(models.DBBusinessUnit).filter(
        models.DBBusinessUnit.client_id == client.id).order_by(
            models.DBBusinessUnit.name).all()
    return {"business_units": [
        {"id": b.id, "name": b.name or "", "code": b.code or "",
         "gstin": b.gstin or "", "pan": b.pan or "", "address": b.address or "",
         "logo_url": b.logo_url or ""}
        for b in rows]}


@router.post("/api/wo/business-units")
def wo_create_business_unit(body: BusinessUnitIn, request: Request,
                            db: Session = Depends(get_db)):
    client = require_items_access(request, db, "workorders.manage")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "The business unit needs a name")
    unit = models.DBBusinessUnit(
        client_id=client.id, name=name, code=(body.code or "").strip().upper(),
        gstin=(body.gstin or "").strip().upper(), pan=(body.pan or "").strip().upper(),
        address=(body.address or "").strip(),
        logo_url=(body.logo_url or "").strip())
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return {"id": unit.id, "name": unit.name, "message": name + " added."}


@router.get("/api/wo/contractors/{con_id}/documents/{key}")
def wo_contractor_document(con_id: int, key: str, request: Request, db: Session = Depends(get_db)):
    """One of the registration form's uploaded documents, as the file it was given."""
    client = require_erp_read(request, db)
    con = db.query(models.DBContractor).filter(models.DBContractor.id == con_id,
                                                models.DBContractor.client_id == client.id).first()
    if not con:
        raise HTTPException(404, "Contractor not found")
    try:
        files = json.loads(con.document_files or "{}")
    except Exception:
        files = {}
    entry = files.get(key)
    if not entry or not entry.get("data"):
        raise HTTPException(404, "No file has been uploaded for that document.")
    m = re.match(r"^data:([^;]+);base64,(.+)$", entry["data"], re.DOTALL)
    if not m:
        raise HTTPException(500, "That file could not be read back.")
    media, raw = served_type(m.group(1)), base64.b64decode(m.group(2))
    name = re.sub(r'[^A-Za-z0-9._ -]', "_", entry.get("name") or (key + ".bin"))
    return StreamingResponse(io.BytesIO(raw), media_type=media,
        headers=dict(file_headers(media), **{
            "Content-Disposition": '%s; filename="%s"' % ("inline" if media != "application/octet-stream" else "attachment", name)}))


@router.get("/api/wo/contractors")
def wo_list_contractors(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    query = db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id)
    if q:
        query = query.filter(or_(
            models.DBContractor.company_name.ilike("%" + q + "%"),
            models.DBContractor.vendor_code.ilike("%" + q + "%"),
            models.DBContractor.nature_of_work.ilike("%" + q + "%"),
            models.DBContractor.gst_number.ilike("%" + q + "%")))
    every = query.order_by(models.DBContractor.company_name).limit(2000).all()
    # The counts are of everybody, so each status tab shows its number
    # whichever tab is open.
    rows = [c for c in every if not status or (c.registration_status or "APPROVED") == status.upper()]
    return {"contractors": [contractor_dict(c) for c in rows],
            "summary": {"registered": len([c for c in every if (c.registration_status or "APPROVED") == "APPROVED"]),
                        "pending": len([c for c in every if c.registration_status == "PENDING"]),
                        "sent_back": len([c for c in every if c.registration_status == "REJECTED"])}}


@router.post("/api/wo/contractors")
def wo_create_contractor(body: ContractorIn, request: Request,
                         db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, ("workorders.manage", "billing.manage"))
    name = (body.company_name or "").strip()
    if not name:
        raise HTTPException(400, "The contractor needs a company name")
    clash = db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id,
        sqlfunc.lower(models.DBContractor.company_name) == name.lower()).first()
    if clash:
        raise HTTPException(409, "'" + name + "' is already on the contractor list")

    code = (body.vendor_code or "").strip().upper()
    if code and db.query(models.DBContractor).filter(
            models.DBContractor.client_id == client.id,
            sqlfunc.upper(models.DBContractor.vendor_code) == code).first():
        raise HTTPException(409, "Vendor code %s is already taken." % code)
    code = code or next_vendor_code(db, client.id)
    # The same checks an edit makes: a PAN or GSTIN typed wrong at
    # registration went straight onto work orders, bills and the TDS return.
    gstin, pan = clean_tax_ids(body.gst_number, body.pan)
    ifsc = (body.bank_ifsc or "").strip().upper()
    if ifsc and not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc):
        raise HTTPException(400, "An IFSC is eleven characters: four letters, a zero, then six (for example SBIN0001234).")

    # Registered by the owner, it is signed off as it is made. Registered by
    # somebody on site, it waits for someone with the right to approve it.
    owner = actor_id is None or raised_by_owner(db, client.id, actor_id)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = models.DBContractor(
        client_id=client.id, company_name=name, vendor_code=code,
        contact_person=(body.contact_person or "").strip(),
        email=(body.email or "").strip(), phone_number=(body.phone_number or "").strip(),
        pan=pan, gst_number=gstin,
        bank_name=(body.bank_name or "").strip(),
        bank_account=re.sub(r"\s", "", body.bank_account or ""),
        bank_ifsc=ifsc,
        address=(body.address or "").strip(),
        registration_status="APPROVED" if owner else "PENDING",
        registered_by=actor_id, registered_by_name=actor_name,
        approved_by_name=(owner_label(db, client.id) if actor_id is None else actor_name) if owner else "",
        approved_at=now if owner else "")
    contractor_form_fields(con, body)
    db.add(con)
    log_audit(db, client.id, "contractor_created", "contractor", None, name, code, request)
    db.flush()
    if not owner:
        notify(db, client.id, "contractor_registered", "%s (%s) registered - waiting for approval" % (name, code),
               "Registered by %s. Approve the registration form before an order is issued to them." % actor_name,
               view="approvals-view", ref_type="contractor", ref_id=con.id, severity="action")
    db.commit()
    db.refresh(con)
    return {"id": con.id, "vendor_code": con.vendor_code, "company_name": con.company_name,
            "registration_status": con.registration_status,
            "message": con.vendor_code + (" added." if owner else " registered - it now waits for approval.")}


@router.get("/api/wo/work-types")
def wo_list_work_types(request: Request, department: str = "",
                       db: Session = Depends(get_db)):
    """The list to pick from, and separately what is waiting on an administrator."""
    client = require_erp_read(request, db)
    seed_work_types(db, client.id)
    rows = db.query(models.DBWorkType).filter(
        models.DBWorkType.client_id == client.id).order_by(
            models.DBWorkType.department, models.DBWorkType.name).all()
    active = [w for w in rows if (w.status or "active") == "active"]
    if department:
        # Narrowed to the discipline, but only when that leaves something to
        # pick: a business whose types are not filed by department would see
        # an empty list and no way to tell why.
        narrowed = [w for w in active if (w.department or "") == department]
        active = narrowed or active
    return {
        "work_types": [work_type_dict(w) for w in active],
        "requested": [work_type_dict(w) for w in rows if w.status == "requested"],
        "may_administer": may_administer(request, db),
    }


@router.post("/api/wo/work-types")
def wo_create_work_type(body: WorkTypeIn, request: Request,
                        db: Session = Depends(get_db)):
    """Added outright by an administrator, or asked for by anybody else."""
    client = require_items_access(request, db, "workorders.manage")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "The work type needs a name")
    clash = db.query(models.DBWorkType).filter(
        models.DBWorkType.client_id == client.id,
        sqlfunc.lower(models.DBWorkType.name) == name.lower()).first()
    if clash:
        raise HTTPException(
            409, "'%s' is already on the list%s." %
                 (name, " and waiting to be approved"
                  if clash.status == "requested" else ""))

    administers = may_administer(request, db)
    _, actor_id, actor_name = wo_actor(request, db)
    work_type = models.DBWorkType(
        client_id=client.id, name=name, code=(body.code or "").strip().upper(),
        department=(body.department or "").strip(),
        status="active" if administers else "requested",
        requested_by=actor_id, requested_by_name=actor_name,
        request_reason=(body.request_reason or "").strip(),
        decided_by_name=actor_name if administers else "",
        decided_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S") if administers else "")
    db.add(work_type)
    db.commit()
    db.refresh(work_type)
    return {"work_type": work_type_dict(work_type),
            "message": (name + " added to the work types.") if administers else
                       ("Asked for '" + name + "'. It can be used once whoever "
                        "administers the system approves it.")}


@router.post("/api/wo/work-types/{type_id}/decide")
def wo_decide_work_type(type_id: int, request: Request, approve: bool = True,
                        db: Session = Depends(get_db)):
    client = require_items_access(request, db, "people.manage")
    _, actor_id, actor_name = wo_actor(request, db, "people.manage")
    work_type = db.query(models.DBWorkType).filter(
        models.DBWorkType.id == type_id,
        models.DBWorkType.client_id == client.id).first()
    if not work_type:
        raise HTTPException(404, "Work type not found")
    if work_type.status != "requested":
        raise HTTPException(409, "That work type has already been decided.")
    work_type.status = "active" if approve else "declined"
    work_type.decided_by_name = actor_name
    work_type.decided_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    return {"work_type": work_type_dict(work_type),
            "message": "%s %s." % (work_type.name,
                                   "is now available" if approve else "was declined")}


@router.get("/api/wo/projects/{job_id}/budgets")
def wo_list_budgets(job_id: int, request: Request, order_id: int = 0,
                    db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    job = db.query(models.DBJob).filter(
        models.DBJob.id == job_id, models.DBJob.client_id == client.id).first()
    if not job:
        raise HTTPException(404, "Project not found")
    order = None
    if order_id:
        order = wo_or_404(db, client.id, order_id)
    rows = wo_budget_rows(db, client.id, job_id, order)
    return {
        "project": ("%s %s" % (job.number or "", job.name or "")).strip(),
        "job_budget": money(job.budget),
        "budgets": rows,
        "totals": {
            "allocated": money(sum(r["allocated"] for r in rows)),
            "committed": money(sum(r["committed"] + r["this_order"] for r in rows)),
            "available": money(sum(r["available"] for r in rows)),
        },
    }


@router.post("/api/wo/projects/{job_id}/budgets")
def wo_create_budget(job_id: int, body: ProjectBudgetIn, request: Request,
                     db: Session = Depends(get_db)):
    client = require_items_access(request, db, "workorders.manage")
    job = db.query(models.DBJob).filter(
        models.DBJob.id == job_id, models.DBJob.client_id == client.id).first()
    if not job:
        raise HTTPException(404, "Project not found")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "The cost centre needs a name")
    budget_breaks_vendor_limit(db, client.id, body.order_id, body.allocated_amount)
    budget = models.DBProjectBudget(
        client_id=client.id, job_id=job_id, name=name,
        code=(body.code or "").strip().upper(),
        department=(body.department or "").strip(),
        allocated_amount=money(body.allocated_amount or 0),
        notes=(body.notes or "").strip())
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return {"id": budget.id, "message": name + " allocated " +
            format_money_plain(budget.allocated_amount) + "."}


@router.put("/api/wo/projects/budgets/{budget_id}")
def wo_update_budget(budget_id: int, body: ProjectBudgetIn, request: Request,
                     db: Session = Depends(get_db)):
    """Re-allocating is allowed; allocating less than is already committed is
    not, because the money has already been promised to somebody."""
    client = require_items_access(request, db, "workorders.manage")
    budget = db.query(models.DBProjectBudget).filter(
        models.DBProjectBudget.id == budget_id,
        models.DBProjectBudget.client_id == client.id).first()
    if not budget:
        raise HTTPException(404, "Cost centre not found")
    wanted = money(body.allocated_amount or 0)
    budget_breaks_vendor_limit(db, client.id, body.order_id, wanted)
    committed = wo_committed_by_budget(db, client.id).get(budget.id, 0.0)
    if wanted > 0 and wanted < committed:
        raise HTTPException(
            409, "%s is already committed against this cost centre. Cancel or "
                 "amend those orders before reducing the allocation below it."
                 % format_money_plain(committed))
    budget.name = (body.name or budget.name or "").strip()
    budget.code = (body.code or "").strip().upper()
    budget.department = (body.department or "").strip()
    budget.allocated_amount = wanted
    budget.notes = (body.notes or "").strip()
    db.commit()
    return {"id": budget.id, "message": budget.name + " updated."}


@router.get("/api/wo/vocabulary")
def wo_vocabulary(request: Request, db: Session = Depends(get_db)):
    """Everything the wizard needs to populate its pickers in one call."""
    client = require_erp_read(request, db)
    # Seeded first: its save would otherwise make every project already read go back to the database again.
    seed_work_types(db, client.id)
    jobs = db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id).order_by(models.DBJob.id.desc()).all()
    types = db.query(models.DBWorkType).filter(
        models.DBWorkType.client_id == client.id,
        models.DBWorkType.status == "active").order_by(
            models.DBWorkType.department, models.DBWorkType.name).all()
    return {
        "departments": wo_department_choices(db, client.id),
        "uoms": list(UNITS_OF_MEASURE),
        "clause_categories": list(WO_CLAUSE_CATEGORIES),
        "statuses": list(WO_TRANSITIONS.keys()),
        "jobs": [{"id": j.id, "number": j.number, "name": j.name} for j in jobs],
        "work_types": [work_type_dict(w) for w in types],
        # The statutory choices, named rather than typed. A GST rate that is
        # not one of these is a typing mistake, and 194C is the section every
        # one of these orders is deducted under.
        "gst_rates": [0, 5, 12, 18, 28],
        "tds_options": [
            {"rate": 1, "label": "1% - Section 194C, individual or HUF"},
            {"rate": 2, "label": "2% - Section 194C, company or firm"},
            {"rate": 0, "label": "Nil - exempt or lower-deduction certificate held"},
        ],
        "may_administer": may_administer(request, db),
        "next_number_year": financial_year_label(),
    }


@router.get("/api/wo/orders")
def wo_list_orders(request: Request, status: str = "", q: str = "",
                   contractor_id: int = 0, job_id: int = 0,
                   db: Session = Depends(get_db)):
    """The register. Filtered the way it is searched - by who, where and
    what - because three hundred rows is not a list anybody reads."""
    client = require_erp_read(request, db)
    query = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.client_id == client.id)
    if status:
        query = query.filter(models.DBSubcontractOrder.status == status.upper())
    if contractor_id:
        query = query.filter(models.DBSubcontractOrder.contractor_id == contractor_id)
    if job_id:
        query = query.filter(models.DBSubcontractOrder.job_id == job_id)
    viewer = STAFF_VIEWER.get()
    if viewer:
        query = query.filter(models.DBSubcontractOrder.id.in_(wo_involved_ids(db, client.id, viewer) or [0]))
    rows = query.order_by(models.DBSubcontractOrder.id.desc()).limit(300).all()
    prime_wo_item_counts(db, [o.id for o in rows])
    prime(db, models.DBBusinessUnit, [o.business_unit_id for o in rows])
    prime(db, models.DBContractor, [o.contractor_id for o in rows])
    prime(db, models.DBJob, [o.job_id for o in rows])
    orders = [d for d in (wo_dict(db, o) for o in rows) if wo_matches(d, q)]
    counts = file_counts(db, client.id, "subcontract_order", [o["id"] for o in orders])
    for o in orders:
        o["files"] = counts.get(o["id"], {"files": 0, "drawings": 0, "photos": 0})
    return {
        "orders": orders,
        "summary": {
            "total": len(orders),
            "draft": len([o for o in orders if o["status"] == "DRAFT"]),
            "awaiting": len([o for o in orders if o["status"] == "PROVISIONAL"]),
            "approved": len([o for o in orders if o["status"] == "APPROVED"]),
            "executed": len([o for o in orders if o["status"] == "EXECUTED"]),
            "value": money(sum(o["net_order_value"] for o in orders
                               if o["status"] not in ("CANCELLED", "AMENDED"))),
        },
    }


@router.post("/api/wo/orders")
def wo_create_order(body: WorkOrderHeadIn, request: Request,
                    db: Session = Depends(get_db)):
    """Opens a draft. The number is issued now so it can be quoted while the
    BOQ is still being priced, which is how the site office refers to it."""
    client, actor_id, actor_name = wo_actor(request, db)
    dept = (body.department or "").strip()
    order = models.DBSubcontractOrder(
        client_id=client.id, status="DRAFT",
        wo_number=next_wo_number(db, client.id, dept, body.commencement_date),
        business_unit_id=body.business_unit_id, contractor_id=body.contractor_id,
        job_id=body.job_id, department=dept, work_type=(body.work_type or "").strip(),
        subject=(body.subject or "").strip(),
        scope_of_work=clean_rich_text(body.scope_of_work),
        commencement_date=(body.commencement_date or "").strip(),
        completion_date=(body.completion_date or "").strip(),
        duration_months=body.duration_months or 0,
        defect_liability_months=body.defect_liability_months or 0,
        bank_guarantee_applicable=bool(body.bank_guarantee_applicable),
        bank_guarantee_amount=money(body.bank_guarantee_amount or 0),
        bank_guarantee_validity=(body.bank_guarantee_validity or "").strip(),
        gst_rate=body.gst_rate if body.gst_rate is not None else 18.0,
        tds_rate=body.tds_rate if body.tds_rate is not None else 1.0,
        retention_percent=body.retention_percent or 0,
        mobilization_advance_percent=body.mobilization_advance_percent or 0,
        advance_recovery_percent=body.advance_recovery_percent or 0,
        labour_cess_percent=wo_percent(body.labour_cess_percent, "labour cess"),
        billing_cycle=wo_billing_cycle(body.billing_cycle),
        payment_days=max(0, int(body.payment_days or 0)),
        submitted_by=actor_id)
    db.add(order)
    db.flush()
    recost_order(db, order)
    record_wo_action(db, client, order, actor_id, actor_name, "CREATE", "", "")
    log_audit(db, client.id, "subcontract_created", "subcontract_order", order.id,
              order.wo_number, "", request)
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True),
            "message": order.wo_number + " opened as a draft."}


@router.get("/api/wo/orders.xlsx")
def wo_register_xlsx(request: Request, status: str = "", q: str = "",
                     contractor_id: int = 0, job_id: int = 0,
                     db: Session = Depends(get_db)):
    """The register as the workbook it is reconciled in."""
    client = require_erp_read(request, db)
    data = wo_list_orders(request, status, q, contractor_id, job_id, db)
    rows = [(o["wo_number"], o["status"], o["contractor"], o["project"],
             o["department"], o["work_type"], o["subject"],
             o["commencement_date"], o["completion_date"], o["item_count"],
             o["gross_amount"], o["gst_amount"], o["tds_amount"],
             o["labour_cess_amount"], o["net_order_value"],
             o["retention_percent"], o["mobilization_advance_percent"],
             o["approved_at"][:10]) for o in data["orders"]]
    s = data["summary"]
    return sheet_response(
        ("WO number", "Status", "Contractor", "Project", "Department", "Work type",
         "Subject", "Commencement", "Completion", "Items", "Gross", "GST", "TDS",
         "Labour cess", "Net value", "Retention %", "Mob. advance %", "Approved on"),
        rows, "work_order_register.xlsx",
        preamble=[("WORK ORDER REGISTER", client.company_name or ""),
                  ("Orders", s["total"], "Committed value", s["value"]), ()])


@router.get("/api/wo/orders/{order_id}")
def wo_get_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return {"order": wo_dict(db, wo_or_404(db, client.id, order_id), detail=True)}


@router.post("/api/wo/orders/{order_id}/copy")
def wo_copy_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    """A new draft that starts as this order did.

    The same trade on the next site is the same schedule with different
    quantities and mostly the same clauses. What is not copied is anything
    that was decided about this order in particular: its number, its dates,
    its approval and its history.
    """
    client, actor_id, actor_name = wo_actor(request, db)
    source = wo_or_404(db, client.id, order_id)
    order = models.DBSubcontractOrder(
        client_id=client.id, status="DRAFT",
        wo_number=next_wo_number(db, client.id, source.department),
        business_unit_id=source.business_unit_id, contractor_id=source.contractor_id,
        job_id=source.job_id, department=source.department, work_type=source.work_type,
        subject=source.subject, scope_of_work=source.scope_of_work,
        duration_months=source.duration_months,
        defect_liability_months=source.defect_liability_months,
        bank_guarantee_applicable=source.bank_guarantee_applicable,
        bank_guarantee_amount=source.bank_guarantee_amount,
        gst_rate=source.gst_rate, tds_rate=source.tds_rate,
        retention_percent=source.retention_percent,
        mobilization_advance_percent=source.mobilization_advance_percent,
        advance_recovery_percent=source.advance_recovery_percent,
        labour_cess_percent=source.labour_cess_percent,
        billing_cycle=source.billing_cycle, payment_days=source.payment_days,
        copied_from_id=source.id, submitted_by=actor_id)
    db.add(order)
    db.flush()
    wo_copy_lines(db, source, order)
    db.flush()
    recost_order(db, order)
    record_wo_action(db, client, order, actor_id, actor_name, "COPY", "",
                     "Copied from " + (source.wo_number or ""))
    log_audit(db, client.id, "subcontract_copied", "subcontract_order", order.id,
              order.wo_number, "from " + (source.wo_number or ""), request)
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True),
            "message": "%s opened as a copy of %s. Set its dates before it goes out."
                       % (order.wo_number, source.wo_number)}


@router.get("/api/wo/rates")
def wo_last_rates(request: Request, item_code: str = "", description: str = "",
                  db: Session = Depends(get_db)):
    """What this line was last ordered at, and from whom.

    Farvision's "copy rate": the rate on the previous order for the same
    code is the one figure a billing engineer wants beside the cell while
    pricing a new one. Drafts are left out - a rate nobody signed is not a
    rate anybody paid.
    """
    client = require_erp_read(request, db)
    code = (item_code or "").strip().lower()
    words = (description or "").strip().lower()
    if not code and not words:
        return {"rates": []}
    rows = db.query(models.DBSubcontractItem, models.DBSubcontractOrder).join(
        models.DBSubcontractOrder,
        models.DBSubcontractOrder.id == models.DBSubcontractItem.order_id).filter(
            models.DBSubcontractOrder.client_id == client.id,
            models.DBSubcontractOrder.status.in_(("APPROVED", "EXECUTED", "AMENDED")),
            models.DBSubcontractItem.is_header.is_(False)).order_by(
                models.DBSubcontractOrder.id.desc()).limit(2000).all()
    out = []
    for item, order in rows:
        if code and (item.item_code or "").strip().lower() != code:
            continue
        if not code and words not in (item.item_description or "").lower():
            continue
        con = db.query(models.DBContractor).filter(
            models.DBContractor.id == order.contractor_id).first()
        out.append({"order_id": order.id, "wo_number": order.wo_number,
                    "contractor": con.company_name if con else "",
                    "on": (order.approved_at or order.created_at or "")[:10],
                    "item_code": item.item_code or "", "uom": item.uom or "",
                    "description": (item.item_description or "").split("\n")[0],
                    "unit_rate": unit_rate(item.unit_rate)})
        if len(out) >= 8:
            break
    return {"rates": out}


@router.put("/api/wo/orders/{order_id}")
def wo_update_order(order_id: int, body: WorkOrderHeadIn, request: Request,
                    db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db)
    order = wo_or_404(db, client.id, order_id)
    if order.status not in WO_EDITABLE:
        raise HTTPException(
            409, order.wo_number + " is " + order.status.lower() +
                 " and cannot be edited. Amend it instead.")
    before = wo_snapshot(order)

    for field in ("business_unit_id", "contractor_id", "job_id"):
        setattr(order, field, getattr(body, field))
    order.work_type = (body.work_type or "").strip()
    order.subject = (body.subject or "").strip()
    order.scope_of_work = clean_rich_text(body.scope_of_work)
    order.commencement_date = (body.commencement_date or "").strip()
    order.completion_date = (body.completion_date or "").strip()
    order.duration_months = body.duration_months or 0
    order.defect_liability_months = body.defect_liability_months or 0
    order.bank_guarantee_applicable = bool(body.bank_guarantee_applicable)
    order.bank_guarantee_amount = money(body.bank_guarantee_amount or 0)
    order.bank_guarantee_validity = (body.bank_guarantee_validity or "").strip()
    if body.gst_rate is not None:
        order.gst_rate = body.gst_rate
    if body.tds_rate is not None:
        order.tds_rate = body.tds_rate
    order.retention_percent = body.retention_percent or 0
    order.mobilization_advance_percent = body.mobilization_advance_percent or 0
    order.advance_recovery_percent = body.advance_recovery_percent or 0
    order.labour_cess_percent = wo_percent(body.labour_cess_percent, "labour cess")
    order.billing_cycle = wo_billing_cycle(body.billing_cycle)
    order.payment_days = max(0, int(body.payment_days or 0))

    # The number carries the discipline, so changing the discipline on a draft
    # has to reissue it - otherwise it is filed under the wrong one for ever.
    dept = (body.department or "").strip()
    if dept != (order.department or ""):
        order.department = dept
        order.wo_number = next_wo_number(db, client.id, dept, order.commencement_date)

    recost_order(db, order)
    changes = wo_changes(before, order)
    if changes:
        record_wo_action(db, client, order, actor_id, actor_name, "EDIT",
                         order.status, "; ".join(changes))
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True), "message": "Saved."}


@router.post("/api/wo/orders/{order_id}/boq/import")
async def wo_import_boq(order_id: int, request: Request, file: UploadFile = File(...),
                        sheet: str = Form(""), db: Session = Depends(get_db)):
    """Read a BOQ off a sheet and hand it back priced, without saving it.

    Nothing is written here. The lines land in the grid where they can be
    read against the file they came from and corrected, and it is the ordinary
    save that commits them - so an import that read a column wrongly is a
    thing somebody notices rather than a thing they discover on the order.
    """
    client, actor_id, actor_name = wo_actor(request, db)
    order = wo_or_404(db, client.id, order_id)
    if order.status not in WO_EDITABLE:
        raise HTTPException(409, "The schedule of a " + order.status.lower() +
                                 " order cannot be changed.")

    header, body = await read_sheet_rows(file, sheet)
    mapping, unmapped = map_headers_with(header, BOQ_HEADER_ALIASES)
    fields = set(mapping.values())
    if "item_description" not in fields:
        raise HTTPException(
            400, "No description column found. Expected something headed "
                 "'Description', 'Description of work' or 'Particulars'." + sheet_note())
    if "quantity" not in fields or "unit_rate" not in fields:
        raise HTTPException(
            400, "A quantity and a rate column are both needed to price the "
                 "schedule. Found: " + (", ".join(sorted(fields)) or "nothing")
                 + "." + sheet_note())

    lines, skipped = [], 0
    for index, row in enumerate(rows_from(header, body, mapping), start=1):
        description = (row.get("item_description") or "").strip()
        quantity = money(sheet_number(row.get("quantity")))
        rate = unit_rate(sheet_number(row.get("unit_rate")))
        # A sheet off a real desk ends in its own grand total: a number with
        # no description against it. Counted and reported rather than read as
        # a line with no name, and rather than refused.
        if not description:
            skipped += 1
            continue
        lines.append({
            "activity_no": (row.get("activity_no") or "").strip() or "%d.0" % index,
            "item_code": (row.get("item_code") or "").strip(),
            "item_description": description,
            "technical_spec": (row.get("technical_spec") or "").strip(),
            "uom": (row.get("uom") or "").strip(),
            "quantity": quantity, "unit_rate": rate,
            "total_amount": money(quantity * rate),
            "budget_id": None, "cost_centre": "",
        })

    if not lines:
        raise HTTPException(
            400, "Nothing on that sheet read as a priced line." + sheet_note())

    return {
        "lines": lines,
        "read_as": mapping_report(header, mapping),
        "ignored_columns": unmapped,
        "skipped_rows": skipped,
        "gross_amount": money(sum(line["total_amount"] for line in lines)),
        "message": "%d line(s) read%s. Check them against the sheet, then save."
                   % (len(lines),
                      ", %d row(s) with no description left out" % skipped
                      if skipped else ""),
    }


@router.put("/api/wo/orders/{order_id}/boq")
def wo_set_boq(order_id: int, body: BoqIn, request: Request,
               db: Session = Depends(get_db)):
    """Replaces the BOQ wholesale, because that is how it is edited: the
    schedule is worked on in one place and saved as a whole."""
    client, actor_id, actor_name = wo_actor(request, db)
    order = wo_or_404(db, client.id, order_id)
    if order.status not in WO_EDITABLE:
        raise HTTPException(409, "The schedule of a " + order.status.lower() +
                                 " order cannot be changed.")

    db.query(models.DBSubcontractItem).filter(
        models.DBSubcontractItem.order_id == order.id).delete()
    kept = 0
    for index, line in enumerate(body.lines):
        description = (line.item_description or "").strip()
        if not description:
            continue
        header = bool(line.is_header)
        # A heading is a heading: it prices nothing and is never measured.
        qty = 0.0 if header else money(line.quantity or 0)
        rate = 0.0 if header else unit_rate(line.unit_rate or 0)
        if qty < 0 or rate < 0:
            raise HTTPException(400, "Line %d: quantity and rate cannot be negative"
                                     % (index + 1))
        tolerance = 0.0 if header else wo_percent(line.tolerance_percent,
                                                  "tolerance on line %d" % (index + 1))
        db.add(models.DBSubcontractItem(
            order_id=order.id, activity_no=(line.activity_no or "").strip(),
            item_code=(line.item_code or "").strip(), item_description=description,
            technical_spec=(line.technical_spec or "").strip(),
            uom="" if header else (line.uom or "").strip(), quantity=qty, unit_rate=rate,
            total_amount=money(qty * rate), is_header=header, tolerance_percent=tolerance,
            budget_id=None if header else wo_valid_budget_id(db, client.id, order, line.budget_id),
            cost_centre=(line.cost_centre or "").strip(), display_order=index,
            boq_key=(line.boq_key or "").strip()[:40] if not header else ""))
        kept += 1

    db.flush()
    recost_order(db, order)
    db.commit()
    db.refresh(order)
    over = boq_over_allotments(db, client.id, [(l.boq_key or "").strip() for l in body.lines])
    return {"order": wo_dict(db, order, detail=True), "warnings": over,
            "message": "%d line%s saved. Gross %s.%s" % (kept, "" if kept == 1 else "s", inr(order.gross_amount),
                                                        (" Over the BOQ - " + "; ".join(over) + ".") if over else "")}


@router.put("/api/wo/orders/{order_id}/terms")
def wo_set_terms(order_id: int, body: TermsIn, request: Request,
                 db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db)
    order = wo_or_404(db, client.id, order_id)
    if order.status not in WO_EDITABLE:
        raise HTTPException(409, "The terms of a " + order.status.lower() +
                                 " order cannot be changed.")
    db.query(models.DBSubcontractTerm).filter(
        models.DBSubcontractTerm.order_id == order.id).delete()
    for index, term in enumerate(body.terms):
        text = (term.clause_text or "").strip()
        if not text:
            continue
        db.add(models.DBSubcontractTerm(
            order_id=order.id, clause_category=(term.clause_category or "").strip(),
            clause_text=text, display_order=index))
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True), "message": "Terms saved."}


@router.get("/api/wo/terms/library")
def wo_terms_library(request: Request, db: Session = Depends(get_db)):
    """The clauses this trade puts on nearly every order.

    Offered as a starting point rather than imposed: they are edited per order,
    but nobody should be retyping the measurement mode from memory.
    """
    client = require_erp_read(request, db)
    own = company_terms(db, client.id, fallback=False)
    head = letterhead(db, client)
    mine = [dict(t, clause_text=fill_terms(t.get("clause_text"), head)) for t in (own or WO_STANDARD_TERMS)]
    return {"library": mine, "custom": bool(own), "standard": WO_STANDARD_TERMS}


@router.put("/api/wo/terms/library")
def wo_save_terms_library(body: TermsIn, request: Request, db: Session = Depends(get_db)):
    """The company's own general conditions, printed on every work order
    that has none of its own. Saving an empty list goes back to the standard."""
    client = get_client_user(request, db)
    clauses = [{"clause_category": (t.clause_category or "").strip()[:80],
                "clause_text": (t.clause_text or "").strip()[:4000]}
               for t in body.terms if (t.clause_text or "").strip()][:80]
    put_setting(db, client.id, "wo_terms_library", json.dumps(clauses) if clauses else "")
    db.commit()
    return {"library": clauses or WO_STANDARD_TERMS, "custom": bool(clauses),
            "message": ("%d conditions saved. Every work order without its own prints these." % len(clauses))
                       if clauses else "Back to the standard conditions."}


@router.post("/api/wo/orders/{order_id}/submit")
def wo_submit(order_id: int, body: WoActionIn, request: Request,
              db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db)
    order = wo_or_404(db, client.id, order_id)
    wo_apply(db, client, order, "SUBMIT", actor_id, actor_name, body.comments)
    log_audit(db, client.id, "subcontract_submitted", "subcontract_order", order.id,
              order.wo_number, "", request)
    db.commit()
    db.refresh(order)
    notify(db, client.id, "subcontract_submitted", "%s is waiting for approval" % order.wo_number,
           "%s - %s." % (order.subject or "Subcontract order", inr(order.gross_amount)),
           view="subcontracts-view", ref_type="subcontract_order", ref_id=order.id, severity="action")
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True),
            "message": order.wo_number + " submitted for approval."}


@router.post("/api/wo/orders/{order_id}/self-approve")
def wo_self_approve(order_id: int, body: WoActionIn, request: Request,
                    db: Session = Depends(get_db)):
    """The owner's own order, approved as it is issued.

    The owner answers to nobody, so sending their own order into a queue to
    wait for their own signature is a step with no one on the other end. It
    is still checked as any order is - complete, on a budget, and any overrun
    explained - and the history says the owner raised and approved it.
    Staff cannot do this: the person who prices an order is not the person
    who commits the business to it.
    """
    client = get_client_user(request, db)
    order = wo_or_404(db, client.id, order_id)
    actor_name = client.contact_name or client.company_name or "Master"
    if order.status == "DRAFT":
        wo_apply(db, client, order, "SUBMIT", None, actor_name, "Raised by the Master", quiet=True)
    wo_apply(db, client, order, "APPROVE", None, actor_name,
             (body.comments or "").strip() or "Approved by the Master", override=bool(body.override), quiet=True)
    log_audit(db, client.id, "subcontract_self_approved", "subcontract_order", order.id,
              order.wo_number, "approved by the Master as issued", request)
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True),
            "message": order.wo_number + " approved and ready to issue."}


@router.post("/api/wo/orders/{order_id}/approve")
def wo_approve(order_id: int, body: WoActionIn, request: Request,
               db: Session = Depends(get_db)):
    """The project head's decision. A separate right from raising the order,
    because the whole point of the provisional state is that the person who
    priced it is not the person who commits the business to it."""
    client, actor_id, actor_name = wo_actor(request, db, "subcontracts.approve")
    order = wo_or_404(db, client.id, order_id)
    nxt = wo_decide_step(db, client, order, actor_id, actor_name, True, body.comments,
                         override=bool(body.override))
    log_audit(db, client.id, "subcontract_approved" if nxt is None else "subcontract_step_approved",
              "subcontract_order", order.id, order.wo_number, "", request)
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True),
            "message": (order.wo_number + " approved.") if nxt is None else
                       ("%s approved by you and passed to %s." % (order.wo_number, wo_step_name(db, nxt)))}


@router.post("/api/wo/orders/{order_id}/reject")
def wo_reject(order_id: int, body: WoActionIn, request: Request,
              db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, "subcontracts.approve")
    order = wo_or_404(db, client.id, order_id)
    wo_decide_step(db, client, order, actor_id, actor_name, False, body.comments)
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True),
            "message": order.wo_number + " sent back to draft."}


@router.post("/api/wo/orders/{order_id}/execute")
def wo_execute(order_id: int, body: WoActionIn, request: Request,
               db: Session = Depends(get_db)):
    """Counter-signed and returned. From here it can carry RA bills."""
    client, actor_id, actor_name = wo_actor(request, db)
    order = wo_or_404(db, client.id, order_id)
    wo_apply(db, client, order, "EXECUTE", actor_id, actor_name, body.comments)
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True),
            "message": order.wo_number + " is executed and open for RA bills."}


@router.post("/api/wo/orders/{order_id}/cancel")
def wo_cancel(order_id: int, body: WoActionIn, request: Request,
              db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, "subcontracts.approve")
    order = wo_or_404(db, client.id, order_id)
    if not (body.comments or "").strip():
        raise HTTPException(400, "Say why it is being cancelled.")
    wo_apply(db, client, order, "CANCEL", actor_id, actor_name, body.comments)
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True),
            "message": order.wo_number + " cancelled."}


@router.get("/api/wo/orders/{order_id}/delete-preview")
def wo_delete_preview(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    order = wo_or_404(db, client.id, order_id)
    rep = wo_delete_report(db, client, order)
    return {"numbers": rep["numbers"], "counts": rep["counts"], "blockers": [], "warnings": rep["warnings"],
            "can_delete": True}


@router.delete("/api/wo/orders/{order_id}")
def wo_delete_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        return wo_delete_order_now(order_id, request, db)
    except IntegrityError as exc:
        # Say which constraint stopped it, rather than a generic clash.
        db.rollback()
        logger.warning("Work order %s could not be deleted: %s", order_id, exc)
        raise HTTPException(409, "Could not delete it: %s" % str(getattr(exc, "orig", exc)).splitlines()[0][:240])


@router.get("/api/wo/contractors/{con_id}/delete-preview")
def vendor_delete_preview(con_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    con = _vendor_or_404(db, client, con_id)
    ids, bills, paid, logins = _vendor_report(db, client, con)
    warnings = ["%s has %s paid against it - those payments are deleted too." % (con.company_name, inr(paid))] if paid > 0 else []
    return {"numbers": [con.company_name], "blockers": [], "warnings": warnings, "can_delete": True,
            "counts": {"orders": len(ids), "bills": bills, "logins": logins}}


@router.delete("/api/wo/contractors/{con_id}")
def vendor_delete(con_id: int, request: Request, db: Session = Depends(get_db)):
    """A vendor goes with every work order, bill, measurement, payment and portal login that is theirs."""
    client = get_client_user(request, db)
    require_owner(request, db)
    con = _vendor_or_404(db, client, con_id)
    name = con.company_name
    ids, _, _, _ = _vendor_report(db, client, con)
    for oid in ids:
        if db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == oid).first():
            wo_delete_order_now(oid, request, db)       # each order with everything attached, as when deleted by itself
    drop = lambda q: q.delete(synchronize_session=False)
    rel_ids = [r.id for r in db.query(models.DBRetentionRelease.id).filter(models.DBRetentionRelease.contractor_id == con.id).all()]
    if rel_ids:
        drop(db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.doc_type == "retention_release", models.DBMoneyEntry.doc_id.in_(rel_ids)))
        drop(db.query(models.DBRetentionRelease).filter(models.DBRetentionRelease.id.in_(rel_ids)))
    drop(db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client.id, models.DBMoneyEntry.party_type == "contractor", models.DBMoneyEntry.party_id == con.id))
    drop(db.query(models.DBPortalUser).filter(
        models.DBPortalUser.client_id == client.id, models.DBPortalUser.party_type == "contractor", models.DBPortalUser.party_id == con.id))
    cascade_delete_referrers(db, "contractors", [con.id])
    drop(db.query(models.DBContractor).filter(models.DBContractor.id == con.id))
    log_audit(db, client.id, "vendor_deleted", "contractor", con_id, name, "Deleted with their orders and bills", request)
    db.commit()
    return {"ok": True, "message": "%s deleted, with their orders, bills and payments." % name}


@router.get("/api/work-orders/delete-all-preview")
def work_orders_delete_all_preview(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    return {"phrase": WIPE_PHRASE,
            "subcontract": db.query(models.DBSubcontractOrder).filter(
                models.DBSubcontractOrder.client_id == client.id).count(),
            "client": db.query(models.DBWorkOrder).filter(models.DBWorkOrder.client_id == client.id).count(),
            "sub_bills": db.query(models.DBSubBill).filter(models.DBSubBill.client_id == client.id).count(),
            "ra_bills": db.query(models.DBRABill).filter(models.DBRABill.client_id == client.id).count()}


@router.post("/api/work-orders/delete-all")
def work_orders_delete_all(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Every work order - given to gangs and received from clients - with everything attached
    to each. The owner's alone, and only with the phrase typed out: there is no undoing it,
    so a backup is taken first (Settings, Alerts & data)."""
    client = get_client_user(request, db)
    require_owner(request, db)
    if ((body or {}).get("confirm") or "").strip() != WIPE_PHRASE:
        raise HTTPException(400, "Type %s to confirm." % WIPE_PHRASE)
    scope = (body or {}).get("scope") or "all"
    gone = {"subcontract": 0, "client": 0}
    if scope in ("all", "subcontract"):
        for oid in [o.id for o in db.query(models.DBSubcontractOrder.id).filter(
                models.DBSubcontractOrder.client_id == client.id).order_by(models.DBSubcontractOrder.id.desc()).all()]:
            if not db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == oid).first():
                continue  # went with an earlier version of the same order
            try:
                wo_delete_order_now(oid, request, db)
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(409, "Could not delete order %s: %s" % (oid, str(getattr(exc, "orig", exc)).splitlines()[0][:220]))
            gone["subcontract"] += 1
    if scope in ("all", "client"):
        for wid in [w.id for w in db.query(models.DBWorkOrder.id).filter(models.DBWorkOrder.client_id == client.id).all()]:
            try:
                erp_delete_work_order(wid, request, db)
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(409, "Could not delete client order %s: %s" % (wid, str(getattr(exc, "orig", exc)).splitlines()[0][:220]))
            gone["client"] += 1
    log_audit(db, client.id, "work_orders_wiped", "work_order", None, "all", "Deleted %d subcontract and %d client work orders" % (
        gone["subcontract"], gone["client"]), request)
    db.commit()
    return {"ok": True, **gone, "message": "Deleted %d subcontract and %d client work orders, with everything attached." % (
        gone["subcontract"], gone["client"])}


@router.post("/api/wo/orders/{order_id}/amend")
def wo_amend(order_id: int, body: WoActionIn, request: Request,
             db: Session = Depends(get_db)):
    """Supersede an order with a revision.

    The original is not edited and not deleted: it was signed, so it stays as
    it was signed. The revision is a new draft carrying everything across, and
    the two are linked so the history reads in one line.
    """
    client, actor_id, actor_name = wo_actor(request, db)
    order = wo_or_404(db, client.id, order_id)
    if "AMEND" not in WO_TRANSITIONS.get(order.status or "", {}):
        raise HTTPException(409, "%s is %s, so it cannot be amended." % (order.wo_number, (order.status or "").lower()))
    pending = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.supersedes_id == order.id,
        models.DBSubcontractOrder.status.in_(("DRAFT", "PROVISIONAL"))).first()
    if pending:
        raise HTTPException(409, "%s is already amending %s. Finish or cancel it first."
                                 % (pending.wo_number, order.wo_number))

    revision = models.DBSubcontractOrder(
        client_id=client.id, status="DRAFT",
        wo_number="%s-REV-%02d" % (
            re.sub(r"-REV-\d+$", "", order.wo_number or ""), (order.amendment_no or 0) + 1),
        amendment_no=(order.amendment_no or 0) + 1, supersedes_id=order.id,
        business_unit_id=order.business_unit_id, contractor_id=order.contractor_id,
        job_id=order.job_id, department=order.department, work_type=order.work_type,
        subject=order.subject, scope_of_work=order.scope_of_work,
        commencement_date=order.commencement_date, completion_date=order.completion_date,
        duration_months=order.duration_months,
        defect_liability_months=order.defect_liability_months,
        bank_guarantee_applicable=order.bank_guarantee_applicable,
        bank_guarantee_amount=order.bank_guarantee_amount,
        bank_guarantee_validity=order.bank_guarantee_validity,
        gst_rate=order.gst_rate, tds_rate=order.tds_rate,
        retention_percent=order.retention_percent,
        mobilization_advance_percent=order.mobilization_advance_percent,
        advance_recovery_percent=order.advance_recovery_percent,
        labour_cess_percent=order.labour_cess_percent,
        billing_cycle=order.billing_cycle, payment_days=order.payment_days,
        submitted_by=actor_id)
    db.add(revision)
    db.flush()
    wo_copy_lines(db, order, revision)
    db.flush()
    recost_order(db, revision)
    # The original stays live - measured and billed as before - until the
    # revision is approved and takes its history over.
    record_wo_action(db, client, order, actor_id, actor_name, "REVISE", order.status,
                     revision.wo_number + " drawn up to amend it")
    record_wo_action(db, client, revision, actor_id, actor_name, "CREATE", "",
                     "Amends " + (order.wo_number or ""))
    log_audit(db, client.id, "subcontract_amended", "subcontract_order", revision.id,
              revision.wo_number, "amends " + (order.wo_number or ""), request)
    db.commit()
    db.refresh(revision)
    return {"order": wo_dict(db, revision, detail=True),
            "message": revision.wo_number + " opened to amend " + order.wo_number +
                       ". The original stays open for measuring and billing until the revision is approved."}


@router.post("/api/wo/orders/bulk-delete")
def wo_bulk_delete(body: dict, request: Request, db: Session = Depends(get_db)):
    return run_bulk_delete(body.get("ids"), lambda i: wo_delete_order_now(i, request, db), db)


@router.post("/api/wo/contractors/bulk-delete")
def vendor_bulk_delete(body: dict, request: Request, db: Session = Depends(get_db)):
    return run_bulk_delete(body.get("ids"), lambda i: vendor_delete(i, request, db), db)


@router.put("/api/wo/business-units/{unit_id}")
def wo_update_business_unit(unit_id: int, body: BusinessUnitIn, request: Request,
                            db: Session = Depends(get_db)):
    """The letterhead: name, address, GSTIN, PAN and logo, as they print at
    the top of every work order, bill and purchase order this unit issues."""
    client = require_items_access(request, db, "workorders.manage")
    unit = db.query(models.DBBusinessUnit).filter(models.DBBusinessUnit.id == unit_id,
                                                  models.DBBusinessUnit.client_id == client.id).first()
    if not unit:
        raise HTTPException(404, "Business unit not found")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "The business unit needs a name")
    gstin, pan = clean_tax_ids(body.gstin, body.pan)
    unit.name, unit.code = name, (body.code or "").strip().upper()
    unit.gstin, unit.pan = gstin, pan
    unit.address = (body.address or "").strip()
    unit.logo_url = image_data_url(body.logo_url, "The logo") if (body.logo_url or "").startswith("data:") \
        else ("" if not body.logo_url else unit.logo_url)
    log_audit(db, client.id, "business_unit_updated", "business_unit", unit.id, name, gstin, request)
    db.commit()
    return {"id": unit.id, "name": unit.name, "message": "%s saved. Documents print with it from now on." % name}


@router.put("/api/wo/contractors/{con_id}")
def wo_update_contractor(con_id: int, body: ContractorIn, request: Request,
                         db: Session = Depends(get_db)):
    """The gang's particulars as the order, the bill and the TDS return need them."""
    client = require_items_access(request, db, ("workorders.manage", "billing.manage"))
    con = db.query(models.DBContractor).filter(models.DBContractor.id == con_id,
                                               models.DBContractor.client_id == client.id).first()
    if not con:
        raise HTTPException(404, "Contractor not found")
    name = (body.company_name or "").strip()
    if not name:
        raise HTTPException(400, "The contractor needs a company name")
    clash = db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id, models.DBContractor.id != con.id,
        sqlfunc.lower(models.DBContractor.company_name) == name.lower()).first()
    if clash:
        raise HTTPException(409, "'" + name + "' is already on the contractor list")
    gstin, pan = clean_tax_ids(body.gst_number, body.pan)
    ifsc = (body.bank_ifsc or "").strip().upper()
    if ifsc and not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc):
        raise HTTPException(400, "An IFSC is eleven characters: four letters, a zero, then six (for example SBIN0001234).")
    con.company_name = name
    con.contact_person = (body.contact_person or "").strip()
    con.email = (body.email or "").strip()
    con.phone_number = (body.phone_number or "").strip()
    con.pan, con.gst_number = pan, gstin
    con.bank_name = (body.bank_name or "").strip()
    con.bank_account = re.sub(r"\s", "", body.bank_account or "")
    con.bank_ifsc = ifsc
    con.address = (body.address or "").strip()
    code = (body.vendor_code or "").strip().upper()
    if code and code != (con.vendor_code or "").upper():
        if db.query(models.DBContractor).filter(
                models.DBContractor.client_id == client.id, models.DBContractor.id != con.id,
                sqlfunc.upper(models.DBContractor.vendor_code) == code).first():
            raise HTTPException(409, "Vendor code %s is already taken." % code)
        con.vendor_code = code
    contractor_form_fields(con, body)
    # A form that was sent back and has been put right goes back for approval.
    if (con.registration_status or "") == "REJECTED":
        con.registration_status = "PENDING"
    log_audit(db, client.id, "contractor_updated", "contractor", con.id, name, pan, request)
    db.commit()
    return {"id": con.id, "company_name": con.company_name, "registration_status": con.registration_status,
            "message": "%s saved." % name}


@router.get("/api/wo/contractors/{con_id}/registration.pdf")
def contractor_registration_pdf(con_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    con = contractor_or_404(db, client.id, con_id)
    return form_pdf_response(registration_form_spec(db, client, con), "registration_%s" % (con.vendor_code or con.id))


@router.get("/api/wo/contractors/{con_id}/registration.xlsx")
def contractor_registration_xlsx(con_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    con = contractor_or_404(db, client.id, con_id)
    data = sheet_forms.registration_workbook(registration_form_data(db, client, con), letterhead(db, client))
    name = re.sub(r"[^A-Za-z0-9]+", "_", "registration_%s" % (con.vendor_code or con.id)).strip("_")
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="%s.xlsx"' % name})


@router.get("/api/wo/contractors.xlsx")
def contractors_register_xlsx(request: Request, db: Session = Depends(get_db)):
    """Every sub contractor on the books with their vendor code, as the office's
    vendor list - its PDF twin beside it."""
    client = require_erp_read(request, db)
    rows = [contractor_dict(c) for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id).order_by(models.DBContractor.vendor_code).all()]
    labels = dict(REGISTRATION_DOCUMENTS)
    headers = ("Vendor Code", "Name of the Sub Contractor", "Project", "Nature of Work", "Contact Person", "Tel no.",
               "E-mail", "PAN", "GST Reg No", "Aadhaar", "Address", "City", "State", "Pin Code", "Bank",
               "Account no", "IFSC", "Branch", "Date of Joining", "Documents", "Status")
    body = [(r["vendor_code"], r["company_name"], r["registered_project"], r["nature_of_work"], r["contact_person"],
             r["phone_number"], r["email"], r["pan"], r["gst_number"], r["aadhaar"], r["address"], r["city"],
             r["state"], r["pin_code"], r["bank_name"], r["bank_account"], r["bank_ifsc"], r["bank_branch"],
             r["joining_date"], ", ".join(labels[d].split(") ", 1)[-1] for d in r["documents"] if d in labels),
             {"APPROVED": "Registered", "PENDING": "Awaiting approval", "REJECTED": "Sent back"}.get(
                 r["registration_status"], r["registration_status"])) for r in rows]
    return sheet_response(headers, body, "sub_contractors.xlsx",
                          preamble=[("SUB CONTRACTOR REGISTER", client.company_name or ""),
                                    ("As at", date.today().isoformat()), ()])


@router.post("/api/wo/contractors/import")
async def import_registration_forms(request: Request, file: UploadFile = File(...),
                                    db: Session = Depends(get_db)):
    """The vendor-codes workbook the office kept - one Sub Contractor
    Registration Form per sheet - brought in once. Each form becomes a
    registered sub contractor under the code written on it; one already on
    the books (by code, else by name) has its form filled in from the sheet.

    Nothing that would be wrong is stored: a PAN, GSTIN or IFSC that is not
    the right shape is left blank and listed back, and a code already taken
    by somebody else is not reused - the code in the sheet's own name is used
    when it is free, which is how a copied form that kept its original's
    code is usually put right."""
    client, actor_id, actor_name = wo_actor(request, db, ("workorders.manage", "billing.manage"))
    raw = await file.read()
    try:
        import_guard.check_workbook_bytes(raw, file.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    try:
        import openpyxl
        book = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, keep_links=False)
    except Exception:
        raise HTTPException(400, "That file could not be read as an Excel workbook. Open it in Excel and save it again as .xlsx.")
    forms = sheet_forms.read_registration_forms(book)
    if not forms:
        raise HTTPException(400, "No Sub Contractor Registration Form was found in that workbook - "
                                 "each form needs a VENDOR CODE and the Name of the Sub Contractor.")
    existing = db.query(models.DBContractor).filter(models.DBContractor.client_id == client.id).all()
    by_code = {(c.vendor_code or "").strip().upper(): c for c in existing if c.vendor_code}
    by_name = {norm_name(c.company_name): c for c in existing if c.company_name}
    created, updated, skipped, warnings = [], [], [], []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source = os.path.basename(file.filename or "workbook")
    for f in forms:
        name = (f.get("company_name") or "").strip()
        code = re.sub(r"\s", "", f.get("vendor_code") or "").upper()
        where = "%s (sheet '%s')" % (code or name, f["sheet"])
        if not name:
            skipped.append("%s: no name of the sub contractor." % where)
            continue
        con = by_code.get(code) if code else None
        if con is not None and norm_name(con.company_name) != norm_name(name) \
                and by_name.get(norm_name(name)) is not None:
            # Already on the books under a code of its own - brought up to date there.
            con, code = by_name[norm_name(name)], ""
        elif con is not None and norm_name(con.company_name) != norm_name(name):
            # The code is somebody else's. The sheet's own name often carries the right one.
            m = re.match(r"^\s*([A-Za-z]+\d+)", f["sheet"])
            alt = m.group(1).upper() if m else ""
            if alt and alt != code and alt not in by_code:
                warnings.append("%s: %s is already %s, so %s was registered as %s, the code in the sheet's name."
                                % (where, code, con.company_name, name, alt))
                code, con = alt, None
            else:
                skipped.append("%s: %s is already %s. Give %s its own code and import again, or add it by hand."
                               % (where, code, con.company_name, name))
                continue
        if con is None:
            con = by_name.get(norm_name(name))
        if con is None:
            con = models.DBContractor(client_id=client.id, company_name=name[:200],
                                      vendor_code=code or next_vendor_code(db, client.id),
                                      registration_status="APPROVED", registered_by=actor_id,
                                      registered_by_name="Imported from %s" % source,
                                      approved_by_name="Registration form on file", approved_at=now)
            db.add(con)
            created.append(con)
        elif con not in created:
            updated.append(con)
        if code and not con.vendor_code:
            con.vendor_code = code
        # Tax and bank identifiers go in only when they are the right shape.
        pan = re.sub(r"\s", "", f.get("pan") or "").upper()
        gstin = re.sub(r"\s", "", f.get("gst_number") or "").upper()
        ifsc = re.sub(r"\s", "", f.get("bank_ifsc") or "").upper()
        aadhaar = re.sub(r"\s", "", f.get("aadhaar") or "")
        if gstin and not (len(gstin) == 15 and state_from_gstin(gstin) and
                          re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$", gstin)):
            warnings.append("%s: GST Reg No '%s' is not a GSTIN - left blank." % (where, f.get("gst_number")))
            gstin = ""
        if pan and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan):
            warnings.append("%s: PAN '%s' is not a PAN - left blank." % (where, f.get("pan")))
            pan = ""
        if not pan and gstin:
            pan = gstin[2:12]
        if ifsc and not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc):
            warnings.append("%s: IFSC '%s' is not an IFSC - left blank." % (where, f.get("bank_ifsc")))
            ifsc = ""
        if aadhaar and not re.match(r"^\d{12}$", aadhaar):
            warnings.append("%s: Aadhaar '%s' is not twelve digits - left blank." % (where, f.get("aadhaar")))
            aadhaar = ""
        values = {"contact_person": f.get("contact_person"), "email": f.get("email"),
                  "phone_number": f.get("phone_number"), "address": f.get("address"),
                  "bank_name": f.get("bank_name"), "bank_account": re.sub(r"\s", "", f.get("bank_account") or ""),
                  "bank_branch": f.get("bank_branch"), "registered_project": f.get("registered_project"),
                  "joining_date": f.get("joining_date"), "pin_code": f.get("pin_code"), "city": f.get("city"),
                  "state": f.get("state"), "nature_of_work": f.get("nature_of_work"),
                  "entity_type": f.get("entity_type"), "pan": pan, "gst_number": gstin, "bank_ifsc": ifsc,
                  "aadhaar": aadhaar}
        for key, value in values.items():
            value = (value or "").strip() if isinstance(value, str) else value
            if value:
                setattr(con, key, str(value)[:300])
        con.declaration_signed = True
        if code:
            by_code[code] = con
        by_name[norm_name(name)] = con
        db.flush()
    log_audit(db, client.id, "contractors_imported", "contractor", None, source,
              "%d new, %d updated, %d skipped" % (len(created), len(updated), len(skipped)), request)
    db.commit()
    return {"ok": True, "created": len(created), "updated": len(set(c.id for c in updated)),
            "skipped": skipped, "warnings": warnings,
            "message": "%d sub contractor%s registered from the workbook, %d brought up to date%s." % (
                len(created), "" if len(created) == 1 else "s", len(set(c.id for c in updated)),
                (", %d not imported" % len(skipped)) if skipped else "")}


@router.post("/api/wo/contractors/{con_id}/{action}")
def decide_contractor_registration(con_id: int, action: str, request: Request, body: dict = None,
                                   db: Session = Depends(get_db)):
    """Taking a sub contractor on: the registration form approved, or sent
    back with what is wrong on it. Not by the person who filled it in."""
    client, actor_id, actor_name = wo_actor(request, db, "subcontracts.approve")
    con = db.query(models.DBContractor).filter(models.DBContractor.id == con_id,
                                               models.DBContractor.client_id == client.id).first()
    if not con:
        raise HTTPException(404, "Contractor not found")
    move = (action or "").lower()
    if move not in ("approve", "reject"):
        raise HTTPException(404, "Unknown action")
    comments = ((body or {}).get("comments") or "").strip()
    if (con.registration_status or "APPROVED") != "PENDING":
        raise HTTPException(409, "%s is not waiting for approval." % (con.vendor_code or con.company_name))
    if actor_id and con.registered_by == actor_id:
        raise HTTPException(403, "You registered %s, so somebody else has to approve it." % con.company_name)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    who = actor_name if actor_id else owner_label(db, client.id)
    if move == "approve":
        con.registration_status, con.approved_by_name, con.approved_at = "APPROVED", who, now
        con.rejection_reason = ""
    else:
        if not comments:
            raise HTTPException(400, "Say what is wrong with the form, so it can be put right.")
        con.registration_status, con.rejection_reason = "REJECTED", comments
    log_audit(db, client.id, "contractor_%s" % ("approved" if move == "approve" else "sent_back"), "contractor",
              con.id, con.company_name or "", comments, request)
    if con.registered_by:
        notify_employee(db, client.id, con.registered_by,
                        "Registration %s: %s" % ("approved" if move == "approve" else "sent back", con.company_name),
                        ("%s is now a registered sub contractor." % con.vendor_code) if move == "approve"
                        else "Put right: " + comments, link="/next/subcontractors/vendors")
    db.commit()
    return {"ok": True, "contractor": contractor_dict(con),
            "message": "%s %s." % (con.vendor_code or con.company_name,
                                   "approved - an order can now be issued to them" if move == "approve"
                                   else "sent back")}


@router.post("/api/wo/orders/{order_id}/charge-budget")
def wo_charge_budget(order_id: int, body: ChargeBudgetIn, request: Request,
                     db: Session = Depends(get_db)):
    """Charge the schedule to one cost centre in a single move - the lines
    not yet charged, or every line. Most orders spend one allocation, and
    picking it on two hundred lines one at a time is how lines get missed."""
    client, _, _ = wo_actor(request, db)
    order = wo_or_404(db, client.id, order_id)
    if order.status not in WO_EDITABLE:
        raise HTTPException(409, "Only a draft order can be re-charged.")
    budget_id = wo_valid_budget_id(db, client.id, order, body.budget_id)
    if not budget_id:
        raise HTTPException(400, "That cost centre is not on this order's project.")
    n = 0
    for item in db.query(models.DBSubcontractItem).filter(
            models.DBSubcontractItem.order_id == order.id).all():
        if item.is_header or (body.only_blank and item.budget_id):
            continue
        item.budget_id = budget_id
        n += 1
    db.commit()
    db.refresh(order)
    return {"order": wo_dict(db, order, detail=True),
            "message": "%d line%s charged." % (n, "" if n == 1 else "s")}


@router.post("/api/wo/orders/{order_id}/boq-lines")
def wo_add_boq_lines(order_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    """Lines of the project BOQ, ready to go into a gang order's schedule: pick them by key, give the quantity and the
    gang's rate. Returns them as schedule lines (nothing saved) with a warning where a line would be over-allotted."""
    client, _, _ = wo_actor(request, db)
    order = wo_or_404(db, client.id, order_id)
    wanted = body.get("lines") or []
    keys = [str(w.get("key") or "") for w in wanted]
    found = {l.key: l for l in db.query(models.DBBoqLine).join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id).filter(
        models.DBBoq.client_id == client.id, models.DBBoqLine.key.in_(keys or [""])).all()}
    given = boq_given_to_gangs(db, client.id, set(keys))
    out, warn = [], []
    for w in wanted:
        l = found.get(str(w.get("key") or ""))
        if not l or l.kind not in BOQ_PRICED:
            continue
        qty = money(w.get("quantity") if w.get("quantity") is not None else l.quantity)
        rate = unit_rate(w.get("rate") if w.get("rate") is not None else l.rate)
        out.append({"boq_key": l.key, "activity_no": l.sno or "", "item_code": l.item_code or "",
                    "item_description": l.description, "technical_spec": l.remarks or "", "uom": l.uom or "",
                    "quantity": qty, "unit_rate": rate})
        total = (given.get(l.key) or {"qty": 0.0})["qty"] + qty
        if total > (l.quantity or 0) + 0.0001:
            warn.append("%s: %s would be given in all against %s in the BOQ" % (l.sno or l.description[:30], money(total), money(l.quantity)))
    return {"lines": out, "warnings": warn}
