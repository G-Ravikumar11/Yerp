"""Store module - inward slice. Owned by P2.

What arrives at a store and is taken into stock: gate entries, goods received notes (against a purchase order, direct
without one, or supplied free by the client), their quality checks, rejection memos, and purchase returns with the debit
note they support. Stock moves only through post_movement / reverse_document:

  GRN (PO or direct)  GRN_IN            ref ("GRN", grn.id)            at the landed rate
  client supply       CLIENT_SUPPLY_IN  ref ("CLIENT_SUPPLY", grn.id)  at the agreed recovery rate
  purchase return     PURCHASE_RETURN_OUT ref ("PURCHASE_RETURN", id)  accepted material only; rejected never came in

Landed rate, per base unit = PO rate (converted from the PO's unit) + the line's share of freight, loading and other
charges (shared by received value) + GST when the company cannot recover it. Only accepted quantity posts. A line that
needs a quality check waits (QC_PENDING) and posts when the inspector records it - so a GRN can post in parts.

Purchase-order tables are read, never written.
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.core.currency import parse_tax_rate
from app.models.store_core import (
    DBStore, DBStoreDocStatusLog, DBStoreItemSettings, DBStoreUomConversion, DocStatus, InvalidMovementError, MovementType,
)
from app.models.store_inward import (
    DBStoreClientSupplyRate, DBStoreGateEntry, DBStoreGrn, DBStoreGrnLine, DBStoreGrnQc, DBStoreInwardSettings,
    DBStorePurchaseReturn, DBStorePurchaseReturnLine, DBStoreRejectionMemo, GrnKind, QcStatus, ReturnSource,
)
from app.schemas.store_contracts import PoLineReceipt
from app.services.stock_ledger import convert_to_base, post_movement, reverse_document
from app.services.store_numbering import next_doc_number

D = Decimal
ZERO = D(0)
_QTY, _RATE, _VALUE, _FACTOR, _PCT = D("0.001"), D("0.0001"), D("0.01"), D("0.000001"), D("0.001")
PO_APPROVED = "Approved"
GRN_DOC, CLIENT_DOC, RETURN_DOC, GATE_DOC = "GRN", "CLIENT_SUPPLY", "PURCHASE_RETURN", "GATE"
IN_HAND = (DocStatus.DRAFT.value, DocStatus.SUBMITTED.value, DocStatus.APPROVED.value)


def q(x, step) -> Decimal:
    return D(str(x) if not isinstance(x, Decimal) else x).quantize(step, rounding=ROUND_HALF_UP)


def plain(x) -> str:
    """12.500 -> 12.5, 40.000 -> 40: a quantity as a person writes it."""
    s = format(D(x), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def num(x, what="Number", allow_blank=True) -> Decimal:
    """A Decimal from what a screen sent; blank is nought unless it must be given."""
    if isinstance(x, Decimal):
        return x
    s = str(x if x is not None else "").strip().replace(",", "")
    if not s:
        if allow_blank:
            return ZERO
        raise HTTPException(400, "%s is missing." % what)
    try:
        out = D(s)
    except Exception:
        raise HTTPException(400, "%s is not a number: %r" % (what, x)) from None
    if not out.is_finite():
        raise HTTPException(400, "%s is not a number: %r" % (what, x))
    return out


def doc_type_of(grn) -> str:
    return CLIENT_DOC if grn.kind == GrnKind.CLIENT_SUPPLY.value else GRN_DOC


def movement_of(grn) -> MovementType:
    return MovementType.CLIENT_SUPPLY_IN if grn.kind == GrnKind.CLIENT_SUPPLY.value else MovementType.GRN_IN


# --- settings, items and units -------------------------------------------------------------------------------------

def inward_settings(db, client_id) -> DBStoreInwardSettings:
    row = db.query(DBStoreInwardSettings).filter(DBStoreInwardSettings.client_id == client_id).first()
    if row is None:
        row = DBStoreInwardSettings(client_id=client_id, gst_recoverable=True)
        db.add(row)
        db.flush()
    return row


def item_settings(db, item_id):
    return db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()


def base_uom(db, item) -> str:
    s = item_settings(db, item.id)
    return ((s.base_uom if s else item.units_of_measure) or "").strip()


def factor_of(db, item, uom) -> Decimal:
    """1 `uom` of the item = this many base units, exactly as set up (not rounded to a quantity)."""
    code = (uom or "").strip()
    if not code or code.lower() == base_uom(db, item).lower():
        return D(1)
    for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).all():
        if c.from_uom.strip().lower() == code.lower():
            return D(c.to_base_factor)
    raise HTTPException(400, "%s has no conversion from %s to %s; set it up in Store > Masters > Items & units."
                        % (item.item_code, code, base_uom(db, item)))


def item_by_code(db, client_id, code):
    code = (code or "").strip()
    if not code:
        return None
    return db.query(models.DBItem).filter(models.DBItem.client_id == client_id,
                                          func.upper(models.DBItem.item_code) == code.upper()).first()


def company_item(db, client_id, item_id):
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != client_id or item.kind != "RM" or not item.is_active:
        raise HTTPException(400, "Item %s is not a stock item of this company." % item_id)
    return item


def tolerance_pct(db, item_id) -> Decimal:
    s = item_settings(db, item_id)
    return D(s.over_receipt_tolerance_pct or 0) if s else ZERO


def steel_check(line, gate_net=None, only_line=False) -> dict:
    """Theoretical weight of the bars (d^2/162 kg a metre) against what was weighed."""
    if not line.nos or not line.dia_mm:
        return None
    length = D(line.bar_length_m or 12)
    theoretical = q(D(line.nos) * D(line.dia_mm) ** 2 / D(162) * length, _QTY)
    actual = D(line.actual_weight) if line.actual_weight is not None else (D(gate_net) if gate_net is not None and only_line else None)
    out = {"theoretical_kg": str(theoretical), "actual_kg": str(actual) if actual is not None else None,
           "variance_kg": None, "variance_pct": None}
    if actual is not None:
        out["variance_kg"] = str(q(actual - theoretical, _QTY))
        out["variance_pct"] = str(q((actual - theoretical) / theoretical * 100, D("0.01"))) if theoretical else None
    return out


# --- purchase orders (read only) -----------------------------------------------------------------------------------

def po_or_400(db, client_id, po_id, store=None):
    po = db.get(models.DBPurchaseOrder, po_id) if po_id else None
    if po is None or po.client_id != client_id:
        raise HTTPException(404, "Purchase order not found")
    if (po.status or "") != PO_APPROVED:
        raise HTTPException(400, "%s is %s; goods are received against an approved order." % (po.number, (po.status or "draft").lower()))
    if store is not None and store.project_id and po.job_id and po.job_id != store.project_id:
        raise HTTPException(400, "%s is for another project than %s." % (po.number, store.code))
    return po


def _grn_line_sums(db, po_line_ids, statuses, exclude_grn=None) -> dict:
    """{po_line_id: (received_base, accepted_base, rejected_base)} over GRNs in these statuses."""
    if not po_line_ids:
        return {}
    query = (db.query(DBStoreGrnLine.po_line_id, func.coalesce(func.sum(DBStoreGrnLine.received_base), 0),
                      func.coalesce(func.sum(DBStoreGrnLine.accepted_base), 0), func.coalesce(func.sum(DBStoreGrnLine.rejected_base), 0))
             .join(DBStoreGrn, DBStoreGrn.id == DBStoreGrnLine.grn_id)
             .filter(DBStoreGrnLine.po_line_id.in_(list(po_line_ids)), DBStoreGrn.status.in_(statuses)))
    if exclude_grn:
        query = query.filter(DBStoreGrn.id != exclude_grn)
    return {r[0]: (D(r[1]), D(r[2]), D(r[3])) for r in query.group_by(DBStoreGrnLine.po_line_id).all()}


def po_line_position(db, client_id, po, exclude_grn=None) -> list:
    """Each line of an order: what it is in stock terms and how much is still to come. Quantities are in base units
    and in the PO's own unit. Pending = ordered - accepted on posted GRNs; 'in hand' is on GRNs not yet posted."""
    lines = db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == po.id).order_by(
        models.DBPurchaseOrderLineItem.id).all()
    posted = _grn_line_sums(db, [l.id for l in lines], [DocStatus.POSTED.value], exclude_grn)
    in_hand = _grn_line_sums(db, [l.id for l in lines], IN_HAND, exclude_grn)
    out = []
    for l in lines:
        item = item_by_code(db, client_id, l.item_code)
        row = {"po_line_id": l.id, "description": l.description or "", "item_code": l.item_code or "", "po_uom": l.uom or "",
               "ordered_qty": str(q(D(str(l.qty or 0)), _QTY)), "po_rate": str(q(D(str(l.price or 0)), _RATE)),
               "gst_pct": str(q(D(str(parse_tax_rate(l.tax_rate, 0.0))) * 100, _PCT)),
               "item_id": None, "item_name": "", "base_uom": "", "factor": None, "problem": None}
        rec, acc, rej = posted.get(l.id, (ZERO, ZERO, ZERO))
        hand = in_hand.get(l.id, (ZERO, ZERO, ZERO))[0]
        if item is None or item.kind != "RM":
            row["problem"] = "Not a stock item (no item code %r in the Item Master)." % (l.item_code or "")
        else:
            row.update(item_id=item.id, item_name=item.item_name, base_uom=base_uom(db, item))
            try:
                f = factor_of(db, item, l.uom)
            except HTTPException as exc:
                row["problem"] = exc.detail
                f = None
            if f:
                ordered_base = q(D(str(l.qty or 0)) * f, _QTY)
                pending = max(ordered_base - acc, ZERO)
                tol = tolerance_pct(db, item.id)
                row.update(factor=str(q(f, _FACTOR)), ordered_base=str(ordered_base), received_base=str(rec), accepted_base=str(acc),
                           rejected_base=str(rej), in_hand_base=str(hand), pending_base=str(pending),
                           pending_qty=str(q(pending / f, _QTY)), tolerance_pct=str(tol),
                           max_receivable_base=str(max(q(ordered_base * (1 + tol / 100), _QTY) - acc - hand, ZERO)),
                           base_rate=str(q(D(str(l.price or 0)) / f, _RATE)))
        out.append(row)
    return out


