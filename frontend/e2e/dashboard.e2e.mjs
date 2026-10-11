import { api, launch, open, signIn, sleep } from './lib.mjs'

const SHOTS = process.env.SHOTS || ''
const { page, check, done } = await launch({ height: 1400 })
await signIn(page)

const compact = (v) => {
  const abs = Math.abs(v), sign = v < 0 ? '-' : ''
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`
  if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(1)} K`
  return `${sign}₹${abs.toFixed(0)}`
}
const rec = (await api(page, 'GET', '/api/money/receivables')).data.summary
const pay = (await api(page, 'GET', '/api/money/payables')).data.summary
const pnl = (await api(page, 'GET', '/api/jobs-pnl')).data

await open(page, '/')
await page.waitForFunction(() => document.querySelectorAll('figure svg').length >= 3, { timeout: 15000 })
await sleep(1500) // let the figures finish counting up
const tiles = await page.$$eval('main p.font-display', (els) => els.map((e) => e.textContent.trim()))
check('the Owed to us tile matches the ledger', tiles.includes(compact(rec.owed)), `${compact(rec.owed)} in ${JSON.stringify(tiles)}`)
check('the We owe tile matches the payables', tiles.includes(compact(pay.owed)), compact(pay.owed))
check('the order book tile matches the project P&L', tiles.includes(compact(pnl.summary.order_value)), compact(pnl.summary.order_value))
check('the greeting names the signed-in person', /Good (morning|afternoon|evening),/.test(await page.$eval('main h1', (e) => e.textContent)))
check('all three charts drew', (await page.$$eval('main figure svg', (s) => s.length)) >= 3)
check('the profit chart has a bar per project (revenue and cost)', (await page.$$eval('figure[aria-label="Revenue and cost by project"] .recharts-bar-rectangle', (r) => r.length)) >= 2)
const attention = await page.$$eval('main ul li a', (a) => a.length)
check('the attention list shows what needs a look, each a link', attention > 0, `${attention} items`)

if (SHOTS) {
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: SHOTS + '/dash-dark.png' })
  await page.evaluate(() => document.querySelector('[aria-label="Light"]').click())
  await sleep(600)
  await page.screenshot({ path: SHOTS + '/dash-light.png' })
}
await done()
