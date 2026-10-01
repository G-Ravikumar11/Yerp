import { api, clickText, fill, launch, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Goods receipt: take a delivery against an approved order, reject part of it, post it, raise the bill, and see the match.
const { page, check, done } = await launch()
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const gone = () => page.waitForFunction(() => !document.querySelector('[role=dialog], [role=alertdialog]'), { timeout: 10000 })

// An item and an approved order for ten of it
const made = await api(page, 'POST', '/api/erp/items/bulk', { items: [{ kind: 'RM', item_name: `QA bricks ${stamp}`, units_of_measure: 'Nos', last_rate: 8, item_type: 'Purchased' }] })
const code = made.data.codes[0]
const job = (await api(page, 'GET', '/api/jobs')).data.jobs[0]
const po = (await api(page, 'POST', '/api/purchase-orders', { supplier_name: `QA Brick Works ${stamp}`, amount: 1000, tax_amount: 0, total: 1000, issue_date: '2026-10-01', needed_by: '', notes: '', job_id: job.id, line_items: [{ item_code: code, description: `QA bricks ${stamp}`, uom: 'Nos', qty: 100, price: 10, tax_rate: '0%' }] })).data
const poId = po.id ?? po.order?.id
await api(page, 'PUT', `/api/purchase-orders/${poId}`, { supplier_name: `QA Brick Works ${stamp}`, amount: 1000, tax_amount: 0, total: 1000, issue_date: '2026-10-01', needed_by: '', notes: '', job_id: job.id, status: 'Approved', line_items: [{ item_code: code, description: `QA bricks ${stamp}`, uom: 'Nos', qty: 100, price: 10, tax_rate: '0%' }] })
await page.evaluate(() => indexedDB.deleteDatabase('keyval-store'))

await open(page, '/store/goods-receipt')
await page.waitForSelector('main h1')
await clickText(page, 'main button', 'Receive a delivery')
await page.waitForSelector('#gr-order')
await page.waitForFunction((s) => [...document.querySelectorAll('#gr-order option')].some((o) => o.textContent.includes(s)), { timeout: 8000 }, `QA Brick Works ${stamp}`)
await page.evaluate((s) => { const sel = document.querySelector('#gr-order'); const o = [...sel.options].find((x) => x.textContent.includes(s)); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(sel, o.value); sel.dispatchEvent(new Event('change', { bubbles: true })) }, `QA Brick Works ${stamp}`)
await fill(page, '#gr-challan', `CH-${stamp}`)
await fill(page, '#gr-veh', 'TS09AB1234')
await clickText(page, '[role=dialog] button', 'Open the receipt')
await waitForToast(page, 'opened')
await page.waitForSelector('table[aria-label=Lines] tbody tr')
check('the receipt opens on the order with its lines to check against the lorry', await page.evaluate((s) => [...document.querySelectorAll('[role=dialog]')].some((d) => d.textContent.includes(s) && d.textContent.includes('100')), `QA bricks ${stamp}`))
await toastsGone(page)
await fill(page, `input[aria-label="Received ${code}"]`, '60')
await fill(page, `input[aria-label="Rejected ${code}"]`, '10')
await fill(page, 'input[aria-label="Why rejected"]', 'Broken in transit')
await sleep(200)
check('accepted is worked out as it is typed (60 - 10 = 50, worth 500)', (await text('table[aria-label=Lines] tbody tr')).includes('50') && (await text('table[aria-label=Lines] tbody tr')).includes('₹500.00'))
await clickText(page, '[role=dialog] button', 'Save and post')
await sleep(1500)
await gone()
const row = () => page.evaluate((s) => [...document.querySelectorAll('table[aria-label="Goods receipts"] tbody tr')].find((r) => r.textContent.includes(s))?.textContent.replace(/\s+/g, ' '), `QA Brick Works ${stamp}`)
check('posted: accepted 500, rejected 100', /Posted/.test(await row()) && /500/.test(await row()), await row())
await toastsGone(page)

await page.evaluate((s) => [...document.querySelectorAll('table[aria-label="Goods receipts"] tbody tr')].find((r) => r.textContent.includes(s)).querySelectorAll('button')[0].click(), `QA Brick Works ${stamp}`)
await page.waitForSelector('table[aria-label=Lines]')
await clickText(page, '[role=dialog] button', 'Raise the supplier bill')
await waitForToast(page, 'drawn up')
check('the bill is drawn from what was accepted', true)
await page.keyboard.press('Escape')
await gone()
await sleep(800)
const matchRow = () => page.evaluate((s) => [...document.querySelectorAll('table[aria-label="Three-way match"] tbody tr')].find((r) => r.textContent.includes(s))?.textContent.replace(/\s+/g, ' '), `QA Brick Works ${stamp}`)
check('the three-way match puts order, receipt and bill side by side', /1,000/.test(await matchRow()) && /500/.test(await matchRow()), await matchRow())
await done()
