import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { api, approvedOrder, clickText, launch, open, signIn, sleep } from './lib.mjs'

// The Measurement Book reads like the Excel sheet it was imported from: sections, lettered blocks, their lines,
// the hold-back subtotal and what is to be paid.
const { page, check, done } = await launch({ allow: [/^4/] })
await signIn(page)
const xlsx = join(tmpdir(), 'mb_held.xlsx')
const py = "import sys; sys.path.insert(0, 'tests'); sys.path.insert(0, '.'); from test_sub_contractor_certificate import held_back_workbook; open(sys.argv[1], 'wb').write(held_back_workbook())"
execFileSync('python', ['-c', py, xlsx], { cwd: join(import.meta.dirname, '..', '..', 'backend') })
const o = await approvedOrder(page, { subject: 'sheet view', lines: [{ activity_no: '1.0', item_code: 'TL001', item_description: 'Tile laying and painting', uom: 'sqm', quantity: 100000, unit_rate: 8, tolerance_percent: 10 }] })

// Import the whole workbook onto the one item, as it is done in the app
await open(page, `/subcontractors/measurement-book?order=${o.id}`)
await clickText(page, 'main button', 'Import MB from Excel')
await page.waitForSelector('#ib-file')
await (await page.$('#ib-file')).uploadFile(xlsx)
await page.waitForSelector('select[aria-label="Send every section with no item to"]', { timeout: 15000 })
const first = await page.$eval('select[aria-label="Send every section with no item to"]', (s) => s.options[1].value)
await page.select('select[aria-label="Send every section with no item to"]', first)
await sleep(500)
await clickText(page, '[role=dialog] button', 'Record it in the book')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'), { timeout: 15000 })
await sleep(1200)
check('the import recorded the sheet', (await api(page, 'GET', `/api/sub-mb/${o.id}`)).data.entries.length >= 3)

await open(page, `/subcontractors/measurement-book?order=${o.id}`)
await clickText(page, '[role=tab]', 'Measurement sheet')
await page.waitForSelector('[aria-label="Measurement sheet"]')
const t = await page.$eval('[aria-label="Measurement sheet"]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the sections are shown with their headings', /I\s*Laying of tiles/.test(t) && /II\s*Internal Painting Work/.test(t), t.slice(0, 160))
check('each block is shown under its letter and place', /A\s*365 sft - Block No\. B24/.test(t) && /B\s*365 sft - Block No\. B12/.test(t))
check('with its lines and the block total', t.includes('Living Room') && t.includes('Total quantity for one block'))
check('a block built several times says so', /Total quantity for 4 blocks/.test(t))
check('the hold-back is shown, and what is left to pay', t.includes('Held back for finishes and handing over') && t.includes('Total quantity to be paid') && /before holding back/.test(t))
check('the group comes to what the sheet says (190)', /to be paid\s*190/.test(t), (t.match(/to be paid.{0,14}/g) || []).join(' | '))
check('and the grand total is what is payable (370)', /after [\d.,]+ held back\)\s*370/.test(t), t.slice(-140))
await clickText(page, '[role=tab]', 'Entries')
await page.waitForSelector('table[aria-label="Measurement entries"] tbody tr')
check('the flat list is one tab away and shows the same entries', (await page.$$('table[aria-label="Measurement entries"] tbody tr')).length >= 3)
await done()
