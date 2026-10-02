import { api, clickText, fill, launch, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

const { page, check, done } = await launch({ allow: [] })
await signIn(page)

// --- An approved order with one entry, made through the API -------------------------------------
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const job = vocab.jobs[0]
let budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
if (!budgets.length) {
  await api(page, 'POST', `/api/wo/projects/${job.id}/budgets`, { name: 'E2E civil', code: 'E2E', allocated_amount: 90000000 })
  budgets = (await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)).data.budgets
}
const created = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: job.id, department: 'Civil', subject: 'E2E change a measurement', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await api(page, 'PUT', `/api/wo/orders/${created.id}/boq`, {
  lines: [{ activity_no: '1.0', item_description: 'Plastering walls', uom: 'sqm', quantity: 500, unit_rate: 300, budget_id: budgets[0].id }],
})
const ok = await api(page, 'POST', `/api/wo/orders/${created.id}/self-approve`, { comments: 'e2e' })
if (ok.status !== 200) throw new Error('could not approve the test order: ' + JSON.stringify(ok.data))
const book0 = (await api(page, 'GET', `/api/sub-mb/${created.id}`)).data
const itemId = book0.lines[0].item_id
const rec = await api(page, 'POST', `/api/sub-mb/${created.id}/entries`, {
  item_id: itemId, location: 'Block A', measured_on: '2026-11-10', multiplier: 1,
  dimensions: [{ particulars: 'Wall', nos: 2, length: 6, breadth: 5 }, { particulars: 'Door', nos: 1, length: 1, breadth: 2, deduct: true }],
})
if (rec.status !== 200) throw new Error('could not record: ' + JSON.stringify(rec.data))

await open(page, `/subcontractors/measurement-book?order=${created.id}`)
await page.waitForSelector('table[aria-label="Measurement entries"] tbody tr')
const text = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' '))
check('the book opens on the Items and Entries layout, not the Excel one', (await page.$('table[aria-label="Items on the order"]')) !== null && (await page.$('table[aria-label="Measurement entries"]')) !== null)
check('each entry shows its calculation in the list', /2 × 6 × 5/.test(await text()), (await text()).slice(-300))

// --- Open it: the lines, figures and total ---------------------------------------------------------
await page.click('table[aria-label="Measurement entries"] tbody tr')
await page.waitForSelector('[role=dialog] table')
let dlg = await page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('opening an entry shows every line with its figures', dlg.includes('Wall') && dlg.includes('Door') && dlg.includes('deduct'), dlg.slice(0, 200))
check('and what it comes to (60 − 2 = 58)', /Measured.{0,12}58/.test(dlg), dlg.slice(-200))

// --- Change the calculation, with a custom line -----------------------------------------------------------
await clickText(page, '[role=dialog] button', 'Change the calculation')
await page.waitForFunction(() => /This entry/.test(document.querySelector('[role=dialog]')?.textContent ?? ''))
await sleep(300)
dlg = await page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the change window opens with the lines already in it', dlg.includes('Wall') && /This entry\s*58/.test(dlg), dlg.slice(0, 300))
await fill(page, '#m-calc-label', 'Hold 5% for finishes')
await fill(page, '#m-calc', '-total * 5%')
await sleep(200)
dlg = await page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the custom calculation shows what it comes to before it is added (−2.9)', /= -2\.9/.test(dlg), (dlg.match(/= -?[\d.]+/) || [''])[0])
await clickText(page, '[role=dialog] button', 'Add as a line')
await sleep(300)
dlg = await page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('added as a line, and the total follows (58 − 2.9 = 55.1)', dlg.includes('Hold 5% for finishes') && /This entry\s*55\.1/.test(dlg), (dlg.match(/This entry.{0,20}/) || [''])[0])
await toastsGone(page)
await clickText(page, '[role=dialog] button', 'Save the change')
await waitForToast(page, 'updated')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(500)
const after = (await api(page, 'GET', `/api/sub-mb/${created.id}`)).data.entries
check('the entry in the book now holds the new quantity and the extra line', after.length === 1 && Math.abs(after[0].quantity - 55.1) < 0.001 && after[0].dimensions.length === 3, JSON.stringify(after.map((e) => e.quantity)))

// --- Delete it from its own window -----------------------------------------------------------------------------
await toastsGone(page)
await page.click('table[aria-label="Measurement entries"] tbody tr')
await page.waitForSelector('[role=dialog] table')
await clickText(page, '[role=dialog] button', 'Delete')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Remove')
await waitForToast(page, 'removed')
await sleep(500)
check('and it can be deleted from there', (await api(page, 'GET', `/api/sub-mb/${created.id}`)).data.entries.length === 0)

await done()
