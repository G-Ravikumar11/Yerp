"""Credit notes against certified bills, both ways.

A certified bill is not cancelled and not rewritten: its GST and TDS are in the return of the month it was
certified, and that month may already be filed. What was over-billed is taken back by a credit note issued today,
against that bill, line by line. It reverses the GST, TDS and retention the bill charged on those quantities, in
the period it is issued, and the quantities become claimable again if the work is measured again.

Side "client" is against our RA bill (we credit the client); side "contractor" is against a contractor's bill (the contractor
credits us). The arithmetic is the bill's own: the same rates, the same CGST/SGST-or-IGST decision, the same
rounding (paise on our bills, whole rupees on the contractors').
"""
from datetime import date

from fastapi import HTTPException

from app import models
from app.core.currency import inr, money, rupees

CLIENT, CONTRACTOR = "client", "contractor"


def _round(side):
    return money if side == CLIENT else rupees


def credit_notes_query(db, client_id, side=None):
    q = db.query(models.DBCreditNote).filter(
        models.DBCreditNote.client_id == client_id, models.DBCreditNote.status == "ISSUED")
    if side:
        q = q.filter(models.DBCreditNote.side == side)
    return q


def credited_qty_by_item(db, side, order_id):
    """{item id: quantity taken back by credit notes} on one order - the client's work order, or a contractor's
    subcontract order. Subtracted from what has been billed, so work taken back can be billed again."""
    if not order_id:
        return {}
    col = models.DBCreditNote.work_order_id if side == CLIENT else models.DBCreditNote.sub_order_id
    out = {}
    rows = db.query(models.DBCreditNoteLine.item_id, models.DBCreditNoteLine.qty).join(
        models.DBCreditNote, models.DBCreditNote.id == models.DBCreditNoteLine.credit_note_id).filter(
            col == order_id, models.DBCreditNote.side == side, models.DBCreditNote.status == "ISSUED").all()
    for item_id, qty in rows:
        out[item_id] = out.get(item_id, 0.0) + (qty or 0.0)
    return out


def credited_qty_by_bill_line(db, side, bill_id):
    """{bill line id: quantity already taken back} on one bill."""
    col = models.DBCreditNote.ra_bill_id if side == CLIENT else models.DBCreditNote.sub_bill_id
    out = {}
    rows = db.query(models.DBCreditNoteLine.bill_line_id, models.DBCreditNoteLine.qty).join(
        models.DBCreditNote, models.DBCreditNote.id == models.DBCreditNoteLine.credit_note_id).filter(
            col == bill_id, models.DBCreditNote.side == side, models.DBCreditNote.status == "ISSUED").all()
    for line_id, qty in rows:
        out[line_id] = out.get(line_id, 0.0) + (qty or 0.0)
    return out


def credited_taxable_by_order(db, side, order_id):
    """The value of work taken back on one order, for the 'billed before this bill' figure."""
    col = models.DBCreditNote.work_order_id if side == CLIENT else models.DBCreditNote.sub_order_id
    return money(sum(n.taxable or 0 for n in db.query(models.DBCreditNote).filter(
        col == order_id, models.DBCreditNote.side == side, models.DBCreditNote.status == "ISSUED").all()))


def credit_totals_by_bill(db, client_id, side):
    """{bill id: {"taxable", "gst", "tds", "retention", "net"}} for every bill that has a credit note."""
    key = "ra_bill_id" if side == CLIENT else "sub_bill_id"
    out = {}
    for n in credit_notes_query(db, client_id, side).all():
        t = out.setdefault(getattr(n, key), {"taxable": 0.0, "gst": 0.0, "tds": 0.0, "retention": 0.0, "net": 0.0})
        t["taxable"] = money(t["taxable"] + (n.taxable or 0))
        t["gst"] = money(t["gst"] + (n.gst_amount or 0))
        t["tds"] = money(t["tds"] + (n.tds_amount or 0))
        t["retention"] = money(t["retention"] + (n.retention_amount or 0))
        t["net"] = money(t["net"] + (n.net_amount or 0))
    return out


def credits_by_job(db, client_id, side):
    """{job id: {"taxable", "retention", "net"}} - for the project's billed, held and owed figures."""
    out = {}
    for n in credit_notes_query(db, client_id, side).all():
        t = out.setdefault(n.job_id, {"taxable": 0.0, "retention": 0.0, "net": 0.0})
        t["taxable"] = money(t["taxable"] + (n.taxable or 0))
        t["retention"] = money(t["retention"] + (n.retention_amount or 0))
        t["net"] = money(t["net"] + (n.net_amount or 0))
    return out


