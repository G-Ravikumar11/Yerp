# P4 - Control (transfers, stock counts, adjustments, scrap)

Migration `store_005_control`: `REVISION` in the slice's model file. This repo has no Alembic, so the name only labels the change.

Backend: `models/store_control.py`, `services/store_control.py`, `routers/store_control.py`, `documents/store/control_forms.py`.
Frontend: `features/store/control/`. Tests: `backend/tests/store/test_control.py`.
Tables (via `create_all`): `store_transfer(_line)`, `store_count(_line)`, `store_adjustment(_line)`, `store_scrap(_line)`, `store_control_log`.
Lifecycle for all: DRAFT -> SUBMITTED -> APPROVED -> POSTED, or CANCELLED; only a draft is edited; every change is logged with user and time.
Rights: `store.control.view/create/approve/post/cancel` (create = draft, edit, submit), plus `approve_high_value` and `reveal_count`.

## Transfer (TRF, ledger ref `TRANSFER`)
Flow: request (draft, submit) -> approve -> dispatch (post) -> receive. Any store to any store (central to site, site to site, site to yard).
Dispatch details on the document: vehicle, driver, challan number and date.
- **Dispatch** (POST) takes the stock out of the sender (`TRANSFER_OUT` at its average rate). The lines then sit on the **in-transit register**
  (`GET /in-transit`, `get_in_transit`) until the receiving store confirms.
- **Receive** (`POST /transfers/{id}/receive`, needs `store.control.post` and access to the receiving store; once only): what arrives goes in at the same rate
  (`TRANSFER_IN`). Whatever did not arrive is a **loss in transit**, given per line with a reason (`CEMENT_SET, BREAKAGE, RUSTING, EXPIRY, PILFERAGE`).
  **Received + loss must equal dispatched** for every line (400 otherwise). A loss leaves the transfer's `loss_status` PENDING and the lost quantity on the
  in-transit register.
- **Approve the loss** (`POST /transfers/{id}/approve-loss`, `store.control.approve`; `approve_high_value` at Rs 1,00,000 or more): posts it as `WASTAGE_OUT`
  on the transfer document (through the receiving store: `TRANSFER_IN` then `WASTAGE_OUT`, so its stock is unchanged and the cost lands on its project, or on
  OVERHEAD if it has none).
- **Inter-project**: stores on different projects make an inter-project cost transfer, flagged on the document and in the in-transit register
  (`InTransitLine.inter_project`) for the reports slice. Approving one needs `approve_high_value`, as does any transfer worth the limit or more.
- Cancelling reverses everything posted (refused with 409, nothing changed, if the receiving store has used the stock).

## Stock count (CNT, ref `COUNT`)
- Create for a store, optionally limited to **item categories** and/or a **bin** (the bin being counted is printed on the sheet; stock is not tracked per bin,
  so a bin does not pick the items - name them, or limit by category). Creating **freezes the store** (`freeze_store`) and snapshots the books.
- **Blind** by default: counters get no system quantity or variance unless they hold `store.control.reveal_count`; everyone sees the result once approved.
- **Recounts**: a reviewer (`store.control.approve`) sends chosen lines of a submitted count back (`POST /counts/{id}/recount`, reason required): the first count is
  kept on the line, the sheet returns to DRAFT, and the recounted figure is the one posted. The store stays frozen.
- **Variance**: quantity and value per line and net (`GET /counts/{id}`, `get_count_variances`, printable variance statement).
- **Approval threshold**: differences worth Rs 1,00,000 or more need `approve_high_value`.
- POST posts `ADJUST_IN` (at the average) / `ADJUST_OUT` and **unfreezes** the store. Abandoning (cancelling) a count also unfreezes it; cancelling a posted count
  reverses the adjustments.

## Adjustment (ADJ, ref `ADJUST`)
- `STOCK` - ad-hoc correction; reason code `DATA_CORRECTION, FOUND, LOST, THEFT, CONVERSION`.
- `WASTAGE` / `WRITEOFF` - wastage and damage write-off (`WASTAGE_OUT`, charged to a project or cost head) and the write-off of material lost on issue (closes the
  outward slice's write-off requests; no stock moves because it left the store when issued; cannot be cancelled); reason code `CEMENT_SET, BREAKAGE, RUSTING, EXPIRY, PILFERAGE`.
- Every adjustment needs a **remark** and an **attachment reference** (the supporting paper), and a reason code. Worth Rs 1,00,000 or more needs `approve_high_value`.

## Scrap (SCR, ref `SCRAP`)
Lines carry a **class** (`STEEL_CUT_PIECES, EMPTY_CEMENT_BAGS, DAMAGED_SHUTTERING, OTHER`) and the amount realised. The note records the **buyer** and the **gate pass number**
(both needed to submit). POST takes `SCRAP_OUT` at book value; the **realised-against-book difference** is shown per line and in total.

## Reorder alerts (export only)
`GET /reorder-alerts[?store_id=][&format=xlsx]`: per store, items at or below their reorder level (from `store_item_settings`), with
**suggested = maximum - (on hand + pending on purchase orders)**. Pending is read through the inward slice's `get_po_receipt_summary` over approved orders (a store on a
project counts that project's orders and those with no project). No purchase document is created.

## Printables
Transfer note / delivery challan, count sheet (blind until approved), variance statement (`/counts/{id}/pdf?form=variance`), adjustment voucher,
write-off note (`/adjustments/{id}/pdf?form=writeoff`, the default for wastage and write-offs), scrap sale note.

## Cross-slice (frozen signatures)
`get_in_transit(db, project_id=None)`, `get_count_variances(db, store_id, from_date, to_date)` (posted counts, differences only),
`get_scrap_realisation(db, project_id, from_date, to_date)` (posted scrap). This slice calls `store_outward.list_writeoff_requests` /
`close_writeoff_request`.

## Routes `/api/store/control`
`/transfers` (+ `/{id}/receive`), `/counts`, `/adjustments`, `/scrap`: each `GET` list, `POST`, `GET|PUT /{id}`, `POST /{id}/{submit|approve|post|cancel}`,
`GET /{id}/pdf`; also `POST /transfers/{id}/approve-loss`, `POST /counts/{id}/recount`, `GET /in-transit`, `GET /writeoff-requests`, `GET /reorder-alerts`, `GET /meta`. `GET /api/store/control` still returns the skeleton stub.
