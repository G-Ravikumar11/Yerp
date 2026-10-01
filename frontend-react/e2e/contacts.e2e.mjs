import { api, clickText, fill, launch, open, signIn, toastsGone, waitForToast } from './lib.mjs'

// Contacts, and the budget report that a budgeted client work order opens.
const { page, check, done } = await launch()
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const main = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' ').trim())

// --- Contacts ---------------------------------------------------------------------------------------------
await open(page, '/clients/contacts')
await page.waitForSelector('table[aria-label=Contacts]')
await clickText(page, 'main button', 'New contact')
await page.waitForSelector('#ct-name')
await fill(page, '#ct-name', `Sri Sai Traders ${stamp}`)
await fill(page, '#ct-email', `sai${stamp}@example.in`)
await fill(page, '#ct-gstin', '36aaacl1234h1z5')
await fill(page, '#ct-city', 'Warangal')
await clickText(page, '[role=dialog] button', 'Save contact')
await waitForToast(page, 'Contact created')
await toastsGone(page)
const made = (await api(page, 'GET', '/api/contacts')).data.find((c) => c.name === `Sri Sai Traders ${stamp}`)
check('a contact is saved, the GSTIN in capitals', !!made && made.gstin === '36AAACL1234H1Z5' && made.city === 'Warangal', JSON.stringify(made))
await page.waitForFunction((n) => document.querySelector('table[aria-label=Contacts]')?.textContent.includes(n), {}, `Sri Sai Traders ${stamp}`)
await fill(page, '[aria-label="Search contacts"]', `Traders ${stamp}`)
check('the search narrows the list', (await page.$$eval('table[aria-label=Contacts] tbody tr', (r) => r.length)) === 1)
await clickText(page, 'table[aria-label=Contacts] button', 'Edit')
await page.waitForSelector('#ct-phone')
await fill(page, '#ct-phone', '9848012345')
await clickText(page, '[role=dialog] button', 'Save contact')
await waitForToast(page, 'Contact updated')
await toastsGone(page)
check('an edit is kept', (await api(page, 'GET', '/api/contacts')).data.find((c) => c.id === made.id).phone_number === '9848012345')
await clickText(page, 'table[aria-label=Contacts] button', 'Delete')
await clickText(page, '[role=alertdialog] button, [role=dialog] button', 'Delete')
await waitForToast(page, 'Contact deleted')
await toastsGone(page)
check('and a contact can be deleted', !(await api(page, 'GET', '/api/contacts')).data.some((c) => c.id === made.id))

// --- Budget report ----------------------------------------------------------------------------------------
const items = (await api(page, 'POST', '/api/erp/items/bulk', { items: [
  { kind: 'FG', item_name: `BR Panel ${stamp}`, units_of_measure: 'Nos', item_type: 'Service' },
  { kind: 'RM', item_name: `BR Steel ${stamp}`, units_of_measure: 'Kgs', item_type: 'Purchased' },
  { kind: 'FG', item_name: `BR Unbudgeted ${stamp}`, units_of_measure: 'Nos', item_type: 'Service' },
] })).data
const [fg, rm, fg2] = items.codes
const jobs = (await api(page, 'GET', '/api/jobs?open_only=true')).data.jobs
const built = await api(page, 'POST', '/api/erp/work-orders/build', { job_id: jobs[0].id, reference: `PO/BR/${stamp}`, lines: [{ code: fg, qty: 10, rate: 500 }, { code: fg2, qty: 2, rate: 1000 }] })
check('an order with two sold lines exists', built.status === 200, JSON.stringify(built.data).slice(0, 120))
const woId = built.data.work_order?.id ?? built.data.id
const bom = await api(page, 'POST', '/api/erp/bom/build', { work_order_id: woId, lines: [{ fg_code: fg, rm_code: rm, qty: 40, rate: 50 }] })
check('one of them is budgeted', bom.status === 200, JSON.stringify(bom.data).slice(0, 120))

await open(page, '/clients/work-orders')
await page.waitForSelector('table[aria-label="Client work orders"] tbody tr')
await page.waitForFunction((r) => [...document.querySelectorAll('table[aria-label="Client work orders"] tbody tr')].some((x) => x.textContent.includes(r)), {}, `PO/BR/${stamp}`)
await page.evaluate((r) => [...document.querySelectorAll('table[aria-label="Client work orders"] tbody tr')].find((x) => x.textContent.includes(r)).querySelector('a[href$="budget-report"]').click(), `PO/BR/${stamp}`)
await page.waitForSelector('table[aria-label="Budget report"]')
const t = await main()
check('the report shows the sold line, what it consumes, and the cost', t.includes(fg) && t.includes(rm) && t.includes('2,000'), t.slice(0, 300))
check('a sold line with nothing budgeted is shown, and counted', t.includes('Not budgeted') && t.includes('1 not budgeted'), t.slice(-200))
check('the margin is worked out (7,000 less 2,000)', t.includes('5,000') && t.includes('Margin'), t.slice(-120))
check('it offers Download, Print and Back', t.includes('Download') && t.includes('Print') && t.includes('Back'))
const xlsx = await api(page, 'GET', `/api/erp/work-orders/${woId}/budget-report.xlsx`).catch(() => ({ status: 0 }))
check('the workbook it links to is served', xlsx.status === 200 || xlsx.status === undefined, String(xlsx.status))
await done()
