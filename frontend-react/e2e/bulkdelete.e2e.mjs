import { api, approvedOrder, clickText, fill, launch, measure, open, signIn, sleep, waitForToast } from './lib.mjs'

// Clearing a lot at once: tick rows (or all of them), delete them together; filters narrow what "all" means.
const { page, check, done } = await launch({ allow: [/^(403|404|409) /] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const made = []
for (let i = 0; i < 6; i++) made.push(await approvedOrder(page, { subject: `Bulk ${stamp} ${i}` }))
// a second project, so the project filter has something to choose between
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const other = vocab.jobs[1] ?? vocab.jobs[0]
await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: other.id, department: 'Civil', subject: `Other project ${stamp}`, commencement_date: '2026-11-01', completion_date: '2027-03-31' })
const dlg = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))

// --- Work orders: filter, select all, delete -----------------------------------------------------------------------------
await open(page, '/subcontractors/work-orders')
await page.waitForSelector('table[aria-label="Work orders"] tbody tr')
await fill(page, 'input[aria-label="Search"]', `Bulk ${stamp}`)
await sleep(400)
const rows = await page.$$eval('table[aria-label="Work orders"] tbody tr', (r) => r.length)
check('the search narrows the list to the six made for this test', rows === 6, String(rows))
check('the list offers a project filter when there is more than one project', vocab.jobs.length < 2 || (await page.$('[aria-label="Projects"]')) !== null)
await page.click('table[aria-label="Work orders"] thead input[aria-label="Select every row"]')
await sleep(200)
const bar = await page.$eval('[aria-label="Selected rows"]', (e) => e.textContent.replace(/\s+/g, ' '))
check('ticking the heading box selects every row shown, and says how many', /6 work orders selected/.test(bar), bar)
// untick one: five go
await page.click('table[aria-label="Work orders"] tbody tr:first-child input[aria-label="Select this row"]')
await sleep(200)
check('one can be left out', /5 work orders selected/.test(await page.$eval('[aria-label="Selected rows"]', (e) => e.textContent)))
await clickText(page, '[aria-label="Selected rows"] button', 'Delete 5')
await page.waitForSelector('[role=dialog]')
check('five or more asks to type DELETE', /Type DELETE/i.test(await dlg()), (await dlg()).slice(0, 200))
check('and Delete is off until it is typed', await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => /^Delete 5/.test(b.textContent))?.disabled))
await fill(page, '#bulk-confirm', 'DELETE')
await clickText(page, '[role=dialog] button', 'Delete 5')
await page.waitForFunction(() => /deleted/.test(document.querySelector('[role=dialog]')?.textContent ?? '') && /Done/.test(document.querySelector('[role=dialog]')?.textContent ?? ''), { timeout: 60000 })
check('it reports five deleted', /5 deleted/.test(await dlg()), await dlg())
await clickText(page, '[role=dialog] button', 'Close')
await sleep(800)
let left = 0
for (const o of made) if ((await api(page, 'GET', `/api/wo/orders/${o.id}`)).status === 200) left++
check('exactly the one that was left out remains', left === 1, String(left))

// --- Measurement book entries ----------------------------------------------------------------------------------------------
const live = await approvedOrder(page, { subject: `Entries ${stamp}` })
for (const q of [3, 4, 5, 6]) await measure(page, live.id, live.items[0].item_id, q)
await api(page, 'POST', `/api/sub-mb/${live.id}/holds`, { item_id: live.items[0].item_id, quantity: 1, reason: 'test' })
await open(page, `/subcontractors/measurement-book?order=${live.id}`)
await page.waitForSelector('table[aria-label="Measurement entries"] tbody tr')
check('the entries have a kind filter once there is a hold among them', (await page.$('[aria-label="Kinds"]')) !== null)
await page.click('table[aria-label="Measurement entries"] thead input[aria-label="Select every row"]')
await sleep(200)
await clickText(page, '[aria-label="Selected rows"] button', 'Delete 5')
await page.waitForSelector('[role=dialog]')
await fill(page, '#bulk-confirm', 'DELETE')
await clickText(page, '[role=dialog] button', 'Delete 5')
await page.waitForFunction(() => /Done/.test(document.querySelector('[role=dialog]')?.textContent ?? ''), { timeout: 30000 })
check('all five were cleared', /5 deleted/.test(await dlg()), await dlg())
await clickText(page, '[role=dialog] button', 'Close')
await sleep(600)
check('five entries cleared in one go', (await api(page, 'GET', `/api/sub-mb/${live.id}`)).data.entries.length === 0)
await done()