def approved_pos(db, client_id, store=None) -> list:
    query = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id,
                                                    models.DBPurchaseOrder.status == PO_APPROVED)
    if store is not None and store.project_id:
        query = query.filter((models.DBPurchaseOrder.job_id == store.project_id) | (models.DBPurchaseOrder.job_id.is_(None)))
    return query.order_by(models.DBPurchaseOrder.id.desc()).all()


def get_po_receipt_summary(db, po_id) -> List[PoLineReceipt]:
    """What has been received, accepted, rejected and is still pending on each line of a purchase order, in the
    order's own unit for each line, from posted GRNs. A line whose material is not a stock item (no item code, or a
    unit with no conversion) shows what it ordered, nothing received, all of it pending."""
    po = db.get(models.DBPurchaseOrder, po_id) if po_id else None
    if po is None:
        return []
    out = []
    for row in po_line_position(db, po.client_id, po):
        ordered = D(row["ordered_qty"])
        if row.get("factor"):
            f = D(row["factor"])
            rec, acc, rej = (q(D(row[k]) / f, _QTY) for k in ("received_base", "accepted_base", "rejected_base"))
        else:
            rec = acc = rej = ZERO
        out.append(PoLineReceipt(po_line_id=row["po_line_id"], item_id=row["item_id"], ordered_qty=ordered, received_qty=rec,
                                 accepted_qty=acc, rejected_qty=rej, pending_qty=max(ordered - acc, ZERO)))
    return out


