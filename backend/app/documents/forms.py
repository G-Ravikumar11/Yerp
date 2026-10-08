"""The printed form of each document: its layout, ready for form_pdf to draw."""
import io
import re
from datetime import date, datetime

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.documents import form_pdf
from app import models
from app.db import SessionLocal

from app.core.currency import amount_in_words, money, rupees, unit_rate
from app.core.dates import financial_year_label
from app.core.gst import WORKS_CONTRACT_SAC


# Sensible openings, not policy. Every one is edited on the order it goes out
# on; what they save is somebody retyping the measurement mode from memory
# and getting it subtly wrong on a document that is legally binding.
WO_STANDARD_TERMS = [
    # The general contract conditions of the order form the firm works to.
    # {company} is the issuing company's short name and {city} the town its
    # letterhead gives, filled in when the order prints.
    {"clause_category": "Retention and Security", "clause_text":
        "The FSD shall be released to the contractor after completion of the defects liability period. The defects "
        "liability period shall be 12/24 months, or as per the Employer's agreement terms as the case may be, from "
        "the date of completion of the entire work and handing over to the Employer."},
    {"clause_category": "Payment Milestones", "clause_text":
        "The contractor has to submit bills in a standard GST format periodically to {company}. {company} will make "
        "payment to the contractor for all bills within 15 days after receiving payment from the \"EMPLOYER\", "
        "subject to deductions as applicable."},
    {"clause_category": "Scope of Work", "clause_text":
        "The contractor shall assume overall responsibility for execution of the work. It shall ensure the quality "
        "of work and maintain the specification standards as per the \"EMPLOYER'S\" BOQ."},
    {"clause_category": "Mode of Measurement", "clause_text":
        "All work shall be measured jointly at site in accordance with IS 1200 and the main contract and recorded "
        "in the measurement book. Only work so measured and certified is billed."},
    {"clause_category": "Defect Liability", "clause_text":
        "The contractor shall attend to the defects, if any, noticed by the \"EMPLOYER\" as per the agreement terms."},
    {"clause_category": "Programme and Liquidated Damages", "clause_text":
        "The time frame for execution of the work order is stipulated by the \"EMPLOYER\". The Employer may at its "
        "discretion levy LD/penalty for any delay in execution or bad quality. {company} will deduct the same from "
        "the contractor wherever applicable."},
    {"clause_category": "Electricity and Water Supply", "clause_text":
        "{company} will provide electricity and water for the execution of work. However, the contractor shall make "
        "his own arrangements for storage and safe custody of all resources."},
    {"clause_category": "General", "clause_text":
        "The contractor shall not be entitled to utilise the reputation of {company} for any other work."},
    {"clause_category": "Labour Hutment and Welfare", "clause_text":
        "Labour accommodation shall be provided as per company policy."},
    {"clause_category": "General", "clause_text":
        "{company} is not responsible for any internal issues pertaining to the contractor."},
    {"clause_category": "Termination", "clause_text":
        "Notwithstanding anything mentioned elsewhere in this work order, {company} reserves the right to terminate "
        "the work order whenever the EMPLOYER / {company} expresses dissatisfaction with the quality of work or time "
        "delays, or for any other reason affecting the work order from the \"EMPLOYER\" to {company}; {company} may "
        "further at its discretion confiscate all deposits, bills and work in progress, and the contractor will be "
        "responsible to pay any additional expenses incurred by {company} for completion of the work as per agreement."},
    {"clause_category": "Safety and Statutory Compliance", "clause_text":
        "The contractor shall comply with the regulations of insurance which are mandatory as per the agreement "
        "terms of the \"EMPLOYER\", and the insurance premium shall be borne by the contractor only."},
    {"clause_category": "Labour Hutment and Welfare", "clause_text":
        "The contractor shall not deploy child labour in the execution of the work."},
    {"clause_category": "Safety and Statutory Compliance", "clause_text":
        "The contractor has to comply with all labour laws as per the main contract terms with the Employer."},
    {"clause_category": "Safety and Statutory Compliance", "clause_text":
        "The contractor has to indemnify {company} against any issues related to labour and associated laws."},
    {"clause_category": "Safety and Statutory Compliance", "clause_text":
        "The contractor has to follow all safety precautions and shall be responsible for all such safety measures, "
        "such as caps, harnesses etc., to safeguard labour against accidents as per norms."},
    {"clause_category": "Safety and Statutory Compliance", "clause_text":
        "The contractor shall be responsible for all accidents and incidents during execution of the \"WORK\"."},
    {"clause_category": "Safety and Statutory Compliance", "clause_text":
        "The contractor shall have statutory registrations such as labour licence, EPF, ESI and GST etc. and should "
        "furnish copies of the same to {company}."},
    {"clause_category": "Programme and Liquidated Damages", "clause_text":
        "To ensure the quality and progress of work, {company} shall review the progress of work from time to time "
        "and may depute its own manpower and other resources as per the requirement to meet the agreed milestones, "
        "in case the contractor fails to meet the targets. All such costs incurred shall be debited to the "
        "contractor's account."},
    {"clause_category": "Defect Liability", "clause_text":
        "The contractor has to provide the required guarantees/warranties as applicable."},
    {"clause_category": "Arbitration and Jurisdiction", "clause_text":
        "All disputes and legalities pertaining to this work order shall fall within the jurisdiction of the City "
        "Civil Court, {city}."},
]


def wo_payment_terms_text(order):
    """The payment clause, written from the two fields rather than typed."""
    parts = []
    if order.billing_cycle:
        parts.append("Running Account bills may be raised %s"
                     % {"Monthly": "monthly", "Fortnightly": "fortnightly",
                        "On milestone": "on completion of each milestone",
                        "On completion": "on completion of the work"}.get(
                            order.billing_cycle, order.billing_cycle.lower()))
    if order.payment_days:
        parts.append("payment shall be released within %d days of certification"
                     % order.payment_days)
    return (", and ".join(parts) + ".") if parts else ""


def wo_document_payload(db, client, order):
    """Everything the printable order needs, in the order it is printed.

    The watermark is decided here rather than in the page, so a provisional
    order cannot be printed as a clean one by loading the view differently.
    Shared by the JSON view, the on-screen preview and the PDF, so all three
    are the same document and cannot drift apart.
    """
    doc = wo_dict(db, order, detail=True)
    doc["company"] = client.company_name or ""
    # The unit's own letterhead where it has one, the account's otherwise. A
    # document that goes out without either is still a valid document, so the
    # absence is not an error anywhere.
    if not doc["business_unit_detail"].get("logo_url"):
        doc["business_unit_detail"]["logo_url"] = client.logo_url or ""
    doc["printed_at"] = datetime.now().strftime("%d/%m/%Y   %H:%M")
    doc["financial_year"] = financial_year_label(order.commencement_date)
    doc["amount_in_words"] = amount_in_words(order.net_order_value)
    doc["payment_terms"] = wo_payment_terms_text(order)
    doc["watermark"] = ("PROVISIONAL - NOT VALID FOR EXECUTION"
                        if order.status == "PROVISIONAL" else
                        "DRAFT - NOT ISSUED" if order.status == "DRAFT" else
                        "CANCELLED" if order.status == "CANCELLED" else
                        "SUPERSEDED" if order.status == "AMENDED" else "")

    # Named where they are known. A signature block printed with the approver's
    # name already on it is the difference between a document that records who
    # committed the business and one that leaves a blank anybody can fill in.
    prepared_by, approved_by = "", ""
    for row in db.query(models.DBSubcontractApproval).filter(
            models.DBSubcontractApproval.order_id == order.id).order_by(
                models.DBSubcontractApproval.id).all():
        if row.action in ("CREATE", "SUBMIT") and not prepared_by:
            prepared_by = row.actor_name or ""
        if row.action == "APPROVE":
            approved_by = row.actor_name or ""
    doc["signatures"] = [
        {"role": "Prepared by", "name": prepared_by, "for": "Billing Engineer"},
        {"role": "Approved by", "name": approved_by, "for": "Project Head"},
        {"role": "For and on behalf of", "name": doc["company"], "for": "The Master"},
        {"role": "Accepted by", "name": doc["contractor"], "for": "The Contractor"},
    ]
    return doc


def wo_special_conditions(doc):
    """The numbered line of special conditions the trade writes on an order."""
    parts = ["TDS applicable" if doc.get("tds_rate") else "TDS not applicable",
             "GST applicable" if doc.get("gst_rate") else "GST not applicable",
             "Payment shall be made on %s RA bills" % (doc.get("billing_cycle") or "monthly").lower()]
    if doc.get("retention_percent"):
        parts.append("FSD %g%% applicable on each bill value" % doc["retention_percent"])
    if doc.get("labour_cess_percent"):
        parts.append("Labour welfare cess %g%% deducted from each bill" % doc["labour_cess_percent"])
    parts.append("GCC as per Annexure-1")
    return " ".join("%d) %s." % (i, p) for i, p in enumerate(parts, 1))


