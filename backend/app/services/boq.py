"""The rules and workings behind the boq endpoints."""
import re
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func

from app import models

from app.constants.approvals import GONE_STATUSES
from app.constants.boq import BOQ_KINDS, BOQ_NOT_LIVE, BOQ_PRICED, BV_TRANSITIONS
from app.core.currency import money, unit_rate
from app.core.permissions import employee_can
from app.core.queries import by_id, chain_rows, forget_chain
from app.core.units import canonical_unit
from app.schemas.items import ItemIn


def boq_or_404(db, client_id, boq_id):
    row = db.query(models.DBBoq).filter(models.DBBoq.id == boq_id, models.DBBoq.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "BOQ not found")
    return row


def boq_revision_of(db, boq, rev_no=None):
    want = boq.current_rev if rev_no is None else rev_no
    rev = db.query(models.DBBoqRevision).filter(
        models.DBBoqRevision.boq_id == boq.id, models.DBBoqRevision.rev_no == want).first()
    if not rev:
        raise HTTPException(404, "That revision of the BOQ does not exist")
    return rev


def boq_amount(kind, qty, rate):
    return money((qty or 0) * (rate or 0)) if kind in BOQ_PRICED else 0.0


def boq_line_dict(l):
    return {"id": l.id, "key": l.key, "kind": l.kind, "sno": l.sno or "", "description": l.description or "",
            "uom": l.uom or "", "quantity": money(l.quantity), "rate": unit_rate(l.rate), "amount": money(l.amount),
            "code": l.code or "", "item_code": l.item_code or "", "remarks": l.remarks or ""}


def boq_lines_with_subtotals(db, rev):
    """The revision's lines in order, each section carrying what its items come to, and the grand total."""
    lines = db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).order_by(
        models.DBBoqLine.display_order, models.DBBoqLine.id).all()
    out, section, total = [], None, 0.0
    for l in lines:
        d = boq_line_dict(l)
        if l.kind == "section":
            section = d
            d["subtotal"] = 0.0
        elif l.kind in BOQ_PRICED:
            total += l.amount or 0
            if section is not None:
                section["subtotal"] = money(section["subtotal"] + (l.amount or 0))
        out.append(d)
    return out, money(total)


def boq_revisions_list(db, boq):
    return [{"rev_no": r.rev_no, "label": r.label or "R%d" % r.rev_no, "note": r.note or "", "status": r.status,
             "created_by_name": r.created_by_name or "", "created_at": r.created_at or "", "issued_at": r.issued_at or ""}
            for r in db.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id == boq.id).order_by(
                models.DBBoqRevision.rev_no).all()]


def boq_head(db, boq, rev=None):
    job = by_id(db, models.DBJob, boq.job_id)
    rev = rev or boq_revision_of(db, boq)
    count, total = db.query(func.count(models.DBBoqLine.id), func.coalesce(func.sum(models.DBBoqLine.amount), 0.0)).filter(
        models.DBBoqLine.revision_id == rev.id, models.DBBoqLine.kind.in_(BOQ_PRICED)).one()
    return {"id": boq.id, "number": boq.number or "", "title": boq.title or "", "job_id": boq.job_id,
            "project": ("%s %s" % (job.number, job.name)).strip() if job else "",
            "customer": (job.customer_name if job else "") or "",
            "current_rev": boq.current_rev, "revision": rev.label or "R%d" % rev.rev_no, "status": rev.status,
            "items": count, "total": money(total), "created_at": boq.created_at or ""}


def boq_new_key():
    return uuid.uuid4().hex[:12]


