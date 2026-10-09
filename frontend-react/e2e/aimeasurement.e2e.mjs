// The AI on the measurement book and on contractor papers. With no key the plain checks still answer, and a reader says plainly it cannot read.
import { approvedOrder, clickText, launch, measure, open, signIn, sleep } from './lib.mjs'

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

await clickText(page, 'main button', 'Read a sheet')
await page.waitForSelector('[role=dialog] textarea')
await page.type('[role=dialog] textarea', 'Footing 4 cum')
await clickText(page, '[role=dialog] button', 'Read it')
await page.waitForFunction(() => /not set up|AI is/.test(document.querySelector('[role=dialog]')?.textContent ?? ''))
check('the sheet reader says plainly it is not set up and adds nothing', /not set up|switched off/.test(await text('[role=dialog]')))
await sleep(200)
await done()
