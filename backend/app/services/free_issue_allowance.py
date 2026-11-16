"""Free-issue material to subcontractors: what a contractor may draw free of cost for the work ordered, by the store's material norms.

Steel already has an allowance (services/steel_allowance.py: the project's approved bar bending schedule plus a margin) and goes through the same
steps here: an issue that takes a material past its allowance is not refused outright - the site may need it - but it cannot go out on the
storekeeper's word. It waits for the Master, who sees what was asked, what was allowed and why, and decides. For every other material the allowance is

    permitted  = sum over the order's priced lines of (the line's quantity x the material's norm per unit on that BOQ line)
    issued     = what has gone out free of cost under that order, net of what came back (posted issues and returns only)
    remaining  = permitted - issued
    excess     = the part of this issue's quantity past `remaining`

Nothing is kept as a counter. The allowance is worked out from the norms, the order and the posted issues each time it is asked, so an issue that is
cancelled (or reversed) gives its quantity back by itself, nothing is counted twice, and a stale figure cannot let anything through. Posting takes a
lock on the order first and works it out again, so two issues approved when each was inside the allowance cannot both go out past it.

Only free-of-cost lines of an issue to a SUBCONTRACTOR under a work order are held to it (what is charged to the contractor is recovered from their
bill). A material with no norm on any of the order's BOQ lines has no allowance to measure against and is not held - as a project with no approved
BBS is not held for steel - and steel the BBS already governs is left to the BBS rather than checked twice. The norm is the quantity of the
material for one unit of the BOQ item (DBStoreMaterialNorm.qty_per_unit); its wastage percentage is not added: the allowance is norm x quantity.
"""
import json
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException

from app import models
from app.models.store_core import DocStatus
from app.models.store_outward import (
    FREE_APPROVED, FREE_PENDING, FREE_REJECTED, FREE_WITHDRAWN, ISSUE, SUBCONTRACTOR, DBStoreFreeIssueRequest, DBStoreIssue, DBStoreIssueLine,
    DBStoreIssueReturn, DBStoreIssueReturnLine, DBStoreOutwardLog,
)
from app.models.store_reports import DBStoreMaterialNorm

ZERO = Decimal("0")
EPS = Decimal("0.0005")                 # quantities are kept to three places
Q3 = Decimal("0.001")


def s3(x) -> str:
    return format(Decimal(str(x)).quantize(Q3), "f")


def is_master(actor) -> bool:
    """The Master (the account holder) - not a member of staff, whatever their rights."""
    return actor.employee is None


def _base_uom(db, item) -> str:
    from app.models.store_core import DBStoreItemSettings
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    return ((s.base_uom if s else item.units_of_measure) or "").strip()


# --- the allowance ---------------------------------------------------------------------------------------------------------------

def order_lines(db, order):
    """[(BOQ key, quantity ordered, what it is)] for the order's priced lines. A line standing for a whole heading of the BOQ is its parts."""
    from app.services.boq import boq_parts_of
    out = []
    for i in db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == order.id).order_by(models.DBSubcontractItem.display_order, models.DBSubcontractItem.id).all():
        if i.is_header:
            continue
        what = (i.item_description or "").split("\n")[0][:60]
        parts = boq_parts_of(i)
        if parts:
            out += [(p["key"], float(p.get("qty") or 0), what) for p in parts]
        elif i.boq_key and (i.quantity or 0) > 0:
            out.append((i.boq_key, float(i.quantity or 0), what))
    return out


def norms_by_key(db, client_id, job_id, item_ids):
    """{(BOQ key, item id): norm per unit} for a project's BOQ. A key stays the same through every revision of the BOQ; where more than one
    revision's line carries a norm, the current revision's wins, then the latest changed."""
    if not job_id or not item_ids:
        return {}
    rows = (db.query(DBStoreMaterialNorm, models.DBBoqLine.key, models.DBBoq.current_rev, models.DBBoqRevision.rev_no)
            .join(models.DBBoqLine, models.DBBoqLine.id == DBStoreMaterialNorm.boq_item_id)
            .join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id)
            .join(models.DBBoqRevision, models.DBBoqRevision.id == models.DBBoqLine.revision_id)
            .filter(DBStoreMaterialNorm.client_id == client_id, models.DBBoq.client_id == client_id, models.DBBoq.job_id == job_id,
                    DBStoreMaterialNorm.item_id.in_(list(item_ids))).all())
    best = {}
    for n, key, current, rev in rows:
        at = (key, n.item_id)
        rank = (rev == current, n.updated_at.isoformat() if n.updated_at else "", n.id)
        if at not in best or rank > best[at][0]:
            best[at] = (rank, Decimal(str(n.qty_per_unit)))
    return {at: v for at, (_r, v) in best.items()}


