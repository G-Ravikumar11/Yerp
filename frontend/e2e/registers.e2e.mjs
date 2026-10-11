import { clickText, launch, open, signIn, sleep } from './lib.mjs'

// Money > TDS, Guarantees & Advances: the three registers.
const { page, check, done } = await launch()
await signIn(page)
await open(page, '/money/registers')
await page.waitForSelector('table[aria-label="TDS by quarter"]')
const main = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' '))
await sleep(600)

check('TDS shows what we deduct, what is deducted from us, and deductees without a PAN', (await main()).includes('Deducted by us (to deposit)') && (await main()).includes('Deductees without a PAN'))
check('by quarter, then each deduction', (await main()).includes('By quarter') && (await main()).includes('Deducted from us'))
const years = await page.$$eval('#tds-year option', (o) => o.length)
check('the financial year and quarter can be narrowed', years >= 1 && (await page.$$eval('#tds-q option', (o) => o.length)) === 5)
await page.select('#tds-q', 'Q1')
await sleep(700)
check('narrowing to a quarter reloads the register', (await page.$eval('#tds-q', (e) => e.value)) === 'Q1')

await clickText(page, 'button[role=tab]', 'Guarantees')
await page.waitForSelector('table[aria-label="Bank guarantees"]')
await sleep(500)
check('guarantees show what is held and what lapses soon', (await main()).includes('Guarantees held') && (await main()).includes('Lapsing within 30 days'))
await clickText(page, 'button[role=tab]', 'Advances')
await page.waitForSelector('table[aria-label=Advances]')
await sleep(500)
check('advances show what is out and what has come back', (await main()).includes('Advances given') && (await main()).includes('Recovered so far'))
check('each register has its Excel', (await page.$('a[href="/api/registers/advances.xlsx"]')) !== null)

await done()