def wo_form_spec(db, client, order):
    """The subcontract work order in the trade's own form, line for line as
    the sample the firm works to: the company and the order box, the gang with
    its PAN and GSTIN, the schedule, the value in words, taxes, the payment
    terms and the signatures; the general conditions on the page after."""
    doc = wo_document_payload(db, client, order)
    sig = doc_signatories(db, client.id)
    con = doc.get("contractor_detail") or {}
    job = db.query(models.DBJob).filter(models.DBJob.id == order.job_id).first()
    history_prepared = next((s["name"] for s in doc.get("signatures", []) if s["role"] == "Prepared by"), "")
    company = letterhead(db, client, order.business_unit_id)

    rows = []
    for i, it in enumerate(doc.get("items") or [], 1):
        boq = " ".join(x for x in (it.get("activity_no") or "", it.get("item_code") or "") if x)
        desc = it.get("item_description") or ""
        if it.get("technical_spec"):
            desc += "\n" + it["technical_spec"]
        rows.append([str(i), boq, desc, it.get("uom") or "", form_pdf.qty_text(it.get("quantity")),
                     form_pdf.plain_number(it.get("unit_rate")), form_pdf.plain_number(it.get("total_amount"))])

    months = doc.get("duration_months")
    period = ""
    if doc.get("commencement_date") or doc.get("completion_date"):
        period = "%s to %s" % (form_pdf.date_text(doc.get("commencement_date")) or "-",
                               form_pdf.date_text(doc.get("completion_date")) or "-")
        if months:
            period += " (%g months)" % months
    sched = doc.get("billing_schedule") or {}
    gst_rate = doc.get("gst_rate") or 0
    gst_text = ("%g%% (CGST %g%% + SGST %g%%) - Rs. %s" % (gst_rate, gst_rate / 2, gst_rate / 2, form_pdf.inr(doc.get("gst_amount")))
                if sched.get("intra_state") else "%g%% IGST - Rs. %s" % (gst_rate, form_pdf.inr(doc.get("gst_amount")))) \
        if gst_rate else "Not applicable"
    tds_text = ("Applicable - %g%% u/s 194C" % doc["tds_rate"]) if doc.get("tds_rate") else "Not applicable"
    others = ("Labour cess %g%%" % doc["labour_cess_percent"]) if doc.get("labour_cess_percent") else ""

    advance = "-"
    if doc.get("mobilization_advance_percent"):
        advance = "%g%% (Rs. %s) against an equal bank guarantee, recovered at %g%% of each RA bill" % (
            doc["mobilization_advance_percent"], form_pdf.inr(doc.get("mobilization_advance_amount")),
            doc.get("advance_recovery_percent") or doc["mobilization_advance_percent"])
    ra = (doc.get("billing_cycle") or "Monthly")
    if doc.get("payment_days"):
        ra += ", paid within %d days of certification" % doc["payment_days"]
    fsd = ("%g%% of bill value" % doc["retention_percent"]) if doc.get("retention_percent") else "-"
    site = ", ".join(x for x in ((job.number if job else "") or "", (job.name if job else "") or "",
                                 (job.site_address if job else "") or "") if x) or doc.get("project") or "-"
    manager = db.query(models.DBEmployee).filter(models.DBEmployee.id == job.manager_id).first() \
        if job and job.manager_id else None
    site_contact = "-".join(x for x in (employee_name(manager) if manager else "", (manager.phone or "") if manager else "") if x) or "-"
    terms = [("1. Mobilisation Advance", advance), ("2. RA Bills", ra), ("3. FSD", fsd),
             ("4. Special Conditions", doc.get("payment_terms") or wo_special_conditions(doc)),
             ("5. Work Address", site), ("6. Contact Person", site_contact)]

    signatures = [("Contractor Signature", doc.get("contractor") or ""),
                  ("Prepared By", _sig_line(dict(sig["prepared"], name=sig["prepared"]["name"] or history_prepared))),
                  ("Proposed By", _sig_line(sig["proposed"])),
                  ("Recommended By", _sig_line(sig["recommended"])),
                  ("Authorized Signatory", _sig_line(sig["authorised"]))]
    # The conditions print as the sample prints them: numbered, without the
    # headings they are filed under.
    clauses = [fill_terms(t.get("clause_text"), company) for t in (doc.get("terms") or []) if t.get("clause_text")] or \
              [fill_terms(t["clause_text"], company) for t in company_terms(db, client.id)]
    stage = {"PROVISIONAL": "submitted", "APPROVED": "approved", "EXECUTED": "approved"}.get(order.status or "")
    signatures, seal = sign_boxes(db, client.id, signatures, stage)
    blocks = [
        {"type": "header", "company": company, "title": "WORK ORDER",
         "facts": [("Project", (job.number if job else "") or doc.get("project") or ""),
                   ("Date", form_pdf.date_text((doc.get("approved_at") or doc.get("created_at") or "")[:10])),
                   ("Expiry Dt", form_pdf.date_text(doc.get("completion_date"))),
                   ("Order No", doc.get("wo_number") or "")]},
        {"type": "party", "label": "Sub Contractor Name", "name": doc.get("contractor") or "",
         "address": con.get("address") or "",
         "facts": party_facts(con.get("gst_number"), con.get("pan"))[:2]},
        {"type": "pairs", "aside": True, "label_width": 34,
         "rows": [("Contact Person", con.get("contact_person") or doc.get("contractor") or ""),
                  ("Mobile No.", con.get("phone_number") or "")]},
    ]
    if doc.get("subject"):
        blocks.append({"type": "pairs", "rows": [("Subject", doc["subject"])], "label_width": 34})
    blocks += [
        {"type": "table", "columns": [("#", 6, "C"), ("BOQ", 26, "L"), ("Description", 70, "L"), ("UoM", 13, "C"),
                                      ("Qty", 19, "R"), ("Rate", 21, "R"), ("Total Amt", 27, "R")],
         "rows": rows, "totals": [("TOTAL AMOUNT", form_pdf.plain_number(doc.get("gross_amount")), True)]},
        {"type": "words", "label": "Rupees", "text": _words(doc.get("gross_amount"))},
        {"type": "text", "text": "The above agreed rates are firm till completion of the entire work including "
                                 "variation in scope and extension of time"},
        {"type": "pairs", "rows": [("Contract Period", period or "-")], "label_width": 34},
        {"type": "heading", "text": "TAXES AND DUTIES (As Applicable)"},
        {"type": "pairs", "rows": [("GST", gst_text)], "label_width": 34},
        {"type": "pairs", "cols": 2, "rows": [("TDS", tds_text), ("Others", others)]},
        {"type": "text", "style": "bold", "text": "All the statutory payments, enactments and adjustments to be borne "
                                                  "by Sub Contractor only."},
        {"type": "text", "style": "small", "text":
            "We are pleased to award the work order subject to Terms & Conditions specified herein. Quote our Order "
            "reference in all your future correspondence. Kindly acknowledge the order as token of acceptance. The "
            "contract prices stipulated here are derived based on the unit rates as offered by you. However the payment "
            "is based on the actual work done. The authorized representatives of the company shall certify the same."},
        {"type": "band", "text": "Payment Terms & Conditions"},
        {"type": "terms", "rows": terms, "label_width": 58, "bold_rows": ["5. Work Address"]},
        {"type": "signatures", "boxes": signatures, "seal": seal},
        {"type": "page_break"},
        {"type": "band", "text": "GENERAL CONTRACT CONDITIONS (GCC)"},
        {"type": "numbered", "items": clauses, "closing": [
            "If any special condition is mentioned, the related conditions in the GCC will be superseded.",
            "We request you to return the duplicate copy duly signed and stamped indicating your receipt of the work "
            "order and its acceptance.",
            "If we do not receive the acceptance within one week, it is considered that the order is accepted by you."]},
        {"type": "signatures", "boxes": signatures, "seal": seal},
    ]
    return {"title": "Work Order %s" % (doc.get("wo_number") or ""), "author": company["name"],
            "watermark": doc.get("watermark") or "", "blocks": blocks,
            "footer": "%s  |  %s  |  Printed %s" % (doc.get("wo_number") or "", company["name"],
                                                    datetime.now().strftime("%d/%m/%Y %H:%M"))}


