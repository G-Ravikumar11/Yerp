# P2: Inward (gate, GRN, QC, returns, direct and client-supplied receipts)

Branch `store/p2-inward`, built on `store/p1-foundation`. It needs P1's hardened ledger, the `store_doc_status_log` table
and a few helpers from `routers/store_masters.py`, so **merge it after P1**. Migration `store_003_inward` (down revision
`store_001_core`) consists only of new tables, made by `create_all`; no shared table changes. Purchase-order tables are
read, never written.

Files: `models/store_inward.py`, `services/store_inward.py`, `routers/store_inward.py`,
`documents/store/inward_forms.py`, `frontend/src/features/store/inward/`, `backend/tests/store/test_inward.py`.

## Stock movements

| Document | Movement | `ref_doc_type` | Rate |
|---|---|---|---|
| GRN against a PO, or a direct receipt | `GRN_IN` | `GRN` | landed rate per base unit |
| Client-supplied material | `CLIENT_SUPPLY_IN` | `CLIENT_SUPPLY` | the agreed recovery rate (`work_order_id` set on the entry) |
| Purchase return of accepted material | `PURCHASE_RETURN_OUT` | `PURCHASE_RETURN` | `None` (valued at the average) |

`ref_doc_id` is the document's id and `ref_line_id` the line's id. Only accepted quantity posts. Rejected material never
enters stock, so returning it only produces a debit note. These are the paths P1's item card already links to:
`/store/hub/inward/grn/{id}`, `/client-supply/{id}` and `/returns/{id}`.

## Rules

- **Lifecycle:** DRAFT, then SUBMITTED, APPROVED and POSTED, with CANCELLED possible from any of them. Every change is
  written to `store_doc_status_log` with who, when and the reason. Posting is **one transaction** for every ready line;
  any refusal rolls all of it back.
- **Against a PO:** only *Approved* orders for the store's project are offered. A central store, which has no project,
  sees every approved order. **Pending = ordered − Σ accepted on posted GRNs.** Lines on GRNs not yet posted show as
  "in hand".
- **Units:** received, accepted, rejected and shortage are entered in any of the item's units and converted with
  `convert_to_base`. The PO's own unit (for example *bag*) is converted with the item's conversion; a PO unit with no
  conversion is reported against the line, never guessed.
- **Over-receipt:** a line may bring the order to at most ordered × (1 + `over_receipt_tolerance_pct`), counting what is
  already accepted and what other GRNs hold in hand. This is checked when the GRN is saved and again when it posts.
- **Landed rate (per base unit):**
  - Start from the PO rate ÷ the PO unit's factor.
  - Add the line's share of freight + loading + other charges. Charges are shared by received value, to the paisa; the
    last line takes the rounding.
  - Add GST **only when it is not recoverable**. The company setting can be overridden on a GRN. Recoverable input GST
    stays out of stock value.

  Worked example (tested): 100 bag of cement at ₹350 a bag and 500 kg of steel at ₹62, with ₹1,000 of charges. The
  charges split ₹530.30 / ₹469.70, so cement lands at ₹7.1061 a kg and steel at ₹62.9394.
- **Steel:** bundles, number of bars, diameter and bar length give the theoretical weight (d²/162 kg a metre × length).
  The variance is shown against the line's weighed kg, or against the gate entry's net weight when the GRN has one steel
  line. Example: 100 bars of 16 mm at 12 m = 1,896.296 kg theoretical, 1,900 kg weighed, +3.704 kg (+0.20 %).
- **Batch-tracked items** need a batch / heat number and an MTC reference before the GRN can be submitted.
- **Quality check:** items with `qc_required` go in as **QC_PENDING** with nothing accepted. An inspector
  (`store.inward.approve`) records accepted and rejected quantity, which must add up to what was received, plus the test
  type, a test reference (required) and remarks.
  - QC can be recorded before posting.
  - **On a posted GRN, the line posts when the QC is recorded**, dated today, because other movements may have followed
    the GRN date. That is how a GRN posts in parts.
- **Rejection memo:** numbered `RJM/<store>/<fy>/n` the first time anything on a GRN is rejected, and printable.
- **Purchase return** `PRN/...`, against a posted GRN, line by line:
  - `REJECTED` returns at most what was rejected. It is a debit only.
  - `ACCEPTED` returns at most what was accepted into stock, which then leaves stock.

  Nothing can be returned twice. `GET /returns/{id}/debit-note` gives the quantity, rate (the PO rate per base unit) and
  GST per line, with totals.
