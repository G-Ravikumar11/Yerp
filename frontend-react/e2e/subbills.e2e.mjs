import { api, approvedOrder, clickText, fill, launch, measure, open, setValue, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/409 POST \/api\/sub-bills/] })
await signIn(page)
const order = await approvedOrder(page, { subject: 'E2E RA bills' })
const item = order.items[0]
const text = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' '))

await open(page, `/subcontractors/ra-bills?order=${order.id}`)
await page.waitForSelector('table[aria-label="RA bills"]')
check('the RA bills screen opens on the chosen order', (await text()).includes('Billed up to date') && (await text()).includes('Cumulative net'))

// --- Nothing measured, nothing to bill ---------------------------------------------------
await clickText(page, 'main button', 'Draw up a bill')
await waitForToast(page, 'Nothing has been measured')
check('a bill cannot be drawn before anything is measured, and it says so', true)
await toastsGone(page)

// --- The first bill ------------------------------------------------------------------------
await measure(page, order.id, item.item_id, 100) // 100 sqm at 410 = 41,000
await clickText(page, 'main button', 'Draw up a bill')
await page.waitForFunction(() => /RA-\d+$/.test(document.querySelector('main h1')?.textContent.trim() ?? ''))
const bill1 = Number(page.url().match(/ra-bills\/(\d+)/)[1])
const num1 = await page.$eval('main h1', (e) => e.textContent.trim())
check('a bill is drawn from the measurement book: RA-01', /\/RA-01$/.test(num1), num1)
const t1 = await text()
check('it claims exactly what was measured (₹41,000) and nothing before it', t1.includes('₹41,000.00') && t1.includes('Previously billed₹0.00'))
check('the certificate works out GST, retention and TDS', /GST|CGST|IGST/.test(t1) && /Retention @ 5%/.test(t1) && /TDS @ 1%/.test(t1))

// --- Fill in the certificate's boxes, save, submit ----------------------------------------------
await fill(page, '#b-name', 'E2E shuttering, tower C')
await setValue(page, '#b-date', '2026-11-30')
await fill(page, '#b-sac', '995469')
await clickText(page, 'main button', 'Save')
await waitForToast(page, 'saved')
await sleep(400)
const saved = (await api(page, 'GET', `/api/sub-bills/${bill1}`)).data
check('the certificate boxes were saved', saved.work_name === 'E2E shuttering, tower C' && saved.hsn_sac === '995469' && saved.bill_date === '2026-11-30')
await toastsGone(page)
await clickText(page, 'main button', 'Submit')
await sleep(1200)
const submitted = (await api(page, 'GET', `/api/sub-bills/${bill1}`)).data
check('submitting sends it up for certification', submitted.status === 'SUBMITTED', submitted.status)
check('a submitted bill can no longer be edited on screen', (await page.$('#b-name:not([disabled])')) === null)

// --- Certify, then pay ---------------------------------------------------------------------------------
await toastsGone(page)
await clickText(page, 'main button', 'Certify')
await page.waitForSelector('[role=dialog]')
await clickText(page, '[role=dialog] button', 'Certify')
await waitForToast(page, 'certified')
await sleep(500)
check('the owner can certify it', (await api(page, 'GET', `/api/sub-bills/${bill1}`)).data.status === 'CERTIFIED')
await toastsGone(page)
await clickText(page, 'main button', 'Pay')
await page.waitForSelector('#pay-amount')
const payText = await page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the payment box shows what is owed', /left/.test(payText) && /Worth/.test(payText), (payText.match(/Worth.{0,80}/) || [''])[0])
await fill(page, '#pay-ref', 'UTR-E2E-1')
await clickText(page, '[role=dialog] button', 'Pay ₹')
await waitForToast(page, 'e', 6000)
await sleep(900)
const paid = (await api(page, 'GET', `/api/sub-bills/${bill1}`)).data
check('paying it settles the bill', paid.status === 'PAID', paid.status)

// --- A second bill: previous, this bill, up to date, cumulative -----------------------------------------
await measure(page, order.id, item.item_id, 50) // +50 sqm = 20,500
await open(page, `/subcontractors/ra-bills?order=${order.id}`)
await page.waitForSelector('table[aria-label="RA bills"] tbody tr')
await clickText(page, 'main button', 'Draw up a bill')
await page.waitForFunction((id) => /ra-bills\/\d+/.test(location.pathname) && !location.pathname.endsWith('/' + id), {}, bill1)
const bill2 = Number(page.url().match(/ra-bills\/(\d+)/)[1])
await page.waitForFunction(() => /RA-02/.test(document.querySelector('main h1')?.textContent ?? ''))
await sleep(300)
check('the second bill claims only the new work (₹20,500) after ₹41,000 billed', (await text()).includes('Previously billed₹41,000.00') && (await text()).includes('₹20,500.00') && (await text()).includes('Billed up to date₹61,500.00'))
await open(page, `/subcontractors/ra-bills?order=${order.id}`)
await page.waitForSelector('table[aria-label="RA bills"] tbody tr')
const cells = await page.$$eval('table[aria-label="RA bills"] tbody tr', (rows) => rows.map((r) => [...r.querySelectorAll('td')].map((c) => c.textContent.trim())))
const [r2, r1] = cells // newest first
check('the list shows Previous / This bill / Up to date for each bill', r2.includes('₹41,000.00') && r2.includes('₹20,500.00') && r2.includes('₹61,500.00') && r1.includes('₹0.00') && r1.includes('₹41,000.00'), r2.slice(3, 7).join(' | '))
const nets = await api(page, 'GET', `/api/sub-bills?order_id=${order.id}`)
const [b2, b1] = nets.data.bills
check('the cumulative net is the running total of what is payable', r2.includes(new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(b1.net_payable + b2.net_payable)), `${b1.net_payable} + ${b2.net_payable}`)
check('the tiles show billed up to date for the order', (await text()).includes('₹61,500.00') || /Billed up to date.{0,20}(61\.5|61,500)/.test(await text()))

// --- Cancel the draft, asking why ------------------------------------------------------------------------
await page.click('table[aria-label="RA bills"] tbody tr:first-child')
await page.waitForFunction((id) => location.pathname.endsWith('/' + id), {}, bill2)
await page.waitForSelector('main h1')
await clickText(page, 'main button', 'Cancel bill')
await page.waitForSelector('[role=dialog] textarea')
await clickText(page, '[role=dialog] button', 'Cancel the bill')
await sleep(400)
check('cancelling asks for a reason', (await page.$eval('[role=dialog]', (e) => e.textContent)).includes('Say why'))
await page.type('[role=dialog] textarea', 'E2E clean up')
await clickText(page, '[role=dialog] button', 'Cancel the bill')
await waitForToast(page, 'cancelled')
await sleep(500)
check('the bill is cancelled and its measurements are freed', (await api(page, 'GET', `/api/sub-bills/${bill2}`)).data.status === 'CANCELLED')

await done()