def pending_to_receive(db, client_id, group="po", store=None) -> list:
    """Approved orders with something still to come, by order or by vendor, valued at the PO rate."""
    rows = []
    for po in approved_pos(db, client_id, store):
        for l in po_line_position(db, client_id, po):
            if not l.get("factor") or D(l["pending_base"]) <= 0:
                continue
            value = q(D(l["pending_base"]) * D(l["base_rate"]), _VALUE)
            rows.append({"po_id": po.id, "po_number": po.number, "vendor": po.supplier_name or "", "project_id": po.job_id,
                         "needed_by": po.needed_by or "", "po_line_id": l["po_line_id"], "item_id": l["item_id"],
                         "item_code": l["item_code"], "item_name": l["item_name"], "po_uom": l["po_uom"],
                         "ordered_qty": l["ordered_qty"], "pending_qty": l["pending_qty"], "pending_base": l["pending_base"],
                         "base_uom": l["base_uom"], "in_hand_base": l["in_hand_base"], "pending_value": str(value)})
    if group == "lines":
        return rows
    acc = {}
    for r in rows:
        key = r["po_id"] if group == "po" else (r["vendor"] or "-").strip().lower()
        a = acc.setdefault(key, {"po_id": r["po_id"] if group == "po" else None, "po_number": r["po_number"] if group == "po" else None,
                                 "vendor": r["vendor"], "lines": 0, "pending_value": ZERO, "orders": set(), "items": []})
        a["lines"] += 1
        a["pending_value"] += D(r["pending_value"])
        a["orders"].add(r["po_number"])
        a["items"].append(r)
    out = []
    for a in acc.values():
        a["orders"] = sorted(a["orders"])
        a["pending_value"] = str(q(a["pending_value"], _VALUE))
        out.append(a)
    out.sort(key=lambda a: -D(a["pending_value"]))
    return out


