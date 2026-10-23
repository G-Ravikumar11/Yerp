"""Store module - photos and papers kept against store records: a delivery challan or damage photo on a receipt, a mill certificate on a quality
check, a picture of rejected goods, a tool's service sheet. They use the app's file store (project_files); this says which records they may be kept
against, which right adds them, and when a record has been closed so its evidence stays."""
from fastapi import HTTPException

from app.models.store_control import DBStoreCount, DBStoreScrap, DBStoreTransfer
from app.models.store_extras import DBStoreRejection, DBStoreTool
from app.models.store_inward import DBStoreClientSupply, DBStoreGrn, DBStoreGrnLine, DBStoreOpening, DBStorePurchaseReturn
from app.models.store_outward import DBStoreGatePass, DBStoreIndent, DBStoreIssue, DBStoreIssueReturn, DBStoreWriteoffRequest

# attached_type -> (slice whose right adds it, the record)
TYPES = {
    "store_grn": ("inward", DBStoreGrn), "store_grn_line": ("inward", DBStoreGrnLine), "store_purchase_return": ("inward", DBStorePurchaseReturn),
    "store_client_supply": ("inward", DBStoreClientSupply), "store_opening": ("inward", DBStoreOpening), "store_rejection": ("inward", DBStoreRejection),
    "store_issue": ("outward", DBStoreIssue), "store_issue_return": ("outward", DBStoreIssueReturn), "store_indent": ("outward", DBStoreIndent),
    "store_gate_pass": ("outward", DBStoreGatePass), "store_writeoff": ("outward", DBStoreWriteoffRequest), "store_tool": ("outward", DBStoreTool),
    "store_transfer": ("control", DBStoreTransfer), "store_count": ("control", DBStoreCount), "store_scrap": ("control", DBStoreScrap),
}
CLOSED = ("POSTED", "CANCELLED", "CLOSED")


def is_store_type(attached_type) -> bool:
    return (attached_type or "") in TYPES


def right_for(attached_type) -> str:
    return "store.%s.create" % TYPES[attached_type][0]


def target(db, client_id, attached_type, attached_id):
    """(job_id, locked, store_id) for the store record a file is kept against, refused if it is not this company's. Locked once the document has
    been posted, closed or cancelled: its evidence is part of the record then."""
    if attached_type not in TYPES:
        raise HTTPException(400, "That is not something the Store keeps files against.")
    model = TYPES[attached_type][1]
    row = db.get(model, attached_id) if attached_id else None
    if row is None:
        raise HTTPException(404, "Record not found")
    if model is DBStoreGrnLine:
        row = db.get(DBStoreGrn, row.grn_id)
    if row is None or getattr(row, "client_id", None) != client_id:
        raise HTTPException(404, "Record not found")
    return getattr(row, "project_id", None), (getattr(row, "status", "") or "") in CLOSED, row.store_id
