// The AI help on a purchase order and on an enquiry. With no key set the plain checks still answer, the email is a plain draft,
// and the quote reader says it is not set up - nothing is saved by any of them.
import { api, clickText, launch, open, signIn } from './lib.mjs'

const { page, check, done } = await launch()
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())

// --- a purchase order -----------------------------------------------------------------------------------------------
const supplier = `QA Steel ${stamp}`
const made = await api(page, 'POST', '/api/purchase-orders', { supplier_name: supplier, supplier_email: 'qa@example.com', amount: 1000, line_items: [{ description: 'TMT Fe500D', item_code: 'RM-STL', qty: 10, price: 100 }] })
check('an order is made', made.status === 200)
await open(page, '/store/purchase-orders')
await page.waitForSelector('main table')
const row = await page.evaluateHandle((s) => [...document.querySelectorAll('main table tbody tr')].find((r) => r.textContent.includes(s)), supplier)
await row.evaluate((r) => [...r.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Edit').click())
await page.waitForSelector('[aria-label="AI help"]')
await clickText(page, '[aria-label="AI help"] button', 'Review it')
await page.waitForSelector('[aria-label="Order review"]')
check('the order review shows its plain checks', /No delivery date/.test(await text('[aria-label="Order review"]')))
await clickText(page, '[aria-label="AI help"] button', 'Draft the supplier email')
await page.waitForSelector('[aria-label="Email draft"]')
const mail = await text('[aria-label="Email draft"]')
check('the email draft names the supplier and the order, and says it is standard wording', /qa@example.com/.test(mail) && /Please find our purchase order/.test(mail) && /standard wording/.test(mail))
await page.keyboard.press('Escape')

// --- an enquiry ------------------------------------------------------------------------------------------------------
const rfq = await api(page, 'POST', '/api/rfqs', { title: `QA AI enquiry ${stamp}`, lines: [{ item_code: 'RM-CEM', description: 'Cement OPC 53', uom: 'Bags', qty: 100 }, { item_code: 'RM-STL', description: 'TMT Fe500D', uom: 'MT', qty: 5 }] })
const rfqId = rfq.data.rfq.id
const lines = (await api(page, 'GET', `/api/rfqs/${rfqId}`)).data.lines
for (const [name, a, b] of [['ACC', 390, 62000], ['Dalmia', 520, 61000]]) {
  await api(page, 'POST', `/api/rfqs/${rfqId}/quotes`, { supplier_name: name, freight: 0, lines: [{ rfq_line_id: lines[0].rfq_line_id, rate: a, tax_percent: 18 }, { rfq_line_id: lines[1].rfq_line_id, rate: b, tax_percent: 18 }] })
}
await open(page, '/store/enquiries')
await page.waitForSelector('main table')
const r = await page.evaluateHandle((t) => [...document.querySelectorAll('main table tbody tr')].find((x) => x.textContent.includes(t)), `QA AI enquiry ${stamp}`)
await (await r.$('button')).click()
await page.waitForSelector('table[aria-label=Comparison]')
await clickText(page, 'section[aria-label^="Comparative statement"] button', 'Recommend')
await page.waitForSelector('[aria-label="Recommendation"]')
check('the recommendation flags the wide spread between quotes', /above the cheapest/.test(await text('[aria-label="Recommendation"]')))
await clickText(page, 'section[aria-label^="Comparative statement"] button', 'Read a quote')
await page.waitForSelector('#rd-text')
await page.type('#rd-text', 'ACC cement 391 per bag')
await clickText(page, '[role=dialog] button', 'Read it')
await page.waitForSelector('[role=dialog] [role=alert], [role=dialog] [aria-label="What was read"]')
check('the quote reader says plainly it is not set up, and records nothing', /not set up|Add/.test(await text('[role=dialog]')) && (await api(page, 'GET', `/api/rfqs/${rfqId}`)).data.suppliers.length === 2)
await done()
