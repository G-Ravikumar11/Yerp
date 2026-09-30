import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { api, clickCell, clickText, fill, launch, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Refusals below are provoked on purpose: past the ceiling, and offline.
const { page, check, done } = await launch({ allow: [/409 POST \/api\/sub-mb/, /net::ERR/] })
await signIn(page)

// --- An approved order to measure, made through the API ----------------------------------
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const job = vocab.jobs[0]
let budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
if (!budgets.length) {
  await api(page, 'POST', `/api/wo/projects/${job.id}/budgets`, { name: 'E2E civil', code: 'E2E', allocated_amount: 90000000 })
  budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
}
const created = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: job.id, department: 'Civil', subject: 'E2E measurement book', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await api(page, 'PUT', `/api/wo/orders/${created.id}/boq`, {
  lines: [
    { activity_no: '1.0', item_description: 'Shuttering for slabs and beams', uom: 'sqm', quantity: 200, unit_rate: 410, tolerance_percent: 10, budget_id: budgets[0].id },
    { activity_no: '2.0', item_description: 'Reinforcement steel', uom: 'MT', quantity: 18, unit_rate: 68000, budget_id: budgets[0].id },
  ],
})
const ok = await api(page, 'POST', `/api/wo/orders/${created.id}/self-approve`, { comments: 'e2e' })
if (ok.status !== 200) throw new Error('could not approve the test order: ' + JSON.stringify(ok.data))

await open(page, `/subcontractors/measurement-book?order=${created.id}`)
await page.waitForSelector('table[aria-label="Items on the order"] tbody tr')
const text = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' '))
check('the book opens on the chosen order with its items', (await page.$$eval('table[aria-label="Items on the order"] tbody tr', (r) => r.length)) === 2)

// --- Find any work order; keep it in sight; type a code and the rest fills in ---------------------
const wo = (await api(page, 'GET', `/api/wo/orders/${created.id}`)).data.order
const jobNo = vocab.jobs[0].number
const picker = 'button[aria-label="Work order"]'
const pickerText = () => page.$eval(picker, (e) => e.textContent)
check('the picker names the work order, its job code and the gang', (await pickerText()).includes(wo.wo_number) && (await pickerText()).includes(jobNo) && (await pickerText()).includes(gang.company_name || gang.name || ''), await pickerText())
await page.click(picker)
await page.waitForSelector('[role=listbox] [role=option]')
const allOrders = await page.$$eval('[role=listbox] [role=option]', (o) => o.length)
check('it lists every approved work order', allOrders >= 1, String(allOrders))
await page.keyboard.type(jobNo)
await sleep(200)
const byJob = await page.$$eval('[role=listbox] [role=option]', (o) => o.map((e) => e.textContent))
check('typing a job code narrows the list to that job', byJob.length >= 1 && byJob.every((t) => t.includes(jobNo)), `${byJob.length}`)
await fill(page, '[role=combobox]', 'zzz-nothing')
await sleep(150)
check('a search that matches nothing says so', (await page.$eval('[role=listbox]', (e) => e.textContent)).includes('No work order matches'))
await fill(page, '[role=combobox]', wo.wo_number)
await sleep(150)
await page.keyboard.press('Enter')
await page.waitForSelector('table[aria-label="Items on the order"] tbody tr')
check('choosing by number opens that book', page.url().includes(`order=${created.id}`))

await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
await page.evaluate(() => document.querySelector('main').scrollIntoView(false))
const inView = await page.$eval(picker, (e) => {
  const r = e.getBoundingClientRect()
  return r.top >= 0 && r.bottom <= window.innerHeight
})
check('the work order stays in view while the page is scrolled', inView)

await page.click('input[aria-label="Item code"]')
await page.keyboard.type('2.0')
await sleep(200)
const facts = await page.$eval('[aria-live=polite]', (e) => e.textContent.replace(/\s+/g, ' '))
check('typing an item code fills in its description from the order', facts.includes('Reinforcement steel'), facts)
check('and its unit, quantity and rate', facts.includes('MT') && facts.includes('18') && /68,000/.test(facts), facts)
await page.keyboard.press('Enter')
await page.waitForSelector('[role=dialog]')
const dialog = await page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('Enter opens the measurement with the work order and the item shown', dialog.includes(wo.wo_number) && dialog.includes('Reinforcement steel') && dialog.includes('68,000'), dialog.slice(0, 200))
await page.waitForSelector('[role=dialog] [role=grid]')
await clickCell(page, 0, 0, 0, '[role=dialog]')
await page.keyboard.type('xyz')
await page.keyboard.press('Escape')
await sleep(250)
check('Escape in a cell cancels that edit without closing the measurement', (await page.$('[role=dialog]')) !== null && (await page.$('[role=dialog] [role=grid] input:not([type=checkbox])')) === null)
await page.keyboard.press('Escape')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(200)
check('closing it puts the cursor back in the code box', await page.evaluate(() => document.activeElement?.getAttribute('aria-label') === 'Item code'))
await page.keyboard.type('nope-9')
await sleep(150)
check('a code that is not on the order is said plainly', (await text()).includes('No item with that code'))
await page.keyboard.press('Escape')

