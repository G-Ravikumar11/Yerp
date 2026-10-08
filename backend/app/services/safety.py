"""The rules and workings behind the safety endpoints."""
import json
from datetime import datetime

from app.constants.quality import SERIOUS_KINDS


def incident_dict(i):
    return {"id": i.id, "job_id": i.job_id, "number": i.number, "happened_on": i.happened_on or "",
            "happened_at": i.happened_at or "", "kind": i.kind, "location": i.location or "",
            "description": i.description or "", "injured_name": i.injured_name or "", "injury": i.injury or "",
            "treatment": i.treatment or "", "lost_days": i.lost_days or 0,
            "immediate_action": i.immediate_action or "", "root_cause": i.root_cause or "",
            "corrective_action": i.corrective_action or "", "reported_by": i.reported_by or "",
            "status": i.status, "closed_on": i.closed_on or "", "closure_note": i.closure_note or "",
            "serious": i.kind in SERIOUS_KINDS}


def permit_dict(p):
    try:
        pre = json.loads(p.precautions or "[]")
    except ValueError:
        pre = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {"id": p.id, "job_id": p.job_id, "number": p.number, "kind": p.kind, "location": p.location or "",
            "description": p.description or "", "valid_from": p.valid_from or "", "valid_to": p.valid_to or "",
            "issued_by": p.issued_by or "", "receiver": p.receiver or "", "precautions": pre,
            "status": p.status, "closed_at": p.closed_at or "", "closed_by": p.closed_by or "",
            "closure_note": p.closure_note or "",
            "expired": p.status == "ACTIVE" and bool(p.valid_to) and p.valid_to < now}
