# Y ERP – team work plan (14 Nov 2026)

Who owns which tabs, what is broken or missing there, and how to fix it. Based on each person's commits and branches
up to 10 Nov, and a check of the app on 14 Nov.

**Priority:** P1 = do first (bug, or blocks daily use). P2 = this sprint. P3 = next.
**Rule for everyone:** branch from the latest `master`, one feature per commit, run backend tests + `npm run lint` +
`npm test` before pushing, never commit `backend/.env`.

## Who owns what

| Person | Tabs owned | Why (from their commits) | Load |
|---|---|---|---|
| **Raju** | Accounts (all of it), Tally | Finance Dashboard, payments, reconciliation tightening | Normal |
| **Nikhil** | Store (Desk + Hub), Equipment & Plant, BBS, email/sign-in, CI | Store Desk, holds, plant costs, Gmail, sign-in lock, CI shards | **Heavy** |
| **Hemanth** | Purchase (enquiries, POs, rate contracts, invoice tracker, supplier portal), Drawings, Document Control, Quality, Safety, look and feel | Purchasing controls, document control, store reports, UI theme | **Heavy** |
| **Abhi** | Phone app (Android + iOS), navigation, frontend tests and e2e | Whole phone app, enquiry comparison | **Heavy** |
| **Nihas** | People: employees, attendance, leave, payroll, Feed, My work | Payroll, HR role, celebrations, read-session speed-ups | Normal |
| **Uday** | Projects, Clients (BOQ, RA bills), Subcontractors, Command Center, merging and releases, business rules | BOQ, Job Lock, wastage, accounts builds, reviews | Lead |

## Do these first (whole team)

| # | Issue | Fix | Owner |
|---|---|---|---|
| 1 | Local `master` is 1 ahead (Wastage loss, not pushed) and 4 behind `origin/master` (Nikhil's CI fix and Nihas's payroll preview were merged on 10 Nov). | `git pull --rebase` (or merge), run the full suite, push. Until then nobody should build on Uday's local work. | Uday |
| 2 | Branches `abhi`, `hemanth`, `raju` are 30–39 commits behind `master` and have nothing unmerged. Starting work there will cause big conflicts. | Each person: `git checkout <branch> && git merge origin/master` before any new work. | Abhi, Hemanth, Raju |
| 3 | Dead branches on GitHub: `copilot/*` (2), `store/p1-foundation`, `store/p2-inward`, `store/p5-reports`, `subcontract-gaps`, `uday`, plus a remote branch literally named `origin`. | Confirm each is merged (`git branch -r --merged origin/master`), then delete. | Uday |
| 4 | Dashboard and bell items open the home page instead of their screen. 7 link names the backend sends are not mapped: `boq-view`, `equipment-view`, `jobs-view`, `quality-view`, `rfq-view`, `safety-view`, `store-issue-view`. | Add them to `attentionHref` in `frontend/src/api/dashboard.ts` (`/projects/boq`, `/projects/equipment`, `/projects`, `/projects/quality`, `/store/enquiries`, `/projects/safety`, `/store/hub/outward/issue`). Add a test that every `view=` in `backend/app` has a mapping. | Abhi |
| 5 | Repo root is cluttered: 6 `*.bundle` files, `money-*.patch`, `error-pages-preview/`, `logo-options/`. | Delete what is not needed; add `*.bundle` and `*.patch` to `.gitignore`. | Uday |

---

## Raju – Accounts

Recently added (by Uday, please learn these first): Journals & Debit Notes, Bank Payments & Cheques, MSME 45-day flags,
staff expense claims, the "To do today" card. Code: `backend/app/services/journals.py`, `payouts.py`,
`accounts_watch.py`; pages under `frontend/src/features/money/`.

