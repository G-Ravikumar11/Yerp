"""The invoice tracker: what was bought, from whom, on which supplier invoice, and whether the bill adds up.

Built from posted goods receipts, so nothing is keyed twice. The supplier's own bill (its date, its printed total,
freight, insurance, hamali, a remark), the rate a material is being worked at, and the block a lorry of concrete went
into are the only things typed in, because a receipt does not carry them. Work-order values come from the committed
subcontract work orders, by work type.
"""
import re
from collections import OrderedDict
from types import SimpleNamespace

from app import models
from app.constants.subcontract_orders import WO_COMMITTED_STATUSES
from app.core.currency import money, unit_rate
from app.core.queries import by_id, prime
from app.services.store_integration import current_stock

DEFAULT_GST = 18.0
DEFAULT_MARKUP = 20.0       # installation + consumables + wastage + overhead and profit, on the basic rate
CHARGE_KINDS = ("insurance", "hamali")
RMC_WORDS = re.compile(r"\b(rmc|ready\s*-?\s*mix(ed)?|concrete)\b", re.I)
GRADE = re.compile(r"\bM\s*-?\s*(\d{1,2}(?:\.\d)?)\b", re.I)
UNCATEGORISED = "Uncategorised"


def _text(v):
    return (v or "").strip()


def _category(item):
    return _text(item.item_category if item else "") or UNCATEGORISED


def _grade(line, item):
    for text in ((item.specification if item else ""), line.description or "", line.item_code or ""):
        m = GRADE.search(text or "")
        if m:
            return "M" + m.group(1)
    return ""


def is_rmc(category, line, item):
    return bool(RMC_WORDS.search(category or "") or RMC_WORDS.search(line.description or "")
                or (item and RMC_WORDS.search(item.item_name or "")))


def is_rmc_name(category):
    """A trade that is ready-mix concrete: it has a register of its own rather than a materials list."""
    return bool(RMC_WORDS.search(category or ""))


def _worth(line):
    """What was taken into stock is what the supplier is paid for, so the accepted quantity prices the line."""
    return money((line.accepted_qty or 0) * (line.rate or 0))


def _same_trade(a, b):
    a, b = _text(a).lower(), _text(b).lower()
    return bool(a and b and (a == b or a in b or b in a))


def material_key(code, description):
    return (code or "").strip().upper() or (description or "").strip().upper()


def work_order_values(db, client_id, job_id):
    """Committed subcontract work orders, summed by their work type: what each trade has been awarded."""
    S = models.DBSubcontractOrder
    q = db.query(S.work_type, S.gross_amount).filter(
        S.client_id == client_id, S.status.in_(WO_COMMITTED_STATUSES))
    if job_id:
        q = q.filter(S.job_id == job_id)
    totals = OrderedDict()
    for work_type, gross in q.all():
        name = _text(work_type)
        if name:
            totals[name] = money(totals.get(name, 0) + (gross or 0))
    return totals


def purchased_items(db, client_id):
    M = models
    return db.query(M.DBItem).filter(M.DBItem.client_id == client_id, M.DBItem.is_active.is_(True),
                                     M.DBItem.item_type == "Purchased").order_by(M.DBItem.item_code).limit(3000).all()


def stock_by_category(db, client_id, items=None):
    """Every purchased material with what the store holds now, under its category: the physical stock sheet."""
    M = models
    items = purchased_items(db, client_id) if items is None else items
    held = current_stock(db, client_id)
    groups = OrderedDict()
    for it in items:
        b = held.get(it.item_code)
        groups.setdefault(_category(it), []).append({
            "item_code": it.item_code, "item_name": it.item_name, "uom": it.units_of_measure or "",
            "on_hand": money(b["on_hand"]) if b else 0.0, "counted": b is not None})
    return [{"category": c, "items": rows} for c, rows in groups.items()]


