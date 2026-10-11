import { api, cellText, clickCell, clickText, fill, launch, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// A picker cell lists its choices the moment it is clicked; and an owner can approve and issue an order straight
// from what is on screen, without saving the schedule first.
const { page, check, done } = await launch()
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const job = vocab.jobs[0]
let budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
if (!budgets.length) { await api(page, 'POST', `/api/wo/projects/${job.id}/budgets`, { name: 'PK civil', code: 'PK', allocated_amount: 900000000 }); budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets }
const head = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: job.id, department: 'Civil', subject: `Pickers ${stamp}`, commencement_date: '2026-11-01', completion_date: '2027-03-31', retention_percent: 5, gst_rate: 18, tds_rate: 1 })).data.order
const options = () => page.$$eval('[role=listbox] [role=option]', (o) => o.map((x) => x.textContent.trim()))

await open(page, `/subcontractors/work-orders/${head.id}`)
await clickText(page, 'button[role=tab]', 'Schedule')
await page.waitForSelector('[role=grid]')
await clickCell(page, 0, 0, 2)
await page.keyboard.type(`Wiring ${stamp}`)
await page.keyboard.press('Tab')
// Unit: just click it, nothing typed
await clickCell(page, 0, 0, 3)
await page.waitForSelector('[role=listbox] [role=option]', { timeout: 5000 })
const units = await options()
check('clicking the Unit cell lists every unit at once', units.length >= 5 && units.includes('Meters'), units.slice(0, 8).join(', '))
await page.evaluate(() => [...document.querySelectorAll('[role=listbox] [role=option]')].find((o) => o.textContent.trim() === 'Meters').click())
await sleep(200)
check('choosing one fills the cell', (await cellText(page, 0, 0, 3)) === 'Meters', await cellText(page, 0, 0, 3))
// Leaving a picker without choosing keeps what it had
await clickCell(page, 0, 0, 3)
await page.waitForSelector('[role=listbox]')
await clickCell(page, 0, 0, 4)
await sleep(200)
check('looking at the list and clicking away leaves the unit as it was', (await cellText(page, 0, 0, 3)) === 'Meters', await cellText(page, 0, 0, 3))
check('and the list is closed', (await page.$$('[role=listbox]')).length === 0)
await page.keyboard.type('1000')
await page.keyboard.press('Tab')
await page.keyboard.type('12')
await page.keyboard.press('Enter')
// Cost centre: click it
const cc = 8
{
  await clickCell(page, 0, 0, cc)
  await page.waitForSelector('[role=listbox]', { timeout: 5000 })
  const centres = await options()
  check('clicking Cost centre lists the project\'s centres at once', centres.length >= 1, centres.join(', '))
  await page.evaluate(() => document.querySelector('[role=listbox] [role=option]').click())
  await sleep(200)
}
check('Unsaved changes shows on the schedule', (await page.$eval('main', (e) => e.textContent)).includes('Unsaved changes'))

// Approve and issue straight from the screen: the schedule on screen is saved first
await clickText(page, 'main button', 'Approve and issue')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Approve')
await sleep(1500)
const o = (await api(page, 'GET', `/api/wo/orders/${head.id}`)).data
const order = o.order ?? o
check('the order was saved and approved in one go', order.status === 'APPROVED' && (order.lines?.length ?? order.items?.length ?? 1) >= 1, `${order.status}`)
await done()