def permitted_for(db, client_id, order, item_ids):
    """{item id: {"permitted": quantity, "basis": [{"boq_key", "what", "order_qty", "norm", "allowed"}]}} for the materials that have a norm on any
    of the order's BOQ lines; a material with none is not in it (nothing to measure against)."""
    lines = order_lines(db, order)
    norms = norms_by_key(db, client_id, order.job_id, item_ids)
    out = {}
    for key, qty, what in lines:
        for item_id in item_ids:
            norm = norms.get((key, item_id))
            if norm is None:
                continue
            allowed = (Decimal(str(qty)) * norm).quantize(Q3)
            slot = out.setdefault(item_id, {"permitted": ZERO, "basis": []})
            slot["permitted"] += allowed
            slot["basis"].append({"boq_key": key, "what": what, "order_qty": qty, "norm": str(norm), "allowed": s3(allowed)})
    return out


def issued_free(db, order_id, item_ids, exclude_issue_id=None):
    """{item id: quantity issued free of cost under the order, net of what came back}: posted issues and posted returns only, so a cancelled
    (or reversed) issue has nothing here and an issue still waiting has nothing here yet."""
    q = (db.query(DBStoreIssueLine.id, DBStoreIssueLine.item_id, DBStoreIssueLine.qty).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
         .filter(DBStoreIssue.subcontract_order_id == order_id, DBStoreIssue.issue_type == SUBCONTRACTOR, DBStoreIssue.status == DocStatus.POSTED.value,
                 DBStoreIssueLine.item_id.in_(list(item_ids) or [0]), (DBStoreIssueLine.chargeable == 0) | (DBStoreIssueLine.chargeable.is_(None))))
    if exclude_issue_id:
        q = q.filter(DBStoreIssue.id != exclude_issue_id)
    lines = q.all()
    if not lines:
        return {}
    back = {}
    for line_id, returned in (db.query(DBStoreIssueReturnLine.issue_line_id, DBStoreIssueReturnLine.qty_returned).join(DBStoreIssueReturn, DBStoreIssueReturn.id == DBStoreIssueReturnLine.return_id)
                              .filter(DBStoreIssueReturnLine.issue_line_id.in_([l[0] for l in lines]), DBStoreIssueReturn.status == DocStatus.POSTED.value).all()):
        back[line_id] = back.get(line_id, ZERO) + Decimal(str(returned or 0))
    out = {}
    for line_id, item_id, qty in lines:
        out[item_id] = out.get(item_id, ZERO) + Decimal(str(qty or 0)) - back.get(line_id, ZERO)
    return {i: max(ZERO, q) for i, q in out.items()}


def _steel_governed(db, client_id, issue, item):
    """Steel the project's approved BBS already holds to an allowance: left to that one, not checked twice."""
    from app.services import steel_allowance as steel
    return bool(steel.diameter_of(item) and steel.bbs_kg(db, client_id, issue.project_id))


def applies(issue) -> bool:
    return issue.issue_type == SUBCONTRACTOR and bool(issue.subcontract_order_id)


def allowance_rows(db, client_id, issue, lines):
    """For each material the issue takes free of cost that has an allowance: {item_id, item_code, item_name, uom, permitted, issued, remaining,
    requested, excess, within, basis}. `lines` are the issue's lines (base unit). Materials with no allowance to measure against are left out."""
    if not applies(issue):
        return []
    order = db.get(models.DBSubcontractOrder, issue.subcontract_order_id)
    if order is None:
        return []
    asked = {}
    for l in lines:
        if not l.chargeable:
            asked[l.item_id] = asked.get(l.item_id, ZERO) + Decimal(str(l.qty or 0))
    if not asked:
        return []
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(asked))).all()}
    asked = {i: q for i, q in asked.items() if i in items and not _steel_governed(db, client_id, issue, items[i])}
    if not asked:
        return []
    allowed = permitted_for(db, client_id, order, list(asked))
    used = issued_free(db, order.id, list(asked), exclude_issue_id=issue.id)
    out = []
    for item_id, qty in asked.items():
        if item_id not in allowed:
            continue
        permitted, before = allowed[item_id]["permitted"], used.get(item_id, ZERO)
        remaining = permitted - before
        excess = min(qty, max(ZERO, before + qty - permitted))
        it = items[item_id]
        out.append({"item_id": item_id, "item_code": it.item_code, "item_name": it.item_name, "uom": _base_uom(db, it), "permitted": permitted, "issued": before,
                    "remaining": remaining, "requested": qty, "excess": excess, "within": excess <= EPS, "basis": allowed[item_id]["basis"],
                    "subcontract_order_id": order.id, "subcontractor_id": order.contractor_id})
    out.sort(key=lambda r: r["item_name"] or "")
    return out


