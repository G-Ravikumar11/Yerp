import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { approvedOrder, clickText, launch, open, signIn, sleep, waitForToast } from './lib.mjs'

// A workbook with many blocks that match no item by name: tick them all and record them against one item.
const { page, check, done } = await launch({ allow: [/^4/] })
await signIn(page)
// The same workbook the backend tests use: two numbered sections, one of them four blocks alike.
const xlsx = join(tmpdir(), 'mb_many.xlsx')
execFileSync('python', ['-c', "import sys; sys.path.insert(0, 'tests'); sys.path.insert(0, '.'); from test_sub_contractor_certificate import mb_workbook; open(sys.argv[1], 'wb').write(mb_workbook())", xlsx], { cwd: join(import.meta.dirname, '..', '..', 'backend') })
const lines = [
  { activity_no: '1.0', item_code: 'TL001', item_description: 'Laying of tiles with sand cement', uom: 'sqm', quantity: 100000, unit_rate: 410, tolerance_percent: 10 },
  { activity_no: '2.0', item_code: 'TL002', item_description: 'Skirting', uom: 'rmt', quantity: 100000, unit_rate: 80 },
]

// --- One item: tick every entry, record them together ---
const o = await approvedOrder(page, { subject: 'record all', lines })
await open(page, `/subcontractors/measurement-book?order=${o.id}`)
await page.waitForSelector('table[aria-label="Items on the order"] tbody tr')
await page.evaluate(() => document.querySelector('table[aria-label="Items on the order"] tbody tr td:last-child button:last-child').click())
await page.waitForSelector('input[aria-label="Excel file to read the lines from"]')
await (await page.$('input[aria-label="Excel file to read the lines from"]')).uploadFile(xlsx)
await page.waitForSelector('input[aria-label="Select every entry"]', { timeout: 15000 })
const dlg = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the sheet\'s entries are listed with a tick box each', (await page.$$('[role=dialog] input[type=checkbox][aria-label^="Tick"]')).length >= 2)
const btn = () => page.$eval('[role=dialog]', (d) => [...d.querySelectorAll('button')].find((b) => /into the grid/.test(b.textContent)).disabled)
check('nothing is loaded until something is ticked', await btn())
await page.click('input[aria-label="Select every entry"]')
check('Select all ticks every entry', !(await btn()) && /Select all [0-9]+ new entries/.test(await dlg()), (await dlg()).slice(0, 200))
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => /into the grid/.test(b.textContent)).click())
await page.waitForSelector('[aria-label="Blocks loaded from the sheet"]')
const blocks = await page.$$eval('[aria-label="Blocks loaded from the sheet"] section[aria-label^="Block"]', (s) => s.length)
check('Select all loads every block into the grid, nothing recorded yet', blocks >= 2 && (await page.evaluate(() => document.querySelector('main').textContent)).includes('Nothing measured yet'), String(blocks))
const firstGrid = await page.$eval('[aria-label="Blocks loaded from the sheet"] [role=grid]', (g) => g.textContent)
check('each block shows its lines in the grid columns', /[0-9]/.test(firstGrid) && firstGrid.length > 20, firstGrid.slice(0, 120))
const record = () => page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => /^Record [0-9]+ blocks?/.test(b.textContent.trim())))
const mixed = await page.$('input[aria-label="They are all this item"]')
if (mixed) {
  check('blocks from different works must be confirmed as this one item', await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => /^Record [0-9]+ blocks?/.test(b.textContent.trim())).disabled))
  await mixed.click()
}
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => /^Record [0-9]+ blocks?/.test(b.textContent.trim())).click())
await page.waitForFunction(() => !document.querySelector('[role=dialog]') || document.querySelector('[role=dialog] [role=alert]'), { timeout: 15000 })
const err = await page.evaluate(() => document.querySelector('[role=dialog] [role=alert]')?.textContent)
if (err) console.log('DIALOG ALERT', err)
await sleep(800)
const rows = await page.$$eval('table[aria-label="Measurement entries"] tbody tr', (r) => r.length)
check('every loaded block is now an entry in the book', rows >= 2, String(rows))
void record

// --- The whole book: send every section with no item to one item ---
const o2 = await approvedOrder(page, { subject: 'send all', lines })
await open(page, `/subcontractors/measurement-book?order=${o2.id}`)
await clickText(page, 'main button', 'Import MB from Excel')
await page.waitForSelector('#ib-file')
await (await page.$('#ib-file')).uploadFile(xlsx)
await page.waitForSelector('select[aria-label="Send every section with no item to"]', { timeout: 15000 })
const first = await page.$eval('select[aria-label="Send every section with no item to"]', (s) => s.options[1].value)
await page.select('select[aria-label="Send every section with no item to"]', first)
await sleep(300)
check('one choice gives every section an item', !(await dlg()).includes('need an item'), (await dlg()).slice(0, 160))
if (/different works are set to/.test(await dlg())) {
  check('different works sent to one item are named, and recording waits for a yes', await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => /Record it in the book/.test(b.textContent)).disabled))
  await page.click('[role=dialog] [role=alert] input[type=checkbox]')
}
check('the window shows what each section will be billed at', /Amount/.test(await dlg()) && /To be paid/.test(await dlg()))
await clickText(page, '[role=dialog] button', 'Record it in the book')
await waitForToast(page, 'recorded')
await sleep(800)
check('and records them all', (await page.$$eval('table[aria-label="Measurement entries"] tbody tr', (r) => r.length)) >= 2)
await done()
