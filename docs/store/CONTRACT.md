# Store module - shared contract

Tag `store-skeleton`. Everything in this file exists in the repo and is finished. If you need it to change, do not edit
it: write the request in `docs/store/requests/P<n>.md` (what you need, why, and the signature you would like) and the
owner of the shared file makes the change in one commit that everyone then merges.

## Who owns what

| | Backend | Frontend |
|---|---|---|
| **P1** Masters + Enquiry | `routers/store_masters.py`, `routers/store_enquiry.py` | `features/store/masters/`, `features/store/enquiry/` |
| **P2** Inward | `models/store_inward.py`, `services/store_inward.py`, `routers/store_inward.py`, `documents/store/inward_forms.py` | `features/store/inward/` |
| **P3** Outward | `models/store_outward.py`, `services/store_outward.py`, `routers/store_outward.py`, `documents/store/outward_forms.py` | `features/store/outward/` |
| **P4** Control | `models/store_control.py`, `services/store_control.py`, `routers/store_control.py`, `documents/store/control_forms.py` | `features/store/control/` |
| **P5** Reports + integration | `models/store_reports.py`, `services/store_reports.py`, `services/store_integration.py`, `routers/store_reports.py`, `documents/store/report_forms.py` | `features/store/reports/` |

**Shared and frozen** (nobody edits): `models/store_core.py`, `services/stock_ledger.py`, `services/store_numbering.py`,
`schemas/store_contracts.py`, `core/store_auth.py`, `routers/store_lookup.py`, `core/permissions.py` (the store keys),
`bootstrap.py` (registration), `models/__init__.py`, `api/store.ts`, `features/store/shared/`, `features/store/StoreShell.tsx`,
`routes.tsx`, `lib/nav.ts`, `lib/pageInfo.ts`, `tests/store/fixtures.py`. Dependencies are done: Excel is `openpyxl`, PDF is
`reportlab` (both already in `backend/requirements.txt`); nothing was added to `package.json`.

Your slice's own tables live in your own `models/store_<slice>.py` (already imported by `models/__init__.py`), are created
by `create_all` at start-up, and must be new tables - adding a column to a shared table is a request.

## Rules that hold everywhere

1. **Stock moves only through `post_movement`.** Nothing else inserts into `store_stock_ledger` or `store_stock_balance`,
   and nothing updates or deletes a ledger row. A mistake is undone with `reverse_document`.