def boq_kind_of(sno, description, quantity, rate):
    """What a row of a client's sheet is: a priced item (or sub-item), a section heading, or a note."""
    sno, text = (sno or "").strip().rstrip(".)"), (description or "").strip()
    if quantity or rate:
        sub = bool(re.match(r"^(\d+(\.\d+)*[.\-\s]*)?\(?([a-z]|[ivx]{1,4})$", sno)) and not re.match(r"^\d+(\.\d+)*$", sno)
        return "sub" if sub else "item"
    if text.isupper() and len(text) < 160:
        return "section"                                  # a heading shouted in capitals
    if re.match(r"^([A-Z]{1,3}|[IVXL]+|\d+)$", sno):
        return "section" if len(text) < 160 else "note"   # lettered, roman or whole-numbered: a section
    return "note" if (len(text) > 60 or text.endswith(".")) else "section"


def boq_save_lines(db, boq, rev, rows, issue_codes, client_id):
    """Replace a revision's lines with the rows given (keeping each row's key, giving new rows one)."""
    db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).delete()
    kept, seen = [], set()
    for index, r in enumerate(rows):
        text = (r.description or "").strip()
        if not text:
            continue
        kind = r.kind if r.kind in BOQ_KINDS else "item"
        qty = money(r.quantity or 0) if kind in BOQ_PRICED else 0.0
        rate = unit_rate(r.rate or 0) if kind in BOQ_PRICED else 0.0
        if qty < 0 or rate < 0:
            raise HTTPException(400, "Line %d: quantity and rate cannot be negative." % (index + 1))
        key = (r.key or "").strip()[:40]
        if not key or key in seen:
            key = boq_new_key()
        seen.add(key)
        line = models.DBBoqLine(
            boq_id=boq.id, revision_id=rev.id, key=key, kind=kind, sno=(r.sno or "").strip()[:30],
            description=text, uom=(r.uom or "").strip()[:20] if kind in BOQ_PRICED else "", quantity=qty, rate=rate,
            amount=boq_amount(kind, qty, rate), code=(r.code or "").strip()[:60],
            item_code=(r.item_code or "").strip().upper()[:40] if kind in BOQ_PRICED else "",
            remarks=(r.remarks or "").strip(), display_order=len(kept))
        db.add(line)
        kept.append(line)
    db.flush()
    issued = 0
    if issue_codes:
        issued = boq_issue_codes(db, client_id, kept)
    return kept, issued


def boq_issue_codes(db, client_id, lines):
    """Every priced line without an item code gets one: the code of the master item of the same name that no other
    line of this BOQ uses, or a newly issued finished-goods code. Returns how many were given."""
    in_use = {l.item_code for l in lines if l.item_code}
    by_name = {}
    for it in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.kind == "FG").all():
        by_name.setdefault(re.sub(r"\s+", " ", (it.item_name or "")).strip().lower(), []).append(it)
    claimed, given = set(), 0
    for l in lines:
        if l.kind not in BOQ_PRICED or l.item_code:
            continue
        name = re.sub(r"\s+", " ", (l.description or "").split("\n")[0]).strip()[:200]
        match = next((i for i in by_name.get(name.lower(), []) if i.item_code not in in_use), None)
        if match is None:
            match = build_item(db, client_id, ItemIn(
                kind="FG", item_name=name, description=(l.description or "").strip(),
                units_of_measure=canonical_unit(l.uom) or "Nos"), claimed)
            db.flush()
            by_name.setdefault(name.lower(), []).append(match)
        l.item_code = match.item_code
        in_use.add(match.item_code)
        given += 1
    return given


def boq_given_to_gangs(db, client_id, keys=None):
    """{boq key: what the gangs have been given against it}, from the orders that are still alive."""
    q = db.query(models.DBSubcontractItem, models.DBSubcontractOrder).join(
        models.DBSubcontractOrder, models.DBSubcontractOrder.id == models.DBSubcontractItem.order_id).filter(
        models.DBSubcontractOrder.client_id == client_id, models.DBSubcontractItem.boq_key != "",
        models.DBSubcontractItem.boq_key.isnot(None), models.DBSubcontractOrder.status.notin_(BOQ_NOT_LIVE))
    if keys is not None:
        q = q.filter(models.DBSubcontractItem.boq_key.in_(list(keys) or [""]))
    out = {}
    for it, order in q.all():
        g = out.setdefault(it.boq_key, {"qty": 0.0, "cost": 0.0, "items": [], "orders": []})
        g["qty"] += it.quantity or 0
        g["cost"] += it.total_amount or 0
        g["items"].append(it.id)
        if order.wo_number not in g["orders"]:
            g["orders"].append(order.wo_number)
    return out