def ra_form_spec(db, client, bill):
    """The client RA bill in the same form: the bill's own box, the client's,
    the abstract of work, the deductions and tax down the right, the figure in
    words, the e-invoice registration, and the signatures."""
    b = ra_bill_dict(db, bill, detail=True)
    sig = doc_signatories(db, client.id)
    job = db.query(models.DBJob).filter(models.DBJob.id == bill.job_id).first()
    wo = b.get("work_order_detail") or {}
    buyer = einvoice_buyer(db, client.id, job) if job else None
    our = b.get("our") or {}
    company = letterhead(db, client)
    card = customer_card(buyer)
    b_addr = ", ".join(x for x in ((buyer.address if buyer else "") or "", (getattr(buyer, "city", "") or "") if buyer else "",
                                   (getattr(buyer, "pincode", "") or "") if buyer else "") if x)
    rows = [[str(i), l.get("fg_code") or "", l.get("description") or "", l.get("uom") or "",
             form_pdf.qty_text(l.get("ordered_qty")), form_pdf.qty_text(l.get("previously_billed_qty")),
             form_pdf.qty_text(l.get("this_bill_qty")), form_pdf.qty_text(l.get("measured_to_date")),
             form_pdf.plain_number(l.get("rate")), form_pdf.plain_number(l.get("amount"))]
            for i, l in enumerate(b.get("lines") or [], 1)]
    taxable = money(b["this_bill"])
    rate = b.get("tax_percent") or 0
    sums = [("Value of work done up to date", form_pdf.inr(b["gross_to_date"]), False),
            ("Less: claimed in earlier bills", form_pdf.inr(-b["previously_billed"]), False),
            ("Value of work in this bill", form_pdf.inr(b["this_bill"]), True)]
    sums.append(("Taxable value (work measured)", form_pdf.inr(taxable), True))
    if b["cgst_amount"] or b["sgst_amount"]:
        sums += [("Add: CGST @ %g%%" % (rate / 2), form_pdf.inr(b["cgst_amount"]), False),
                 ("Add: SGST @ %g%%" % (rate / 2), form_pdf.inr(b["sgst_amount"]), False)]
    elif b["igst_amount"]:
        sums.append(("Add: IGST @ %g%%" % rate, form_pdf.inr(b["igst_amount"]), False))
    if b["retention_amount"]:
        sums.append(("Less: retention @ %g%%" % b["retention_percent"], form_pdf.inr(-b["retention_amount"]), False))
    if b["advance_recovery"]:
        sums.append(("Less: mobilisation advance recovered", form_pdf.inr(-b["advance_recovery"]), False))
    if b["other_deductions"]:
        sums.append(("Less: other deductions%s" % ((" (%s)" % b["deduction_notes"]) if b["deduction_notes"] else ""),
                     form_pdf.inr(-b["other_deductions"]), False))
    if b["tds_amount"]:
        sums.append(("Less: TDS @ %g%% (deducted by the client)" % b["tds_percent"], form_pdf.inr(-b["tds_amount"]), False))
    sums.append(("NET AMOUNT PAYABLE", form_pdf.inr(b["net_payable"]), True))

    irn = active_irn(db, client.id, "ra_bill", bill.id)
    certified = b.get("certified_by_name") or ""
    signatures = [("Prepared By", _sig_line(sig["prepared"])),
                  ("Checked By", _sig_line(sig["recommended"])),
                  ("Certified By", (certified + " (Client's Engineer)") if certified else "Client's Engineer"),
                  ("Authorized Signatory", _sig_line(sig["authorised"]))]
    period = ("%s to %s" % (form_pdf.date_text(b.get("period_from")), form_pdf.date_text(b.get("period_to")))
              if b.get("period_from") else ("Up to %s" % form_pdf.date_text(b.get("period_to")) if b.get("period_to") else ""))
    blocks = [
        {"type": "header", "company": company, "title": "RA BILL",
         "facts": [("Bill No", b["number"]), ("RA No", str(b.get("sequence") or 1)),
                   ("Bill Date", form_pdf.date_text((b.get("certified_at") or b.get("created_at") or "")[:10])),
                   ("Period", period or "-")]},
        {"type": "party", "label": "Bill To", "name": (buyer.name if buyer else "") or (job.customer_name if job else ""),
         "address": card.get("address") or b_addr,
         "facts": party_facts(card.get("gstin"), card.get("pan"), card.get("state")) + [
             ("Place of Supply", ("%s (%s)" % (b.get("place_of_supply_name"), b.get("place_of_supply")))
              if b.get("place_of_supply") else "")]},
        {"type": "pairs", "aside": True, "label_width": 34,
         "rows": [("Contact Person", card.get("contact") or ""), ("Mobile No.", card.get("phone") or "")]},
        {"type": "pairs", "cols": 2, "rows": [("Project", b.get("project") or ""), ("Work Order", "%s%s" % (
            wo.get("number") or b.get("work_order") or "", (" dt. " + form_pdf.date_text(wo.get("date"))) if wo.get("date") else "")),
            ("Site", (job.site_address if job else "") or "-"), ("Your Reference", wo.get("reference") or "-")]},
        {"type": "table", "columns": [("#", 5, "C"), ("Item", 16, "L"), ("Description", 50, "L"), ("UoM", 11, "C"),
                                      ("Order Qty", 16, "R"), ("Previous", 16, "R"), ("This Bill", 16, "R"),
                                      ("Up to Date", 16, "R"), ("Rate", 16, "R"), ("Amount", 20, "R")],
         "rows": rows, "totals": [("VALUE OF WORK IN THIS BILL", form_pdf.plain_number(b["this_bill"]), True)]},
        {"type": "sums", "rows": sums},
        {"type": "words", "label": "Rupees", "text": _words(b["net_payable"])},
        {"type": "pairs", "rows": [("SAC", WORKS_CONTRACT_SAC + " - works contract services")], "label_width": 42},
    ]
    varied = order_variations(db, bill)
    if varied:
        blocks += [
            {"type": "band", "text": "VARIATIONS AGREED ON THIS ORDER"},
            {"type": "table", "columns": [("Ref", 12, "L"), ("Agreed", 16, "C"), ("What changed", 82, "L"), ("Value", 22, "R")],
             "rows": [[x["number"], form_pdf.date_text(x["date"]), (x["reason"] + (" - " if x["reason"] else "") + x["what"]).strip(),
                       form_pdf.plain_number(x["value"])] for x in varied["variations"]],
             "totals": [("TOTAL VARIATIONS", form_pdf.plain_number(sum(x["value"] for x in varied["variations"])), True)]},
            {"type": "pairs", "label_width": 62, "rows": [("Order value as first placed", form_pdf.inr(varied["original"])),
                                                           ("Order value as varied", form_pdf.inr(varied["varied"]))]},
        ]
    if irn:
        blocks.append({"type": "qr", "data": irn.signed_qr, "lines": [
            "e-Invoice registered with the GST Invoice Registration Portal",
            "IRN: " + irn.irn, "Ack No: %s     Ack Date: %s" % (irn.ack_no, irn.ack_date)]})
    blocks += [
        {"type": "text", "style": "small", "text": "Quantities are as recorded in the measurement book and jointly "
                                                   "verified. Retention is held as per the contract and released on "
                                                   "completion of the defects liability period."},
    ]
    signatures, seal = sign_boxes(db, client.id, signatures, {"SUBMITTED": "submitted", "CERTIFIED": "approved",
                                                              "PAID": "approved"}.get(b["status"]))
    blocks.append({"type": "signatures", "boxes": signatures, "seal": seal})
    watermark = {"DRAFT": "DRAFT - NOT A CLAIM", "SUBMITTED": "SUBMITTED - NOT YET CERTIFIED",
                 "CANCELLED": "CANCELLED"}.get(b["status"], "")
    return {"title": "RA Bill %s" % b["number"], "author": company["name"], "watermark": watermark,
            "blocks": blocks, "footer": "%s  |  %s  |  Printed %s" % (b["number"], company["name"],
                                                                      datetime.now().strftime("%d/%m/%Y %H:%M"))}


def form_pdf_response(spec, name):
    if not form_pdf.PDF_AVAILABLE:
        raise HTTPException(503, "The PDF library is not installed on this server; the workbook is still available.")
    pdf = form_pdf.build_form_pdf(spec)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name or "document").strip("_") or "document"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="%s.pdf"' % safe,
                                      "Content-Length": str(len(pdf))})