def hub_receipts(db, client_id, job_id=0):
    """The Store Hub's posted goods receipts, shaped like the old store's so the tracker reads both alike. Their ids,
    and their lines' ids, are negative: the tracker's own rows (invoice details, blocks) key on a receipt id, and a
    Hub receipt must never land on an old receipt's row."""
    from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
    from app.services.store_inward import base_uom_of
    q = db.query(DBStoreGrn).filter(DBStoreGrn.client_id == client_id, DBStoreGrn.status == "POSTED")
    if job_id:
        q = q.filter(DBStoreGrn.project_id == job_id)
    docs = q.order_by(DBStoreGrn.grn_date, DBStoreGrn.id).limit(2000).all()
    grns = [SimpleNamespace(id=-g.id, number=g.number or "", supplier_name=g.supplier_name or "", invoice_number=g.challan_no or "",
                            received_on=g.grn_date.isoformat() if g.grn_date else "", purchase_order_id=g.po_id,
                            vehicle_number=g.vehicle_no or "") for g in docs]
    rows = db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id.in_([g.id for g in docs])).order_by(
        DBStoreGrnLine.grn_id, DBStoreGrnLine.line_no, DBStoreGrnLine.id).all() if docs else []
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_({l.item_id for l in rows})).all()} if rows else {}
    lines = []
    for l in rows:
        it = items.get(l.item_id)
        lines.append(SimpleNamespace(id=-l.id, goods_receipt_id=-l.grn_id, item_code=it.item_code if it else "",
                                     description=it.item_name if it else "", uom=base_uom_of(db, it) if it else "",
                                     accepted_qty=float(l.accepted_qty or 0), rate=float(l.rate or 0)))
    return grns, lines


