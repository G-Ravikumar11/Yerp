# Y ERP: what is left, split for five people

Written 26 Oct 2026 from the code on master (5e3d45fb) and `docs/YERP-Master-Plan.md` (modules M1 to M38).
"Missing" means a keyword search of the backend, frontend and mobile folders found nothing for it; "partial" means some
of it exists. Nobody opened every screen, so check the start of each item before building it.

## What is already built (do not redo)

Tenders and estimates, BOQ, work orders, measurement book, client RA bills, subcontractor RA bills with recoveries and
compliance, planning and progress (programme, Gantt, baseline), site diary, quality (inspections, cubes, NCR), safety
(incidents, toolbox talks, work permits, worker screening), equipment and plant (assets, fuel, rentals), the Store Hub
(masters, inward, outward, control, reports, indents, reservations, cycle counts, tools, rejections), enquiries and
comparison, purchase orders, accounts (vouchers, payment approval, site cash, bank reconciliation, cheque register,
Tally export), GST and TDS registers, people and payroll basics, partner portal, AI planning, sign-in protection.

## Rules for five people working at once

1. **One owner per area.** Each package below owns its files. Do not edit another package's files; ask the owner.
2. **Shared files** (`models/__init__.py`, `routes.tsx`, `nav.ts`, `pageInfo.ts`, `bootstrap.py`, `permissions.py`,
   `migrations.py`): add your lines at the end of the list, keep the change small, and merge master into your branch
   before you push, so these never conflict.
3. **One branch per package**, merged to master by the owner once the full suite passes. Master stays green.
4. **Sign-in, sessions, passwords, permission keys** are Uday's only (the master plan's firm rule). Package E asks him.
5. Every item ships with tests; each new screen gets a line in `lib/pageInfo.ts` (a test fails without it).
6. The two stock systems, the Store Hub and the old store under `/store/old/*`, must not both get new features: new
   work goes in the Hub (package C retires the old one).

---

## Package A: Client contract and billing (commercial)

| Item | State | What to build |
|---|---|---|
| M12 Client billing v2 | missing | Secured advance on materials at site (recovered as consumed), price escalation clause, deviation limit, withheld amounts, the final bill. Fits the existing RA bill form. |
| M11 Contract master and key dates | partial | One contract record per project: dates, DLP, retention terms, LD, and a key-dates list with reminders. |
| M14 Claims | missing | Extension of time and cost claims: notice dates, evidence (diary, photos, hindrances), claim value, status, a claim letter PDF. Needs package B's hindrance register. |
| M13 Document control | missing | Transmittals, RFIs, submittals with due dates and status, linked to drawings. |
| M34 Client portal | missing | Read-only view for the client (progress, bills, drawings); the sign-in side is Uday's, the screens and data are yours. |

Files: `services/client_billing.py`, `routers/client_*.py`, `features/clientbook`, `features/clientorders`, `features/drawings`.

## Package B: Site operations

| Item | State | What to build |
|---|---|---|
| M1 Cost codes and work breakdown | missing | A cost code tree per project that BOQ lines, indents, issues, bills and labour all carry, so cost can be read by code. |
| M18 Hindrances and delays | missing | Hindrance register (cause, dates, impact, who is responsible), feeding programme delay and package A's claims. |
| M17 Labour | partial | Labour register, wages, and the statutory registers (muster roll, wage register, contract labour records). |
| M37 Project control, earned value | missing | Planned value, earned value, actual cost, CPI and SPI per project from the programme and the cost codes. |
| M19/M20 Quality and safety v2 | partial | Failed lot blocks the store (with C), safety observations, audits, corrective-action tracking, monthly safety statistics. |
| M16 Daily progress report | partial | Phone-first daily report and a PDF for the client; check the diary against the master plan list. |

Files: `routers/projects.py`, `programme.py`, `quality.py`, `safety.py`, `features/schedule`, `diary`, `quality`, `safety`.

## Package C: Supply chain and plant