| P | Gap | How to fix |
|---|---|---|
| P1 | **No trial balance or day book.** Accounts cannot check the books before sending to Tally. | Reuse `Books` in `services/tally.py`: it already builds every voucher as balanced ledger lines. Add `/api/reports/trial-balance` (sum debit and credit per ledger, with opening for a period) and `/api/reports/day-book` (vouchers of a day). New page `/money/books` with two tabs and Excel export. |
| P1 | **No opening balances for parties.** A supplier's or client's balance on the start date cannot be entered. | New table `party_openings` (party type, name, amount, as-on date, project). Add rows to `_ledger_rows` in `services/crm.py` and to Tally as an opening journal. Entry form on Ledgers & Bank → Parties. |
| P1 | **No single "New voucher" screen.** Payment, receipt, contra, expense, journal are on five different pages. | One modal opened from the Accounts menu and from a keyboard shortcut: pick the voucher type, then show the existing form for it (`PayModal`, `OnAccountModal`, expense voucher, transfer, `JournalModal`). No new backend. |
| P2 | **Recurring payments** (rent, internet, hire, insurance) are entered by hand each month. | Table `recurring_payments` (payee, head, project, amount, day of month, end date). A `@scheduled_job` creates a payment request each month, the same pattern as `job_recurring_invoices` in `services/invoicing.py`. |
| P2 | **Loans and EMIs** are not in the app at all. | Tables `loans` and `loan_instalments` (principal, interest split, due date). Paying an instalment books principal to the loan ledger and interest to an expense head. Add "EMI due this week" to `accounts_items()` in `services/accounts_watch.py`. |
| P2 | **A journal or debit note cancelled after export is not cancelled in Tally.** | In `Books._journals`, `_debit_notes`, `_claims`: when status is CANCELLED and `was_exported(...)` is true, call `self.cancel(...)` the way `_money` does for voided entries. |
| P2 | **Client advance recovery in Tally is inconsistent.** RA bills debit the `client_advance` ledger, but a receipt on account credits the client's own ledger. | Decide one treatment with Uday; simplest is to post client on-account receipts tagged as mobilisation advance to `client_advance`. Fix in `Books._money`. |
| P2 | **Purchase return with no supplier bill yet** stays on the "no debit note" list forever. | In `returns_without_note` (`services/journals.py`), allow "bill expected net of return" as a close reason, or raise the note on the supplier's account automatically after N days. |
| P3 | **GSTR-2B matching**, **TDS return (26Q) and Form 16A**, **cash flow forecast**, **month-end close checklist**. | Build in that order. 2B: upload the portal's Excel, match on GSTIN + invoice number + amount against `DBBill`. 26Q: TDS already sits on contractor bills; export the quarter in the return's layout. Forecast: due dates of payables, receivables, PDCs, salaries, recurring payments by week. Close: checklist that ends with the existing books lock. |
| P3 | **Free-form credit note** to a client is not possible (only line-by-line from an RA bill). | Mirror `DBSupplierDebitNote` for the client side. |
| P3 | **Bank file layouts are untested against a real bank.** | Upload one small real file per bank used; correct `file_rows()` in `services/payouts.py` if the bank rejects it. |

---

## Nikhil – Store, Plant, BBS, email and sign-in (heavy)

| P | Gap | How to fix |
|---|---|---|
| P1 | **App emails do not come from the new domain.** Domain `yalavartiinfra.com` is live on Railway and Zoho mail is set up. | Finish DKIM in Zoho. In the company Gmail add "Send mail as" `erp@yalavartiinfra.com` through `smtp.zoho.in`. Then set the sender in Settings and send a test. Update the app's public base URL so links in emails use the new domain. |
| P1 | **Wastage loss only shows where a limit exists.** Most BOQ items have no store norm, so non-steel wastage shows "None" even when material is wasted. | Add an Excel import for norms (BOQ item, material, qty per unit, wastage %) on Store → Hub → Reports → Norms, and a "copy norms from another project" button. Code: `DBStoreMaterialNorm`, `routers/store_reports.py`. |
| P1 | **Old store screens still exist** at `/store/old/*` (stock, material vouchers, material costing, goods receipt) and confuse users. | Confirm with Uday nothing still writes there, then remove the routes and menu links; keep the tables. |
| P2 | **Two wastage percentages.** Budgeting has its own wastage %, the store norms have another. They can disagree. | Make Budgeting read the norm's wastage % when a norm exists; show a warning where the two differ. |
| P2 | **Low stock needs manual follow-up.** The reorder check now runs every morning, but someone still has to raise the enquiry. | On the low-stock list add "Raise indent / enquiry for all selected", pre-filled with reorder quantity. Auto-clear the alert when stock is back above the level (check `raise_reorder_alert` in `services/stock_ledger.py`). |
| P2 | **Free-issue material to contractors has no allowance.** Steel has BBS + 2%; material issued to a contractor has no limit. | Reuse the steel pattern (`services/steel_allowance.py`, `_steel_allowance` in `store_outward.py`): limit = norm for the contractor's work-order quantity; past it, approval by the Master. |
| P2 | **Cross-charges reversed after adjustment do not reach Tally.** Only `ADJUSTED` rows are exported. | In `Books._cross_charges` add a reversing journal for `REVERSE` rows; needs a `reversed_on` date on `DBStoreCrossCharge`. |
| P2 | **Steel in items counted in numbers is not checked** (the BBS page lists them as "not weighed"). | Add weight per piece on the item, or block steel items whose unit is not kg or MT. |
| P3 | **Plant:** monthly "unbilled rentals" alert exists; add the same for machines idle more than N days and for fuel per hour out of range. | `services/plant_checks.py`. |
| P3 | **CI runs `pytest -q` in one process.** Locally the suite takes 20 minutes in 6 shards. | Confirm CI uses the six-share runner from his 10 Nov commit; fail the build on any skipped shard. |

