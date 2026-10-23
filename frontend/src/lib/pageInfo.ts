/**
 * What each screen is for, in a few lines: shown from the (i) button in the top bar. Keyed by the screen's address;
 * a screen with an id in it ("/projects/:id") is a detail page of the list it sits under.
 */
export const PAGE_INFO: Record<string, string> = {
  '/': 'Your front page. The money, progress and attention items across every project, and a link into each portal. For staff it is Overview: your own work, leave and what is waiting on you.',
  '/calendar': 'India\'s public holidays and the days off this business has added. The Master can mark one day or a run of days; every employee has them off for leave, attendance and payslips.',
  '/ho': 'Head Office\'s front page: every site\'s vendors, work orders, BOQs and bills in one place, and what is waiting on whom.',
  '/approvals': 'Everything waiting for your decision - bills, work orders, leave and the like. Open one, look at it, and approve or send it back with a reason.',

  '/me/timesheet': 'Record the hours you worked on each project and day, and send the week for approval.',
  '/me/costs': 'Claim what you spent on site - fuel, materials, travel - with the bill attached, and follow it to payment.',
  '/me/site-cash': 'The cash box you hold for the site: enter each payment as you make it with a photo of the bill, see what should be in hand, and print the cash book.',
  '/me/orders': 'The work orders and purchase orders you raised or are responsible for, and where each one stands.',
  '/me/leave': 'Your leave balance, your requests and their status. Apply for leave here; holidays and days off are not counted against you.',
  '/me/payslips': 'Your payslips month by month, with earnings, deductions and the working days they were based on.',
  '/me/documents': 'Your own documents - letters, certificates and anything HR has asked you for - kept in one place.',
  '/me/goals': 'The goals set for you and how far along each is. Update your progress as you go.',
  '/me/onboarding': 'The steps to finish when you join: forms, documents and introductions. Each step ticks off as it is done.',
  '/me/team': 'Who you work with and who you report to, with their roles.',
  '/me/profile': 'Your own details - contact, address, bank and emergency contact. Keep them current; payroll uses them.',

  '/projects': 'Every project with its client, status and money in and out. Open one for its orders, bills, diary and progress.',
  '/projects/:id': 'One project: its client, budget, orders, bills, team and what has been done to date.',
  '/projects/programme': 'The programme: activities, sub-items and their dates as a grid and a chart. Draw it from the BOQ, record progress by quantity, save a baseline and export it to Excel or PDF.',
  '/projects/programme/:job/activity/:id': 'One activity of the programme: its dates, quantities done, and the tasks and diary entries against it.',
  '/projects/drawings': 'The drawings register. Every revision is kept, and the latest is always the one to build to.',
  '/projects/quality': 'Quality control: inspection checklists, cube tests and non-conformance reports (NCRs) with who must fix what and by when.',
  '/projects/safety': 'Workers and Safety. Workers: every worker screened before they start. Safety: incidents, toolbox talks, permits to work, safe days and the equipment checklists.',
  '/projects/diary': 'The site diary: one entry a day with weather, labour, plant, work done, hold-ups and visitors. A signed-off day is changed only with a reason, and the change is kept.',
  '/projects/chart': 'The project chart: every activity as a bar against time, to see what is running, late or next.',
  '/projects/equipment': 'Equipment & Plant: machines and vehicles, where each one is, service due dates, fuel and rentals.',
  '/projects/profit': 'What each project has earned against what it has cost, so you can see where money is made or lost.',
  '/projects/costs': 'The cost of each project by head - materials, labour, subcontract and plant. Open one for the lines behind it.',
  '/projects/costs/:id': 'The costs of one project, line by line, by head and by month.',
  '/projects/boq': 'The Bill of Quantities. Each BOQ has revisions (tender, award, variations), so what it said when an order was placed is never overwritten.',
  '/projects/boq/:id': 'One BOQ: its sections and items with quantities and rates, its revisions, and variations to raise.',

  '/clients/pipeline': 'Tenders and leads as they move from enquiry to won or lost, so nothing sits forgotten.',
  '/clients/estimates': 'Tender estimates: price a job line by line, compare versions and turn a won tender into a project.',
  '/clients/estimates/:id': 'One estimate: its lines, rates and totals, and the versions behind it.',
  '/clients/measurement': 'Measure the work done for the client and raise running-account (RA) bills against the BOQ.',
  '/clients/work-orders': 'The work orders the client has placed with you, with what is billed against each.',
  '/clients/work-orders/:id/budget-report': 'What one client work order allows against what it is costing, and where the budget is going.',
  '/clients/customers': 'Your customers with their GST details, projects and what they owe.',
  '/clients/contacts': 'The people at your clients and prospects - who to call, and for what.',

  '/subcontractors/vendors': 'Sub Contract Registration: the subcontractors you work with, their papers, rates and trades.',
  '/subcontractors/work-orders': 'Work orders placed with subcontractors: the scope, rate and value of each, and where it stands in approval and progress.',
  '/subcontractors/work-orders/:id': 'One subcontract work order: its items, approvals, measurements and bills.',
  '/subcontractors/measurement-book': 'The subcontractors\' measurement book: record work done against each work order, to be checked and billed.',
  '/subcontractors/ra-bills': 'Running-account bills from subcontractors: certify what is measured, apply deductions and retention, and send for payment.',
  '/subcontractors/ra-bills/:id': 'One RA bill: the measured work, deductions, retention and what is payable.',
  '/subcontractors/registers': 'Recoveries and kinds of work: the material issued to contractors and taken back off their bills, and the kinds of work that orders are raised for.',
  '/subcontractors/compliance': 'Each subcontractor\'s statutory papers - registrations, insurance, licences - with expiry dates so nothing lapses unnoticed.',

  '/store/items': 'The Item Master: every material and consumable with its unit, code and rate. Orders, stock and costing all use this list.',
  '/store/enquiries': 'Send an enquiry to several suppliers and compare their quotes side by side before ordering.',
  '/store/enquiries/:id': 'One enquiry: the items asked for, the suppliers asked and their quotes side by side, and the award that makes the purchase orders.',
  '/store/purchase-orders': 'Purchase orders to suppliers: what was ordered, at what rate, what has arrived and what is billed.',
  '/store/eway': 'E-way bills for goods moving between places, with their validity so a load is never on the road without one.',
  '/store/old/goods-receipt': 'Record what actually arrives against a purchase order and match it to the order and the supplier\'s bill.',
  '/store/old/material-vouchers': "The store's Material Issue Voucher, as on the printed form: project, who indented it, who issued it and for what, and each item issued and returned. Every voucher is kept in Sl. No. order, to print as a PDF or download as an Excel register.",
  '/store/hub': 'The Store module: stock held at each store and everything that moves it. Open a part below.',
  '/store/hub/masters/*': 'Stores, bins, who works where, item stock settings and unit conversions.',
  '/store/hub/enquiry/*': 'What each store holds, and the movements behind every balance.',
  '/store/hub/inward/*': 'Goods received against purchase orders, quality checks and returns to suppliers.',
  '/store/hub/outward/*': 'Issues to site and to subcontractors, returnable tools and write-offs.',
  '/store/hub/control/*': 'Transfers between stores, stock counts, adjustments and scrap.',
  '/store/hub/reports/*': 'Stock, consumption and material cost reports.',
  '/store/old/stock': 'Stock on hand at each store, receipts, and issues to site. Issue material to a project and the balance falls.',
  '/store/invoice-tracker': 'Purchases by trade and supplier invoice, with each bill checked against what was received, plus a ready-mix register by lorry and block.',
  '/store/old/material-costing': 'Material used on site against what was costed, so overuse and wastage show up early.',

  '/money/ledgers': 'Payments and ledgers: what has been paid to or received from each party, and the running balance.',
  '/money/owed': 'What is owed to you and by you - with ageing and retention held - so you know who to chase and when to pay.',
  '/money/supplier-bills': 'Bills from suppliers: enter, check against the order and receipt, approve and pay.',
  '/money/gst': 'GST on sales and purchases for the period, and what is payable or claimable.',
  '/money/assets': 'Fixed assets with cost, depreciation and book value.',
  '/money/registers': 'TDS, bank guarantees and advances: the registers you must keep, with amounts and due dates.',
  '/money/tally': 'The period for the books in Tally Prime: an XML of ledgers and projects (cost centres) to import first, then one of vouchers - receipts, payments, expenses, transfers, client and contractor RA bills and supplier bills.',
  '/money/site-cash': 'The cash box of each site: what it should hold, what the site spent and is waiting to be checked, accepting or rejecting it against the bill, and topping the float back up.',

  '/people/employees': 'Everyone who works for you: details, role, sites, pay and, under Access, what each person may see and do.',
  '/people/employees/:id': 'One employee: their details, documents, pay, leave and - under Access - their portals and permissions.',
  '/people/departments': 'Departments are set per site. Choose a site, press Edit to add or remove its departments, and open one to see its people as a chart by level.',
  '/people/attendance': 'Who is in, absent, late or on leave today, with history and overtime. Holidays are not counted as absent.',
  '/people/leave': 'Leave requests waiting for you, and the leave taken across the business. Approve or decline with a reason.',
  '/people/payroll': 'Run the month\'s payroll: working days, earnings and deductions for each person, then payslips.',

  '/settings': 'The business\'s own settings: company details, numbering, approval rules, notifications and the Master\'s controls.',
}

/** The words for one address: the exact screen, or the detail page of a list ("/projects/12" -> "/projects/:id"). */
export function infoFor(pathname: string): string {
  const clean = pathname.replace(/\/+$/, '') || '/'
  if (PAGE_INFO[clean]) return PAGE_INFO[clean]!
  // A screen with sub-pages of its own, registered as "/store/hub/inward/*": every address beneath it reads as it does.
  const wide = Object.keys(PAGE_INFO).find((k) => k.endsWith('/*') && (clean + '/').startsWith(k.slice(0, -1)))
  if (wide) return PAGE_INFO[wide]!
  const parts = clean.split('/')
  let best = ''
  let bestLiterals = -1
  for (const pattern of Object.keys(PAGE_INFO)) {
    const p = pattern.split('/')
    if (p.length !== parts.length || !pattern.includes(':')) continue
    if (!p.every((seg, i) => seg.startsWith(':') || seg === parts[i])) continue
    const literals = p.filter((s) => !s.startsWith(':')).length
    if (literals > bestLiterals) { best = pattern; bestLiterals = literals }
  }
  return best ? PAGE_INFO[best]! : ''
}
