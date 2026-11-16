"""Opening balances for parties: entered once, as the balance stood on the day the books begin."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.auth import require_items_access, wo_actor
from app.core.currency import inr
from app.db import get_db, get_read_db
from app.models.party_openings import DBPartyOpening
from app.schemas.party_openings import PartyOpeningIn
from app.services.party_openings import apply_opening, list_openings, number_of, one_dict, opening_or_404

router = APIRouter()
WRITE = "accounts.manage"


@router.get("/api/ledger/openings")
def openings(request: Request, db: Session = Depends(get_read_db)):
    """Every opening balance entered, newest first, and what they come to on each side."""
    client = require_items_access(request, db, "bills.view_all")
    rows = list_openings(db, client.id)
    return {"openings": rows, "summary": {
        "count": len(rows),
        "owed_to_us": round(sum(r["amount"] for r in rows if r["party_type"] == "client" and r["side"] == "owed"), 2),
        "we_owe": round(sum(r["amount"] for r in rows if r["party_type"] != "client" and r["side"] == "owed"), 2)}}


@router.post("/api/ledger/openings")
def add_opening(body: PartyOpeningIn, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, WRITE)
    o = DBPartyOpening(client_id=client.id)
    apply_opening(db, client.id, o, body, who, creating=True)
    db.add(o)
    db.flush()
    log_audit(db, client.id, "party_opening_added", "party_opening", o.id, number_of(o), "%s %s: %s as on %s" % (o.party_type, o.party_name, inr(o.amount), o.as_on),
              request=request, user_name=who)
    db.commit()
    return {"ok": True, "opening": one_dict(db, o), "message": "%s kept: %s on %s's account." % (number_of(o), inr(o.amount), o.party_name)}


@router.put("/api/ledger/openings/{opening_id}")
def change_opening(opening_id: int, body: PartyOpeningIn, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, WRITE)
    o = opening_or_404(db, client.id, opening_id)
    from app.services.money import refuse_if_locked
    refuse_if_locked(db, client.id, o.as_on, "changed")           # as it stood: moving it out of a closed period is no way round the lock
    apply_opening(db, client.id, o, body, who, creating=False)
    log_audit(db, client.id, "party_opening_changed", "party_opening", o.id, number_of(o), "%s: %s as on %s" % (o.party_name, inr(o.amount), o.as_on),
              request=request, user_name=who)
    db.commit()
    return {"ok": True, "opening": one_dict(db, o), "message": "%s saved." % number_of(o)}


@router.delete("/api/ledger/openings/{opening_id}")
def delete_opening(opening_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, WRITE)
    o = opening_or_404(db, client.id, opening_id)
    from app.services.money import refuse_if_locked
    refuse_if_locked(db, client.id, o.as_on, "taken away")
    log_audit(db, client.id, "party_opening_deleted", "party_opening", o.id, number_of(o), "%s: %s as on %s" % (o.party_name, inr(o.amount), o.as_on),
              request=request, user_name=who)
    number = number_of(o)
    db.delete(o)
    db.commit()
    return {"ok": True, "message": "%s removed. The party's balance no longer starts from it." % number}