---

## Hemanth – Purchase, Drawings, Documents, Quality, Safety, look and feel (heavy)

| P | Gap | How to fix |
|---|---|---|
| P1 | **Accounts retype every supplier bill.** The store's goods receipt already has supplier, PO, items, quantities and rates. | "Create bill from receipt" on the Invoice Tracker and on a posted GRN: draft `DBBill` with lines, PO link and project filled in, status Draft, for accounts to check and accept. Refuse a second bill for the same receipt quantity. |
| P1 | **MSME status is typed by hand** and will be missed. | Ask for MSME type and Udyam number on the supplier portal and on the enquiry reply form; show an "MSME" badge on POs and on the comparison sheet. Fields already exist: `suppliers.msme_type`, `udyam_no`. |
| P2 | **Suppliers without bank details block the bank payment file.** | Collect bank account + IFSC on the supplier portal; list "suppliers with no bank details" on the Suppliers tab. |
| P2 | **Rate contracts are not applied automatically.** | When a PO line's item has a live rate contract for that supplier, fill the rate and flag any line above it (he built the price check; extend it). |
| P2 | **Take-off quantities stop at the screen.** Quantities from a drawing cannot become a BOQ, an indent or an enquiry. | Buttons on `TakeoffModal.tsx`: "Send to BOQ lines" and "Raise enquiry". Also accept DWG by converting to DXF on the server if a converter is available. |
| P2 | **Quality and safety alerts have no owner or due date follow-up.** | NCRs, permits and incidents: add assignee + due date, and a daily reminder to the assignee (pattern: `job_doc_control_reminders` in `services/doc_control.py`). |
| P2 | **Late-delivery chasers.** The late list exists; the supplier is not told. | Automatic email to the supplier on the needed-by date and every 3 days after (supplier chasers are allowed to be automatic). Reuse `services/rfq_chasers.py`. |
| P3 | **Look and feel is uneven on new pages.** Journals, Bank Payments, Claims use plain tables; older pages use cards and stat tiles. | One pass over `frontend/src/features/money/`: same header, filters row, empty states, mobile column hiding as `OwedPage.tsx`. |
| P3 | **Document control:** transmittals and drawing approvals cannot be decided from the Approvals inbox. | Add kinds to `approval_inbox()` and the decide route, as done for `journal` and `steel_issue`. |

---

## Abhi – Phone app, navigation, tests (heavy)