def build_tracker(db, client_id, job_id=0, gst_percent=DEFAULT_GST, markup_percent=DEFAULT_MARKUP):
    M = models
    q = db.query(M.DBGoodsReceipt).filter(M.DBGoodsReceipt.client_id == client_id, M.DBGoodsReceipt.status == "POSTED")
    if job_id:
        q = q.filter(M.DBGoodsReceipt.job_id == job_id)
    grns = q.order_by(M.DBGoodsReceipt.received_on, M.DBGoodsReceipt.id).limit(2000).all()
    old_ids = [g.id for g in grns]
    lines = db.query(M.DBGoodsReceiptLine).filter(M.DBGoodsReceiptLine.goods_receipt_id.in_(old_ids)).order_by(
        M.DBGoodsReceiptLine.goods_receipt_id, M.DBGoodsReceiptLine.display_order,
        M.DBGoodsReceiptLine.id).all() if old_ids else []
    # Deliveries received in the Store Hub come in beside the old store's, in date order.
    hub_grns, hub_lines = hub_receipts(db, client_id, job_id)
    grns = sorted(grns + hub_grns, key=lambda g: (g.received_on or "", g.id < 0, abs(g.id)))
    lines = lines + hub_lines
    grn_ids = [g.id for g in grns]

    codes = {l.item_code for l in lines if l.item_code}
    items = {i.item_code: i for i in db.query(M.DBItem).filter(
        M.DBItem.client_id == client_id, M.DBItem.item_code.in_(codes)).all()} if codes else {}
    master = purchased_items(db, client_id)
    held = current_stock(db, client_id)
    prime(db, M.DBPurchaseOrder, [g.purchase_order_id for g in grns])
    meta = {m.grn_id: m for m in db.query(M.DBTrackerInvoice).filter(
        M.DBTrackerInvoice.client_id == client_id, M.DBTrackerInvoice.grn_id.in_(grn_ids)).all()} if grn_ids else {}
    remarks = {n.grn_id: n.remark for n in db.query(M.DBTrackerInvoiceNote).filter(
        M.DBTrackerInvoiceNote.client_id == client_id, M.DBTrackerInvoiceNote.grn_id.in_(grn_ids)).all()} if grn_ids else {}
    extra = {}
    for c in (db.query(M.DBTrackerCharge).filter(M.DBTrackerCharge.client_id == client_id,
                                                 M.DBTrackerCharge.grn_id.in_(grn_ids)).all() if grn_ids else []):
        extra[(c.grn_id, c.kind)] = c.amount or 0.0
    line_ids = [l.id for l in lines]
    blocks = {b.grn_line_id: b.block for b in db.query(M.DBTrackerBlock).filter(
        M.DBTrackerBlock.client_id == client_id, M.DBTrackerBlock.grn_line_id.in_(line_ids)).all()} if line_ids else {}
    notes = {n.category: n for n in db.query(M.DBTrackerNote).filter(
        M.DBTrackerNote.client_id == client_id, M.DBTrackerNote.job_id == (job_id or 0)).all()}
    working = {w.item_key: w.rate for w in db.query(M.DBTrackerWorkingRate).filter(
        M.DBTrackerWorkingRate.client_id == client_id, M.DBTrackerWorkingRate.job_id == (job_id or 0)).all()}
    awarded = work_order_values(db, client_id, job_id)

    gst = float(gst_percent or 0) / 100.0
    by_grn = {}
    for l in lines:
        by_grn.setdefault(l.goods_receipt_id, []).append(l)

    invoices, slices = [], {}
    for g in grns:
        gl = by_grn.get(g.id, [])
        m = meta.get(g.id)
        basic = money(sum(_worth(l) for l in gl))
        tax = money(basic * gst)
        freight = money(m.freight if m else 0)
        insurance = money(extra.get((g.id, "insurance"), 0))
        hamali = money(extra.get((g.id, "hamali"), 0))
        total = money(basic + tax + freight + insurance + hamali)
        printed = m.invoice_amount if m and m.invoice_amount is not None else None
        po = by_id(db, M.DBPurchaseOrder, g.purchase_order_id)
        trades = list(OrderedDict.fromkeys(_category(items.get(l.item_code)) for l in gl))
        share = {}
        for l in gl:
            cat = _category(items.get(l.item_code))
            share[cat] = money(share.get(cat, 0) + _worth(l))
        slices[g.id] = share
        invoices.append({
            "grn_id": g.id, "grn": g.number or "", "supplier": g.supplier_name or "",
            "invoice_number": g.invoice_number or "", "invoice_date": (m.invoice_date if m else "") or "",
            "received_on": g.received_on or "", "po_number": po.number if po else "",
            "vehicle": g.vehicle_number or "", "amount": basic, "gst": tax, "freight": freight,
            "insurance": insurance, "hamali": hamali, "total": total, "trades": trades,
            "remark": remarks.get(g.id) or "",
            "invoice_amount": None if printed is None else money(printed),
            "difference": None if printed is None else money(printed - total),
        })
    inv_by_id = {i["grn_id"]: i for i in invoices}

    # What a trade has bought is what its suppliers billed: the printed amount where it was keyed in, otherwise what the
    # receipts come to. An invoice across several trades is shared out by the value of the goods in each.
    cat_buy = OrderedDict()
    for inv in invoices:
        billed = inv["invoice_amount"] if inv["invoice_amount"] is not None else inv["total"]
        base = sum(slices[inv["grn_id"]].values())
        for cat, part in slices[inv["grn_id"]].items():
            cat_buy[cat] = money(cat_buy.get(cat, 0) + (billed * part / base if base else 0))

    # One block per trade: its materials down the side, the supplier invoices across the top.
    cats = OrderedDict()
    for g in grns:
        for l in by_grn.get(g.id, []):
            it = items.get(l.item_code)
            cat = _category(it)
            c = cats.setdefault(cat, {"name": cat, "invoice_ids": [], "materials": OrderedDict()})
            if g.id not in c["invoice_ids"]:
                c["invoice_ids"].append(g.id)
            key = material_key(l.item_code, l.description)
            mat = c["materials"].setdefault(key, {
                "key": key, "item_code": l.item_code or "", "description": l.description or (it.item_name if it else ""),
                "uom": l.uom or "", "cells": OrderedDict(), "total_qty": 0.0, "total_amount": 0.0})
            cell = mat["cells"].setdefault(g.id, {"grn_id": g.id, "qty": 0.0, "amount": 0.0, "rate": 0.0})
            cell["qty"] = money(cell["qty"] + (l.accepted_qty or 0))
            cell["amount"] = money(cell["amount"] + _worth(l))
            cell["rate"] = unit_rate(cell["amount"] / cell["qty"]) if cell["qty"] else unit_rate(l.rate)
            mat["total_qty"] = money(mat["total_qty"] + (l.accepted_qty or 0))
            mat["total_amount"] = money(mat["total_amount"] + _worth(l))
    # Every material of the trade is listed, whether or not any has come yet: the sheet shows what is still to arrive.
    for it in master:
        cat = _category(it)
        if cat in cats:
            key = material_key(it.item_code, it.item_name)
            cats[cat]["materials"].setdefault(key, {
                "key": key, "item_code": it.item_code, "description": it.item_name, "uom": it.units_of_measure or "",
                "cells": OrderedDict(), "total_qty": 0.0, "total_amount": 0.0})

    markup = float(markup_percent or 0) / 100.0
    categories = []
    for c in cats.values():
        mats = []
        for n, m in enumerate(c["materials"].values(), start=1):
            cells = list(m["cells"].values())
            stock = held.get(m["item_code"])
            rate = working.get(m["key"])
            qty = m["total_qty"]
            mats.append(dict(
                m, sl=n, cells=cells, total_rate=money(sum(x["rate"] for x in cells)),
                avg_rate=unit_rate(m["total_amount"] / qty) if qty else 0.0,
                working_rate=None if rate is None else unit_rate(rate),
                working_amount=None if rate is None else money(qty * rate),
                on_hand=money(stock["on_hand"]) if stock else 0.0, counted=stock is not None))
        total = money(sum(m["total_amount"] for m in mats))
        # Under each invoice column: its amount and GST for this trade, then the bill's own charges and printed total.
        # An invoice that spans several trades shows its charges and printed total only against the invoice list.
        foot = []
        for gid in c["invoice_ids"]:
            inv = inv_by_id[gid]
            whole = len(inv["trades"]) == 1
            part = slices[gid].get(c["name"], 0.0)
            foot.append({"grn_id": gid, "amount": part, "gst": money(part * gst),
                         "total": money(part * (1 + gst) + (inv["freight"] + inv["insurance"] + inv["hamali"] if whole else 0)),
                         "freight": inv["freight"] if whole else None, "insurance": inv["insurance"] if whole else None,
                         "hamali": inv["hamali"] if whole else None,
                         "invoice_amount": inv["invoice_amount"] if whole else None,
                         "difference": inv["difference"] if whole else None, "whole": whole,
                         "remark": inv["remark"]})
        note = notes.get(c["name"])
        categories.append({"name": c["name"], "invoice_ids": c["invoice_ids"], "materials": mats, "total": total,
                           "working_total": money(sum(m["working_amount"] or 0 for m in mats)),
                           "footer": foot, "gst": money(total * gst), "with_gst": money(total * (1 + gst)),
                           "markup": money(total * markup), "with_markup": money(total * (1 + markup)),
                           "note": (note.remarks if note else "") or ""})

    # What each trade has been awarded, from committed work orders, unless a figure was typed over it.
    summary_rows = []
    wo_names = [n for n in awarded if not any(_same_trade(n, k) for k in list(cat_buy) + list(notes))]
    for name in list(cat_buy.keys()) + [n for n in notes if n not in cat_buy] + wo_names:
        n = notes.get(name)
        buy = money(cat_buy.get(name, 0))
        suggested = money(sum(v for k, v in awarded.items() if _same_trade(k, name)))
        typed = money(n.wo_amount) if n and n.wo_amount else 0.0
        wo = typed or suggested
        summary_rows.append({"category": name, "purchase_amount": buy, "wo_amount": wo, "wo_suggested": suggested,
                             "wo_source": "typed" if typed else ("work orders" if suggested else ""),
                             "difference": money(wo - buy), "remarks": (n.remarks if n else "") or ""})
    summary = {"rows": summary_rows,
               "purchase_amount": money(sum(r["purchase_amount"] for r in summary_rows)),
               "wo_amount": money(sum(r["wo_amount"] for r in summary_rows)),
               "difference": money(sum(r["difference"] for r in summary_rows))}

    # Ready-mix gets its own register: a row per lorry, and what each block took.
    rmc_rows, block_totals = [], OrderedDict()
    for g in grns:
        for l in by_grn.get(g.id, []):
            it = items.get(l.item_code)
            if not is_rmc(_category(it), l, it):
                continue
            inv = inv_by_id[g.id]
            block = _text(blocks.get(l.id))
            qty, amt = money(l.accepted_qty or 0), _worth(l)
            rmc_rows.append({"line_id": l.id, "n": len(rmc_rows) + 1, "grn_id": g.id,
                             "invoice_date": inv["invoice_date"] or inv["received_on"],
                             "supplier": inv["supplier"], "po_number": inv["po_number"], "vehicle": inv["vehicle"],
                             "invoice_number": inv["invoice_number"], "grade": _grade(l, it), "qty": qty,
                             "rate": unit_rate(l.rate), "amount": amt, "block": block})
            label = block or "(no block yet)"
            b = block_totals.setdefault(label, {"block": label, "loads": 0, "qty": 0.0, "amount": 0.0})
            b["loads"] += 1
            b["qty"] = money(b["qty"] + qty)
            b["amount"] = money(b["amount"] + amt)
    r_amt = money(sum(r["amount"] for r in rmc_rows))
    rmc = {"rows": rmc_rows, "blocks": list(block_totals.values()), "qty": money(sum(r["qty"] for r in rmc_rows)),
           "amount": r_amt, "gst": money(r_amt * gst), "total": money(r_amt * (1 + gst))}

    return {"job_id": job_id or 0, "gst_percent": float(gst_percent), "markup_percent": float(markup_percent),
            "summary": summary, "invoices": invoices, "categories": categories, "rmc": rmc,
            "stock": stock_by_category(db, client_id, master),
            "totals": {"invoices": len(invoices), "amount": money(sum(i["amount"] for i in invoices)),
                       "gst": money(sum(i["gst"] for i in invoices)),
                       "freight": money(sum(i["freight"] for i in invoices)),
                       "insurance": money(sum(i["insurance"] for i in invoices)),
                       "hamali": money(sum(i["hamali"] for i in invoices)),
                       "total": money(sum(i["total"] for i in invoices)),
                       "unchecked": len([i for i in invoices if i["invoice_amount"] is None]),
                       "mismatched": len([i for i in invoices if i["difference"] is not None and abs(i["difference"]) >= 1])}}
