"""The contractor compliance endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.compliance import BACK_CHARGE_KINDS, DOC_KINDS, RATING_FIELDS
from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.schemas.compliance import ApplyBackChargesIn, BackChargeIn, ComplianceDocIn, RatingIn
from app.services.compliance import (
    add_rating, apply_back_charges, back_charge_dict, compliance_overview, contractor_compliance, doc_dict,
    raise_back_charge, release_back_charge, scorecard, settlement,
)
from app.services.subcontract_billing import recost_sub_bill, sub_bill_dict, sub_bill_or_404

router = APIRouter()


def _contractor_or_404(db, client_id, contractor_id):
    row = db.query(models.DBContractor).filter(models.DBContractor.id == contractor_id,
                                               models.DBContractor.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "Contractor not found")
    return row


@router.get("/api/compliance")
def compliance_home(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return {"contractors": compliance_overview(db, client.id), "kinds": DOC_KINDS,
            "back_charge_kinds": list(BACK_CHARGE_KINDS), "rating_fields": list(RATING_FIELDS)}


@router.get("/api/compliance/contractors/{contractor_id}")
def contractor_status(contractor_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    con = _contractor_or_404(db, client.id, contractor_id)
    out = contractor_compliance(db, client.id, con.id)
    out.update({"contractor": con.company_name, "score": scorecard(db, client.id, con.id)})
    out["ratings"] = [{"id": r.id, "bill_id": r.bill_id, "quality": r.quality, "speed": r.speed, "safety": r.safety,
                       "discipline": r.discipline, "note": r.note, "by": r.rated_by_name, "at": r.created_at}
                      for r in db.query(models.DBContractorRating).filter(
                          models.DBContractorRating.client_id == client.id,
                          models.DBContractorRating.contractor_id == con.id).order_by(
                              models.DBContractorRating.id.desc()).limit(50).all()]
    return out


@router.post("/api/compliance/documents")
def add_document(body: ComplianceDocIn, request: Request, db: Session = Depends(get_db)):
    client, _, name = wo_actor(request, db, "billing.manage")
    con = _contractor_or_404(db, client.id, body.contractor_id)
    if body.kind not in DOC_KINDS:
        raise HTTPException(400, "Unknown document kind.")
    if not (body.valid_to or "").strip()[:10]:
        raise HTTPException(400, "Say the date it runs out.")
    row = models.DBComplianceDocument(client_id=client.id, contractor_id=con.id, kind=body.kind,
                                      number=(body.number or "").strip(), valid_from=(body.valid_from or "")[:10],
                                      valid_to=body.valid_to.strip()[:10], note=(body.note or "").strip()[:300],
                                      recorded_by_name=name)
    db.add(row)
    log_audit(db, client.id, "compliance_document_added", "contractor", con.id, con.company_name, DOC_KINDS[body.kind], request)
    db.commit()
    db.refresh(row)
    return {"ok": True, "document": doc_dict(row), "message": "%s recorded for %s." % (DOC_KINDS[body.kind], con.company_name)}


@router.delete("/api/compliance/documents/{doc_id}")
def delete_document(doc_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    row = db.query(models.DBComplianceDocument).filter(models.DBComplianceDocument.id == doc_id,
                                                       models.DBComplianceDocument.client_id == client.id).first()
    if not row:
        raise HTTPException(404, "Document not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "Removed."}


@router.get("/api/back-charges")
def list_back_charges(request: Request, contractor_id: int = 0, status: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBBackCharge).filter(models.DBBackCharge.client_id == client.id)
    if contractor_id:
        q = q.filter(models.DBBackCharge.contractor_id == contractor_id)
    if status:
        q = q.filter(models.DBBackCharge.status == status)
    rows = q.order_by(models.DBBackCharge.id.desc()).limit(500).all()
    return {"back_charges": [back_charge_dict(db, r) for r in rows]}


@router.post("/api/back-charges")
def create_back_charge(body: BackChargeIn, request: Request, db: Session = Depends(get_db)):
    client, _, name = wo_actor(request, db, "billing.manage")
    row = raise_back_charge(db, client.id, body, name)
    log_audit(db, client.id, "back_charge_raised", "back_charge", row.id, row.number, row.reason[:100], request)
    db.commit()
    db.refresh(row)
    return {"ok": True, "back_charge": back_charge_dict(db, row), "message": "%s raised." % row.number}


@router.post("/api/back-charges/{charge_id}/cancel")
def cancel_back_charge(charge_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    row = db.query(models.DBBackCharge).filter(models.DBBackCharge.id == charge_id,
                                               models.DBBackCharge.client_id == client.id).first()
    if not row:
        raise HTTPException(404, "Back-charge not found")
    if row.status != "OPEN":
        raise HTTPException(409, "Only an open back-charge can be cancelled; take it off its bill first.")
    row.status = "CANCELLED"
    log_audit(db, client.id, "back_charge_cancelled", "back_charge", row.id, row.number, "", request)
    db.commit()
    return {"ok": True, "message": "%s cancelled." % row.number}


@router.post("/api/sub-bills/{bill_id}/back-charges")
def put_back_charges_on_bill(bill_id: int, body: ApplyBackChargesIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    bill = sub_bill_or_404(db, client.id, bill_id)
    apply_back_charges(db, client.id, bill, body.ids, recost_sub_bill)
    log_audit(db, client.id, "back_charges_applied", "sub_bill", bill.id, bill.number or "", ",".join(map(str, body.ids)), request)
    db.commit()
    db.refresh(bill)
    return {"ok": True, "bill": sub_bill_dict(db, bill, detail=True), "message": "Back-charges taken off %s." % bill.number}


@router.delete("/api/sub-bills/{bill_id}/back-charges/{charge_id}")
def take_back_charge_off_bill(bill_id: int, charge_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    bill = sub_bill_or_404(db, client.id, bill_id)
    charge = db.query(models.DBBackCharge).filter(models.DBBackCharge.id == charge_id,
                                                  models.DBBackCharge.client_id == client.id,
                                                  models.DBBackCharge.applied_bill_id == bill.id).first()
    if not charge:
        raise HTTPException(404, "That back-charge is not on this bill.")
    release_back_charge(db, charge, bill, recost_sub_bill)
    db.commit()
    db.refresh(bill)
    return {"ok": True, "bill": sub_bill_dict(db, bill, detail=True), "message": "%s is open again." % charge.number}


@router.post("/api/compliance/ratings")
def rate_contractor(body: RatingIn, request: Request, db: Session = Depends(get_db)):
    client, _, name = wo_actor(request, db, "billing.manage")
    row = add_rating(db, client.id, body, name)
    db.commit()
    return {"ok": True, "score": scorecard(db, client.id, row.contractor_id), "message": "Rating saved."}


@router.get("/api/subcontract-orders/{order_id}/settlement")
def order_settlement(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return settlement(db, client.id, order_id)
