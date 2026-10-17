"""Store module - control slice. Owned by P4."""
from typing import List

from app.schemas.store_contracts import CountVarianceLine, InTransitLine, ScrapLine


def get_in_transit(db, project_id=None) -> List[InTransitLine]:
    """Stock sent from one store and not yet received at the other."""
    # TODO(P4)
    return []


def get_count_variances(db, store_id, from_date, to_date) -> List[CountVarianceLine]:
    """What stock counts found against the books, between two dates."""
    # TODO(P4)
    return []


def get_scrap_realisation(db, project_id, from_date, to_date) -> List[ScrapLine]:
    """Scrap sold or written off for a project: book value against what it fetched."""
    # TODO(P4)
    return []