def breaches(db, client_id, issue, lines) -> list:
    """The materials this issue would take past the allowance, in words; [] when it stays inside it. Counted on top of what has gone out already."""
    out = []
    for r in allowance_rows(db, client_id, issue, lines):
        if not r["within"]:
            out.append("%s: %s %s with this issue against %s %s permitted by its norms for the work ordered (%s %s issued before); %s %s over"
                       % (r["item_name"], s3(r["issued"] + r["requested"]), r["uom"], s3(r["permitted"]), r["uom"], s3(r["issued"]), r["uom"], s3(r["excess"]), r["uom"]))
    return out


# --- the request, the Master's decision, and the audit trail --------------------------------------------------------------------

def _log(db, actor, issue, action, note):
    db.add(DBStoreOutwardLog(client_id=actor.client.id, doc_type=ISSUE, doc_id=issue.id, action=action, from_status=issue.status, to_status=issue.status,
                             user_id=actor.user_id, user_name=actor.name, note=(note or "")[:300]))


def requests_of(db, issue_id):
    return db.query(DBStoreFreeIssueRequest).filter(DBStoreFreeIssueRequest.issue_id == issue_id).order_by(DBStoreFreeIssueRequest.id).all()


def request_dict(db, r):
    item = db.get(models.DBItem, r.item_id)
    order = db.get(models.DBSubcontractOrder, r.subcontract_order_id)
    con = db.get(models.DBContractor, r.subcontractor_id) if r.subcontractor_id else None
    job = db.get(models.DBJob, r.project_id) if r.project_id else None
    try:
        basis = json.loads(r.basis or "[]")
    except ValueError:
        basis = []
    return {"id": r.id, "issue_id": r.issue_id, "status": r.status, "item_id": r.item_id, "item_code": item.item_code if item else "", "item_name": item.item_name if item else "",
            "subcontract_order_id": r.subcontract_order_id, "subcontract_order": (order.wo_number or str(order.id)) if order else "",
            "subcontractor_id": r.subcontractor_id, "subcontractor": (con.company_name if con else "") or "", "project": ("%s - %s" % (job.number, job.name)) if job else "",
            "permitted_qty": s3(r.permitted_qty or 0), "issued_qty": s3(r.issued_qty or 0), "requested_qty": s3(r.requested_qty or 0), "excess_qty": s3(r.excess_qty or 0),
            "approved_excess": s3(r.approved_excess) if r.approved_excess is not None else None, "reason": r.reason or "", "basis": basis,
            "requested_by": r.requested_by or "", "requested_at": r.requested_at.isoformat(timespec="seconds") if r.requested_at else "",
            "decided_by": r.decided_by or "", "decided_at": r.decided_at.isoformat(timespec="seconds") if r.decided_at else "", "decision_note": r.decision_note or ""}