def boq_over_allotments(db, client_id, keys):
    """Words for each BOQ line the given keys name whose gang orders now add up to more than the BOQ quantity."""
    keys = {k for k in keys if k}
    if not keys:
        return []
    given = boq_given_to_gangs(db, client_id, keys)
    current = {}
    for boq in db.query(models.DBBoq).filter(models.DBBoq.client_id == client_id).all():
        rev = db.query(models.DBBoqRevision.id).filter(
            models.DBBoqRevision.boq_id == boq.id, models.DBBoqRevision.rev_no == boq.current_rev).first()
        if rev:
            current[rev[0]] = boq.id
    out = []
    for l in db.query(models.DBBoqLine).filter(models.DBBoqLine.key.in_(list(keys)),
                                               models.DBBoqLine.revision_id.in_(list(current) or [0])).all():
        g = given.get(l.key)
        if g and g["qty"] > (l.quantity or 0) + 0.0001:
            out.append("%s: %s given to gangs against %s in the BOQ" % (l.sno or l.description[:30], money(g["qty"]), money(l.quantity)))
    return out


def boq_tracker_data(db, client, boq):
    rev = boq_revision_of(db, boq)
    lines = db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).order_by(models.DBBoqLine.display_order).all()
    given = boq_given_to_gangs(db, client.id, {l.key for l in lines if l.kind in BOQ_PRICED})
    item_ids = [i for g in given.values() for i in g["items"]]
    done = dict(db.query(models.DBSubMeasurement.item_id, func.coalesce(func.sum(models.DBSubMeasurement.quantity), 0.0)).filter(
        models.DBSubMeasurement.item_id.in_(item_ids or [0])).group_by(models.DBSubMeasurement.item_id).all())
    billed = dict(db.query(models.DBSubBillLine.item_id, func.coalesce(func.sum(models.DBSubBillLine.this_bill_qty), 0.0)).join(
        models.DBSubBill, models.DBSubBill.id == models.DBSubBillLine.sub_bill_id).filter(
        models.DBSubBillLine.item_id.in_(item_ids or [0]), models.DBSubBill.status != "CANCELLED").group_by(models.DBSubBillLine.item_id).all())
    # The client's side: orders drawn from this BOQ, by item code.
    client_done, client_billed = {}, {}
    for wo in db.query(models.DBWorkOrder).filter(models.DBWorkOrder.boq_id == boq.id).all():
        m, b = measured_to_date(db, wo.id), billed_qty_to_date(db, wo.id)
        for wl in db.query(models.DBWorkOrderLine).filter(models.DBWorkOrderLine.work_order_id == wo.id).all():
            code = (wl.fg_code or "").upper()
            client_done[code] = client_done.get(code, 0.0) + m.get(wl.id, 0.0)
            client_billed[code] = client_billed.get(code, 0.0) + b.get(wl.id, 0.0)
    rows, flags = [], {"no_gang": 0, "over_allotted": 0, "loss": 0, "over_executed": 0}
    totals = {"value": 0.0, "given_cost": 0.0, "client_billed": 0.0, "gang_billed": 0.0}
    for l in lines:
        if l.kind == "section":
            rows.append({"kind": "section", "sno": l.sno or "", "description": l.description})
            continue
        if l.kind not in BOQ_PRICED:
            continue
        g = given.get(l.key, {"qty": 0.0, "cost": 0.0, "items": [], "orders": []})
        gang_rate = unit_rate(g["cost"] / g["qty"]) if g["qty"] else 0.0
        executed = money(sum(done.get(i, 0.0) for i in g["items"]))
        gang_billed = money(sum(billed.get(i, 0.0) for i in g["items"]))
        code = (l.item_code or "").upper()
        c_done, c_billed = money(client_done.get(code, 0.0)), money(client_billed.get(code, 0.0))
        row_flags = []
        if (l.quantity or 0) > 0 and not g["qty"]:
            row_flags.append("no_gang")
        if g["qty"] > (l.quantity or 0) + 0.0001:
            row_flags.append("over_allotted")
        if g["qty"] and gang_rate > (l.rate or 0) + 0.0001:
            row_flags.append("loss")
        if max(executed, c_done) > (l.quantity or 0) + 0.0001:
            row_flags.append("over_executed")
        for f in row_flags:
            flags[f] += 1
        totals["value"] += l.amount or 0
        totals["given_cost"] += g["cost"]
        totals["client_billed"] += c_billed * (l.rate or 0)
        totals["gang_billed"] += gang_billed * gang_rate
        rows.append({"kind": l.kind, "key": l.key, "sno": l.sno or "", "description": l.description, "uom": l.uom or "",
                     "item_code": l.item_code or "", "quantity": money(l.quantity), "rate": unit_rate(l.rate), "amount": money(l.amount),
                     "given": money(g["qty"]), "gang_rate": gang_rate, "gang_cost": money(g["cost"]), "orders": g["orders"],
                     "left_to_give": money(max(0.0, (l.quantity or 0) - g["qty"])),
                     "executed": executed, "gang_billed": gang_billed, "client_executed": c_done, "client_billed": c_billed,
                     "margin_percent": round(((l.rate or 0) - gang_rate) / l.rate * 100, 1) if g["qty"] and l.rate else None,
                     "percent_done": round(max(executed, c_done) / l.quantity * 100, 1) if l.quantity else 0.0,
                     "flags": row_flags})
    return {"boq": boq_head(db, boq, rev), "rows": rows, "flags": flags,
            "totals": {k: money(v) for k, v in totals.items()}}


