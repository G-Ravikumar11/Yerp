import { api, approvedOrder, fill, launch, open, setValue, signIn, sleep } from './lib.mjs'

// The same search, status and date filters as Work Orders, on the Measurement Book, Vendor Register and the other lists;
// and the item code beside every item in the book.
const { page, check, done } = await launch()
await signIn(page)
const o = await approvedOrder(page, { subject: 'filters' })
await api(page, 'POST', `/api/sub-mb/${o.id}/entries`, { item_id: o.items[0].item_id, quantity: 10, measured_on: '2026-11-15' })
const text = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' '))

await open(page, `/subcontractors/measurement-book?order=${o.id}`)
await page.waitForSelector('table[aria-label="Items on the order"] tbody tr')
check('the book lists an Item code column', (await page.$$eval('table[aria-label="Items on the order"] th', (h) => h.map((x) => x.textContent))).includes('Item code'))
const rowsBefore = await page.$$eval('table[aria-label="Items on the order"] tbody tr', (r) => r.length)
const searches = await page.$$('input[aria-label=Search]')
check('the items have their own search, and the entries have theirs', searches.length >= 2, String(searches.length))
await searches[0].type('Reinforcement')
await sleep(300)
const rowsAfter = await page.$$eval('table[aria-label="Items on the order"] tbody tr', (r) => r.length)
check('searching narrows the items', rowsAfter > 0 && rowsAfter < rowsBefore, `${rowsBefore} -> ${rowsAfter}`)
const statuses = await page.$$eval('select[aria-label=Status] option', (o) => o.map((x) => x.textContent))
check('and the items filter by how far the work has got', statuses.some((x) => /Not started|In progress|Complete/.test(x)), statuses.join(', '))

await open(page, '/subcontractors/vendors')
await page.waitForSelector('table[aria-label=Vendors] tbody tr')
check('the Vendor Register has the filter bar: search, status and dates', (await page.$('input[aria-label=Search]')) !== null && (await page.$('select[aria-label=Status]')) !== null && (await page.$('input[aria-label="From date"]')) !== null)
const n = await page.$$eval('table[aria-label=Vendors] tbody tr', (r) => r.length)
await fill(page, 'input[aria-label=Search]', 'zzzz-no-such-gang')
await sleep(300)
check('and searching it narrows the list', (await text()).includes('Nobody matches') || (await page.$$eval('table[aria-label=Vendors] tbody tr', (r) => r.length)) < n)

for (const [path, label] of [['/store/goods-receipt', 'Goods receipts'], ['/store/enquiries', 'Enquiries'], ['/store/eway', 'E-way bills'], ['/projects/equipment', 'Machines']]) {
  await open(page, path)
  await sleep(800)
  check(`${label}: the filter bar is there`, (await page.$('input[aria-label=Search]')) !== null, path)
}
await done()