def sync_requests(db, actor, issue, reason=""):
    """Bring the issue's requests in line with what it takes now: one for each material past its allowance (opened, or brought up to date),
    and any open one for a material now inside it withdrawn. An approved request that no longer covers the excess is asked again. Returns the
    rows still past the allowance."""
    from app.services.store_outward import issue_lines
    rows = allowance_rows(db, actor.client.id, issue, issue_lines(db, issue))
    over = [r for r in rows if not r["within"]]
    have = {r.item_id: r for r in requests_of(db, issue.id)}
    now = datetime.now()
    said = (reason or issue.purpose or "").strip()[:300]
    for r in over:
        row = have.get(r["item_id"])
        figures = dict(permitted_qty=r["permitted"], issued_qty=r["issued"], requested_qty=r["requested"], excess_qty=r["excess"], basis=json.dumps(r["basis"]))
        if row is None:
            row = DBStoreFreeIssueRequest(client_id=actor.client.id, issue_id=issue.id, project_id=issue.project_id, subcontractor_id=r["subcontractor_id"],
                                          subcontract_order_id=r["subcontract_order_id"], item_id=r["item_id"], status=FREE_PENDING, requested_by=actor.name,
                                          requested_at=now, reason=said, **figures)
            db.add(row)
            _log(db, actor, issue, "free_issue_requested", "%s: %s %s asked, %s permitted, %s over. %s" % (r["item_name"], s3(r["requested"]), r["uom"], s3(r["permitted"]), s3(r["excess"]), said))
        elif row.status == FREE_APPROVED and (row.approved_excess or ZERO) + EPS >= r["excess"]:
            continue                                                   # the Master already allowed at least this much
        elif row.status in (FREE_PENDING, FREE_APPROVED, FREE_WITHDRAWN, FREE_REJECTED):
            if row.status != FREE_PENDING:
                _log(db, actor, issue, "free_issue_requested", "%s: asked again - the excess is now %s %s" % (r["item_name"], s3(r["excess"]), r["uom"]))
                row.requested_by, row.requested_at = actor.name, now
                row.decided_by, row.decided_at, row.decision_note, row.approved_excess = "", None, "", None
            for k, v in figures.items():
                setattr(row, k, v)
            if said:
                row.reason = said
            row.status = FREE_PENDING
    still = {r["item_id"] for r in over}
    for item_id, row in have.items():
        if item_id not in still and row.status == FREE_PENDING:
            row.status, row.decision_note = FREE_WITHDRAWN, "No longer past the allowance."
    db.flush()
    return over


def waiting(db, actor, issue, reason=""):
    """An issue sent for approval that takes a material past its allowance: the request is recorded and the Master is told at once, so it does
    not sit in the store's list waiting for somebody to notice it. Returns the words for what is over; [] when nothing is."""
    over = sync_requests(db, actor, issue, reason)
    if not over:
        return []
    said = "; ".join("%s %s over (%s asked, %s permitted)" % (s3(r["excess"]), r["uom"] + " of " + r["item_name"], s3(r["requested"]), s3(r["permitted"])) for r in over)
    if not is_master(actor):
        from app.core.notifications import tell_approvers
        con = db.get(models.DBContractor, issue.subcontractor_id) if issue.subcontractor_id else None
        tell_approvers(db, actor.client.id, "Free issue past the allowance: %s waits for you" % issue.number,
                       "%s to %s, raised by %s. %s" % (issue.number, (con.company_name if con else "the contractor"), actor.name, said), rights=(), owner=True)
    return over


def gate(db, actor, issue, action, direct, reason=""):
    """Run at approve and at post. Past the allowance, only the Master lets it through - never the storekeeper, never as a direct issue by anybody
    else - and what the Master approved is what may go out: an issue that has come to take more than was approved (other issues have used
    the allowance since) must be asked again."""
    from app.services.store_outward import issue_lines
    if not applies(issue):
        return
    if action == "post":
        # Serialise the posting of issues under one order: the allowance is worked out below with nobody else's posting in between.
        db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == issue.subcontract_order_id).with_for_update().first()
    rows = [r for r in allowance_rows(db, actor.client.id, issue, issue_lines(db, issue)) if not r["within"]]
    have = {r.item_id: r for r in requests_of(db, issue.id)}
    if not rows:
        return
    said = breaches(db, actor.client.id, issue, issue_lines(db, issue))
    said = "; ".join(said)
    if action == "approve":
        if not is_master(actor):
            if direct:
                raise HTTPException(409, "This takes free-issue material past what its norms allow for the work ordered (%s). It cannot go out directly: save it and send it for the Master's approval." % said)
            raise HTTPException(403, "This takes free-issue material past what its norms allow for the work ordered (%s). Only the Master can approve it." % said)
        sync_requests(db, actor, issue, reason)
        now = datetime.now()
        for r in rows:
            row = next((x for x in requests_of(db, issue.id) if x.item_id == r["item_id"]), None)
            if row is None or row.status == FREE_APPROVED:
                continue
            row.status, row.decided_by, row.decided_at, row.approved_excess = FREE_APPROVED, actor.name, now, r["excess"]
            row.decision_note = ((reason or "").strip() or ("Issued directly by the Master" if direct else ""))[:300]
            _log(db, actor, issue, "free_issue_approved", "%s: %s %s over the allowance approved by %s. %s" % (r["item_name"], s3(r["excess"]), r["uom"], actor.name, row.decision_note))
        db.flush()
        return
    for r in rows:
        row = have.get(r["item_id"])
        if row is None or row.status != FREE_APPROVED or (row.approved_excess or ZERO) + EPS < r["excess"]:
            raise HTTPException(409, "Since it was approved, %s has gone past what its norms allow for the work ordered (%s). Send it back and have it approved by the Master." % (r["item_name"], said))


