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
from app.models.store_core import InsufficientStockError, InvalidMovementError, StoreError, StoreFrozenError


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


@contextmanager
def store_errors():
    """Turn the module's errors into the HTTP answers a screen can show."""
    try:
        yield
    except InsufficientStockError as exc:
        raise HTTPException(409, str(exc)) from exc
    except StoreFrozenError as exc:
        raise HTTPException(423, str(exc)) from exc
    except InvalidMovementError as exc:
        raise HTTPException(400, str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from exc