def po_form_spec(db, client, order):
    """The purchase order: supplier with GSTIN, the lines with their GST, the
    total in words, delivery and payment, and the signatures."""
    d = purchase_order_to_dict(db, order)
    sig = doc_signatories(db, client.id)
    sup = next((s for s in db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client.id).all()
                if norm_name(s.name) == norm_name(order.supplier_name)), None)
    our = d.get("our") or our_party(db, client.id)
    company = letterhead(db, client)
    job = db.query(models.DBJob).filter(models.DBJob.id == order.job_id).first() if order.job_id else None
    rows, sub = [], 0.0
    for i, l in enumerate(d.get("line_items") or [], 1):
        amt = money((l.get("qty") or 0) * (l.get("price") or 0))
        sub += amt
        rows.append([str(i), l.get("item_code") or "", l.get("description") or "", l.get("uom") or "",
                     form_pdf.qty_text(l.get("qty")), form_pdf.plain_number(l.get("price")),
                     str(l.get("tax_rate") or "").replace("GST", "").strip(), form_pdf.plain_number(amt)])
    if not rows:
        # An order agreed as a lump sum, with no schedule: one line carrying
        # the figure, so the sub total is the order's and not a nought.
        sub = money(d.get("amount") or 0)
        rows.append(["1", "", d.get("notes") or d.get("category") or "As agreed", "", "", "", "",
                     form_pdf.plain_number(sub)])
    days = (sup.payment_days if sup and sup.payment_days else 30)
    deliver = d.get("deliver_to") or (job.site_address if job else "") or "As instructed"
    signatures = [("Supplier Acceptance", order.supplier_name or ""),
                  ("Prepared By", _sig_line(sig["prepared"])), ("Proposed By", _sig_line(sig["proposed"])),
                  ("Recommended By", _sig_line(sig["recommended"])), ("Authorized Signatory", _sig_line(sig["authorised"]))]
    blocks = [
        {"type": "header", "company": company, "title": "PURCHASE ORDER",
         "facts": [("PO No", d.get("number") or ""), ("Date", form_pdf.date_text(d.get("issue_date"))),
                   ("Needed By", form_pdf.date_text(d.get("needed_by")) or "-"),
                   ("Project", (job.number if job else "") or "General")]},
        {"type": "party", "label": "Supplier Name", "name": order.supplier_name or "",
         "address": (sup.address if sup else "") or "",
         "facts": party_facts((sup.gstin if sup else "") or "", (sup.pan if sup else "") or "")},
        {"type": "pairs", "cols": 2, "rows": [("Contact Person", (sup.contact_person if sup else "") or ""),
                                              ("Mobile No.", (sup.phone if sup else "") or ""),
                                              ("Email", order.supplier_email or (sup.email if sup else "") or ""),
                                              ("Reference", d.get("reference") or "-")]},
        {"type": "table", "columns": [("#", 6, "C"), ("Item Code", 20, "L"), ("Description", 62, "L"), ("UoM", 13, "C"),
                                      ("Qty", 18, "R"), ("Rate", 20, "R"), ("GST", 13, "C"), ("Amount", 30, "R")],
         "rows": rows, "totals": [("SUB TOTAL", form_pdf.plain_number(sub), False),
                                  ("GST", form_pdf.plain_number(d.get("tax_amount")), False),
                                  ("TOTAL AMOUNT", form_pdf.plain_number(d.get("total")), True)]},
        {"type": "words", "label": "Rupees", "text": _words(d.get("total"))},
        {"type": "band", "text": "Delivery & Payment Terms"},
        {"type": "terms", "rows": [("1. Delivery Address", deliver),
                                   ("2. Delivery By", form_pdf.date_text(d.get("needed_by")) or "As agreed"),
                                   ("3. Payment", "Within %d days of receipt of material and a correct GST invoice" % days),
                                   ("4. Invoice", "Quote this PO number on the invoice, the delivery challan and the e-way bill"),
                                   ("5. Inspection", "Material is accepted on receipt and inspection at site; rejected material "
                                                     "is returned at the supplier's cost"),
                                   ("6. Notes", d.get("notes") or "-")], "label_width": 42},
    ]
    po_stage = "approved" if ((order.approval_status or "") == "approved" or order.status in ("Approved", "Closed")) \
        else ("submitted" if (order.approval_status or "") == "pending" else None)
    signatures, seal = sign_boxes(db, client.id, signatures, po_stage)
    blocks.append({"type": "signatures", "boxes": signatures, "seal": seal})
    watermark = {"Draft": "DRAFT - NOT ISSUED", "Cancelled": "CANCELLED", "Rejected": "REJECTED"}.get(order.status, "")
    if (order.approval_status or "") == "pending":
        watermark = "AWAITING APPROVAL"
    return {"title": "Purchase Order %s" % (d.get("number") or ""), "author": company["name"], "watermark": watermark,
            "blocks": blocks, "footer": "%s  |  %s  |  Printed %s" % (d.get("number") or "", company["name"],
                                                                      datetime.now().strftime("%d/%m/%Y %H:%M"))}


def _cert_person(db, emp_id, fallback_name, default_title):
    """A name on the signature row, with the designation HR gave them - else
    the one the certificate prints under that box."""
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first() if emp_id else None
    name = employee_name(emp) if emp else (fallback_name or "")
    title = ((emp.job_title or "").strip() if emp else "") or default_title
    return name, title


def _bill_figures(bill):
    """One bill's figures as the certificate's rows name them."""
    work = money(bill.this_bill)
    debit = money(getattr(bill, "debit_notes", 0) or 0)
    gross = rupees(work - debit)
    gst = money(bill.gst_amount)
    adv, other = money(bill.advance_recovery), money(bill.other_deductions)
    ret, tds, cess = money(bill.retention_amount), money(bill.tds_amount), money(bill.labour_cess_amount)
    return {"work": work, "mob": 0.0, "mat": 0.0, "debit": debit, "gross": gross,
            "sgst": money(bill.sgst_amount), "cgst": money(bill.cgst_amount), "igst": money(bill.igst_amount),
            "gst": gst, "total": money(gross + gst), "adv": adv, "other": other, "ret": ret, "tds": tds,
            "cess": cess, "ded": money(adv + other + ret + tds + cess), "net": money(bill.net_payable)}


def short_entry_code(entry):
    """The part of an entry's code that is its own number, "MB-007": on a bill the book's number is in the heading."""
    return (getattr(entry, "code", "") or "").rsplit("/", 1)[-1]


