import { api, clickText, launch, open, signIn, sleep } from './lib.mjs'

// The four store registers through the screens: stock, receive, issue and low stock, from a receipt and an issue posted here.
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
const issue = await api(page, 'POST', '/api/store/outward/issue/direct', { store_id: Number(STORE), issue_date: today, project_id: job, received_by_type: 'FOREMAN', received_by_name: 'Suresh', purpose: 'Block A - Foundation',
  lines: [{ item_id: Number(ITEM), qty: '60', uom: 'Bag', cost_head: 'OVERHEAD' }] })
check('a receipt and an issue are posted', grn.status === 200 && issue.status === 200)

await open(page, '/store/stock-register')
await page.waitForFunction((t) => document.querySelector('table[aria-label="Stock register"]')?.textContent.includes(t), { timeout: 15000 }, tag)
await sleep(600)
const reg = await text('main')
check('the stock register shows the item, its level and where it is', reg.includes(`OPC Cement 53 Grade ${tag}`) && reg.includes('Main Store') && reg.includes('190') && /Total items/.test(reg) && /Low stock count/.test(reg))
await shot('stock-register')
await clickText(page, 'main button', 'Low stock count')
await sleep(500)
check('the low stock tile narrows the list', (await text('table[aria-label="Stock register"]')).includes(tag))

await open(page, '/store/receive')
await page.waitForFunction((n) => document.querySelector('table[aria-label="Material received"]')?.textContent.includes(n), { timeout: 15000 }, grn.data.number)
const rec = await text('table[aria-label="Material received"]')
check('the receive register shows the receipt line', rec.includes('Ultratech Cement') && rec.includes('250'))
await clickText(page, 'main a', 'New Receive')
await page.waitForFunction(() => location.pathname.endsWith('/store/receive/new') && document.querySelector('main')?.textContent.includes('New goods receipt'), { timeout: 15000 })
check('New Receive opens the goods receipt form under Store > Receive', true)
await open(page, `/store/receive/${grn.data.id}`)
await page.waitForFunction((n) => document.querySelector('main')?.textContent.includes(n), { timeout: 15000 }, grn.data.number)
check('a receipt opens under Store > Receive, with the way back to its list', !!(await page.$('main a[href$="/store/receive"]')))
await open(page, '/store/receive')
await page.waitForSelector('table[aria-label="Material received"]')
await shot('receive')

await open(page, '/store/issue')
await page.waitForFunction((n) => document.querySelector('table[aria-label="Material issued"]')?.textContent.includes(n), { timeout: 15000 }, issue.data.number)
const out = await text('table[aria-label="Material issued"]')
check('the issue register shows where it went and for which project', out.includes('Block A - Foundation') && out.includes('60'))
await clickText(page, 'main a', 'New Issue')
await page.waitForFunction(() => location.pathname.endsWith('/store/issue/new') && document.querySelector('main')?.textContent.includes('New issue'), { timeout: 15000 })
check('New Issue opens the issue form under Store > Issue', true)
const draft = await api(page, 'POST', '/api/store/outward/issue', { store_id: Number(STORE), issue_date: today, project_id: job, received_by_type: 'FOREMAN', received_by_name: 'Ravi', purpose: 'Block B - Columns',
  lines: [{ item_id: Number(ITEM), qty: '5', uom: 'Bag', cost_head: 'OVERHEAD' }] })
await open(page, '/store/issue')
await page.waitForFunction((n) => document.querySelector('table[aria-label="Material issued"]')?.textContent.includes(n), { timeout: 15000 }, draft.data.number)
check('a draft issue is listed with its status', (await text('table[aria-label="Material issued"]')).includes('Draft'))
await open(page, `/store/issue/${draft.data.id}`)
await page.waitForFunction((n) => document.querySelector('main')?.textContent.includes(n), { timeout: 15000 }, draft.data.number)
for (const step of ['Submit', 'Approve', 'Post']) {
  await clickText(page, 'main button', step)
  await sleep(700)
  const confirm = await page.$('[role=alertdialog] button, [role=dialog] button')
  if (confirm) await page.evaluate((w) => { const b = [...document.querySelectorAll('[role=alertdialog] button, [role=dialog] button')].filter((x) => x.textContent.trim().startsWith(w)); if (b.length) b[b.length - 1].click() }, step)
  await sleep(1200)
}
check('the draft is submitted, approved and posted from Store > Issue', (await api(page, 'GET', `/api/store/outward/issue/${draft.data.id}`)).data.status === 'POSTED')
check('posting keeps you under Store > Issue', (await page.evaluate(() => location.pathname)).includes('/store/issue/'))
await open(page, '/store/issue')
await page.waitForSelector('table[aria-label="Material issued"]')
await shot('issue')

await open(page, '/store/low-stock')
await page.waitForFunction((t) => document.querySelector('table[aria-label="Low stock"]')?.textContent.includes(t), { timeout: 15000 }, tag)
const low = await text('main')
check('low stock lists the item with how much it is short', low.includes('at or below the minimum') && low.includes('10'))
await shot('low-stock')

await open(page, '/store/hub/enquiry')
await page.waitForSelector('table[aria-label="Stock position"]', { timeout: 15000 })
check('the Store Hub stock enquiry is still the original screen', !!(await page.$('table[aria-label="Stock position"]')))
const menu = await text('nav')
check('the menu has the Store Desk under Store', menu.includes('Store Desk'))
await done()