def credited_retention_by_order(db, client_id, side):
    """{order id: retention no longer held because of credit notes}."""
    key = "work_order_id" if side == CLIENT else "sub_order_id"
    out = {}
    for n in credit_notes_query(db, client_id, side).all():
        k = getattr(n, key)
        out[k] = money(out.get(k, 0.0) + (n.retention_amount or 0))
    return out


def preload_credits(db, client_id):
    """Every credit note of the company, grouped the four ways the money and profit figures need - in one query,
    so a list of projects asks the database the same number of questions however many it shows."""
    out = {"client_job": {}, "sub_job": {}, "client_bill": {}, "sub_order": {}}
    for n in credit_notes_query(db, client_id).all():
        taxable, ret, net = money(n.taxable), money(n.retention_amount), money(n.net_amount)
        jobs = out["client_job"] if n.side == CLIENT else out["sub_job"]
        j = jobs.setdefault(n.job_id, {"taxable": 0.0, "retention": 0.0, "net": 0.0})
        j["taxable"], j["retention"], j["net"] = money(j["taxable"] + taxable), money(j["retention"] + ret), money(j["net"] + net)
        if n.side == CLIENT:
            b = out["client_bill"].setdefault(n.ra_bill_id, {"net": 0.0})
            b["net"] = money(b["net"] + net)
        else:
            out["sub_order"][n.sub_order_id] = money(out["sub_order"].get(n.sub_order_id, 0.0) + taxable)
    return out


def bill_credited_net(db, side, bill_id):
    """What the credit notes against one bill have taken off its net payable."""
    col = models.DBCreditNote.ra_bill_id if side == CLIENT else models.DBCreditNote.sub_bill_id
    return money(sum(n.net_amount or 0 for n in db.query(models.DBCreditNote).filter(
        col == bill_id, models.DBCreditNote.side == side, models.DBCreditNote.status == "ISSUED").all()))


def credit_note_dict(db, n, detail=False):
    row = {
        "id": n.id, "number": n.number or "", "side": n.side, "sequence": n.sequence or 1,
        "bill_id": n.ra_bill_id if n.side == CLIENT else n.sub_bill_id,
        "note_date": n.note_date or "", "reason": n.reason or "", "status": n.status or "ISSUED",
        "taxable": money(n.taxable), "gst_percent": n.gst_percent or 0, "gst_amount": money(n.gst_amount),
        "cgst_amount": money(n.cgst_amount), "sgst_amount": money(n.sgst_amount),
        "igst_amount": money(n.igst_amount), "place_of_supply": n.place_of_supply or "",
        "retention_amount": money(n.retention_amount), "tds_percent": n.tds_percent or 0,
        "tds_amount": money(n.tds_amount), "cess_amount": money(n.cess_amount),
        "net_amount": money(n.net_amount), "created_by_name": n.created_by_name or "",
        "created_at": n.created_at or "",
    }
    if detail:
        row["lines"] = [{
            "id": l.id, "bill_line_id": l.bill_line_id, "item_id": l.item_id,
            "description": (l.description or "").split("\n")[0], "uom": l.uom or "",
            "qty": money(l.qty), "rate": l.rate or 0, "amount": money(l.amount),
        } for l in db.query(models.DBCreditNoteLine).filter(
            models.DBCreditNoteLine.credit_note_id == n.id).order_by(models.DBCreditNoteLine.id).all()]
    return row


def bill_credit_summary(db, side, bill):
    """What the credit notes against one bill have taken back, and what is still open to take back, by line."""
    done = credited_qty_by_bill_line(db, side, bill.id)
    notes = db.query(models.DBCreditNote).filter(
        models.DBCreditNote.side == side, models.DBCreditNote.status == "ISSUED",
        (models.DBCreditNote.ra_bill_id if side == CLIENT else models.DBCreditNote.sub_bill_id) == bill.id
    ).order_by(models.DBCreditNote.id).all()
    return {
        "credited": money(sum(n.taxable or 0 for n in notes)),
        "credited_net": money(sum(n.net_amount or 0 for n in notes)),
        "credit_notes": [credit_note_dict(db, n) for n in notes],
        "credited_qty": done,
    }


