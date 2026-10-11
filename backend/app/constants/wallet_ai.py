"""The fixed lists, limits and statuses for wallet ai."""
import os


# The catalogue of things that can be charged for. Prices are set by the
# operator; these are only the starting values and the wording tenants see.
DEFAULT_PRICING = [
    ("invoice_send",      "Send invoice by email",   "invoicing", 5,  50,
     "Charged when an invoice is emailed to a customer."),
    ("invoice_whatsapp",  "Send invoice on WhatsApp", "invoicing", 15, 0,
     "Charged per WhatsApp message delivered."),
    ("quote_send",        "Send quote by email",     "invoicing", 5,  50,
     "Charged when a quote is emailed to a customer."),
    ("payslip_send",      "Send payslip by email",   "hr",        5,  50,
     "Charged when a payslip is emailed to an employee."),
    ("payroll_run",       "Payroll run (per payslip)", "hr",      10, 10,
     "Charged for each payslip generated in a payroll run."),
    ("candidate_email",   "Email a candidate",       "hr",        5,  25,
     "Charged per interview invitation, offer or rejection sent."),
    ("ai_resume_screen",  "AI resume screening",     "hr",        40, 5,
     "Charged per candidate screened by AI."),
    ("ai_onboarding",     "AI onboarding checklist", "hr",        30, 5,
     "Charged per generated onboarding plan."),
    ("ai_email_draft",    "AI email drafting",       "invoicing", 25, 10,
     "Charged per AI-written email."),
    ("ai_attendance_summary", "AI attendance summary", "hr",      30, 5,
     "Charged per attendance summary generated."),
    ("ai_assistant",      "AI assistant question",   "platform",  10, 30,
     "Charged per question answered by the in-app assistant."),
    ("ai_insights",       "AI business insights",    "platform",  25, 10,
     "Charged per dashboard insight generated."),
    ("ai_job_description","AI job description",      "hr",        30, 5,
     "Charged per job advert drafted."),
    ("ai_interview_questions", "AI interview questions", "hr",    30, 5,
     "Charged per interview question set."),
    ("ai_describe_item",  "AI line item wording",    "invoicing", 10, 20,
     "Charged per invoice description rewritten."),
    ("ai_brand_theme",    "AI branding theme",       "invoicing", 25, 5,
     "Charged per invoice theme designed."),
    ("ai_hard_copy_check", "AI hard-copy bill check", "subcontracts", 0, 0,
     "Charged per scanned contractor bill read and compared. Priced at zero until set."),
    ("ai_bill_review",    "AI contractor bill review", "subcontracts", 0, 0,
     "Charged per written bill summary. Priced at zero until set."),
    ("ai_contractor_brief", "AI contractor brief",  "subcontracts", 0, 0,
     "Charged per contractor standing summary. Priced at zero until set."),
    ("ai_po_review",      "AI purchase order review", "purchasing", 0, 0,
     "Charged per written purchase order review. Priced at zero until set."),
    ("ai_po_email",       "AI supplier email draft", "purchasing", 0, 0,
     "Charged per supplier email drafted. Priced at zero until set."),
    ("ai_quote_recommend", "AI quote recommendation", "purchasing", 0, 0,
     "Charged per recommendation on an enquiry. Priced at zero until set."),
    ("ai_quote_read",     "AI quote reader",        "purchasing", 0, 0,
     "Charged per supplier quote read. Priced at zero until set."),
    ("ai_measurement_analysis", "AI measurement analysis", "subcontracts", 0, 0,
     "Charged per measurement book summary. Priced at zero until set."),
    ("ai_measurement_read", "AI measurement sheet reader", "subcontracts", 0, 0,
     "Charged per measurement sheet read. Priced at zero until set."),
    ("ai_measurement_ask", "AI measurement book question", "subcontracts", 0, 0,
     "Charged per question answered about a measurement book. Priced at zero until set."),
    ("ai_document_read",  "AI compliance paper reader", "subcontracts", 0, 0,
     "Charged per licence or insurance paper read. Priced at zero until set."),
]

# PAYMENT GATEWAYS
# Top-ups go through Stripe, Razorpay or PayPal. Keys come from the
# environment; with none set the endpoints say so plainly rather than
# pretending to work.
#
# Crediting only ever happens from a verified provider callback, never from
# the browser. A client-side "payment succeeded" is not proof of payment.
TOPUP_MIN_MAJOR = float(os.getenv("TOPUP_MIN", "5"))
TOPUP_MAX_MAJOR = float(os.getenv("TOPUP_MAX", "5000"))

ASSISTANT_SYSTEM = (
    "You are the assistant inside a combined invoicing and HR platform. "
    "Answer using ONLY the CONTEXT below, which contains this company's real, current data. "
    "Never invent numbers, names, dates or totals. If the answer is not in the context, "
    "say plainly that you do not have that information and name the screen where the user can find it "
    "(Invoices, Employees, Leave, Payroll, Recruitment, Wallet). "
    "Be brief and concrete: two or three sentences, or a short list. Quote figures exactly as given. "
    "Do not give legal, tax or financial advice; suggest a qualified professional instead."
)