// --- Measure with dimensions --------------------------------------------------------------
await page.click('table[aria-label="Items on the order"] tbody tr:first-child button')
await page.waitForSelector('[role=dialog] [role=grid]')
await clickCell(page, 0, 0, 0, '[role=dialog]')
await page.keyboard.type('Slab')
await page.keyboard.press('Tab')
await page.keyboard.type('2')
await page.keyboard.press('Tab')
await page.keyboard.press('Tab') // no NoM
await page.keyboard.type('6')
await page.keyboard.press('Tab')
await page.keyboard.type('5')
await page.keyboard.press('Enter')
await sleep(200)
const live = await page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the total is worked out live as the dimensions are typed (2 × 6 × 5 = 60)', /This entry\s*60\s*sqm/.test(live), (live.match(/This entry.{0,20}/) || [''])[0])
await fill(page, '#m-where', 'Block C-3, first floor')
await clickText(page, '[role=dialog] button', 'Record it in the book')
await waitForToast(page, 'Recorded')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(400)
check('the entry appears in the book, and the item shows it measured', (await text()).includes('Block C-3, first floor') && /60(?!\d)/.test(await text()))

// --- A plain total ----------------------------------------------------------------------------
await page.click('table[aria-label="Items on the order"] tbody tr:first-child button')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button[role=tab]', 'Just a total')
await fill(page, '#m-total', '45')
await clickText(page, '[role=dialog] button', 'Record it in the book')
await waitForToast(page, 'Recorded')
await sleep(500)

// --- Past the ceiling --------------------------------------------------------------------------
await page.click('table[aria-label="Items on the order"] tbody tr:first-child button')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button[role=tab]', 'Just a total')
await fill(page, '#m-total', '130')
await sleep(150)
const warn = await page.$eval('[role=dialog]', (e) => e.textContent)
check('the dialog warns before saving that it goes past the allowance', /past the 220/.test(warn), (warn.match(/That takes.{0,70}/) || [''])[0])
await clickText(page, '[role=dialog] button', 'Record it in the book')
await page.waitForSelector('[role=dialog] [role=alert]')
const refusal = await page.$eval('[role=dialog] [role=alert]', (e) => e.textContent)
check('the server\'s refusal is shown in the dialog, in its own words', /already measured/.test(refusal), refusal.slice(0, 90))
await clickText(page, '[role=dialog] button', 'Cancel')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(400)
check('closing a dialog leaves the page clickable (no stuck overlay)', (await page.evaluate(() => document.body.style.pointerEvents)) !== 'none' && !(await page.$('[data-state=open][class*="bg-black"]')))

// --- Remove an entry ------------------------------------------------------------------------------
await toastsGone(page)
const entriesBefore = await page.$$eval('table[aria-label="Measurement entries"] tbody tr', (r) => r.length)
await page.click('table[aria-label="Measurement entries"] tbody tr button[aria-label="Remove this entry"]')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Remove')
await waitForToast(page, 'removed')
await sleep(500)
check('an unbilled entry can be removed', (await page.$$eval('table[aria-label="Measurement entries"] tbody tr', (r) => r.length)) === entriesBefore - 1)

// --- Import the MB from Excel ------------------------------------------------------------------------
const b64 = await page.evaluate(async () => {
  const buf = new Uint8Array(await (await fetch('/api/sub-mb/template.xlsx', { credentials: 'include' })).arrayBuffer())
  let s = ''
  buf.forEach((b) => (s += String.fromCharCode(b)))
  return btoa(s)
})
const xlsx = join(tmpdir(), 'e2e-mb.xlsx')
writeFileSync(xlsx, Buffer.from(b64, 'base64'))
await clickText(page, 'main button', 'Import MB from Excel')
await page.waitForSelector('#ib-file')
await (await page.$('#ib-file')).uploadFile(xlsx)
await page.waitForSelector('[role=dialog] table select', { timeout: 10000 })
const matched = await page.$eval('[role=dialog]', (e) => e.textContent)
check('the worked example is read and its section matched to an item', /1 of 1 sections matched/.test(matched), (matched.match(/\d of \d sections matched/) || [''])[0])
await clickText(page, '[role=dialog] button', 'Record it in the book')
await waitForToast(page, 'recorded from')
await sleep(600)
check('the imported entry (114.4) is in the book', /114\.4/.test(await text()))

