import { clickText, fill, launch, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Money > Owed & Retention: who owes us, who we owe, and the retention held both ways.
const { page, check, done } = await launch({ allow: [/409 POST \/api\/retention/] })
await signIn(page)
await open(page, '/money/owed')
await page.waitForSelector('table[aria-label="Owed to us"]')
const main = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' '))
const dialog = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))

check('what is owed to us is listed with its ageing', (await main()).includes('Owed to us') && (await main()).includes('Not due') && (await main()).includes('0-30 days'))
const rows = await page.$$eval('table[aria-label="Owed to us"] tbody tr', (r) => r.length)
check('every open invoice and bill is a row', rows >= 1, `${rows} rows`)

const receive = await page.$$eval('table[aria-label="Owed to us"] button', (b) => b.filter((x) => x.textContent === 'Receive').length)
if (receive) {
  await clickText(page, 'table[aria-label="Owed to us"] button', 'Receive')
  await page.waitForSelector('[role=dialog]')
  check('Receive opens the payment for that bill', (await dialog()).includes('Receive '))
  await page.keyboard.press('Escape')
  await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
}

await clickText(page, 'button[role=tab]', 'We owe')
await page.waitForSelector('table[aria-label="We owe"]')
check('what we owe is listed with its own stats and ageing', (await main()).includes('Waiting on approval') && (await page.$$eval('table[aria-label="We owe"] tbody tr', (r) => r.length)) >= 1)

await clickText(page, 'button[role=tab]', 'Retention')
await page.waitForSelector('table[aria-label="Retention held by clients"]')
await sleep(400)
check('retention shows what clients hold and what we hold from gangs', (await main()).includes('Client is holding') && (await main()).includes('Held by us, from gangs'))

// Release some of what a client is holding
await clickText(page, 'table[aria-label="Retention held by clients"] button', 'Release')
await page.waitForSelector('#rr-amount')
check('the release dialog suggests the stage and amount', (await dialog()).includes('still held') && Number(await page.$eval('#rr-amount', (e) => e.value)) > 0)
await fill(page, '#rr-amount', '99999999')
await sleep(200)
check('more than is held is refused before it is sent', (await dialog()).includes('More than the') && (await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].find((b) => b.textContent === 'Raise the claim').disabled)))
await fill(page, '#rr-amount', '100')
await sleep(200)
check('the GST and total are worked out as the amount is typed', (await dialog()).includes('total'))
await clickText(page, 'button', 'Raise the claim')
await waitForToast(page, 'raised')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await toastsGone(page)
await sleep(600)
const rel = await page.$eval('table[aria-label="Retention releases"]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the release is listed, to receive', rel.includes('to receive'), rel.slice(0, 160))

// Cancel it again: the reason is needed, and the retention goes back to being held
await page.evaluate(() => {
  const row = [...document.querySelectorAll('table[aria-label="Retention releases"] tbody tr')].find((r) => r.textContent.includes('to receive'))
  ;[...row.querySelectorAll('button')].find((b) => b.textContent === 'Cancel').click()
})
await page.waitForSelector('[role=dialog] textarea, [role=dialog] input[type=text]')
await fill(page, '[role=dialog] textarea, [role=dialog] input[type=text]', 'Raised in error')
await clickText(page, '[role=dialog] button', 'Cancel the release')
await sleep(1200)
const after = await page.$eval('table[aria-label="Retention releases"]', (e) => e.textContent.replace(/\s+/g, ' '))
check('a cancelled release says so', after.includes('cancelled'), after.slice(0, 160))

await done()
