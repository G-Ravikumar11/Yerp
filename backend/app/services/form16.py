"""Form 16 for a financial year, from the payslips: Part A (the tax deducted, quarter by quarter) and Part B (how the
year's tax on salary is worked out under the new regime).

This is the employer's own statement. The certificate the Income Tax Department recognises for Part A is the one
downloaded from TRACES, which carries the challan and BIN details of each deposit; those are not held here, so the
statement says so on its face. Part B is the employer's to issue, and is worked out the way the payslips were.

The company's TAN and PAN are read from Settings (company_tan, company_pan) and left blank when not yet set.
"""
from app import models
from app.core.currency import amount_in_words, money
from app.documents.wo_pdf import inr          # Indian grouping without the rupee sign: the PDF font has no glyph for it
from app.services import income_tax as it

QUARTERS = (("Q1", "April to June", (4, 5, 6)), ("Q2", "July to September", (7, 8, 9)),
            ("Q3", "October to December", (10, 11, 12)), ("Q4", "January to March", (1, 2, 3)))
NOT_TRACES = ("Part A here is the employer's statement of tax deducted from the payslips. The certificate recognised "
              "for Part A is the one downloaded from TRACES, which also shows each deposit's challan details.")


def parse_fy(value):
    """'2025-26' or '2025' -> 2025."""
    text = str(value or "").strip()
    try:
        return int(text[:4])
    except ValueError:
        raise ValueError("Give the financial year as 2025-26.")


def data(db, client, emp, start_year, payslips=None):
    """Everything on the form, as figures. `payslips` limits it to the ones given (the employee's own view)."""
    fy_start, fy_end = it.fy_bounds(start_year)
    P = models.DBPayslip
    slips = payslips if payslips is not None else db.query(P).filter(
        P.client_id == client.id, P.employee_id == emp.id, P.status != "Void",
        P.period_end >= fy_start.isoformat(), P.period_end <= fy_end.isoformat()).order_by(P.period_end).all()
    quarters = []
    for code, months_text, months in QUARTERS:
        q = [p for p in slips if int(p.period_end[5:7]) in months]
        quarters.append({"quarter": code, "months": months_text, "paid": money(sum(p.gross_pay or 0 for p in q)),
                         "tds": money(sum(p.tax_amount or 0 for p in q))})
    gross = money(sum(p.gross_pay or 0 for p in slips))
    tds = money(sum(p.tax_amount or 0 for p in slips))
    tax = it.annual_tax(gross, start_year)
    settings = {k: v for k, v in db.query(models.DBSettings.key, models.DBSettings.value).filter(
        models.DBSettings.client_id == client.id,
        models.DBSettings.key.in_(["company_name", "company_address", "company_tan", "company_pan"])).all()}
    return {
        "fy": it.fy_label(start_year), "assessment_year": it.fy_label(start_year + 1),
        "period": (max(fy_start.isoformat(), emp.start_date or fy_start.isoformat()),
                   min(fy_end.isoformat(), emp.end_date or fy_end.isoformat())),
        "employer": {"name": settings.get("company_name") or client.company_name or "",
                     "address": settings.get("company_address") or client.address or "",
                     "tan": settings.get("company_tan", ""), "pan": settings.get("company_pan", "")},
        "employee": {"name": ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip(), "pan": emp.pan_no or "",
                     "designation": emp.job_title or "", "employee_id": emp.employee_id or ""},
        "quarters": quarters, "payslips": len(slips), "gross": gross, "tds": tds, "tax": tax,
        "balance": money(tax["total_tax"] - tds),
    }


def pdf_spec(d):
    """The form for the PDF engine (documents.form_pdf)."""
    e, w, t = d["employer"], d["employee"], d["tax"]
    blocks = [
        {"type": "banner", "lines": [("FORM No. 16", "banner"), ("[See rule 31(1)(a)]", "centrebold"),
                                     ("Certificate under section 203 of the Income-tax Act for tax deducted at source on salary", "centrebold")]},
        {"type": "pairs", "cols": 2, "rows": [
            ("Employer", e["name"]), ("Employee", w["name"]),
            ("Employer's address", e["address"]), ("Designation", w["designation"]),
            ("TAN of the deductor", e["tan"] or "(not set in Settings)"), ("PAN of the employee", w["pan"] or "(not on record)"),
            ("PAN of the deductor", e["pan"] or "(not set in Settings)"), ("Employee number", w["employee_id"]),
            ("Financial year", d["fy"]), ("Assessment year", d["assessment_year"]),
            ("Period with the employer", "%s to %s" % d["period"]), ("Tax regime", "New regime (section 115BAC)"),
        ]},
        {"type": "band", "text": "PART A - Tax deducted at source, quarter by quarter"},
        {"type": "table", "columns": [("Quarter", 22, "L"), ("Months", 58, "L"), ("Amount paid / credited (Rs.)", 50, "R"), ("Tax deducted (Rs.)", 50, "R")],
         "rows": [[q["quarter"], q["months"], inr(q["paid"]), inr(q["tds"])] for q in d["quarters"]]
                 + [["Total", "", inr(d["gross"]), inr(d["tds"])]], "bold_rows": [4]},
        {"type": "text", "style": "small", "text": NOT_TRACES},
        {"type": "band", "text": "PART B - Details of salary paid and tax deducted"},
        {"type": "sums", "rows": [
            ("1. Gross salary (section 17(1))", inr(d["gross"]), False),
            ("2. Less: standard deduction (section 16(ia))", inr(t["standard_deduction"]), False),
            ("3. Income chargeable under the head Salaries", inr(t["taxable"]), True),
            ("4. Total taxable income (rounded, section 288A)", inr(t["taxable"]), True),
            ("5. Tax on total income", inr(t["slab_tax"]), False),
            ("6. Less: rebate under section 87A", inr(t["rebate_87a"]), False),
            ("7. Surcharge", inr(t["surcharge"]), False),
            ("8. Health and education cess at 4%", inr(t["cess"]), False),
            ("9. Tax payable (rounded, section 288B)", inr(t["total_tax"]), True),
            ("10. Tax deducted at source", inr(d["tds"]), False),
            ("11. %s" % ("Tax still payable" if d["balance"] >= 0 else "Tax deducted in excess (refundable)"), inr(abs(d["balance"])), True),
        ]},
        {"type": "words", "label": "Tax deducted, in words: Rupees", "text": amount_in_words(d["tds"])},
        {"type": "text", "style": "small", "text": "Professional tax is not deducted against salary under the new regime. "
                                                  "Worked out from %d payslip(s) of the year." % d["payslips"]},
        {"type": "signatures", "boxes": [("Signature of the person responsible for deduction of tax", e["name"])]},
    ]
    return {"title": "Form 16 %s %s" % (w["name"], d["fy"]), "blocks": blocks, "footer": e["name"]}


def pdf_bytes(d):
    from app.documents import form_pdf
    return form_pdf.build_form_pdf(pdf_spec(d))
