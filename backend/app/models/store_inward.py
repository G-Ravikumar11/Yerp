"""Store module - inward tables (gate entries, GRNs and their quality checks, rejection memos, purchase returns, the
agreed rates for client-supplied material). Owned by P2. Migration store_003_inward (down revision store_001_core): all
new tables, made by create_all; no shared table is touched.

Quantities are kept twice on a GRN line: as entered (in any of the item's units) and in the item's base unit, which is
what posts. Rates on a line are per base unit.
"""
import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base
from app.models.store_core import FACTOR, PERCENT, QTY, RATE, VALUE, DocStatus

REVISION_INWARD = "store_003_inward"
DOWN_REVISION_INWARD = "store_001_core"


class GrnKind(str, enum.Enum):
    PO = "PO"                           # against an approved purchase order
    DIRECT = "DIRECT"                   # emergency / cash purchase without a PO: needs a reason and an approver
    CLIENT_SUPPLY = "CLIENT_SUPPLY"     # given free by the client, valued at the agreed recovery rate


class QcStatus(str, enum.Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    QC_PENDING = "QC_PENDING"
    DONE = "DONE"


class ReturnSource(str, enum.Enum):
    REJECTED = "REJECTED"               # never entered stock: a debit note only
    ACCEPTED = "ACCEPTED"               # taken into stock and now sent back: PURCHASE_RETURN_OUT


class DBStoreInwardSettings(Base):
    """A company's inward rules."""
    __tablename__ = "store_inward_settings"
    __table_args__ = (UniqueConstraint("client_id", name="uq_store_inward_settings_client"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    # Input GST the company can claim back is not a cost of the material and stays out of stock value; when it cannot
    # be claimed (exempt supply, composition scheme) it is part of what the material cost.
    gst_recoverable = Column(Boolean, default=True, nullable=False)


class DBStoreGateEntry(Base):
    """A vehicle at the gate with material: the inward register."""
    __tablename__ = "store_gate_entry"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)           # GATE/CS01/26-27/00001
    entry_date = Column(Date, nullable=False)
    time_in = Column(String, default="")                          # 14:35
    vehicle_no = Column(String, default="")
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    vendor_name = Column(String, default="")
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    challan_no = Column(String, default="")
    challan_date = Column(Date, nullable=True)
    weighbridge_slip_no = Column(String, default="")
    gross_weight = Column(QTY, nullable=True)                     # kg
    tare_weight = Column(QTY, nullable=True)
    net_weight = Column(QTY, nullable=True)
    remarks = Column(Text, default="")
    status = Column(String, default="OPEN", index=True)           # OPEN | GRN_MADE | CANCELLED
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class DBStoreGrn(Base):
    """A goods received note. Posts GRN_IN (ref GRN) - or CLIENT_SUPPLY_IN (ref CLIENT_SUPPLY) - for accepted quantity."""
    __tablename__ = "store_grn"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)           # GRN/CS01/26-27/00001, CSR/... for client supply
    kind = Column(String, nullable=False, default=GrnKind.PO.value, index=True)
    grn_date = Column(Date, nullable=False)
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True, index=True)
    gate_entry_id = Column(Integer, ForeignKey("store_gate_entry.id"), nullable=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)   # client supply
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    vendor_name = Column(String, default="")
    challan_no = Column(String, default="")
    challan_date = Column(Date, nullable=True)
    invoice_no = Column(String, default="")
    invoice_date = Column(Date, nullable=True)
    freight = Column(VALUE, default=0)
    loading = Column(VALUE, default=0)
    other_charges = Column(VALUE, default=0)
    gst_recoverable = Column(Boolean, default=True, nullable=False)
    reason = Column(Text, default="")                             # why a direct receipt had no PO
    remarks = Column(Text, default="")
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)
    cancel_reason = Column(Text, default="")


