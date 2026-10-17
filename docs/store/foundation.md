# P1: Foundation (ledger, numbering, masters, opening stock, stock enquiry)

Branch `store/p1-foundation`, migration `store_002_foundation` (down revision `store_001_core`). This page covers what P1
changed underneath the shared contract and what P1 built on top of it. The contract itself is in
[CONTRACT.md](CONTRACT.md) and is unchanged: no public signature, exception name or argument meaning has moved.

## 1. The ledger engine (`services/stock_ledger.py`)

These rules are added on top of the contract. Each is covered by `backend/tests/store/test_foundation.py`.

| Rule | What happens | Error |
|---|---|---|
| **Locking.** Every movement locks its store + item balance row before reading it, and reads it fresh (`populate_existing`). On Postgres this is `SELECT ... FOR UPDATE`. On SQLite, where `FOR UPDATE` does nothing, it is a no-op `UPDATE` on the row first, which makes the connection SQLite's one writer. | Two people issuing the last 100 bags at once: one gets them, the other is told there is not enough. Receipts at the same moment both count. | `InsufficientStockError` (409) |
| **No back-dating.** A movement may not be dated before the last movement of the same store and item. The same day is fine. | Running quantities read the same in date order as in posting order. | `InvalidMovementError` (400) naming the item, store and both dates |
| **Freeze for a count.** `freeze_store_for_count(db, store_id, reason, user_id, *, count_doc_id, count_doc_type="COUNT")` is a **new** function. It is the same freeze as `freeze_store`, but it names the count. While it is open, that count's own `ADJUST_IN` / `ADJUST_OUT` (same `ref_doc_type` and `ref_doc_id`) post and reverse. Nothing else moves. A plain `freeze_store` still holds everything, adjustments included. | P4 freezes with this, books the variances, then unfreezes. | `StoreFrozenError` (423) |
| **Reversal at the original rate.** An IN comes back out at its own value (all of what is left if it is the whole balance, so no residue); an OUT comes back in at the value it left at. **What is left is re-averaged.** The skeleton kept the old average after taking a receipt back out, so `avg_rate` disagreed with value / qty. | Cancel a dearer GRN and the average goes back down. | |
| **Reversal that would go negative.** The message names the item (code and name), the store, the quantity on hand and the quantity needed. | `Cannot reverse GRN 20: only 10 cum of ST-SAND River Sand is on hand in CS01 (Central Store); 20 cum is needed.` | `InsufficientStockError` (409) |
| **Reversal that would leave a negative value** (cheap stock, then a dear receipt, then an issue at the blend, then cancelling the dear receipt). | Refused, with what the stock is now worth. Cancel the later issues first, or correct with an adjustment. | `InvalidMovementError` (400) |
| **Reversed once only.** `reverse_document` locks every balance the document touched (in store, item order), then looks again. A **unique index on `reversal_of_id`** means the database refuses a second reversal of the same row even if two cancels race. | Two people pressing Cancel at once: one reverses, the other is told it is already reversed. | `InvalidMovementError` (400) |
| **Readable quantities in errors.** `InsufficientStockError` takes an optional `message=` (the four attributes are unchanged), so the error says `only 5 nos of ST-HELMET Safety Helmet`, not `item 37`. | | |

There is a new read-only helper, `ledger_position(db, store_id, item_id) -> StockBalance`. It nets the ledger by direction
and must always equal `get_balance`.

### Valuation, worked (from the tests)

Sand at CS01: 100 cum opening at 1800.

| Step | Qty | Value | Avg |
|---|---|---|---|
| GRN 50 @ 2000 | 150.000 | 280000.00 | 1866.6667 |
| Issue 40 (valued 40 x 1866.6667 = 74666.67; entry rate 1866.6668) | 110.000 | 205333.33 | 1866.6667 |
| GRN 30 @ 1750.50 | 140.000 | 257848.33 | 1841.7738 |
| **Reverse the issue** (back in at 74666.67) | 180.000 | 332515.00 | 1847.3056 |
| Issue 25 | 155.000 | 286332.36 | 1847.3056 |

Rounding: three issues of 333.333 litres from 1000 at 92 each come to 30666.64. That leaves 0.001 litre worth 0.08, and
issuing it takes the whole 0.08. A 200-step random run of receipts, issues and reversals keeps the balance equal to the
ledger, the value non-negative, and the average within a paisa of value / qty.

## 2. Numbering (`services/store_numbering.py`)

`next_doc_number(db, doc_type, store_id, *, on_date=None)` is unchanged on the outside. Underneath, it now takes the
number with **one** `UPDATE ... SET last_no = last_no + 1` and reads the result back in the same transaction. That is
atomic on Postgres (row lock) and on SQLite (single writer). The skeleton read the number and then wrote it, which
gave duplicates under load on SQLite.

