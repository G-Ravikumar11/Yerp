import { api, approvedOrder, launch, open, signIn, sleep } from './lib.mjs'

// After an order is amended and its revision approved, the Measurement Book opens on the revision -
// not on the amended order it was last left on.
const { page, check, done } = await launch()
await signIn(page)
const o = await approvedOrder(page, { subject: 'follow the revision' })
await api(page, 'POST', `/api/sub-mb/${o.id}/entries`, { item_id: o.items[0].item_id, quantity: 10, measured_on: '2026-11-15' })

// The book is last left on this order
await open(page, `/subcontractors/measurement-book`)
await sleep(800)
await page.click('button[aria-label="Work order"]')
await page.type('input[role=combobox]', o.number)
await sleep(300)
await page.keyboard.press('Enter')
await sleep(800)
const current = () => page.$eval('button[aria-label="Work order"]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the order is chosen and remembered', (await current()).includes(o.number), await current())

// It is amended and the revision approved
const rev = (await api(page, 'POST', `/api/wo/orders/${o.id}/amend`, {})).data.order
await api(page, 'POST', `/api/wo/orders/${rev.id}/submit`, {})
const ap = await api(page, 'POST', `/api/wo/orders/${rev.id}/approve`, { comments: 'ok' })
check('the revision is approved', ap.status === 200, JSON.stringify(ap.data).slice(0, 100))

await open(page, '/subcontractors/measurement-book')
await sleep(1200)
check('the book now opens on the revision', (await current()).includes(rev.wo_number), await current())
const t = await page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' '))
check('with the measurement carried across, and it can take more', t.includes('Measured') && !t.includes('cannot take new measurements'), t.slice(0, 160))
await page.click('button[aria-label="Work order"]')
const opts = await page.$$eval('[role=listbox] [role=option]', (x) => x.map((e) => e.textContent.replace(/\s+/g, ' ')))
check('the amended order is still listed, for reference', opts.some((x) => x.includes(o.number) && x.includes('amended')), opts.slice(0, 3).join(' | '))
await done()
