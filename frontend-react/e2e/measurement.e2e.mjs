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
await page.click('table[aria-label="Items on the order"] tbody tr:first-child td:last-child button:last-child')
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

// Opening a measurement right after closing the last one can catch the old dialog on its way out:
// wait for the new one's tabs, and try once more if they never come.
async function openFirstItem() {
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.evaluate(() => document.querySelector('table[aria-label="Items on the order"] tbody tr:first-child td:last-child button:last-child')?.click())
    try {
      await page.waitForSelector('[role=dialog] button[role=tab]', { timeout: 4000 })
      return
    } catch {
      await page.keyboard.press('Escape')
      await sleep(400)
    }
  }
  throw new Error('the measurement dialog did not open')
}

// --- A plain total ----------------------------------------------------------------------------
await openFirstItem()
await clickText(page, '[role=dialog] button[role=tab]', 'Just a total')
await fill(page, '#m-total', '45')
await clickText(page, '[role=dialog] button', 'Record it in the book')
await waitForToast(page, 'Recorded')
await sleep(500)

// --- Past the ceiling --------------------------------------------------------------------------
await openFirstItem()
await clickText(page, '[role=dialog] button[role=tab]', 'Just a total')
await fill(page, '#m-total', '130')
await page.waitForFunction(() => /past the 220/.test(document.querySelector('[role=dialog]')?.textContent ?? ''), { timeout: 5000 }).catch(() => {}) // the allowance follows the refetched book, which can land a moment late
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
check('a block already measured for that item is flagged, and left out unless asked', /already in the book/.test(matched))
await page.click('[role=dialog] label input[type=checkbox]')
await clickText(page, '[role=dialog] button', 'Record it in the book')
await waitForToast(page, 'recorded from')
await sleep(600)
check('the imported entry (114.4) is in the book', /114\.4/.test(await text()))

// --- Offline: keep the measurement on the device, send it when the signal returns ----------------------------
await page.setOfflineMode(true)
await page.evaluate(() => window.dispatchEvent(new Event('offline')))
await sleep(300)
check('going offline is shown in the top bar', (await page.$eval('header', (e) => e.textContent)).includes('Offline'))
await page.click('table[aria-label="Items on the order"] tbody tr:nth-child(2) td:last-child button:last-child')
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


// --- Fill the lines from an Excel sheet, inside the measure window ----------------------------------------------------
await open(page, `/subcontractors/measurement-book?order=${created.id}`)
await page.waitForSelector('table[aria-label="Items on the order"] tbody tr')
await page.click('table[aria-label="Items on the order"] tbody tr:first-child td:last-child button:last-child')
await page.waitForSelector('[role=dialog] [role=grid]')
check('the window offers the template to download', (await page.$('[role=dialog] a[href="/api/sub-mb/template.xlsx"]')) !== null)
const bytes = await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/api/sub-mb/template.xlsx', { credentials: 'include' })).arrayBuffer())))
const sheet = join(tmpdir(), 'e2e-mb-template.xlsx')
writeFileSync(sheet, Buffer.from(bytes))
await (await page.$('input[aria-label="Excel file to read the lines from"]')).uploadFile(sheet)
// Nothing is loaded for the person: the sheet's entry is listed, and loads when it is clicked.
await page.waitForFunction(() => /Block C-3/.test(document.querySelector('[role=dialog]')?.textContent ?? ''), { timeout: 10000 })
await sleep(300)
check('a sheet with one matching entry is listed, not loaded by itself', (await page.$eval('#m-where', (e) => e.value)) === '')
await page.click('[role=dialog] button[title^="Load just this one"]')
await page.waitForSelector('[aria-label="Blocks loaded from the sheet"] section[aria-label="Block 1"]', { timeout: 10000 })
const rows = await page.$$eval('[aria-label="Blocks loaded from the sheet"] [role=grid] [role=row]', (rs) => rs.slice(1, 4).map((r) => r.querySelector('[role=gridcell]')?.textContent.trim()))
check('importing the sheet fills the lines from it', rows[0] === 'Slab' && rows[1] === 'Beam', rows.join(' | '))
check('and where it was measured', (await page.$eval('[aria-label="Blocks loaded from the sheet"] input[id^="sb-where-"]', (e) => e.value)) === 'Block C-3, First Floor')
check('the quantity is worked out from those lines (114.4)', (await page.$eval('[role=dialog]', (e) => e.textContent)).includes('114.4'))
check('nothing is recorded until asked', (await api(page, 'GET', `/api/sub-mb/${created.id}`)).data.entries.every((e) => !(e.quantity === 114.4 && e.mb_ref.includes('e2e-mb-template'))))
await page.keyboard.press('Escape')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))