# --- client supply rates -------------------------------------------------------------------------------------------

def client_rate(db, work_order_id, item_id):
    return db.query(DBStoreClientSupplyRate).filter(DBStoreClientSupplyRate.work_order_id == work_order_id,
                                                    DBStoreClientSupplyRate.item_id == item_id).first()


def client_work_order(db, client_id, work_order_id, store=None):
    wo = db.get(models.DBWorkOrder, work_order_id) if work_order_id else None
    if wo is None or wo.client_id != client_id:
        raise HTTPException(400, "Choose the client work order the material is supplied under.")
    if store is not None and store.project_id and wo.job_id != store.project_id:
        raise HTTPException(400, "%s is for another project than %s." % (wo.number, store.code))
    return wo


# --- building a GRN's lines ----------------------------------------------------------------------------------------

def build_lines(db, client_id, store, grn, lines_in) -> list:
    """Lines as typed -> DBStoreGrnLine rows (not added), worked out and checked. Raises 400 naming the line."""
    if not lines_in:
        raise HTTPException(400, "Add at least one line.")
    kind = grn.kind
    po_rows = {}
    if kind == GrnKind.PO.value:
        po = po_or_400(db, client_id, grn.po_id, store)
        po_rows = {r["po_line_id"]: r for r in po_line_position(db, client_id, po, exclude_grn=grn.id)}
    out, seen = [], set()
    for n, li in enumerate(lines_in, 1):
        def bad(msg):
            raise HTTPException(400, "Line %d: %s" % (n, msg))
        if kind == GrnKind.PO.value:
            pr = po_rows.get(li.get("po_line_id"))
            if pr is None:
                bad("that line is not on %s." % grn_po_number(db, grn))
            if pr["problem"]:
                bad(pr["problem"])
            if pr["po_line_id"] in seen:
                bad("the same PO line appears twice.")
            seen.add(pr["po_line_id"])
            item = db.get(models.DBItem, pr["item_id"])
        else:
            item = company_item(db, client_id, li.get("item_id"))
            if item.id in seen:
                bad("%s appears twice." % item.item_code)
            seen.add(item.id)
        uom = (li.get("uom") or "").strip() or base_uom(db, item)
        f = factor_of(db, item, uom)
        received, accepted, rejected, shortage = (q(num(li.get(k), k.replace("_", " ").capitalize()), _QTY)
                                                  for k in ("received_qty", "accepted_qty", "rejected_qty", "shortage_qty"))
        if min(received, accepted, rejected, shortage) < 0:
            bad("quantities cannot be negative.")
        if received <= 0:
            bad("enter the quantity received.")
        cfg = item_settings(db, item.id)
        qc = bool(cfg and cfg.qc_required)
        if qc:
            accepted = rejected = ZERO              # the inspector decides
        elif accepted + rejected != received:
            bad("accepted (%s) and rejected (%s) must add up to received (%s)." % (plain(accepted), plain(rejected), plain(received)))
        line = DBStoreGrnLine(line_no=n, po_line_id=li.get("po_line_id") if kind == GrnKind.PO.value else None, item_id=item.id,
                              uom=uom, factor=q(f, _FACTOR), received_qty=received, accepted_qty=accepted, rejected_qty=rejected,
                              shortage_qty=shortage, received_base=convert_to_base(db, item.id, received, uom),
                              accepted_base=convert_to_base(db, item.id, accepted, uom), rejected_base=convert_to_base(db, item.id, rejected, uom),
                              shortage_base=convert_to_base(db, item.id, shortage, uom),
                              qc_status=(QcStatus.QC_PENDING if qc else QcStatus.NOT_REQUIRED).value,
                              batch_no=(li.get("batch_no") or "").strip()[:60], mtc_ref=(li.get("mtc_ref") or "").strip()[:80],
                              bundles=li.get("bundles") or None, nos=li.get("nos") or None,
                              dia_mm=q(num(li.get("dia_mm")), _QTY) if li.get("dia_mm") not in (None, "") else None,
                              bar_length_m=q(num(li.get("bar_length_m")), _QTY) if li.get("bar_length_m") not in (None, "") else None,
                              actual_weight=q(num(li.get("actual_weight")), _QTY) if li.get("actual_weight") not in (None, "") else None,
                              remarks=(li.get("remarks") or "")[:400])
        if kind == GrnKind.PO.value:
            line.base_rate, line.gst_pct = D(pr["base_rate"]), D(pr["gst_pct"])
            # Over-receipt: what is already accepted, what other GRNs have in hand and this one, within the tolerance.
            if line.received_base > D(pr["max_receivable_base"]):
                bad("%s %s received is more than the order allows: %s %s still to come%s." % (
                    plain(received), uom, plain(q(max(D(pr["pending_base"]) - D(pr["in_hand_base"]), ZERO) / f, _QTY)), uom,
                    (" (with %s%% tolerance, at most %s %s)" % (plain(pr["tolerance_pct"]), plain(q(D(pr["max_receivable_base"]) / f, _QTY)), uom))
                    if D(pr["tolerance_pct"]) else ""))
        elif kind == GrnKind.CLIENT_SUPPLY.value:
            agreed = client_rate(db, grn.work_order_id, item.id)
            if agreed is None:
                bad("no agreed rate for %s on this work order; set it under Client supply rates." % item.item_code)
            line.base_rate, line.gst_pct = D(agreed.rate), ZERO
        else:
            rate = q(num(li.get("rate"), "Rate", allow_blank=False), _RATE)
            if rate < 0:
                bad("the rate cannot be negative.")
            line.base_rate, line.gst_pct = q(rate / f, _RATE), q(num(li.get("gst_pct")), _PCT)
        if not (0 <= D(line.gst_pct) <= 100):
            bad("GST is a percentage.")
        out.append(line)
    return out


