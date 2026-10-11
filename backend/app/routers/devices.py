"""Phones that have the native app and want push notifications."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.core.auth import require_erp_read
from app.core.push import push_ready
from app.schemas.devices import DeviceIn


router = APIRouter()


@router.get("/api/devices/status")
def push_status():
    """Whether the server can send pushes yet, so the app does not ask permission for nothing."""
    return {"enabled": push_ready()}


@router.post("/api/devices")
def register_device(data: DeviceIn, request: Request, db: Session = Depends(get_db)):
    """Remember this phone for the signed-in person. A token seen before is moved to whoever holds the phone now."""
    client = require_erp_read(request, db)
    employee_id = request.session.get("employee_id") or None
    token = data.token.strip()
    device = db.query(models.DBDevice).filter(models.DBDevice.token == token).first()
    if device:
        device.client_id, device.employee_id, device.platform = client.id, employee_id, data.platform
    else:
        db.add(models.DBDevice(client_id=client.id, employee_id=employee_id, token=token, platform=data.platform))
    db.commit()
    return {"ok": True}


@router.delete("/api/devices/{token}")
def forget_device(token: str, request: Request, db: Session = Depends(get_db)):
    """On sign-out: this phone stops getting this person's notices."""
    client = require_erp_read(request, db)
    db.query(models.DBDevice).filter(models.DBDevice.token == token,
                                     models.DBDevice.client_id == client.id).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}