// --- Narrow the work orders to one site -------------------------------------------------------------------------------------
const other = vocab.jobs[1]
let otherBudgets = (await api(page, 'GET', `/api/wo/projects/${other.id}/budgets`)).data.budgets
if (!otherBudgets.length) {
  await api(page, 'POST', `/api/wo/projects/${other.id}/budgets`, { name: 'E2E other', code: 'E2E-2', allocated_amount: 90000000 })
  otherBudgets = (await api(page, 'GET', `/api/wo/projects/${other.id}/budgets`)).data.budgets
}
const elsewhere = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: other.id, department: 'Civil', subject: 'E2E other site', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await api(page, 'PUT', `/api/wo/orders/${elsewhere.id}/boq`, { lines: [{ activity_no: '1.0', item_description: 'Plastering', uom: 'sqm', quantity: 100, unit_rate: 200, budget_id: otherBudgets[0].id }] })
await api(page, 'POST', `/api/wo/orders/${elsewhere.id}/self-approve`, { comments: 'e2e' })
await open(page, `/subcontractors/measurement-book?order=${created.id}`)
await page.waitForSelector('select[aria-label="Site"]')
const siteOptions = await page.$$eval('select[aria-label="Site"] option', (o) => o.map((e) => e.textContent))
check('the sites of the work orders can be chosen from', siteOptions.length >= 3 && siteOptions[0].startsWith('All sites'), siteOptions.join(' | '))
await page.select('select[aria-label="Site"]', String(other.id))
await page.waitForFunction((id) => location.search.includes('order=' + id), {}, elsewhere.id)
await page.click(picker)
await page.waitForSelector('[role=listbox] [role=option]')
const inSite = await page.$$eval('[role=listbox] [role=option]', (o) => o.map((e) => e.textContent))
check('choosing a site lists only its work orders, and opens the first', inSite.length >= 1 && inSite.every((t) => t.includes(other.number)), `${inSite.length} listed`)
await page.keyboard.press('Escape')
await page.select('select[aria-label="Site"]', '')
await page.click(picker)
await page.waitForSelector('[role=listbox] [role=option]')
const everywhere = await page.$$eval('[role=listbox] [role=option]', (o) => o.map((e) => e.textContent))
check('All sites brings the rest back', everywhere.some((t) => t.includes(other.number)) && everywhere.some((t) => t.includes(vocab.jobs[0].number)))
await page.keyboard.press('Escape')

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


// --- Amended twice: the line of revisions sits together, and the oldest points at the one now live -----------------
const rev2 = (await api(page, 'POST', `/api/wo/orders/${rev.id}/amend`, {})).data.order
await api(page, 'POST', `/api/wo/orders/${rev2.id}/self-approve`, {})
await page.evaluate(() => indexedDB.deleteDatabase('keyval-store'))
await open(page, `/subcontractors/measurement-book?order=${old.id}`)
await page.waitForSelector('[role=status]')
const banner2 = await page.$eval('[role=status]', (e) => e.textContent)
check('the oldest order, amended twice, points to the revision that is live now', banner2.includes(rev2.wo_number) && banner2.includes('amended'), banner2.slice(0, 120))
await page.click('button[aria-label="Work order"]')
await page.waitForSelector('[role=listbox] [role=option]')
const options = await page.$$eval('[role=listbox] [role=option]', (o) => o.map((e) => e.textContent))
const at = options.findIndex((t) => t.includes(rev2.wo_number))
check('and each amended order is listed directly under the one that replaced it', at >= 0 && options[at + 1]?.includes(rev.wo_number) && options[at + 2]?.includes(old.wo_number) && options[at + 1].includes('amended'), options.slice(at, at + 3).map((t) => t.slice(0, 40)).join(' | '))
await page.keyboard.press('Escape')

// --- A draft has nothing to measure, so the picker leaves it out -----------------------------------------------
const draft = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: job.id, department: 'Civil', subject: 'E2E still a draft', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await open(page, `/subcontractors/measurement-book?order=${created.id}`)
await page.click('button[aria-label="Work order"]')
await page.waitForSelector('[role=listbox] [role=option]')
const listed = await page.$$eval('[role=listbox] [role=option]', (o) => o.map((e) => e.textContent))
check('a draft is not in the picker', !listed.some((t) => t.includes(draft.wo_number)) && listed.length >= 2, `${listed.length} listed`)
check('nor is anything else that is not approved or amended', !listed.some((t) => /draft|awaiting|cancelled/.test(t)))
await page.keyboard.press('Escape')
await open(page, `/subcontractors/measurement-book?order=${draft.id}`)
await page.waitForSelector('[role=status]')
check('opened by its link, a draft says it is still a draft', (await page.$eval('[role=status]', (e) => e.textContent)).includes('still a draft'))
check('and it takes no measurements', (await page.$('input[aria-label="Item code"]')) === null)

await done()
