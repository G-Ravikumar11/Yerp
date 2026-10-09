// The AI buttons on a bill and on a contractor. With no key set the plain checks must still answer, and say so plainly.
import { api, approvedOrder, clickText, launch, measure, open, signIn, sleep } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/409 POST \/api\/sub-bills/] })
await signIn(page)
const order = await approvedOrder(page, { subject: 'E2E AI check' })
await measure(page, order.id, order.items[0].item_id, 100)
const billId = (await api(page, 'POST', '/api/sub-bills', { order_id: order.id })).data.bill.id
const text = () => page.$eval('main', (m) => m.textContent.replace(/\s+/g, ' '))

await open(page, `/subcontractors/ra-bills/${billId}`)
await page.waitForFunction(() => /Check this bill/.test(document.querySelector('main')?.textContent ?? ''))
check('the bill page offers the check, and says when the AI is not set up', /not set up yet/.test(await text()) || /Review the bill/.test(await text()))
await clickText(page, 'main button', 'Review the bill')
await page.waitForSelector('[aria-label="Bill review"]')
const review = await page.$eval('[aria-label="Bill review"]', (e) => e.textContent)
check('the plain checks answer without a key', /No hard copy/.test(review), review.slice(0, 120))

await open(page, '/subcontractors/compliance')
await page.waitForSelector('table[aria-label="Contractor compliance"]')
const row = await page.evaluateHandle((name) => [...document.querySelectorAll('table[aria-label="Contractor compliance"] tbody tr')].find((r) => r.textContent.includes(name)), order.gang.company_name)
await row.click()
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Get a brief')
await page.waitForSelector('[aria-label="Contractor brief"]')
check('a contractor brief shows their standing from the books', /order\(s\)/.test(await page.$eval('[aria-label="Contractor brief"]', (e) => e.textContent)))
await sleep(200)
await done()