def grn_po_number(db, grn):
    po = db.get(models.DBPurchaseOrder, grn.po_id) if grn.po_id else None
    return po.number if po else "the order"


def apportion(grn, lines):
    """Share freight, loading and other charges over the lines by received value, to the paisa (the last line takes
    what rounding leaves), and set each line's landed rate per base unit."""
    charges = D(grn.freight or 0) + D(grn.loading or 0) + D(grn.other_charges or 0)
    basis = [D(l.received_base) * D(l.base_rate) for l in lines]
    total = sum(basis, ZERO)
    left = charges
    for i, (l, b) in enumerate(zip(lines, basis)):
        if i == len(lines) - 1:
            share = left
        else:
            share = q(charges * b / total, _VALUE) if total else ZERO
            left -= share
        l.charges_share = share
        rate = D(l.base_rate)
        if not grn.gst_recoverable:
            rate += rate * D(l.gst_pct) / 100
        if D(l.received_base) > 0:
            rate += share / D(l.received_base)
        l.landed_rate = q(rate, _RATE)


def replace_lines(db, client_id, store, grn, lines_in):
    built = build_lines(db, client_id, store, grn, lines_in)
    db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id == grn.id).delete(synchronize_session=False)
    for l in built:
        l.grn_id = grn.id
        db.add(l)
    apportion(grn, built)
    db.flush()
    return built


def grn_lines(db, grn) -> list:
    return db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id == grn.id).order_by(DBStoreGrnLine.line_no).all()


# --- the lifecycle -------------------------------------------------------------------------------------------------

def log(db, client_id, doc_type, doc_id, was, to, actor, note=""):
    db.add(DBStoreDocStatusLog(client_id=client_id, doc_type=doc_type, doc_id=doc_id, from_status=was, to_status=to,
                               user_id=actor.user_id, user_name=actor.name, note=note or "", at=datetime.now()))