| P | Gap | How to fix |
|---|---|---|
| P1 | **Fix the 7 dead links** (item 4 at the top). | See above. |
| P1 | **Phone app still points at the old server address.** | Change the server URL to `https://yalavartiinfra.com`, rebuild Android and iOS, publish. Keep the old address working until everyone has updated. |
| P1 | **New approvals are not on the phone.** `ApprovalsCards.tsx` does not know "Steel over BBS" or "Expense claim". | Add cards for kinds `steel_issue` and `expense_claim` (approve / refuse with reason). Journals stay Master-only. |
| P1 | **Staff cannot claim expenses from the phone.** The web page exists at `/me/claims`. | Add "Expense claim" to the + sheet (`AddSheet.tsx`): amount, head, project, camera photo of the bill; put it in the offline queue like site cash. |
| P2 | **Attendance can still be faked on a phone.** Server checks distance and accuracy; a mock-location app passes. | Native check for mock location (Android `isFromMockProvider`, iOS jailbreak signals) and an optional selfie at clock-in, sent with the punch. Server side: `job_lock_check` in `services/employee_portal.py`. |
| P2 | **Push notifications open the app but not the right screen.** | Use the `link` already sent with each notification (`/next/...`) to deep-link on tap. |
| P2 | **Almost no frontend tests for money screens.** 37 unit test files in total; none for Pay & Receive, Journals, Bank Payments, Claims, BBS, Safety. 89 e2e files, none for the pages added since 8 Nov. | Add e2e scripts for: raise and approve a journal; debit note on a bill; payment file → mark paid; expense claim → approve → pay; steel issue over 2% → approve. Add unit tests for the modals' validation. |
| P2 | **No test that menu, routes and page info agree for the phone layout.** | Extend `lib/nav.test.ts` to cover `app-mobile` routes. |
| P3 | **Storekeeper flows on the phone:** issue against an indent, and receive against a PO with barcode or QR scan. | New + sheet actions calling the Store Desk APIs. |

---

## Nihas – People, payroll, attendance, Feed

| P | Gap | How to fix |
|---|---|---|
| P1 | **Staff advances are not recovered through payroll.** Accounts enter a manual "Adjustment" receipt. | Payroll run: show each person's advance balance (`staff_balance()` in `services/payouts.py`), let HR set the month's deduction, and on release post a receipt (mode Adjustment) against the staff ledger so the balance drops. Work with Raju on the ledger side. |
| P1 | **Approved expense claims can only be paid by bank.** | Option "pay with salary": add the approved amount to that month's payslip as a non-taxable reimbursement and mark the claim settled. |
| P2 | **Two bank files.** Salaries use `documents/neft.py` (one plain layout); supplier payments use `services/payouts.py` (HDFC, ICICI, SBI, Axis). | Make the salary file use `file_rows()` from `payouts.py` so payroll gets the same bank layouts. |
| P2 | **Full-and-final settlement** does not net off advances held and claims owed. | Include both in the settlement sheet (`services/settlement.py`). |
| P2 | **Site Lock refusals are stored but nobody reviews them.** | Weekly summary to HR: who was refused, where, how often; one-click "allow this person at this site". Page: `features/attendance/JobLockTab.tsx`. |
| P3 | **Payroll to accounts:** salaries paid are posted to "bank account not recorded" in Tally. | On marking a month paid, ask which bank account and record it, so Tally gets the real bank ledger (`Books._payroll`). |
| P3 | **Feed media is stored in the database** (up to 6 photos or videos a post). It will bloat backups. | Move to file/object storage, keep the range-served endpoint. |

---

## Uday – Projects, Clients, Subcontractors, releases

| P | Item |
|---|---|
| P1 | Pull, test and push the Wastage loss commit (item 1). |
| P1 | Decide the open business rules people are waiting on: client advance treatment in Tally (Raju), free-issue allowance for contractors (Nikhil), whether MSME bills past 45 days should need Master approval to pay (currently only flagged). |
| P2 | Enter store norms for the main BOQ items of live projects, or wastage loss will show only steel. |
| P2 | Project Profit: add "Wastage loss" to the project's own page and to the Excel workbook (`/api/jobs/{id}/pnl.xlsx`), not only the list. |
| P2 | Subcontractor RA bills: show the contractor's MSME 45-day date on the bill page (it is only on Pay & Receive today). |
| P3 | Review and merge everyone's work twice a week; keep `master` green. |

## Suggested order for the next two weeks

1. **Days 1–2:** the five "do these first" items; everyone syncs their branch.
2. **Week 1:** all P1 rows.
3. **Week 2:** P2 rows; Abhi's e2e tests land alongside each feature.
4. **After:** P3.

*Not verified in this check:* whether CI already uses the six-share test runner, and whether a "raise enquiry" button
already exists on the store's Reorder report (the alert text refers to one). Owners should confirm before building.
