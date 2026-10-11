// The partner portal in React: a gang is invited, sets a password, and sees only its own orders, bills, payments and statement.
import { BASE, api, approvedOrder, launch, measure, signIn, sleep } from './lib.mjs'

const { browser, page, check, done } = await launch({ allow: [/401/, /404/] })
await signIn(page)
const order = await approvedOrder(page, { subject: 'E2E portal' })
await measure(page, order.id, order.items[0].item_id, 50)
const email = `gang${Date.now()}@example.com`
const inv = (await api(page, 'POST', '/api/portal-access', { party_type: 'contractor', party_id: order.gang.id, email, name: 'Babu' })).data
check('the invite link points at the React portal', /\/next\/portal\?invite=/.test(inv.invite_url), inv.invite_url)

// A separate browser profile, as the gang's own phone would be.
const ctx = await browser.createBrowserContext()
const gang = await ctx.newPage()
const text = () => gang.$eval('body', (b) => b.textContent.replace(/\s+/g, ' '))
await gang.goto(inv.invite_url.replace(/^https?:\/\/[^/]+/, BASE), { waitUntil: 'networkidle0' })
await gang.waitForSelector('#pi-pass')
check('the invite greets the gang by name', /Welcome, Babu/.test(await text()))
await gang.type('#pi-pass', 'Portal1234x')
await gang.type('#pi-pass2', 'Portal1234x')
await gang.click('button[type=submit]')
await gang.waitForFunction(() => /Where things stand/.test(document.body.textContent), { timeout: 15000 })
check('setting a password opens the portal on the overview', /Your account with/.test(await text()))

const tab = async (name, expect) => {
  await gang.evaluate((n) => [...document.querySelectorAll('[role=tab]')].find((t) => t.textContent === n).click(), name)
  await gang.waitForFunction((re) => new RegExp(re).test(document.body.textContent), { timeout: 10000 }, expect)
  check(`the ${name} tab opens`, true)
}
await tab('Orders', 'Your orders')
await tab('Bills', 'Your bills')
await tab('Payments', 'Payments to you')
await tab('Statement', 'Statement of account')
await tab('Overview', 'Where things stand')
check('a contractor is not offered "Send an invoice"', !/Send an invoice/.test(await text()))
await gang.evaluate(() => [...document.querySelectorAll('[role=tab]')].find((t) => t.textContent === 'Orders').click())
await gang.waitForSelector('table[aria-label="Orders"] tbody tr button')
await gang.evaluate(() => [...document.querySelectorAll('table[aria-label="Orders"] button')].find((b) => b.textContent === 'Items').click())
await gang.waitForSelector('table[aria-label="Order items"]')
check('an order opens to its items', /Shuttering/.test(await text()))

await gang.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent === 'Sign out').click())
await gang.waitForSelector('#pl-email')
check('signing out returns to the portal sign-in', true)
await gang.type('#pl-email', email)
await gang.type('#pl-pass', 'Portal1234x')
await gang.click('button[type=submit]')
await gang.waitForFunction(() => /Where things stand/.test(document.body.textContent), { timeout: 15000 })
check('the same gang signs back in with the password', true)
await sleep(200)
await done()
