import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { api, clickText, fill, launch, open, setValue, signIn, sleep, text, toastsGone } from './lib.mjs'

// The item master: an item made with its make, materials and work items apart, the details still missing found and
// filled in for several items at once, an unused item turned into a material, and the old ERP's item list imported.
const { page, check, done } = await launch()
await signIn(page)
// The list remembers the last filters used; each part of this starts from none.
const forget = () => page.evaluate(() => { try { Object.keys(localStorage).filter((k) => k.startsWith('yerp.items.filters')).forEach((k) => localStorage.removeItem(k)) } catch { /* private window */ } })
await forget()
const stamp = Date.now().toString().slice(-6)
const gone = () => page.waitForFunction(() => !document.querySelector('[role=dialog], [role=alertdialog]'), { timeout: 10000 })
const last = (label) => page.evaluate((label) => [...[...document.querySelectorAll('[role=dialog]')].pop().querySelectorAll('button')].find((b) => b.textContent.trim().startsWith(label)).click(), label)
const search = async (q) => {
  await fill(page, 'input[aria-label="Search items"]', q)
  await sleep(900)
}
const rows = () => page.$$eval('table[aria-label=Items] tbody tr', (r) => r.map((x) => x.textContent.replace(/\s+/g, ' ')))

await open(page, '/store/items')
await page.waitForSelector('table[aria-label=Items] tbody tr')

// A new material with its make
await clickText(page, 'main button', 'New item')
await page.waitForSelector('#im-name')
await page.evaluate(() => [...document.querySelectorAll('[role=radio]')].find((b) => b.textContent.startsWith('Material')).click())
await fill(page, '#im-name', `QA Binding wire ${stamp}`)
await fill(page, '#im-uom', 'Kgs')
await fill(page, '#im-make', 'Tata Wiron')
await last('Save item')
await gone()
await toastsGone(page)
await search(`Tata Wiron`)
const found = await rows()
check('a new material is listed with its make, and is found by it', found.some((r) => r.includes(`QA Binding wire ${stamp}`) && r.includes('Tata Wiron') && r.includes('Material')), found.join(' | ').slice(0, 200))

// Materials and work items apart
await search('')
await clickText(page, 'main [role=tab]', 'Work items')
await sleep(900)
const work = await rows()
check('the Work items tab shows only work items', work.length > 0 && work.every((r) => r.includes('Work item')), `${work.length} rows`)
await clickText(page, 'main [role=tab]', 'Materials')
await sleep(900)
const mats = await rows()
check('the Materials tab shows only materials', mats.length > 0 && mats.every((r) => r.includes('Material')), `${mats.length} rows`)
await clickText(page, 'main [role=tab]', 'All items')
await sleep(600)

// Two items with gaps, filled in together
const sand = (await api(page, 'POST', '/api/items', { item_name: `QA Sand ${stamp}`, kind: 'FG', units_of_measure: 'cum' })).data.item
const agg = (await api(page, 'POST', '/api/items', { item_name: `QA Aggregate ${stamp}`, kind: 'RM', units_of_measure: 'cum' })).data.item
await forget()
await open(page, '/store/items')
await page.waitForSelector('section[aria-label="Details still missing"]')
await clickText(page, 'section[aria-label="Details still missing"] button', 'No HSN / SAC code')
await sleep(900)
check('a gap picked becomes a filter', (await text(page, 'main')).includes('Showing the items with no HSN / SAC code') && !!(await page.$('button[aria-label="Remove filter No HSN / SAC code"]')))
await search(stamp)
await page.click('input[aria-label="Select all items on this page"]')
await clickText(page, 'main button', 'Edit selected')
await page.waitForSelector('#be-gst')
await setValue(page, '#be-gst', '5')
await fill(page, '#be-hsn', '2505')
await last('Save changes')
await gone()
await sleep(600)
const after = await Promise.all([sand, agg].map(async (i) => (await api(page, 'GET', `/api/items/${i.id}`)).data.item))
check('the ticked items get the GST and HSN together, and nothing else moves', after.every((i) => i.item_tax_type === '5%' && i.hsn_code === '2505') && after[0].kind === 'FG')
await toastsGone(page)

// An unused item put right as a material
await forget()
await open(page, '/store/items')
await search(`QA Sand ${stamp}`)
await page.click(`button[aria-label="Edit QA Sand ${stamp}"]`)
await page.waitForSelector('#im-name')
await page.evaluate(() => [...document.querySelectorAll('[role=radio]')].find((b) => b.textContent.startsWith('Material')).click())
await last('Save changes')
await gone()
check('an item nothing uses yet can be turned into a material', (await api(page, 'GET', `/api/items/${sand.id}`)).data.item.kind === 'RM')
await toastsGone(page)

// The old ERP's own item list, prompt row and all
const csv = [
  'Item Code,Item Name,Segment,Description,Category,Sub Category,HSN Code,Item Tax Type,Item Type,Units Of Measure,Make',
  ',,,,Please Select Option From Dropdown,Please Select Option From Dropdown,,Please Select Option From Dropdown,Please Select Option From Dropdown,Please Select Option From Dropdown,',
  `QA${stamp}A,QA Copper earth wire ${stamp},YPPL,QA Copper earth wire,RAW MATERIAL,RM,7408,0.18,Purchased,kilograms,Polycab`,
  `QA${stamp}B,QA Site watchman ${stamp},YPPL,QA Site watchman,RAW MATERIAL,RM,998525,0.18,Service,Lump Sum per Month,Make List`,
].join('\n')
const file = path.join(os.tmpdir(), `old_erp_items_${stamp}.csv`)
fs.writeFileSync(file, csv)
await clickText(page, 'main button', 'Import from Excel')
await page.waitForSelector('#ii-file')
await (await page.$('#ii-file')).uploadFile(file)
await last('Read my file')
await page.waitForSelector('table[aria-label="Rows read from your file"]', { timeout: 20000 })
const read = await text(page, '[role=dialog]')
check('the old ERP sheet reads with no errors: both lines new, the prompt row left out', /All 2\s*New 2/.test(read) && /Error 0/.test(read), read.slice(0, 200))
await page.evaluate(() => [...[...document.querySelectorAll('[role=dialog]')].pop().querySelectorAll('button')].find((b) => /^(Import|Save|Add)/.test(b.textContent.trim()) && !b.disabled).click())
await sleep(1500)
const wire = (await api(page, 'GET', `/api/items?q=QA${stamp}A`)).data.items[0]
check('an imported item is a material with its GST, make and segment', !!wire && wire.kind === 'RM' && wire.item_tax_type === '18%' && wire.make === 'Polycab' && wire.segment === 'YPPL' && wire.units_of_measure === 'Kgs', JSON.stringify(wire ?? {}).slice(0, 200))
const watch = (await api(page, 'GET', `/api/items?q=QA${stamp}B`)).data.items[0]
check('a prompt left in a cell is read as nothing chosen', !!watch && watch.make === '' && watch.units_of_measure === 'Months')
fs.unlinkSync(file)
await done()