- **Direct receipt** (no PO): needs a reason and a named vendor, takes its rate per the entered unit and its GST, and is
  **approved by someone other than whoever raised it**. The account holder is exempt.
- **Client supply:** linked to a client work order of the store's project and valued at the agreed rate per base unit,
  kept in `store_client_supply_rate` per work order and item (Rates & settings). There is no rate on the contract tables
  to read, so the agreed rate is entered here, with its clause reference.
- **Cancelling a posted GRN** reverses it with `reverse_document`. If any of its stock has since been issued, it is
  refused with 409 and P1's message, e.g. *"Cannot reverse GRN 12: only 50 kg of ST-TMT12 TMT Steel 12mm is on hand in
  ST01 (Tower A Site Store); 500 kg is needed."* A GRN with a live purchase return needs that return cancelled first.
  Cancelling frees its gate entry.

## API: `/api/store/inward`

Rights: `store.inward.view`, `.create` (raise and submit), `.approve` (approve, QC, client rates, GST setting), `.post`,
`.cancel`. Every route that touches a store also checks access to it. Another company's records answer 404.

| Route | What |
|---|---|
| `GET ""` | `{"slice": "inward", "items": [latest GRNs]}` |
| `GET/PUT /settings` | `gst_recoverable` for the company |
| `GET/POST /gate`, `GET/PUT /gate/{id}`, `POST /gate/{id}/cancel` | Gate inward register: vehicle, vendor, PO, challan, time in, weighbridge slip, gross / tare / net |
| `GET /pos?store_id=`, `GET /pos/{id}/lines?store_id=` | Approved orders for the store, and each line's position (ordered, accepted, in hand, pending, tolerance, rate per base unit, GST) |
| `GET /pos/{id}/receipt-summary` | `get_po_receipt_summary` over HTTP |
| `GET /pending?group=po/vendor/lines` | Pending to receive, valued at the PO rate |
| `GET/POST /grn`, `GET/PUT /grn/{id}` | GRNs (`kind` PO / DIRECT / CLIENT_SUPPLY; `gate_entry_id` fills the challan and vendor). Only a draft can be edited. |
| `POST /grn/{id}/submit` / `approve` / `post` / `cancel` `{reason}` | The lifecycle |
| `POST /grn/lines/{line_id}/qc` | The inspector's result |
| `GET/POST /returns`, `GET /returns/{id}`, `POST /returns/{id}/{action}`, `GET /returns/{id}/debit-note` | Purchase returns |
| `GET /work-orders?store_id=`, `GET/POST /client-rates` | Client work orders and their agreed rates |
| `GET /grn/{id}/document.pdf`, `/qc.pdf`, `/rejection.pdf`, `GET /returns/{id}/document.pdf` | GRN (or client-supply receipt), QC report, rejection memo, purchase return / debit note |

## For P5: `get_po_receipt_summary(db, po_id) -> list[PoLineReceipt]`

One row per PO line, **in that line's own unit** (bags for a bag line), counting posted GRNs only:
`ordered_qty`, `received_qty`, `accepted_qty`, `rejected_qty`, `pending_qty = ordered − accepted` (never below 0). A line
whose material is not a stock item (no matching item code, or a unit with no conversion) shows what it ordered, nothing
received, and everything pending. An unknown PO gives `[]`. Purchase returns do not reduce `accepted_qty`.

## Screens: `/store/hub/inward`

GRNs (list, new, view), Gate register (with **Make GRN**), Pending (by order or by vendor), Returns (list and debit
note), and Rates & settings (client rates, input-GST setting).

The GRN form opens an order's open lines ready to fill in. Accepted is worked out as received − rejected. Steel and
batch fields sit on every line, and the theoretical weight shows as you type.

## Tests (`backend/tests/store/test_inward.py`, 15)

- Pending lines and unit conversion.
- Landed cost and the posted value; GST recoverable or not.
- Tolerance, including GRNs still in hand; line checks.
- Steel variance against the weighbridge; the gate entry being freed when its GRN is cancelled.
- Batch / MTC enforcement.
- QC waiting, posting later, and refusals.
- Cancelling: refused after an issue (409 naming the item and quantity), reversed otherwise.
- Purchase returns: limits, the debit-note figures, stock leaving only for accepted material, and the return blocking
  the GRN's cancel.
- Direct receipt: the reason and segregated approval.
- Client supply at the agreed rate.
- The receipt summary and the pending views.
- All four PDFs.
- Rights and wrong-store access.
