// The Master deletes a project and a single record, each with what hangs off it, from the screens.
import { api, clickText, launch, open, signIn, sleep } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/404 GET \/api\/jobs\//] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)

// A project with a bill filed against it.
const job = (await api(page, 'POST', '/api/jobs', { name: `Delete me ${stamp}`, status: 'in_progress' })).data
const jobId = job.job?.id ?? job.id
const bill = await api(page, 'POST', '/api/bills', { number: `DEL-${stamp}`, vendor_name: 'X', amount: 10, total: 10, job_id: jobId })
check('a project and a bill against it exist', !!jobId && bill.status === 200, JSON.stringify(bill.data).slice(0, 80))

await open(page, '/projects')
await page.waitForSelector('table[aria-label="Projects"] tbody tr')
const label = `Delete me ${stamp}`
const rowBtn = await page.evaluateHandle((l) => [...document.querySelectorAll('table[aria-label="Projects"] button')].find((b) => (b.getAttribute('aria-label') || '').includes(l)), label)
check('the Master sees a delete on the project row', !!rowBtn.asElement())
await rowBtn.click()
await page.waitForSelector('[role=dialog]')
await page.waitForFunction(() => /Along with it/.test(document.querySelector('[role=dialog]').textContent), { timeout: 10000 })
check('the dialog says what goes with the project (the bill)', /1 supplier bills/.test(await page.$eval('[role=dialog]', (d) => d.textContent)), await page.$eval('[role=dialog]', (d) => d.textContent.slice(0, 160)))
await clickText(page, '[role=dialog] button', 'Delete everywhere')
await page.waitForFunction((l) => ![...document.querySelectorAll('table[aria-label="Projects"] tbody tr')].some((r) => r.textContent.includes(l)), { timeout: 15000 }, label)
check('the project is gone from the list', true)
await sleep(500)
check('and the project is gone from the server', (await api(page, 'GET', `/api/jobs/${jobId}`)).status === 404)
check('and so is its bill', !(await api(page, 'GET', '/api/bills')).data.some((b) => b.number === `DEL-${stamp}`))

// A single record: a purchase order from its list.
const po = await api(page, 'POST', '/api/purchase-orders', { supplier_name: 'ACC', amount: 1000, line_items: [{ description: 'Cement', item_code: 'RM-CEM', qty: 10, price: 100 }] })
if (po.status === 200) {
  await open(page, '/store/purchase-orders')
  await page.waitForSelector('table[aria-label="Purchase orders"] tbody tr')
  const btn = await page.$('table[aria-label="Purchase orders"] button[aria-label^="Delete "]')
  check('a purchase order row offers the Master delete', !!btn)
  if (btn) {
    await btn.click()
    await page.waitForSelector('[role=dialog]')
    await clickText(page, '[role=dialog] button', 'Delete everywhere')
    await sleep(1500)
    check('and it deletes', !(await page.$('[role=dialog]')))
  }
} else check('purchase order created for the test', false, JSON.stringify(po.data).slice(0, 100))
await done()
