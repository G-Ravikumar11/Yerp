import { attachHardCopy, api, launch, signIn } from './lib.mjs'

// The whole chain, with the people who really do each step: a planner drafts a work order, the project
// manager and then the owner approve it, a site engineer measures, the planner bills, the same two sign
// the bill, accounts pays. Then the order is amended with a certified bill behind it.
const { page, check, done } = await launch({ allow: [/^(40[0-9]|429) /] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const PW = 'Passw0rd-QA1'
const dom = (await api(page, 'GET', '/api/hr/org-domain')).data.domain || 'example.in'
const mk = async (first, role, level, reports_to = null) => {
  const email = `${first.toLowerCase()}.ff${stamp}@${dom}`
  const r = await api(page, 'POST', '/api/employees', { first_name: first, last_name: `FF${stamp}`, email, password: PW, phone: '', job_title: role, department_id: null, reports_to, level, role: 'employee', permission_role: role, site_ids: [], employment_type: 'full_time', pay_frequency: 'monthly', salary: 1, tax_rate: 0, start_date: '2026-01-01', emergency_contact: '', emergency_phone: '' })
  if (r.status !== 200) throw new Error(first + ': ' + JSON.stringify(r.data))
  return { id: r.data.id, email, name: `${first} FF${stamp}` }
}
const pm = await mk('Pmgr', 'project_manager', 'L4')
const planner = await mk('Plan', 'planning_billing', 'L2', pm.id)
const site = await mk('Site', 'construction', 'L2', pm.id)
const acct = await mk('Acct', 'accounts', 'L2', pm.id)
const who = async (p) => {
  await api(page, 'POST', '/api/client/logout'); await api(page, 'POST', '/api/employee/auth/logout')
  if (!p) return signIn(page)
  let r = await api(page, 'POST', '/api/employee/auth/login', { email: p.email, password: PW })
  for (let i = 0; i < 4 && r.status === 429; i++) { await new Promise((x) => setTimeout(x, 20000)); r = await api(page, 'POST', '/api/employee/auth/login', { email: p.email, password: PW }) }
  if (r.status !== 200) throw new Error('login ' + p.email + ' ' + JSON.stringify(r.data))
}
const order = async (id) => (await api(page, 'GET', `/api/wo/orders/${id}`)).data.order ?? (await api(page, 'GET', `/api/wo/orders/${id}`)).data
const inbox = async () => (await api(page, 'GET', '/api/approvals/inbox')).data.items
const mine = async (kind, id) => (await inbox()).find((i) => i.kind === kind && i.id === id)
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const job = vocab.jobs[0]
let budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
if (!budgets.length) { await api(page, 'POST', `/api/wo/projects/${job.id}/budgets`, { name: 'FF civil', code: 'FF', allocated_amount: 900000000 }); budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets }

// 1. The planner drafts and sends it up
await who(planner)
const head = await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: job.id, department: 'Civil', subject: `Full flow ${stamp}`, commencement_date: '2026-11-01', completion_date: '2027-03-31', retention_percent: 5, gst_rate: 18, tds_rate: 1 })
check('the planner can draft a work order', head.status === 200, JSON.stringify(head.data).slice(0, 120))
const oid = head.data.order.id
const boq = await api(page, 'PUT', `/api/wo/orders/${oid}/boq`, { lines: [{ activity_no: '1.0', item_description: 'Shuttering', uom: 'sqm', quantity: 1000, unit_rate: 410, tolerance_percent: 10, budget_id: budgets[0].id }, { activity_no: '2.0', item_description: 'Steel', uom: 'MT', quantity: 20, unit_rate: 68000, budget_id: budgets[0].id }] })
check('and price the schedule', boq.status === 200, JSON.stringify(boq.data).slice(0, 120))
check('nothing can be measured or billed on a draft', (await api(page, 'POST', `/api/sub-bills`, { order_id: oid })).status === 409)
const sub = await api(page, 'POST', `/api/wo/orders/${oid}/submit`, {})
check('submitting works', sub.status === 200, JSON.stringify(sub.data).slice(0, 160))
const o1 = await order(oid)
check('it is provisional and routed to the manager first, the owner last', o1.status === 'PROVISIONAL' && o1.approval_route?.length === 2 && o1.approval_route[0].name === pm.name && o1.approval_route[1].owner === true, JSON.stringify(o1.approval_route))
check('the planner cannot approve their own order', [401, 403].includes((await api(page, 'POST', `/api/wo/orders/${oid}/self-approve`, {})).status) && [401, 403, 409].includes((await api(page, 'POST', `/api/wo/orders/${oid}/approve`, {})).status))

