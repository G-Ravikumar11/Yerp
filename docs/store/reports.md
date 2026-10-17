# P5: Reports, norms, reconciliation and dashboard

Branch `store/p5-reports`, built on `store/p1-foundation`. Migration `store_006_reports` (down revision
`store_001_core`) adds only new tables: `store_consumption_norm` and `store_subcon_recovery`. Reports read the ledger,
and other slices only through their published functions. **Nothing here writes stock.**

Files: `models/store_reports.py`, `services/store_reports.py`, `services/store_integration.py`,
`routers/store_reports.py`, `documents/store/report_forms.py`, `frontend/src/features/store/reports/`. The existing
modules touched are listed in [integration.md](integration.md).

## Netting

A reversal is a row of the same type in the other column, so:
- an IN type totals `qty_in − qty_out`;
- an OUT type totals `qty_out − qty_in`;
- value is signed by direction.

Cancelled documents drop out of every total; they are never filtered out.

**Consumption** means `ISSUE_OUT` and `SUBCON_ISSUE_OUT` net of `ISSUE_RETURN_IN` and `SUBCON_RETURN_IN`, plus
`WASTAGE_OUT`, `SCRAP_OUT` (book value) and `ADJUST_OUT` (count and transit losses), less `ADJUST_IN`. It is charged
to the entry's `project_id`. Transfers and purchase returns are not consumption.

## Reports: `GET /api/store/reports/run/{code}?project_id&store_id&item_id&category&date_from&date_to&format=json|xlsx|pdf`

| Code | What |
|---|---|
| `stock-register` | Per store × item: opening (before `date_from`), in, out and closing, quantity and value |
| `valuation` | Quantity, average rate and value as on `date_to` (the ledger summed to that date) |
| `item-ledger` | Every movement with the store's position after it |
| `grn-register` | GRN, client-supply and purchase-return movements per document and item; a fully reversed document shows as Cancelled |
| `issue-register` | Issues and returns per document and item, with project, work order, BOQ item, cost head and subcontractor |
| `consumption` (`group=work_order\|boq_item\|cost_head\|subcontractor`) | Project-wise material consumption |
| `ageing` (`days=90\|180\|365`) | Stock held, aged against the receipts that brought it (newest first) into 0-90 / 91-180 / 181-365 / over 365 days, the last issue date, and non-moving where nothing went out in `days` days |
| `subcontractor-account` (`subcontractor_id`) | Issued and returned (from the ledger), recoverable (P3 `get_subcon_issues`, chargeable lines), recovered (noted against their bills), and still to recover |
| `transfers` | Sent, received and in transit per transfer and item, flagged when it crosses projects, plus P4 `get_in_transit` |
| `count-scrap` | P4 `get_count_variances` and `get_scrap_realisation` (book value against realised), plus the ledger's COUNT adjustments |

The project filter means a project's stores for stock reports, and the entry's project for consumption and issues.
Every report also exports to Excel (the workbook carries the filters and totals) and to PDF (landscape, under the
company's heading).

## Consumption norms: `store_consumption_norm`

A norm keys a **work-item code** to a material. The code is the BOQ line's item code, which is also the client work
order line's FG code and the subcontract item's code. A norm can optionally be pinned to one BOQ line. Each norm holds
a `coefficient` (base units of the material per unit of work, e.g. 425 kg of cement a cum of M25), a permissible
`wastage_pct`, and a `penal_rate` per base unit for excess recovered from a subcontractor (blank means the average issue
cost).

- **Routes:** `GET/POST /norms`, `PUT /norms/{id}`, `DELETE /norms/{id}` (retires the norm, never erases it),
  `GET /norms/template.csv`, `POST /norms/import[?apply=true]`, `GET /work-items`.
- **Import:** checks every row first. Saving updates an existing norm for the same code and material. Only one active
  norm per code, material and BOQ pin is allowed.
- **`get_theoretical_requirement(db, boq_item_id, item_id) -> Decimal | None`** (for P3): the BOQ line's quantity × the
  norm's coefficient, in base units, *without* wastage. A norm pinned to the line wins over the one for its code.
  It returns `None` without a norm. Over HTTP: `GET /norms/requirement`.

## Reconciliation: `GET /reconciliation?scope=project|work_order|subcontractor&scope_id&upto&project_id&category`

- **Theoretical** = quantity executed × coefficient. Executed quantity comes from the measurement books, read-only:
  - client work orders' `measurements` by FG code, for a project or work order;
  - subcontract orders' `sub_measurements` with kind "" (holds and releases are billing, not work), for a subcontractor.
- **Actual** = issued net of returns, to the project / work order / subcontractor.
- **Variance** = actual − theoretical.
- **Excess** = actual − (theoretical + wastage allowed).
- For a subcontractor, **recoverable** = excess × penal rate. When several norms use one material, the highest penal
  rate applies.

Tested example: a subcontractor did 10 cum of M25 at 425 kg + 2 % and used 4,400 kg net. Permitted is 4,335 kg, so
65 kg is excess, recoverable at ₹9.50 = **₹617.50**.

`GET /client-supply?project_id|work_order_id`: client-supplied material received (`CLIENT_SUPPLY_IN`), consumed (net
issued, capped at what was received), consumption by the norms, balance at site, and the value to recover in the client
RA bill at the receipt's own rate.

## Dashboard: `GET /dashboard`

Stock value by store, items below reorder level, in transit (P4), overdue returnables (P3), and frozen stores.

**Pending indents** and **GRNs pending QC** return `null` and show "once Outward / Inward publishes it": neither slice
publishes a count yet. See [requests/P5.md](requests/P5.md).

## Rights

`store.reports.view` reads. `store.reports.create` keeps the norms and notes recoveries. A person sees the stores they
are assigned to; asking for another store answers 403. The integration reads use the app's ordinary read access, the
same as the screens they sit in.

## Tests

- **`backend/tests/store/test_reports.py` (19):**
  - Each report and its netting.
  - Filters, exports, rights and store access.
  - Norms: CRUD, import, and the requirement.
  - Reconciliation by subcontractor, project and work order; client-supplied material.
  - Project cost and profit with the legacy cut-over.
  - The old receipt blocked; PO receipts and stocked bills; sub-bill recovery due and notes.
  - Dashboard; legacy handover.
- **`backend/tests/store/test_e2e.py` (1):** PO → GRN with QC rejection → purchase return → indent → issue to WO/BOQ →
  subcontractor free issue → partial return → inter-project transfer → count variance → reconciliation → project
  material cost → sub-bill recovery.
  - At every step each balance equals its ledger, and at the end ₹34,080 received = held + returned + consumed.
  - Until P2-P4 are merged, their documents are the ledger movements they post and their functions are mocked. After
    the merge, swap the `slice_*` helper for their services; the assertions stay.