def check_ready(db, grn, lines):
    """What a GRN must have before it goes for approval."""
    for l in lines:
        cfg = item_settings(db, l.item_id)
        if cfg and cfg.is_batch_tracked and not (l.batch_no and l.mtc_ref):
            item = db.get(models.DBItem, l.item_id)
            raise HTTPException(400, "Line %d: %s is batch tracked; give its batch / heat number and mill test certificate."
                                % (l.line_no, item.item_code))
    if grn.kind == GrnKind.DIRECT.value and not (grn.reason or "").strip():
        raise HTTPException(400, "Say why this was bought without a purchase order.")


def _post_line(db, grn, line, actor, day):
    if line.posted or D(line.accepted_base) <= 0 or line.qc_status == QcStatus.QC_PENDING.value:
        return None
    entry = post_movement(db, movement_type=movement_of(grn), store_id=grn.store_id, item_id=line.item_id, qty=D(line.accepted_base),
                          rate=D(line.landed_rate), txn_date=day, project_id=grn.project_id, ref_doc_type=doc_type_of(grn),
                          ref_doc_id=grn.id, ref_line_id=line.id, user_id=actor.user_id, work_order_id=grn.work_order_id,
                          remarks="%s line %d" % (grn.number, line.line_no))
    line.posted = True
    return entry


def ensure_rejection_memo(db, grn):
    if db.query(DBStoreRejectionMemo.id).filter(DBStoreRejectionMemo.grn_id == grn.id).first():
        return
    if any(D(l.rejected_base) > 0 for l in grn_lines(db, grn)):
        db.add(DBStoreRejectionMemo(grn_id=grn.id, number=next_doc_number(db, "RJM", grn.store_id, on_date=date.today())))
        db.flush()


def post_grn(db, grn, actor):
    """Every line that is ready, in one go: accepted quantity at its landed rate. QC-pending lines wait for the
    inspector and post then. The over-receipt check is made again here, against what is posted now."""
    lines = grn_lines(db, grn)
    check_ready(db, grn, lines)
    if grn.kind == GrnKind.PO.value:
        po = db.get(models.DBPurchaseOrder, grn.po_id)
        rows = {r["po_line_id"]: r for r in po_line_position(db, grn.client_id, po, exclude_grn=grn.id)}
        for l in lines:
            r = rows.get(l.po_line_id)
            ceiling = q(D(r["ordered_base"]) * (1 + D(r["tolerance_pct"]) / 100), _QTY) - D(r["accepted_base"])
            if D(l.accepted_base) > ceiling:
                raise HTTPException(409, "Line %d: accepting %s %s would take %s past its order (at most %s more)." % (
                    l.line_no, plain(l.accepted_qty), l.uom, po.number, plain(q(max(ceiling, ZERO) / D(l.factor), _QTY))))
    for l in lines:
        _post_line(db, grn, l, actor, grn.grn_date)
    grn.posted_at = datetime.now()
    ensure_rejection_memo(db, grn)


def record_qc(db, grn, line, actor, accepted, rejected, test_type="", test_ref="", remarks=""):
    """The inspector's verdict on a line. Once the GRN is posted, its accepted quantity goes into stock now."""
    if line.qc_status != QcStatus.QC_PENDING.value:
        raise HTTPException(409, "Line %d is not waiting for a quality check." % line.line_no)
    if grn.status not in (DocStatus.SUBMITTED.value, DocStatus.APPROVED.value, DocStatus.POSTED.value):
        raise HTTPException(409, "A %s GRN is not inspected." % grn.status.lower())
    accepted, rejected = q(num(accepted, "Accepted", False), _QTY), q(num(rejected, "Rejected", False), _QTY)
    if accepted < 0 or rejected < 0 or accepted + rejected != D(line.received_qty):
        raise HTTPException(400, "Accepted (%s) and rejected (%s) must add up to the %s %s received."
                            % (plain(accepted), plain(rejected), plain(line.received_qty), line.uom))
    if not (test_ref or "").strip():
        raise HTTPException(400, "Give the test reference (cube / setting test, TC number ...).")
    line.accepted_qty, line.rejected_qty = accepted, rejected
    line.accepted_base = convert_to_base(db, line.item_id, accepted, line.uom)
    line.rejected_base = convert_to_base(db, line.item_id, rejected, line.uom)
    line.qc_status = QcStatus.DONE.value
    db.add(DBStoreGrnQc(grn_line_id=line.id, accepted_qty=accepted, rejected_qty=rejected, test_type=(test_type or "").strip(),
                        test_ref=test_ref.strip(), remarks=(remarks or "").strip(), inspector_id=actor.user_id, inspector_name=actor.name))
    db.flush()
    if grn.status == DocStatus.POSTED.value:
        # After the posting date other movements may have happened; the line goes in on the day it was passed.
        _post_line(db, grn, line, actor, max(date.today(), grn.grn_date))
        ensure_rejection_memo(db, grn)
    log(db, grn.client_id, doc_type_of(grn), grn.id, grn.status, grn.status, actor,
        "QC line %d: %s accepted, %s rejected (%s)" % (line.line_no, accepted, rejected, test_ref.strip()))