The first number of a year is an insert guarded by the unique key; whoever loses the race takes the next number. Three
threads taking 8 numbers each get 24 different numbers. The year rolls over on 1 April (`TRF/CS01/26-27/...` on 31 March,
`.../27-28/00001` on 1 April). A rolled-back document gives its number back.

An **unreadable `on_date` is now an error**. It used to fall back silently to today and could number a document into the
wrong year. There is also a new helper, `financial_year(on_date) -> "26-27"`.

## 3. Masters: `/api/store/masters` (screens at `/store/hub/masters`)

Rights: `store.masters.view` to look, `store.masters.create` to set up and to raise or submit an opening,
`store.masters.approve` / `.post` / `.cancel` for an opening's later steps. Anything about one store also needs access to
that store (`assert_store_access`). Another company's store or item is a 404.

| Route | What |
|---|---|
| `GET ""` | `{"slice": "masters", "items": [stores]}` |
| `GET/POST /stores`, `PUT /stores/{id}` | Stores. The code is 2-10 capital letters or digits and unique per company. **A SITE store needs a project.** The code cannot change once a document has been numbered with it. A store that holds stock or is frozen cannot be closed. Each row says `accessible` and `frozen`, and gives bin and people counts. |
| `GET/POST /stores/{id}/bins`, `PUT /bins/{id}` | Bins (unique code per store, retire and bring back) |
| `GET/POST /stores/{id}/users`, `PUT /assignments/{id}`, `GET /employees?q=` | Who works in the store: the rows `assert_store_access` reads. Roles (labels only): STOREKEEPER, SITE_ENGINEER, STORE_INCHARGE, APPROVER, VIEWER. Re-adding someone brings their row back. |
| `GET /items?q=&configured=yes/no`, `GET /items/{id}`, `PUT /items/{id}/settings` | Item store settings: category, base unit, reorder / min / max, QC, tolerance, batch. **The base unit is fixed once the item has stock history.** |
| `GET/POST /items/{id}/uoms`, `PUT/DELETE /uoms/{id}` | Unit conversions (1 unit = factor x base). Changing a factor affects only what is entered afterwards, since the ledger is in base units. |
| `POST /items/{id}/uoms/preset` `{kind}` | Standard sets worked out from the base unit. **CEMENT**: kg / bag (50 kg) / MT. **STEEL** `{dia_mm, bar_length_m=12}`: nos = d^2/162 x length kg, plus MT or kg. **VOLUME**: cum / cft (1 cft = 0.028316846592 cum). Running it again brings existing units to the standard. |
| `GET /steel-weight?dia_mm=&bar_length_m=` | kg per metre and per bar |

### Opening stock

`store_opening` + `store_opening_line`, numbered `OPEN/<store>/<fy>/00001`, posted as `OPENING_IN` with
**`ref_doc_type = "OPENING_STOCK"`**, `ref_doc_id` = the opening's id and `ref_line_id` = the line's id. The fixtures
already use `("OPENING", 1)`; a separate type keeps a real opening from ever being reversed together with them.

| Route | What |
|---|---|
| `GET /opening?store_id=&status=`, `POST /opening`, `GET/PUT /opening/{id}` | List, create (DRAFT), view (lines + status trail), edit (DRAFT only) |
| `POST /opening/{id}/submit` / `approve` / `post` / `cancel` `{reason}` | The lifecycle. **Post** re-checks every line and posts them all in one transaction. **Cancel** needs a reason; cancelling a POSTED opening reverses it, and is refused (409, naming the item and quantity) if the stock has since been used. |
| `GET /opening/{id}/document.pdf` | The printed opening (watermarked CANCELLED when cancelled) |
| `POST /opening/import/preview` (multipart `file`, `store_id`, `opening_date`) | Every row of a CSV checked; nothing is saved |
| `POST /opening/import` (+ `remarks`, `skip_errors`) | The sheet becomes a DRAFT opening. It is refused while any row is wrong, unless `skip_errors`, in which case only the good rows go in. |
| `GET /opening/template.csv` | `item_code,qty,uom,rate,bin_code,remarks` |

A line is entered in any of the item's units at a rate **per that unit**. It is posted in the base unit at
`rate = qty x rate / base qty` (4 places), and its value is what the ledger will record. Example: 10 nos of 12 mm at
661.33 posts as 106.667 kg at 61.9995, value 6613.30.

A line is refused when:

