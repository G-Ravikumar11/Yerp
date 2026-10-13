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


def log_audit_many(db, client_id, action, entity_type, entries, request=None, user_type="client", user_name=""):
    """Several entries of one kind as a single insert. `entries` are
    (entity_id, entity_name, details). Added one by one, each is its own trip
    to the database when it is written."""
    if not entries:
        return
    from sqlalchemy import insert
    ip = (request.client.host or "") if request and request.client else ""
    db.execute(insert(models.DBAuditLog), [{
        "client_id": client_id, "user_type": user_type, "user_name": user_name,
        "action": action, "entity_type": entity_type, "entity_id": eid,
        "entity_name": name, "details": details, "ip_address": ip,
    } for eid, name, details in entries])
