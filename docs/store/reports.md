# P5 - Reports and integration

Migration `store_006_reports`: `REVISION` in the slice's model file. This repo has no Alembic, so the name only labels the change.

Backend: `models/store_reports.py`, `services/store_reports.py`, `services/store_integration.py`, `routers/store_reports.py`,
`documents/store/report_forms.py`. Frontend: `features/store/reports/`. Tests: `backend/tests/store/test_reports.py`
(includes the end-to-end run GRN -> transfer -> issue -> subcontractor issue -> return, checked against every report).
Tables (via `create_all`): `store_consumption_norm`, `store_recovery_link`. No existing module's code was changed.

## Reports - `GET /api/store/reports/run/{code}?format=json|xlsx|pdf&<params>`
Every report returns one table (`columns`, `rows`, `totals`; numbers as strings), so one screen, one Excel writer and one PDF writer serve all.
Staff see only their assigned stores; a named `store_id` they cannot reach is 403. `GET /catalog` lists the reports, `GET /summary` the home tiles.

| Code | Shows | Params |
|---|---|---|
| `stock-valuation` | stock and value per store/item, today or as on a past date (from the ledger) | `as_on, store_id, category` |
| `stock-movement` | opening / received / issued / closing for a period | `from, to` (required), `store_id` |
| `reorder` | items at or below reorder level, quantity to reach maximum | `store_id` |
| `slow-moving` | stock not issued for N days | `days` (90), `store_id` |
| `consumption` | material charged to a project net of returns and reversals, against BOQ norms | `project_id` (required), `from, to, group_by` (detail, cost_head, work_order, item) |
| `subcon-material` | issued / returned / recoverable per subcontractor (P3) | `subcontractor_id` (required), `to` |
| `po-pending` | purchase-order lines still to receive (P2) | `project_id` |
| `returnables` | returnables still out, holder, days late (P3) | `project_id` |
| `in-transit` | stock dispatched, not received (P4) | `project_id` |
| `count-variances` | differences found by counts (P4) | `store_id` (required), `from, to` |
| `scrap` | scrap book value vs realised (P4) | `project_id, from, to` |

Ledger rules: reports sum `qty_in - qty_out` and `value` signed by direction, never filter reversals out (see CONTRACT). Cost reports use
ISSUE_OUT, SUBCON_ISSUE_OUT, WASTAGE_OUT less ISSUE_RETURN_IN, SUBCON_RETURN_IN, so a return or a cancelled issue nets out.

## Norms and the theoretical requirement
`PUT /norms {boq_item_id, item_id, qty_per_unit, wastage_pct}` (`store.reports.create`), `GET /norms?boq_item_id=|work_order_id=`,
`DELETE /norms/{id}` (`store.reports.cancel`). `get_theoretical_requirement(db, boq_item_id, item_id)` = BOQ quantity x norm x (1 + wastage%),
to 3 decimals, `None` without a norm.

## Integration
- `get_project_material_cost(db, project_id, from_date, to_date)` (frozen signature) and `GET /integration/project-cost`.
- `POST /integration/subcon-recoveries/sync` (`store.reports.post`): turns chargeable lines of posted subcontractor issues (read through the outward slice's `get_subcon_issues` and the shared ledger, never its tables) into
  `material_recoveries` rows (the existing subcontract billing deducts them from the next bill) on the subcontractor's active order for the project.
  Net of posted returns; repeatable; refreshes quantity/amount after returns; withdraws rows for cancelled issues; **never touches a row a bill has taken**;
  reports issues with no active order under `skipped`.

## Printable
`documents/store/report_forms.py`: one builder turns any report table into the repo's ruled-box PDF page (landscape above 6 columns); `list_forms()`
names one form per report. Excel files have numeric cells, number formats and a frozen header.

## Slice independence
This slice reads the other slices only through their published functions (`get_po_receipt_summary`, `get_subcon_issues`, `get_outstanding_returnables`, `get_in_transit`, `get_count_variances`, `get_scrap_realisation`) and the shared ledger. It imports none of their models and has no foreign key into their tables (`store_recovery_link.issue_line_id` is a plain integer).
