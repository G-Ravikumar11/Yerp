# P5: Integration hooks into existing modules

P5 is the only slice allowed to touch existing modules, and only with small, additive hooks. Every touched file is
listed here. Each hook asks `services/store_integration.py`, the one place the rest of the ERP reads the Store module.
It never reads another slice's tables, and it never writes stock.

## Files touched outside the Store module

| File | Change | Why |
|---|---|---|
| `backend/app/services/projects.py` | In `preload_pnl_for_job` and `preload_pnl`: the old ledger's issues are filtered through `legacy_moves_before_cutover`; a new `store_material` key holds `project_material_cost_by_job`; `stocked` merges `store_stocked_share` into the old stocked share. In `project_pnl`: `material += store_material`; new output field `cost.material_from_store_module`. About 20 lines. | **4a** Project profit uses the Store ledger's material cost (issues − returns + write-offs, scrap, count and transit losses) instead of the old stock data. The old ledger still counts up to the cut-over date, so history is not lost and nothing is counted twice. A supplier bill for material taken into stock through a Store GRN is not also counted as cost. |
| `backend/app/services/procurement.py` | `grn_apply("POST")` refuses (409) once the company uses the Store module. 7 lines. | **4c** Stops direct stock posting from the old purchase-order receipt, so one delivery cannot be counted in both ledgers. Old receipts can still be drafted and matched against orders and bills. |
| `frontend/src/features/purchaseorders/PurchaseOrdersPage.tsx` | A **Received** link on approved orders opens `PoReceiptsButton`: received and pending per line from P2's `get_po_receipt_summary`, with **Receive in Store**. 2 lines. | **4c** Received / pending per PO line. |
| `frontend/src/features/grn/GrnPage.tsx` | `StoreReceiveNotice` banner: goods are received in Store > Inward, with a **New GRN** button. 2 lines. | **4c** Redirects the old "receive" action to the new GRN screen. |
| `frontend/src/features/subbills/BillPage.tsx` | `SubBillRecoveryPanel` above the certificate. 3 lines. | **4b** Shows "material recovery due" read-only: P3's chargeable issue records plus excess-wastage recovery. Sub-bill posting is unchanged. A recovery can be *noted* (P5's own table); the deduction is still typed on the bill. |
| `frontend/src/features/stock/StockPage.tsx` | `LegacyHandover` at the top. 2 lines. | **4e** Once the company has a store and its old balances are carried over (a posted LEGACY opening, or it never had old stock), the old Stock & Issues screen sends people to Store > Stock enquiry. |
| `frontend/src/features/stock/ConsumptionPage.tsx` | `LegacyHandover` to Store > Reports. 2 lines. | **4e** The same, for the old consumption screen. |

The rules didn't change in: sub-bill posting, client RA billing, PO screens' saving, and the old stock posting functions.

## Read-only providers (no existing file changed)

| Endpoint / function | For |
|---|---|
| `store_integration.get_project_material_cost(db, project_id, from, to) -> list[MaterialCostLine]`, also `GET /api/store/reports/integration/project-cost/{project_id}` | **4a** Material cost by cost head, work order, BOQ item and item |
| `GET /api/store/reports/integration/po/{po_id}` | **4c** Received / pending per PO line |
| `GET/POST /api/store/reports/integration/sub-bills/{id}/recovery` | **4b** Recovery due; note a recovery |
| `GET /api/store/reports/integration/client-billing?project_id=` or `&work_order_id=` | **4d** Client-supplied material to recover (consumed × agreed rate), balance at site, and material-at-site value |
| `GET /api/store/reports/integration/status` | **4e** `store_active`, `legacy_migrated`, `redirect`, `legacy_receipt_blocked` |

## Note for the client-billing owner (4d)

`/integration/client-billing` gives, for a project or client work order:
- `client_supply.rows`: per material, received, consumed (net issued, never more than received), balance at site,
  `recovery_value` at the agreed rate, and `balance_value`.
- `material_at_site`: what the project's stores hold, with its value.

Nothing in RA billing uses it yet. If client-supplied material is to be recovered in RA bills, or material at site
advanced, the RA-bill code should read this provider. Billing rules are yours to change.

## Behaviour to know

- **Cut-over date** is the earliest `txn_date` in the company's Store ledger (normally the opening-stock date). The old
  ledger's issues dated on or after it are left out of profit, because the old screens hand over then. Issues still
  made in the old screens after cut-over should be re-entered in the Store module.
- The old receipt is blocked as soon as the company has **any** store. Set up stores only when you are ready to receive
  in the Store module.
