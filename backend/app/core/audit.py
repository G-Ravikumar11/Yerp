"""The audit trail and login log."""
from datetime import datetime

from app import models


def log_login(db, client_id, email, user_type="client", login_type="password", request=None, status="success"):
    ip = ""
    device = ""
    if request and request.client:
        ip = request.client.host or ""
    if request:
        device = request.headers.get("user-agent", "")[:200]
    log = models.DBClientLoginLog(
        client_id=client_id, email=email, user_type=user_type,
        login_type=login_type, ip_address=ip, device_info=device,
        status=status,
    )
    db.add(log)
    if client_id:
        client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
        if client:
            client.last_login = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            client.login_count = (client.login_count or 0) + 1
    db.commit()


def log_audit(db, client_id, action, entity_type="", entity_id=None, entity_name="", details="", request=None, user_type="client", user_name=""):
    ip = ""
    if request and request.client:
        ip = request.client.host or ""
    log = models.DBAuditLog(
        client_id=client_id, user_type=user_type, user_name=user_name,
        action=action, entity_type=entity_type, entity_id=entity_id,
        entity_name=entity_name, details=details, ip_address=ip,
    )
    db.add(log)