// --- Offline: keep the measurement on the device, send it when the signal returns ----------------------------
await page.setOfflineMode(true)
await page.evaluate(() => window.dispatchEvent(new Event('offline')))
await sleep(300)
check('going offline is shown in the top bar', (await page.$eval('header', (e) => e.textContent)).includes('Offline'))
await page.click('table[aria-label="Items on the order"] tbody tr:nth-child(2) button')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button[role=tab]', 'Just a total')
await fill(page, '#m-total', '3')
await clickText(page, '[role=dialog] button', 'Record it in the book')
await waitForToast(page, 'kept on this device')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
check('with no signal the measurement is kept, and the bar counts it', /Offline - 1 kept/.test(await page.$eval('header', (e) => e.textContent)))
const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('yerp-offline') || '{}').state?.queue?.length)
check('it survives in local storage (a reload would not lose it)', stored === 1, String(stored))
await page.setOfflineMode(false)
await page.evaluate(() => window.dispatchEvent(new Event('online')))
await waitForToast(page, '1 change sent')
await sleep(800)
const after = (await api(page, 'GET', `/api/sub-mb/${created.id}`)).data
const steel = after.lines.find((l) => l.activity_no === '2.0')
check('on reconnecting it is sent, in order, and the server has it', steel.measured_to_date === 3, `${steel.measured_to_date} MT`)
check('the top bar goes quiet again', !(await page.$eval('header', (e) => e.textContent)).match(/Offline|sending|kept/))


// --- An amended order is still in the book, read-only, and points to its revision ----------------------
const old = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: job.id, department: 'Civil', subject: 'E2E to be amended', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await api(page, 'PUT', `/api/wo/orders/${old.id}/boq`, { lines: [{ activity_no: '1.0', item_description: 'Brickwork', uom: 'cum', quantity: 50, unit_rate: 5200, budget_id: budgets[0].id }] })
await api(page, 'POST', `/api/wo/orders/${old.id}/self-approve`, { comments: 'e2e' })
const rev = (await api(page, 'POST', `/api/wo/orders/${old.id}/amend`, {})).data.order
await api(page, 'POST', `/api/wo/orders/${rev.id}/submit`, {})
const approved = await api(page, 'POST', `/api/wo/orders/${rev.id}/approve`, {})
if (approved.status !== 200) throw new Error('could not approve the revision: ' + JSON.stringify(approved.data))
await open(page, `/subcontractors/measurement-book?order=${old.id}`)
await page.waitForSelector('[role=status]')
const banner = await page.$eval('[role=status]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the amended order opens, and says it was replaced by its revision', banner.includes('was amended') && banner.includes(rev.wo_number), banner)
check('it cannot take new measurements', (await page.$('table[aria-label="Items on the order"] tbody button')) === null && (await page.$('input[aria-label="Item code"]')) === null)
await page.click('button[aria-label="Work order"]')
await page.waitForSelector('[role=listbox] [role=option]')
check('the picker lists it, marked amended', (await page.$$eval('[role=listbox] [role=option]', (o, no) => o.some((e) => e.textContent.includes(no) && e.textContent.includes('amended')), old.wo_number)))
await page.keyboard.press('Escape')
await clickText(page, 'button', `Open ${rev.wo_number}`)
await page.waitForFunction((id) => location.search.includes('order=' + id), {}, rev.id)
await page.waitForSelector('table[aria-label="Items on the order"] tbody tr')
check('one click opens the revision, which can be measured', (await page.$('table[aria-label="Items on the order"] tbody button')) !== null)


// --- A draft is listed too, and says why it cannot be measured yet -----------------------------------------
const draft = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: job.id, department: 'Civil', subject: 'E2E still a draft', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await open(page, `/subcontractors/measurement-book?order=${draft.id}`)
await page.waitForSelector('[role=status]')
check('a draft is in the list too, and says it is still a draft', (await page.$eval('[role=status]', (e) => e.textContent)).includes('still a draft'))
check('and it takes no measurements', (await page.$('input[aria-label="Item code"]')) === null)

await done()
