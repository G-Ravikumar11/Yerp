import { clickText, fill, launch, open, signIn, sleep, waitForToast } from './lib.mjs'

// Money > GST: the supplies a return is filed from, and the GSTIN that decides CGST/SGST or IGST.
const { page, check, done } = await launch()
await signIn(page)
await open(page, '/money/gst')
await page.waitForSelector('#gst-gstin')
const main = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' '))
await sleep(800)

check('the outward supplies show their tax split and the months', (await main()).includes('Taxable value') && (await main()).includes('Total tax') && (await main()).includes('By month'))
check('the period defaults to this financial year', (await page.$eval('#gst-from', (e) => e.value)).endsWith('-04-01') && (await page.$eval('#gst-to', (e) => e.value)).endsWith('-03-31'))
check('an Excel of the outward supplies can be downloaded', (await page.$('a[href^="/api/gst/outward.xlsx"]')) !== null)

await fill(page, '#gst-gstin', '36aaacl0140p1z8')
await clickText(page, 'button', 'Save')
await waitForToast(page, 'Registered in')
await sleep(600)
check('saving the GSTIN says which state it puts us in', (await main()).includes('Telangana') || (await main()).includes('(36)'), (await main()).slice(0, 220))

await fill(page, '#gst-from', '2020-04-01')
await sleep(900)
await clickText(page, 'button[role=tab]', 'Inward')
await page.waitForSelector('table[aria-label="Inward supplies"]')
await sleep(500)
check('inward supplies show the input credit and flag suppliers with no GSTIN', (await main()).includes('Input credit') && (await main()).includes('Missing supplier GSTIN'))
check('and have their own Excel', (await page.$('a[href^="/api/gst/inward.xlsx"]')) !== null)

await done()
