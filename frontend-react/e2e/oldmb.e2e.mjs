import { BASE, api, approvedOrder, fill, launch, signIn, sleep } from './lib.mjs'

// The current app's Measurement Book (/app.html), which the team still works in.
const { page, check, done } = await launch({ width: 1440, height: 900 })
await signIn(page)
const made = await approvedOrder(page, { subject: 'E2E old book' })

await page.goto(BASE + '/app.html?old=1', { waitUntil: 'networkidle0' })
await page.waitForFunction(() => typeof openSubTab === 'function')
await page.evaluate(() => openSubTab('mb'))
await page.waitForSelector('#sub-mb-body tr')
await sleep(800)
const find = '#sub-wo-find'
const value = (sel) => page.$eval(sel, (e) => e.value)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' '))

// --- Find any work order -----------------------------------------------------------------
await page.click(find)
await page.waitForSelector('#sub-wo-list .wo-opt')
const count = await page.$$eval('#sub-wo-list .wo-opt', (o) => o.length)
check('clicking the box lists every work order', count >= 2, String(count))
await fill(page, find, made.job.number)
await sleep(150)
const byJob = await page.$$eval('#sub-wo-list .wo-opt', (o) => o.map((e) => e.textContent))
check('typing a job code narrows the list to that job', byJob.length >= 1 && byJob.every((t) => t.includes(made.job.number)), String(byJob.length))
await fill(page, find, 'zzz-nothing')
await sleep(150)
check('a search that matches nothing says so', (await text('#sub-wo-list')).includes('No work order matches'))
await fill(page, find, made.number)
await sleep(150)
await page.keyboard.press('Enter')
await page.waitForFunction((n) => document.getElementById('sub-mb-body').textContent.includes('Reinforcement steel'), {}, made.number)
check('Enter opens that work order', (await value('#sub-order')) === String(made.id))
check('the box then shows its number, job code and gang', (await value(find)).includes(made.number) && (await value(find)).includes(made.job.number))

// --- It stays in view ---------------------------------------------------------------------
await page.evaluate(() => { const m = document.querySelector('.main-content'); m.scrollTop = m.scrollHeight })
await sleep(200)
const inView = await page.$eval('#sub-wo-strip', (e) => { const r = e.getBoundingClientRect(); return r.top >= -2 && r.bottom <= window.innerHeight })
check('the work order stays in view while the page scrolls', inView)
await page.evaluate(() => { document.querySelector('.main-content').scrollTop = 0 })

// --- Type a code, the rest comes from the order -----------------------------------------------
await page.click('#sub-code')
await page.keyboard.type('2.0')
await sleep(200)
const card = await text('#sub-code-card')
check('an item code fills in its description, unit, rate and quantities', card.includes('Reinforcement steel') && card.includes('MT') && /68,000/.test(card) && card.includes('20'), card)
await page.keyboard.press('Enter')
await page.waitForFunction(() => getComputedStyle(document.getElementById('sub-measure-modal')).display !== 'none')
const ctx = await text('#sub-measure-context')
check('Enter opens the measurement with the work order and the item shown', ctx.includes(made.number) && ctx.includes(made.job.number) && /68,000/.test(ctx), ctx)
await page.evaluate(() => closeSubMeasure())
await sleep(300)
check('closing it returns to the code box', await page.evaluate(() => document.activeElement && document.activeElement.id === 'sub-code'))
await page.keyboard.type('nope-9')
await sleep(150)
check('a code that is not on the order is said plainly', (await text('#sub-code-card')).includes('No item with that code'))

