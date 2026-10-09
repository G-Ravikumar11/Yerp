# Ai_service

All AI work for the app lives in this folder. One file per function; the shared plumbing is in `config.py`,
`llm_client.py` and `guard.py`.

## Adding your keys

Put these in `backend/.env` for your own machine, and in Railway → Variables for the live site:

| Variable | What it does |
| --- | --- |
| `GROQ_API_KEY` | The default for every text task. |
| `ANTHROPIC_API_KEY` | Claude. Used only where a picture or PDF has to be read (scanned bills, quote files), or for text if `AI_PROVIDER=claude`. |
| `AI_PROVIDER` | `groq` (default) or `claude`: who answers text tasks when both keys are set. |
| `GROQ_MODEL` | Default `llama-3.3-70b-versatile`. |
| `AI_ENABLED` | `1` (default) or `0` to turn every function here off at once. |
| `AI_MODEL_SMART` | Default `claude-sonnet-5-5`: reading documents. |
| `AI_MODEL_FAST` | Default `claude-haiku-5-5`: short summaries. |

With no key, the plain checks still work (bill flags, contractor standing); only the AI parts say they are not set up.

## What is here

| File | Endpoint | What it does |
| --- | --- | --- |
| `status.py` | `GET /api/ai/subcontracts/status` | Is AI on and keyed? |
| `hard_copy_check.py` | `POST /api/ai/subcontracts/bills/{id}/hard-copy-check` | Reads the scanned hard copy and compares its figures with the bill. The model reads; plain code compares. |
| `bill_review.py` | `GET /api/ai/subcontracts/bills/{id}/review` | Plain-code flags (quantity beyond the order, lapsed papers, no hard copy, unusually large bill, open back-charges) plus a short written summary. |
| `contractor_brief.py` | `GET /api/ai/subcontracts/contractors/{id}/brief` | A contractor's standing and a short paragraph for deciding on the next order. |
| `po_review.py` | `GET /api/ai/purchase-orders/{id}/review` | Flags (price up on the last paid, no GSTIN, possible duplicate, overdue date, billed above the order) plus a short summary. |
| `po_supplier_email.py` | `POST /api/ai/purchase-orders/{id}/draft-email` | A draft email to the supplier; a plain template when AI is off. Nothing is sent. |
| `quote_comparison.py` | `GET /api/ai/rfqs/{id}/recommend` | Flags on the quotes and a recommendation with reasons. The buyer awards. |
| `quote_reader.py` | `POST /api/ai/rfqs/{id}/read-quote` | Reads a quote (pasted text via Groq; PDF or photo via Claude) into quote-form figures, matched to the enquiry's lines. Saves nothing. |

## Rules

- The model suggests and shows its reasoning; a person decides. Nothing here approves, certifies, pays or deletes.
- Every call goes through `guard.run_feature`: it checks the wallet, charges only if the model produced something, and
  writes the audit log. Prices are in Settings → wallet pricing (`ai_hard_copy_check`, `ai_bill_review`,
  `ai_contractor_brief`, `ai_po_review`, `ai_po_email`, `ai_quote_recommend`, `ai_quote_read`); they start at zero.
- A feature file never talks to a provider directly. Tests replace `llm_client.ask` / `ask_json` and run with no network.