def boq_variation_or_404(db, client_id, vid):
    row = db.query(models.DBBoqVariation).filter(
        models.DBBoqVariation.id == vid, models.DBBoqVariation.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "Variation not found")
    return row


def bv_next_number(db, boq):
    n = (db.query(func.max(models.DBBoqVariation.sequence)).filter(models.DBBoqVariation.boq_id == boq.id).scalar() or 0) + 1
    while db.query(models.DBBoqVariation.id).filter(models.DBBoqVariation.client_id == boq.client_id,
                                                    models.DBBoqVariation.number == "%s/BV-%02d" % (boq.number, n)).first():
        n += 1
    return "%s/BV-%02d" % (boq.number, n), n


def bv_write_lines(db, boq, vo, rows):
    """The variation's lines as they are given, checked against the BOQ as it stands now, with what the BOQ already
    says filled in where the person left it blank (description, unit and - for a quantity - its rate)."""
    rev = boq_revision_of(db, boq)
    by_key = {l.key: l for l in db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).all()}
    db.query(models.DBBoqVariationLine).filter(models.DBBoqVariationLine.variation_id == vo.id).delete()
    seen, kept = set(), 0
    for index, r in enumerate(rows):
        kind = r.kind if r.kind in ("quantity", "extra") else "quantity"
        change = money(r.change_qty or 0)
        label = "Line %d" % (index + 1)
        if kind == "quantity":
            line = by_key.get(r.boq_key or "")
            if not line or line.kind not in BOQ_PRICED:
                raise HTTPException(400, "%s: choose the BOQ line whose quantity changes." % label)
            if r.boq_key in seen:
                raise HTTPException(400, "%s: %s is on this variation twice." % (label, line.sno or line.description[:30]))
            seen.add(r.boq_key)
            if not change:
                raise HTTPException(400, "%s: say how much is added to (or taken from) %s." % (label, line.sno or line.description[:30]))
            if money((line.quantity or 0) + change) < 0:
                raise HTTPException(400, "%s: that would take %s below nothing." % (label, line.sno or line.description[:30]))
            rate = unit_rate(r.rate if r.rate is not None else line.rate)
            db.add(models.DBBoqVariationLine(
                variation_id=vo.id, kind="quantity", boq_key=line.key, sno=line.sno or "", description=line.description,
                uom=line.uom or "", old_qty=money(line.quantity), change_qty=change, rate=rate, amount=money(change * rate),
                remarks=(r.remarks or "").strip(), display_order=index))
        else:
            text = (r.description or "").strip()
            if not text:
                raise HTTPException(400, "%s: an extra item needs its description." % label)
            if change <= 0:
                raise HTTPException(400, "%s: an extra item needs a quantity." % label)
            rate = unit_rate(r.rate or 0)
            if rate <= 0:
                raise HTTPException(400, "%s: an extra item needs its rate." % label)
            if r.section_key and (by_key.get(r.section_key) is None or by_key[r.section_key].kind != "section"):
                raise HTTPException(400, "%s: that section is not in the BOQ." % label)
            db.add(models.DBBoqVariationLine(
                variation_id=vo.id, kind="extra", section_key=(r.section_key or ""), sno=(r.sno or "").strip()[:30],
                description=text, uom=(r.uom or "").strip()[:20], old_qty=0.0, change_qty=change, rate=rate,
                amount=money(change * rate), remarks=(r.remarks or "").strip(), display_order=index))
        kept += 1
    if not kept:
        raise HTTPException(400, "A variation needs at least one line.")
    db.flush()
    vo.value = money(sum(l.amount or 0 for l in db.query(models.DBBoqVariationLine).filter(
        models.DBBoqVariationLine.variation_id == vo.id).all()))
    vo.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def bv_dict(db, vo, detail=False):
    boq = db.query(models.DBBoq).filter(models.DBBoq.id == vo.boq_id).first()
    job = by_id(db, models.DBJob, vo.job_id)
    revs = {r.rev_no: (r.label or "R%d" % r.rev_no) for r in db.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id == vo.boq_id).all()}
    row = {"id": vo.id, "number": vo.number or "", "boq_id": vo.boq_id, "boq": boq.number if boq else "",
           "project": ("%s %s" % (job.number, job.name)).strip() if job else "", "status": vo.status or "DRAFT",
           "reason": vo.reason or "", "value": money(vo.value), "basis_rev": revs.get(vo.basis_rev, "R%d" % (vo.basis_rev or 0)),
           "applied_rev": revs.get(vo.applied_rev, "") if vo.applied_rev is not None else "",
           "raised_by_name": vo.raised_by_name or "", "approved_by_name": vo.approved_by_name or "",
           "approved_at": vo.approved_at or "", "rejection_reason": vo.rejection_reason or "",
           "actions": sorted(BV_TRANSITIONS.get(vo.status or "DRAFT", {}).keys()),
           "editable": (vo.status or "DRAFT") == "DRAFT", "created_at": vo.created_at or ""}
    route = bv_route(db, vo)
    row["route"] = route
    row["waiting_on"] = next((r["name"] for r in route if r["status"] == "waiting"), "")
    if detail:
        row["lines"] = [{"id": l.id, "kind": l.kind, "boq_key": l.boq_key or "", "section_key": l.section_key or "",
                         "sno": l.sno or "", "description": l.description or "", "uom": l.uom or "",
                         "old_qty": money(l.old_qty), "change_qty": money(l.change_qty), "new_qty": money((l.old_qty or 0) + (l.change_qty or 0)),
                         "rate": unit_rate(l.rate), "amount": money(l.amount), "remarks": l.remarks or ""}
                        for l in db.query(models.DBBoqVariationLine).filter(models.DBBoqVariationLine.variation_id == vo.id).order_by(
                            models.DBBoqVariationLine.display_order, models.DBBoqVariationLine.id).all()]
    return row


