import { api, clickCell, clickText, fill, launch, open, signIn, sleep, text, toastsGone } from './lib.mjs'

// Enquiries: list items picked from the item master, ask a supplier by link, take three quotes, compare them, put a
// quote right, correct the enquiry, award it into a purchase order - and cancel another one.
const { page, check, done } = await launch()
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const title = `QA Cement and steel ${stamp}`
const gone = () => page.waitForFunction(() => !document.querySelector('[role=dialog], [role=alertdialog]'), { timeout: 10000 })
const last = (label) => page.evaluate((label) => [...[...document.querySelectorAll('[role=dialog]')].pop().querySelectorAll('button')].find((b) => b.textContent.trim().startsWith(label)).click(), label)
const idFromUrl = () => Number(page.url().split('/store/enquiries/')[1]?.split(/[?#]/)[0])

// A material in the master, to pick on the enquiry's first line.
const item = (await api(page, 'POST', '/api/items', { item_name: `QA Cement OPC 53 ${stamp}`, kind: 'RM', units_of_measure: 'Bags' })).data.item

await open(page, '/store/enquiries')
await clickText(page, 'main button', 'New enquiry')
await page.waitForSelector('#rn-title')
await fill(page, '#rn-title', title)
await clickCell(page, 0, 0, 0, '[role=dialog]')
await page.keyboard.type(`QA Cement OPC 53 ${stamp}`)
await sleep(300)
await page.keyboard.press('Enter')
await sleep(200)
await clickCell(page, 0, 0, 3, '[role=dialog]')
await page.keyboard.type('200')
await page.keyboard.press('Enter')
await sleep(200)
await clickCell(page, 0, 1, 1, '[role=dialog]')
await page.keyboard.type('QA TMT bar 12mm')
await page.keyboard.press('Tab')
await page.keyboard.type('MT')
await page.keyboard.press('Tab')
await page.keyboard.type('5')
await page.keyboard.press('Enter')
await sleep(300)
await last('Open the enquiry')
await page.waitForFunction(() => /\/store\/enquiries\/\d+/.test(location.pathname), { timeout: 15000 })
await page.waitForSelector('section[aria-label=Suppliers]')
await gone()
const id = idFromUrl()
check('a new enquiry opens on its own page, at the suppliers, with nobody asked yet', (await text(page, 'main h1')) === title && (await text(page, 'ol[aria-label=Progress]')).includes('Nobody asked yet'))
let st = (await api(page, 'GET', `/api/rfqs/${id}/statement`)).data
check('the item picked from the master brings its code, name and unit', st.lines[0].item_code === item.item_code && st.lines[0].uom === 'Bags' && st.lines[0].description === item.item_name, JSON.stringify(st.lines[0]))
await toastsGone(page)

// Ask a supplier by link
await clickText(page, 'main button', 'Ask by link')
await page.waitForSelector('#as-name')
await fill(page, '#as-name', `Delta Steel ${stamp}`)
await last('Make the link')
await page.waitForFunction(() => document.querySelector('[role=dialog]')?.textContent.includes('Link ready'), { timeout: 10000 })
await last('Done')
await gone()
await sleep(600)
check('the supplier asked is listed, waiting on the link', (await text(page, 'section[aria-label=Suppliers]')).includes(`Delta Steel ${stamp}`) && (await text(page, 'section[aria-label=Suppliers]')).includes('Link sent'))

// One quote typed in on screen, two more sent straight in
await clickText(page, 'main button', 'Enter a quote')
await page.waitForSelector('#rq-sup')
await fill(page, '#rq-sup', `Alpha Traders ${stamp}`)
await fill(page, '#rq-freight', '500')
await fill(page, 'input[aria-label="Rate 1"]', '400')
await fill(page, 'input[aria-label="Rate 2"]', '65000')
await last('Save the quote')
await gone()
await toastsGone(page)
const quote = (supplier, rates, freight) => api(page, 'POST', `/api/rfqs/${id}/quotes`, { supplier_name: `${supplier} ${stamp}`, quote_ref: 'Q1', quote_date: '2026-10-01', payment_terms: '30 days', freight, delivery_days: 5, lines: st.lines.map((l, i) => ({ rfq_line_id: l.rfq_line_id, rate: rates[i], tax_percent: 18 })) })
for (const [name, rates, freight] of [['Beta Supplies', [395, 66000], 1500], ['Gamma Steel', [410, 64000], 0]]) {
  const res = await quote(name, rates, freight)
  if (res.status !== 200) console.log('quote refused', res.status, JSON.stringify(res.data).slice(0, 200))
}

await open(page, `/store/enquiries/${id}?view=compare`)
await page.waitForSelector('table[aria-label=Comparison] tfoot')
// Quotes sent from outside the screen show as soon as the enquiry is opened again.
await page.waitForFunction((s) => document.querySelector('table[aria-label=Comparison]')?.textContent.includes(`Gamma Steel ${s}`), { timeout: 15000 }, stamp).catch(() => {})
const t = await text(page, 'table[aria-label=Comparison]')
check('three suppliers sit side by side with their totals at site and ranks', ['Alpha', 'Beta', 'Gamma'].every((n) => t.includes(n)) && /L1/.test(t) && t.includes('Total at site'), t.slice(0, 200))
await clickText(page, 'section[aria-label="Comparative statement"] [role=tab]', 'Amount')
await sleep(300)
check('the sheet shows amounts as well as rates', (await text(page, 'table[aria-label=Comparison]')).includes('80,000.00'))

// Alpha revises the cement rate
await page.click(`button[aria-label="Edit Alpha Traders ${stamp}'s quote"]`)
await page.waitForSelector('input[aria-label="Rate 1"]')
check('editing a quote starts from what was quoted', (await page.$eval('input[aria-label="Rate 2"]', (e) => e.value)).replace(/\D/g, '') === '65000')
await fill(page, 'input[aria-label="Rate 1"]', '380')
await last('Save changes')
await gone()
await toastsGone(page)
await clickText(page, 'section[aria-label="Comparative statement"] [role=tab]', 'Rate per unit')
await sleep(500)
check('the revised rate replaces the old one', (await text(page, 'table[aria-label=Comparison]')).includes('380.00'))

// Correct the enquiry: the title changes, the priced items stay
await clickText(page, 'main button', 'Edit')
await page.waitForSelector('#rn-title')
check('once quoted, the items are shown locked', (await text(page, '[role=dialog]')).includes('stay as they are'))
await fill(page, '#rn-title', `${title} (Block A)`)
await last('Save changes')
await gone()
await sleep(600)
check('the corrected title shows', (await text(page, 'main h1')) === `${title} (Block A)`)
await toastsGone(page)

// Award to the lowest total: one item is cheaper elsewhere, so a reason is asked for
st = (await api(page, 'GET', `/api/rfqs/${id}/statement`)).data
await clickText(page, 'main button', `Award to ${st.l1}`)
await page.waitForSelector('[role=radiogroup][aria-label="How to award"]')
check('the award says which order it makes', (await text(page, '[role=dialog]')).includes('This makes one purchase order'))
if (await page.$('#aw-reason')) await fill(page, '#aw-reason', 'One delivery for everything')
await last('Make the purchase order')
await gone()
await sleep(800)
check('the enquiry says it was awarded and names the order', /Awarded/.test(await text(page, 'main')) && /PO-/.test(await text(page, 'ol[aria-label=Progress]')))
const pos = (await api(page, 'GET', '/api/purchase-orders')).data.orders
check('the award made a draft purchase order for the lowest total', pos.some((o) => o.supplier_name === st.l1 && o.status === 'Draft'))

// The list: awarded under its own tab; an old ?id= link still opens the page
await open(page, '/store/enquiries?show=awarded')
await page.waitForSelector('table[aria-label=Enquiries] tbody tr')
check('the awarded tab lists it, awarded to the supplier', (await text(page, 'table[aria-label=Enquiries]')).includes(`${title} (Block A)`))
await page.goto(page.url().replace(/\/store\/enquiries.*$/, `/store/enquiries?id=${id}`), { waitUntil: 'networkidle0' })
await page.waitForSelector('ol[aria-label=Progress]')
check('an old link to the enquiry opens its page', idFromUrl() === id)

// Cancel another
const other = (await api(page, 'POST', '/api/rfqs', { title: `QA Plywood ${stamp}`, lines: [{ description: 'Plywood 19mm', uom: 'Nos', qty: 40 }] })).data.rfq.id
await open(page, `/store/enquiries/${other}`)
await clickText(page, 'main button', 'Cancel enquiry')
await page.waitForSelector('#pm-reason')
await fill(page, '#pm-reason', 'Bought locally')
await last('Cancel the enquiry')
await gone()
await sleep(600)
check('a cancelled enquiry says so and can no longer be edited', (await text(page, 'main')).includes('Cancelled') && !(await page.$$eval('main button', (b) => b.some((x) => x.textContent.trim() === 'Edit'))))
await done()