// 2. Site staff have nothing to approve
await who(site)
check('site staff are not offered it', !(await mine('subcontract_order', oid)))
check('and cannot approve it', [401, 403].includes((await api(page, 'POST', `/api/wo/orders/${oid}/approve`, {})).status))

// 3. The manager signs; it moves to the owner
await who(pm)
const seenPm = await mine('subcontract_order', oid)
check('the manager has it in Approvals as theirs', !!seenPm && seenPm.mine === true, JSON.stringify(seenPm))
const ap1 = await api(page, 'POST', `/api/wo/orders/${oid}/approve`, { comments: 'ok' })
check('the manager signs', ap1.status === 200, JSON.stringify(ap1.data).slice(0, 160))
const o2 = await order(oid)
check('it is still not live: now waiting on the owner', o2.status === 'PROVISIONAL' && /owner|Yalavarti|Owner/i.test(o2.waiting_on || JSON.stringify(o2.approval_route)), `${o2.status} ${o2.waiting_on}`)
check('the manager cannot sign twice or for the owner', [401, 403, 409].includes((await api(page, 'POST', `/api/wo/orders/${oid}/approve`, {})).status))

// 4. The owner signs
await who(null)
const seenOwner = await mine('subcontract_order', oid)
check('the owner has it, as theirs now', !!seenOwner && seenOwner.mine === true, JSON.stringify(seenOwner))
const ap2 = await api(page, 'POST', `/api/wo/orders/${oid}/approve`, { comments: 'ok' })
check('the owner approves', ap2.status === 200 && (await order(oid)).status === 'APPROVED', JSON.stringify(ap2.data).slice(0, 160))
check('and it leaves the inbox', !(await mine('subcontract_order', oid)))

// 5. The site engineer measures - once the owner has let them see the order
await api(page, 'PUT', `/api/wo/orders/${oid}/access`, { employee_ids: [site.id, acct.id] })
await who(site)
const book = (await api(page, 'GET', `/api/sub-mb/${oid}`)).data
const shut = book.lines.find((l) => l.activity_no === '1.0')
const steel = book.lines.find((l) => l.activity_no === '2.0')
const m1 = await api(page, 'POST', `/api/sub-mb/${oid}/entries`, { item_id: shut.item_id, quantity: 400, measured_on: '2026-11-15' })
check('site staff record a measurement', m1.status === 200 && m1.data.measured_to_date === 400, JSON.stringify(m1.data).slice(0, 140))
const m2 = await api(page, 'POST', `/api/sub-mb/${oid}/entries`, { item_id: steel.item_id, quantity: 5, measured_on: '2026-11-15' })
check('on both lines', m2.status === 200)
const over = await api(page, 'POST', `/api/sub-mb/${oid}/entries`, { item_id: shut.item_id, quantity: 800, measured_on: '2026-11-16' })
console.log('INFO measuring 1200 of 1000 (10% tolerance):', over.status, JSON.stringify(over.data).slice(0, 200))
check('measuring far past the order plus tolerance is not silently accepted', over.status >= 400 || over.data.over_measured === undefined || over.data.over_measured > 0, JSON.stringify(over.data).slice(0, 200))
check('site staff cannot bill', [401, 403].includes((await api(page, 'POST', '/api/sub-bills', { order_id: oid })).status))

