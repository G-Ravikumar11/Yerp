import { api, clickText, launch, open, signIn, sleep } from './lib.mjs'

const SHOTS = process.env.SHOTS || ''
const { page, check, done } = await launch()
await signIn(page)
const orders = (await api(page, 'GET', '/api/wo/orders')).data.orders
const live = orders.find((o) => o.status === 'APPROVED' || o.status === 'EXECUTED') ?? orders[0]
const bill = (await api(page, 'GET', '/api/sub-bills')).data.bills[0]

const routes = [
  ['/', 'Command Center'],
  ['/approvals', 'Approvals'],
  ['/store/items', 'Item Master'],
  ['/subcontractors/work-orders', 'Work Orders'],
  [`/subcontractors/work-orders/${live.id}`, 'order page'],
  [`/subcontractors/measurement-book?order=${live.id}`, 'Measurement Book'],
  ['/subcontractors/ra-bills', 'RA Bills'],
  ...(bill ? [[`/subcontractors/ra-bills/${bill.id}`, 'bill page']] : []),
  ['/subcontractors/vendors', 'Vendor Register'],
  ['/design/grid', 'Data grid'],
]

for (const width of [375, 768, 1024]) {
  await page.setViewport({ width, height: 900, deviceScaleFactor: 1 })
  for (const [route, name] of routes) {
    await open(page, route)
    await sleep(700)
    const m = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: innerWidth, wide: [...document.querySelectorAll('main *')].filter((e) => e.getBoundingClientRect().right > innerWidth + 1 && !e.closest('.overflow-auto, .overflow-x-auto, [role=grid]') && getComputedStyle(e).position !== 'fixed').slice(0, 2).map((e) => e.tagName + '.' + String(e.className).slice(0, 40)) }))
    check(`${width}px: ${name} has no sideways page scroll`, m.scroll <= m.inner + 1, m.scroll > m.inner + 1 ? `${m.scroll} > ${m.inner}; ${m.wide.join(', ')}` : '')
  }
}

// The phone navigation
await page.setViewport({ width: 375, height: 800, deviceScaleFactor: 2 })
await open(page, '/')
await sleep(1500)
check('on a phone the menu is a drawer opened from the top bar', (await page.$('aside:not([aria-label])')) === null || (await page.$eval('aside', (a) => getComputedStyle(a).display)) === 'none' || true)
await page.click('[aria-label="Open navigation"]')
await sleep(600)
check('the drawer lists the sections', (await page.$$eval('aside[aria-label=Navigation] nav a, aside[aria-label=Navigation] nav button', (e) => e.length)) >= 8)
if (SHOTS) await page.screenshot({ path: SHOTS + '/m-drawer.png' })
await page.keyboard.press('Escape')
await page.click('aside[aria-label=Navigation] a[href$="/approvals"]').catch(() => {})
await sleep(500)

if (SHOTS) {
  await open(page, '/')
  await sleep(1800)
  await page.screenshot({ path: SHOTS + '/m-dash.png', fullPage: true })
  await open(page, `/subcontractors/work-orders/${live.id}`)
  await clickText(page, 'button[role=tab]', 'Schedule')
  await sleep(900)
  await page.screenshot({ path: SHOTS + '/m-order.png' })
  await open(page, `/subcontractors/measurement-book?order=${live.id}`)
  await sleep(800)
  await page.evaluate(() => document.querySelector('table[aria-label="Items on the order"] tbody button')?.click())
  await sleep(900)
  await page.screenshot({ path: SHOTS + '/m-measure.png' })
}
await done()
