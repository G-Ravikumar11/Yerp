import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { api, cellText, clickCell, clickText, fill, gridRowCount, launch, open, signIn, sleep, waitForToast } from './lib.mjs'

const { page, check, done } = await launch()
await signIn(page)
await open(page, '/store/items')

const rowCount = () => page.$$eval('table[aria-label=Items] tbody tr', (r) => r.length)
const search = async (q) => {
  await fill(page, 'input[aria-label="Search items"]', q)
  await sleep(700)
}

// --- The list -----------------------------------------------------------------
await page.waitForSelector('table[aria-label=Items] tbody tr')
const before = await rowCount()
check('the item list loads from the real backend', before > 0, `${before} rows`)

const first = await page.$eval('table[aria-label=Items] tbody tr td', (e) => e.textContent.trim())
await search(first)
check('searching by a code narrows to that item', (await rowCount()) >= 1 && (await page.$eval('table[aria-label=Items] tbody tr td', (e) => e.textContent.trim())) === first, first)
await search('zzzzqqqq')
check('a search with no match says so', (await page.$eval('main', (e) => e.textContent)).includes('Nothing matches'))
await search('')

await clickText(page, 'button[role=tab]', 'Finished goods')
await sleep(500)
const kinds = await page.$$eval('table[aria-label=Items] tbody tr', (rows) => rows.map((r) => r.textContent.includes('Finished good')))
const noFg = (await page.$eval('main', (e) => e.textContent)).includes('No items yet')
check('the Finished goods tab shows only finished goods', noFg || (kinds.length > 0 && kinds.every(Boolean)), `${kinds.length} rows`)
await clickText(page, 'button[role=tab]', 'All')
await sleep(400)

// --- Adding several at once in the grid -----------------------------------------
await clickText(page, 'button', 'Add items')
await page.waitForSelector('[role=dialog] [role=grid]')
await clickCell(page, 0, 0, 2, '[role=dialog]')
await page.keyboard.type('E2E Steel bar 12mm')
await page.keyboard.press('Enter')
await page.keyboard.type('E2E River sand')
await page.keyboard.press('Enter')
check('two rows typed into the grid', (await cellText(page, 0, 0, 2, '[role=dialog]')) === 'E2E Steel bar 12mm' && (await cellText(page, 0, 1, 2, '[role=dialog]')) === 'E2E River sand')
await clickText(page, '[role=dialog] button', 'Save 2 items')
await waitForToast(page, 'code(s) added')
check('saving reports the codes issued', true)
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await search('E2E')
check('both new items are in the list, with codes issued', (await rowCount()) === 2)

// --- Editing ----------------------------------------------------------------------
await page.click('table[aria-label=Items] tbody tr')
await page.waitForSelector('[role=dialog] input#ei-name')
await fill(page, '#ei-name', 'E2E Steel bar 16mm')
await clickText(page, '[role=dialog] button', 'Save')
await waitForToast(page, 'updated')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(400)
const names = await page.$$eval('table[aria-label=Items] tbody tr', (r) => r.map((x) => x.textContent))
check('an edit shows in the list', names.some((n) => n.includes('16mm')))

// --- Deleting ------------------------------------------------------------------------
await page.click('table[aria-label=Items] tbody tr button[aria-label^="Remove"]')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Remove')
await waitForToast(page, 'removed')
await sleep(500)
check('a removed item leaves the list', (await rowCount()) === 1)

// --- Import from any workbook --------------------------------------------------------
const csv = join(tmpdir(), 'e2e-items.csv')
writeFileSync(csv, 'Material Code,Description,UOM,HSN,GST\n,E2E Cement OPC 53,Bags,2523,28%\n,E2E Aggregate 20mm,cum,2517,5%\n')
await search('')
await clickText(page, 'button', 'Import from Excel')
await page.waitForSelector('#ii-file')
await (await page.$('#ii-file')).uploadFile(csv)
await page.select('#ii-kind', 'RM')
await clickText(page, '[role=dialog] button', 'Read the workbook')
await page.waitForSelector('[role=dialog] [role=grid]', { timeout: 10000 }).catch(() => {})
const reviewing = await page.$('[role=dialog] [role=grid]')
if (reviewing) {
  check('a workbook in someone else\'s columns is read and mapped', (await gridRowCount(page, 0, '[role=dialog]')) >= 2, `${await gridRowCount(page, 0, '[role=dialog]')} rows`)
  await clickText(page, '[role=dialog] button', 'Save 2 items')
  await sleep(1500)
  const toast = await page.evaluate(() => document.querySelector('[aria-live=polite]')?.textContent ?? '')
  check('the import saves them', /saved|added/i.test(toast), toast.slice(0, 80))
} else {
  const msg = await page.evaluate(() => document.querySelector('[aria-live=polite]')?.textContent ?? '')
  check('a workbook in someone else\'s columns is read and mapped', false, msg.slice(0, 120))
}
await page.keyboard.press('Escape')
await sleep(400)
await search('E2E')
check('imported items are in the master', (await rowCount()) >= 2, `${await rowCount()} rows`)

// tidy: remove what this run made
const list = await api(page, 'GET', '/api/erp/items?q=E2E')
for (const it of list.data.items) await api(page, 'DELETE', `/api/erp/items/${it.id}`)

await done()
