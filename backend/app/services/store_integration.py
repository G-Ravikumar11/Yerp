"""Store module - what the rest of the ERP (costing, billing) reads from the store. Owned by P5."""
from typing import List

from app.schemas.store_contracts import MaterialCostLine


def get_project_material_cost(db, project_id, from_date, to_date) -> List[MaterialCostLine]:
    """Material issued to a project between two dates, by cost head, work order and BOQ item."""
    # TODO(P5): group store_stock_ledger OUT entries (net of reversals) by the cost dimensions.
    return []
