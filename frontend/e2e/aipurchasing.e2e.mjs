// The AI help on a purchase order and on an enquiry's quotes. With no key set the plain checks still answer, the email is a
// plain draft, and the quote reader says it could not read the file - nothing is saved by any of them.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
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
// A supplier's quotation file chosen in the quote form: with no AI key the form says it could not read it, keeps the
// form for typing, and records nothing until saved.
const quoteFile = path.join(os.tmpdir(), `quote_${stamp}.txt`)
fs.writeFileSync(quoteFile, 'ACC Ltd quotation. Cement OPC 53 Rs 391 per bag. TMT Fe500D Rs 61500 per MT.')
await open(page, `/store/enquiries/${rfqId}?view=suppliers`)
await clickText(page, 'main button', 'Enter a quote')
const picker = `input[aria-label="The supplier's quotation file"]`
await page.waitForSelector(picker)
await (await page.$(picker)).uploadFile(quoteFile)
await page.waitForSelector('[role=dialog] [role=status], [role=dialog] [role=alert]', { timeout: 30000 })
check('the quote reader says what it could do, and records nothing', /Read:|could not|not set up|Type the rates/i.test(await text('[role=dialog]')) && (await api(page, 'GET', `/api/rfqs/${rfqId}`)).data.suppliers.length === 2)
fs.unlinkSync(quoteFile)
await done()
