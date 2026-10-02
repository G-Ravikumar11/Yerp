import { api, approvedOrder, clickText, launch, open, signIn, sleep } from './lib.mjs'

// The owner decides who else sees an order.
const { page, check, done } = await launch({ allow: [] })
await signIn(page)
const o = await approvedOrder(page, { subject: 'Share me' })
await open(page, `/subcontractors/work-orders/${o.id}`)
await clickText(page, 'main button', 'Who can see it')
await page.waitForSelector('[role=dialog]')
await page.waitForFunction(() => /Tick anyone/.test(document.querySelector('[role=dialog]')?.textContent || '') && !document.querySelector('[role=dialog] [class*=animate-pulse]'), { timeout: 8000 })
const people = (await api(page, 'GET', `/api/wo/orders/${o.id}/access`)).data.people
check('the owner is offered the staff', Array.isArray(people))
if (people.length) {
  const first = await page.$('[role=dialog] input[type=checkbox]:not([disabled])')
  if (first) await first.click()
  await clickText(page, '[role=dialog] button', 'Save')
  await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
  await sleep(300)
  const after = (await api(page, 'GET', `/api/wo/orders/${o.id}/access`)).data.people
  check('ticking someone shares the order with them', after.filter((p) => p.shared).length === 1)
} else {
  check('with no other staff it says so', /no other staff/.test(await page.$eval('[role=dialog]', (e) => e.textContent)))
}
await done()
