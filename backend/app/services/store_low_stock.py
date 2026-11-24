"""Store module - the Low Stock list and raising an indent or enquiry for many low items at once.

The list is what is low NOW: every item whose available stock in a store (stock_ledger.available_map - on hand less what is held, rejected,
expired or reserved) is at or below its reorder level, with the store's alert beside it (when it was raised, when it was last checked, and the
indent or enquiry raised for it). Resolved alerts, and every earlier episode an alert has had, are the history view.

Raising for many at once reuses the existing documents and their approvals: an INDENT is the store's own indent (one per store, submitted to
the project manager for approval, exactly as one typed on the Indent screen), an ENQUIRY is a purchase enquiry (one for all the items). Each
line is checked again against the stock as it is now - the screen's figures are never taken on trust - and a line that is no longer low,
already has a live indent or enquiry, or asks for more than the store's maximum allows is refused on its own, with the reason; the others go
ahead together. Raising never resolves an alert and never moves stock: the alert resolves when the stock is back above the level.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from fastapi import HTTPException

from app import models
from app.core.audit import log_audit
from app.models.store_core import DBStore, DBStoreItemSettings, DBStoreStockLedger
from app.models.store_extras import DBStoreReorderAlert
from app.models.store_outward import INDENT, DBStoreIndent
from app.services import store_levels
from app.services.stock_ledger import _alert_row, _history, assert_store_access, available_map, check_reorder, reorder_target

ZERO = Decimal("0")
Q3 = Decimal("0.001")
MAX_QTY = Decimal("999999")
MAX_LINES = 200
ACTIONS = ("INDENT", "ENQUIRY")
DEAD = {"INDENT": ("CANCELLED",), "ENQUIRY": ("CANCELLED",)}
STATUS_OF = {"INDENT": "INDENT_RAISED", "ENQUIRY": "ENQUIRY_RAISED"}
# Where an open alert's replenishment has got to. Worked out from the records each time, never stored, and never a reason to
# resolve: only available stock back above the reorder level does that.
STAGE_ACTIVE, STAGE_INDENT, STAGE_ENQUIRY, STAGE_PO = "ALERT ACTIVE", "INDENT RAISED", "ENQUIRY RAISED", "PO CREATED"
STAGE_RECEIVED, STAGE_QC, STAGE_UPDATED, STAGE_LOW = "GOODS RECEIVED", "QUALITY ACCEPTED", "STOCK UPDATED", "LOW STOCK"


def s3(x):
    return format(Decimal(str(x)).quantize(Q3), "f") if x is not None else None


def _job_label(job):
    return ("%s - %s" % (job.number, job.name)).strip(" -") if job else ""


def _docs(db, alerts):
    """{alert id: (live?, document status)} for the indents and enquiries alerts were raised on."""
    ind = {a.action_doc_id for a in alerts if a.action == "INDENT" and a.action_doc_id}
    rfq = {a.action_doc_id for a in alerts if a.action == "ENQUIRY" and a.action_doc_id}
    ind_status = dict(db.query(DBStoreIndent.id, DBStoreIndent.status).filter(DBStoreIndent.id.in_(ind or {0})).all())
    rfq_status = dict(db.query(models.DBRfq.id, models.DBRfq.status).filter(models.DBRfq.id.in_(rfq or {0})).all())
    out = {}
    for a in alerts:
        if not a.action:
            continue
        st = (ind_status if a.action == "INDENT" else rfq_status).get(a.action_doc_id)
        out[a.id] = (st is not None and st.upper() not in DEAD[a.action], st or "deleted")
    return out


def _stages_data(db, keys, alerts):
    """What the stage of each (store, item) is read from: receipts in hand (not yet posted, and whether they passed QC) and
    stock posted in since the alert. (Items a live order still has to deliver come from the order book low_rows reads once.)"""
    from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
    stores, items = {k[0] for k in keys}, {k[1] for k in keys}
    pending = {}
    for g, l in (db.query(DBStoreGrn, DBStoreGrnLine).join(DBStoreGrnLine, DBStoreGrnLine.grn_id == DBStoreGrn.id)
                 .filter(DBStoreGrn.store_id.in_(stores or {0}), DBStoreGrnLine.item_id.in_(items or {0}),
                         DBStoreGrn.status.in_(("DRAFT", "SUBMITTED", "APPROVED"))).all()):
        k = (g.store_id, l.item_id)
        pending[k] = pending.get(k, False) or l.qc_status == "PASSED"
    since = {}
    first = min((a.alerted_at for a in alerts.values() if a.cleared_at is None and a.alerted_at), default=None)
    if first is not None:
        for sid, iid, at in (db.query(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id, DBStoreStockLedger.created_at)
                             .filter(DBStoreStockLedger.store_id.in_(stores or {0}), DBStoreStockLedger.item_id.in_(items or {0}),
                                     DBStoreStockLedger.qty_in > 0, DBStoreStockLedger.reversal_of_id.is_(None),
                                     DBStoreStockLedger.ref_doc_type.in_(("GRN", "CLIENT_SUPPLY", "TRANSFER")),
                                     DBStoreStockLedger.created_at >= first).all()):
            since[(sid, iid)] = max(since.get((sid, iid)) or at, at)
    return pending, since


def _stage(key, a, open_alert, live, pending, since, ordered):
    if not open_alert:
        return STAGE_LOW
    if key in pending:
        return STAGE_QC if pending[key] else STAGE_RECEIVED
    if key in since and a.alerted_at and since[key] >= a.alerted_at:
        return STAGE_UPDATED
    if key[1] in ordered:
        return STAGE_PO
    if a.action and live:
        return STAGE_INDENT if a.action == "INDENT" else STAGE_ENQUIRY
    return STAGE_ACTIVE


def _coming(db, client_id):
    from app.services.buying_links import on_order
    return dict(on_order(db, client_id)[1])


def low_rows(db, client_id, store_ids, only=None):
    """Every item low now in these stores (None = every store of the company), worst first. `only` narrows to a set of (store, item)."""
    q = db.query(DBStore).filter(DBStore.client_id == client_id, DBStore.is_active.is_(True))
    if store_ids is not None:
        q = q.filter(DBStore.id.in_(list(store_ids) or [0]))
    stores = {s.id: s for s in q.all()}
    if not stores:
        return []
    avail = available_map(db, list(stores))
    if only is not None:
        avail = {k: v for k, v in avail.items() if k in only}
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_({i for _s, i in avail} or {0})).all()}
    over = store_levels.overrides(db, list(stores))
    low = []
    for (sid, iid), f in avail.items():
        level, low_qty, high = store_levels.effective(sets.get(iid), over.get((sid, iid)))
        if level > 0 and f["available"] <= level:
            target, basis = reorder_target(level, high)
            low.append((sid, iid, f, level, low_qty, high, target, basis))
    if not low:
        return []
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_({x[1] for x in low})).all()}
    alerts = {(a.store_id, a.item_id): a for a in db.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.store_id.in_(list(stores)),
                                                                                      DBStoreReorderAlert.item_id.in_({x[1] for x in low})).all()}
    docs = _docs(db, [a for a in alerts.values() if a.cleared_at is None])
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.id.in_({s.project_id for s in stores.values() if s.project_id} or {0})).all()}
    # What is already coming (open enquiries, orders not yet received) is the company's: it is set against the first store's need, then the next.
    from app.services.buying_links import order_book
    _by_indent, by_item, ordered = order_book(db, client_id)
    coming = dict(by_item)
    pending, since = _stages_data(db, {(x[0], x[1]) for x in low}, alerts)
    rows = []
    for sid, iid, f, level, low_qty, high, target, basis in sorted(low, key=lambda x: (x[2]["available"] / x[3], stores[x[0]].code, items[x[1]].item_name or "")):
        store, item, s = stores[sid], items[iid], sets.get(iid)
        suggested = max(ZERO, target - f["available"])
        covered = min(suggested, coming.get(iid, ZERO))
        coming[iid] = coming.get(iid, ZERO) - covered
        a = alerts.get((sid, iid))
        open_alert = a is not None and a.cleared_at is None
        live, doc_status = docs.get(a.id, (False, "")) if open_alert else (False, "")
        status = STATUS_OF[a.action] if open_alert and a.action and live else "LOW_STOCK"
        rows.append({"key": "%d-%d" % (sid, iid), "alert_id": a.id if open_alert else None, "store_id": sid, "store_code": store.code, "store_name": store.name,
                     "project_id": store.project_id, "project": _job_label(jobs.get(store.project_id)), "item_id": iid, "item_code": item.item_code,
                     "item_name": item.item_name, "category": s.category if s else None, "base_uom": ((s.base_uom if s else item.units_of_measure) or ""),
                     "on_hand": s3(f["on_hand"]), "unusable": s3(f["unusable"]), "reserved": s3(f["reserved"]), "available": s3(f["available"]),
                     "reorder_level": s3(level), "min_qty": s3(low_qty), "max_qty": s3(high), "target_level": s3(target), "suggest_basis": basis,
                     "suggested_qty": s3(suggested), "on_order": s3(covered), "to_order": s3(suggested - covered),
                     "alerted_at": a.alerted_at.isoformat(timespec="seconds") if open_alert and a.alerted_at else "",
                     "last_checked_at": a.last_checked_at.isoformat(timespec="seconds") if open_alert and a.last_checked_at else "",
                     "times_raised": (a.times_raised or 1) if a is not None else 0, "status": status,
                     "shortage": s3(max(ZERO, level - f["available"])),
                     "stage": _stage((sid, iid), a, open_alert, live, pending, since, ordered),
                     "action": a.action if open_alert and a.action else "", "action_ref": a.action_ref if open_alert and a.action else "",
                     "action_doc_id": a.action_doc_id if open_alert and a.action else None, "action_doc_status": doc_status, "action_live": live,
                     "action_qty": s3(a.action_qty) if open_alert and a.action_qty is not None else None,
                     "action_by": a.action_by if open_alert else "", "action_at": a.action_at.isoformat(timespec="seconds") if open_alert and a.action_at else ""})
    return rows


def history_rows(db, client_id, store_ids, limit=300):
    """Resolved alerts and every earlier episode of every alert, newest first: the alert history, nothing ever removed."""
    q = db.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.client_id == client_id)
    if store_ids is not None:
        q = q.filter(DBStoreReorderAlert.store_id.in_(list(store_ids) or [0]))
    alerts = q.all()
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.id.in_({a.store_id for a in alerts} or {0})).all()}
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_({a.item_id for a in alerts} or {0})).all()}
    out = []
    for a in alerts:
        base = {"alert_id": a.id, "store_id": a.store_id, "store_code": stores[a.store_id].code if a.store_id in stores else "",
                "item_id": a.item_id, "item_code": items[a.item_id].item_code if a.item_id in items else "", "item_name": items[a.item_id].item_name if a.item_id in items else ""}
        for ep in _history(a):
            out.append({**base, "status": "RESOLVED" if ep.get("resolved_at") else "CLOSED", **{k: ep.get(k) for k in (
                "alerted_at", "resolved_at", "available", "reorder_level", "suggested_qty", "resolved_qty", "action", "action_ref", "action_qty", "action_by", "action_at")}})
        if a.cleared_at is not None:
            out.append({**base, "status": "RESOLVED", "alerted_at": a.alerted_at.isoformat(timespec="seconds") if a.alerted_at else "",
                        "resolved_at": a.cleared_at.isoformat(timespec="seconds"), "available": s3(a.available), "reorder_level": s3(a.reorder_level),
                        "suggested_qty": s3(a.suggested_qty), "resolved_qty": s3(a.resolved_qty), "action": a.action or "", "action_ref": a.action_ref or "",
                        "action_qty": s3(a.action_qty), "action_by": a.action_by or "", "action_at": a.action_at.isoformat(timespec="seconds") if a.action_at else ""})
    out.sort(key=lambda r: r.get("resolved_at") or "", reverse=True)
    return out[:limit]


# --- raising ---------------------------------------------------------------------------------------------------------------

def _qty(raw):
    try:
        d = Decimal(str(raw if raw is not None else "").strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None, "The requested quantity is not a number."
    if not d.is_finite() or d <= 0:
        return None, "The requested quantity must be more than zero."
    if d > MAX_QTY:
        return None, "The requested quantity is more than 999999."
    d = d.quantize(Q3)
    return (d, "") if d > 0 else (None, "The requested quantity is too small.")


def raise_for(db, actor, action, lines, request_key="", project_id=0, required_by="", title="", request=None):
    """Raise one indent per store (INDENT) or one enquiry (ENQUIRY) for the low items chosen. Each line is
    {store_id, item_id, qty, alert_id?}. Returns {created: [...], results: [...], ok: bool, message}. The caller commits."""
    from app.services import store_outward as out_svc
    if action not in ACTIONS:
        raise HTTPException(400, "Choose to raise an indent or an enquiry.")
    if not lines:
        raise HTTPException(400, "Choose at least one material.")
    if len(lines) > MAX_LINES:
        raise HTTPException(400, "Raise for at most %d materials at once." % MAX_LINES)
    key = (request_key or "").strip()[:64]
    now = datetime.now()
    results, seen, good = [], set(), []
    coming = _coming(db, actor.client.id)

    def fail(l, why, **extra):
        results.append({"store_id": l["store_id"], "item_id": l["item_id"], "ok": False, "message": why, **extra})

    for l in lines:
        pair = (l["store_id"], l["item_id"])
        if pair in seen:
            fail(l, "This material and store are chosen twice; it is raised once.")
            continue
        seen.add(pair)
        store = db.get(DBStore, l["store_id"])
        item = db.get(models.DBItem, l["item_id"])
        if store is None or store.client_id != actor.client.id or item is None or item.client_id != actor.client.id:
            fail(l, "That store or material is not on file.")
            continue
        try:
            assert_store_access(actor.user, store.id)
        except HTTPException as exc:
            fail(l, exc.detail)
            continue
        if not available_map(db, [store.id], [item.id]):
            fail(l, "Store %s holds no record of %s, so it is not on the Low Stock list." % (store.code, item.item_name))
            continue
        # Checked again now, against the stock as it is: the alert is raised, brought up to date or resolved to match.
        check_reorder(db, actor.client.id, store, item.id)
        db.flush()
        alert = _alert_row(db, store.id, item.id, lock=True)
        figs = available_map(db, [store.id], [item.id]).get(pair) or {"available": ZERO}
        level, _low, high = store_levels.levels_for(db, store.id, item.id)
        if alert is None or alert.cleared_at is not None:
            fail(l, "No longer low: %s available against a reorder level of %s. Nothing was raised." % (s3(figs["available"]), s3(level)), status="RESOLVED",
                 available=s3(figs["available"]))
            continue
        if l.get("alert_id") and l["alert_id"] != alert.id:
            fail(l, "This alert has changed since the list was loaded. Reload the list and choose again.")
            continue
        if alert.action:
            if key and alert.action_key == key:
                results.append({"store_id": store.id, "item_id": item.id, "ok": True, "message": "Already raised on %s by this request." % alert.action_ref,
                                "ref": alert.action_ref, "doc_id": alert.action_doc_id, "repeat": True})
                continue
            live = _docs(db, [alert]).get(alert.id, (False, ""))[0]
            if live:
                fail(l, "Already raised on %s (%s, %s); it is still open." % (alert.action_ref, alert.action.lower(), alert.action_by or "someone"),
                     ref=alert.action_ref)
                continue
        qty, why = _qty(l.get("qty"))
        if qty is None:
            fail(l, why)
            continue
        target, _basis = reorder_target(level, high)
        need = max(ZERO, target - figs["available"]) if target is not None else ZERO
        covered = min(need, coming.get(item.id, ZERO))
        if action == "ENQUIRY" and need > 0 and covered >= need:
            fail(l, "Already being bought: %s is on open enquiries or orders, which covers the %s needed." % (s3(coming.get(item.id, ZERO)), s3(need)))
            continue
        # The store's maximum is not to be passed: what is available, plus what is coming, plus this, stays within it.
        if high > 0 and figs["available"] + covered + qty > high:
            room = max(ZERO, high - figs["available"] - covered)
            fail(l, "%s would take the store past its maximum of %s: at most %s can be asked for." % (s3(qty), s3(high), s3(room)))
            continue
        coming[item.id] = coming.get(item.id, ZERO) - covered
        good.append({"store": store, "item": item, "alert": alert, "qty": qty, "uom": out_svc.base_uom_of(db, item)})

    created = []
    if good and action == "INDENT":
        by_store = {}
        for g in good:
            by_store.setdefault(g["store"].id, []).append(g)
        for store_id, group in by_store.items():
            store = group[0]["store"]
            job_id = project_id or store.project_id
            job = db.query(models.DBJob).filter(models.DBJob.id == job_id, models.DBJob.client_id == actor.client.id).first() if job_id else None
            if job is None:
                for g in group:
                    fail({"store_id": store.id, "item_id": g["item"].id}, "Store %s belongs to no project: choose the project the indent is for." % store.code)
                continue
            try:
                with db.begin_nested():
                    needed = datetime.strptime(required_by[:10], "%Y-%m-%d").date() if required_by else None
                    rows = out_svc.build_indent_lines(db, actor.client.id, [SimpleNamespace(item_id=g["item"].id, qty=str(g["qty"]), uom=g["uom"],
                                                                                            purpose="Low stock: reorder level %s" % s3(g["alert"].reorder_level)) for g in group])
                    indent = DBStoreIndent(client_id=actor.client.id, store_id=store.id, number=out_svc.numbered(db, INDENT, store.id, date.today()), status="DRAFT",
                                           indent_date=date.today(), required_by=needed, project_id=job.id, activity="Replenish low stock",
                                           remarks=("Raised from the Low Stock list for %d material%s at or below the reorder level." % (len(group), "" if len(group) == 1 else "s")),
                                           requested_by_id=actor.user_id, requested_by_name=actor.name)
                    db.add(indent)
                    db.flush()
                    out_svc.write_indent_lines(db, indent, rows)
                    out_svc.log(db, actor, INDENT, indent.id, "create", "", "DRAFT", "From the Low Stock list")
                    out_svc.indent_submit(db, actor, indent)          # waits for the project manager's approval, as any indent does
            except (HTTPException, ValueError) as exc:
                for g in group:
                    fail({"store_id": store.id, "item_id": g["item"].id}, getattr(exc, "detail", None) or "The required-by date is not a date (use YYYY-MM-DD).")
                continue
            created.append({"type": "INDENT", "id": indent.id, "number": indent.number, "store_code": store.code, "lines": len(group), "status": indent.status})
            for g in group:
                _link(g, "INDENT", indent.id, indent.number, actor, key, now)
                results.append({"store_id": store.id, "item_id": g["item"].id, "ok": True, "message": "On %s, waiting for approval." % indent.number, "ref": indent.number,
                                "doc_id": indent.id, "qty": s3(g["qty"])})
    elif good and action == "ENQUIRY":
        from app.services.procurement import _make_rfq
        merged = {}
        for g in good:
            m = merged.setdefault(g["item"].id, {"item_code": g["item"].item_code, "description": g["item"].item_name, "uom": g["uom"], "qty": 0.0, "stores": []})
            m["qty"] += float(g["qty"])
            m["stores"].append(g["store"].code)
        projects = {g["store"].project_id for g in good}
        job_id = project_id or (projects.pop() if len(projects) == 1 else None)
        stores = sorted({g["store"].code for g in good})
        try:
            with db.begin_nested():
                rfq = _make_rfq(db, actor.client, actor.name, (title or "Low stock - %s" % ", ".join(stores))[:120], job_id or None, required_by or "",
                                "Raised from the Low Stock list for materials at or below the reorder level in %s." % ", ".join(stores),
                                [{k: v for k, v in m.items() if k != "stores"} for m in merged.values()])
                rfq.created_by_id = actor.user_id
        except HTTPException as exc:
            for g in good:
                fail({"store_id": g["store"].id, "item_id": g["item"].id}, exc.detail)
            good = []
        else:
            created.append({"type": "ENQUIRY", "id": rfq.id, "number": rfq.number, "lines": len(merged), "status": rfq.status})
            for g in good:
                _link(g, "ENQUIRY", rfq.id, rfq.number, actor, key, now)
                results.append({"store_id": g["store"].id, "item_id": g["item"].id, "ok": True, "message": "On enquiry %s." % rfq.number, "ref": rfq.number,
                                "doc_id": rfq.id, "qty": s3(g["qty"])})
    db.flush()
    done = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    if created:
        log_audit(db, actor.client.id, "store_low_stock_raised", "store_doc", created[0]["id"], ", ".join(c["number"] for c in created),
                  "%s from the Low Stock list: %d material%s raised, %d refused" % (action.lower(), len(done), "" if len(done) == 1 else "s", len(failed)),
                  request=request, user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
    refs = ", ".join(c["number"] for c in created)
    if created and not failed:
        message = "Raised %s for %d material%s." % (refs, len(done), "" if len(done) == 1 else "s")
    elif created:
        message = "Raised %s for %d material%s; %d could not be raised - see each line." % (refs, len(done), "" if len(done) == 1 else "s", len(failed))
    elif done:
        message = "Already raised by this request: nothing new was created."
    else:
        message = "Nothing was raised: none of the chosen materials could be - see each line."
    return {"ok": bool(done) and not failed, "action": action, "created": created, "results": results, "raised": len(done), "failed": len(failed), "message": message}


def _link(g, action, doc_id, ref, actor, key, now):
    a = g["alert"]
    a.action, a.action_doc_id, a.action_ref, a.action_qty, a.action_by, a.action_at, a.action_key = action, doc_id, ref, g["qty"], actor.name, now, key
