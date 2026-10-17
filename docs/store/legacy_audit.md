# Legacy stock: what exists today and how it moves into the Store module

Audited on branch `store/p1-foundation`, from tag `store-skeleton`. Owner: P1.

The old stock feature and the new Store module run side by side until P5 points the old screens at the new ones. The
old feature is left as it is. The one exception is the fix in "Bugs found" below.

## What the old feature is

| Piece | Where | What it does |
|---|---|---|
| Ledger | `stock_movements` (`DBStockMovement`, `models/stores.py`) | One row per movement, **signed** `quantity` (issue negative), `rate`, `value`, `kind` RECEIPT / ISSUE / RETURN / ADJUSTMENT / TRANSFER_IN / TRANSFER_OUT, `store` as **free text** (default `"Main store"`), `item_code` as text, `source_type` / `source_id` / `source_ref` naming the document, `job_id`, `work_order_id`. Floats throughout. |
| Balance | `stock_balances` (`DBStockBalance`) | One row per **company and item code**, not per store: `on_hand`, weighted-average `rate`, `value`, lifetime `received` / `issued`. Kept by `apply_to_balance`. It can be rebuilt with `rebuild_stock_balances` (`POST /api/stock/rebuild`). |
| Writer | `services/stores.py: stock_movement()` | The one function that writes a movement and folds it into the balance. |
| Per-store figures | `replay_stock_ledger(store=...)` | The balance does not split by store, so anything per store **replays the ledger** in Python. |
| Issues | `stock_issues` + `stock_issue_lines` (`/api/stock-issues`, `routers/stores.py`) | DRAFT, then POSTED (writes ISSUE movements), then CANCELLED (writes RETURN movements). An issue can be posted anyway with `allow_negative`. It can be charged to a subcontractor (`charge_issue_to_contractor`). |
| Adjustments | `POST /api/stock/adjustments` | Takes a counted quantity and posts the difference as an ADJUSTMENT at the current rate. There is no document and no approval. |
| Transfers | `POST/GET /api/stock/transfers` | TRANSFER_OUT and TRANSFER_IN at the average rate, numbered by `next_transfer_number`. The destination store is parsed back out of `remarks` (`"A -> B. note"`). E-way bills read transfers from it (`services/invoicing.py: transfer_lines_for`). |
| Reports | `GET /api/stock`, `/api/stock.xlsx`, `/api/stock/{code}/ledger`, `/api/stock/stores`, `/api/stock/consumption/{wo}` | Stock on hand, Excel export, item ledger, stores by name, BOM vs issued (wastage). |
| Other readers | `services/item_master.py`, `services/item_usage.py`, `services/projects.py`, `routers/client_orders.py` | The item master's on-hand column, "is this item in use", project material cost and transfers, and deleting a work order. |
| Screens | `frontend/src/features/stock/` at `/store/stock` (Stock & Issues), `/store/material-costing` (Consumption) | `StockPage`, `IssueModal`, `TransferModal`, `LedgerModal`, `ConsumptionPage`. `MaterialVouchersPage` (`/store/material-vouchers`) is a printed-voucher register and **moves no stock**. |
| Rights | `stores.manage`, `stores.receive`, `site.record`, `store.view` | Not the `store.<slice>.<action>` rights of the new module. |

## How a purchase receipt posts stock today

1. A GRN (`goods_receipts` + `goods_receipt_lines`, `/api/grn`) is raised against an approved purchase order. Each line
   carries `received_qty`, `accepted_qty`, `rejected_qty` and the PO `rate`.
2. `POST /api/grn/{id}/post` calls `services/procurement.py: grn_apply(..., "POST")`. Transitions are
   `GRN_TRANSITIONS` (`constants/common.py`): DRAFT to POSTED or CANCELLED, POSTED to CANCELLED. There is no submit or
   approve step.
3. On POST, every line with `accepted_qty > 0` becomes a RECEIPT movement through `stock_movement()`:
   - the quantity is `accepted_qty` in the line's own `uom`, with no conversion;
   - the rate is the line rate;
   - the store is `grn.store_location` (free text), else `"Main store"`;
   - `moved_on` is `grn.received_on`, `source_type="goods_receipt"`, `source_id=grn.id`, and `job_id` is the GRN's project.

   Rejected quantity never enters stock.
