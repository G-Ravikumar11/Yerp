"""Draw the programme from the BOQ: the client's sheet as a tree, picked from, and put on the programme as rows.

The sheet numbers its lines I, II (parts), 1, 2 (items), 2.1, 2.1.1 (sub-items), sometimes A, B under an item. A line
with no quantity is a heading; a line with a quantity is work to be done. The tree comes from the numbers, so it is
the client's own; a BOQ saved before numbers were kept falls back to its sections and the priced lines under them.
"""
import re

from fastapi import HTTPException

from app import models
from app.constants.boq import BOQ_PRICED
from app.core.currency import money
from app.core.naming import short_name
from app.services.programme import _date_text, _place, _row_or_404, job_rows
from app.services.projects import boq_order_lines

PART = re.compile(r"^[IVXLC]+$")
NUMBER = re.compile(r"^\d+(\.\d+)*$")


def roman(n):
    out = ""
    for v, s in ((100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out, n = out + s, n - v
    return out


def _boq_lines(db, client_id, job):
    boq = db.query(models.DBBoq).filter(models.DBBoq.client_id == client_id, models.DBBoq.job_id == job.id).first()
    if boq is None:
        return None, None, []
    rev = db.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id == boq.id,
                                                models.DBBoqRevision.rev_no == boq.current_rev).first()
    lines = db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).order_by(
        models.DBBoqLine.display_order, models.DBBoqLine.id).all() if rev else []
    return boq, rev, lines


def boq_tree(lines):
    """The BOQ's lines as a tree of nodes, in the sheet's order. Each node: id (the line's key; "<key>#own" for an
    item's own work when it also has sub-items), key, ref ("I-2.1.1"), item_no, parent (node id), heading, name (short),
    description (in full, with any unnumbered lines of text that follow it), uom, quantity, rate, amount."""
    numbered = any((getattr(l, "item_no", "") or "").strip() for l in lines)
    nodes, kids = [], {}

    def add(l, parent, ref, no=""):
        qty = money(l.quantity) if l.kind in BOQ_PRICED and not l.rate_only else 0.0
        rate = float(l.rate or 0) if l.kind in BOQ_PRICED else 0.0
        amount = money(l.amount) if l.amount else money(qty * rate)      # weighted by quantity x rate when no amount
        n = {"id": l.key, "key": l.key, "ref": ref, "item_no": no, "parent": parent["id"] if parent else None,
             "heading": False, "priced": l.kind in BOQ_PRICED, "name": short_name(l.description) or "Work",
             "description": (l.description or "").strip(), "uom": (l.uom or "") if l.kind in BOQ_PRICED else "",
             "quantity": qty, "rate": rate, "amount": amount, "rate_only": bool(l.rate_only)}
        nodes.append(n)
        kids.setdefault(n["parent"], []).append(n)
        return n

    if not numbered:
        # Headings nest as the sheet nests them: a sub-heading under its main heading, each line under the nearest.
        from app.services.boq_outline import boq_outline
        _heads, path, _ = boq_outline(lines)
        made = {}
        for l in lines:
            if l.kind == "section":
                above = path.get(l.key) or []
                made[l.key] = add(l, made.get(above[-1]) if above else None, "")
            elif l.kind in BOQ_PRICED:
                above = path.get(l.key) or []
                add(l, made.get(above[-1]) if above else None, "")
    else:
        part, stack, lettered, parts_seen = None, [], None, 0
        for l in lines:
            no = (getattr(l, "item_no", "") or "").strip().rstrip(".").strip()
            priced = l.kind in BOQ_PRICED
            if no and PART.match(no) and not priced and no == roman(parts_seen + 1):
                parts_seen += 1
                part = add(l, None, no, no)
                stack, lettered = [], None
            elif no and NUMBER.match(no):
                at = tuple(int(x) for x in no.split("."))
                while stack and not (len(stack[-1][0]) < len(at) and at[:len(stack[-1][0])] == stack[-1][0]):
                    stack.pop()
                parent = stack[-1][1] if stack else part
                node = add(l, parent, "%s-%s" % (part["ref"], no) if part else no, no)
                stack.append((at, node))
                lettered = None
            elif no:                                          # A, B, (a), i: under the numbered line above
                parent = stack[-1][1] if stack else part
                ref = ("%s.%s" % (parent["ref"], no.strip("()"))) if parent else no
                lettered = add(l, parent, ref, no)
            else:
                owner = lettered or (stack[-1][1] if stack else part)
                if priced:                                   # priced but unnumbered: the work of the line above
                    add(l, owner, owner["ref"] if owner else "")
                elif owner is not None and (l.description or "").strip():
                    owner["description"] += "\n" + l.description.strip()

    # A node with lines under it is a heading. If it carries a quantity too, that work becomes its first sub-item.
    out = []

    def walk(n):
        under = kids.get(n["id"], [])
        if under:
            own = dict(n) if n["priced"] and (n["quantity"] or n["rate"]) else None
            n.update(heading=True, uom="", quantity=0.0, rate=0.0, amount=0.0)
            out.append(n)
            if own:
                own.update(id=n["key"] + "#own", parent=n["id"], heading=False)
                out.append(own)
            for c in under:
                walk(c)
        elif n["priced"]:
            out.append(n)
        # a heading with nothing under it is left out: there is nothing in it to draw

    for n in kids.get(None, []):
        walk(n)
    kept = {n["id"] for n in out}
    while True:                                              # headings whose lines were all left out go too
        has_kids = {n["parent"] for n in out}
        drop = [n for n in out if n["heading"] and n["id"] not in has_kids]
        if not drop:
            break
        out = [n for n in out if n not in drop]
    level = {}
    for n in out:
        level[n["id"]] = 0 if n["parent"] is None or n["parent"] not in kept else level.get(n["parent"], -1) + 1
        n["level"] = level[n["id"]]
    return out


