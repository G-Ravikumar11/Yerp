# Porting the old app (`/app.html`) to the new interface (`/next/`) - finished, and the old app removed

The two share one server and one database, so **no data moves**: a record made in
either shows in both. What is being ported is the screens.

Every screen was ported and checked in a real browser, and the owner confirmed on 2026-10-01 that
the old app should go. It is removed: `frontend/` keeps only the pages below, and `app.html`,
`hr.html` and `employee-dashboard.html` are small forwards to `/next/`. It is all in git history
if anything has to be recovered.

Status: `done` · `todo`

## Clients
| Screen | Old view | Status |
| --- | --- | --- |
| Tender Pipeline (board, EMD register, decided) | `leads-view` | done |
| Tenders & Estimates (rate build-up, win to work order) | `estimates-view` | done |
| Client Work Orders (build, budget, place, approve, material, sheet import) | `workorders-view` | done |
| Measurement & RA Bills (client side: book, statement, variations, bills) | `measurement-view` | done |
| Customers | `customers-view`, `customer-view` | done |

## Money
| Screen | Old view | Status |
| --- | --- | --- |
| Payments & Ledgers (parties, statements, receipts, bank book, suppliers) | `ledger-view` | done |
| Owed & Retention (receivables, payables, retention releases) | `money-view` | done |
| Supplier Bills (accept, pay, Excel import) | `bills-view` | done |
| Client Invoices | legacy: hidden in the old app (`invoices-view`, `legacy-hidden`) - not ported, removed from the menu | n/a |
| GST (outward, inward, GSTIN) | `gst-view` | done |
| Fixed Assets (register, books, tax blocks) | `fixedassets-view` | done |
| TDS, Guarantees & Advances | `registers-view` | done |

## Store
| Screen | Old view | Status |
| --- | --- | --- |
| Item Master | `items-view` | done |
| Enquiries & Comparison | `rfq-view`, `inquiry-view` | done (new enquiry or from a work order, quotes, comparison with landed cost, award makes draft orders) |
| Purchase Orders (+ My Orders for staff) | `orders-view`, `my-orders-view` | done |
| E-way Bills | `eway-view` | done (typed or drawn from a transfer, what the portal would refuse, issued number, vehicle change, cancel) |
| Goods Receipt & Match | `stores-view` | done (receive against an order, reject part, post, bill from what arrived, three-way match) |
| Stock & Issues | `stock-view` | done (ledger, count, issue to site with optional charge to a gang, post, cancel, send to another store) |
| Material Used vs Costed | `consume-view` | done |

## Projects
| Screen | Old view | Status |
| --- | --- | --- |
| Projects (+ detail) | `jobs-view`, `job-detail-view` | done (board, project page, form with site location and GST state) |
| Programme & Progress | `schedule-view` | done (bars, S-curve, activities after one another, progress by hand or from a work order line) |
| Drawings & Photos | `drawings-view` | done (drawings register with revisions and status, project photos and files) |
| Quality | `quality-view` | done (inspections walked item by item, cube sets and results, NCRs, photos, PDFs) |
| Safety | `safety-view` | done (incidents with cause and fix, toolbox talks, permits to work, photos, PDFs) |
| Site Diary (record a day, labour and plant, photos, sign off, DPR, who has been on site) | `diary-view` | done; works offline (kept on the device, goes up by itself) |
| Project Chat | `chat-view` | done (threads, photos, @names, close and reopen, unread counts) |
| Equipment & Plant | `equipment-view` | done (register, deploy and move, log a day, service, history) |
| Project Profit | `pnl-view` | done |
| Cost by Project | `project-costs-view`, `costs-view` | done (list and each project with the papers behind the figures) |
| Budget report | `budget-report-view` | done (a Report button on every budgeted client work order: sold lines, what each consumes, unbudgeted lines flagged, margin, workbook, print) |

## Subcontractors
| Screen | Old view | Status |
| --- | --- | --- |
| Vendor Register | `vendors-view` | done |
| Work Orders (+ builder, documents) | `subcontracts-view`, `subcontract-wizard-view`, `subcontract-document-view` | done (documents: check) |
| Measurement Book | `subbills-view` (MB tab) | done |
| RA Bills | `subbills-view` (bills tab) | done |

## People
| Screen | Old view | Status |
| --- | --- | --- |
| Employees (list, add, edit, access, password, start leaving) | `employees-view`, `employee-detail-view` | done; the detail's goals, documents and the leaving checklist are still todo |
| Attendance (today, history, analytics, overtime, settings) | `attendance-view` | done; the AI alerts and AI summary are not ported |
| Departments (the owner's own list, reflected on employees, work orders and staff) | `departments-view` | done |
| Leave (decide requests) | `leave-view` | done |
| Payroll (payslips, run for everyone, detail, pay, email, print) | `payroll-view`, `payslip-detail-view` | done; the PDF is the browser print of a plain payslip, not the old jsPDF one |

## Everything else
| Screen | Old view | Status |
| --- | --- | --- |
| Command Center | `dashboard-view` | done |
| Approvals | `approvals-view` | done |
| Settings (company, logo, bank, tax rates, letterheads, signatures, conditions, approval rules, staff domain, team, partner logins, alerts, backup, activity log) | `settings-view` | done; the hidden legacy blocks (Gmail connect, invoice templates, demo mail) are not ported |
| Contacts | `contacts-view` | done (list, search, add, edit, delete; under Clients). The old customer history page behind a contact was invoice-based (legacy) and is not ported |
| Document viewer | `document-view` | not needed: it only framed the server PDF. Every screen now opens its own PDF (bill, order, purchase order, statement, slips) in a tab; Goods Receipt has its own screen |
| Staff self-service (overview with clock, timesheet, costs, orders, leave, payslips, documents) | `my-*-view`, `employee-dashboard.html` | done; notifications, goals, team presence and profile of the old staff page are not ported |

## Sign-in
One sign-in door (`login.html`) and `employee-login.html` send the owner and staff to `/next/`.

## Pages that stay in `frontend/`
Sign-in (`login.html`, `employee-login.html`, `superadmin-login.html`), `reset-password.html`, `onboard.html`,
`portal.html` (partners), `superadmin.html`, `recruitment.html` (the public application form), `jobs.html`
(the public job board) and `meeting.html`. They are separate from the ERP screens and were not rebuilt.

## Gone with the old app, not rebuilt
- Recruitment management (vacancies and applications): it was only in the hidden legacy part of the old app and in `hr.html`. The server side still exists.
- The old invoicing, quotes, recurring invoices and reports screens (legacy, hidden in the old app).
- Staff goals, team presence and profile on the old staff page; attendance AI alerts and summary.
- The old customer history page behind a contact (invoice based).