def sub_bill_certificate(db, client, bill):
    """The gang's RA bill as the three sheets it is signed on - the Top Sheet
    (certificate of payment), AB-1 (abstract) and MB-1 (measurement book) -
    as one description the PDF and the workbook are both drawn from."""
    b = sub_bill_dict(db, bill, detail=True)
    order = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == bill.order_id).first()
    con = db.query(models.DBContractor).filter(models.DBContractor.id == bill.contractor_id).first() \
        if bill.contractor_id else None
    job = db.query(models.DBJob).filter(models.DBJob.id == bill.job_id).first() if bill.job_id else None
    company = letterhead(db, client, order.business_unit_id if order else None)
    d = form_pdf.date_text
    seq = bill.sequence or 1
    previous = db.query(models.DBSubBill).filter(
        models.DBSubBill.order_id == bill.order_id, models.DBSubBill.id != bill.id,
        models.DBSubBill.sequence < seq, models.DBSubBill.status != "CANCELLED").all()
    this = _bill_figures(bill)
    prev = {k: money(sum(_bill_figures(p)[k] for p in previous)) for k in this}
    rate = bill.gst_percent or 0
    con_name = (con.company_name if con else b.get("contractor")) or ""
    project = (job.name if job else "") or b.get("project") or ""

    # --- Top Sheet: the certificate of payment ---
    amount = form_pdf.inr(order.gross_amount if order else 0)
    if order and order.amendment_no and order.supersedes_id:
        first = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == order.supersedes_id).first()
        if first:
            amount = "%s (original) & %s (amended)" % (form_pdf.inr(first.gross_amount), amount)
    info = [
        ("1.1", "Work Order No. & Date (original)", [order.wo_number if order else "", None, "Date :",
                                                      d(((order.approved_at or order.created_at) if order else "")[:10])]),
        ("1.2", "Work Order Amendment No. & Date", [("Amendment %d" % order.amendment_no) if order and order.amendment_no else "-",
                                                     None, "Date :", d((order.updated_at or "")[:10]) if order and order.amendment_no else "-"]),
        ("1.3", "Work Order Amount (original & amended)", [amount]),
        ("1.4", "SC Work Period - From and To", [d(order.commencement_date) if order else "", None, "to",
                                                 d(order.completion_date) if order else ""]),
        ("2.1", "Name of the Sub Contractor", [con_name]),
        ("2.2", "Address of the Sub Contractor", [", ".join(x for x in ((con.address or "").replace("\n", ", ") if con else "",
                                                                          (con.city or "") if con else "",
                                                                          (con.state or "") if con else "",
                                                                          (con.pin_code or "") if con else "") if x)]),
        ("2.3", "PAN # of Sub Contractor", [(con.pan or "") if con else ""]),
        ("2.4", "GST # of Sub Contractor", [(con.gst_number or "") if con else ""]),
        ("2.5", "PRW's Bill Detail :", ["RA Bill No.", str(seq), "Bill Date", d(b["bill_date"])]),
        ("3.1", "Bill Period :", ["From", d(b["period_from"]) or "-", "To", d(b["period_to"]) or "-"]),
        ("3.2", "HSN/SAC CODE", ["HSN/SAC", b["hsn_sac"] or "", "STATE CODE", b.get("place_of_supply") or ""]),
        ("3.3", "Typ of Work", [b["work_type"] or ""]),
    ]

    def fig(sl, label, key, ref="", bold=False):
        return {"sl": sl, "label": label, "ref": ref, "bold": bold,
                "upto": money(prev[key] + this[key]), "prev": prev[key], "this": this[key]}

    cess_on = bool(this["cess"] or prev["cess"] or (bill.labour_cess_percent or 0))
    money_rows = [
        {"section": "EARNINGS/GROSS BILL"},
        fig("4.01", "Value of Sub Contract Work Measured (Type of Work: %s) / SAC Code: %s"
            % (b["work_type"] or "", b["hsn_sac"] or ""), "work", "Bill Detail"),
        fig("4.02", "Mobilization Advance ", "mob"),
        fig("4.03", "Material / Work Advance", "mat"),
        fig("4.04", "Recoveries in Debit Notes", "debit"),
        fig("4.04", "Gross Total Value ", "gross", bold=True),
        {"section": "ADD GST CHARGE "},
        fig("4.05", "SGST @  %g %%" % (rate / 2.0), "sgst", "Accounts"),
        fig("4.06", "CGST @ %g %%" % (rate / 2.0), "cgst", "Accounts"),
        fig("4.07", "IGST @ %g%%" % rate, "igst", "Accounts"),
        fig("4.08", "GST Total Value ", "gst", bold=True),
        fig("4.09", "Total Gross Value including GST", "total", bold=True),
        {"section": "DEDUCTION & RECOVERYS"},
        fig("5.01", "Recovery of Mobilization Advance", "adv"),
        fig("5.02", "Recovery of Material / Work Advance/Others", "other"),
        fig("5.03", "Recovery of Retention @ %g %% " % (bill.retention_percent or 0), "ret"),
        fig("5.04", "Tax Deduction at Source @ %.2f%% " % (bill.tds_percent or 0), "tds", "Accounts"),
    ]
    if cess_on:
        money_rows.append(fig("5.05", "Labour Welfare Cess @ %g%%" % (bill.labour_cess_percent or 0), "cess", "Accounts"))
    money_rows.append(fig("5.06" if cess_on else "5.05", "Total Deduction ", "ded", bold=True))
    net_row = fig("", "Net Amount for Payment ", "net", bold=True)
    net_row["span_label"] = True
    money_rows.append(net_row)

    # Who signed: prepared by whoever sent it, measured by whoever wrote the
    # book, certified by the route's signatures before the last, approved by the last.
    entries = db.query(models.DBSubMeasurement).filter(
        models.DBSubMeasurement.sub_bill_id == bill.id).order_by(models.DBSubMeasurement.id).all()
    measurers, seen = [], set()
    for m in entries:
        key = m.recorded_by or m.recorded_by_name
        if key in seen:
            continue
        seen.add(key)
        measurers.append(_cert_person(db, m.recorded_by, m.recorded_by_name, "Site Engineer"))
    signed = sub_bill_signed(db, bill)
    prep = _cert_person(db, getattr(bill, "submitted_by", None), b.get("submitted_by_name"), "QS") \
        if b.get("submitted_by_name") else ("", "QS")
    chain = [r for r in sub_bill_chain_rows(db, bill.id) if r.status == "approved"]
    final = (bill.status or "") in ("CERTIFIED", "PAID")
    certifiers = [_cert_person(db, r.approver_id, sub_bill_step_name(db, r), "Head QS")
                  for r in (chain[:-1] if final else chain)]
    approver = _cert_person(db, chain[-1].approver_id, sub_bill_step_name(db, chain[-1]), "Site Incharge") \
        if (final and chain) else ((signed["approved"], "Site Incharge") if final else ("", "Site Incharge"))
    accepted = b.get("accepted_by_name") or ""
    top_sign = [
        ("Accepted for Sub Contractor", ("%s\n%s" % (con_name, ("Accepted by %s, %s" % (accepted, d(b["accepted_at"][:10])))
                                                      if accepted else "")).strip(), "Authorized Signatory"),
        ("Prepared By", prep[0], prep[1]),
        ("Site Engineer", ", ".join(n for n, _ in measurers), (measurers[0][1] if measurers else "Site Engineer")),
        ("Certified by", ", ".join(n for n, _ in certifiers), certifiers[0][1] if certifiers else "Head QS"),
        ("Approved By", approver[0], approver[1]),
    ]
    top = {"banner": [(company["name"].upper(), "banner"),
                      (company["address"].replace("\n", ", "), "centre"),
                      ("GSTIN NO: %s" % company["gstin"], "centrebold") if company.get("gstin") else ("", "centre"),
                      ("PROJECT : %s" % project, "centrebold"),
                      ("CERTIFICATE OF PAYMENT", "band")],
           "info": info, "money": money_rows, "words": amount_in_words(this["net"]),
           "signatures": top_sign}

    # --- AB-1: the abstract ---
    lines = {l["item_id"]: l for l in b.get("lines") or []}
    prev_qty = {}
    if previous:
        for l in db.query(models.DBSubBillLine).filter(
                models.DBSubBillLine.sub_bill_id.in_([p.id for p in previous])).all():
            prev_qty[l.item_id] = prev_qty.get(l.item_id, 0.0) + (l.this_bill_qty or 0.0)
    rows, pending_header, n = [], None, 0
    items = db.query(models.DBSubcontractItem).filter(
        models.DBSubcontractItem.order_id == bill.order_id).order_by(
            models.DBSubcontractItem.display_order, models.DBSubcontractItem.id).all()
    for it in items:
        if it.is_header:
            pending_header = {"header": True, "description": (it.item_description or "").split("\n")[0]}
            continue
        pq = money(prev_qty.get(it.id, 0.0))
        line = lines.get(it.id)
        tq = money(line["this_bill_qty"]) if line else 0.0
        if not pq and not tq:
            continue
        if pending_header:
            rows.append(pending_header)
            pending_header = None
        n += 1
        r8 = unit_rate(line["rate"] if line else it.unit_rate)
        rows.append({"sl": n, "description": (it.item_description or "").split("\n")[0], "unit": it.uom or "",
                     "prev_qty": pq or None, "prev_rate": r8 if pq else None, "prev_amount": money(pq * r8) if pq else None,
                     "this_qty": tq or None, "this_rate": r8 if tq else None, "this_amount": money(tq * r8) if tq else None,
                     "upto_qty": money(pq + tq), "upto_amount": money((pq + tq) * r8), "remarks": ""})
    totals = {"prev": money(sum(r.get("prev_amount") or 0 for r in rows if not r.get("header"))),
              "this": money(sum(r.get("this_amount") or 0 for r in rows if not r.get("header")))}
    totals["upto"] = money(totals["prev"] + totals["this"])
    period = "%s to %s" % (d(b["period_from"]) or "-", d(b["period_to"]) or "-")
    site = ((job.site_address or "").split("\n")[0] if job else "") or project
    abstract = {
        "banner": [(company["name"].upper(), "banner"), ("ABSTRACT SHEET", "band")],
        "meta": [("Name of the Project : %s" % project, "Vendor Code : %s" % ((con.vendor_code or "") if con else ""),
                  "Bill.No. %02d" % seq),
                 ("Name of the Contractor: %s" % con_name, "WO.No: %s" % (order.wo_number if order else ""),
                  "Bill Period: %s" % period),
                 ("Name of the Work: %s" % (b["work_name"] or ""), "Name of the site: %s" % site,
                  "To be paid vide Bill.No: %02d   Date: %s" % (seq, d(b["bill_date"])))],
        "rows": rows, "totals": totals,
        "signatures": [("CONTRACTOR", con_name, ""), ("CHECKED BY", prep[0], prep[1]),
                       ("PROJECT MANAGER", ", ".join(n for n, _ in certifiers), certifiers[0][1] if certifiers else ""),
                       ("PROJECT INCHARGE", approver[0], approver[1] if approver[0] else "")],
    }

    # --- MB-1: the measurement book ---
    dims = dimensions_for(db, [m.id for m in entries], models.DBMeasurementDimension.sub_measurement_id)
    order_of = {it.id: i for i, it in enumerate(items)}
    by_item = {}
    # A hold recorded for a group of blocks is printed once, under that group - not as a block of its own.
    grouped = {(m.item_id, (getattr(m, "group_ref", "") or "").strip()) for m in entries
               if not (getattr(m, "kind", "") or "") and (getattr(m, "group_ref", "") or "").strip()}
    group_holds = {}
    for m in entries:
        key = (m.item_id, (getattr(m, "group_ref", "") or "").strip())
        if (getattr(m, "kind", "") or "") == "hold" and key in grouped:
            group_holds.setdefault(key, []).append(m)
            continue
        by_item.setdefault(m.item_id, []).append(m)
    mb_rows, k = [], 0
    held_of = lambda lines_, mult: round(sum(abs(x["quantity"]) for x in (lines_ or []) if str(x.get("particulars") or "").lower().startswith("held back")) * mult, 2)
    for it in sorted((it for it in items if it.id in by_item), key=lambda x: order_of[x.id]):
        k += 1
        uom = it.uom or ""
        mb_rows.append({"kind": "item", "sno": str(k), "description": (it.item_description or "").split("\n")[0].upper()})
        item_total = 0.0
        ents = by_item[it.id]
        section, sec_total, sec_count = None, 0.0, 0
        sec_key = None

        def close_section():
            if section and sec_count > 1:
                mb_rows.append({"kind": "total", "description": "Total - %s" % section, "label": "Total Quantity",
                                "quantity": money(sec_total), "uom": uom})

        for j, m in enumerate(ents):
            mult = getattr(m, "multiplier", None) or 1.0
            # An imported book keeps its own sections and block letters, so the printed sheet reads like the Excel it came from.
            sec = (getattr(m, "section", "") or "").strip()
            if sec and sec != sec_key:
                close_section()
                sec_key = sec
                parts = sec.split(" ", 1)
                numeral = parts[0] if (len(parts) == 2 and re.match(r"^([IVXL]+|\d+)$", parts[0])) else ""
                mb_rows.append({"kind": "item", "sno": numeral, "description": (parts[1] if numeral else sec).upper()})
                section, sec_total, sec_count = (parts[1] if numeral else sec), 0.0, 0
            letter = (getattr(m, "block_label", "") or "").strip() or (chr(ord("a") + j) if j < 26 else str(j + 1))
            place = (m.location or "").strip() or (m.mb_ref or "").strip() or ("Measured on %s" % d(m.measured_on))
            mb_rows.append({"kind": "entry", "sno": letter, "description": place, "code": short_entry_code(m)})
            lines_ = dims.get(m.id) or []
            if not lines_:
                mb_rows.append({"kind": "dim", "description": m.remarks or "As measured", "uom": uom,
                                "quantity": money(money(m.quantity) / mult)})
            for dl in lines_:
                if dl.get("is_heading"):
                    mb_rows.append({"kind": "heading", "description": dl["particulars"]})
                    continue
                nos = dl.get("nos")
                mb_rows.append({"kind": "dim", "description": dl["particulars"], "uom": uom,
                                "nos": (-nos if (dl["deduct"] and nos is not None) else nos),
                                "nom": dl.get("nom"), "length": dl.get("length"), "width": dl.get("breadth"),
                                "height": dl.get("depth"), "quantity": round(dl["quantity"], 3)})
            one = round(sum(x["quantity"] for x in lines_ if not x.get("is_heading")), 3) if lines_                 else money(money(m.quantity) / mult)
            if mult != 1:
                mb_rows.append({"kind": "subtotal", "description": "Total Quantity for one Block",
                                "label": "Total Quantity", "quantity": one, "uom": uom})
                mb_rows.append({"kind": "total", "description": "Total Quantity for Block No. - %s" % place,
                                "label": "Total Quantity for %g Blocks" % mult, "quantity": money(m.quantity), "uom": uom})
            else:
                mb_rows.append({"kind": "total", "description": "Total Quantity for %s" % place,
                                "label": "Total Quantity", "quantity": money(m.quantity), "uom": uom})
            item_total += m.quantity or 0
            sec_total += m.quantity or 0
            sec_count += 1
            # Under a group of blocks that share one hold-back: what they came to, what is held, what is to be paid.
            gref = (getattr(m, "group_ref", "") or "").strip()
            nxt = ents[j + 1] if j + 1 < len(ents) else None
            if gref and (nxt is None or (getattr(nxt, "group_ref", "") or "").strip() != gref):
                grp = [x for x in ents if (getattr(x, "group_ref", "") or "").strip() == gref]
                holds_here = group_holds.get((it.id, gref), [])
                if holds_here:
                    measured_here = money(sum(x.quantity or 0 for x in grp))
                    for h in holds_here:
                        mb_rows.append({"kind": "subtotal", "description": "Total Quantity before holding back",
                                        "label": "Total Quantity", "quantity": measured_here, "uom": uom})
                        mb_rows.append({"kind": "subtotal", "description": ((h.remarks or "Held back for finishes and handing over")[:150]
                                                                           + ((" [%s]" % short_entry_code(h)) if short_entry_code(h) else "")),
                                        "label": "Held back", "quantity": money(h.quantity), "uom": uom})
                        measured_here = money(measured_here + (h.quantity or 0))
                        item_total += h.quantity or 0
                        sec_total += h.quantity or 0
                    mb_rows.append({"kind": "total", "description": "Total Qty To be paid",
                                    "label": "Total Qty To be paid", "quantity": measured_here, "uom": uom})
                    continue
                # A book imported before holds were kept apart carries the hold as a line in each block.
                paid = money(sum(x.quantity or 0 for x in grp))
                held = money(sum(held_of(dims.get(x.id), getattr(x, "multiplier", None) or 1.0) for x in grp))
                if held > 0:
                    mb_rows.append({"kind": "subtotal", "description": "Total Quantity before holding back",
                                    "label": "Total Quantity", "quantity": money(paid + held), "uom": uom})
                    mb_rows.append({"kind": "subtotal", "description": "Hold for Finishes & Handing over",
                                    "label": "Held back", "quantity": -held, "uom": uom})
                    mb_rows.append({"kind": "total", "description": "Total Qty To be paid",
                                    "label": "Total Qty To be paid", "quantity": paid, "uom": uom})
        close_section()
        if len(ents) > 1 and not section:
            mb_rows.append({"kind": "total", "description": "Total - %s" % (it.item_description or "").split("\n")[0],
                            "label": "Total Quantity", "quantity": money(item_total), "uom": uom})
    mb = {"banner": [(company["name"].upper(), "banner")],
          "meta": [("Name of the Work :- %s" % (b["work_name"] or "").upper(), ""),
                   ("Name of the contractor :- %s" % con_name, "Bill Period: %s" % period),
                   ("Bill no :- %02d (Measurements)" % seq, "Date :- %s" % d(b["bill_date"])),
                   ("Measurement book no. :- %s/MB" % (order.wo_number if order else ""),
                    "Entries on this bill :- %d" % len([m for m in entries if not (getattr(m, "kind", "") or "")]))],
          "rows": mb_rows,
          "signatures": [("CONTRACTOR", con_name, ""),
                         ("MEASURED BY", ", ".join(n for n, _ in measurers), "Site Engineer"),
                         ("CHECKED BY", prep[0], prep[1])]}
    return {"bill": b, "company": company, "top": top, "abstract": abstract, "mb": mb}


