"""Who is calling a Store route, and the answers the Store module's errors turn into.

    actor = store_actor(request, db, "store.inward.create")      # 403 without the right (or store.admin)
    assert_store_access(actor.user, store_id)                    # 403 for a store they are not assigned to
    with store_errors():                                         # InsufficientStockError -> 409, and so on
        post_movement(db, ..., user_id=actor.user_id)
"""
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException

from app.core.auth import get_employee_user, require_items_access
from app.models.store_core import BatchOnHoldError, InsufficientStockError, InvalidMovementError, StoreError, StoreFrozenError


@dataclass
class StoreActor:
    client: object                      # the company (DBClient)
    employee: Optional[object]          # the member of staff; None for the account holder
    name: str

    @property
    def user(self):
        """What assert_store_access wants: the employee, or the company for the account holder."""
        return self.employee if self.employee is not None else self.client

    @property
    def user_id(self) -> Optional[int]:
        """What goes in a ledger's user_id: the employee's id, empty for the account holder."""
        return self.employee.id if self.employee is not None else None


def store_actor(request, db, permission) -> StoreActor:
    """The company and person behind the request, who must hold `permission` - one right, or a tuple of which any
    will do. store.admin always passes."""
    wanted = (permission,) if isinstance(permission, str) else tuple(permission)
    client = require_items_access(request, db, wanted + ("store.admin",))
    employee = None
    try:
        employee = get_employee_user(request, db)
    except HTTPException:
        pass                            # the account holder has no employee record
    name = ("%s %s" % (employee.first_name or "", employee.last_name or "")).strip() if employee else ""
    return StoreActor(client=client, employee=employee, name=name or client.company_name or "Account holder")


class LotOnHold(HTTPException):
    """409 for a lot on hold. `extra` goes into the body beside the usual fields."""

    def __init__(self, lot_id, hold_reason, code="LOT_ON_HOLD", message=BatchOnHoldError.MESSAGE):
        super().__init__(409, message)
        self.extra = {"success": False, "code": code, "message": message, "lotId": lot_id, "holdReason": hold_reason}


@contextmanager
def store_errors():
    """Turn the module's errors into the HTTP answers a screen can show."""
    try:
        yield
    except BatchOnHoldError as exc:
        raise LotOnHold(exc.lot_id, exc.hold_reason, exc.code, str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(409, str(exc)) from exc
    except StoreFrozenError as exc:
        raise HTTPException(423, str(exc)) from exc
    except InvalidMovementError as exc:
        raise HTTPException(400, str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from exc


def separate_duties(db, client_id) -> bool:
    """Whether the company keeps making and approving apart (it does unless it has turned it off)."""
    from app.models.store_core import DBStoreControlSetting
    row = db.query(DBStoreControlSetting.separate_duties).filter(DBStoreControlSetting.client_id == client_id).first()
    return True if row is None else bool(row[0])


def check_not_own(db, actor, doc, log_model, doc_type, label, also=()):
    """Approving is for someone other than whoever made or submitted the document (or, in `also`, raised what it settles).

    Staff only: the account holder answers for the company and may approve anything. A company can turn the rule off in
    the store controls."""
    if actor.employee is None or not separate_duties(db, actor.client.id):
        return
    me = actor.employee.id
    if getattr(doc, "created_by_id", None) == me:
        raise HTTPException(403, "You made this %s, so someone else has to approve it." % label.lower())
    if db.query(log_model.id).filter(log_model.doc_type == doc_type, log_model.doc_id == doc.id, log_model.action == "submit",
                                     log_model.user_id == me).first():
        raise HTTPException(403, "You submitted this %s, so someone else has to approve it." % label.lower())
    if me in set(i for i in also if i):
        raise HTTPException(403, "You raised what this %s settles, so someone else has to approve it." % label.lower())
