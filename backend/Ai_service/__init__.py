"""Everything that calls an AI model lives here, one file per function.

    config.py            keys and switches, read from the environment
    llm_client.py        the only place a model is called (Groq for text by default; Claude for pictures and PDFs)
    guard.py             what every endpoint does around a call: wallet, charge on success, audit
    status.py            is AI on and keyed?
    hard_copy_check.py   read a scanned contractor bill and compare it with ours
    bill_review.py       flags and a short summary for whoever certifies a bill
    contractor_brief.py  a contractor's standing, for deciding on the next order
    po_review.py         flags and a summary for a purchase order before it goes out
    po_supplier_email.py a draft email to the supplier for a purchase order
    quote_comparison.py  a recommendation on an enquiry's supplier quotes
    quote_reader.py      read a supplier's quote file or pasted text into the quote form

To add a function: write a new file here with its own `router = APIRouter()`, call `llm_client.ask` / `ask_json`
inside `guard.run_feature`, and add the module to FEATURES below. Nothing else in the app needs to change.
The model reads and writes words; anything that changes money, approves or deletes is done by a person.
"""
from Ai_service import (bill_review, contractor_brief, hard_copy_check, po_review, po_supplier_email, quote_comparison,
                        quote_reader, status)

FEATURES = (status, hard_copy_check, bill_review, contractor_brief, po_review, po_supplier_email, quote_comparison, quote_reader)

routers = [module.router for module in FEATURES]
