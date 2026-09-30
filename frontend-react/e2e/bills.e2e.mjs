import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { clickText, fill, launch, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Money > Supplier Bills: a bill is a draft until it is accepted; accepted, it can be paid; a workbook can bring in many.
const { page, check, done } = await launch()
await signIn(page)
await open(page, '/money/supplier-bills')
await page.waitForSelector('table[aria-label="Supplier bills"]')
const stamp = Date.now().toString().slice(-6)
const vendor = `QA Vendor ${stamp}`
const rows = () => page.$$eval('table[aria-label="Supplier bills"] tbody tr', (r) => r.map((e) => e.textContent.replace(/\s+/g, ' ')))
const dialog = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
const search = async (q) => { await fill(page, 'input[aria-label=Search]', q); await sleep(400) }

check('the list loads the bills', (await rows()).length >= 1, `${(await rows()).length} bills`)
await clickText(page, 'button', 'New bill')
await page.waitForSelector('#bf-vendor')
await page.waitForFunction(() => document.querySelector('#bf-number')?.value.startsWith('BILL-'), { timeout: 8000 })
check('a new bill is given the next number', true)
await fill(page, '#bf-vendor', vendor)
await fill(page, '#bf-amount', '10000')
await page.select('#bf-rate', '18')
await sleep(200)
check('choosing a tax rate works out the tax and the total (10,000 + 18% = 11,800)', (await page.$eval('#bf-tax', (e) => e.value)) === '1800' && (await page.$eval('#bf-total', (e) => e.value)).includes('11,800'))
await clickText(page, 'button', 'Save bill')
await waitForToast(page, 'created')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await toastsGone(page)
await search(vendor)
check('it is listed as a draft', (await rows()).length === 1 && (await rows())[0].includes('Draft') && (await rows())[0].includes('11,800'), (await rows())[0])

await clickText(page, 'table[aria-label="Supplier bills"] button', 'Accept')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Accept')
await waitForToast(page, 'accepted')
await toastsGone(page)
await sleep(500)
check('once accepted it shows as owed and offers Pay', (await rows())[0].includes('Awaiting Payment') && (await rows())[0].includes('Pay'), (await rows())[0])

await clickText(page, 'table[aria-label="Supplier bills"] button', 'Pay')
await page.waitForSelector('[role=dialog]')
await page.waitForFunction(() => document.querySelector('[role=dialog]')?.textContent.includes('left'), { timeout: 8000 })
check('the payment opens with what the bill is worth and what is left', (await dialog()).includes('11,800'))
await page.keyboard.press('Escape')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))

// From a workbook
const bytes = await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/api/sheets/bills/template.xlsx', { credentials: 'include' })).arrayBuffer())))
const sheet = join(tmpdir(), 'e2e-bills.xlsx')
writeFileSync(sheet, Buffer.from(bytes))
await search('')
await clickText(page, 'button', 'From Excel')
await page.waitForSelector('input[aria-label="Workbook to read"]')
await (await page.$('input[aria-label="Workbook to read"]')).uploadFile(sheet)
await page.waitForSelector('[role=dialog] [role=grid]', { timeout: 10000 })
await sleep(800)
check('a workbook is read into rows to check before anything is saved', (await dialog()).includes('row') && /Every row reads cleanly|needs? a look|need a look/.test(await dialog()), (await dialog()).slice(-240))
const before = (await rows()).length
await clickText(page, '[role=dialog] button', 'Bring these in as drafts')
await waitForToast(page, 'brought in')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(800)
check('they arrive as drafts', (await rows()).length > before, `${before} -> ${(await rows()).length}`)
await toastsGone(page)

// Delete the bill made above
await search(vendor)
await page.evaluate(() => [...document.querySelectorAll('table[aria-label="Supplier bills"] button')].find((b) => b.textContent === 'Delete').click())
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Delete it')
await waitForToast(page, 'deleted')
await sleep(600)
check('a bill can be deleted after a confirmation', (await rows()).every((r) => !r.includes(vendor)) || (await page.$eval('main', (e) => e.textContent.includes('No bills found'))))

await done()