| Item | State | What to build |
|---|---|---|
| Indent to enquiry to PO | gap | One-click: an approved indent becomes an enquiry, the award becomes a PO that remembers its indent lines. |
| Bill check against Hub receipts | gap | Three-way match: PO, goods receipt in the Hub, supplier bill; flag differences before payment. |
| Retire the old store | gap | Move or remove `/store/old/*`, one reorder level, a simpler Store menu, one-step small issues. |
| M24 Scaffolding, shuttering, plant hire | missing | Stock and hire of reusable material by project, with return and loss tracking. |
| M25 Equipment v2 | partial | Hour meter readings, breakdowns, utilisation, service schedule alerts. |
| M26 Bar bending schedules | missing | BBS entry, steel weights, cutting list PDF, link to steel issues. |
| M36 Vendor portal | partial | Suppliers see their POs, delivery dates and payments (the quote link already exists); the sign-in side is Uday's. |

Files: `services/store_*.py`, `routers/store_*.py`, `routers/procurement.py`, `features/store`, `rfq`, `purchaseorders`, `equipment`.

## Package D: Money and statutory compliance

| Item | State | What to build |
|---|---|---|
| M33 Payroll statutory | missing | PF, ESI, professional tax, TDS on salary, ECR file, Form 16, payslip changes. |
| M32 GST and TDS reconciliation | missing | Match purchase GST to GSTR-2B, TDS deducted against Form 26AS, challan tracking, return-ready exports. |
| M28 Cash flow forecast | missing | Receipts due and payments due by week from bills, retention and payment requests, with a project and company view. |
| M27 Subcontractors v2 | partial | Contractor performance score, advance recovery plan, rate comparison between contractors. |
| Accounts polish | gap | Trial balance and P&L reports from the books (Tally keeps the final books today), credit notes in the Tally export, retention releases in the export. |

Files: `routers/payroll.py`, `services/money.py`, `tally.py`, `routers/money.py`, `features/payroll`, `gst`, `registers`, `ledger`.

## Package E: Platform and security (needs Uday for sign-in parts)

| Item | State | What to build |
|---|---|---|
| Two-step sign-in (2FA) | missing | Authenticator code for the Master and anyone with money rights. Uday's area. |
| M8 Backups, staging, monitoring | missing | Scheduled database backups with a restore test, error alerts, a staging copy, and the full suite run on Postgres in CI. |
| M4 Phone app and offline | partial | Offline queue for site forms (diary, measurement, site cash, attendance), conflict handling, the Android and iOS builds. |
| M5 Languages | missing | A translation framework, Telugu and Hindi for the site screens first. |
| M2 Approvals v2 | partial | Delegation when someone is away, escalation after N days, reminders. |
| M6/M7 Documents and report builder | missing | Digital signature on PDFs, a saved-report builder that all modules can use. |
| M38 Portfolio analytics | missing | Last, after A and B: delay and cost prediction. |

Files: `core/*`, `bootstrap.py`, `.github/workflows`, `mobile/`, `features/settings`, `lib/*`.

## Suggested order

1. **First week:** A (M12), B (M1 cost codes), C (indent to PO, bill check), D (M33 payroll statutory), E (backups and monitoring, 2FA).
2. **Second week:** A (M11, M13), B (M18, M17), C (retire old store, M24), D (M32, M28), E (M4 offline, M2).
3. **Last:** M14, M37, M26, M34, M36, M5, M6, M7, M38.

Dependencies: C's and B's cost codes (M1) before D's cost reports; B's hindrances (M18) before A's claims (M14); client and vendor portals wait for E's sign-in work.

## Already known issues to close first (small)

- Rotate every Railway variable (the platform's own incident notice): database, SECRET_KEY, API keys. Not code.
- The address-fix middleware (`core/login_guard.py`) works around `--forwarded-allow-ips='*'` in `railway.json`; fix at the start command when a trusted proxy range is known.
- Payment approval and CAPTCHA settings are live but default off or built-in: switch on payment approval in Settings and add Turnstile keys.