def _dash(v, places=2):
    """A figure on the certificate: a dash for nothing, as the form is filled in."""
    if v is None or v == "":
        return ""
    return form_pdf.inr(v, places) if abs(v) >= 0.005 else "-"


def _q(v):
    """A quantity as the book writes it - a deduction's count as -6, not (6)."""
    if v is None:
        return ""
    return ("-" if v < 0 else "") + form_pdf.qty_text(abs(v))


def sub_bill_form_spec(db, client, bill):
    """The gang's RA bill in its three sheets: Top Sheet, AB-1 and MB-1."""
    c = sub_bill_certificate(db, client, bill)
    b = c["bill"]
    stage = {"SUBMITTED": "submitted", "CERTIFIED": "approved", "PAID": "approved"}.get(b["status"])

    def sigs(boxes):
        out, seal = sign_boxes(db, client.id, [(role, ("%s\n(%s)" % (name, cap)) if name and cap else
                                                (name or (cap and "(%s)" % cap) or ""))
                                               for role, name, cap in boxes], stage)
        return {"type": "signatures", "boxes": out, "seal": seal}

    top = c["top"]
    W6 = [10, 64, 20, 30, 29, 29]
    info_rows, info_spans = [], []
    for i, (sl, label, cells) in enumerate(top["info"]):
        cc, dd, ee, ff = (list(cells) + [None] * 4)[:4]
        info_rows.append([{"t": sl, "a": "C"}, label, cc or "", dd or "", ee or "", ff or ""])
        if ee is None and ff is None:
            info_spans.append((2, i, 5, i))
        elif dd is None:
            info_spans.append((2, i, 3, i))
    head = [["Sl\nNo", "Description", "Reference", "Upto This\nBill Amount", "Upto Previous\nBill Amount",
             "For This\nBill Amount"]]
    m_rows, m_spans, m_shade = list(head), [], []
    for row in top["money"]:
        r = len(m_rows)
        if row.get("section"):
            m_rows.append([{"t": row["section"], "b": True}])
            m_spans.append((0, r, 5, r))
            m_shade.append(r)
            continue
        bold = row.get("bold", False)
        cells = [{"t": row["sl"], "a": "C", "b": bold}, {"t": row["label"], "b": bold}, row.get("ref") or ""]
        cells += [{"t": _dash(row[k]), "a": "R", "b": bold} for k in ("upto", "prev", "this")]
        if row.get("span_label"):
            cells[0] = {"t": row["label"], "b": True}
            m_spans.append((0, r, 2, r))
        m_rows.append(cells)
    blocks = [{"type": "banner", "logo": c["company"].get("logo_url"), "lines": [x for x in top["banner"] if x[0]]},
              {"type": "grid", "widths": W6, "rows": info_rows, "spans": info_spans},
              {"type": "grid", "widths": W6, "rows": m_rows, "spans": m_spans, "shade": m_shade, "head": 1},
              {"type": "words", "label": "AMOUNT IN WORDS:", "text": top["words"]},
              sigs(top["signatures"]),
              {"type": "page_break"}]

    a = c["abstract"]
    W12 = [9, 35, 10, 14, 11, 17, 14, 11, 17, 14, 17, 13]
    a_rows = [["SI.No", "Description", "Unit", "Up To Previous Bill", "", "", "In This Bill Claimed", "", "",
               "Up to This Bill", "", "Remarks"],
              ["", "", "", "Qty", "Rate", "Amount", "Qty", "Rate", "Amount", "Qty", "Amount", ""]]
    a_spans = [(0, 0, 0, 1), (1, 0, 1, 1), (2, 0, 2, 1), (3, 0, 5, 0), (6, 0, 8, 0), (9, 0, 10, 0), (11, 0, 11, 1)]
    for row in a["rows"]:
        if row.get("header"):
            a_rows.append(["", {"t": row["description"], "b": True}])
            continue
        a_rows.append([{"t": str(row["sl"]), "a": "C"}, row["description"], {"t": row["unit"], "a": "C"},
                       {"t": _q(row["prev_qty"]), "a": "R"}, {"t": _dash(row["prev_rate"]) if row["prev_qty"] else "", "a": "R"},
                       {"t": _dash(row["prev_amount"]) if row["prev_qty"] else "", "a": "R"},
                       {"t": _q(row["this_qty"]), "a": "R"}, {"t": _dash(row["this_rate"]) if row["this_qty"] else "", "a": "R"},
                       {"t": _dash(row["this_amount"]) if row["this_qty"] else "", "a": "R"},
                       {"t": _q(row["upto_qty"]), "a": "R"}, {"t": _dash(row["upto_amount"]), "a": "R"},
                       row.get("remarks") or ""])
    r = len(a_rows)
    t = a["totals"]
    a_rows.append([{"t": "A)", "b": True, "a": "C"}, {"t": "Total Invoice Amount", "b": True},
                   {"t": "Up to Previous Bill Amount :-", "b": True}, "", "", {"t": _dash(t["prev"]), "b": True, "a": "R"},
                   {"t": "In this Bill", "b": True}, "", {"t": _dash(t["this"]), "b": True, "a": "R"}, "",
                   {"t": _dash(t["upto"]), "b": True, "a": "R"}, ""])
    a_spans += [(2, r, 4, r), (6, r, 7, r)]
    blocks += [{"type": "banner", "logo": c["company"].get("logo_url"), "lines": a["banner"]},
               {"type": "grid", "widths": [72, 56, 54], "rows": [list(x) for x in a["meta"]], "size": "small"},
               {"type": "grid", "widths": W12, "rows": a_rows, "spans": a_spans, "head": 2, "size": "small"},
               sigs(a["signatures"]),
               {"type": "page_break"}]

    m = c["mb"]
    W10 = [9, 62, 11, 11, 11, 14, 14, 14, 20, 16]
    mb_rows, mb_spans = [["S.No", "Description", "UoM", "No's", "NoM", "Length", "Width", "Height",
                          "Total Quantity", "Remarks"]], []
    for row in m["rows"]:
        kind = row["kind"]
        r = len(mb_rows)
        if kind == "entry":
            mb_rows.append([{"t": row.get("sno") or "", "a": "C", "b": True}, {"t": row["description"], "b": True},
                            "", "", "", "", "", "", "", {"t": row.get("code") or "", "b": True, "a": "C"}])
        elif kind == "item":
            mb_rows.append([{"t": row.get("sno") or "", "a": "C", "b": True}, {"t": row["description"], "b": True}])
        elif kind == "heading":
            mb_rows.append(["", {"t": row["description"], "b": True, "i": True}])
        elif kind in ("subtotal", "total"):
            mb_rows.append(["", {"t": row["description"], "b": True}, "", "", "",
                            {"t": row["label"], "b": True}, "", "", {"t": _q(row["quantity"]), "b": True, "a": "R"},
                            {"t": row.get("uom") or "", "b": True}])
            mb_spans.append((5, r, 7, r))
        else:
            mb_rows.append(["", row["description"], {"t": row.get("uom") or "", "a": "C"},
                            {"t": _q(row.get("nos")), "a": "R"}, {"t": _q(row.get("nom")), "a": "R"},
                            {"t": _q(row.get("length")), "a": "R"}, {"t": _q(row.get("width")), "a": "R"},
                            {"t": _q(row.get("height")), "a": "R"},
                            {"t": ("-" if row["quantity"] < 0 else "") + form_pdf.inr(abs(row["quantity"]), 3), "a": "R"},
                            row.get("remarks") or ""])
    if len(mb_rows) == 1:
        mb_rows.append(["", "Nothing measured is pinned to this bill."])
    blocks += [{"type": "banner", "logo": c["company"].get("logo_url"), "lines": m["banner"]},
               {"type": "grid", "widths": [110, 72], "rows": [list(x) for x in m["meta"]], "size": "small"},
               {"type": "grid", "widths": W10, "rows": mb_rows, "spans": mb_spans, "head": 1, "size": "small"},
               sigs(m["signatures"])]
    watermark = {"DRAFT": "DRAFT - NOT CERTIFIED", "SUBMITTED": "SUBMITTED - NOT YET CERTIFIED",
                 "CANCELLED": "CANCELLED"}.get(b["status"], "")
    company = c["company"]
    return {"title": "Sub Contractor Bill %s" % b["number"], "author": company["name"], "watermark": watermark,
            "blocks": blocks, "footer": "%s  |  %s  |  RA Bill %02d  |  Printed %s" % (
                b["number"], company["name"], b.get("sequence") or 1, datetime.now().strftime("%d/%m/%Y %H:%M"))}