def open_returns(db, grn_id):
    return db.query(DBStorePurchaseReturn).filter(DBStorePurchaseReturn.grn_id == grn_id,
                                                  DBStorePurchaseReturn.status != DocStatus.CANCELLED.value).all()


def cancel_grn(db, grn, actor, reason):
    """Back out a GRN. A posted one is reversed - refused, with the item and quantity named, if the stock has been
    issued since - and one with a live purchase return must have the return cancelled first."""
    live = open_returns(db, grn.id)
    if live:
        raise HTTPException(409, "Cancel purchase return %s first." % ", ".join(r.number for r in live))
    if grn.status == DocStatus.POSTED.value and any(l.posted for l in grn_lines(db, grn)):
        reverse_document(db, ref_doc_type=doc_type_of(grn), ref_doc_id=grn.id, user_id=actor.user_id, reason=reason)
    grn.cancel_reason = reason
    if grn.gate_entry_id:
        gate = db.get(DBStoreGateEntry, grn.gate_entry_id)
        if gate and gate.status == "GRN_MADE" and not db.query(DBStoreGrn.id).filter(
                DBStoreGrn.gate_entry_id == gate.id, DBStoreGrn.id != grn.id, DBStoreGrn.status != DocStatus.CANCELLED.value).first():
            gate.status = "OPEN"


# --- purchase returns ----------------------------------------------------------------------------------------------

def returned_so_far(db, grn_line_id, source, exclude_return=None) -> Decimal:
    query = (db.query(func.coalesce(func.sum(DBStorePurchaseReturnLine.qty_base), 0))
             .join(DBStorePurchaseReturn, DBStorePurchaseReturn.id == DBStorePurchaseReturnLine.return_id)
             .filter(DBStorePurchaseReturnLine.grn_line_id == grn_line_id, DBStorePurchaseReturnLine.source == source,
                     DBStorePurchaseReturn.status != DocStatus.CANCELLED.value))
    if exclude_return:
        query = query.filter(DBStorePurchaseReturn.id != exclude_return)
    return D(query.scalar() or 0)


def build_return_lines(db, grn, lines_in, exclude_return=None) -> list:
    if grn.status != DocStatus.POSTED.value:
        raise HTTPException(409, "Goods go back against a posted GRN.")
    if grn.kind == GrnKind.CLIENT_SUPPLY.value:
        raise HTTPException(400, "Client-supplied material is not returned to a supplier.")
    by_id = {l.id: l for l in grn_lines(db, grn)}
    out = []
    for n, li in enumerate(lines_in or [], 1):
        gl = by_id.get(li.get("grn_line_id"))
        if gl is None:
            raise HTTPException(400, "Line %d: not a line of %s." % (n, grn.number))
        try:
            source = ReturnSource(li.get("source") or ReturnSource.REJECTED.value)
        except ValueError:
            raise HTTPException(400, "Line %d: return what was REJECTED or what was ACCEPTED." % n) from None
        qty = q(num(li.get("qty"), "Quantity", False), _QTY)
        if qty <= 0:
            raise HTTPException(400, "Line %d: enter the quantity going back." % n)
        qty_base = convert_to_base(db, gl.item_id, qty, gl.uom)
        if source == ReturnSource.REJECTED:
            room = D(gl.rejected_base) - returned_so_far(db, gl.id, source.value, exclude_return)
        else:
            room = (D(gl.accepted_base) if gl.posted else ZERO) - returned_so_far(db, gl.id, source.value, exclude_return)
        if qty_base > room:
            raise HTTPException(400, "Line %d: only %s %s %s is left to return." % (
                n, plain(q(max(room, ZERO) / D(gl.factor), _QTY)), gl.uom, "rejected" if source == ReturnSource.REJECTED else "accepted"))
        out.append(DBStorePurchaseReturnLine(grn_line_id=gl.id, item_id=gl.item_id, source=source.value, qty=qty, qty_base=qty_base,
                                             rate=D(gl.base_rate), gst_pct=D(gl.gst_pct), remarks=(li.get("remarks") or "")[:400]))
    if not out:
        raise HTTPException(400, "Add at least one line.")
    return out


