import { api, approvedOrder, clickText, launch, measure, open, signIn, sleep, waitForToast } from './lib.mjs'

// Delete in the subcontract screens: a bill (from the list and from its page), a work order (from the list), a vendor.
const { page, check, done } = await launch({ allow: [/^(403|404|409) /] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const dialogText = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
const settle = () => page.waitForFunction(() => /Along with it|Nothing else|cannot be deleted/.test(document.querySelector('[role=dialog]')?.textContent || ''), { timeout: 8000 })
const raise = async (o) => {
  await measure(page, o.id, o.items[0].item_id, 10)
  const r = (await api(page, 'POST', '/api/sub-bills', { order_id: o.id })).data
  return r.bill?.id ?? r.id
}

// --- A bill, from the RA bills list ----------------------------------------------------------------------
const o = await approvedOrder(page, { subject: `Bill delete ${stamp}` })
const billId = await raise(o)
const billNo = (await api(page, 'GET', `/api/sub-bills/${billId}`)).data
const number = (billNo.bill ?? billNo).number
await open(page, `/subcontractors/ra-bills?order=${o.id}`)
await page.waitForSelector(`button[aria-label="Delete ${number}"]`)
await page.click(`button[aria-label="Delete ${number}"]`)
await page.waitForSelector('[role=dialog]')
await settle()
check('the bill says what goes with it and that its measurements are freed', /measurement/.test(await dialogText()) && /billed again/.test(await dialogText()), (await dialogText()).slice(0, 200))
await clickText(page, '[role=dialog] button', 'Delete everywhere')
await waitForToast(page, 'deleted')
check('the bill is gone', (await api(page, 'GET', `/api/sub-bills/${billId}`)).status === 404)
const book = (await api(page, 'GET', `/api/sub-mb/${o.id}`)).data
check('and what it measured is unbilled again', book.entries.length === 1 && !book.entries[0].billed)

// --- A bill, from its own page ---------------------------------------------------------------------------------
const again = await raise({ ...o, items: o.items })
await open(page, `/subcontractors/ra-bills/${again}`)
await page.waitForSelector('main')
await clickText(page, 'main button', 'Delete')
await page.waitForSelector('[role=dialog]')
await settle()
await clickText(page, '[role=dialog] button', 'Delete everywhere')
await page.waitForFunction(() => location.pathname.endsWith('/subcontractors/ra-bills'), { timeout: 10000 })
check('from its page it returns to the list and the bill is gone', (await api(page, 'GET', `/api/sub-bills/${again}`)).status === 404)

// --- A work order, from the Work Orders list ---------------------------------------------------------------------
await open(page, '/subcontractors/work-orders')
await page.waitForSelector(`button[aria-label="Delete ${o.number}"]`)
await page.click(`button[aria-label="Delete ${o.number}"]`)
await page.waitForSelector('[role=dialog]')
await settle()
await clickText(page, '[role=dialog] button', 'Delete everywhere')
await waitForToast(page, 'deleted')
check('a work order goes from the list', (await api(page, 'GET', `/api/wo/orders/${o.id}`)).status === 404)

// --- A vendor, with an order of theirs -----------------------------------------------------------------------------
const con = (await api(page, 'POST', '/api/wo/contractors', { company_name: `Gang ${stamp}`, contact_person: 'Raju', email: `gang${stamp}@example.in`, phone_number: '9000000000', pan: '', gst_number: '' })).data
const vid = (con.contractor ?? con).id
await open(page, '/subcontractors/vendors')
await page.waitForSelector(`button[aria-label="Delete Gang ${stamp}"]`)
await page.click(`button[aria-label="Delete Gang ${stamp}"]`)
await page.waitForSelector('[role=dialog]')
await settle()
check('the vendor dialog names the vendor', (await dialogText()).includes(`Gang ${stamp}`))
await clickText(page, '[role=dialog] button', 'Delete everywhere')
await waitForToast(page, 'deleted')
await sleep(400)
check('the vendor is gone from the register', !(await api(page, 'GET', '/api/wo/contractors')).data.contractors.some((c) => c.id === vid))
await done()
