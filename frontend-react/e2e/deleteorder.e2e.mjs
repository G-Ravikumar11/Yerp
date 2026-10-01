import { api, approvedOrder, clickText, launch, measure, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Delete a work order: the owner's alone, and from everywhere.
const { page, check, done } = await launch({ allow: [/^(403|404|409) /] })

await signIn(page)
const stamp = Date.now().toString().slice(-6)
const dialog = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))

// --- A subcontract order with a measurement and a bill ----------------------------------------------------------
const o = await approvedOrder(page, { subject: `Delete me ${stamp}` })
await measure(page, o.id, o.items[0].item_id, 10)
const bill = (await api(page, 'POST', '/api/sub-bills', { order_id: o.id })).data
const billId = bill.bill?.id ?? bill.id
check('the order has a bill behind it', !!billId, JSON.stringify(bill).slice(0, 100))
await open(page, `/subcontractors/work-orders/${o.id}`)
await clickText(page, 'main button', 'Delete')
await page.waitForSelector('[role=dialog]')
await page.waitForFunction(() => /Along with it|Nothing else|cannot be deleted/.test(document.querySelector('[role=dialog]')?.textContent || ''), { timeout: 8000 })
const d = await dialog()
check('the dialog says what goes with it', /1 bill/.test(d) && /measurement/.test(d), d.slice(0, 220))
await clickText(page, '[role=dialog] button', 'Delete everywhere')
await page.waitForFunction(() => location.pathname.endsWith('/subcontractors/work-orders'), { timeout: 10000 })
check('it returns to the list', true)
check('the order is gone', (await api(page, 'GET', `/api/wo/orders/${o.id}`)).status === 404)
check('and its bill', (await api(page, 'GET', `/api/sub-bills/${billId}`)).status === 404)
await open(page, '/subcontractors/measurement-book')
await sleep(1200)
await page.click('button[aria-label="Work order"]')
const opts = await page.$$eval('[role=listbox] [role=option]', (x) => x.map((e) => e.textContent))
check('and out of the Measurement Book', !opts.some((t) => t.includes(o.number)), String(opts.length))
await open(page, '/subcontractors/ra-bills')
await sleep(1000)
check('and out of the RA bills', !(await page.$eval('main', (e) => e.textContent)).includes(o.number))

// --- Money behind it stops the delete -------------------------------------------------------------------
const paidOrder = await approvedOrder(page, { subject: `Paid ${stamp}` })
const adv = (await api(page, 'GET', `/api/wo/orders/${paidOrder.id}`)).data
const adv0 = (adv.order ?? adv).mobilization_advance_amount
if (adv0 > 0) {
  await api(page, 'POST', '/api/money/entries', { doc_type: 'sub_advance', doc_id: paidOrder.id, amount: adv0, mode: 'Bank transfer', reference: `UTR${stamp}` })
  await open(page, `/subcontractors/work-orders/${paidOrder.id}`)
  await clickText(page, 'main button', 'Delete')
  await page.waitForFunction(() => /cannot be deleted/.test(document.querySelector('[role=dialog]')?.textContent || ''), { timeout: 8000 })
  check('an order with money paid says why it cannot go, and the button is off', (await page.$eval('[role=dialog]', (e) => [...e.querySelectorAll('button')].find((b) => b.textContent.includes('Delete everywhere')).disabled)))
  await page.keyboard.press('Escape')
}

// --- A client work order -----------------------------------------------------------------------------------------
const made = (await api(page, 'POST', '/api/erp/items/bulk', { items: [{ kind: 'FG', item_name: `DEL Panel ${stamp}`, units_of_measure: 'Nos', item_type: 'Service' }] })).data
const jobs = (await api(page, 'GET', '/api/jobs?open_only=true')).data.jobs
const wo = (await api(page, 'POST', '/api/erp/work-orders/build', { job_id: jobs[0].id, reference: `PO/DEL/${stamp}`, lines: [{ code: made.codes[0], qty: 5, rate: 100 }] })).data.work_order
await open(page, '/clients/work-orders')
await page.waitForSelector(`button[aria-label="Delete ${wo.number}"]`)
await page.click(`button[aria-label="Delete ${wo.number}"]`)
await page.waitForFunction(() => /Along with it|Nothing else/.test(document.querySelector('[role=dialog]')?.textContent || ''), { timeout: 8000 })
await clickText(page, '[role=dialog] button', 'Delete everywhere')
await waitForToast(page, 'deleted')
await toastsGone(page)
check('a client work order is deleted too', (await api(page, 'GET', `/api/erp/work-orders/${wo.id}`)).status === 404)
check('and leaves the list', !(await page.$eval('main', (e) => e.textContent)).includes(wo.number))
await done()
