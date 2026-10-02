import { api, cellText, clickCell, clickText, fill, launch, open, setValue, signIn, sleep, waitForToast } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/still needs/] })
await signIn(page)

// What the demo has: an approved gang, a project, a trade.
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gangs = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.filter((c) => c.registration_status === 'APPROVED')
const job = vocab.jobs[0]
const gang = gangs[0]

await open(page, '/subcontractors/work-orders')
await page.waitForSelector('table[aria-label="Work orders"]')
const rows = () => page.$$eval('table[aria-label="Work orders"] tbody tr', (r) => r.length)
const before = await rows()
check('the work orders list loads with its summary tiles', before >= 0 && (await page.$eval('main', (e) => e.textContent)).includes('Committed value'), `${before} orders`)

// --- A new draft ----------------------------------------------------------------
await clickText(page, 'button', 'New work order')
await page.waitForSelector('#no-con')
await setValue(page, '#no-con', String(gang.id))
await setValue(page, '#no-job', String(job.id))
await setValue(page, '#no-dept', 'Civil')
await fill(page, '#no-subject', 'E2E shuttering, tower C')
await clickText(page, '[role=dialog] button', 'Open the draft')
await waitForToast(page, 'opened as a draft')
await page.waitForFunction(() => /\/work-orders\/\d+/.test(location.pathname))
const orderId = Number(page.url().match(/work-orders\/(\d+)/)[1])
await page.waitForSelector('main h1')
const number = await page.$eval('main h1', (e) => e.textContent.trim())
check('a draft opens with its number issued and the gang shown', /^WO\//.test(number) && (await page.$eval('main', (e) => e.textContent)).includes(gang.company_name), number)
check('the draft shows its state', (await page.$eval('main', (e) => e.textContent)).includes('Draft'))

// --- Submitting an incomplete order says what is missing -----------------------------
await clickText(page, 'main button', 'Submit for approval')
await page.waitForFunction(() => document.querySelector('[aria-live=polite]')?.textContent.includes('still needs'), { timeout: 8000 })
const refusal = await page.$eval('[aria-live=polite]', (e) => e.textContent)
check('an incomplete order is refused, in the server\'s words', /still needs .*commencement date/.test(refusal), refusal.slice(0, 110))

// --- The details ---------------------------------------------------------------------
await setValue(page, '#h-start', '2026-11-01')
await setValue(page, '#h-end', '2027-03-31')
await fill(page, '#h-ret', '5')
check('Save is offered once something changes', await page.$eval('main button', () => !![...document.querySelectorAll('main button')].find((b) => b.textContent.trim() === 'Save' && !b.disabled)))

// --- The schedule, typed into the grid -------------------------------------------------
await clickText(page, 'button[role=tab]', 'Schedule')
await page.waitForSelector('[role=grid]')
await clickCell(page, 0, 0, 2) // description, first row
await page.keyboard.type('Shuttering for slabs')
await page.keyboard.press('Tab')
await page.keyboard.type('sq')
await page.keyboard.press('Tab')
await page.keyboard.type('12.5*40') // quantity as arithmetic
await page.keyboard.press('Tab')
await page.keyboard.type('410')
await page.keyboard.press('Enter')
check('quantity worked out from 12.5*40', (await cellText(page, 0, 0, 4)) === '500.000', await cellText(page, 0, 0, 4))
check('the amount is worked out', (await cellText(page, 0, 0, 6)).includes('2,05,000'), await cellText(page, 0, 0, 6))
await clickCell(page, 0, 1, 2)
await page.keyboard.type('Reinforcement steel Fe500D')
await page.keyboard.press('Tab')
await page.keyboard.type('MT')
await page.keyboard.press('Tab')
await page.keyboard.type('18.5')
await page.keyboard.press('Tab')
await page.keyboard.type('68000')
await page.keyboard.press('Enter')
const total = await page.evaluate(() => [...document.querySelectorAll('[role=grid] [role=row]')].at(-1).textContent)
check('the schedule totals its amounts', total.includes('14,63,000'), total.replace(/\s+/g, ' ').slice(0, 60))

// --- The budget -------------------------------------------------------------------------------
await page.click('main button[type=button]:not([role=tab])', { delay: 0 }).catch(() => {})
const fresh = await api(page, 'GET', `/api/wo/projects/${job.id}/budgets`)
if (!fresh.data.budgets.length) {
  await api(page, 'POST', `/api/wo/projects/${job.id}/budgets`, { name: 'E2E civil', code: 'E2E-1', allocated_amount: 50000000 })
}

// --- Save, then charge the lines to the cost centre ---------------------------------------------
await clickText(page, 'main button', 'Save')
await waitForToast(page, 'Saved')
await page.waitForFunction(() => !document.body.textContent.includes('Unsaved changes'))
await clickText(page, 'button[role=tab]', 'Schedule')
await page.waitForSelector('[role=grid]')
const optionValues = await page.$$eval('select[aria-label="Cost centre for every line"] option', (o) => o.map((x) => x.value).filter(Boolean))
check('the project\'s cost centres are offered', optionValues.length > 0, optionValues.join(','))
await setValue(page, 'select[aria-label="Cost centre for every line"]', optionValues[0])
await clickText(page, 'main button', 'Charge')
await waitForToast(page, 'charged')
const server = (await api(page, 'GET', `/api/wo/orders/${orderId}`)).data.order
check('what was typed was saved: two lines, gross 14,63,000', server.item_count === 2 && server.gross_amount === 1463000, `${server.item_count} lines, ${server.gross_amount}`)
check('the dates and retention were saved', server.commencement_date === '2026-11-01' && server.retention_percent === 5)

// --- Submit, then approve ------------------------------------------------------------------------------
await clickText(page, 'main button', 'Submit for approval')
await sleep(1500)

const afterSubmit = (await api(page, 'GET', `/api/wo/orders/${orderId}`)).data.order
check('submitting sends it for approval', afterSubmit.status === 'PROVISIONAL' || afterSubmit.status === 'APPROVED', afterSubmit.status)
if (afterSubmit.status === 'PROVISIONAL') {
  await clickText(page, 'main button', 'Approve')
  await page.waitForSelector('[role=dialog]')
  await clickText(page, '[role=dialog] button', 'Approve')
  await waitForToast(page, 'approved')
  await sleep(500)
}
const approved = (await api(page, 'GET', `/api/wo/orders/${orderId}`)).data.order
check('the owner can approve it', approved.status === 'APPROVED', approved.status)
check('an approved order is no longer editable', (await page.$('#h-start:not([disabled])')) === null)

// --- Approval tab -----------------------------------------------------------------------------------------
await clickText(page, 'button[role=tab]', 'Approval')
await sleep(300)
const approvalText = await page.$eval('main', (e) => e.textContent)
check('the approval tab shows the route and the history', approvalText.includes('History') && approvalText.includes('Approve'))

// --- Amend, then cancel the revision --------------------------------------------------------------------------
await clickText(page, 'main button', 'Amend')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Open a revision')
await waitForToast(page, 'amend')
await page.waitForFunction((id) => !location.pathname.endsWith('/' + id), {}, orderId)
const revId = Number(page.url().match(/work-orders\/(\d+)/)[1])
const rev = (await api(page, 'GET', `/api/wo/orders/${revId}`)).data.order
const original = (await api(page, 'GET', `/api/wo/orders/${orderId}`)).data.order
check('an amendment opens a draft revision and leaves the original live', rev.status === 'DRAFT' && rev.supersedes_id === orderId && original.status === 'APPROVED', `${rev.wo_number} draft; original ${original.status}`)
await clickText(page, 'main button', 'Cancel order')
await page.waitForSelector('[role=dialog] textarea')
await clickText(page, '[role=dialog] button', 'Cancel the order')
await sleep(500)
check('cancelling asks for a reason', (await page.$eval('[role=dialog]', (e) => e.textContent)).includes('Say why'))
await page.type('[role=dialog] textarea', 'E2E clean up')
await clickText(page, '[role=dialog] button', 'Cancel the order')
await waitForToast(page, 'cancelled')
await sleep(400)
const cancelled = (await api(page, 'GET', `/api/wo/orders/${revId}`)).data.order
check('the revision is cancelled', cancelled.status === 'CANCELLED', cancelled.status)

// --- Back on the list ------------------------------------------------------------------------------------------------
await open(page, '/subcontractors/work-orders')
await page.waitForSelector('table[aria-label="Work orders"] tbody tr')
await fill(page, 'input[aria-label="Search"]', 'E2E')
await sleep(300)
check('search finds the order by what was typed on it', (await rows()) >= 1, `${await rows()} rows`)
await page.click('table[aria-label="Work orders"] tbody tr')
await page.waitForFunction(() => /\/work-orders\/\d+/.test(location.pathname))
check('clicking a row opens the order', true)

await done()