4. Cancelling a **posted** GRN writes a negative ADJUSTMENT per line at the line rate (`source_ref = "<number> cancelled"`).
   This is not a reversal at the value the stock went in at, and nothing stops it taking stock negative.

## Differences that matter for the move

| Old | New (Store module) |
|---|---|
| Store is a text label; a typo is a new store | `store_store` rows with a code; stock is held per store and item |
| Item by code (text) | Item by `erp_items.id`; the base unit is from `store_item_settings`, with conversions in `store_uom_conversion` |
| Floats | `Decimal`: quantities to 3 places, rates to 4, values to 2 |
| Negative stock allowed (`allow_negative`, cancellations) | Never negative (`InsufficientStockError`) |
| Edits by counter-movement of any kind | Append-only ledger; a document is undone by `reverse_document` at the original rate |
| One balance per company and item | One balance per store and item, locked while it is posted |
| No freeze, no back-dating rule | Freeze for counts; no movement dated before the last one of its store and item |
| GRN: DRAFT, then POSTED | DRAFT, SUBMITTED, APPROVED, POSTED (CANCELLED), with every step logged |

## Moving the balances: `backend/scripts/store_legacy_to_opening.py`

```
python scripts/store_legacy_to_opening.py --client 12                                   # dry run: prints what it would do
python scripts/store_legacy_to_opening.py --client 12 --map "Main store=CS01" --commit
python scripts/store_legacy_to_opening.py --all --create-stores --as-of 2026-10-01 --commit
```

For each old store name, the script:

1. replays the old ledger for that store (`replay_stock_ledger(store=name)`), so each store's balance is what the old
   screens show for it;
2. finds the new store. It uses `--map "OLD NAME=CODE"` first, then a store whose name or code matches the old name. With
   `--create-stores` it makes a CENTRAL store whose code is built from the old name's initials (`Main store` becomes `MS01`).
3. for each item with a positive balance, finds the item by code. The quantity is converted from the old unit to the
   item's base unit (`convert_to_base`). The rate is the old value divided by the base quantity, so the value carries
   over to the paisa (rounding aside).
4. writes **one opening document per store**: `store_opening` with `source=LEGACY` and number `OPEN/<store>/<fy>/n`. It is
   posted at once as `OPENING_IN` movements (ref `OPENING_STOCK` and the document id), and its trail records DRAFT, then
   POSTED, by "Legacy stock migration". It can be cancelled from the Opening stock screen like any other opening.

Left out and reported, never guessed:

- zero and **negative** balances;
- codes that are not in the item master;
- FG items;
- a unit with no conversion to the item's base unit;
- an old store with no match (when `--create-stores` is not given);
- any item that already has stock history in the new store. The last rule makes a second run safe: it only picks up what
  the first run could not.

Nothing is written without `--commit`. The old tables are only read, so the old screens show the same as before.

Covered by `test_legacy_balances_become_opening_stock_once` in `backend/tests/store/test_foundation.py`.

### Suggested cut-over

1. Set up the stores, assignments and item settings (Masters), and map every old store name with `--map`.
2. Dry-run the script, fix what it reports in the old screens (negatives, unknown codes, missing conversions), and run
   it again.
3. Run it with `--commit --as-of <the cut-over date>`.
4. From the cut-over date, post receipts and issues in the new module only. Redirecting the old screens is P5's job.

## Bugs found in the old code

- **Fixed:** `apply_to_balance` added a new `stock_balances` row without flushing it. Sessions do not autoflush, so a
  second movement of the same new item in one request (two lines of a first GRN, or a transfer's two legs) did not
  find the row. It inserted a duplicate and failed on the unique key. A `db.flush()` after the add fixes it. The old
  stock tests still pass.
- **Not fixed, for P5:**
  - a cancelled posted GRN takes stock out at the GRN rate, and can make stock negative;
  - transfers keep their destination only inside `remarks`;
  - `stock_issue` posting with `allow_negative` lets the balance go below zero, and `rebuild_stock_balances` then
    reproduces it.

  These are behaviours of the old screens. They go away when those screens move onto the Store module.
