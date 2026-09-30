# Porting the current app (`/app.html`) to the new interface (`/next/`)

The two share one server and one database, so **no data moves**: a record made in
either shows in both. What is being ported is the screens.

The old app is removed only when every row below is done, verified in a real
browser, and the owner has said to go ahead.

Status: `done` · `todo`

## Clients
| Screen | Old view | Status |
| --- | --- | --- |
| Tender Pipeline | `leads-view` | todo |
| Tenders & Estimates | `estimates-view` | todo |
| Client Work Orders (build, budget, place, approve, material, sheet import) | `workorders-view` | done |
| Measurement & RA Bills (client side: book, statement, variations, bills) | `measurement-view` | done |
| Customers | `customers-view`, `customer-view` | todo |

## Money
| Screen | Old view | Status |
| --- | --- | --- |
| Payments & Ledgers | `ledger-view` | todo |
| Owed & Retention | `money-view` | todo |
| Supplier Bills | `bills-view` | todo |
| Client Invoices | `orders-view`? / invoices | todo |
| GST | `gst-view` | todo |
| Fixed Assets | `fixedassets-view` | todo |
| TDS, Guarantees & Advances | `registers-view` | todo |

## Store
| Screen | Old view | Status |
| --- | --- | --- |
| Item Master | `items-view` | done |
| Enquiries & Comparison | `rfq-view`, `inquiry-view` | todo |
| Purchase Orders | `orders-view`, `my-orders-view` | todo |
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
| Site Diary | `diary-view` | todo |
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
| Employees (+ detail, payslip) | `employees-view`, `employee-detail-view`, `payslip-detail-view` | todo |
| Attendance | `attendance-view` | todo |
| Departments | `departments-view` | todo |
| Leave | `leave-view` | todo |
| Payroll | `payroll-view` | todo |

## Everything else
| Screen | Old view | Status |
| --- | --- | --- |
| Command Center | `dashboard-view` | done |
| Approvals | `approvals-view` | done |
| Settings (letterhead, company, users) | `settings-view` | todo |
| Contacts | `contacts-view` | todo |
| Document viewer | `document-view` | todo |
| Staff self-service (overview, timesheet, costs, leave, payslips, documents) | `my-*-view` | todo |

## Pages outside `app.html`
Sign-in (`login.html`, `employee-login.html`, `superadmin-login.html`), `portal.html`
(partners), `employee-dashboard.html`, `hr.html`, `recruitment.html`, `onboard.html`,
`reset-password.html`, `meeting.html`, `superadmin.html`. Decide with the owner which of
these count as "the old app" before removing anything.
