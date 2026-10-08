"""The stores endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.documents import form_pdf
from app import models
from app.db import get_db

from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.core.currency import inr, money, unit_rate
from app.core.sheets import sheet_response
from app.documents.forms import _field_doc, form_pdf_response
from app.schemas.stores import AdjustmentIn, StockIssueIn, TransferIn
from app.services.projects import job_or_404
from app.services.stores import (
    _replace_issue_lines,
    charge_issue_to_gang,
    issue_dict,
    issue_or_404,
    item_rate,
    next_issue_number,
    next_transfer_number,
    rebuild_stock_balances,
    replay_stock_ledger,
    stock_balances,
    stock_movement,
    store_holding,
)
from app.services.subcontract_orders import wo_or_404, work_order_or_404, work_order_to_dict


router = APIRouter()


@router.get("/api/stock")
def stock_on_hand(request: Request, store: str = "", low_only: bool = False,
                  db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    balances = stock_balances(db, client.id, store=store or None)
    levels = {i.item_code: (i.reorder_level or 0.0)
              for i in db.query(models.DBItem).filter(
                  models.DBItem.client_id == client.id).all()}

    rows = []
    for code, a in balances.items():
        level = levels.get(code, 0.0)
        a = dict(a)
        a["received"] = money(a["received"])
        a["issued"] = money(a["issued"])
        a["reorder_level"] = money(level)
        # A level of zero means nobody set one, which is not the same as
        # "never warn" - so it stays quiet rather than shouting about
        # every item in the yard.
        a["below_level"] = bool(level) and a["on_hand"] < level
        a["negative"] = a["on_hand"] < 0
        rows.append(a)
    rows.sort(key=lambda r: (not r["below_level"], r["item_code"]))
    if low_only:
        rows = [r for r in rows if r["below_level"]]

    return {
        "stock": rows,
        "summary": {
            "items_held": len([r for r in rows if r["on_hand"] > 0]),
            "value_on_hand": money(sum(r["value"] for r in rows)),
            "below_reorder": len([r for r in rows if r["below_level"]]),
            # Issued more than was ever received: the store is telling you
            # its own records are wrong, which is worth surfacing loudly.
            "negative_lines": len([r for r in rows if r["negative"]]),
        },
    }


@router.post("/api/stock/rebuild")
def rebuild_balances(request: Request, db: Session = Depends(get_db)):
    """Replay the ledger and overwrite the running balances.

    Reports what changed, because a balance that had drifted from its ledger
    is worth knowing about - it means something wrote stock without going
    through the one door that should.
    """
    client, _, actor_name = wo_actor(request, db, "stores.manage")
    before = {b.item_code: money(b.on_hand) for b in db.query(models.DBStockBalance).filter(
        models.DBStockBalance.client_id == client.id).all()}
    n = rebuild_stock_balances(db, client.id)
    after = {b.item_code: money(b.on_hand) for b in db.query(models.DBStockBalance).filter(
        models.DBStockBalance.client_id == client.id).all()}
    drift = [{"item_code": k, "was": before.get(k, 0.0), "now": v}
             for k, v in after.items() if money(before.get(k, 0.0)) != v]
    log_audit(db, client.id, "stock_rebuilt", "item", None, "",
              "%d items, %d drifted" % (n, len(drift)), request)
    db.commit()
    return {"ok": True, "items": n, "drift": drift,
            "message": ("Rebuilt %d balances from the ledger. " % n) +
                       ("All agreed." if not drift else
                        "%d had drifted and are corrected." % len(drift))}


@router.get("/api/stock/{item_code}/ledger")
def stock_ledger(item_code: str, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    rows = db.query(models.DBStockMovement).filter(
        models.DBStockMovement.client_id == client.id,
        models.DBStockMovement.item_code == item_code).order_by(
            models.DBStockMovement.id).all()
    running, out = 0.0, []
    for m in rows:
        running = money(running + (m.quantity or 0))
        out.append({
            "id": m.id, "kind": m.kind, "moved_on": m.moved_on or "",
            "quantity": money(m.quantity), "rate": unit_rate(m.rate),
            "value": money(m.value), "balance": running,
            "store": m.store or "", "source_type": m.source_type or "",
            "source_id": m.source_id, "source_ref": m.source_ref or "",
            "remarks": m.remarks or "", "recorded_by_name": m.recorded_by_name or "",
        })
    bal = stock_balances(db, client.id, item_code=item_code).get(item_code, {})
    return {"item_code": item_code, "item_name": bal.get("item_name", ""),
            "uom": bal.get("uom", ""), "on_hand": money(bal.get("on_hand", 0)),
            "rate": unit_rate(bal.get("rate", 0)), "value": money(bal.get("value", 0)),
            "movements": list(reversed(out))}


@router.get("/api/stock-issues")
def list_stock_issues(request: Request, work_order_id: int = 0,
                      db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBStockIssue).filter(
        models.DBStockIssue.client_id == client.id)
    if work_order_id:
        q = q.filter(models.DBStockIssue.work_order_id == work_order_id)
    issues = q.order_by(models.DBStockIssue.id.desc()).limit(200).all()
    wo_names = {w.id: (w.number or "") for w in db.query(
        models.DBWorkOrder.id, models.DBWorkOrder.number).filter(
            models.DBWorkOrder.client_id == client.id).all()}
    rows = [issue_dict(db, i, wo_names=wo_names) for i in issues]
    return {
        "issues": rows,
        "summary": {
            "notes": len(rows),
            "not_yet_posted": len([r for r in rows if r["status"] == "DRAFT"]),
            "issued_value": money(sum(r["total_value"] for r in rows
                                      if r["status"] == "POSTED")),
        },
    }


@router.post("/api/stock-issues")
def create_stock_issue(body: StockIssueIn, request: Request,
                       db: Session = Depends(get_db)):
    """Draw up an issue note, priced at what the store's stock actually cost."""
    client, actor_id, actor_name = wo_actor(request, db, "site.record")
    wo = None
    if body.work_order_id:
        wo = work_order_or_404(db, client.id, body.work_order_id)
    # Material goes to a site before its order is placed - mobilisation, the
    # first pour on a letter of intent. Issued "not against an order" it was
    # charged to no project at all; the project can be named on its own.
    job_id = wo.job_id if wo else (job_or_404(db, client.id, body.job_id).id if body.job_id else None)

    issue = models.DBStockIssue(
        client_id=client.id, work_order_id=(wo.id if wo else None),
        job_id=job_id,
        number=next_issue_number(db, client.id),
        issued_on=(body.issued_on or datetime.now().strftime("%Y-%m-%d")),
        store=((body.store or "").strip() or store_holding(db, client.id, body.lines or [])),
        status="DRAFT",
        issued_to=(body.issued_to or "").strip(),
        purpose=(body.purpose or "").strip(),
        remarks=(body.remarks or "").strip(),
        issued_by=actor_id, issued_by_name=actor_name)
    db.add(issue)
    db.flush()
    _replace_issue_lines(db, client.id, issue, body.lines or [])
    db.commit()
    db.refresh(issue)
    return {"ok": True, "issue": issue_dict(db, issue, detail=True),
            "message": "%s opened." % issue.number}