def statement_form_spec(client, party_name, party_label, s, date_from="", date_to="", db=None):
    """A party's statement of account, in the same form."""
    card = {}
    if db is not None:
        company = letterhead(db, client)
        card = party_card(db, client.id, party_name)
    else:
        company = {"name": client.company_name or "", "address": client.address or "", "gstin": client.gstin or "",
                   "pan": "", "state": _state_line(client.gstin), "logo_url": client.logo_url or ""}
    fi = form_pdf.inr
    rows = [[form_pdf.date_text(r.get("date")), r.get("kind") or "", r.get("number") or "",
             r.get("against") or r.get("reference") or "", fi(r["billed"]) if r.get("billed") else "",
             fi(r.get("paid", r.get("moved", 0))) if r.get("paid", r.get("moved")) else "", fi(r.get("balance"))]
            for r in s.get("rows") or []]
    closing = s.get("closing") or 0
    blocks = [
        {"type": "header", "company": company, "title": "STATEMENT OF ACCOUNT",
         "facts": [("Party", party_name), ("From", form_pdf.date_text(date_from) or "Beginning"),
                   ("To", form_pdf.date_text(date_to) or datetime.now().strftime("%d/%m/%Y")),
                   ("Printed", datetime.now().strftime("%d/%m/%Y"))]},
        {"type": "party", "label": party_label, "name": party_name, "address": card.get("address") or "",
         "facts": party_facts(card.get("gstin"), card.get("pan"), card.get("state"))},
        {"type": "pairs", "rows": [("Opening balance", fi(s.get("opening") or 0))], "label_width": 42},
        {"type": "table", "columns": [("Date", 18, "C"), ("Entry", 34, "L"), ("Number", 30, "L"), ("Against / Ref", 30, "L"),
                                      ("Billed", 23, "R"), ("Paid", 23, "R"), ("Balance", 24, "R")],
         "rows": rows, "totals": [("CLOSING BALANCE %s" % ("DUE TO YOU" if closing >= 0 else "DUE FROM YOU"),
                                   fi(abs(closing)), True)]},
        {"type": "words", "label": "Rupees", "text": _words(abs(closing))},
        {"type": "text", "style": "small", "text": "Please check this statement and tell us within fifteen days of any "
                                                   "difference; after that it is taken as agreed."},
    ]
    return {"title": "Statement - %s" % party_name, "author": company["name"], "blocks": blocks,
            "footer": "Statement of account  |  %s  |  %s" % (party_name, company["name"])}


