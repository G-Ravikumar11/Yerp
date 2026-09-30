import { api, approvedOrder, clickText, launch, measure, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/400 POST \/api\/approvals\/decide/] })
await signIn(page)

// --- Two things waiting on the owner: an order sent for approval and a bill -----------------
const tag = 'E2E approve ' + Date.now().toString(36)
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const job = vocab.jobs[0]
let budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
if (!budgets.length) {
  await api(page, 'POST', `/api/wo/projects/${job.id}/budgets`, { name: 'E2E civil', code: 'E2E', allocated_amount: 900000000 })
  budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
}
const draft = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: job.id, department: 'Civil', subject: tag, commencement_date: '2026-11-01', completion_date: '2027-02-28' })).data.order
await api(page, 'PUT', `/api/wo/orders/${draft.id}/boq`, { lines: [{ activity_no: '1.0', item_description: 'Approvals test line', uom: 'cum', quantity: 10, unit_rate: 5000, budget_id: budgets[0].id }] })
const sent = await api(page, 'POST', `/api/wo/orders/${draft.id}/submit`, {})
if (sent.status !== 200) throw new Error('could not submit: ' + JSON.stringify(sent.data))

const order = await approvedOrder(page, { subject: 'E2E approvals bill' })
await measure(page, order.id, order.items[0].item_id, 40)
const bill = (await api(page, 'POST', '/api/sub-bills', { order_id: order.id })).data.bill
await api(page, 'POST', `/api/sub-bills/${bill.id}/submit`, {})

await open(page, '/approvals')
await page.waitForFunction(() => document.querySelectorAll('main ul li').length > 0, { timeout: 10000 })
const list = () => page.$$eval('main ul li', (li) => li.map((x) => x.textContent.replace(/\s+/g, ' ')))
const all = await list()
check('both appear in the inbox, with their kind, number and amount', all.some((t) => t.includes('Subcontract work order') && t.includes(tag)) && all.some((t) => t.includes('Subcontractor bill') && t.includes(bill.number)), `${all.length} waiting`)
check('the menu shows how many are waiting on the owner', /\d/.test(await page.$eval('a[href$="/approvals"] [aria-label$="waiting"]', (e) => e.textContent)))

// --- Filter by kind ------------------------------------------------------------------------------
await clickText(page, 'button[role=tab]', 'Subcontractor bill')
await sleep(300)
check('the kind tabs narrow the list', (await list()).every((t) => t.includes('Subcontractor bill')))
await clickText(page, 'button[role=tab]', 'All')

// --- Send the bill back, which needs a reason ---------------------------------------------------------
const billCard = (await page.$$('main ul li'))[(await list()).findIndex((t) => t.includes(bill.number))]
await (await billCard.$$('button')).at(-2).click() // "Send back"
await page.waitForSelector('[role=dialog] textarea')
await clickText(page, '[role=dialog] button', 'Send back')
await sleep(300)
check('sending back asks why', (await page.$eval('[role=dialog]', (e) => e.textContent)).includes('Say why'))
await page.type('[role=dialog] textarea', 'E2E: measurements need checking')
await clickText(page, '[role=dialog] button', 'Send back')
await waitForToast(page, 'draft')
await sleep(600)
check('the bill went back to a draft with the reason', (await api(page, 'GET', `/api/sub-bills/${bill.id}`)).data.status === 'DRAFT' && (await api(page, 'GET', `/api/sub-bills/${bill.id}`)).data.remarks.includes('E2E'))
await toastsGone(page)

// --- Approve the order --------------------------------------------------------------------------------
const orderIdx = (await list()).findIndex((t) => t.includes('Subcontract work order') && t.includes(tag))
const orderCard = (await page.$$('main ul li'))[orderIdx]
await (await orderCard.$$('button')).at(-1).click() // "Approve"
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Approve')
await waitForToast(page, 'approved')
await sleep(600)
check('approving from the inbox approves the order, by the same rules', (await api(page, 'GET', `/api/wo/orders/${draft.id}`)).data.order.status === 'APPROVED')
check('what was decided leaves the inbox', !(await list()).some((t) => t.includes(bill.number)))

await done()