def _bill_lines(db, side, bill):
    if side == CLIENT:
        return db.query(models.DBRABillLine).filter(models.DBRABillLine.ra_bill_id == bill.id).all()
    return db.query(models.DBSubBillLine).filter(models.DBSubBillLine.sub_bill_id == bill.id).all()


def raise_credit_note(db, side, client_id, bill, lines, reason, note_date="", actor_name=""):
    """Issue a credit note against a certified or paid bill. `lines` is [{"bill_line_id", "qty"}].

    Refuses more than the bill billed on a line (less what earlier credit notes took back), a bill that is not
    certified (a draft or submitted bill is sent back and redrawn from the book instead), and no reason.
    """
    status = bill.status or "DRAFT"
    if status not in ("CERTIFIED", "PAID"):
        raise HTTPException(
            409, "%s is %s. A credit note corrects a certified bill; one that has not been certified is sent "
                 "back and redrawn from the measurement book." % (bill.number, status.lower()))
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "Say why the credit note is being issued.")
    asked = {}
    for ln in lines or []:
        try:
            line_id, qty = int(ln.get("bill_line_id")), money(ln.get("qty") or 0)
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(400, "Each line needs a bill line and a quantity.")
        if qty < 0:
            raise HTTPException(400, "A quantity taken back cannot be negative.")
        if qty > 0:
            asked[line_id] = money(asked.get(line_id, 0.0) + qty)
    if not asked:
        raise HTTPException(400, "Enter the quantity to take back on at least one line.")

    bill_lines = {l.id: l for l in _bill_lines(db, side, bill)}
    done = credited_qty_by_bill_line(db, side, bill.id)
    cut = _round(side)
    rows, taxable = [], 0.0
    for line_id, qty in asked.items():
        l = bill_lines.get(line_id)
        if not l:
            raise HTTPException(400, "That line is not on %s." % bill.number)
        room = money((l.this_bill_qty or 0) - done.get(line_id, 0.0))
        if qty > room + 0.0001:
            raise HTTPException(
                400, "Only %s of '%s' can still be taken back off %s; %s is more than that." % (
                    room, (l.description or "").split("\n")[0][:40], bill.number, qty))
        rate = l.rate or 0.0
        amount = money(qty * rate)
        taxable = money(taxable + amount)
        rows.append((l, qty, rate, amount))

    # The bill's own terms, applied to the work taken back.
    if side == CLIENT:
        gst_rate, tds_rate, ret_rate, cess_rate = bill.tax_percent or 0, bill.tds_percent or 0, bill.retention_percent or 0, 0.0
        item_of = lambda l: l.line_id
    else:
        gst_rate, tds_rate, ret_rate = bill.gst_percent or 0, bill.tds_percent or 0, bill.retention_percent or 0
        cess_rate = bill.labour_cess_percent or 0.0
        item_of = lambda l: l.item_id
    intra = bool(bill.cgst_amount or bill.sgst_amount)
    gst_total = cut(taxable * gst_rate / 100.0)
    if intra:
        cgst = cut(gst_total / 2.0)
        sgst, igst = cut(gst_total - cgst), 0.0
    else:
        cgst = sgst = 0.0
        igst = gst_total
    retention = cut(taxable * ret_rate / 100.0)
    tds = cut(taxable * tds_rate / 100.0)
    cess = cut(taxable * cess_rate / 100.0)
    net = cut(taxable + gst_total - retention - tds - cess)

    seq = db.query(models.DBCreditNote).filter(
        models.DBCreditNote.side == side,
        (models.DBCreditNote.ra_bill_id if side == CLIENT else models.DBCreditNote.sub_bill_id) == bill.id).count() + 1
    note = models.DBCreditNote(
        client_id=client_id, side=side,
        ra_bill_id=bill.id if side == CLIENT else None,
        sub_bill_id=bill.id if side == CONTRACTOR else None,
        work_order_id=bill.work_order_id if side == CLIENT else None,
        sub_order_id=bill.order_id if side == CONTRACTOR else None,
        job_id=bill.job_id, contractor_id=getattr(bill, "contractor_id", None) if side == CONTRACTOR else None,
        number="%s/CN-%02d" % (bill.number, seq), sequence=seq,
        note_date=(note_date or date.today().isoformat())[:10], reason=reason[:500],
        taxable=taxable, gst_percent=gst_rate, gst_amount=gst_total, cgst_amount=cgst, sgst_amount=sgst,
        igst_amount=igst, place_of_supply=bill.place_of_supply or "", retention_amount=retention,
        tds_percent=tds_rate, tds_amount=tds, cess_amount=cess, net_amount=net,
        status="ISSUED", created_by_name=actor_name or "")
    db.add(note)
    db.flush()
    for l, qty, rate, amount in rows:
        db.add(models.DBCreditNoteLine(
            credit_note_id=note.id, bill_line_id=l.id, item_id=item_of(l), description=l.description or "",
            uom=l.uom or "", qty=qty, rate=rate, amount=amount))
    db.flush()
    return note


