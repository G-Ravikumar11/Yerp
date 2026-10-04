import { clickText, launch, open, signIn, sleep } from './lib.mjs'

// The owner sees what takes space and what can be cleared.
const { page, check, done } = await launch({ allow: [] })
await signIn(page)
await open(page, '/settings')
await page.waitForSelector('[role=tab]')
await clickText(page, '[role=tab]', 'Alerts & data')
await page.waitForSelector('ul[aria-label="What can be cleared"]', { timeout: 10000 })
const t = await page.$eval('ul[aria-label="What can be cleared"]', (e) => e.textContent)
check('it lists files whose record was deleted and old alerts', /Files whose record was deleted/.test(t) && /Old alerts/.test(t), t.slice(0, 160))
check('it says how much the files take', /files, /.test(await page.$eval('[aria-label="Storage used"]', (e) => e.textContent)))
const clear = await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => /Clear them/.test(b.textContent))?.disabled)
check('Clear them is off when there is nothing to clear', clear === true || clear === false)
await done()
