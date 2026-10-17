# P4 - Control (transfers, stock counts, adjustments, scrap)

Migration `store_005_control`: `REVISION` in the slice's model file. This repo has no Alembic, so the name only labels the change.

Backend: `models/store_control.py`, `services/store_control.py`, `routers/store_control.py`, `documents/store/control_forms.py`.
Frontend: `features/store/control/`. Tests: `backend/tests/store/test_control.py`.
Tables (via `create_all`): `store_transfer(_line)`, `store_count(_line)`, `store_adjustment(_line)`, `store_scrap(_line)`, `store_control_log`.
Lifecycle for all: DRAFT -> SUBMITTED -> APPROVED -> POSTED, or CANCELLED; only a draft is edited; every change is logged with user and time.
Rights: `store.control.view/create/approve/post/cancel` (create = draft, edit, submit), plus `approve_high_value` and `reveal_count`.

## Transfer (TRF, ledger ref `TRANSFER`)
POST takes the stock out of the sender (`TRANSFER_OUT` at its average) and the transfer is **in transit** until the receiving store confirms
(`POST /transfers/{id}/receive`, needs `store.control.post` and access to the receiving store). What arrives goes in at the rate it left at
(`TRANSFER_IN`); anything short goes back to the sender (`TRANSFER_IN` there). Receive is once only. Cancelling reverses everything posted so far
(refused with 409, nothing changed, if the receiving store has used the stock). A transfer between stores of different projects is *inter-project*.
Approving an inter-project transfer, or one worth Rs 1,00,000 or more, needs `approve_high_value` (limit `HIGH_VALUE_LIMIT` in the service).

## Stock count (CNT, ref `COUNT`)
Creating a count **freezes the store** (`freeze_store`) and snapshots the books (all items held, or the items named). The counter enters
`counted_qty` (PUT) without seeing the books unless they hold `reveal_count`; once the count is approved the result is visible to all. Submit needs
every line counted. Approving differences worth the limit or more needs `approve_high_value`. POST unfreezes and posts each difference
(`ADJUST_IN` at the average, `ADJUST_OUT`). Cancelling a draft count unfreezes; cancelling a posted one reverses the adjustments.

## Adjustment (ADJ, ref `ADJUST`)
Kinds: `STOCK` (lines IN or OUT; an IN uses the given rate or the store average), `WASTAGE` (`WASTAGE_OUT`, must be charged to a project - the store's
by default - or a cost head) and `WRITEOFF` (lines are open write-off requests from the outward slice; posting calls `close_writeoff_request`; no stock
moves because the material left the store when it was issued; a posted write-off cannot be cancelled). A reason is required.

## Scrap (SCR, ref `SCRAP`)
`SCRAP_OUT` at book value, with `realised_value` per line (what it fetched), buyer and reason, charged to the store's project unless given.

## Cross-slice (frozen signatures)
`get_in_transit(db, project_id=None)`, `get_count_variances(db, store_id, from_date, to_date)` (posted counts, differences only),
`get_scrap_realisation(db, project_id, from_date, to_date)` (posted scrap). This slice calls `store_outward.list_writeoff_requests` /
`close_writeoff_request`.

## Routes `/api/store/control`
`/transfers` (+ `/{id}/receive`), `/counts`, `/adjustments`, `/scrap`: each `GET` list, `POST`, `GET|PUT /{id}`, `POST /{id}/{submit|approve|post|cancel}`,
`GET /{id}/pdf`; also `GET /in-transit`, `GET /writeoff-requests`. `GET /api/store/control` still returns the skeleton stub.
