"""The Master's delete: any record, with what hangs off it, from every screen. The account Master only.

    GET    /api/master/{kind}/{id}/delete-preview     what it would take with it
    DELETE /api/master/{kind}/{id}
    POST   /api/master/{kind}/bulk-delete             {"ids": [...]}
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_client_user, require_owner
from app.core.config import logger
from app.db import get_db
from app.services import purge
from app.services.subcontract_orders import run_bulk_delete

router = APIRouter()


@router.get("/api/master/kinds")
def kinds(request: Request, db: Session = Depends(get_db)):
    get_client_user(request, db)
    require_owner(request, db)
    return {"kinds": {k: v[2] for k, v in purge.KINDS.items()}}


@router.get("/api/master/{kind}/{rec_id}/delete-preview")
def preview(kind: str, rec_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    row, table, noun, label = purge.record(db, client.id, kind, rec_id)
    counts = purge.human(purge.explain(db, table, [row.id]))
    return {"numbers": [label], "noun": noun, "counts": counts, "blockers": [], "warnings": [], "can_delete": True}


def _delete(db, request, client, kind, rec_id):
    try:
        return purge.delete_one(db, request, client, kind, rec_id)
    except IntegrityError as exc:
        db.rollback()
        logger.warning("%s %s could not be deleted: %s", kind, rec_id, exc)
        raise HTTPException(409, "Could not delete it: %s" % str(getattr(exc, "orig", exc)).splitlines()[0][:240])


@router.delete("/api/master/{kind}/{rec_id}")
def delete(kind: str, rec_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    return {"ok": True, "message": _delete(db, request, client, kind, rec_id)}


@router.post("/api/master/{kind}/bulk-delete")
def bulk_delete(kind: str, body: dict, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    purge.kind_or_404(kind)
    return run_bulk_delete(body.get("ids"), lambda i: _delete(db, request, client, kind, i), db)
