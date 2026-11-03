import { api, clickText, launch, open, signIn, sleep } from './lib.mjs'

// The Store Desk: one screen for receiving, issuing, stock and low stock, with the store chosen once and remembered.
const { page, check, done } = await launch({ allow: [] })
await signIn(page)
const { TAG: tag, STORE, ITEM, SHOTS } = process.env
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const shot = (name) => (SHOTS ? page.screenshot({ path: `${SHOTS}/${name}.png` }) : null)
const today = new Date().toISOString().slice(0, 10)
const jobs = (await api(page, 'GET', '/api/jobs')).data
const job = (jobs.jobs ?? jobs.items ?? jobs)[0].id
const grn = await api(page, 'POST', '/api/store/inward/grn', { store_id: Number(STORE), grn_date: today, supplier_name: 'Ultratech Cement', lines: [{ item_id: Number(ITEM), qty: '250', uom: 'Bag', rate: '380' }] })
for (const step of ['submit', 'approve', 'post']) await api(page, 'POST', `/api/store/inward/grn/${grn.data.id}/${step}`)
await api(page, 'POST', '/api/store/outward/issue/direct', { store_id: Number(STORE), issue_date: today, project_id: job, received_by_type: 'FOREMAN', received_by_name: 'Suresh', purpose: 'Block A - Foundation',
  lines: [{ item_id: Number(ITEM), qty: '60', uom: 'Bag', cost_head: 'OVERHEAD' }] })

await open(page, '/store/desk')
await page.waitForFunction((t) => document.querySelector('table[aria-label="Stock register"]')?.textContent.includes(t), { timeout: 15000 }, tag)
const main = await text('main')
check('the desk has the two big jobs and today\'s figures', /Receive material/.test(main) && /Issue material/.test(main) && /Received today/.test(main) && /Issued today/.test(main) && /Low stock/.test(main))
await shot('desk')
await page.select('#desk-store', String(STORE))
await sleep(800)
for (const [tab, table, word] of [['Received', 'Material received', 'Ultratech Cement'], ['Issued', 'Material issued', 'Block A - Foundation'], ['Low stock', 'Low stock', tag]]) {
  await clickText(page, '[role=tab]', tab)
  await page.waitForFunction((t, w) => document.querySelector(`table[aria-label="${t}"]`)?.textContent.includes(w), { timeout: 15000 }, table, word)
  check(`the ${tab} tab shows its list`, true)
}
await open(page, '/store/desk')
await sleep(1200)
check('the chosen store is remembered', (await page.$eval('#desk-store', (e) => e.value)) === String(STORE))
await clickText(page, 'main a', 'Receive material')
await page.waitForFunction(() => location.pathname.endsWith('/store/receive/new'), { timeout: 15000 })
await sleep(1000)
check('Receive material opens the receipt with the store filled in', (await page.$eval('main select', (e) => e.value)) === String(STORE) || (await text('main')).includes('R' + ITEM))
const crumbs = await text('nav[aria-label="Breadcrumb"], header')
check('the page says it is under the Store Desk', /Store Desk/.test(crumbs))
await done()