def _cell_text(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else ""
    if isinstance(v, float):
        return form_pdf.inr(v) if v != int(v) or abs(v) >= 1000 else form_pdf.inr(v, 0 if v == int(v) else 2)
    if isinstance(v, int):
        return form_pdf.inr(v, 0) if abs(v) >= 1000 else str(v)
    text = str(v)
    # Stored ISO so they sort; printed as dates are read here.
    if re.match(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?$", text):
        return form_pdf.date_text(text[:10]) + (text[10:16] if len(text) > 10 else "")
    return text


def sheet_report_spec(headers, rows, filename, preamble=None, closing=None, client=None):
    """A workbook's rows as a ruled report."""
    pre = [list(r) for r in (preamble or []) if r and any(str(x).strip() for x in r)]
    title = str(pre[0][0]).strip() if pre else re.sub(r"[_\-]+", " ", filename.rsplit(".", 1)[0]).upper()
    facts, notes = [], []
    for r in pre[1:] if pre else []:
        cells = [c for c in r if str(c).strip() != ""]
        if len(cells) == 1:
            notes.append(str(cells[0]))
        else:
            for i in range(0, len(cells) - 1, 2):
                facts.append((str(cells[i]), _cell_text(cells[i + 1])))
    # The preamble often names the company beside the title; the header says it already.
    of = str(pre[0][1]).strip() if pre and len(pre[0]) > 1 else ""
    if of and not (client is not None and of == (client.company_name or "")):
        facts.insert(0, ("Of", of))
    body = [[_cell_text(v) for v in r] for r in rows]
    n = len(headers)
    # Each column as wide as what it holds, within reason.
    pref = []
    for i, h in enumerate(headers):
        longest = max([len(str(h))] + [len(r[i]) for r in body[:300] if i < len(r)])
        pref.append(max(6, min(longest, 46)))
    numeric = [all((not r[i]) or re.match(r"^[\(\-]?[\d,]+(\.\d+)?\)?%?$", r[i]) for r in body[:300] if i < len(r))
               for i in range(n)]
    landscape = n > 7 or sum(pref) > 110
    columns = [(str(h), p, "R" if numeric[i] and body else "L") for i, (h, p) in enumerate(zip(headers, pref))]
    foot = []
    for r in closing or []:
        if len([c for c in r if str(c).strip() != ""]) >= 2:
            foot.append([_cell_text(c) for c in list(r)[:n]] + [""] * max(0, n - len(r)))
    company = {}
    if client is not None:
        with SessionLocal() as own:
            company = letterhead(own, client)
    head = {"type": "header", "company": company, "title": title[:40],
            "facts": (facts[:5] or [("Printed", datetime.now().strftime("%d/%m/%Y"))])}
    blocks = [head]
    if len(facts) > 5:
        blocks.append({"type": "pairs", "cols": 2, "rows": facts[5:]})
    for note in notes:
        blocks.append({"type": "text", "style": "small", "text": note})
    blocks.append({"type": "table", "columns": columns, "rows": body, "foot": foot})
    return {"title": title, "author": company.get("name", ""), "landscape": landscape, "blocks": blocks,
            "footer": "%s  |  %s  |  Printed %s" % (title.title(), company.get("name", ""),
                                                    datetime.now().strftime("%d/%m/%Y %H:%M"))}


def _pre(client, title, *facts):
    rows = [(title, client.company_name or ""), ("As at", date.today().isoformat())]
    rows += [f for f in facts if f]
    return rows + [()]


def _job_line(db, job_id):
    j = db.query(models.DBJob).filter(models.DBJob.id == job_id).first() if job_id else None
    return (("%s %s" % (j.number or "", j.name or "")).strip() if j else ""), ((j.site_address or "") if j else "")


def _field_doc(db, client, title, facts, blocks, signatures, footer_no, watermark=""):
    blocks = [{"type": "header", "company": _company_of(db, client), "title": title, "facts": facts}] + blocks
    if signatures:
        blocks.append({"type": "signatures", "boxes": signatures})
    return {"title": "%s %s" % (title.title(), footer_no), "author": client.company_name or "", "watermark": watermark,
            "blocks": blocks, "footer": "%s  |  %s  |  Printed %s" % (footer_no, client.company_name or "",
                                                                      datetime.now().strftime("%d/%m/%Y %H:%M"))}


def registration_form_spec(db, client, con):
    f = registration_form_data(db, client, con)
    rows, spans, shade = [], [], []

    def band(text):
        rows.append([{"t": text, "b": True}, ""])
        spans.append((0, len(rows) - 1, 1, len(rows) - 1))
        shade.append(len(rows) - 1)

    rows.append([{"t": "VENDOR CODE:", "b": True}, {"t": f["vendor_code"], "b": True}])
    band("1. Subcontractor Personal Details")
    rows += [[{"t": k, "b": True}, v] for k, v in f["personal"]]
    band("2. Bank details")
    rows += [[{"t": k, "b": True}, v] for k, v in f["bank"]]
    band("3.Documents Required")
    rows += [[label, {"t": "Received" if got else "", "a": "C"}] for label, got in f["documents"]]
    decl = [{"type": "text", "text": "Declaration:", "style": "bold"}] + \
        [{"type": "text", "text": line} for line in f["declaration"]]
    if f["declaration_signed"]:
        decl.append({"type": "text", "style": "small", "text": "Declaration signed by the sub contractor."})
    approved = "APPROVED" == f["status"]
    boxes = [("Authorized Signature", ("%s%s" % (f["approved_by"], (" - " + form_pdf.date_text(f["approved_at"][:10]))
                                               if f["approved_at"] else "")) if approved else ""),
             ("Contractor Signature", f["name"])]
    return {"title": "Sub Contractor Registration %s" % f["vendor_code"], "author": f["company"],
            "watermark": {"PENDING": "AWAITING APPROVAL", "REJECTED": "SENT BACK"}.get(f["status"], ""),
            "blocks": [{"type": "banner", "logo": letterhead(db, client).get("logo_url"), "lines": [(f["company"], "banner"),
                                                    ("SUB CONTRACTOR REGISTRATION FORM", "band"),
                                                    ("PROJECT: %s" % f["project"], "centrebold")]},
                       {"type": "grid", "widths": [70, 112], "rows": rows, "spans": spans, "shade": shade}]
                      + decl + [{"type": "signatures", "boxes": boxes}],
            "footer": "%s  |  Sub Contractor Registration Form  |  Printed %s" % (
                f["vendor_code"], datetime.now().strftime("%d/%m/%Y %H:%M"))}


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.documents.letterhead import (
    _company_of,
    _sig_line,
    _state_line,
    company_terms,
    customer_card,
    doc_signatories,
    fill_terms,
    letterhead,
    our_party,
    party_card,
    party_facts,
    sign_boxes,
)
from app.services.client_billing import _words, dimensions_for, order_variations, ra_bill_dict
from app.services.crm import norm_name
from app.services.hr import employee_name
from app.services.invoicing import active_irn, einvoice_buyer
from app.services.procurement import purchase_order_to_dict
from app.services.subcontract_billing import (
    sub_bill_chain_rows,
    sub_bill_dict,
    sub_bill_signed,
    sub_bill_step_name,
)
from app.services.subcontract_orders import registration_form_data, wo_dict