def bv_chain_rows(db, vid):
    return chain_rows(db, "boq_variation", vid)


def bv_start_chain(db, client_id, vo, submitter_id):
    forget_chain(db, "boq_variation", vo.id)
    db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == "boq_variation", models.DBApprovalChain.entity_id == vo.id).delete(synchronize_session=False)
    if submitter_id and not raised_by_owner(db, client_id, submitter_id):
        rungs = hierarchy_chain(db, client_id, submitter_id, "subcontracts.approve", vo.job_id, owner_signs=True)
    else:
        rungs = []
    rungs = rungs or [chain_rung(None, db, client_id)]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for i, rung in enumerate(rungs, 1):
        db.add(models.DBApprovalChain(client_id=client_id, entity_type="boq_variation", entity_id=vo.id, employee_id=submitter_id,
                                      approver_id=rung["employee_id"], level=rung["level"], step=i, status="pending", created_at=now))
    db.flush()


def bv_current_step(db, vo):
    """The step it waits at; an approver who has left or lost the right is passed over, not left to block it."""
    for row in bv_chain_rows(db, vo.id):
        if row.status != "pending":
            continue
        if row.approver_id is None:
            return row
        emp = by_id(db, models.DBEmployee, row.approver_id)
        if emp and (emp.status or "active") not in GONE_STATUSES and employee_can(emp, "subcontracts.approve"):
            return row
        row.status, row.notes = "skipped", "No longer able to approve"
        row.decided_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return None


