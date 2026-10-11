// A contractor's papers, a back-charge taken off a draft bill, and an order's settlement - on screen.
import { api, approvedOrder, clickText, fill, launch, measure, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/409 POST \/api\/sub-bills/] })
await signIn(page)
const order = await approvedOrder(page, { subject: 'E2E compliance' })
const conId = order.gang.id
const text = () => page.$eval('main', (m) => m.textContent.replace(/\s+/g, ' '))

// --- papers ---------------------------------------------------------------------------------------------------------
await open(page, '/subcontractors/compliance')
await page.waitForSelector('table[aria-label="Contractor compliance"]')
check('the page lists contractors and says who is safe to pay', /Safe to pay/.test(await text()))
const row = await page.evaluateHandle((name) => [...document.querySelectorAll('table[aria-label="Contractor compliance"] tbody tr')].find((r) => r.textContent.includes(name)), order.gang.company_name)
await row.click()
await page.waitForSelector('[role=dialog]')
check('a contractor with no papers is told what is missing', /is not on record/.test(await page.$eval('[role=dialog]', (d) => d.textContent)))
await setValue(page, '#cd-until', '2099-01-01')
await clickText(page, '[role=dialog] button', 'Add')
await waitForToast(page, 'recorded')
await sleep(500)
check('a paper added shows with its date and state', /Contract labour licence/.test(await page.$eval('[role=dialog]', (d) => d.textContent)))
await page.keyboard.press('Escape')
await toastsGone(page)

// --- a back-charge off a draft bill ---------------------------------------------------------------------------------
const item = order.items[0]
await measure(page, order.id, item.item_id, 100)
const made = await api(page, 'POST', '/api/sub-bills', { order_id: order.id })
const billId = made.data.bill.id
const before = made.data.bill.net_payable
const charge = await api(page, 'POST', '/api/back-charges', { contractor_id: conId, order_id: order.id, kind: 'Wastage', reason: 'E2E cement wasted', amount: 250 })
check('a back-charge is raised', charge.status === 200 && charge.data.back_charge.status === 'OPEN')

await open(page, `/subcontractors/ra-bills/${billId}`)
await page.waitForFunction(() => /Papers and back-charges/.test(document.querySelector('main')?.textContent ?? ''))
await clickText(page, 'main button', 'Take off this bill')
await waitForToast(page, 'Back-charges taken off')
await sleep(600)
const after = (await api(page, 'GET', `/api/sub-bills/${billId}`)).data
check('the bill carries the back-charge and is smaller by it', after.back_charges === 250 && Math.round(after.net_payable) === Math.round(before - 250), `${before} -> ${after.net_payable}`)
check('the bill page shows it as a deduction', /Back-charges/.test(await text()))
await toastsGone(page)
await clickText(page, 'main button', 'Take off')
await waitForToast(page, 'is open again')
await sleep(500)
check('taking it off gives the amount back', Math.round((await api(page, 'GET', `/api/sub-bills/${billId}`)).data.net_payable) === Math.round(before))

// --- the charges list and the settlement ------------------------------------------------------------------------------
await open(page, '/subcontractors/compliance')
await clickText(page, 'main button, main [role=tab]', 'Back-charges')
await page.waitForSelector('table[aria-label="Back-charges"]')
check('the back-charge is listed as open', /E2E cement wasted/.test(await text()))
await clickText(page, 'main button, main [role=tab]', 'Order settlement')
await page.waitForFunction((id) => !!document.querySelector(`select[aria-label="Order"] option[value="${id}"]`), {}, String(order.id))
await page.select('select[aria-label="Order"]', String(order.id))
await page.waitForFunction(() => /Still to pay/.test(document.querySelector('main')?.textContent ?? ''))
check('an order with a draft bill and an open back-charge is not ready to close', /Not ready to close/.test(await text()))
await done()