def reject(db, actor, issue, note):
    """The Master refuses the extra material. The requests are closed as REJECTED with who and why; the caller then cancels the issue."""
    if not is_master(actor):
        raise HTTPException(403, "Only the Master can refuse or approve free-issue material past its allowance.")
    why = (note or "").strip()
    if len(why) < 3:
        raise HTTPException(400, "Say why it is refused.")
    open_ = [r for r in requests_of(db, issue.id) if r.status in (FREE_PENDING, FREE_APPROVED)]
    if not open_:
        raise HTTPException(409, "Nothing on this issue is waiting for the Master's decision.")
    now = datetime.now()
    for r in open_:
        r.status, r.decided_by, r.decided_at, r.decision_note, r.approved_excess = FREE_REJECTED, actor.name, now, why[:300], None
    _log(db, actor, issue, "free_issue_rejected", why)
    db.flush()
    return open_


def on_cancel(db, actor, issue):
    """The issue is cancelled: what was still waiting or approved for it is withdrawn (a refusal keeps its own status). The allowance it had
    used comes back by itself, since it is worked out from posted issues only."""
    for r in requests_of(db, issue.id):
        if r.status in (FREE_PENDING, FREE_APPROVED):
            r.status = FREE_WITHDRAWN
            r.decision_note = (r.decision_note or ("Issue %s cancelled." % issue.number))[:300]


def status_of(db, client_id, issue, lines):
    """What the screens show for an issue: the allowance row for each material and the requests made for it."""
    return {"rows": [{**{k: (s3(v) if isinstance(v, Decimal) else v) for k, v in r.items() if k != "basis"}, "basis": r["basis"]} for r in allowance_rows(db, client_id, issue, lines)],
            "requests": [request_dict(db, r) for r in requests_of(db, issue.id)]}


def allowance_for_order(db, client_id, order, item_ids=None):
    """The allowance and what has been drawn of it, material by material, for one subcontract order - contractor, work order, material, quantity
    ordered, norm, permitted, issued, remaining - for the materials with a norm on any of its BOQ lines."""
    lines = order_lines(db, order)
    if item_ids is None:
        keys = {k for k, _q, _w in lines}
        if not keys:
            return []
        item_ids = sorted({n.item_id for n in db.query(DBStoreMaterialNorm).join(models.DBBoqLine, models.DBBoqLine.id == DBStoreMaterialNorm.boq_item_id)
                           .join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id)
                           .filter(DBStoreMaterialNorm.client_id == client_id, models.DBBoq.job_id == order.job_id, models.DBBoqLine.key.in_(keys)).all()})
    allowed = permitted_for(db, client_id, order, list(item_ids))
    used = issued_free(db, order.id, list(item_ids))
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(allowed) or [0])).all()}
    con = db.get(models.DBContractor, order.contractor_id) if order.contractor_id else None
    out = []
    for item_id, a in allowed.items():
        it = items.get(item_id)
        if it is None:
            continue
        before = used.get(item_id, ZERO)
        out.append({"item_id": item_id, "item_code": it.item_code, "item_name": it.item_name, "uom": _base_uom(db, it), "subcontract_order_id": order.id,
                    "subcontract_order": order.wo_number or str(order.id), "subcontractor_id": order.contractor_id, "subcontractor": (con.company_name if con else "") or "",
                    "order_qty": round(sum(float(b["order_qty"]) for b in a["basis"]), 3), "basis": a["basis"], "permitted": s3(a["permitted"]), "issued": s3(before),
                    "remaining": s3(a["permitted"] - before)})
    out.sort(key=lambda r: r["item_name"] or "")
    return out
