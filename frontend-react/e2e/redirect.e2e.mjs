import { BASE, launch, signIn, sleep } from './lib.mjs'

// The account holder who opens app.html is taken to the new version; the previous one is at app.html?old=1 and says so.
const { page, check, done } = await launch()
await signIn(page)

await page.goto(BASE + '/app.html', { waitUntil: 'domcontentloaded' })
await page.waitForFunction(() => location.pathname.startsWith('/next'), { timeout: 10000 })
check('opening app.html takes the account holder to the new version', page.url().includes('/next/'), page.url())

await page.goto(BASE + '/app.html#approvals', { waitUntil: 'domcontentloaded' })
await page.waitForFunction(() => location.pathname.startsWith('/next'), { timeout: 10000 })
check('a link to an approval still lands on that screen (#approvals)', page.url().includes('/next/approvals'), page.url())

await page.goto(BASE + '/app.html?old=1', { waitUntil: 'networkidle0' })
await sleep(800)
check('app.html?old=1 stays on the previous version', page.url().includes('/app.html'))
const notice = await page.evaluate(() => document.querySelector('[role=status]')?.textContent ?? '')
check('and says it is the previous version, with a way to the new one', notice.includes('previous version') && notice.includes('new version'), notice)

await page.click('[role=status] a')
await page.waitForFunction(() => location.pathname.startsWith('/next'), { timeout: 10000 })
await page.waitForSelector('main h1')
await page.goto(BASE + '/app.html', { waitUntil: 'domcontentloaded' })
await page.waitForFunction(() => location.pathname.startsWith('/next'), { timeout: 10000 })
check('after going back to the new version, app.html opens the new one again', page.url().includes('/next/'))

await page.waitForSelector('a[href="/app.html?old=1"]')
await page.click('a[href="/app.html?old=1"]')
await sleep(1200)
check('the Old version link in the new app opens the previous one, not back to the new', page.url().includes('/app.html'), page.url())

await done()
