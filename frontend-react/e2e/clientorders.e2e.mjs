import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { api, clickCell, clickText, fill, launch, open, signIn, sleep, toastsGone, waitForToast } from './lib.mjs'

// Clients > Client Work Orders: build one from the item master, budget it, place it, buy its material.
const { page, check, done } = await launch({ allow: [/409 POST \/api\/erp/, /400 POST \/api\/erp/] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const made = (await api(page, 'POST', '/api/erp/items/bulk', { items: [
  { kind: 'FG', item_name: `E2E Panel ${stamp}`, units_of_measure: 'Nos', item_type: 'Service' },
  { kind: 'RM', item_name: `E2E Steel ${stamp}`, units_of_measure: 'Kgs', item_type: 'Purchased' },
] })).data
const [fgCode, rmCode] = made.codes
const jobs = (await api(page, 'GET', '/api/jobs?open_only=true')).data.jobs

await open(page, '/clients/work-orders')
await page.waitForSelector('table[aria-label="Client work orders"]')
const before = await page.$$eval('table[aria-label="Client work orders"] tbody tr', (r) => r.length)
check('the page lists the client work orders, with their figures', before >= 1 && (await page.$eval('main', (e) => e.textContent)).includes('Expected margin'), `${before} rows`)

// --- Build one from codes in the item master -----------------------------------------------------------
await clickText(page, 'button', 'New client work order')
await page.waitForSelector('[role=dialog] [role=grid]')
await page.select('#co-job', String(jobs[0].id))
await fill(page, '#co-ref', `PO/E2E/${stamp}`)
await clickCell(page, 0, 0, 0, '[role=dialog]')
await page.keyboard.type(`E2E Panel ${stamp}`)
await page.keyboard.press('Enter')
await sleep(200)
await clickCell(page, 0, 0, 2, '[role=dialog]')
await page.keyboard.type('10')
await page.keyboard.press('Tab')
await page.keyboard.type('500')
await page.keyboard.press('Enter')
await sleep(300)
const dialogText = () => page.$eval('[role=dialog]', (e) => e.textContent.replace(/\s+/g, ' '))
check('the item comes from the master and the value is worked out live', (await dialogText()).includes(fgCode) && (await dialogText()).includes('5,000'), (await dialogText()).slice(0, 160))
await clickText(page, 'button', 'Create the order')
await waitForToast(page, 'created')
await page.waitForFunction(() => document.querySelector('[role=dialog]')?.textContent.includes('Budget - WO-'), { timeout: 10000 })
check('the budget is offered straight after, while the order is in front of you', true)

// --- Budget it -----------------------------------------------------------------------------------------------------
await toastsGone(page)
await clickCell(page, 0, 0, 0, '[role=dialog]')
await page.keyboard.type(`E2E Panel ${stamp}`)
await page.keyboard.press('Enter')
await sleep(200)
await clickCell(page, 0, 0, 1, '[role=dialog]')
await page.keyboard.type(`E2E Steel ${stamp}`)
await page.keyboard.press('Enter')
await sleep(200)
await clickCell(page, 0, 0, 2, '[role=dialog]')
await page.keyboard.type('40')
await page.keyboard.press('Tab')
await page.keyboard.type('50')
await page.keyboard.press('Enter')
await sleep(300)
const b = await dialogText()
check('the margin is shown as the budget is typed (5,000 less 2,000 = 3,000, 60%)', b.includes('3,000') && b.includes('60%'), b.slice(-200))
await clickText(page, 'button', 'Save the budget')
await waitForToast(page, 'Budget saved')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))

// --- Place it, then buy what it needs -----------------------------------------------------------------------------
const list = (await api(page, 'GET', '/api/erp/work-orders')).data.work_orders
const mine = list.find((w) => w.reference === `PO/E2E/${stamp}`)
check('the order was created against that job with its reference', !!mine && mine.job_id === jobs[0].id && mine.budgeted, JSON.stringify(mine)?.slice(0, 120))
const row = `table[aria-label="Client work orders"] tbody tr:has(.font-mono)`
await fill(page, 'input[aria-label="Search"]', mine.number)
await sleep(400)
const rowText = () => page.$eval(row, (e) => e.textContent.replace(/\s+/g, ' '))
check('its margin shows on the list', (await rowText()).includes('3,000') && (await rowText()).includes('60%'), await rowText())
await clickText(page, 'button', 'Place order')
await waitForToast(page, mine.number)
await sleep(800)
const placed = (await api(page, 'GET', `/api/erp/work-orders/${mine.id}`)).data
check('placing it sends it on its way (approved by the owner, or waiting on the next signature)', ['approved', 'pending'].includes(placed.approval_status), placed.approval_status)
if (placed.approval_status === 'pending') await clickText(page, 'button', 'Approve')
await toastsGone(page)
await sleep(800)
check('once approved it offers Measure and Material', (await rowText()).includes('Measure') && (await rowText()).includes('Material'), await rowText())

await clickText(page, 'button', 'Material')
await page.waitForFunction(() => document.querySelector('[role=dialog]')?.textContent.includes('still to buy'), { timeout: 10000 })
check('the material still to buy is listed from the budget', (await dialogText()).includes(rmCode) && (await dialogText()).includes('40'), (await dialogText()).slice(0, 200))
await fill(page, '#rq-supplier', 'E2E Steel Traders')
await clickText(page, 'button', 'Raise the purchase order')
await waitForToast(page, 'E2E Steel Traders')
check('a purchase order is raised as a draft for that supplier', true)
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
await toastsGone(page)

// --- The order in full ------------------------------------------------------------------------------------------------------
await page.click(`${row} td:nth-child(2)`)
await page.waitForSelector('[role=dialog]')
const d = await dialogText()
check('clicking a row opens what was sold, the budget and the margin', d.includes(fgCode) && d.includes(rmCode) && d.includes('margin 60%'), d.slice(0, 200))
await page.keyboard.press('Escape')
await page.waitForFunction(() => !document.querySelector('[role=dialog]'))

// --- From a file ------------------------------------------------------------------------------------------------------------------
const bytes = await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/api/erp/work-orders/template', { credentials: 'include' })).arrayBuffer())))
const sheet = join(tmpdir(), 'e2e-client-order.xlsx')
writeFileSync(sheet, Buffer.from(bytes))
await clickText(page, 'button', 'From a file')
await page.waitForSelector('[role=dialog] input[type=file]')
await (await page.$('[role=dialog] input[type=file]')).uploadFile(sheet)
await clickText(page, 'button', 'Check the sheet')
await page.waitForFunction(() => /error\(s\)|Validated/.test(document.querySelector('[role=dialog]')?.textContent || ''), { timeout: 10000 })
check('a sheet is checked and what is wrong with it is said line by line', true)

await done()