@router.get("/api/stock-issues/{issue_id}")
def get_stock_issue(issue_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return issue_dict(db, issue_or_404(db, client.id, issue_id), detail=True)


@router.put("/api/stock-issues/{issue_id}")
def update_stock_issue(issue_id: int, body: StockIssueIn, request: Request,
                       db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "site.record")
    issue = issue_or_404(db, client.id, issue_id)
    if (issue.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "A posted issue cannot be changed. "
                                 "Post a return instead.")
    for field in ("issued_on", "issued_to", "purpose", "store", "remarks"):
        val = getattr(body, field, None)
        if val is not None and val != "":
            setattr(issue, field, val)
    if body.lines is not None:
        _replace_issue_lines(db, client.id, issue, body.lines)
    db.commit()
    db.refresh(issue)
    return {"ok": True, "issue": issue_dict(db, issue, detail=True)}


@router.post("/api/stock-issues/{issue_id}/post")
def post_stock_issue(issue_id: int, request: Request, body: dict = None,
                     db: Session = Depends(get_db)):
    """Take it out of the store. This is where stock actually moves."""
    client, actor_id, actor_name = wo_actor(request, db, "site.record")
    issue = issue_or_404(db, client.id, issue_id)
    if (issue.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Only a draft can be posted.")
    lines = db.query(models.DBStockIssueLine).filter(
        models.DBStockIssueLine.stock_issue_id == issue.id).all()
    if not lines:
        raise HTTPException(400, "Nothing on this issue note.")

    allow_negative = bool((body or {}).get("allow_negative"))
    short = []
    for l in lines:
        on_hand = money(stock_balances(db, client.id, item_code=l.item_code).get(
            l.item_code, {}).get("on_hand", 0))
        if l.quantity > on_hand:
            short.append("%s: %s in store, %s asked for"
                         % (l.item_code, on_hand, money(l.quantity)))
    if short and not allow_negative:
        # Refused rather than silently going negative: material that is not
        # there has either not been booked in or has already gone, and both
        # want looking at before more is issued on paper.
        raise HTTPException(409, "Not enough in the store - %s. Book the "
                                 "delivery in first, or post it anyway if the "
                                 "store is behind." % "; ".join(short[:4]))

    # Handed to a gang whose rate includes the material: the order says which
    # project it was spent on, and it has to be known before the stock moves
    # or the movements are written against no project at all.
    recover_order = None
    recover_from = (body or {}).get("recover_from_order_id")
    if recover_from:
        recover_order = wo_or_404(db, client.id, int(recover_from))
        if (recover_order.status or "") not in ("APPROVED", "EXECUTED"):
            raise HTTPException(409, "%s is %s; material is charged to a live order."
                                     % (recover_order.wo_number,
                                        (recover_order.status or "").lower()))
        if not issue.job_id and recover_order.job_id:
            issue.job_id = recover_order.job_id

    for l in lines:
        stock_movement(db, client.id, l.item_code, "ISSUE", -l.quantity, l.rate,
                       item_name=l.item_name, uom=l.uom, store=issue.store,
                       moved_on=issue.issued_on, source_type="stock_issue",
                       source_id=issue.id, source_ref=issue.number,
                       work_order_id=issue.work_order_id, job_id=issue.job_id,
                       remarks=issue.purpose, recorded_by=actor_id,
                       recorded_by_name=actor_name)
    issue.status = "POSTED"
    issue.posted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # It is theirs to pay for, recovered from their next bill on its own.
    charged = 0.0
    if recover_order:
        charged = charge_issue_to_gang(db, client.id, issue, recover_order,
                                       float((body or {}).get("markup_percent") or 0))
        issue.issued_to = issue.issued_to or ("Recover from " + (recover_order.wo_number or ""))
    log_audit(db, client.id, "stock_issued", "stock_issue", issue.id,
              issue.number or "", "%s lines, %s" % (len(lines), inr(issue.total_value)),
              request)
    db.commit()
    db.refresh(issue)
    return {"ok": True, "issue": issue_dict(db, issue, detail=True),
            "message": "%s issued - %s of material has left the store."
                       % (issue.number, inr(issue.total_value))}


@router.post("/api/stock-issues/{issue_id}/cancel")
def cancel_stock_issue(issue_id: int, request: Request, body: dict = None,
                       db: Session = Depends(get_db)):
    """A posted issue is reversed by putting the material back, not erased."""
    client, actor_id, actor_name = wo_actor(request, db, "stores.manage")
    issue = issue_or_404(db, client.id, issue_id)
    if (issue.status or "DRAFT") == "CANCELLED":
        raise HTTPException(409, "Already cancelled.")
    if (issue.status or "DRAFT") == "POSTED":
        for l in db.query(models.DBStockIssueLine).filter(
                models.DBStockIssueLine.stock_issue_id == issue.id).all():
            stock_movement(db, client.id, l.item_code, "RETURN", l.quantity, l.rate,
                           item_name=l.item_name, uom=l.uom, store=issue.store,
                           source_type="stock_issue", source_id=issue.id,
                           source_ref=issue.number + " cancelled",
                           work_order_id=issue.work_order_id, job_id=issue.job_id,
                           remarks="Issue cancelled", recorded_by=actor_id,
                           recorded_by_name=actor_name)
    issue.status = "CANCELLED"
    issue.remarks = ((body or {}).get("comments") or issue.remarks or "")
    db.commit()
    return {"ok": True, "message": "%s cancelled and the material put back."
                                   % issue.number}


@router.post("/api/stock/adjustments")
def adjust_stock(body: AdjustmentIn, request: Request,
                 db: Session = Depends(get_db)):
    """A physical count. The difference is posted, the history is left alone."""
    client, actor_id, actor_name = wo_actor(request, db, "stores.manage")
    code = (body.item_code or "").strip()
    bal = stock_balances(db, client.id, item_code=code).get(code, {})
    on_hand = money(bal.get("on_hand", 0))
    difference = money(money(body.counted) - on_hand)
    if not difference:
        return {"ok": True, "difference": 0,
                "message": "The count agrees with the book. Nothing posted."}
    stock_movement(db, client.id, code, "ADJUSTMENT", difference,
                   bal.get("rate", 0), store=body.store or "Main store",
                   source_type="manual", source_ref="Physical count",
                   remarks=(body.remarks or "Physical count"),
                   recorded_by=actor_id, recorded_by_name=actor_name)
    log_audit(db, client.id, "stock_adjusted", "item", None, code,
              "book %s counted %s" % (on_hand, money(body.counted)), request)
    db.commit()
    return {"ok": True, "was": on_hand, "now": money(body.counted),
            "difference": difference,
            "message": "%s %s %s." % (code,
                                      "written down by" if difference < 0 else "written up by",
                                      abs(difference))}


@router.get("/api/stock/consumption/{work_order_id}")
def material_consumption(work_order_id: int, request: Request,
                         db: Session = Depends(get_db)):
    """BOM against actual issues - the wastage report.

    The BOM is what the contract was costed on. The issues are what the site
    actually drew. The gap between them is waste, theft, or a BOM that was
    wrong, and on a material-heavy contract it is the difference between the
    margin that was signed off and the one that turns up.
    """
    client = require_erp_read(request, db)
    wo = work_order_or_404(db, client.id, work_order_id)

    planned = {}
    for b in db.query(models.DBBomLine).filter(
            models.DBBomLine.work_order_id == wo.id).all():
        p = planned.setdefault(b.rm_code, {
            "item_code": b.rm_code, "item_name": b.rm_name or "",
            "uom": b.uom or "", "planned_qty": 0.0, "planned_value": 0.0})
        p["planned_qty"] = money(p["planned_qty"] + (b.qty or 0))
        p["planned_value"] = money(p["planned_value"] + (b.amount or 0))

    actual = {}
    for m in db.query(models.DBStockMovement).filter(
            models.DBStockMovement.client_id == client.id,
            models.DBStockMovement.work_order_id == wo.id).all():
        a = actual.setdefault(m.item_code, {"qty": 0.0, "value": 0.0})
        # An issue is negative and a return positive, so consumption is the
        # negated sum and a cancelled issue costs the job nothing.
        a["qty"] = money(a["qty"] - (m.quantity or 0))
        a["value"] = money(a["value"] - (m.value or 0))

    rows = []
    for code in sorted(set(planned) | set(actual)):
        p = planned.get(code, {"item_code": code, "item_name": "", "uom": "",
                               "planned_qty": 0.0, "planned_value": 0.0})
        a = actual.get(code, {"qty": 0.0, "value": 0.0})
        over = money(a["qty"] - p["planned_qty"])
        rows.append({
            "item_code": code, "item_name": p["item_name"], "uom": p["uom"],
            "planned_qty": p["planned_qty"], "planned_value": p["planned_value"],
            "issued_qty": a["qty"], "issued_value": a["value"],
            "variance_qty": over,
            "variance_value": money(a["value"] - p["planned_value"]),
            "percent_used": (round(a["qty"] / p["planned_qty"] * 100, 1)
                             if p["planned_qty"] else 0.0),
            "over_consumed": over > 0,
            # Drawn without ever being budgeted: usually a BOM nobody updated
            # after a variation, occasionally something worse.
            "unplanned": p["planned_qty"] == 0 and a["qty"] > 0,
        })

    return {
        "work_order": work_order_to_dict(db, wo),
        "lines": rows,
        "summary": {
            "planned_value": money(sum(r["planned_value"] for r in rows)),
            "issued_value": money(sum(r["issued_value"] for r in rows)),
            "variance_value": money(sum(r["variance_value"] for r in rows)),
            "lines_over_consumed": len([r for r in rows if r["over_consumed"]]),
            "unplanned_items": len([r for r in rows if r["unplanned"]]),
        },
    }


@router.get("/api/stock.xlsx")
def stock_export(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    balances = stock_balances(db, client.id)
    levels = {i.item_code: (i.reorder_level or 0.0)
              for i in db.query(models.DBItem).filter(
                  models.DBItem.client_id == client.id).all()}
    rows = [(a["item_code"], a["item_name"], a["uom"], money(a["received"]),
             money(a["issued"]), a["on_hand"], unit_rate(a["rate"]), a["value"],
             money(levels.get(code, 0.0)),
             "yes" if levels.get(code, 0.0) and a["on_hand"] < levels[code] else "")
            for code, a in sorted(balances.items())]
    return sheet_response(
        ("Item code", "Description", "UOM", "Received", "Issued", "On hand",
         "Rate", "Value", "Reorder level", "Below level"),
        rows, "stock_on_hand.xlsx",
        preamble=[("STOCK ON HAND", client.company_name or ""),
                  ("As at", datetime.now().strftime("%Y-%m-%d")),
                  ()],
        closing=[(), ("Total value", "", "", "", "", "", "",
                      money(sum(r[7] for r in rows)))])


@router.get("/api/stock/stores")
def list_stores(request: Request, db: Session = Depends(get_db)):
    """Every store that has ever held anything, with what it holds now."""
    client = require_erp_read(request, db)
    names = sorted({s for (s,) in db.query(models.DBStockMovement.store).filter(
        models.DBStockMovement.client_id == client.id).distinct().all() if s})
    out = []
    for name in names:
        held = replay_stock_ledger(db, client.id, store=name)
        live = [a for a in held.values() if abs(a["on_hand"]) > 0.0001]
        out.append({"store": name, "items": len(live),
                    "value": money(sum(a["value"] for a in live))})
    return {"stores": out}


@router.post("/api/stock/transfers")
def transfer_stock(body: TransferIn, request: Request, db: Session = Depends(get_db)):
    """Material from one store to another, at what it cost.

    Refused when the store it is coming from does not hold it: a transfer on
    paper of cement that is not in the shed is how two sites end up counting
    the same bags.
    """
    client, actor_id, actor_name = wo_actor(request, db, "stores.manage")
    src, dst = (body.from_store or "").strip(), (body.to_store or "").strip()
    if not src or not dst:
        raise HTTPException(400, "Say where it is coming from and where it is going.")
    if src.lower() == dst.lower():
        raise HTTPException(400, "It is already in %s." % src)
    lines = [l for l in body.lines if (l.item_code or "").strip() and (l.qty or 0) > 0]
    if not lines:
        raise HTTPException(400, "Nothing to transfer.")
    held = replay_stock_ledger(db, client.id, store=src,
                               item_codes=[l.item_code for l in lines])
    short = []
    for l in lines:
        have = money(held.get(l.item_code, {}).get("on_hand", 0))
        if l.qty > have + 0.0001:
            short.append("%s: %s in %s, %s asked for" % (l.item_code, have, src, money(l.qty)))
    if short:
        raise HTTPException(409, "Not enough to send - " + "; ".join(short[:4]) + ".")
    number = next_transfer_number(db, client.id)
    on = (body.moved_on or datetime.now().strftime("%Y-%m-%d"))[:10]
    value = 0.0
    for l in lines:
        rate = item_rate(db, client.id, l.item_code)
        common = dict(moved_on=on, source_type="transfer", source_ref=number,
                      remarks=("%s -> %s. %s" % (src, dst, body.note or "")).strip(),
                      recorded_by=actor_id, recorded_by_name=actor_name)
        stock_movement(db, client.id, l.item_code, "TRANSFER_OUT", -l.qty, rate, store=src, **common)
        stock_movement(db, client.id, l.item_code, "TRANSFER_IN", l.qty, rate, store=dst, **common)
        value += l.qty * rate
    log_audit(db, client.id, "stock_transferred", "stock", 0, number,
              "%s -> %s, %d lines, %s" % (src, dst, len(lines), inr(value)), request)
    db.commit()
    return {"ok": True, "number": number, "value": money(value),
            "message": "%s: %d line%s, %s, sent from %s to %s." % (
                number, len(lines), "" if len(lines) == 1 else "s", inr(value), src, dst)}


@router.get("/api/stock/transfers")
def list_transfers(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    out = {}
    for m in db.query(models.DBStockMovement).filter(
            models.DBStockMovement.client_id == client.id,
            models.DBStockMovement.kind == "TRANSFER_OUT").order_by(
                models.DBStockMovement.id.desc()).limit(2000).all():
        t = out.setdefault(m.source_ref, {"number": m.source_ref, "moved_on": m.moved_on,
                                          "from_store": m.store, "to_store": "",
                                          "lines": [], "value": 0.0,
                                          "by": m.recorded_by_name or ""})
        t["lines"].append({"item_code": m.item_code, "item_name": m.item_name,
                           "uom": m.uom, "qty": money(-m.quantity), "rate": unit_rate(m.rate)})
        t["value"] = money(t["value"] - (m.value or 0))
        remarks = m.remarks or ""
        if " -> " in remarks:
            t["to_store"] = remarks.split(" -> ", 1)[1].split(".", 1)[0]
    return {"transfers": list(out.values())}


@router.get("/api/stock-issues/{issue_id}/document.pdf")
def stock_issue_pdf(issue_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = issue_dict(db, issue_or_404(db, client.id, issue_id), detail=True)
    rows = [[str(n), l["item_code"], l["item_name"], l["uom"], form_pdf.qty_text(l["quantity"]),
             form_pdf.plain_number(l["rate"]), form_pdf.plain_number(l["amount"])] for n, l in enumerate(d["lines"], 1)]
    blocks = [
        {"type": "pairs", "cols": 2, "rows": [("From store", d["store"]), ("Issued to", d["issued_to"] or "-"),
                                              ("Work order", d["work_order"] or "-"), ("Purpose", d["purpose"] or "-")]},
        {"type": "table", "columns": [("#", 6, "C"), ("Code", 22, "L"), ("Material", 72, "L"), ("UoM", 14, "C"),
                                      ("Qty", 20, "R"), ("Rate", 20, "R"), ("Value", 28, "R")],
         "rows": rows, "totals": [("TOTAL VALUE", form_pdf.plain_number(d["total_value"]), True)]},
        {"type": "pairs", "rows": [("Remarks", d["remarks"] or "-")], "label_width": 30},
    ]
    sig = [("Issued By (Store)", d["issued_by_name"] or ""), ("Received By (Site)", ""), ("Site Engineer", ""),
           ("Store In-charge", "")]
    return form_pdf_response(_field_doc(db, client, "MATERIAL ISSUE SLIP",
                                        [("Issue No", d["number"]), ("Date", form_pdf.date_text(d["issued_on"])),
                                         ("Status", d["status"])], blocks, sig, d["number"],
                                        "DRAFT - NOT POSTED" if d["status"] == "DRAFT" else ""), d["number"])
