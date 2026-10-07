import { attachHardCopy, api, approvedOrder, clickText, launch, measure, open, signIn, sleep } from './lib.mjs'

// Every measurement entry has a code, and a bill can be drawn for chosen entries only.
const { page, check, done } = await launch({ allow: [/^(403|404|409) /] })
await signIn(page)
const order = await approvedOrder(page, { subject: `Chosen ${Date.now().toString().slice(-6)}` })
const item = order.items[0].item_id
await measure(page, order.id, item, 3)
await measure(page, order.id, item, 5)
await measure(page, order.id, item, 7)
const entries = (await api(page, 'GET', `/api/sub-mb/${order.id}`)).data.entries.sort((a, b) => a.id - b.id)
check('every entry has a code, in order', entries.every((e, i) => e.code.endsWith(`MB-00${i + 1}`)), entries.map((e) => e.code).join(' '))

// --- the measurement book shows the codes, and a ticked entry is billed on its own ------------------------------------
await open(page, `/subcontractors/measurement-book?order=${order.id}`)
await page.waitForSelector('table[aria-label="Measurement entries"] tbody tr')
const view = await page.$$eval('button', (b) => b.map((x) => x.textContent.trim()))
if (view.includes('List')) await clickText(page, 'button', 'List')
await page.waitForSelector('table[aria-label="Measurement entries"] tbody tr')
const shown = await page.$eval('table[aria-label="Measurement entries"]', (t) => t.textContent)
check('the entry codes are on the screen', /MB-001/.test(shown) && /MB-003/.test(shown))
const boxes = await page.$$('table[aria-label="Measurement entries"] tbody input[aria-label="Select this row"]')
await boxes[boxes.length - 1].click() // the oldest row: the list shows the newest first
await sleep(200)
await clickText(page, '[aria-label="Selected rows"] button', 'Bill 1')
await page.waitForFunction(() => /RA-\d+$/.test(document.querySelector('main h1')?.textContent.trim() ?? ''), { timeout: 20000 })
const text = await page.$eval('main', (m) => m.textContent.replace(/\s+/g, ' '))
check('a bill is drawn for the ticked entry alone', /Measurement entries on this bill/.test(text) && /MB-001/.test(text) && !/MB-002/.test(text), text.slice(0, 200))
const bill = Number(page.url().match(/ra-bills\/(\d+)/)[1])
const got = (await api(page, 'GET', `/api/sub-bills/${bill}`)).data
check('and it claims only that entry', got.lines.length === 1 && got.lines[0].this_bill_qty === 3 && got.entry_mode === 'chosen', JSON.stringify(got.lines.map((l) => l.this_bill_qty)))

// --- the dialog on the RA bills screen: choose entries again, once the first bill is done ------------------------------
await attachHardCopy(page, bill)
await api(page, 'POST', `/api/sub-bills/${bill}/submit`, {})
await api(page, 'POST', `/api/sub-bills/${bill}/certify`, {})
await open(page, `/subcontractors/ra-bills?order=${order.id}`)
await page.waitForSelector('table[aria-label="RA bills"]')
await clickText(page, 'main button', 'Draw up a bill')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] label', 'Only the entries I choose')
await page.waitForSelector('table[aria-label="Entries not yet billed"] tbody tr')
const left = await page.$$eval('table[aria-label="Entries not yet billed"] tbody tr', (r) => r.length)
check('the dialog lists only what is not yet billed', left === 2, String(left))
await page.click('input[aria-label="Bill ' + entries[2].code + '"]')
await clickText(page, '[role=dialog] button', 'Draw up a bill for 1 entry')
await page.waitForFunction(() => /RA-\d+$/.test(document.querySelector('main h1')?.textContent.trim() ?? ''), { timeout: 20000 })
const second = Number(page.url().match(/ra-bills\/(\d+)/)[1])
const g2 = (await api(page, 'GET', `/api/sub-bills/${second}`)).data
check('the second bill takes the third entry and leaves the second', g2.lines[0].this_bill_qty === 7 && g2.entries.length === 1 && g2.entries[0].code === entries[2].code, JSON.stringify(g2.entries))
const book = (await api(page, 'GET', `/api/sub-mb/${order.id}`)).data.entries
check('the entry not chosen is still free to bill', book.find((e) => e.id === entries[1].id).billed === false)
await done()
