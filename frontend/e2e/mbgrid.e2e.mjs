import { copyFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { api, approvedOrder, fill, launch, open, signIn, sleep } from './lib.mjs'

// Demo Bill-1, the real workbook: Select all loads both blocks into the grid with the sheet's 10% hold under each;
// recording keeps the measurement as the sheet wrote it and the hold as a hold.
const { page, check, done } = await launch({ allow: [/^4/] })
await signIn(page)
const xlsx = join(tmpdir(), 'demo_bill_1.xlsx')
copyFileSync(join(import.meta.dirname, '..', '..', 'backend', 'tests', 'data', 'demo_bill_1.xlsx'), xlsx)
const o = await approvedOrder(page, { subject: 'Demo Bill 1', lines: [{ activity_no: '1.0', item_description: 'Internal Hole Packing', uom: 'Sqm', quantity: 20000, unit_rate: 100 }] })
await open(page, `/subcontractors/measurement-book?order=${o.id}`)
await page.waitForSelector('table[aria-label="Items on the order"] tbody tr')
await page.evaluate(() => document.querySelector('table[aria-label="Items on the order"] tbody tr td:last-child button:last-child').click())
await page.waitForSelector('input[aria-label="Excel file to read the lines from"]')
await (await page.$('input[aria-label="Excel file to read the lines from"]')).uploadFile(xlsx)
await page.waitForSelector('input[aria-label="Select every entry"]', { timeout: 20000 })
const dlg = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the sheet says what is wrong with itself (row 224)', /Row 224/.test(await dlg()))
await page.click('input[aria-label="Select every entry"]')
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => /into the grid/.test(b.textContent)).click())
await page.waitForSelector('[aria-label="Blocks loaded from the sheet"]')
check('both blocks are in the grid', (await page.$$('[aria-label="Blocks loaded from the sheet"] section[aria-label^="Block"]')).length === 2)
const holds = await page.$$eval('[aria-label="What the sheet holds back"]', (h) => h.map((x) => x.textContent.replace(/\s+/g, ' ')))
const reasons = await page.$$eval('[aria-label="What the sheet holds back"] input[id^="sb-why-"]', (i) => i.map((x) => x.value))
check('each block has the sheet hold under it, in its own words', holds.length === 2 && reasons.length === 2 && reasons.every((t) => /hsnding over/.test(t)), reasons.join(' || '))
check('365 block: 7,059.4 before holding back, 705.94 held, 6,353.46 to be paid', /7,059\.4/.test(holds[0]) && /705\.94/.test(holds[0]) && /6,353\.46/.test(holds[0]), holds[0])
const summary = await page.$eval('[aria-label="What will be recorded"]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the window adds it up: measured 15,839.528, to be paid 14,255.575', /15,839\.528/.test(summary) && /14,255\.57/.test(summary), summary)
check('nothing is in the book yet', (await api(page, 'GET', `/api/sub-mb/${o.id}`)).data.entries.length === 0)
// change a figure in the grid: the hold follows
const pct = await page.$eval('[aria-label="Blocks loaded from the sheet"] input[id^="sb-pct-"]', (e) => '#' + e.id)
await fill(page, pct, '20')
await sleep(300)
const changed = await page.$$eval('[aria-label="What the sheet holds back"]', (h) => h[0].textContent.replace(/\s+/g, ' '))
check('changing the hold percent works the held quantity out again (20% of 7,059.4 = 1,411.88)', /1,411\.88/.test(changed), changed)
await fill(page, pct, '10')
await sleep(300)
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => /^Record 2 blocks/.test(b.textContent.trim())).click())
await page.waitForFunction(() => !document.querySelector('[role=dialog]'), { timeout: 20000 })
await sleep(800)
const line = (await api(page, 'GET', `/api/sub-mb/${o.id}`)).data.lines[0]
check('the book holds what the sheet measured and holds what it holds', Math.abs(line.measured_to_date - 15839.53) < 0.02 && Math.abs(line.held - 1583.95) < 0.02 && Math.abs(line.unbilled - 14255.58) < 0.02, JSON.stringify([line.measured_to_date, line.held, line.unbilled]))
await done()
