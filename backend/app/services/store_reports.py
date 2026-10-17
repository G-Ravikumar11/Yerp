"""Store module - reports slice. Owned by P5."""
from decimal import Decimal
from typing import Optional


def get_theoretical_requirement(db, boq_item_id, item_id) -> Optional[Decimal]:
    """What the BOQ item should consume of an item by its quantity and norms; None when there is no norm."""
    # TODO(P5)
    return None
