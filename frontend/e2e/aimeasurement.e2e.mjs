// The AI on the measurement book and on contractor papers. With no key the plain checks still answer, and a reader says plainly it cannot read.
import { api, approvedOrder, clickText, launch, measure, open, signIn, sleep } from './lib.mjs'

const { page, check, done } = await launch({ allow: [/503/] })
await signIn(page)
const order = await approvedOrder(page, { subject: 'E2E AI measurement' })
await measure(page, order.id, order.items[0].item_id, 100)
const text = (sel) => page.$eval(sel, (e) => e.textContent.replace(/\s+/g, ' '))

await open(page, `/subcontractors/measurement-book?order=${order.id}`)
await page.waitForFunction(() => /Analyse the book/.test(document.querySelector('main')?.textContent ?? ''))
await clickText(page, 'main button', 'Analyse the book')
await page.waitForSelector('[aria-label="Measurement analysis"]')
check('the analysis answers from the book without a key', /of the order.s value measured/.test(await text('[aria-label="Measurement analysis"]')))

// An entry the plain checks find odd is marked in the table, with no AI and no cost.
await api(page, 'POST', `/api/sub-mb/${order.id}/entries`, { item_id: order.items[0].item_id, quantity: 2, measured_on: '2099-01-01', location: 'Far block' })
await open(page, `/subcontractors/measurement-book?order=${order.id}`)
await page.waitForSelector('[aria-label^="Check this entry"]', { timeout: 15000 })
check('an entry dated in the future is marked in the entries table', /future/.test(await page.$eval('[aria-label^="Check this entry"]', (e) => e.getAttribute('aria-label'))))

// A question to the book answers plainly when there is no key.
await page.type('input[aria-label="Ask about this book"]', 'Which items are behind?')
await clickText(page, 'main button', 'Ask')
await page.waitForSelector('[aria-label="Answer"]')
check('asking without a key says it is not set up', /not set up|switched off/.test(await page.$eval('[aria-label="Answer"]', (e) => e.textContent)))

await clickText(page, 'main button', 'Read a sheet')
await page.waitForSelector('[role=dialog] textarea')
await page.type('[role=dialog] textarea', 'Footing 4 cum')
await clickText(page, '[role=dialog] button', 'Read it')
await page.waitForFunction(() => /not set up|AI is/.test(document.querySelector('[role=dialog]')?.textContent ?? ''))
check('the sheet reader says plainly it is not set up and adds nothing', /not set up|switched off/.test(await text('[role=dialog]')))
await sleep(200)
await done()