2. **Nothing in the ledger code commits.** The route (or the document's post action) owns the transaction: call
   `post_movement` for every line, then `db.commit()` once; on any `StoreError` call `db.rollback()`.
3. **Numbers are `Decimal`.** Quantities `Numeric(18,3)`, rates `Numeric(18,4)`, values `Numeric(18,2)`. Never `float` in
   a calculation. Over the API they travel as strings.
4. **Every movement names its document**: `ref_doc_type` (`GRN`, `ISSUE`, `TRANSFER`, `COUNT`, `SCRAP`, `OPENING` ...),
   `ref_doc_id`, and `ref_line_id` when it has lines. `reverse_document` finds a document's movements by that pair, so a
   document that posts must use the same pair for every one of its movements.
5. **Tenancy**: every route starts with `actor = store_actor(request, db, "store.<slice>.<action>")`, and uses
   `actor.client.id` to scope queries. A route that takes a `store_id` also calls `assert_store_access(actor.user, store_id)`.
6. **Errors**: wrap posting in `with store_errors():` - `InsufficientStockError` -> 409, `StoreFrozenError` -> 423,
   `InvalidMovementError` -> 400.
7. **Documents** carry a `status` from `DocStatus`: `DRAFT -> SUBMITTED -> APPROVED -> POSTED`, and `CANCELLED` from any
   earlier state. Only `POSTED` has touched stock; cancelling a `POSTED` document calls `reverse_document`. Numbers come
   from `next_doc_number`.
8. No inventing rights, enums or movement types. If you need one, request it.

## Tables (`models/store_core.py`, migration `store_001_core`)

This repo has no Alembic: `Base.metadata.create_all` makes new tables at start-up, so `store_001_core` names the change
(`REVISION` in `store_core.py`) and needs no script. All the tables are new; no existing table changed.

| Table | Class | Notes |
|---|---|---|
| `store_store` | `DBStore` | `client_id`, `code` (unique per company, e.g. `CS01`), `name`, `type` CENTRAL/SITE/YARD, `project_id` -> `jobs`, `address`, `is_active` |
| `store_bin` | `DBStoreBin` | `store_id`, `code`, `description`, `is_active` |
| `store_user_assignment` | `DBStoreUserAssignment` | `store_id`, `employee_id`, `role` (label), `is_active`. No row and no `store.admin` = no access to the store |
| `store_item_settings` | `DBStoreItemSettings` | one per `erp_items` row: `category` CONSUMABLE/RETURNABLE/TOOL/SPARE, `base_uom`, `reorder_level`, `min_qty`, `max_qty`, `qc_required`, `over_receipt_tolerance_pct`, `is_batch_tracked` |
| `store_uom_conversion` | `DBStoreUomConversion` | `item_id`, `from_uom`, `to_base_factor` (1 `from_uom` = factor of base) |
| `store_freeze` | `DBStoreFreeze` | `store_id`, `reason`, `frozen_by`, `frozen_at`, `unfrozen_at`, `unfrozen_by`. Open while `unfrozen_at` is empty |
| `store_doc_sequence` | `DBStoreDocSequence` | `doc_type`, `store_id`, `fy` (`26-27`), `last_no` |
| `store_stock_ledger` | `DBStoreStockLedger` = `StockLedgerEntry` | append-only, below |
| `store_stock_balance` | `DBStoreStockBalance` | one row per `store_id` + `item_id`: `qty`, `value`, `avg_rate` |

The ORM classes are `DB`-prefixed like the rest of the repo. `StockLedgerEntry` is an alias of `DBStoreStockLedger`.
`StockBalance(qty, value, avg_rate)` is the frozen dataclass `get_balance` returns (`services/stock_ledger.py`).

Items are the existing item master (`erp_items`, kind `RM`); the store adds settings beside them, it does not copy them.
Projects are `jobs`, work orders `work_orders`, BOQ items `boq_lines`, subcontractors `contractors`, staff `employees`.
Dates are `Date`/`DateTime` columns (the older tables keep dates as text - convert at the edge).

### The ledger row

`txn_date`, `store_id`, `item_id`, `movement_type`, `qty_in`, `qty_out`, `rate`, `value`, `running_qty`, `running_value`,
`avg_rate`, `project_id`, `work_order_id`, `boq_item_id`, `cost_head`, `subcontractor_id`, `ref_doc_type`, `ref_doc_id`,
`ref_line_id`, `reversal_of_id`, `user_id`, `created_at`, `remarks`.

* Exactly one of `qty_in` / `qty_out` is non-zero. `value` is always **positive** (the size of the movement); the
  direction is which quantity is set.
* An OUT's `rate` is the average rate it was valued at (value / qty); an IN's `rate` is the rate given.
* `running_qty`, `running_value` and `avg_rate` are the store/item position right after the entry, **in posting order
  (id)**. `txn_date` is the business date (never in the future) and can be earlier than the posting.
* `user_id` is an employee id; empty when the account holder acted.
* **A reversal is a row with the same `movement_type` as the original**, the quantity in the opposite column,
  `reversal_of_id` pointing at the original, dated today, `remarks` = `Reversal: <reason>`. So a cancelled `GRN_IN` shows
  as a `GRN_IN` row with `qty_out` set. **Reports that total by movement type must net these**: sum `qty_in - qty_out`
  and `value` signed by direction; never filter reversals out, and never count a reversed original on its own.
* Cost reports (project, cost head, work order, BOQ item) read the `*_OUT` rows' dimensions; a reversal copies them, so the
  net is right.

### Enums (`models/store_core.py`; TypeScript copies in `api/store.ts`)

* `MovementType`: OPENING_IN, GRN_IN, CLIENT_SUPPLY_IN, PURCHASE_RETURN_OUT, ISSUE_OUT, ISSUE_RETURN_IN, SUBCON_ISSUE_OUT,
  SUBCON_RETURN_IN, TRANSFER_OUT, TRANSFER_IN, ADJUST_IN, ADJUST_OUT, WASTAGE_OUT, SCRAP_OUT. Names ending `_IN` add
  stock and need a rate; names ending `_OUT` remove it and must pass `rate=None`. `IN_MOVEMENTS` / `OUT_MOVEMENTS` list them.
* `DocStatus`: DRAFT, SUBMITTED, APPROVED, POSTED, CANCELLED.
* `CostHead`: SITE_ESTABLISHMENT, P_AND_M_FUEL, OVERHEAD, SAFETY, TEMPORARY_WORKS.
* `StoreType`: CENTRAL, SITE, YARD. `ItemCategory`: CONSUMABLE, RETURNABLE, TOOL, SPARE.
* Errors: `StoreError` (base), `InsufficientStockError`, `StoreFrozenError`, `InvalidMovementError`.

## Services (`services/stock_ledger.py`, `services/store_numbering.py`)

```python
post_movement(db, *, movement_type, store_id, item_id, qty, rate, txn_date, project_id,
              ref_doc_type, ref_doc_id, ref_line_id, user_id,
              work_order_id=None, boq_item_id=None, cost_head=None, subcontractor_id=None, remarks=None) -> StockLedgerEntry
reverse_document(db, *, ref_doc_type, ref_doc_id, user_id, reason) -> list[StockLedgerEntry]
get_balance(db, store_id, item_id) -> StockBalance(qty, value, avg_rate)
convert_to_base(db, item_id, qty, uom_code) -> Decimal
assert_store_access(user, store_id)            # 403 unless assigned / store.admin / the account holder
freeze_store(db, store_id, reason, user_id)
unfreeze_store(db, store_id, user_id)
is_frozen(db, store_id) -> bool
next_doc_number(db, doc_type, store_id, *, on_date=None) -> str      # "GRN/CS01/26-27/00042"
```

* **Valuation is a moving weighted average** per store and item. IN: `value += qty x rate`, `avg = value / qty`. OUT: valued
  at the current `avg_rate`, which does not change; taking the whole balance takes the whole value, so no rounding
  residue is left behind a zero quantity. A transfer is `TRANSFER_OUT` at the source (note the entry's `rate`), then
  `TRANSFER_IN` at the destination with that rate.
* **Blocked, with an exception and no ledger row**: negative stock (`InsufficientStockError`), a frozen store
  (`StoreFrozenError`, including reversals), unknown/inactive store, an item of another company, zero quantity, a missing
  rate on an IN or a rate on an OUT, a future date, an unknown movement type or cost head, a missing `ref_doc_*`
  (`InvalidMovementError`).
* **`reverse_document`** undoes every not-yet-reversed movement of the document, newest first, all or nothing (a
  savepoint): an IN comes back out at the value it went in at, an OUT comes back in at the value it left at. It raises
  `InsufficientStockError` if the stock has since been used, and `InvalidMovementError` for a document with nothing
  posted or already fully reversed. Stock can only be reversed while it is still there - plan the screens for that.
* **`convert_to_base`** returns the base-unit quantity to 3 decimals; the base unit (from `store_item_settings`, else the
  item master's unit) needs no conversion; an unknown unit raises `InvalidMovementError`. Post in base units.
* **`next_doc_number`** restarts at 00001 each Indian financial year (April-March) per document type and store, locks the
  row, and gives its number back if the transaction rolls back. `doc_type` is capital letters (`GRN`, `ISSUE`, `TRF`).
* **`assert_store_access(user, store_id)`** takes the `actor.user` from `store_actor` (the employee, or the company for the
  account holder). The account holder reaches every store of their company; staff reach the stores they are assigned to,
  all stores with `store.admin`, and none of another company's.

## Cross-slice data (`schemas/store_contracts.py`, frozen dataclasses)

`PoLineReceipt`, `SubconIssueLine`, `ReturnableOutstanding`, `WriteOffRequest`, `InTransitLine`, `CountVarianceLine`,
`ScrapLine`, `MaterialCostLine` - fields exactly as in the file. A slice that needs another slice's data calls its
function below; it never reads that slice's tables. Until the owner builds them they return empty results.

| Function | Owner | Returns |
|---|---|---|
| `store_inward.get_po_receipt_summary(db, po_id)` | P2 | `list[PoLineReceipt]` |
| `store_outward.get_subcon_issues(db, subcontractor_id, upto_date)` | P3 | `list[SubconIssueLine]` |
| `store_outward.get_outstanding_returnables(db, project_id=None, store_id=None)` | P3 | `list[ReturnableOutstanding]` |
| `store_outward.list_writeoff_requests(db, status="OPEN")` | P3 | `list[WriteOffRequest]` |
| `store_outward.close_writeoff_request(db, request_id, ref_doc_type, ref_doc_id, user_id)` | P3 | `None` |
| `store_control.get_in_transit(db, project_id=None)` | P4 | `list[InTransitLine]` |
| `store_control.get_count_variances(db, store_id, from_date, to_date)` | P4 | `list[CountVarianceLine]` |
| `store_control.get_scrap_realisation(db, project_id, from_date, to_date)` | P4 | `list[ScrapLine]` |
| `store_reports.get_theoretical_requirement(db, boq_item_id, item_id)` | P5 | `Decimal \| None` |
| `store_integration.get_project_material_cost(db, project_id, from_date, to_date)` | P5 | `list[MaterialCostLine]` |

## Permissions (`core/permissions.py`)

`store.<slice>.<action>` for slices `masters, enquiry, inward, outward, control, reports` and actions
`view, create, approve, post, cancel` (30 keys), plus `store.outward.direct_issue`, `store.control.reveal_count`,
`store.control.approve_high_value`, and `store.admin` (every store, every right). The account holder holds all of them;
staff get them from their access level or by tick. The six `view` keys and the other 24 action keys belong to the
"Store & Supplies" portal card; the four extras are never part of a card. `store_actor(request, db, key)` also lets
`store.admin` through. The sidebar item and the hub tabs follow the `view` keys.

## HTTP

Each slice owns `/api/store/<slice>` (`masters`, `enquiry`, `inward`, `outward`, `control`, `reports`); each answers
`GET` with `{"slice": ..., "items": []}` until its owner replaces it. Shared, read-only, finished:

* `GET /api/store/lookup/meta` - the enums above.
* `GET /api/store/lookup/stores?project_id=` - the stores this person may work in.
* `GET /api/store/lookup/items?q=&limit=` - stock items with `base_uom` and `uoms`.
* `GET /api/store/lookup/items/{id}/uoms`.

## Frontend

* Everything is under `features/store/`. The hub is `/store/hub`; each slice owns `/store/hub/<slice>/*` and renders
  `<StoreShell slice="...">` itself - use `<Routes>` inside your `index.tsx` for sub-pages, so `routes.tsx` never changes.
  The sidebar item is *Store > Store Hub*.
* `api/store.ts`: `storeGet/Post/Put/Patch/Delete(slice, path, body)`, `storePerm(slice, action)`, `storeKeys`, and the hooks
  `useStoreMeta`, `useStoreOptions`, `useItemSearch`, `useItemUoms`. Quantities are strings.
* `features/store/shared/` - props are frozen:
  * `StorePicker { value: number|null; onChange(id, store); projectId?; type?; excludeId?; placeholder?; disabled?; id? }`
  * `ItemPicker { value: StoreItemOption|null; onChange(item|null); placeholder?; disabled?; id? }`
  * `UomQtyInput { itemId: number|null; value: {qty: string; uom: string}; onChange(next); showBase?; disabled? }`
  * `DocStatusBadge { status: DocStatus }`
  * `DocActionsBar { status; can: {submit?, approve?, post?, cancel?}; busy?; onAction(action, reason?); disabled? }` -
    Post and Cancel ask for confirmation; Cancel asks for a reason; the buttons follow the status.

## Test fixtures (`backend/tests/store/fixtures.py`)

`build_store_world(db)` makes one company: a project (`Tower A`), a work order with 2 BOQ items, a supplier, an approved PO
of 3 lines (cement 400 bag, TMT 12mm 1500 kg, TMT 16mm 2500 kg), a subcontractor, 2 stores (`CS01` central, `ST01` site on
the project), 10 items (cement kg/bag/MT with 1 bag = 50 kg; TMT 12mm/16mm kg/nos with nos = d^2/162 x 12 kg), and opening
stock at `CS01` posted through `post_movement`. Six staff: `central_keeper`, `site_keeper`, `approver`, `viewer`,
`unassigned`, `admin`. In a test: `from store.fixtures import db, store_world  # noqa: F401` then take `store_world` and
`db` as arguments (do **not** add a `conftest.py` to `tests/store/` - it would shadow `tests/conftest.py`).
`backend/tests/store/test_store_skeleton_smoke.py` shows posting, reversing and checking balances.