def programme_boq(db, client, job):
    """The BOQ as the picker shows it, with what is already on the programme from each line."""
    boq, rev, lines = _boq_lines(db, client.id, job)
    if boq is None:
        return {"boq": None, "items": [], "numbered": False}
    drawn = {}
    for a in db.query(models.DBScheduleActivity).filter(models.DBScheduleActivity.client_id == client.id,
                                                         models.DBScheduleActivity.job_id == job.id,
                                                         models.DBScheduleActivity.boq_key != "").all():
        d = drawn.setdefault(a.boq_key, {"rows": 0, "quantity": 0.0})
        d["rows"] += 1
        d["quantity"] += a.quantity or 0
    items = boq_tree(lines)
    for n in items:
        d = drawn.get(n["key"], {"rows": 0, "quantity": 0.0})
        n["drawn_rows"], n["drawn_quantity"] = d["rows"], money(d["quantity"])
    return {"boq": {"id": boq.id, "number": boq.number or "", "revision": (rev.label if rev else "") or ""},
            "items": items, "numbered": any(n["item_no"] for n in items)}


def draw_from_boq(db, client, job, picks, anchor_id=None, position="end", start=""):
    """Put the picked BOQ lines on the programme, with the headings above them, under the row chosen (or after it, or
    at the end). A heading already on the programme from the same BOQ line is used again rather than made twice. A line
    split across units becomes a row per unit, each with its share of the quantity. Returns the new rows' ids and what
    to tell the user (a split that does not add up to the BOQ quantity is said, not refused)."""
    boq, rev, lines = _boq_lines(db, client.id, job)
    if boq is None:
        raise HTTPException(409, "This project has no BOQ yet. Make one under Projects, BOQ, then draw the programme from it.")
    nodes = {n["id"]: n for n in boq_tree(lines)}
    picks = [p for p in (picks or []) if p.get("id") in nodes]
    if not picks:
        raise HTTPException(400, "Tick the BOQ lines to put on the programme.")
    names = {p["id"]: (p.get("name") or "").strip()[:200] for p in picks}
    chosen = {p["id"] for p in picks if not nodes[p["id"]]["heading"]}
    if not chosen:
        raise HTTPException(400, "Tick at least one line with a quantity: a heading on its own has nothing to schedule.")
    need = set()
    for nid in chosen:
        n = nodes[nid]
        while n is not None and n["id"] not in need:
            need.add(n["id"])
            n = nodes.get(n["parent"]) if n["parent"] else None

    acts = job_rows(db, client.id, job)
    anchor = _row_or_404(acts, anchor_id) if anchor_id else None
    if position == "child" and anchor is None:
        raise HTTPException(400, "Choose the row to put them under.")
    top_parent = anchor.id if position == "child" else (anchor.parent_id if anchor else None)
    top_before = None
    if position == "after" and anchor is not None:
        sibs = sorted([a for a in acts if a.parent_id == anchor.parent_id], key=lambda a: (a.display_order or 0, a.id))
        at = next(i for i, a in enumerate(sibs) if a.id == anchor.id)
        top_before = sibs[at + 1].id if at + 1 < len(sibs) else None
    has_kids = {a.parent_id for a in acts if a.parent_id}
    existing = {a.boq_key: a for a in acts if a.boq_key and a.id in has_kids}       # headings drawn before
    begin = _date_text(start, "Start") if start else ""
    # A client work order made from this BOQ measures the work: a line drawn whole takes its progress from that book.
    wo_line = boq_order_lines(db, client.id, boq.id)
    used_lines = {a.work_order_line_id for a in acts if a.work_order_line_id}

    made, warnings, row_of = [], [], {}
    line_of = {l.key: l for l in lines}

    def new_row(n, parent_id, before, name, qty=None, label=""):
        quantity = n["quantity"] if qty is None else money(qty)
        a = models.DBScheduleActivity(
            client_id=client.id, job_id=job.id, name=(name + (" - %s" % label if label else ""))[:200],
            description=n["description"], boq_ref=n["ref"][:40], boq_key=n["key"], uom=n["uom"][:20],
            quantity=quantity, rate=n["rate"], amount=money(quantity * n["rate"]) if qty is not None else n["amount"],
            weight=money(quantity * n["rate"]) if qty is not None else n["amount"])
        if not n["heading"] and begin:
            a.planned_start = begin
        if not n["heading"] and not label:
            code = (getattr(line_of.get(n["key"]), "item_code", "") or "").upper()
            wl = wo_line.get(code) if code else None
            if wl and wl not in used_lines:
                a.work_order_line_id = wl
                used_lines.add(wl)
        db.add(a)
        db.flush()
        acts.append(a)
        _place(acts, a, parent_id, before)
        made.append(a.id)
        return a

    for nid in [n for n in nodes if n in need]:                 # the sheet's order: parents before their lines
        n = nodes[nid]
        parent = row_of.get(n["parent"]) if n["parent"] else None
        if n["heading"] and n["key"] in existing and not n["id"].endswith("#own"):
            row_of[nid] = existing[n["key"]]
            continue
        parent_id = parent.id if parent is not None else top_parent
        before = None if parent is not None else top_before
        name = names.get(nid) or n["name"]
        if n["heading"]:
            row_of[nid] = new_row(n, parent_id, before, name)
            continue
        pick = next(p for p in picks if p["id"] == nid)
        splits = [s for s in (pick.get("splits") or []) if (s.get("label") or "").strip()]
        if not splits:
            row_of[nid] = new_row(n, parent_id, before, name)
            continue
        total = 0.0
        for s in splits:
            q = float(s.get("quantity") or 0)
            if q < 0:
                raise HTTPException(400, "%s: a unit's quantity cannot be negative." % name)
            total += q
            new_row(n, parent_id, before, name, q, s["label"].strip()[:60])
        if n["quantity"] and abs(total - n["quantity"]) > 1e-6:
            warnings.append("%s %s: the units come to %s %s, the BOQ has %s." % (
                n["ref"], name, _num(total), n["uom"], _num(n["quantity"])))
    leaves = sum(1 for nid in need if not nodes[nid]["heading"])
    message = "%d BOQ line%s put on the programme (%d row%s)." % (leaves, "" if leaves == 1 else "s", len(made),
                                                                   "" if len(made) == 1 else "s")
    if warnings:
        message += " Check: " + " ".join(warnings)
    return made, message, warnings


def _num(x):
    return ("%.3f" % x).rstrip("0").rstrip(".")