// --- An amended order stays in the list ------------------------------------------------------------
const rev = (await api(page, 'POST', `/api/wo/orders/${made.id}/amend`, {})).data.order
await api(page, 'POST', `/api/wo/orders/${rev.id}/submit`, {})
const ok = await api(page, 'POST', `/api/wo/orders/${rev.id}/approve`, {})
if (ok.status !== 200) throw new Error('could not approve the revision: ' + JSON.stringify(ok.data))
await page.evaluate(() => loadSubBills())
await sleep(1200)
await page.evaluate((id) => subWoChoose(id), made.id)
await page.waitForSelector('#sub-amend-note .sub-amend-note')
const note = await text('#sub-amend-note')
check('an amended order opens and says it was replaced by its revision', note.includes('was amended') && note.includes(rev.wo_number), note)
check('it cannot take new measurements', (await page.$('#sub-mb-body button')) === null && (await page.$eval('#sub-code', (e) => e.disabled)))
await page.click(find)
await page.waitForSelector('#sub-wo-list .wo-opt')
check('the picker lists it, marked amended', (await text('#sub-wo-list')).includes('amended'))
await page.keyboard.press('Escape')
await page.evaluate(() => document.querySelector('#sub-amend-note button').click())
await page.waitForFunction((id) => document.getElementById('sub-order').value === String(id), {}, rev.id)
await page.waitForSelector('#sub-mb-body button')
check('one click opens the revision, which can be measured', true)


// --- Narrow the work orders to one site ----------------------------------------------------------------------------------
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const other = (await api(page, 'GET', '/api/wo/vocabulary')).data.jobs[1]
let otherBudgets = (await api(page, 'GET', `/api/wo/projects/${other.id}/budgets`)).data.budgets
if (!otherBudgets.length) {
  await api(page, 'POST', `/api/wo/projects/${other.id}/budgets`, { name: 'E2E other', code: 'E2E-2', allocated_amount: 90000000 })
  otherBudgets = (await api(page, 'GET', `/api/wo/projects/${other.id}/budgets`)).data.budgets
}
const elsewhere = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: made.gang.id, job_id: other.id, department: 'Civil', subject: 'E2E other site', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await api(page, 'PUT', `/api/wo/orders/${elsewhere.id}/boq`, { lines: [{ activity_no: '1.0', item_description: 'Plastering', uom: 'sqm', quantity: 100, unit_rate: 200, budget_id: otherBudgets[0].id }] })
await api(page, 'POST', `/api/wo/orders/${elsewhere.id}/self-approve`, { comments: 'e2e' })
await page.evaluate(() => loadSubBills())
await sleep(1500)
const siteOpts = await page.$$eval('#sub-site option', (o) => o.map((e) => e.textContent))
check('the sites of the work orders can be chosen from', siteOpts.length >= 3 && siteOpts[0].startsWith('All sites'), siteOpts.join(' | '))
await page.select('#sub-site', String(other.id))
await page.waitForFunction((id) => document.getElementById('sub-order').value === String(id), {}, elsewhere.id)
await page.click(find)
await page.waitForSelector('#sub-wo-list .wo-opt')
const inSite = await page.$$eval('#sub-wo-list .wo-opt', (o) => o.map((e) => e.textContent))
check('choosing a site lists only its work orders, and opens the first', inSite.length >= 1 && inSite.every((t) => t.includes(other.number)), `${inSite.length} listed`)
await page.keyboard.press('Escape')
await page.select('#sub-site', '')
await page.click(find)
await page.waitForSelector('#sub-wo-list .wo-opt')
check('All sites brings the rest back', (await page.$$eval('#sub-wo-list .wo-opt', (o) => o.length)) > inSite.length)
await page.keyboard.press('Escape')

// --- A draft has nothing to measure, so the picker leaves it out ----------------------------------------------------
const draft = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0].id, contractor_id: made.gang.id, job_id: made.job.id, department: 'Civil', subject: 'E2E still a draft', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await page.evaluate(() => loadSubBills())
await sleep(1200)
await page.click(find)
await page.waitForSelector('#sub-wo-list .wo-opt')
const listedText = await text('#sub-wo-list')
check('a draft is not in the picker', !listedText.includes(draft.wo_number))
check('nor is anything else that is not approved or amended', !/draft|awaiting|cancelled/.test(listedText))

await done()
