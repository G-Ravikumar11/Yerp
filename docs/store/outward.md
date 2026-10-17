# P3 - Outward (requisitions, issues, returns, write-off requests)

Migration `store_004_outward`: `REVISION` in the slice's model file. This repo has no Alembic, so the name only labels the change.

Backend: `models/store_outward.py`, `services/store_outward.py`, `routers/store_outward.py`, `documents/store/outward_forms.py`.
Frontend: `features/store/outward/`. Tests: `backend/tests/store/test_outward.py`.
Tables (via `create_all`): `store_requisition(_line)`, `store_issue(_line)`, `store_issue_return(_line)`, `store_writeoff_request`, `store_outward_log`.

## Documents and lifecycle
| Document | Number | Moves stock? |
|---|---|---|
| Requisition (MRQ) | `MRQ/<store>/<fy>/n` | no - DRAFT -> SUBMITTED -> APPROVED (or CANCELLED) |
| Issue (ISSUE) | `ISSUE/...` | on POST: `ISSUE_OUT` (site) or `SUBCON_ISSUE_OUT` (subcontractor), valued at the store average |
| Issue return (RTN) | `RTN/...` | on POST: `ISSUE_RETURN_IN` / `SUBCON_RETURN_IN` at the rate the material left at |

Issues and returns: DRAFT -> SUBMITTED -> APPROVED -> POSTED, or CANCELLED; only a draft is edited; every change is in
`store_outward_log`. Cancelling a posted document calls `reverse_document` (409 with nothing changed if stock has since been used).
An issue with a live return cannot be cancelled; a requisition with a live issue cannot be cancelled.

Rights: create = draft/edit/submit, approve, post, cancel (all `store.outward.*`). An issue with **no requisition** is a direct
issue and also needs `store.outward.direct_issue`.

## Rules
- Material is charged to a project or a cost head (the store's project is the default). Work order must belong to the project, BOQ
  item to the work order's BOQ. The movement carries project / work order / BOQ item / cost head / subcontractor for cost reports.
- Against a requisition, an issue may not exceed what the requisition still allows (posted issues counted; re-checked on submit/post);
  costing is copied from the requisition unless given.
- Returnable items (category RETURNABLE or TOOL) must name a holder (EMPLOYEE / SUBCONTRACTOR / GANG); a subcontractor issue is
  held by the subcontractor. Outstanding = issued - returned - lost on posted returns.
- A return line has `qty` (back into stock) and `lost_qty` (needs a reason; posting raises an OPEN write-off request for P4).
- Subcontractor lines may be `chargeable` with a `recovery_rate` per base unit (the issue rate when left empty).

## Cross-slice (frozen signatures)
`get_subcon_issues(db, subcontractor_id, upto_date)`, `get_outstanding_returnables(db, project_id=None, store_id=None)`,
`list_writeoff_requests(db, status="OPEN")`, `close_writeoff_request(db, request_id, ref_doc_type, ref_doc_id, user_id)` (flushes,
caller commits; raises `StoreError` if not open).

## Routes `/api/store/outward`
`/options`, `/work-orders/{id}/boq`; `/requisitions`, `/issues`, `/returns` each with `GET` list, `POST`, `GET|PUT /{id}`,
`POST /{id}/{submit|approve|post|cancel}`, `GET /{id}/pdf`; `GET /issues/{id}/returnable`; `GET /outstanding`; `GET /writeoffs`.
`GET /api/store/outward` still returns the skeleton stub.
