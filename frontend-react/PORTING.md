# Porting the current app (`/app.html`) to the new interface (`/next/`)

The two share one server and one database, so **no data moves**: a record made in
either shows in both. What is being ported is the screens.

The old app is removed only when every row below is done, verified in a real
browser, and the owner has said to go ahead.

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
| Enquiries & Comparison | `rfq-view`, `inquiry-view` | todo |
| Purchase Orders (+ My Orders for staff) | `orders-view`, `my-orders-view` | done |
| E-way Bills | `eway-view` | todo |
| Goods Receipt & Match | `stores-view` | todo |
| Stock & Issues | `stock-view` | todo |
| Material Used vs Costed | `consume-view` | todo |

## Projects
| Screen | Old view | Status |
| --- | --- | --- |
| Projects (+ detail) | `jobs-view`, `job-detail-view` | todo |
| Programme & Progress | `schedule-view` | todo |
| Drawings & Photos | `drawings-view` | todo |
| Quality | `quality-view` | todo |
| Safety | `safety-view` | todo |
| Site Diary (record a day, labour and plant, photos, sign off, DPR, who has been on site) | `diary-view` | done; works offline (kept on the device, goes up by itself) |
| Project Chat | `chat-view` | todo |
| Equipment & Plant | `equipment-view` | todo |
| Project Profit | `pnl-view` | todo |
| Cost by Project | `project-costs-view`, `costs-view` | todo |
| Budget report | `budget-report-view` | todo |

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
| Settings (letterhead, company, users) | `settings-view` | todo |
| Contacts | `contacts-view` | todo |
| Document viewer | `document-view` | todo |
| Staff self-service (overview with clock, timesheet, costs, orders, leave, payslips, documents) | `my-*-view`, `employee-dashboard.html` | done; notifications, goals, team presence and profile of the old staff page are not ported |

## Pages outside `app.html`
Sign-in (`login.html`, `employee-login.html`, `superadmin-login.html`), `portal.html`
(partners), `employee-dashboard.html`, `hr.html`, `recruitment.html`, `onboard.html`,
`reset-password.html`, `meeting.html`, `superadmin.html`. Decide with the owner which of
these count as "the old app" before removing anything.