- the item is unknown or inactive;
- the quantity is zero or negative, or the rate is negative;
- the unit has no conversion;
- the bin is not in this store;
- the same item appears twice in the same bin;
- the item already has stock history in this store (opening stock is the first entry; use a count adjustment instead);
- the item is already on another opening of this store that is still in hand;
- the date is in the future.

Every status change is written to **`store_doc_status_log`** (doc type, id, from, to, user id and name, note, time).

## 4. Stock enquiry: `/api/store/enquiry` (screens at `/store/hub/enquiry`)

`store.enquiry.view`. Only the stores the person works in (all of them for the account holder and `store.admin`).

| Route | What |
|---|---|
| `GET ""` | `{"slice": "enquiry", "items": [store x item balances]}` |
| `GET /balances?group=store/item/project&store_id=&project_id=&q=&category=&include_zero=` | Balance with value and average rate. By store, one row per store and item, with a below-reorder flag. By item, added up across stores. By project, added up across each project's stores (central and yard show as "Not on a project"). Summary: total value, items, stores, below reorder. |
| `GET /items/{id}/card?store_id=&date_from=&date_to=` | The ledger card: opening position before `date_from`, every movement with the position after it, totals in and out, closing, and the live balance. Each row has `doc_number` and `doc_path` (drill-down), `reversal_of_id` / `reversed_by_id`, project, cost head and user. |
| `GET /items/{id}/card.pdf` | The card printed |
| `GET /items/{id}/availability` | The item in every store the person works in, with zeros, and the total |

**Drill-down paths** (`DOC_PATHS` in `routers/store_enquiry.py`):

| `ref_doc_type` | Path |
|---|---|
| `OPENING_STOCK` | `/store/hub/masters/opening/{id}` |
| `GRN` | `/store/hub/inward/grn/{id}` |
| `PURCHASE_RETURN` | `inward/returns` |
| `CLIENT_SUPPLY` | `inward/client-supply` |
| `ISSUE` | `outward/issues` |
| `ISSUE_RETURN` | `outward/returns` |
| `SUBCON_ISSUE` | `outward/subcon` |
| `TRANSFER` | `control/transfers` |
| `COUNT` | `control/counts` |
| `ADJUST` | `control/adjustments` |
| `SCRAP` | `control/scrap` |

**P2-P4: if your screen lives elsewhere, or you post under another `ref_doc_type`, tell P1** and the map changes in one
line. Until then the card shows the type and id without a link. Only openings show their printed number, because a
slice never reads another slice's tables.

## 5. Shared components (`features/store/shared`, props unchanged)

- **ItemPicker**: arrow keys, Home, End and Enter pick from the list. Escape closes the list without closing the dialog
  around it. The best match is highlighted as you type. A spinner shows while searching. Each option shows its units
  (`kg · also bag, MT`). It is a proper combobox for screen readers, and focus returns to the box after Clear.
- **UomQtyInput**: shows `1 bag = 50 kg` under the box beside `= 150.000 kg`. It accepts `1,000` and cleans it to `1000`.
  Alt+Up / Alt+Down in the quantity steps through the units. A unit left over from a previously chosen item falls back
  to the base unit.
- **StorePicker**: labels include the type (`ST01 - Tower A (site)`), and the list says "No store you work in" when that
  is the case.
- New pure helpers, tested in `shared.test.ts`: `nextIndex`, `unitsLine`, `unitHint`, `cleanQty`, `storeLabel`.

## 6. Migration `store_002_foundation`

Additive only. New tables `store_opening`, `store_opening_line` and `store_doc_status_log` (made by `create_all`). New
nullable columns `store_freeze.ref_doc_type` and `store_freeze.ref_doc_id`. New ledger indexes
`ix_store_ledger_store_item_date` (store, item, date) and unique `uq_store_ledger_reversal_of`. The indexes on
(project, date) and (ref type, ref id) were already in `store_001_core`.

The repo has no Alembic, so `models/store_core.py` carries `REVISION_FOUNDATION = "store_002_foundation"` and
`upgrade_store_002_foundation(engine)`. That function is idempotent and adds the columns and indexes to a database
created before them. Calling it at start-up is a frozen-file change: see [requests/P1.md](requests/P1.md).

## 7. Legacy

See [legacy_audit.md](legacy_audit.md) and `backend/scripts/store_legacy_to_opening.py`.

## Tests

`backend/tests/store/`:

- `test_foundation.py`: ledger, valuation, reversals, dates, freezes, concurrency, numbering, legacy migration.
- `test_masters.py`: stores, bins, people, items, units, openings, CSV import, rights, store access, other company.
- `test_enquiry.py`: balances, card, drill-down, availability, rights, store access.

Frontend: `features/store/shared/shared.test.ts`.