def return_lines(db, ret) -> list:
    return db.query(DBStorePurchaseReturnLine).filter(DBStorePurchaseReturnLine.return_id == ret.id).order_by(
        DBStorePurchaseReturnLine.id).all()


def post_return(db, ret, actor):
    """Accepted material leaves stock as PURCHASE_RETURN_OUT (valued at the average); rejected material only debits."""
    grn = db.get(DBStoreGrn, ret.grn_id)
    # Checked again: another return against the same GRN may have been posted since this one was raised.
    build_return_lines(db, grn, [{"grn_line_id": l.grn_line_id, "source": l.source, "qty": l.qty} for l in return_lines(db, ret)],
                       exclude_return=ret.id)
    for l in return_lines(db, ret):
        if l.source == ReturnSource.ACCEPTED.value:
            post_movement(db, movement_type=MovementType.PURCHASE_RETURN_OUT, store_id=ret.store_id, item_id=l.item_id,
                          qty=D(l.qty_base), rate=None, txn_date=ret.return_date, project_id=grn.project_id,
                          ref_doc_type=RETURN_DOC, ref_doc_id=ret.id, ref_line_id=l.id, user_id=actor.user_id,
                          remarks="%s against %s" % (ret.number, grn.number))
    ret.posted_at = datetime.now()


def cancel_return(db, ret, actor, reason):
    if ret.status == DocStatus.POSTED.value and any(l.source == ReturnSource.ACCEPTED.value for l in return_lines(db, ret)):
        reverse_document(db, ref_doc_type=RETURN_DOC, ref_doc_id=ret.id, user_id=actor.user_id, reason=reason)
    ret.cancel_reason = reason


def debit_note(db, ret) -> dict:
    """What the supplier is debited: each line's quantity at the PO rate, and the GST on it."""
    grn = db.get(DBStoreGrn, ret.grn_id)
    po = db.get(models.DBPurchaseOrder, grn.po_id) if grn.po_id else None
    supplier = db.get(models.DBSupplier, grn.supplier_id) if grn.supplier_id else None
    lines, taxable, gst = [], ZERO, ZERO
    for l in return_lines(db, ret):
        item = db.get(models.DBItem, l.item_id)
        gl = db.get(DBStoreGrnLine, l.grn_line_id)
        value = q(D(l.qty_base) * D(l.rate), _VALUE)
        tax = q(value * D(l.gst_pct) / 100, _VALUE)
        taxable, gst = taxable + value, gst + tax
        lines.append({"item_id": item.id, "item_code": item.item_code, "item_name": item.item_name, "source": l.source,
                      "qty": str(l.qty), "uom": gl.uom, "qty_base": str(l.qty_base), "base_uom": base_uom(db, item),
                      "rate": str(q(D(l.rate), _RATE)), "taxable_value": str(value), "gst_pct": str(q(D(l.gst_pct), _PCT)),
                      "gst": str(tax), "total": str(value + tax)})
    return {"return_id": ret.id, "number": ret.number, "date": ret.return_date.isoformat(), "status": ret.status,
            "grn_number": grn.number, "po_number": po.number if po else None, "invoice_no": grn.invoice_no or "",
            "vendor": grn.vendor_name or (supplier.name if supplier else ""), "vendor_gstin": supplier.gstin if supplier else "",
            "lines": lines, "taxable_value": str(q(taxable, _VALUE)), "gst": str(q(gst, _VALUE)), "total": str(q(taxable + gst, _VALUE))}
