# P2 - Inward (GRN, quality check, returns to supplier)

Migration `store_003_inward`: `REVISION` in the slice's model file. This repo has no Alembic, so the name only labels the change.

Backend: `models/store_inward.py`, `services/store_inward.py`, `routers/store_inward.py`, `documents/store/inward_forms.py`.
Frontend: `features/store/inward/`. Tests: `backend/tests/store/test_inward.py`.
Tables (made by `create_all`): `store_grn`, `store_grn_line`, `store_purchase_return`, `store_purchase_return_line`, `store_inward_log`.

## Lifecycle
DRAFT -> SUBMITTED -> APPROVED -> POSTED, or CANCELLED. Only a draft is edited. Every change is written to `store_inward_log`
(who, when, note). Stock moves only on POST; cancelling a POSTED document calls `reverse_document` and is refused (409, nothing
changed) if the stock has since been used.

| Action | Right |
|---|---|
| draft, edit, submit | `store.inward.create` |
| approve, record quality check | `store.inward.approve` |
| post | `store.inward.post` |
| cancel (needs a reason) | `store.inward.cancel` |
| read, print | `store.inward.view` |

## GRN
- Against an approved purchase order (`po_id`, lines carry `po_line_id`) or stand-alone (item + rate typed).
- Quantities are typed in any unit the item has; stored in the base unit (`received_qty`) with the typed unit kept. Rate is typed per
  entered unit and stored per base unit.
- Items with `qc_required` start with accepted = 0; the quality check (`POST /grn/{id}/qc`, accepted + rejected = received, base
  unit) must be recorded on every such line before approval. **Only the accepted quantity is posted** (`GRN_IN` at the line rate,
  `ref_doc_type="GRN"`, `ref_line_id` = line id). A GRN with nothing accepted cannot be posted.
- Over-receipt: posted receipts plus this GRN may not exceed the PO line plus the item's `over_receipt_tolerance_pct` (checked at
  submit and post).

## Purchase return (PRN)
Sends accepted stock back (`PURCHASE_RETURN_OUT`, valued at the store's average, `ref_doc_type="PRN"`). Against a posted GRN it may
not return more than that line accepted less earlier non-cancelled returns. A GRN with a live return cannot be cancelled.

## Routes `/api/store/inward`
`GET /pos`, `GET /pos/{id}/lines`; `GET|POST /grn`, `GET|PUT /grn/{id}`, `POST /grn/{id}/qc`, `POST /grn/{id}/{submit|approve|post|cancel}`,
`GET /grn/{id}/returnable`, `GET /grn/{id}/pdf`; `GET|POST /returns`, `GET|PUT /returns/{id}`, `POST /returns/{id}/{action}`,
`GET /returns/{id}/pdf`. Lists take `store_id, status, q, from_date, to_date, limit, offset` and show only the person's stores.
`GET /api/store/inward` still returns the skeleton stub.

## Cross-slice
`store_inward.get_po_receipt_summary(db, po_id)` returns `PoLineReceipt` per PO line from posted GRNs (ordered/received/accepted/
rejected in the item's base unit; pending = ordered - accepted, so rejected goods stay pending).

## Printable forms
`documents/store/inward_forms.py`: `grn_form_spec`, `prn_form_spec` (the repo's ruled-box PDF layout, DRAFT/CANCELLED watermark).