# ---- what the credit notes do to the returns and the books ------------------------------------------------------

def credit_gst_rows(db, client_id, side, date_from="", date_to=""):
    """Credit notes as negative lines for the GST registers: outward for ours, inward for the contractors'. They fall
    in the month they were issued, not the month of the bill, so a return already filed is not disturbed."""
    rows = []
    for n in credit_notes_query(db, client_id, side).all():
        on = (n.note_date or n.created_at or "")[:10]
        if (date_from and on < date_from) or (date_to and on > date_to):
            continue
        job = db.query(models.DBJob).filter(models.DBJob.id == n.job_id).first() if n.job_id else None
        if side == CLIENT:
            party = job.customer_name if job else ""
        else:
            con = db.query(models.DBContractor).filter(
                models.DBContractor.id == n.contractor_id).first() if n.contractor_id else None
            party = con.company_name if con else ""
        row = {"kind": "Credit note", "number": n.number or "", "date": on, "party": party,
               "project": job.name if job else "", "place_of_supply": n.place_of_supply or "",
               "sac": "9954", "rate": n.gst_percent or 0,
               "taxable": -money(n.taxable), "cgst": -money(n.cgst_amount), "sgst": -money(n.sgst_amount),
               "igst": -money(n.igst_amount), "tax": -money(n.gst_amount),
               "total": -money(money(n.taxable) + money(n.gst_amount))}
        if side == CONTRACTOR:
            row["party_gstin"] = (con.gst_number or "") if n.contractor_id and con else ""
        rows.append(row)
    return rows


def credit_tds_rows(db, client_id, side, fy_quarter):
    """Credit notes as negative lines for the TDS register, in the quarter they were issued."""
    rows = []
    for n in credit_notes_query(db, client_id, side).all():
        if not (n.tds_amount or 0):
            continue
        on = (n.note_date or n.created_at or "")[:10]
        fy, q = fy_quarter(on)
        job = db.query(models.DBJob).filter(models.DBJob.id == n.job_id).first() if n.job_id else None
        row = {"date": on, "year": fy, "quarter": q, "bill": n.number or "", "section": "194C",
               "rate": n.tds_percent or 0, "amount_credited": -money(n.taxable), "tds": -money(n.tds_amount),
               "status": "CREDIT NOTE", "credit_note": True}
        if side == CLIENT:
            row.update({"deductor": job.customer_name if job else "", "project": job.name if job else ""})
        else:
            con = db.query(models.DBContractor).filter(
                models.DBContractor.id == n.contractor_id).first() if n.contractor_id else None
            row.update({"deductee": con.company_name if con else "", "pan": (con.pan or "") if con else "",
                        "paid_on": "", "missing_pan": not (con and (con.pan or "").strip())})
        rows.append(row)
    return rows


def credit_ledger_rows(db, client_id):
    """Credit notes in the party ledgers: a sum the client no longer owes us, or that we no longer owe a contractor."""
    rows = []
    for n in credit_notes_query(db, client_id).all():
        job = db.query(models.DBJob).filter(models.DBJob.id == n.job_id).first() if n.job_id else None
        if n.side == CLIENT:
            party_type, party = "client", (job.customer_name if job else "")
        else:
            con = db.query(models.DBContractor).filter(
                models.DBContractor.id == n.contractor_id).first() if n.contractor_id else None
            party_type, party = "contractor", (con.company_name if con else "")
        rows.append({"party_type": party_type, "party": party, "date": (n.note_date or n.created_at or "")[:10],
                     "kind": "Credit note" if n.side == CLIENT else "Their credit note", "number": n.number,
                     "doc_type": "credit_note", "doc_id": n.id, "billed": -money(n.net_amount), "moved": 0.0,
                     "job_id": n.job_id})
    return rows


def describe(n):
    return "%s: %s taken back, %s net" % (n.number, inr(n.taxable), inr(n.net_amount))
