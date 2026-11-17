"""Attendance from the biometric machines: where the office program sends punches, and HR's page for it."""
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.auth import require_items_access, require_owner
from app.db import get_db, get_read_db
from app.models.biometric import DBBiometricDevice
from app.services import biometric as bio

router = APIRouter()
HR = ("people.manage", "attendance.view_team")


# --- the office program ---------------------------------------------------------------------------------------------------

@router.post("/api/biometric/punches")
def receive_punches(body: dict = Body(...), x_biometric_key: str = Header(default=""), db: Session = Depends(get_db)):
    """Punches from the office's sync program. It signs in with the key made on the Biometric tab, not as a person."""
    client = bio.client_for_key(db, x_biometric_key)
    rows = body.get("punches")
    if not isinstance(rows, list):
        raise HTTPException(400, 'Send {"punches": [{"employee_code", "time", "device", "direction"}]}.')
    result = bio.take_punches(db, client, [r for r in rows if isinstance(r, dict)], agent=body.get("agent") or "")
    db.commit()
    return result


@router.get("/api/biometric/ping")
def ping(x_biometric_key: str = Header(default=""), db: Session = Depends(get_read_db)):
    """The office program's first call: is the key right, and whose company is it."""
    client = bio.client_for_key(db, x_biometric_key)
    return {"ok": True, "company": client.company_name or ""}


# --- HR's page --------------------------------------------------------------------------------------------------------------

@router.get("/api/biometric/status")
def biometric_status(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, HR)
    return bio.status(db, client.id)


@router.post("/api/biometric/key")
def make_key(request: Request, db: Session = Depends(get_db)):
    """A new key for the office program. Shown once; the one before it stops working. The Master's to make."""
    require_owner(request, db)
    client = require_items_access(request, db, HR)
    key = bio.new_key(db, client.id)
    log_audit(db, client.id, "biometric_key_made", "settings", None, "biometric", "A new key for the attendance sync program", request)
    db.commit()
    return {"key": key, "message": "Copy this key into the sync program's settings now. It is not shown again."}


@router.post("/api/biometric/setup-package")
def setup_package(request: Request, db: Session = Depends(get_db)):
    """The office program with this company's address and a new key already in its config.ini - unzip, double-click
    SETUP.bat. The key before it stops working, so this is the Master's to press."""
    require_owner(request, db)
    client = require_items_access(request, db, HR)
    from app.core.static import _public_base
    data = bio.setup_package(db, client, _public_base(request))
    log_audit(db, client.id, "biometric_key_made", "settings", None, "biometric", "A new key, in the downloaded set-up package", request)
    db.commit()
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="YERP-biometric-setup.zip"', "Content-Length": str(len(data)), "Cache-Control": "no-store"})


@router.put("/api/biometric/devices/{device_id}")
def set_device(device_id: int, request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    client = require_items_access(request, db, "people.manage")
    d = db.query(DBBiometricDevice).filter(DBBiometricDevice.id == device_id, DBBiometricDevice.client_id == client.id).first()
    if not d:
        raise HTTPException(404, "Machine not found")
    job = int(body.get("job_id") or 0) or None
    if job and not db.query(models.DBJob.id).filter(models.DBJob.id == job, models.DBJob.client_id == client.id).first():
        raise HTTPException(404, "Project not found")
    d.name, d.job_id = (body.get("name") or d.name or "").strip()[:80], job
    db.commit()
    return {"ok": True, "message": "%s saved." % (d.name or "Machine")}


@router.put("/api/biometric/employees/{employee_id}")
def set_biometric_id(employee_id: int, request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    """A person's number on the machines, where it is not their employee code. Punches waiting for it are applied."""
    client = require_items_access(request, db, "people.manage")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == employee_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(404, "Employee not found")
    number = str(body.get("biometric_id") or "").strip()[:40]
    if number:
        taken = bio.employee_index(db, client.id).get(bio.norm_id(number))
        if taken is not None and taken.id != emp.id:
            raise HTTPException(409, "%s is %s %s's number." % (number, taken.first_name, taken.last_name))
    emp.biometric_id = number
    db.flush()
    found = bio.rematch(db, client.id)
    db.commit()
    return {"ok": True, "matched": found,
            "message": "Saved." + (" %d waiting punch%s now counted." % (found, "" if found == 1 else "es") if found else "")}


@router.post("/api/biometric/rematch")
def rematch(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "people.manage")
    found = bio.rematch(db, client.id)
    db.commit()
    return {"ok": True, "matched": found, "message": "%d punch%s matched to their people." % (found, "" if found == 1 else "es")}