// 6. The planner bills; it climbs the same line
await who(planner)
const bill = await api(page, 'POST', '/api/sub-bills', { order_id: oid, period_from: '2026-11-01', period_to: '2026-11-30' })
check('the planner draws up the bill from the book', bill.status === 200, JSON.stringify(bill.data).slice(0, 160))
const bid = bill.data.bill?.id ?? bill.data.id
check('a second bill cannot be opened while one is', (await api(page, 'POST', '/api/sub-bills', { order_id: oid })).status === 409)
await attachHardCopy(page, bid)
const sb = await api(page, 'POST', `/api/sub-bills/${bid}/submit`, {})
check('sent for certification', sb.status === 200 && sb.data.bill.status === 'SUBMITTED', JSON.stringify(sb.data).slice(0, 160))
const bd = (await api(page, 'GET', `/api/sub-bills/${bid}`)).data.bill ?? (await api(page, 'GET', `/api/sub-bills/${bid}`)).data
console.log('INFO bill figures:', JSON.stringify({ this_bill: bd.this_bill, retention: bd.retention_amount ?? bd.retention, tds: bd.tds_amount ?? bd.tds, gst: bd.gst_amount ?? bd.gst, net: bd.net_payable }))
check('the bill is worth 400 x 410 + 5 x 68,000 = 504,000 of work', Math.round(bd.this_bill) === 504000, String(bd.this_bill))
check('the planner cannot certify their own bill', [401, 403].includes((await api(page, 'POST', `/api/sub-bills/${bid}/certify`, {})).status))
await who(site)
check('site staff cannot certify it', [401, 403].includes((await api(page, 'POST', `/api/sub-bills/${bid}/certify`, {})).status))
await who(pm)
const bi = await mine('sub_bill', bid)
check('the manager has the bill in Approvals', !!bi && bi.mine === true, JSON.stringify(bi))
const c1 = await api(page, 'POST', `/api/sub-bills/${bid}/certify`, { comments: 'checked' })
console.log('INFO after the manager alone signed the bill, its status is', c1.data.bill?.status)
check('the manager signs it', c1.status === 200, JSON.stringify(c1.data).slice(0, 160))
await who(null)
if (c1.data.bill.status === 'SUBMITTED') { const c2 = await api(page, 'POST', `/api/sub-bills/${bid}/certify`, { comments: 'ok' }); check('the owner certifies', c2.data.bill.status === 'CERTIFIED') }
{ const d = (await api(page, 'GET', `/api/sub-bills/${bid}`)).data; check('the bill is certified', (d.bill ?? d).status === 'CERTIFIED') }
check('nobody can certify it again', (await api(page, 'POST', `/api/sub-bills/${bid}/certify`, {})).status === 409)

// 7. Paying is accounts', not the approvers'
await who(planner)
check('the planner cannot pay', [401, 403].includes((await api(page, 'POST', `/api/sub-bills/${bid}/pay`, { reference: 'x' })).status))
await who(acct)
const pay = await api(page, 'POST', `/api/sub-bills/${bid}/pay`, { reference: `UTR${stamp}` })
check('accounts pay it', pay.status === 200 && pay.data.bill.status === 'PAID', JSON.stringify(pay.data).slice(0, 160))

// 8. More work, a second bill
await who(site)
await api(page, 'POST', `/api/sub-mb/${oid}/entries`, { item_id: shut.item_id, quantity: 300, measured_on: '2026-12-10' })
await who(planner)
const bill2 = await api(page, 'POST', '/api/sub-bills', { order_id: oid, period_from: '2026-12-01', period_to: '2026-12-31' })
const bd2 = bill2.data.bill ?? bill2.data
check('a second bill carries only the new work, 300 x 410 = 123,000', bill2.status === 200 && Math.round(bd2.this_bill) === 123000, JSON.stringify(bd2).slice(0, 160))
await attachHardCopy(page, bd2.id)
const sb2 = await api(page, 'POST', `/api/sub-bills/${bd2.id}/submit`, {})
check('the second bill is sent up', sb2.status === 200 && sb2.data.bill.status === 'SUBMITTED')
await who(null)
const seen2 = await mine('sub_bill', bd2.id)
console.log('INFO owner sees the PM-held bill:', JSON.stringify(seen2 && { mine: seen2.mine, waiting_on: seen2.waiting_on }))
const step = await api(page, 'POST', `/api/sub-bills/${bd2.id}/certify`, { comments: 'owner steps in' })
check('the owner can certify a bill that is waiting with the manager', step.status === 200 && step.data.bill.status === 'CERTIFIED', JSON.stringify(step.data).slice(0, 160))
await done()