class DBStoreGrnLine(Base):
    __tablename__ = "store_grn_line"

    id = Column(Integer, primary_key=True, index=True)
    grn_id = Column(Integer, ForeignKey("store_grn.id"), nullable=False, index=True)
    line_no = Column(Integer, nullable=False, default=1)
    po_line_id = Column(Integer, ForeignKey("purchase_order_line_items.id"), nullable=True, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    uom = Column(String, nullable=False)                          # the unit the quantities below were entered in
    factor = Column(FACTOR, nullable=False, default=1)            # 1 uom = factor x base unit
    received_qty = Column(QTY, nullable=False, default=0)
    accepted_qty = Column(QTY, nullable=False, default=0)
    rejected_qty = Column(QTY, nullable=False, default=0)
    shortage_qty = Column(QTY, nullable=False, default=0)         # on the challan but not on the vehicle
    received_base = Column(QTY, nullable=False, default=0)
    accepted_base = Column(QTY, nullable=False, default=0)
    rejected_base = Column(QTY, nullable=False, default=0)
    shortage_base = Column(QTY, nullable=False, default=0)
    base_rate = Column(RATE, nullable=False, default=0)           # PO / agreed rate per base unit, before charges and GST
    gst_pct = Column(PERCENT, nullable=False, default=0)
    charges_share = Column(VALUE, nullable=False, default=0)      # this line's part of freight, loading and other charges
    landed_rate = Column(RATE, nullable=False, default=0)         # what a base unit is taken into stock at
    qc_status = Column(String, nullable=False, default=QcStatus.NOT_REQUIRED.value)
    batch_no = Column(String, default="")                         # batch or heat number
    mtc_ref = Column(String, default="")                          # mill test certificate
    bundles = Column(Integer, nullable=True)                      # steel
    nos = Column(Integer, nullable=True)
    dia_mm = Column(QTY, nullable=True)
    bar_length_m = Column(QTY, nullable=True)
    actual_weight = Column(QTY, nullable=True)                    # kg on the weighbridge, for this line
    posted = Column(Boolean, nullable=False, default=False)       # its accepted quantity is in stock
    remarks = Column(String, default="")


class DBStoreGrnQc(Base):
    """An inspector's result for one GRN line."""
    __tablename__ = "store_grn_qc"

    id = Column(Integer, primary_key=True, index=True)
    grn_line_id = Column(Integer, ForeignKey("store_grn_line.id"), nullable=False, index=True)
    accepted_qty = Column(QTY, nullable=False)                    # in the line's unit
    rejected_qty = Column(QTY, nullable=False)
    test_type = Column(String, default="")                        # cube / setting time / tensile ...
    test_ref = Column(String, default="")                         # lab report or TC number
    remarks = Column(Text, default="")
    inspector_id = Column(Integer, nullable=True)
    inspector_name = Column(String, default="")
    inspected_at = Column(DateTime, default=datetime.now)


class DBStoreRejectionMemo(Base):
    """The memo to the supplier for what a GRN rejected. One per GRN, numbered when there is first something rejected."""
    __tablename__ = "store_rejection_memo"
    __table_args__ = (UniqueConstraint("grn_id", name="uq_store_rejection_memo_grn"),)

    id = Column(Integer, primary_key=True, index=True)
    grn_id = Column(Integer, ForeignKey("store_grn.id"), nullable=False, index=True)
    number = Column(String, nullable=False)                       # RJM/CS01/26-27/00001
    created_at = Column(DateTime, default=datetime.now)


class DBStorePurchaseReturn(Base):
    """Material sent back to the supplier against a GRN, with the debit note it supports. Posts PURCHASE_RETURN_OUT
    (ref PURCHASE_RETURN) for what had been accepted into stock; rejected material never entered stock and only debits."""
    __tablename__ = "store_purchase_return"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    grn_id = Column(Integer, ForeignKey("store_grn.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)           # PRN/CS01/26-27/00001
    return_date = Column(Date, nullable=False)
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    reason = Column(Text, default="")
    vehicle_no = Column(String, default="")
    remarks = Column(Text, default="")
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)
    cancel_reason = Column(Text, default="")


class DBStorePurchaseReturnLine(Base):
    __tablename__ = "store_purchase_return_line"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("store_purchase_return.id"), nullable=False, index=True)
    grn_line_id = Column(Integer, ForeignKey("store_grn_line.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    source = Column(String, nullable=False, default=ReturnSource.REJECTED.value)
    qty = Column(QTY, nullable=False)                             # in the GRN line's unit
    qty_base = Column(QTY, nullable=False)
    rate = Column(RATE, nullable=False)                           # debit rate per base unit (the PO rate)
    gst_pct = Column(PERCENT, nullable=False, default=0)
    remarks = Column(String, default="")


class DBStoreClientSupplyRate(Base):
    """The rate a client work order fixes for material the client supplies (and recovers), per base unit of the item."""
    __tablename__ = "store_client_supply_rate"
    __table_args__ = (UniqueConstraint("work_order_id", "item_id", name="uq_store_client_supply_rate"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    rate = Column(RATE, nullable=False)
    reference = Column(String, default="")                        # the clause or annexure of the contract
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
