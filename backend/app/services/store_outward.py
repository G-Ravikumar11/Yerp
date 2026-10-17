"""Store module - outward slice. Owned by P3."""
from typing import List

from app.schemas.store_contracts import ReturnableOutstanding, SubconIssueLine, WriteOffRequest


def get_subcon_issues(db, subcontractor_id, upto_date) -> List[SubconIssueLine]:
    """Material issued to a subcontractor up to a date, for recovery on their RA bill."""
    # TODO(P3): read posted subcontractor issue lines.
    return []


def get_outstanding_returnables(db, project_id=None, store_id=None) -> List[ReturnableOutstanding]:
    """Returnable items and tools issued and not yet back."""
    # TODO(P3): issued less returned, per issue line.
    return []


def list_writeoff_requests(db, status="OPEN") -> List[WriteOffRequest]:
    """Requests to write off a returnable that did not come back."""
    # TODO(P3)
    return []


def close_writeoff_request(db, request_id, ref_doc_type, ref_doc_id, user_id) -> None:
    """Mark a write-off request dealt with by the document that did it (a bill recovery, an adjustment)."""
    # TODO(P3)
    return None