def bv_route(db, vo):
    rows = bv_chain_rows(db, vo.id)
    current = bv_current_step(db, vo) if (vo.status or "") == "SUBMITTED" else None
    return [{"step": r.step, "name": sub_bill_step_name(db, r), "owner": r.approver_id is None,
             "status": "waiting" if current is not None and r.id == current.id else r.status,
             "notes": r.notes or "", "decided_at": r.decided_at or ""} for r in rows]


def bv_decide(db, client, vo, actor_id, actor_name, approve, comments=""):
    """One signature on a variation. Returns True when it was the last one needed."""
    step = bv_current_step(db, vo)
    owner = actor_id is None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not owner and vo.raised_by and vo.raised_by == actor_id:
        raise HTTPException(403, "You raised this variation, so somebody else has to approve it. It is waiting with %s."
                            % (sub_bill_step_name(db, step) or "the Master"))
    if not owner and (step is None or step.approver_id != actor_id):
        raise HTTPException(403, "%s is waiting with %s." % (vo.number, sub_bill_step_name(db, step) or "the Master"))
    if not approve:
        if step is not None:
            step.status, step.notes, step.decided_at = "rejected", (comments or "").strip(), now
        return False
    if owner:
        for row in bv_chain_rows(db, vo.id):
            if row.status == "pending":
                if row.approver_id is None:
                    row.status, row.notes, row.decided_at = "approved", (comments or "").strip(), now
                else:
                    row.status, row.notes, row.decided_at = "skipped", "Signed over by the Master", now
        db.flush()
        return True
    step.status, step.notes, step.decided_at = "approved", (comments or "").strip(), now
    db.flush()
    return bv_current_step(db, vo) is None


