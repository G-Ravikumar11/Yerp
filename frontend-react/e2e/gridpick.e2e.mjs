import { api, clickCell, clickText, launch, open, signIn, sleep } from './lib.mjs'

// Choosing a unit in the schedule grid: with the mouse, with the keyboard, and typing one nobody listed.
const { page, check, done } = await launch({ width: 1366, height: 768 })
await signIn(page)
const vocab = (await api(page, 'GET', '/api/wo/vocabulary')).data
const gang = (await api(page, 'GET', '/api/wo/contractors')).data.contractors.find((c) => c.registration_status === 'APPROVED')
const unit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
const order = (await api(page, 'POST', '/api/wo/orders', { business_unit_id: unit.id, contractor_id: gang.id, job_id: vocab.jobs[0].id, department: 'Civil', subject: 'QA unit picker', commencement_date: '2026-11-01', completion_date: '2027-03-31' })).data.order
await open(page, `/subcontractors/work-orders/${order.id}`)
await clickText(page, 'button[role=tab]', 'Schedule')
await page.waitForSelector('[role=grid]')
const heads = await page.$$eval('[role=columnheader]', (h) => h.map((e) => e.textContent.trim()))
const col = heads.findIndex((h) => h.startsWith('Unit')) - 1
const cellOf = (row) => page.evaluate((r, c) => [...document.querySelectorAll('[role=grid] [role=row]')][r + 1]?.querySelectorAll('[role=gridcell]')[c]?.textContent.trim(), row, col)
const press = async (name) => {
  const p = await page.evaluate((n) => { const e = [...document.querySelectorAll('[role=listbox] [role=option]')].find((x) => x.textContent === n); const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 } }, name)
  await page.mouse.click(p.x, p.y)
}

await clickCell(page, 0, 0, 1)
await page.keyboard.type('Shuttering'); await page.keyboard.press('Enter')
await clickCell(page, 0, 1, 1)
await page.keyboard.type('Plastering'); await page.keyboard.press('Enter')
await clickCell(page, 0, 2, 1)
await page.keyboard.type('Earth work'); await page.keyboard.press('Enter')

await clickCell(page, 0, 0, col)
await page.keyboard.press('F2')
await page.waitForSelector('[role=listbox] [role=option]')
await press('sqm')
await sleep(400)
check('clicking a unit in the list puts it in the cell', (await cellOf(0)) === 'sqm', await cellOf(0))
check('and the list closes', (await page.$('[role=listbox]')) === null)

await clickCell(page, 0, 1, col)
await page.keyboard.press('F2')
await page.keyboard.type('cu')
await sleep(200)
await page.keyboard.press('Enter')
await sleep(300)
check('typing part of a unit and pressing Enter takes the match (cu -> cum)', (await cellOf(1)) === 'cum', await cellOf(1))

await clickCell(page, 0, 2, col)
await page.keyboard.press('F2')
await page.keyboard.type('Lump sum')
await sleep(200)
await page.keyboard.press('Enter')
await sleep(300)
check('a unit nobody listed can be typed and kept', (await cellOf(2)) === 'Lump sum', await cellOf(2))

// Clicking inside the box while editing must not throw the edit away
await clickCell(page, 0, 0, 1)
await page.keyboard.press('F2')
await page.keyboard.type(' (upper floors)')
const box = await page.evaluate(() => { const r = document.querySelector('[data-cell-editor] input').getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 } })
await page.mouse.click(box.x, box.y)
await sleep(200)
check('clicking inside the cell being edited keeps the edit open', (await page.$('[data-cell-editor] input')) !== null)
await page.keyboard.press('Enter')
await done()
