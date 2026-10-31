import { api, clickText, launch, open, signIn, sleep, waitForToast } from './lib.mjs'

// Rejecting the material on an NCR, Rejected Goods, the expired filter, and the reason a later-expiry lot needs, through the screens and the server.
const { page, check, done } = await launch({ allow: [/409 POST/] })
await signIn(page)
const { TAG: tag, STORE, ITEM, REJ } = process.env
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' ').trim())

// The rule the issue screen shows, at the server, on the seeded lots.
const jobs = (await api(page, 'GET', '/api/jobs')).data
const job = (jobs.jobs ?? jobs.items ?? jobs)[0].id
const today = new Date().toISOString().slice(0, 10)
const issue = (batch, fefo_reason = '') => api(page, 'POST', '/api/store/outward/issue/direct', { store_id: Number(STORE), issue_date: today, project_id: job, received_by_type: 'FOREMAN', received_by_name: 'Suresh',
  lines: [{ item_id: Number(ITEM), qty: '1', uom: 'Bag', cost_head: 'OVERHEAD', batch_no: batch, fefo_reason }] })
const refused = await issue(`FEFO-B${tag}`)
check('a later-expiry lot with no reason is refused', refused.status === 409 && refused.data.code === 'FEFO_REASON_REQUIRED' && refused.data.skippedLot === `FEFO-A${tag}`)
const allowed = await issue(`FEFO-B${tag}`, 'The older lot is behind the steel')
check('with a reason it goes out', allowed.status === 200)

// Raise the NCR from the batch and reject it from the NCR screen.
const raised = await api(page, 'POST', '/api/qc/ncrs', { store_batch_id: Number(REJ), description: 'Failed density test', severity: 'Minor', job_id: job })
check('the NCR is raised and the lot held', raised.status === 200)
const number = raised.data.ncr.number
await open(page, `/projects/quality?ncr=${raised.data.ncr.id}`)
await page.waitForSelector('[role=dialog]')
await sleep(900)
await clickText(page, '[role=dialog] button', 'Reject material')
await sleep(500)
const box = await page.$$('[role=dialog] textarea, [role=alertdialog] textarea')
await box[box.length - 1].type('Density far below the data sheet')
await page.evaluate(() => { const b = [...document.querySelectorAll('[role=dialog] button, [role=alertdialog] button')].filter((x) => x.textContent.trim() === 'Reject material'); b[b.length - 1].click() })
await waitForToast(page, 'rejected')
check('the NCR is rejected', (await api(page, 'GET', `/api/qc/ncrs/${raised.data.ncr.id}`)).data.ncr.status === 'REJECTED')
const lot = (await api(page, 'GET', `/api/store/batches/${REJ}`)).data
check('the lot shows Rejected with nothing available', lot.hold_status === 'Rejected' && Number(lot.available_qty) === 0)

await open(page, '/store/hub/inward/rejected')
await page.waitForSelector('table[aria-label="Rejected goods"]')
await sleep(1500)
const list = await text('table[aria-label="Rejected goods"]')
check('Rejected Goods lists the lot and its NCR', list.includes(`REJ-${tag}`) && list.includes(number))

await open(page, '/store/hub/enquiry/batches')
await page.waitForSelector('table[aria-label=Batches]')
await clickText(page, 'main button', 'Expired stock')
await sleep(1000)
check('the expired filter answers', /No batches|Expired/.test(await text('main')))
const again = await api(page, 'POST', `/api/qc/ncrs/${raised.data.ncr.id}/reject`, { reason: 'Again' })
check('rejecting twice is refused', again.status === 409)

// The issue form: a draft naming the later lot warns, keeps the reason, and the posted issue shows who passed over what.
const draft = await api(page, 'POST', '/api/store/outward/issue', { store_id: Number(STORE), issue_date: today, project_id: job, received_by_type: 'FOREMAN', received_by_name: 'Suresh',
  lines: [{ item_id: Number(ITEM), qty: '1', uom: 'Bag', cost_head: 'OVERHEAD', batch_no: `FEFO-B${tag}`, fefo_reason: 'Older lot is behind the steel' }] })
check('a draft with a reason saves', draft.status === 200)
await open(page, `/store/hub/outward/issue/${draft.data.id}/edit`)
await page.waitForSelector('input[aria-label="Reason for selecting this later-expiry lot"]', { timeout: 15000 })
check('the form warns of the earlier lot and offers it', /earlier-expiry material lot is available/.test(await text('main')) && (await text('main')).includes(`Use FEFO-A${tag}`))
check('the reason is kept on the line', (await page.$eval('input[aria-label="Reason for selecting this later-expiry lot"]', (e) => e.value)) === 'Older lot is behind the steel')
const direct = allowed.data.id
await open(page, `/store/hub/outward/issue/${direct}`)
await page.waitForFunction(() => document.querySelector('main')?.textContent.includes('passed over by'), { timeout: 15000 })
check('the posted issue shows the lot passed over and why', (await text('main')).includes(`FEFO-A${tag}`) && (await text('main')).includes('behind the steel'))

// The receipt works the expiry out the same way the server saves it, and the maker's date replaces it.
const made = new Date(Date.now() - 2 * 864e5).toISOString().slice(0, 10)
const grn = await api(page, 'POST', '/api/store/inward/grn', { store_id: Number(STORE), grn_date: today, supplier_name: 'Shree Traders', lines: [{ item_id: Number(ITEM), qty: '10', uom: 'Bag', rate: '10', batch_no: `G-${tag}`, manufacturing_date: made }] })
check('a receipt with a manufacturing date saves', grn.status === 200)
check('the saved expiry is manufacture + the item shelf life', grn.data.lines[0].expiry_date === new Date(Date.parse(made) + 30 * 864e5).toISOString().slice(0, 10))
const none = await api(page, 'POST', '/api/store/inward/grn', { store_id: Number(STORE), grn_date: today, supplier_name: 'Shree Traders', lines: [{ item_id: Number(ITEM), qty: '10', uom: 'Bag', rate: '10', batch_no: `H-${tag}` }] })
check('a tracked item with no dates is refused', none.status === 400)
await open(page, `/store/hub/inward/grn/${grn.data.id}/edit`)
await page.waitForSelector('input[aria-label="Expiry date"]', { timeout: 15000 })
await sleep(1200)
check('the receipt form says how it is worked out', /30 days from manufacture/.test(await text('main')))

// The item form asks for the shelf life.
await open(page, '/store/items')
await clickText(page, 'main button', 'New item')
await page.waitForSelector('[role=dialog]')
await sleep(500)
check('the item form offers shelf life and expiry tracking', /This material has a shelf life/.test(await text('[role=dialog]')) && /Track expiry/.test(await text('[role=dialog]')))
await page.evaluate(() => [...document.querySelectorAll('[role=dialog] label')].find((l) => l.textContent.includes('This material has a shelf life')).querySelector('input').click())
await page.waitForSelector('#im-shelf')
check('ticking it asks for the days', true)
await done()