def bv_apply(db, client, boq, vo):
    """Move the BOQ to its next revision with the variation's changes in it, and raise the client's work order to match."""
    cur = boq_revision_of(db, boq)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if cur.status == "OPEN":
        cur.status, cur.issued_at = "ISSUED", now
    nxt = models.DBBoqRevision(boq_id=boq.id, rev_no=cur.rev_no + 1, status="OPEN", created_by_name=vo.raised_by_name or "",
                               label="R%d - %s" % (cur.rev_no + 1, (vo.number or "").rsplit("/", 1)[-1]), note=vo.reason or "")
    db.add(nxt)
    db.flush()
    copies = []
    for l in db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == cur.id).order_by(models.DBBoqLine.display_order).all():
        copies.append(models.DBBoqLine(boq_id=boq.id, revision_id=nxt.id, key=l.key, kind=l.kind, sno=l.sno, description=l.description,
                                       uom=l.uom, quantity=l.quantity, rate=l.rate, amount=l.amount, code=l.code,
                                       item_code=l.item_code, remarks=l.remarks))
    by_key = {c.key: c for c in copies}
    added = []
    for vl in db.query(models.DBBoqVariationLine).filter(models.DBBoqVariationLine.variation_id == vo.id).order_by(
            models.DBBoqVariationLine.display_order, models.DBBoqVariationLine.id).all():
        if vl.kind == "quantity":
            line = by_key.get(vl.boq_key)
            if line is None:
                raise HTTPException(409, "%s is no longer in the BOQ, so this variation cannot be applied. Send it back and correct it."
                                    % (vl.sno or vl.description[:30]))
            line.quantity = money((line.quantity or 0) + vl.change_qty)
            if line.quantity < 0:
                raise HTTPException(409, "%s would fall below nothing. Send it back and correct it." % (vl.sno or vl.description[:30]))
            line.amount = money(line.quantity * (line.rate or 0))
        else:
            # An extra item with no number of its own is numbered after the variation that brought it: V1/1, V1/2.
            new = models.DBBoqLine(boq_id=boq.id, revision_id=nxt.id, key=boq_new_key(), kind="item",
                                   sno=vl.sno or "V%d/%d" % (vo.sequence or 1, len(added) + 1),
                                   description=vl.description, uom=vl.uom, quantity=money(vl.change_qty), rate=unit_rate(vl.rate),
                                   amount=money(vl.change_qty * vl.rate), remarks=vl.remarks or "")
            at = len(copies)
            if vl.section_key and vl.section_key in by_key:
                at = copies.index(by_key[vl.section_key]) + 1
                while at < len(copies) and copies[at].kind != "section":
                    at += 1                                   # the end of that section
            copies.insert(at, new)
            added.append(new)
    for i, l in enumerate(copies):
        l.display_order = i
        db.add(l)
    db.flush()
    boq_issue_codes(db, client.id, copies)                    # the extra items get their codes from the item master
    boq.current_rev = nxt.rev_no
    # The client's work order drawn from this BOQ follows it.
    for wo in db.query(models.DBWorkOrder).filter(models.DBWorkOrder.boq_id == boq.id, models.DBWorkOrder.status != "Closed").all():
        lines = db.query(models.DBWorkOrderLine).filter(models.DBWorkOrderLine.work_order_id == wo.id).all()
        for vl in db.query(models.DBBoqVariationLine).filter(models.DBBoqVariationLine.variation_id == vo.id).all():
            if vl.kind == "quantity":
                code = (by_key[vl.boq_key].item_code or "").upper()
                wl = next((x for x in lines if (x.fg_code or "").upper() == code and code), None)
                if wl:
                    wl.qty = money((wl.qty or 0) + vl.change_qty)
                    wl.amount = money(wl.qty * (wl.rate or 0))
        for new in added:
            if new.item_code and not any((x.fg_code or "").upper() == new.item_code.upper() for x in lines):
                db.add(models.DBWorkOrderLine(work_order_id=wo.id, fg_code=new.item_code, item_name=new.description.split("\n")[0][:200],
                                              description=new.description.split("\n")[0][:300], qty=new.quantity, uom=new.uom,
                                              rate=new.rate, amount=new.amount))
        db.flush()
        wo.total_value = money(sum(money(x.amount) for x in db.query(models.DBWorkOrderLine).filter(
            models.DBWorkOrderLine.work_order_id == wo.id).all()))
    vo.applied_rev = nxt.rev_no
    return nxt


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.approvals import chain_rung, hierarchy_chain, raised_by_owner
from app.services.client_billing import billed_qty_to_date, measured_to_date
from app.services.items import build_item
from app.services.subcontract_billing import sub_bill_step_name
