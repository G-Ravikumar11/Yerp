import { api, clickText, fill, launch, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Clients > Measurement & RA Bills: measure a client order, go past it, raise a variation, draw up and certify a bill.
const { page, check, done } = await launch({ allow: [/409 POST \/api\//] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const [code, rm] = (await api(page, 'POST', '/api/erp/items/bulk', { items: [{ kind: 'FG', item_name: `E2E Slab ${stamp}`, units_of_measure: 'Cum', item_type: 'Service' }, { kind: 'RM', item_name: `E2E Cement ${stamp}`, units_of_measure: 'Bag', item_type: 'Purchased' }] })).data.codes
const job = (await api(page, 'GET', '/api/jobs?open_only=true')).data.jobs[0]
const wo = (await api(page, 'POST', '/api/erp/work-orders/build', { job_id: job.id, reference: `PO/BOOK/${stamp}`, lines: [{ code, qty: 10, rate: 500 }] })).data.work_order
await api(page, 'POST', '/api/erp/bom/build', { work_order_id: wo.id, lines: [{ fg_code: code, rm_code: rm, qty: 100, rate: 20 }] })
const sent = await api(page, 'POST', `/api/erp/work-orders/${wo.id}/place-order`)
if (sent.status !== 200) throw new Error('could not place the order: ' + JSON.stringify(sent.data))
const placed = sent.data.work_order
if (placed.approval_status !== 'approved') await api(page, 'POST', `/api/erp/work-orders/${wo.id}/decide`, { decision: 'approve', note: 'e2e' })
const dialogText = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
const mainText = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' '))

await open(page, `/clients/measurement?order=${wo.id}`)
await page.waitForSelector('table[aria-label="Items on the order"] tbody tr')
check('the book opens on the approved order with its line', (await mainText()).includes(code) && (await mainText()).includes('Where this order stands'), code)
check('the statement shows the order value and what is left to build', (await mainText()).includes('Original order') && (await mainText()).includes('5,000'))
const picker = 'button[aria-label="Work order"]'
check('the picker names the order and its job code', (await page.$eval(picker, (e) => e.textContent)).includes(wo.number))

// --- Measure a part of it by typing the item code ------------------------------------------------------------
await page.click('input[aria-label="Item code"]')
await page.keyboard.type(code)
await sleep(250)
const card = await page.$$eval('main [aria-live=polite]', (els) => els.map((e) => e.textContent).join(' | '))
check('typing the code fills in the item from the order', /cum/i.test(card) && card.includes(code), card)
await page.keyboard.press('Enter')
await page.waitForSelector('[role=dialog]')
check('the window asks who witnessed it, and offers no blocks-alike', (await dialogText()).includes('Witnessed by') && !(await dialogText()).includes('Blocks built alike'))
await clickText(page, '[role=dialog] button[role=tab]', 'Just a total')
await fill(page, '#m-total', '4')
await fill(page, '#m-witness', 'Site engineer')
await clickText(page, 'button', 'Record it in the book')
await waitForToast(page, 'easure')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await page.waitForFunction(() => document.querySelector('main')?.textContent.includes('witnessed: Site engineer'), { timeout: 10000 }).catch(() => {})
check('the entry is in the book, witnessed', (await mainText()).includes('witnessed: Site engineer'))
await toastsGone(page)

// --- Draw up a bill, submit and certify it -----------------------------------------------------------------------------
await clickText(page, 'button', 'Draw up a bill')
await clickText(page, '[role=dialog] button', 'Draw it up')
await waitForToast(page, 'RA')
await page.waitForFunction(() => document.querySelector('table[aria-label="Running account bills"] tbody')?.textContent.includes('2,000'), { timeout: 10000 })
check('a bill claims what was measured (4 x 500 = 2,000)', true)
await toastsGone(page)
await clickText(page, 'table[aria-label="Running account bills"] button', 'Submit')
await waitForToast(page, 'ubmitted')
await toastsGone(page)
await clickText(page, 'table[aria-label="Running account bills"] button', 'Certify')
await page.waitForFunction(() => document.querySelector('table[aria-label="Running account bills"] tbody')?.textContent.includes('Certified'), { timeout: 10000 })
check('it is submitted and certified, and can then be received', (await page.$eval('table[aria-label="Running account bills"]', (e) => e.textContent)).includes('Receive'))
check('the bill prints as a PDF', (await page.$(`a[href^="/api/ra-bills/"][href$="/document.pdf"]`)) !== null)
await toastsGone(page)

// --- Build past the order: a variation -------------------------------------------------------------------------------------
await page.click('input[aria-label="Item code"]')
await page.keyboard.type(code)
await sleep(200)
await page.keyboard.press('Enter')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button[role=tab]', 'Just a total')
await fill(page, '#m-total', '8')
await clickText(page, 'button', 'Record it in the book')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(800)
check('past the order the line is flagged over', (await mainText()).includes('over the order'))
check('and a variation is offered, raised from the book', (await mainText()).includes('been built past the order'))
await toastsGone(page)
await clickText(page, 'button', 'Raise it from the book')
await fill(page, '[role=dialog] textarea, [role=dialog] input[type=text]', 'Extra slab to the landing')
await clickText(page, '[role=dialog] button', 'Raise it')
await page.waitForFunction(() => document.querySelector('table[aria-label="Variations"] tbody')?.textContent.includes('from the book'), { timeout: 10000 })
check('the variation is raised as a draft that can be submitted', (await page.$eval('table[aria-label="Variations"]', (e) => e.textContent)).includes('Submit'))

await done()
