import { api, clickText, launch, open, signIn, sleep } from './lib.mjs'

// The Store Desk and the Store Hub lead to each other, and what is posted in one shows in the other at once.
const { page, check, done } = await launch({ allow: [] })
await signIn(page)
const { TAG: tag, STORE, ITEM } = process.env
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())
const path = () => page.evaluate(() => location.pathname + location.search)
const today = new Date().toISOString().slice(0, 10)
const row = (table, word) => page.evaluate((t, w) => [...document.querySelectorAll(`table[aria-label="${t}"] tbody tr`)].find((r) => r.textContent.includes(w))?.textContent.replace(/\s+/g, ' '), table, word)
const clickRow = (table, word) => page.evaluate((t, w) => [...document.querySelectorAll(`table[aria-label="${t}"] tbody tr`)].find((r) => r.textContent.includes(w)).click(), table, word)

// The hub leads to the desk.
await open(page, '/store/hub')
await clickText(page, 'main a', 'Store Desk')
await page.waitForFunction(() => location.pathname.endsWith('/store'), { timeout: 15000 })
check('every Store Hub page has a way to the Store Desk', true)

// A first receipt, so the item is in stock and the hub's stock list is loaded (and cached) with it.
const first = await api(page, 'POST', '/api/store/inward/grn', { store_id: Number(STORE), grn_date: today, supplier_name: 'Ultratech Cement', lines: [{ item_id: Number(ITEM), qty: '100', uom: 'Bag', rate: '380' }] })
for (const step of ['submit', 'approve', 'post']) await api(page, 'POST', `/api/store/inward/grn/${first.data.id}/${step}`)
await open(page, '/store/hub/enquiry')
await page.waitForFunction((t) => document.querySelector('table[aria-label="Stock position"]')?.textContent.includes(t), { timeout: 15000 }, tag)
check('the hub stock list shows 100 to start with', /\D100 Bag/.test(await row('Stock position', tag)))

// From the desk, the stock card leads back to the desk.
await clickText(page, 'main a', 'Store Desk')
await page.waitForFunction((t) => document.querySelector('table[aria-label="Stock register"]')?.textContent.includes(t), { timeout: 15000 }, tag)
await clickRow('Stock register', tag)
await page.waitForFunction(() => location.pathname.endsWith('/store/hub/enquiry/card'), { timeout: 15000 })
await sleep(800)
check('the stock card opened from the desk says the way back is the desk', /Store Desk/.test(await text('main')))
await clickText(page, 'main a', 'Store Desk')
await page.waitForFunction(() => location.pathname.endsWith('/store'), { timeout: 15000 })
check('and goes back to it', true)

// Batches from the desk lead back to it too.
await page.waitForFunction(() => [...document.querySelectorAll('main a')].some((a) => a.textContent.includes('Batches')), { timeout: 15000 })
await clickText(page, 'main a', 'Batches & quality holds')
await page.waitForFunction(() => location.pathname.endsWith('/store/hub/enquiry/batches'), { timeout: 15000 })
await sleep(600)
check('batches opened from the desk lead back to the desk', !!(await page.$('main a[href$="/store?tab=stock"]')))

// A receipt posted from the desk shows at once in the hub, with no reload.
const second = await api(page, 'POST', '/api/store/inward/grn', { store_id: Number(STORE), grn_date: today, supplier_name: 'Ultratech Cement', lines: [{ item_id: Number(ITEM), qty: '50', uom: 'Bag', rate: '380' }] })
await open(page, `/store/receive/${second.data.id}`)
await page.waitForFunction((n) => document.querySelector('main')?.textContent.includes(n), { timeout: 15000 }, second.data.number)
for (const step of ['Submit', 'Approve', 'Post']) {
  await clickText(page, 'main button', step)
  await sleep(700)
  await page.evaluate((w) => { const b = [...document.querySelectorAll('[role=alertdialog] button, [role=dialog] button')].filter((x) => x.textContent.trim().startsWith(w)); if (b.length) b[b.length - 1].click() }, step)
  await sleep(1200)
}
check('the receipt is posted from the desk', (await api(page, 'GET', `/api/store/inward/grn/${second.data.id}`)).data.status === 'POSTED')
check('and stays under Store > Receive', (await path()).includes('/store/receive/'))
// Into the hub the way a person would, by clicking - the page is not reloaded, so a stale list would show.
await page.evaluate(() => document.querySelector('a[href$="/store"]')?.click())
await page.waitForFunction(() => location.pathname.endsWith('/store'), { timeout: 15000 })
await clickText(page, 'main a', 'All store work')
await page.waitForFunction(() => location.pathname.endsWith('/store/hub'), { timeout: 15000 })
await page.evaluate(() => [...document.querySelectorAll('nav[aria-label="Store sections"] a')].find((a) => /Stock enquiry/.test(a.textContent)).click())
await page.waitForFunction((t) => document.querySelector('table[aria-label="Stock position"]')?.textContent.includes(t), { timeout: 15000 }, tag)
await sleep(1500)
check('the hub stock list shows the new 150 without a reload', /\D150 Bag/.test(await row('Stock position', tag)))
await done()
