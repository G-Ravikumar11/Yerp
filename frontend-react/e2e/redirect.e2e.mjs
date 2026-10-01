import { BASE, launch, signIn } from './lib.mjs'

// The previous interface is gone: its old addresses, bookmarks and installed shortcuts land in the new one.
const { page, check, done } = await launch()
await signIn(page)
const lands = async (path, expect, why) => {
  await page.goto(BASE + path, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => location.pathname.startsWith('/next'), { timeout: 10000 })
  check(why, page.url().includes(expect), page.url())
}
await lands('/app.html', '/next/', 'app.html opens the new interface')
await lands('/app.html#approvals', '/next/approvals', 'a link to an approval still lands on that screen (#approvals)')
await lands('/app.html#subcontracts', '/next/subcontractors/work-orders', 'and one to subcontracts')
await lands('/app.html#diary-view', '/next/projects/diary', 'an installed Site Diary shortcut lands on the diary')
await lands('/employee-dashboard.html', '/next/', 'the old staff page opens the new interface')
await lands('/hr.html', '/next/people/employees', 'the old HR page opens People')
await page.waitForSelector('main h1')
check('there is no link back to a previous version', (await page.$('a[href*="old=1"]')) === null)
await done()
