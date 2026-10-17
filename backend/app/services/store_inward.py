"""Store module - inward slice. Owned by P2."""
from typing import List

from app.schemas.store_contracts import PoLineReceipt


def get_po_receipt_summary(db, po_id) -> List[PoLineReceipt]:
    """What has been received, accepted, rejected and is still pending on each line of a purchase order."""
    # TODO(P2): sum posted GRN lines per po_line_id.
    return []
