import { clickText, fill, launch, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Clients > Customers: add one, find it, correct it; the same name twice is refused.
const { page, check, done } = await launch({ allow: [/409 POST \/api\/customers/] })
await signIn(page)
await open(page, '/clients/customers')
await page.waitForSelector('table[aria-label=Customers]')
const stamp = Date.now().toString().slice(-6)
const name = `E2E Builders ${stamp}`
const rows = () => page.$$eval('table[aria-label=Customers] tbody tr', (r) => r.map((e) => e.textContent.replace(/\s+/g, ' ')))

check('the list loads from the real backend', (await rows()).length >= 1, `${(await rows()).length} customers`)

await clickText(page, 'button', 'Add new customer')
await page.waitForSelector('[role=dialog]')
await fill(page, '#cu-name', name)
await fill(page, '#cu-person', 'A. Rao')
await fill(page, '#cu-gstin', '36aaacl0140p1z8')
await fill(page, '#cu-city', 'Vizag')
await clickText(page, 'button', 'Save customer')
await waitForToast(page, 'added')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await toastsGone(page)

await fill(page, 'input[aria-label="Search customers"]', stamp)
await sleep(700)
const found = await rows()
check('a new customer gets a code and is found by searching', found.length === 1 && /CUS|C-?\d|\d{3}/.test(found[0]) && found[0].includes(name), found[0])
check('the GSTIN is kept in capitals, and the PAN is read from it', found[0].includes('36AAACL0140P1Z8') && found[0].includes('AAACL0140P'), found[0])

await clickText(page, 'table[aria-label=Customers] button', 'Edit')
await page.waitForSelector('[role=dialog]')
check('editing opens what was saved', (await page.$eval('#cu-person', (e) => e.value)) === 'A. Rao')
await fill(page, '#cu-person', 'B. Reddy')
await clickText(page, 'button', 'Save customer')
await waitForToast(page, 'updated')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await sleep(500)
check('the change shows on the list', (await rows())[0].includes('B. Reddy'))
await toastsGone(page)

await clickText(page, 'button', 'Add new customer')
await page.waitForSelector('[role=dialog]')
await fill(page, '#cu-name', name.toUpperCase())
await clickText(page, 'button', 'Save customer')
await page.waitForFunction(() => document.querySelector('[role=dialog] [role=alert]')?.textContent.includes('already'), { timeout: 8000 })
check('the same name in other capitals is refused, in the server\'s words', true)

await done()
